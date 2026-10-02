import hashlib
import http.client
import json
import socket
import threading
from urllib.parse import urlencode
from unittest.mock import Mock, patch

from support import PanelCase


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
            connection.request(method, path, body=body, headers=headers or {})
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

    def test_anonymous_html_redirects_and_api_and_terminal_require_login(self):
        status, headers, _ = self.request("GET", "/")
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/login")
        for path in ("/api/sessions", "/api/ui-version", "/t/?arg=cc-demo"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 401)
        self.panel.list_sessions.assert_not_called()

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
        for path, length in (("/api/send", 1_000_001), ("/api/upload", 12 * 1024 * 1024 + 1)):
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
        self.assertEqual(self.panel.tmux.call_count, 2)

    def test_missing_ttyd_returns_bad_gateway(self):
        status, _, body = self.request("GET", "/t/?arg=cc-demo", headers={"Cookie": self.login()})
        self.assertEqual(status, 502)
        self.assertIn("ttyd unavailable", json.loads(body)["error"])

    def test_websocket_upgrade_and_bytes_are_proxied_to_isolated_unix_socket(self):
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
            client.sendall(("GET /t/?arg=cc-demo HTTP/1.1\r\nHost: test\r\nConnection: Upgrade\r\n"
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

    def test_trusted_proxy_uses_rightmost_ip_and_https(self):
        handler = self.handler("172.18.0.2", {"X-Forwarded-For": "spoof, 203.0.113.2", "X-Forwarded-Proto": "https"})
        self.assertEqual(handler.client_ip(), "203.0.113.2")
        self.assertTrue(handler.is_https())
