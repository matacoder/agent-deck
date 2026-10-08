import base64
import hashlib
import http.client
import json
import socket
import threading
from urllib.parse import urlencode
from unittest.mock import Mock, patch

from support import PanelCase, require_crypto


class HTTPTests(PanelCase):
    def setUp(self):
        super().setUp()
        self.panel.list_sessions = Mock(return_value=[])
        self.enterContext(patch.object(self.panel.Handler, "log_message"))
        self.server = self.panel.ThreadingHTTPServer(("127.0.0.1", 0), self.panel.Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            defaults = {"Content-Type": "application/json"} if method == "POST" and path.startswith("/api/") else {}
            connection.request(method, path, body=body, headers={**defaults, **(headers or {})})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def login(self, headers=None):
        status, response_headers, _ = self.request("POST", "/login", urlencode({
            "username": "test-user", "password": "test-password-only",
        }), {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})})
        self.assertEqual(status, 303)
        return response_headers["Set-Cookie"].split(";", 1)[0]

    def test_legacy_update_without_catalogs_still_serves_ui_and_offers_repair(self):
        cookie = self.login()
        with patch.object(self.panel, 'locales', None):
            status, _, body = self.request('GET', '/', headers={'Cookie':cookie})
            self.assertEqual(status, 200)
            self.assertIn(b'const I18N={"language":"ru","messages":{}};', body)
            self.assertTrue(self.panel.version_info()['incomplete'])

    def test_locales_are_public_and_language_cookie_localizes_login_html_and_errors(self):
        status, _, body = self.request("GET", "/api/locales")
        self.assertEqual(status, 200)
        self.assertEqual({x['code'] for x in json.loads(body)['languages']}, {x['code'] for x in self.panel.locales.available()})
        _, _, body = self.request('GET', '/login', headers={'Cookie': 'cc_lang=en'})
        self.assertIn(b'<html lang="en"', body)
        self.assertIn(b'Password', body)
        self.assertNotIn('Пароль'.encode(), body)
        authenticated = self.login()
        for item in self.panel.locales.available():
            code = item['code']
            with self.subTest(language=code):
                cookie = authenticated + '; cc_lang=' + code
                _, _, body = self.request('GET', '/login', headers={'Cookie': cookie})
                self.assertIn(('<html lang="' + code + '"').encode(), body)
                self.assertIn(self.panel.locales.translate('Пароль', code).encode(), body)
                _, _, body = self.request('GET', '/', headers={'Cookie': cookie})
                self.assertIn(('<h3>' + self.panel.locales.translate('Настройки', code) + '</h3>').encode(), body)
                status, _, body = self.request('POST', '/api/send', '{}', {'Cookie': cookie})
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(body)['error'], self.panel.locales.translate('неверное имя сессии', code))
        cookie = authenticated + '; cc_lang=en'
        _, _, body = self.request('GET', '/', headers={'Cookie': cookie})
        self.assertIn(b'<h3>Settings</h3>', body)
        self.assertNotIn(b'__PANEL_I18N__', body)
        status, _, body = self.request('POST', '/api/send', '{}', {'Cookie': cookie})
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)['error'], 'invalid session name')
        _, _, body = self.request('GET', '/login', headers={'Cookie': 'cc_lang=../../outside'})
        self.assertIn(b'<html lang="en"', body)

    def test_anonymous_html_redirects_and_api_and_terminal_require_login(self):
        status, headers, _ = self.request("GET", "/")
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/login")
        for path in ("/api/sessions", "/api/server-metrics", "/api/ui-version", "/t/?arg=cc-demo"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 401)
        self.panel.list_sessions.assert_not_called()
        self.assertEqual(self.request("POST", "/api/update", "{}")[0], 401)

    def test_question_endpoints_require_login_origin_and_return_json(self):
        self.assertEqual(self.request("GET", "/api/question?name=demo")[0], 401)
        self.assertEqual(self.request("GET", "/api/questions")[0], 401)
        for path in ("/api/backups", "/api/backup_blob?origin=x&created=1"):
            self.assertEqual(self.request("GET", path)[0], 401)
        self.assertEqual(self.request("POST", "/api/backup_restore", "{}")[0], 401)
        cookie = self.login()
        with patch.object(self.panel, "scan_questions", Mock(return_value=[])):
            status, _, body = self.request("GET", "/api/questions", headers={"Cookie": cookie})
            self.assertEqual((status, json.loads(body)), (200, {"questions": []}))
        with patch.object(self.panel, "session_question", Mock(return_value=None)) as lookup:
            status, headers, body = self.request("GET", "/api/question?name=demo", headers={"Cookie": cookie})
            self.assertEqual(status, 200)
            self.assertTrue(headers["Content-Type"].startswith("application/json"))
            self.assertEqual(json.loads(body), {"question": None})
            lookup.assert_called_once_with("demo")
        with patch.dict(self.panel.ACTIONS, {"answer": Mock(return_value=None)}):
            self.assertEqual(self.request("POST", "/api/answer", '{"name":"demo","id":"x","index":0}',
                                          {"Cookie": cookie, "Origin": "http://sibling.test"})[0], 403)
            self.panel.ACTIONS["answer"].assert_not_called()

    def test_backup_lifecycle_over_http_restores_from_a_downloaded_file(self):
        require_crypto(self)
        cookie = self.login()
        post = lambda path, body: self.request("POST", path, json.dumps(body), {"Cookie": cookie})
        kimi = self.home / ".config/cc-panel/kimi.json"
        kimi.write_text('{"key":"original"}')
        status, _, body = post("/api/backup_setup", {})
        code = json.loads(body)["code"]
        self.assertEqual(status, 200)
        self.assertEqual(post("/api/backup_setup", {})[0], 400)
        self.assertEqual(post("/api/backup_run", {})[0], 200)
        _, _, body = self.request("GET", "/api/backups", headers={"Cookie": cookie})
        state = json.loads(body)
        self.assertNotIn(code, body.decode())
        [meta] = state["stored"]
        _, headers, body = self.request("GET", f"/api/backup_blob?origin={meta['origin']}&created={meta['created']}",
                                        headers={"Cookie": cookie})
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        blob = json.loads(body)["blob"]
        self.assertNotIn(b"original", base64.b64decode(blob))
        kimi.write_text('{"key":"changed"}')
        self.panel.backup_service().key_path.unlink()
        with patch.object(self.panel, "restart_soon") as restart:
            self.assertEqual(post("/api/backup_restore", {"blob": blob})[0], 400)
            status, _, body = post("/api/backup_restore", {"blob": blob, "code": code})
            self.assertEqual(status, 200, body)
            restart.assert_called_once()
        self.assertEqual(kimi.read_text(), '{"key":"original"}')
        self.assertEqual(self.request("GET", "/api/backup_blob?origin=../x&created=1", headers={"Cookie": cookie})[0], 404)

    def test_update_rejects_cross_origin_and_non_json_requests(self):
        cookie = self.login()
        with patch.dict(self.panel.ACTIONS, {"update": Mock(return_value={"job": {"phase": "checking"}})}):
            for headers in ({"Content-Type": "text/plain"}, {"Content-Type": "application/json", "Origin": "https://evil.example.com"}):
                with self.subTest(headers=headers):
                    self.assertEqual(self.request("POST", "/api/update", "{}", {"Cookie": cookie, **headers})[0], 403)
            self.panel.ACTIONS["update"].assert_not_called()
            status, _, body = self.request("POST", "/api/update", "{}", {"Cookie": cookie, "Content-Type": "application/json"})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["job"]["phase"], "checking")

    def test_all_mutations_login_logout_and_websocket_reject_sibling_origins(self):
        cookie = self.login()
        host = f"{self.server.server_address[0]}:{self.server.server_address[1]}"
        for origin in ("http://sibling.test", "https://" + host, "null", "http://" + host + "/bad"):
            with self.subTest(origin=origin):
                headers = {"Cookie": cookie, "Origin": origin}
                self.assertEqual(self.request("POST", "/api/send", "{}", headers)[0], 403)
                self.assertEqual(self.request("POST", "/login", "", headers)[0], 403)
                self.assertEqual(self.request("POST", "/logout", "", headers)[0], 403)
                self.assertEqual(self.request("GET", "/t/", headers={**headers, "Upgrade": "websocket"})[0], 403)
        self.assertEqual(self.request("GET", "/t/", headers={"Cookie": cookie, "Upgrade": "websocket",
                                                             "Sec-Fetch-Site": "cross-site"})[0], 403)
        # Safari omits Origin on same-origin WebSocket handshakes: no Origin must pass the origin
        # check (ttyd's own -O re-checks), so the request reaches the proxy and fails only on the
        # missing test backend with 502, not on a 403.
        self.assertEqual(self.request("GET", "/t/", headers={"Cookie": cookie, "Upgrade": "websocket"})[0], 502)
        self.assertEqual(self.request("POST", "/api/send", "{}", {"Cookie": cookie, "Sec-Fetch-Site": "same-site"})[0], 403)
        self.panel.tmux.assert_not_called()

    def test_unexpected_errors_and_invalid_lengths_return_json_and_close_connection(self):
        cookie = self.login()
        for path in ("/api/send", "/login"):
            status, _, body = self.request("POST", path, headers={"Cookie": cookie, "Content-Length": "invalid"})
            self.assertEqual(status, 400)
            self.assertIn("error", json.loads(body))
        with patch.dict(self.panel.ACTIONS, {"send": Mock(side_effect=OSError("private diagnostic"))}):
            status, _, body = self.request("POST", "/api/send", "{}", {"Cookie": cookie})
            self.assertEqual(status, 500)
            self.assertNotIn("private diagnostic", body.decode())
            self.assertIn("error", json.loads(body))
        self.panel.list_sessions.side_effect = OSError("private diagnostic")
        self.assertEqual(self.request("GET", "/api/sessions", headers={"Cookie": cookie})[0], 500)
        self.assertEqual(self.panel.actions_in_progress, 0)

    def test_unread_or_unframed_bodies_cannot_smuggle_a_second_request(self):
        cookie = self.login()
        smuggled = b"GET /api/version HTTP/1.1\r\nHost: x\r\n\r\n"
        for head, code in ((b"POST /api/nope HTTP/1.1\r\nCookie: " + cookie.encode() + b"\r\n", b"404"),
                           (b"POST /api/send HTTP/1.1\r\n", b"401"),
                           (b"POST /api/send HTTP/1.1\r\nTransfer-Encoding: chunked\r\n", b"411")):
            with self.subTest(code=code), socket.create_connection(self.server.server_address, timeout=5) as client:
                length = b"" if code == b"411" else b"Content-Length: %d\r\n" % len(smuggled)
                client.sendall(head + b"Host: x\r\n" + length + b"\r\n" + smuggled)
                received = b""
                while chunk := client.recv(65536):
                    received += chunk
                self.assertTrue(received.startswith(b"HTTP/1.1 " + code))
                self.assertEqual(received.count(b"HTTP/1.1 "), 1)
                self.assertIn(b"application/json", received)

    def test_delayed_parallel_login_bodies_reserve_the_limit_before_password_check(self):
        clients = []
        host = f"{self.server.server_address[0]}:{self.server.server_address[1]}"
        body = b"username=test-user&password=wrong"
        import time
        with patch.object(self.panel.time, "sleep"), patch.object(self.panel.hmac, "compare_digest", wraps=self.panel.hmac.compare_digest) as compare:
            try:
                for _ in range(5):
                    client = socket.create_connection(self.server.server_address, timeout=5)
                    clients.append(client)
                    client.sendall(f"POST /login HTTP/1.1\r\nHost: {host}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode())
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    with self.panel.login_lock:
                        reserved = self.panel.failed_logins.get("127.0.0.1", (0, 0))[0]
                    if reserved == 5:
                        break
                    threading.Event().wait(0.01)
                self.assertEqual(reserved, 5)
                status, _, response = self.request("POST", "/login", body)
                self.assertEqual(status, 401)
                self.assertIn("Слишком много попыток", response.decode())
                compare.assert_not_called()
                for client in clients:
                    client.sendall(body)
                    self.assertIn(b"401", client.recv(4096))
                self.assertEqual(compare.call_count, 10)
            finally:
                for client in clients:
                    client.close()

    def test_running_update_blocks_mutations_and_inflight_mutation_blocks_update(self):
        cookie = self.login()
        self.panel.updater.write_state(self.panel.UPDATE_STATE, "downloading")
        fd = self.panel.updater.lock(self.panel.UPDATE_STATE)
        try:
            self.assertEqual(self.request("POST", "/api/send", '{"name":"demo","text":"keep"}', {"Cookie": cookie})[0], 503)
            self.panel.tmux.assert_not_called()
        finally:
            import os
            os.close(fd)
        self.panel.actions_in_progress = 1
        status, _, body = self.request("POST", "/api/update", "{}", {"Cookie": cookie, "Content-Type": "application/json"})
        self.assertEqual(status, 400)
        self.assertIn("Дождитесь", json.loads(body)["error"])

    def test_actual_inflight_send_finishes_before_update_can_start(self):
        cookie = self.login()
        entered, release = threading.Event(), threading.Event()
        results = []

        def send(data):
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test send timed out")

        with patch.dict(self.panel.ACTIONS, {"send": send}):
            thread = threading.Thread(target=lambda: results.append(self.request("POST", "/api/send", '{}', {"Cookie": cookie})))
            thread.start()
            try:
                self.assertTrue(entered.wait(timeout=5))
                status, _, body = self.request("POST", "/api/update", '{}', {"Cookie": cookie, "Content-Type": "application/json"})
                self.assertEqual(status, 400)
                self.assertIn("Дождитесь", json.loads(body)["error"])
            finally:
                release.set()
                thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0][0], 200)
        self.assertEqual(self.panel.actions_in_progress, 0)

    def test_real_login_cookie_allows_requests_and_logout_revokes_browser_cookie(self):
        cookie = self.login()
        status, headers, body = self.request("GET", "/api/sessions", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"sessions": []})
        self.assertEqual(headers["Cache-Control"], "no-store")
        status, headers, _ = self.request("POST", "/logout", headers={"Cookie": cookie})
        self.assertEqual(status, 303)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])

    def test_login_over_trusted_https_proxy_sets_secure_cookie(self):
        status, headers, _ = self.request("POST", "/login", urlencode({
            "username": "test-user", "password": "test-password-only",
        }), {"X-Forwarded-Proto": "https"})
        self.assertEqual(status, 303)
        for flag in ("HttpOnly", "SameSite=Lax", "Secure"):
            self.assertIn(flag, headers["Set-Cookie"])

    def test_bad_password_is_throttled_by_real_proxy_client_ip(self):
        with patch.object(self.panel.time, "sleep"):
            for _ in range(5):
                status, _, _ = self.request("POST", "/login", "username=test-user&password=wrong",
                                           {"X-Forwarded-For": "203.0.113.20"})
                self.assertEqual(status, 401)
            status, _, body = self.request("POST", "/login", "username=test-user&password=wrong",
                                           {"X-Forwarded-For": "203.0.113.20"})
        self.assertEqual(status, 401)
        self.assertIn("Слишком много попыток", body.decode())
        self.assertIn("203.0.113.20", self.panel.failed_logins)
        self.login({"X-Forwarded-For": "203.0.113.21"})

    def test_page_embeds_same_revision_as_version_endpoint(self):
        cookie = self.login()
        _, _, body = self.request("GET", "/", headers={"Cookie": cookie})
        _, _, version = self.request("GET", "/api/ui-version", headers={"Cookie": cookie})
        revision = json.loads(version)["revision"]
        with open(self.panel.PAGE_FILE, "rb") as f:
            self.assertEqual(revision, hashlib.sha256(f.read()).hexdigest())
        self.assertIn(revision.encode(), body)
        self.assertNotIn(b"__PANEL_REVISION__", body)

    def test_bad_json_unknown_actions_and_oversized_requests(self):
        cookie = self.login()
        for body in ("{", "[]", '"text"'):
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/send", body, {"Cookie": cookie})[0], 400)
        self.assertEqual(self.request("POST", "/api/unknown", "{}", {"Cookie": cookie})[0], 404)
        for path, length in (("/api/send", 1_000_001), ("/api/upload", ((self.panel.MAX_FILE_BYTES + 2) // 3) * 4 + 10_001)):
            with self.subTest(path=path):
                status, _, _ = self.request("POST", path, headers={"Cookie": cookie, "Content-Length": str(length)})
                self.assertEqual(status, 413)

    def test_upload_returns_attachment_identifier_then_send_uses_it(self):
        import base64
        from support import PNG
        self.allow_session()
        cookie = self.login()
        status, _, body = self.request("POST", "/api/upload", json.dumps({
            "name": "demo", "data": base64.b64encode(PNG).decode(),
        }), {"Cookie": cookie})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertRegex(data["attachment"], r"^[a-f0-9]{32}\.png$")
        status, _, _ = self.request("POST", "/api/send", json.dumps({
            "name": "demo", "text": "", "attachments": [data["attachment"]],
        }), {"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.pasted), 2)
        self.assertIn("через 7 дней", self.pasted[-1])
        self.assertEqual(self.panel.tmux.call_args_list[-1].args[-1], "Enter")

    def test_raw_upload_streams_to_disk_privately_and_keeps_upload_rules(self):
        from support import PNG
        self.allow_session()
        cookie = self.login()
        raw = {"Cookie": cookie, "Content-Type": "application/octet-stream"}
        status, _, body = self.request("POST", "/api/upload_raw?name=demo&filename=shot.png", PNG, raw)
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        self.assertRegex(data["attachment"], r"^[a-f0-9]{32}\.png$")
        stored = self.home / ".config/cc-panel/uploads/demo" / data["attachment"]
        self.assertEqual(stored.read_bytes(), PNG)
        self.assertEqual(stored.stat().st_mode & 0o777, 0o600)
        self.assertEqual([p.name for p in stored.parent.iterdir() if p.name.startswith(".incoming")], [])
        status, _, body = self.request("POST", "/api/upload_raw?name=demo&filename=notes.zip", b"PK\x03\x04zip", raw)
        self.assertRegex(json.loads(body)["attachment"], r"^[a-f0-9]{32}--notes\.zip$")
        for headers in ({**raw, "Origin": "http://sibling.test"}, {**raw, "Content-Type": "text/plain"},
                        {**raw, "Content-Type": "application/json"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("POST", "/api/upload_raw?name=demo&filename=a.png", PNG, headers)[0], 403)
        self.assertEqual(self.request("POST", "/api/upload_raw?name=demo&filename=a/b.png", PNG, raw)[0], 400)
        self.assertEqual(self.request("POST", "/api/upload_raw?name=demo&filename=a.png", b"", raw)[0], 413)
        with patch.object(self.panel, "MAX_FILE_BYTES", 4):
            self.assertEqual(self.request("POST", "/api/upload_raw?name=demo&filename=a.png", PNG, raw)[0], 413)
        self.panel.opt = Mock(return_value="shell")
        self.assertEqual(self.request("POST", "/api/upload_raw?name=demo&filename=a.png", PNG, raw)[0], 400)

    def test_zip_upload_then_send_passes_file_path_and_retention_notice(self):
        import base64
        self.allow_session()
        cookie = self.login()
        content = b"PK\x03\x04\x00\xff"
        status, _, body = self.request("POST", "/api/upload", json.dumps({
            "name": "demo", "filename": "archive.zip", "data": base64.b64encode(content).decode(),
        }), {"Cookie": cookie})
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["kind"], "file")
        status, _, _ = self.request("POST", "/api/send", json.dumps({
            "name": "demo", "attachments": [data["attachment"]],
        }), {"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.pasted), 1)
        self.assertIn("archive.zip", self.pasted[0])
        self.assertIn("через 7 дней", self.pasted[0])

    def test_missing_ttyd_returns_bad_gateway(self):
        status, _, body = self.request("GET", "/t/?arg=cc-demo", headers={"Cookie": self.login()})
        self.assertEqual(status, 502)
        self.assertIn("ttyd unavailable", json.loads(body)["error"])

    def test_pages_and_the_terminal_refuse_foreign_frames(self):
        status, headers, _ = self.request("GET", "/login")
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(headers["Content-Security-Policy"], "frame-ancestors 'self'")
        head = self.panel.with_frame_headers(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<html>")
        self.assertTrue(head.startswith(b"HTTP/1.1 200 OK\r\nX-Frame-Options: SAMEORIGIN\r\n"))
        self.assertTrue(head.endswith(b"Content-Type: text/html\r\n\r\n<html>"))

    def test_terminal_link_with_extra_tmux_arguments_is_refused(self):
        # ttyd -a appends every arg to `tmux attach -t`; a bare `;` would chain run-shell.
        cookie = self.login()
        for path in ("/t/?arg=_keep&arg=%3B&arg=run-shell&arg=touch%20x", "/t/ws?arg=cc-demo&arg=%3B",
                     "/t/?arg=-x", "/t/?arg=cc-demo%3Brun-shell", "/t/?cmd=cc-demo"):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path, headers={"Cookie": cookie})
                self.assertEqual(status, 400)
                self.assertIn("error", json.loads(body))

    def test_websocket_upgrade_and_bytes_are_proxied_to_isolated_unix_socket(self):
        self.assert_websocket_proxy()

    def test_secure_websocket_through_traefik_accepts_https_origin(self):
        self.assert_websocket_proxy(forwarded=True)

    def assert_websocket_proxy(self, forwarded=False):
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(self.panel.TTYD_SOCK)
        listener.listen(1)
        listener.settimeout(5)
        self.addCleanup(listener.close)
        captured = []
        def read_exact(connection, length):
            result = b""
            while len(result) < length:
                chunk = connection.recv(length - len(result))
                if not chunk:
                    raise AssertionError("proxy closed before all bytes arrived")
                result += chunk
            return result

        def backend():
            with listener.accept()[0] as connection:
                connection.settimeout(5)
                request = b""
                while b"\r\n\r\n" not in request:
                    chunk = connection.recv(4096)
                    if not chunk:
                        raise AssertionError("proxy closed before the request headers arrived")
                    request += chunk
                captured.append(request)
                connection.sendall(b"HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n")
                captured.append(read_exact(connection, 4))
                connection.sendall(b"pong")
        thread = threading.Thread(target=backend, daemon=True)
        thread.start()
        cookie = self.login()
        with socket.create_connection(self.server.server_address, timeout=5) as client:
            host = f"{self.server.server_address[0]}:{self.server.server_address[1]}"
            scheme = "https" if forwarded else "http"
            proxy_header = "X-Forwarded-Proto: wss\r\n" if forwarded else ""
            client.sendall((f"GET /t/ws?arg=cc-demo HTTP/1.1\r\nHost: {host}\r\nOrigin: {scheme}://{host}\r\n{proxy_header}Connection: Upgrade\r\n"
                            "Upgrade: websocket\r\nCookie: " + cookie + "\r\n\r\n").encode())
            response = b""
            while b"\r\n\r\n" not in response:
                chunk = client.recv(4096)
                self.assertTrue(chunk, "proxy closed before the upgrade response arrived")
                response += chunk
            self.assertIn(b"101 Switching Protocols", response)
            client.sendall(b"ping")
            self.assertEqual(read_exact(client, 4), b"pong")
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertIn(b"Upgrade: websocket", captured[0])
        self.assertEqual(captured[1], b"ping")


    def test_kimi_key_requires_login_and_same_origin_and_never_returns_secret(self):
        key = 'sk-private-test-123456789'
        body = json.dumps({'key': key, 'model': 'k3'})
        self.assertEqual(self.request('POST', '/api/kimi_config', body)[0], 401)
        cookie = self.login()
        self.assertEqual(self.request('POST', '/api/kimi_config', body,
                         {'Cookie': cookie, 'Origin': 'https://evil.example'})[0], 403)
        status, _, response = self.request('POST', '/api/kimi_config', body, {'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertNotIn(key.encode(), response)
        with patch.object(self.panel, 'agent_status', return_value={'installed': True}):
            status, _, response = self.request('GET', '/api/agents', headers={'Cookie': cookie})
        self.assertEqual(status, 200)
        self.assertNotIn(key.encode(), response)
        self.assertTrue(json.loads(response)['kimi_config']['configured'])


class ProxyTrustTests(PanelCase):
    def handler(self, address, headers):
        handler = self.panel.Handler.__new__(self.panel.Handler)
        handler.client_address = (address, 1234)
        handler.headers = headers
        return handler

    def test_untrusted_client_cannot_spoof_ip_or_https(self):
        handler = self.handler("203.0.113.1", {"X-Forwarded-For": "1.1.1.1", "X-Forwarded-Proto": "https"})
        self.assertEqual(handler.client_ip(), "203.0.113.1")
        self.assertFalse(handler.is_https())

    def test_idle_timeout_is_not_logged_and_needs_no_headers(self):
        handler = self.panel.Handler.__new__(self.panel.Handler)
        handler.client_address = ("172.18.0.2", 1234)
        with patch("builtins.print") as printed:
            handler.log_error("Request timed out: %r", TimeoutError("timed out"))
            printed.assert_not_called()
            handler.log_error("code %d, message %s", 400, "Bad request")
        self.assertIn("172.18.0.2 code 400", printed.call_args.args[0])

    def test_trusted_proxy_uses_rightmost_ip_and_https(self):
        handler = self.handler("172.18.0.2", {"X-Forwarded-For": "spoof, 203.0.113.2", "X-Forwarded-Proto": "https"})
        self.assertEqual(handler.client_ip(), "203.0.113.2")
        self.assertTrue(handler.is_https())

    def test_wss_requires_trusted_proxy_and_matching_https_origin(self):
        for address, origin, expected in (("172.18.0.2", "https://panel.test", True),
                                           ("172.18.0.2", "https://other.test", False),
                                           ("172.18.0.2", "http://panel.test", False),
                                           ("203.0.113.1", "https://panel.test", False)):
            with self.subTest(address=address, origin=origin):
                handler = self.handler(address, {"Host": "panel.test", "Origin": origin,
                                                 "X-Forwarded-Proto": "wss"})
                self.assertEqual(handler.same_origin(), expected)
