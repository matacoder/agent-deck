import json
import base64
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

from support import PanelCase, PNG


class AuthenticationTests(PanelCase):
    def test_token_round_trip_tampering_expiry_and_password_change(self):
        with patch.object(self.panel.time, "time", return_value=100):
            token = self.panel.make_token()
            self.assertTrue(self.panel.token_valid(token))
            self.assertFalse(self.panel.token_valid(token + "x"))
            # A non-ASCII cookie (latin-1 bytes) is a refusal, not a TypeError from compare_digest.
            for invalid in (None, "", "garbage", "100.bad", "x.signature", token.split(".")[0] + ".\xe9" * 64):
                self.assertFalse(self.panel.token_valid(invalid))
        with patch.object(self.panel.time, "time", return_value=100 + 91 * 86400):
            self.assertFalse(self.panel.token_valid(token))
        self.panel.PANEL_PASSWORD = "changed-test-password"
        self.panel.COOKIE_KEY = self.panel._cookie_key()
        self.assertFalse(self.panel.token_valid(token))


class AttachmentTests(PanelCase):
    def setUp(self):
        super().setUp()
        self.allow_session()

    def test_upload_detects_format_and_saves_private_exact_bytes(self):
        for image, extension in ((PNG, "png"), (b"\xff\xd8\xffjpeg", "jpg"),
                                 (b"GIF89agif", "gif"), (b"RIFF1234WEBPdata", "webp")):
            with self.subTest(extension=extension):
                attachment = self.upload(image=image)
                path = Path(self.panel.UPLOAD_DIR) / "demo" / attachment
                self.assertEqual(path.suffix, "." + extension)
                self.assertEqual(path.read_bytes(), image)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_upload_rejects_invalid_empty_oversized_and_non_image_data(self):
        self.panel.MAX_IMAGE_BYTES = 32
        for data in ("%%%", "", base64.b64encode(b"not an image").decode(),
                     base64.b64encode(PNG * 4).decode(), []):
            with self.subTest(data=str(data)[:20]), self.assertRaises(ValueError):
                self.panel.action_upload({"name": "demo", "data": data})

    def test_zip_and_arbitrary_files_keep_bytes_names_and_are_sent_as_paths(self):
        for filename, content in (("archive.zip", b"PK\x03\x04zip data"), ("notes.txt", b"hello"),
                                  ("empty.txt", b""), ("unknown", b"\x00\xff"), ("fake.png", b"not an image")):
            with self.subTest(filename=filename):
                result = self.panel.action_upload({"name": "demo", "filename": filename,
                                                  "data": base64.b64encode(content).decode()})
                self.assertEqual(result["kind"], "file")
                path = self.panel.attachment_paths("demo", [result["attachment"]])[0]
                self.assertEqual(Path(path).read_bytes(), content)
                self.assertTrue(path.endswith("--" + filename))
                self.pasted.clear()
                self.panel.action_send({"name": "demo", "attachments": [result["attachment"]]})
                self.assertEqual(len(self.pasted), 1)
                self.assertIn(path, self.pasted[0])
                self.assertIn("через 7 дней", self.pasted[0])
                self.assertIn("в проекте", self.pasted[0])
                import os
                os.utime(path, (0, 0))
                self.panel.cleanup_uploads()
                self.assertFalse(Path(path).exists())

    def test_partial_uploads_left_by_a_restart_are_removed_after_an_hour(self):
        import os, time
        folder = Path(self.panel.UPLOAD_DIR) / "demo"; folder.mkdir(parents=True, exist_ok=True)
        stale, live = folder / (".incoming-" + "a" * 32), folder / (".incoming-" + "b" * 32)
        stale.write_bytes(b"x"); live.write_bytes(b"x")
        os.utime(stale, (time.time() - 3700,) * 2)
        self.panel.cleanup_uploads()
        self.assertFalse(stale.exists())
        self.assertTrue(live.exists())  # Possibly still streaming.

    def test_file_names_and_size_limits_are_validated(self):
        self.assertEqual(self.panel.MAX_FILE_BYTES, 200 * 1024 * 1024)
        for filename in ("../escape.zip", "path\\evil", "bad\nname", "", [], "x" * 256):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.panel.action_upload({"name": "demo", "filename": filename, "data": "YWJj"})
        self.panel.MAX_FILE_BYTES = 32
        with self.assertRaises(ValueError):
            self.panel.action_upload({"name": "demo", "filename": "big.zip", "data": base64.b64encode(b"x" * 33).decode()})

    def test_file_above_twenty_megabytes_is_preserved(self):
        content = b"x" * (20 * 1024 * 1024 + 1)
        result = self.panel.action_upload({"name": "demo", "filename": "big.zip", "data": base64.b64encode(content).decode()})
        path = self.panel.attachment_paths("demo", [result["attachment"]])[0]
        self.assertEqual(Path(path).read_bytes(), content)

    def test_mixed_image_and_zip_keeps_native_image_and_file_instructions(self):
        image = self.upload()
        archive = self.panel.action_upload({"name": "demo", "filename": "test.zip", "data": "UEsDBA=="})["attachment"]
        paths = self.panel.attachment_paths("demo", [image, archive])
        self.panel.action_send({"name": "demo", "text": "Inspect", "attachments": [image, archive]})
        self.assertEqual(self.pasted[0], "\x1b[200~" + paths[0] + "\x1b[201~")
        self.assertIn(paths[1], self.pasted[1])
        self.assertIn("Inspect", self.pasted[1])

    def test_upload_rejects_missing_session_and_shell(self):
        self.panel.session_exists.return_value = False
        with self.assertRaises(ValueError):
            self.upload()
        self.panel.session_exists.return_value = True
        self.panel.opt.return_value = "shell"
        with self.assertRaises(ValueError):
            self.upload()

    def test_attachments_are_scoped_to_session_and_reject_traversal_and_symlinks(self):
        attachment = self.upload()
        for name, attachments in (("other", [attachment]), ("../escape", [attachment]),
                                  ("demo", ["../" + attachment]), ("demo", [attachment] * 5),
                                  ("demo", "not a list")):
            with self.subTest(name=name, attachments=attachments), self.assertRaises(ValueError):
                self.panel.attachment_paths(name, attachments)
        path = Path(self.panel.UPLOAD_DIR) / "demo" / attachment
        path.unlink()
        path.symlink_to(Path(self.panel.HERE) / "index.html")
        with self.assertRaises(ValueError):
            self.panel.attachment_paths("demo", [attachment])

    def test_codex_gets_image_pastes_then_text_then_one_enter(self):
        attachment = self.upload()
        path = self.panel.attachment_paths("demo", [attachment])[0]
        self.panel.action_send({"name": "demo", "text": "Explain this\nimage", "attachments": [attachment]})
        self.assertEqual(self.pasted, ["\x1b[200~" + path + "\x1b[201~",
                                     "\x1b[200~Explain this\nimage\n\nВложения временные: удаляются с сервера через 7 дней после загрузки. Если они нужны надолго, сохрани их в подходящем месте в проекте.\x1b[201~"])
        self.assertEqual([call.args[-1] for call in self.panel.tmux.call_args_list if call.args[0] == "send-keys"], ["Enter"])

    def test_english_attachment_notice_preserves_user_message_and_paths(self):
        attachment = self.upload()
        self.panel.action_send({'name':'demo','text':'Сообщение пользователя','attachments':[attachment], '_language':'en'})
        self.assertIn('Сообщение пользователя', self.pasted[-1])
        self.assertIn('Attachments are temporary', self.pasted[-1])
        self.assertNotIn('Вложения временные', self.pasted[-1])

    def test_image_only_send_and_claude_paths(self):
        attachment = self.upload()
        self.panel.action_send({"name": "demo", "attachments": [attachment]})
        self.assertEqual(len(self.pasted), 2)
        self.panel.tmux.reset_mock()
        self.panel.opt.return_value = "claude"
        self.panel.action_send({"name": "demo", "text": "Look", "attachments": [attachment]})
        pasted = self.pasted[-1]
        self.assertIn(self.panel.attachment_paths("demo", [attachment])[0], pasted)
        self.assertTrue(pasted.startswith("\x1b[200~Look"))
        self.assertEqual(self.panel.tmux.call_args_list[-1].args[-1], "Enter")

    def test_enter_waits_until_the_agent_finished_attaching_images(self):
        attachment = self.upload()
        self.panel.opt.return_value = "claude"
        screens = iter(["path", "[Image #1]", "[Image #1] Look", "[Image #1] Look", "[Image #1] Look", "[Image #1] Look"])
        def tmux(*args, check=True):
            return next(screens) if args[0] == "capture-pane" else ""
        self.panel.tmux = Mock(side_effect=tmux)
        self.panel.action_send({"name": "demo", "text": "Look", "attachments": [attachment]})
        calls = [call.args[0] for call in self.panel.tmux.call_args_list if call.args[0] in ("capture-pane", "send-keys")]
        # Enter only after three identical captures, never while the prompt is still being redrawn.
        self.assertEqual(calls, ["capture-pane"] * 6 + ["send-keys"])

    def test_invalid_attachment_does_not_type_anything(self):
        with self.assertRaises(ValueError):
            self.panel.action_send({"name": "demo", "text": "Keep", "attachments": ["missing.png"]})
        self.panel.tmux.assert_not_called()

    def test_plain_text_and_special_keys_still_work(self):
        self.panel.action_send({"name": "demo", "text": "hello"})
        self.assertEqual(self.pasted, ["\x1b[200~hello\x1b[201~"])
        self.assertEqual(self.panel.tmux.call_args_list[-1].args[-1], "Enter")
        for key in ("Escape", "Enter", "C-c", "Up", "Down", "Tab", "BTab", "1"):
            self.panel.tmux.reset_mock()
            self.panel.action_send({"name": "demo", "key": key})
            self.assertEqual(self.panel.tmux.call_count, 1)
            self.assertEqual(self.panel.tmux.call_args.args[-1], key)


class SessionTests(PanelCase):
    def test_groups_keep_legacy_projects_and_new_dev_after_directory_change(self):
        with patch.object(self.panel.project_directory, 'get', return_value=str(self.home/'dev')), patch.object(self.panel.os.path, 'expanduser', side_effect=lambda p:str(self.home/p[2:])):
            for folder in ('projects','dev'):
                self.assertEqual(self.panel.session_group(str(self.home/folder/'agent-deck')), 'agent-deck')
                self.assertEqual(self.panel.session_group(str(self.home/folder/'agent-deck.worktrees'/'feature')), 'agent-deck')
            self.assertEqual(self.panel.session_group(str(self.home/'projects-other'/'repo')), 'другое')
        with patch.object(self.panel.project_directory, 'get', return_value=str(self.home/'custom')):
            self.assertEqual(self.panel.session_group(str(self.home/'custom'/'repo'/'src')), 'repo')

    def test_invalid_session_names_are_rejected_before_commands(self):
        self.panel.session_exists = Mock(return_value=False)
        self.panel.create_session = Mock()
        for name in ("", "../escape", "x;touch", "x" * 33, "demo\n", None, 123, []):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.panel.action_new({"name": name})
        self.panel.create_session.assert_not_called()

    def test_capture_keeps_ansi_and_bounds_plain_preview(self):
        capture = "\x1b[31m" + "\n".join(str(i) for i in range(2010)) + "\x1b[0m\n"
        def tmux(command, *args, **kwargs):
            if command == "list-sessions":
                return f"unrelated\t1\t0\t/tmp\tbash\t1\ncc-demo\t1\t0\t{self.panel.PROJECTS}/repo\tcodex\t2\tcodex\t\t0\n"
            self.assertIn("-e", args)
            return capture
        self.panel.tmux = Mock(side_effect=tmux)
        self.panel.opt = Mock(side_effect=lambda name, key: "codex" if key == "@cc_agent" else None)
        sessions = self.panel.list_sessions("demo")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["group"], "repo")
        self.assertEqual(sessions[0]["preview_ansi"], capture)
        self.assertEqual(sessions[0]["preview"].splitlines(), [str(i) for i in range(10, 2010)])

    def test_only_the_previewed_session_reports_its_transcript_model_and_reads_change_only(self):
        sid = "11111111-1111-4111-8111-111111111111"
        folder = self.home / ".claude/projects/-repo"
        folder.mkdir(parents=True)
        path = folder / (sid + ".jsonl")
        path.write_text(json.dumps({"type": "assistant", "message": {"model": "claude-opus-5-5"}}) + "\n")
        line = f"cc-NAME\t1\t0\t/tmp\tclaude\t2\tclaude\t{sid}\t0\t\t\n"
        self.panel.tmux = Mock(side_effect=lambda command, *args, **kwargs: (line.replace("NAME", "demo") + line.replace("NAME", "other")) if command == "list-sessions" else "")
        from integrations import questions
        with patch.object(questions, "transcript_model", wraps=questions.transcript_model) as read:
            sessions = {s["name"]: s for s in self.panel.list_sessions("demo")}
            self.assertEqual(sessions["demo"]["model"], "claude-opus-5-5")
            self.assertNotIn("model", sessions["other"])
            self.panel.list_sessions("demo")
            self.assertEqual(read.call_count, 1)
            with path.open("a") as stream:
                stream.write(json.dumps({"type": "assistant", "message": {"model": "claude-sonnet-5-5"}}) + "\n")
            self.assertEqual(self.panel.list_sessions("demo")[0]["model"], "claude-sonnet-5-5")
        self.assertIsNone(self.panel.session_model("shell", sid))
        self.assertIsNone(self.panel.session_model("claude", "../escape"))

    def test_project_names_and_paths_cannot_escape_home(self):
        for project in ("../escape", "/tmp", "reserved.worktrees", "a..b"):
            with self.subTest(project=project), self.assertRaises(ValueError):
                self.panel.resolve_path({"project": project}, "demo")
        outside = self.enterContext(tempfile.TemporaryDirectory())
        with self.assertRaises(ValueError):
            self.panel.resolve_path({"path": outside}, "demo")
        inside = self.home / "safe"
        inside.mkdir()
        self.assertEqual(self.panel.resolve_path({"path": str(inside)}, "demo"), str(inside))

    def test_restart_after_server_change_restores_only_missing_sessions(self):
        self.panel.tmux_server_pid = Mock(return_value=20)
        self.panel.load_state = Mock(return_value={"server_pid": 10, "sessions": {"kept": {}, "missing": {"path": "x"}}})
        self.panel.live_sessions = Mock(return_value={"kept": {"created": 1, "agent": "codex"}})
        self.panel.restore_session = Mock()
        self.panel.save_state = Mock()
        self.panel.sync_state()
        self.panel.restore_session.assert_called_once_with("missing", {"path": "x"})
        self.assertNotIn("created", self.panel.save_state.call_args.args[0]["sessions"]["kept"])

    def test_atomic_state_round_trip_and_corrupt_state_fallback(self):
        state = {"server_pid": 1, "sessions": {"demo": {"agent": "codex"}}}
        self.panel.save_state(state)
        self.assertEqual(self.panel.load_state(), state)
        self.assertFalse(Path(self.panel.STATE_FILE + ".tmp").exists())
        Path(self.panel.STATE_FILE).write_text("broken json")
        self.assertEqual(self.panel.load_state(), {})


class CacheTests(PanelCase):
    def test_success_is_cached_until_ttl(self):
        fetch = Mock(return_value={"value": 1})
        with patch.object(self.panel.time, "time", return_value=100):
            self.panel.cached("test", 600, fetch)
        with patch.object(self.panel.time, "time", return_value=699):
            self.panel.cached("test", 600, fetch)
        self.assertEqual(fetch.call_count, 1)
        with patch.object(self.panel.time, "time", return_value=701):
            self.panel.cached("test", 600, fetch)
        self.assertEqual(fetch.call_count, 2)

    def test_failure_serves_stale_data_and_retries_after_five_minutes(self):
        fetch = Mock(return_value={"percent": 57})
        with patch.object(self.panel.time, "time", return_value=0):
            self.panel.cached("usage", 3600, fetch)
        fetch.side_effect = RuntimeError("temporarily unavailable")
        with patch.object(self.panel.time, "time", return_value=3601):
            self.assertEqual(self.panel.cached("usage", 3600, fetch), {"percent": 57, "stale": True})
        with patch.object(self.panel.time, "time", return_value=3900):
            self.panel.cached("usage", 3600, fetch)
        self.assertEqual(fetch.call_count, 2)
        fetch.side_effect = None
        fetch.return_value = {"percent": 58}
        with patch.object(self.panel.time, "time", return_value=3902):
            self.assertEqual(self.panel.cached("usage", 3600, fetch), {"percent": 58})

    def test_persisted_usage_survives_restart_and_rate_limited_first_request(self):
        fetch = Mock(return_value={"windows": [{"percent": 33}]})
        with patch.object(self.panel.time, "time", return_value=1000):
            self.panel.cached("usage-claude", 300, fetch, persist=True)
        path = Path(self.panel.usage_store_path())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.panel._cache.clear()  # a panel update restarts the process
        with patch.object(self.panel.time, "time", return_value=1200):
            self.assertEqual(self.panel.cached("usage-claude", 300, fetch, persist=True), {"windows": [{"percent": 33}]})
        self.assertEqual(fetch.call_count, 1)
        self.panel._cache.clear()
        fetch.side_effect = RuntimeError("HTTP Error 429: Too Many Requests")
        with patch.object(self.panel.time, "time", return_value=2000):
            self.assertEqual(self.panel.cached("usage-claude", 300, fetch, persist=True), {"windows": [{"percent": 33}], "stale": True})
        self.assertNotIn("stale", json.loads(path.read_text())["usage-claude"][1])

    def test_rate_limit_backs_off_at_least_thirty_minutes_or_retry_after(self):
        import email.message
        def limited(seconds):
            headers = email.message.Message()
            if seconds is not None:
                headers["Retry-After"] = seconds
            return self.panel.urllib.error.HTTPError("https://api.example/usage", 429, "Too Many Requests", headers, None)
        for retry_after, backoff in ((None, 1800), ("7200", 7200), ("999999", 6 * 3600), ("soon", 1800)):
            with self.subTest(retry_after=retry_after):
                self.panel._cache.clear()
                fetch = Mock(side_effect=limited(retry_after))
                with patch.object(self.panel.time, "time", return_value=10000):
                    self.panel.cached("usage-claude", 600, fetch)
                with patch.object(self.panel.time, "time", return_value=10000 + backoff - 1):
                    self.panel.cached("usage-claude", 600, fetch)
                self.assertEqual(fetch.call_count, 1)
                with patch.object(self.panel.time, "time", return_value=10000 + backoff + 1):
                    self.panel.cached("usage-claude", 600, fetch)
                self.assertEqual(fetch.call_count, 2)

    def test_errors_and_unpersisted_values_are_not_written(self):
        self.panel.cached("usage-claude", 300, Mock(return_value={"error": "token expired"}), persist=True)
        self.panel.cached("usage-kimi-hash", 60, Mock(return_value={"windows": []}))
        self.assertFalse(Path(self.panel.usage_store_path()).exists())

    def test_disabled_release_checks_do_not_use_network(self):
        self.assertEqual(self.panel.version_info()["version"], self.panel.VERSION)
        self.panel.http_json.assert_not_called()


class BindHostTests(PanelCase):
    def test_a_tailscale_address_that_left_this_machine_follows_tailscale(self):
        from types import SimpleNamespace
        run = Mock(return_value=SimpleNamespace(stdout="100.101.102.103\n"))
        self.assertEqual(self.panel.usable_bind_host("127.0.0.1", run), "127.0.0.1")
        run.assert_not_called()  # A working address is never second-guessed.
        self.assertEqual(self.panel.usable_bind_host("100.64.250.250", run), "100.101.102.103")
        self.assertEqual(run.call_args.args[0], ["tailscale", "ip", "-4"])
        # Never re-resolved outside the tailnet range, so exposure cannot widen.
        self.assertEqual(self.panel.usable_bind_host("203.0.113.9", run), "203.0.113.9")
        run.return_value = SimpleNamespace(stdout="0.0.0.0\n")
        self.assertEqual(self.panel.usable_bind_host("100.64.250.250", run), "100.64.250.250")


class TranscriptLookupTests(PanelCase):
    def test_a_missing_transcript_is_not_searched_again_on_every_scan(self):
        self.panel.transcript_paths.clear(); self.panel.transcript_misses.clear()
        self.enterContext(patch.object(self.panel.os.path, 'expanduser', side_effect=lambda p: str(self.home / p[2:])))
        sid = '12345678-1234-1234-1234-123456789abc'
        clock = [1000.0]
        self.enterContext(patch.object(self.panel.time, 'monotonic', side_effect=lambda: clock[0]))
        with patch('pathlib.Path.rglob', return_value=iter(())) as search:
            self.assertIsNone(self.panel.transcript_path('claude', sid))
            self.assertIsNone(self.panel.transcript_path('claude', sid))
            self.assertEqual(search.call_count, 1)
        project = self.home / '.claude/projects/demo'; project.mkdir(parents=True)
        (project / (sid + '.jsonl')).write_text('{}')
        clock[0] += 31
        self.assertEqual(self.panel.transcript_path('claude', sid).name, sid + '.jsonl')


class SingleFlightCacheTests(PanelCase):
    def test_concurrent_misses_share_one_fetch(self):
        import threading
        self.panel._cache.pop('single-flight', None)
        started, release, calls = threading.Event(), threading.Event(), []
        def slow():
            calls.append(1); started.set(); release.wait(5); return {'value': 1}
        results = []
        first = threading.Thread(target=lambda: results.append(self.panel.cached('single-flight', 60, slow)))
        first.start(); self.assertTrue(started.wait(5))
        second = threading.Thread(target=lambda: results.append(self.panel.cached('single-flight', 60, slow)))
        second.start(); release.set(); first.join(5); second.join(5)
        self.assertEqual(len(calls), 1)
        self.assertEqual(results, [{'value': 1}, {'value': 1}])


class FreshReleaseCheckTests(PanelCase):
    def test_network_asks_github_again_but_at_most_once_a_minute(self):
        self.enterContext(patch.object(self.panel, 'UPDATE_REPO', 'matacoder/agent-deck'))
        self.enterContext(patch.object(self.panel.updater, 'available', return_value=True))
        self.panel.http_json = Mock(return_value={'tag_name': 'v99.0.0', 'html_url': 'https://example.test'})
        self.panel._cache.pop('release', None)
        self.addCleanup(self.panel._cache.pop, 'release', None)
        self.assertEqual(self.panel.version_info(fresh=True)['latest'], '99.0.0')
        self.panel.version_info(fresh=True)
        self.assertEqual(self.panel.http_json.call_count, 1)
        at, value = self.panel._cache['release']
        self.panel._cache['release'] = (at - 61, value)
        self.panel.version_info(fresh=True)
        self.assertEqual(self.panel.http_json.call_count, 2)


class ReviewFixTests(PanelCase):
    def fake_tmux(self, sessions):
        def run(*args, **kwargs):
            if args[0] == 'list-sessions':
                fields = args[2].split('\t')
                return '\n'.join('\t'.join(s.get(f, '') for f in fields) for s in sessions)
            if args[0] == 'set-option':
                return ''
            raise AssertionError('unexpected tmux command')
        self.panel.tmux = Mock(side_effect=run)

    def test_renamed_title_round_trips_and_rename_checks_titles(self):
        self.fake_tmux([{'#{session_name}': 'cc-one', '#{@cc_agent}': 'shell', '#{@cc_title}': 'Backend'},
                        {'#{session_name}': 'cc-two', '#{@cc_agent}': 'shell'}])
        titles = {s['name']: s['title'] for s in self.panel.list_sessions()}
        self.assertEqual(titles, {'one': 'Backend', 'two': 'two'})
        self.panel.session_exists = Mock(return_value=True)
        self.assertNotEqual(self.panel.action_rename({'name': 'two', 'title': 'backend'})['title'].casefold(), 'backend')

    def handler(self, raw_headers, path='/api/nope'):
        import http.client, io
        handler = object.__new__(self.panel.Handler)
        handler.headers = http.client.parse_headers(io.BytesIO(raw_headers + b'\r\n'))
        handler.path, handler.command, handler.close_connection = path, 'POST', False
        handler.rfile = io.BytesIO(b'{}GET /api/version HTTP/1.1\r\n\r\n')
        handler.send_json, handler.redirect = Mock(), Mock()
        handler.same_origin = Mock(return_value=True)
        return handler

    def test_unread_bodies_close_connection_and_bad_framing_returns_json(self):
        token = self.panel.make_token()
        for raw, code in ((b'Content-Length: 2\r\n', 401),
                          (b'Content-Length: 2\r\nCookie: cc_auth=' + token.encode() + b'\r\n', 404),
                          (b'Content-Length: 2\r\nContent-Type: text/plain\r\nCookie: cc_auth=' + token.encode() + b'\r\n', 404),
                          (b'Transfer-Encoding: chunked\r\n', 411),
                          (b'Content-Length: 2\r\nTransfer-Encoding: chunked\r\n', 411),
                          (b'Content-Length: invalid\r\n', 400),
                          (b'Content-Length: 2\r\nContent-Length: 40\r\n', 400)):
            with self.subTest(raw=raw):
                handler = self.handler(raw)
                handler.do_POST()
                self.assertEqual(handler.send_json.call_args.args[0], code)
                self.assertTrue(handler.close_connection)
                self.assertNotIn('invalid literal', str(handler.send_json.call_args))
        handler = self.handler(b'Content-Length: 2\r\n')
        handler.post_request = Mock(side_effect=lambda: handler.read_body(2))
        handler.do_POST()
        self.assertFalse(handler.close_connection)

    def test_malformed_foreign_cookie_does_not_hide_auth_or_language(self):
        token = self.panel.make_token()
        handler = self.handler(b'Cookie: pref={"a":1}; cc_auth=' + token.encode() + b'; cc_lang=en\r\n', '/api/sessions')
        self.assertTrue(handler.authorized())
        self.assertEqual(handler.language(), 'en')
        handler = self.handler(b'Cookie: pref={"a":1}; cc_auth=forged.value\r\n', '/api/sessions')
        self.assertFalse(handler.authorized())
        self.assertEqual(handler.send_json.call_args.args[0], 401)

    def test_upload_rejects_symlinked_upload_directories(self):
        self.allow_session()
        target = self.home / 'elsewhere'
        target.mkdir()
        Path(self.panel.UPLOAD_DIR).symlink_to(target)
        with self.assertRaises(ValueError):
            self.upload()
        Path(self.panel.UPLOAD_DIR).unlink()
        Path(self.panel.UPLOAD_DIR).mkdir()
        (Path(self.panel.UPLOAD_DIR) / 'demo').symlink_to(target)
        with self.assertRaises(ValueError):
            self.upload()
        self.assertEqual([p for p in target.rglob('*') if p.is_file()], [])

    def test_send_body_sets_nosniff(self):
        import io
        handler = object.__new__(self.panel.Handler)
        handler.request_version, handler.wfile, handler.log_request = 'HTTP/1.1', io.BytesIO(), Mock()
        handler.send_body(200, b'x', 'text/html')
        self.assertIn(b'X-Content-Type-Options: nosniff', handler.wfile.getvalue())


class WebQuestionTests(PanelCase):
    def question(self, **values):
        from integrations.questions import Question
        data = dict(session='demo', agent='claude', instance='%1:1:sid', title='Proceed?',
                    options=('Yes', 'No', 'Type something'), selected=0)
        return Question(**{**data, **values})

    def test_payload_marks_free_text_options_and_carries_the_fingerprint(self):
        question = self.question(progress='Question 1/2')
        payload = self.panel.question_payload(question)
        self.assertEqual(payload['id'], question.fingerprint)
        self.assertEqual(payload['options'], [{'label': 'Yes', 'text': False}, {'label': 'No', 'text': False},
                                              {'label': 'Type something', 'text': True}])
        self.assertEqual((payload['selected'], payload['progress']), (0, 'Question 1/2'))

    def test_transcript_question_wins_and_invalid_names_never_reach_tmux(self):
        structured = self.question(request_id='tool-1')
        with patch.object(self.panel, 'session_exists', return_value=True), \
             patch.object(self.panel, 'pending_questions', return_value=[structured]), \
             patch.object(self.panel, 'current_question') as screen:
            self.assertIs(self.panel.session_question('demo'), structured)
            screen.assert_not_called()
        with patch.object(self.panel, 'session_exists') as exists:
            for name in (None, '', '../demo', 'a b', 7):
                self.assertIsNone(self.panel.session_question(name))
            exists.assert_not_called()

    def test_answer_requires_the_shown_question_and_an_integer_index(self):
        question = self.question()
        with patch.object(self.panel, 'session_question', return_value=question), \
             patch.object(self.panel, 'answer_question') as answer:
            for bad in ({'index': '1'}, {'index': True}, {'index': None}):
                with self.assertRaises(ValueError):
                    self.panel.action_answer({'name': 'demo', 'id': question.fingerprint, **bad})
            with self.assertRaises(ValueError):
                self.panel.action_answer({'name': 'demo', 'id': 'other', 'index': 1})
            answer.assert_not_called()
            self.panel.action_answer({'name': 'demo', 'id': question.fingerprint, 'index': 1})
            answer.assert_called_once_with(question, 1, None)


class RemoteQuestionTests(PanelCase):
    REMOTE = 'a' * 24
    ITEM = {'id': 'remote-fp', 'session': 'api', 'agent': 'claude', 'title': 'Proceed?', 'selected': 0, 'progress': '',
            'options': [{'label': 'Yes', 'text': False}, {'label': 'No', 'text': False}]}

    def setUp(self):
        super().setUp()
        from integrations.gateway import Gateway
        self.decks = Mock()
        self.decks.status.return_value = {'decks': [{'id': self.REMOTE, 'name': 'Mac Studio'}]}
        self.enterContext(patch.object(self.panel, 'remote_decks', self.decks))
        self.enterContext(patch.object(self.panel, 'gateway', Gateway(lambda: self.panel.remote_decks)))

    def test_connected_machine_questions_carry_their_origin_and_remote_id(self):
        self.decks.request.return_value = (200, {}, json.dumps({'questions': [self.ITEM]}).encode())
        [question] = self.panel.remote_questions()
        self.assertEqual((question.deck, question.origin, question.instance, question.session), (self.REMOTE, 'Mac Studio', 'remote-fp', 'api'))
        self.assertEqual(question.options, ('Yes', 'No'))
        self.decks.request.assert_called_once_with(self.REMOTE, 'GET', '/api/questions', timeout=5, limit=8 * 1024 * 1024)

    def test_unreachable_or_older_machine_is_skipped_for_a_while(self):
        self.decks.request.return_value = (404, {}, b'{"error":"not found"}')
        self.assertEqual(self.panel.remote_questions(), [])
        self.assertEqual(self.panel.remote_questions(), [])
        self.assertEqual(self.decks.request.call_count, 1)

    def test_a_blip_keeps_the_last_questions_until_they_are_stale(self):
        self.decks.request.return_value = (200, {}, json.dumps({'questions': [self.ITEM]}).encode())
        self.assertEqual(len(self.panel.remote_questions()), 1)
        self.decks.request.side_effect = OSError('timed out')
        # Disappearing would retire the Telegram message and re-announce it on return.
        self.assertEqual([q.instance for q in self.panel.remote_questions()], ['remote-fp'])
        from integrations.gateway import QUESTIONS_STALE_FOR
        at, items = self.panel.gateway.snapshot[self.REMOTE]
        self.panel.gateway.snapshot[self.REMOTE] = (at - QUESTIONS_STALE_FOR, items)
        self.assertEqual(self.panel.remote_questions(), [])

    def test_shared_questions_readers_do_not_wait_for_a_slow_refresh(self):
        import threading
        from integrations.questions import Question
        old = [Question('api', 'claude', '%1', 'Old?', ('Yes',), 0)]
        self.panel._questions_cache.update(at=-10.0, items=[], refreshing=False)
        self.addCleanup(self.panel._questions_cache.update, at=-10.0, items=[], refreshing=False)
        started, release = threading.Event(), threading.Event()
        def slow():
            started.set(); release.wait(5); return []
        with patch.object(self.panel, 'all_questions', return_value=old):
            self.assertEqual(self.panel.shared_questions(), old)
        self.panel._questions_cache['at'] -= 5
        with patch.object(self.panel, 'all_questions', side_effect=slow):
            worker = threading.Thread(target=self.panel.shared_questions); worker.start()
            started.wait(5)
            self.assertEqual(self.panel.shared_questions(), old)
            release.set(); worker.join(5)
        self.assertEqual(self.panel.shared_questions(), [])

    def test_notification_sessions_survive_a_malformed_or_unreachable_computer(self):
        other = 'b' * 24
        self.decks.status.return_value = {'decks': [{'id': self.REMOTE, 'name': 'Mac Studio'}, {'id': other, 'name': 'Server'}]}
        self.enterContext(patch.object(self.panel, 'list_sessions', return_value=[]))
        answers = {self.REMOTE: (200, {}, b'{"sessions":[{"name":"api","activity":1},{"title":"no name"},"junk"]}'),
                   other: (200, {}, b'["not a dict"]')}
        self.decks.request.side_effect = lambda deck, *args, **kwargs: answers[deck]
        self.assertEqual([(s['deck'], s['name']) for s in self.panel.push_sessions()], [(self.REMOTE, 'api')])
        self.decks.request.side_effect = OSError('timed out')
        self.panel.gateway.sessions_at = None
        # Unreachable for one poll: its sessions stay, so they do not look finished and restarted.
        self.assertEqual([(s['deck'], s['name']) for s in self.panel.push_sessions()], [(self.REMOTE, 'api')])

    def test_answers_route_to_the_owning_machine_with_its_fingerprint(self):
        from integrations.questions import Question
        question = Question('api', 'claude', 'remote-fp', 'Proceed?', ('Yes', 'No'), 0, deck=self.REMOTE, origin='Mac Studio')
        self.decks.request.return_value = (200, {}, b'{"ok":true}')
        with patch.object(self.panel, 'answer_question') as local:
            self.panel.answer_any_question(question, 1)
            local.assert_not_called()
        method, path, body = self.decks.request.call_args.args[1:4]
        self.assertEqual((method, path, json.loads(body)), ('POST', '/api/answer', {'name': 'api', 'id': 'remote-fp', 'index': 1}))

    def test_remote_rejection_is_definite_but_transport_failure_is_uncertain(self):
        from integrations.questions import Question
        question = Question('api', 'claude', 'remote-fp', 'Proceed?', ('Yes', 'No'), 0, deck=self.REMOTE)
        self.decks.request.return_value = (400, {}, b'{"error":"This question is already closed"}')
        with self.assertRaisesRegex(ValueError, 'already closed'):
            self.panel.answer_any_question(question, 0)
        for failure in (ValueError('Remote Agent Deck did not respond'), OSError('reset')):
            self.decks.request.side_effect = failure
            with self.assertRaises(RuntimeError):
                self.panel.answer_any_question(question, 0)

    def test_local_questions_are_answered_locally(self):
        from integrations.questions import Question
        question = Question('api', 'claude', '%1:1:sid', 'Proceed?', ('Yes', 'No'), 0)
        with patch.object(self.panel, 'answer_question') as local:
            self.panel.answer_any_question(question, 1)
        local.assert_called_once_with(question, 1, None)
        self.decks.request.assert_not_called()


class InboxAndTextAnswerTests(PanelCase):
    def question(self, **values):
        from integrations.questions import Question
        return Question(**{**dict(session='api', agent='codex', instance='%1:1:sid', title='Which DB?',
                                  options=('Prod', 'Type something'), selected=0), **values})

    def test_one_scan_serves_every_consumer_for_two_seconds(self):
        scans = []
        with patch.object(self.panel, 'all_questions', side_effect=lambda: scans.append(1) or [self.question()]):
            with patch.object(self.panel.time, 'monotonic', return_value=1000.0):
                self.panel.shared_questions(); self.panel.shared_questions()
            with patch.object(self.panel.time, 'monotonic', return_value=1003.0):
                self.panel.shared_questions()
        self.assertEqual(len(scans), 2)

    def test_inbox_lists_local_and_remote_questions_with_the_id_each_machine_checks(self):
        local, remote = self.question(), self.question(instance='remote-fp', deck='a' * 24, origin='Mac')
        with patch.object(self.panel, 'shared_questions', return_value=[local, remote]):
            items = self.panel.inbox_payload()['questions']
        self.assertEqual(items[0]['id'], local.fingerprint)
        self.assertEqual((items[1]['id'], items[1]['deck'], items[1]['origin']), ('remote-fp', 'a' * 24, 'Mac'))
        self.assertEqual([o['text'] for o in items[0]['options']], [False, True])

    def test_text_answers_are_validated_and_forwarded_to_the_owning_machine(self):
        q = self.question()
        with patch.object(self.panel, 'session_question', return_value=q), patch.object(self.panel, 'answer_question') as answer:
            for bad in ('', '   ', 'x' * 4001, 5):
                with self.assertRaises(ValueError):
                    self.panel.action_answer({'name': 'api', 'id': q.fingerprint, 'index': 1, 'text': bad})
            self.panel.action_answer({'name': 'api', 'id': q.fingerprint, 'index': 1, 'text': 'Use staging'})
            answer.assert_called_once_with(q, 1, 'Use staging')
        remote = self.question(instance='remote-fp', deck='a' * 24)
        with patch.object(self.panel, 'remote_decks') as decks:
            decks.request.return_value = (200, {}, b'{"ok":true}')
            self.panel.answer_any_question(remote, 1, 'Use staging')
            self.assertEqual(json.loads(decks.request.call_args.args[3]), {'name': 'api', 'id': 'remote-fp', 'index': 1, 'text': 'Use staging'})


class OutOfMemoryTests(PanelCase):
    def test_low_memory_ends_one_process_not_the_tmux_session(self):
        home = Path(tempfile.mkdtemp(dir='/tmp'))
        self.addCleanup(lambda: __import__('shutil').rmtree(home))
        run = Mock()
        with patch.object(self.panel.sys, 'platform', 'linux'), patch.object(self.panel.os.path, 'isdir', return_value=True):
            self.panel.keep_sessions_on_oom(str(home), run)
            self.panel.keep_sessions_on_oom(str(home), run)
        units = home / '.config/systemd/user'
        self.assertIn('[Scope]\nOOMPolicy=continue\n', (units / 'tmux-spawn-.scope.d/agent-deck-oom.conf').read_text())
        self.assertIn('[Service]\nOOMPolicy=continue\n', (units / 'cc-tmux.service.d/agent-deck-oom.conf').read_text())
        run.assert_called_once()  # Reloaded only when something changed.
        self.assertEqual(run.call_args.args[0], ['systemctl', '--user', 'daemon-reload'])
        other = Path(tempfile.mkdtemp(dir='/tmp'))
        self.addCleanup(lambda: __import__('shutil').rmtree(other))
        with patch.object(self.panel.sys, 'platform', 'darwin'):
            self.panel.keep_sessions_on_oom(str(other), run)
        self.assertFalse((other / '.config').exists())
