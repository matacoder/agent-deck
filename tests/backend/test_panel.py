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
            for invalid in (None, "", "garbage", "100.bad", "x.signature"):
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
    def test_invalid_session_names_are_rejected_before_commands(self):
        self.panel.session_exists = Mock(return_value=False)
        self.panel.create_session = Mock()
        for name in ("", "../escape", "x;touch", "x" * 33, "demo\n", None, 123, []):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.panel.action_new({"name": name})
        self.panel.create_session.assert_not_called()

    def test_capture_keeps_ansi_and_bounds_plain_preview(self):
        capture = "\x1b[31m" + "\n".join(str(i) for i in range(210)) + "\x1b[0m\n"
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
        self.assertEqual(sessions[0]["preview"].splitlines(), [str(i) for i in range(10, 210)])

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

    def test_disabled_release_checks_do_not_use_network(self):
        self.assertEqual(self.panel.version_info()["version"], self.panel.VERSION)
        self.panel.http_json.assert_not_called()
