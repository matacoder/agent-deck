import importlib.util
import os
import shlex
from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

from support import PanelCase, ROOT, PNG


class ReviewRegressions(PanelCase):
    def test_list_only_captures_requested_session_and_reads_options_in_one_command(self):
        self.panel.tmux = Mock(side_effect=[
            f"cc-a\t1\t0\t{self.home}\tcodex\t1\tcodex\t\t0\n"
            f"cc-b\t1\t0\t{self.home}\tclaude\t1\tclaude\t\t0\n",
            "\x1b[31mSelected output\x1b[0m",
        ])
        result = self.panel.list_sessions("b")
        self.assertNotIn("preview", result[0])
        self.assertIn("Selected output", result[1]["preview"])
        self.assertEqual(self.panel.tmux.call_count, 2)
        self.panel.tmux = Mock(return_value="cc-a\t1\t0\t/tmp\tcodex\t1\tcodex\t\t0\n")
        self.assertNotIn("preview_ansi", self.panel.list_sessions()[0])
        self.assertEqual(self.panel.tmux.call_count, 1)

    def test_codex_commands_resume_distinct_ids_in_same_project_without_last_fallback(self):
        first = "11111111-1111-4111-8111-111111111111"
        second = "22222222-2222-4222-8222-222222222222"
        self.assertIn(first, self.panel.agent_cmd("codex", first, True))
        self.assertIn(second, self.panel.agent_cmd("codex", second, True))
        self.assertNotIn("--last", self.panel.agent_cmd("codex", first, True))
        self.assertIn("--no-alt-screen", self.panel.agent_cmd("codex", first, True))
        self.assertIn("--no-alt-screen", self.panel.agent_cmd("codex"))
        for missing in (None, "garbage", "x; touch /tmp/unsafe"):
            with self.assertRaises(ValueError):
                self.panel.agent_cmd("codex", missing, True)

    def test_missing_conversation_id_does_not_stop_the_running_agent(self):
        self.allow_session()
        self.panel.opt.return_value = None
        self.panel.stop_children = Mock()
        self.panel.transcript_exists = Mock(return_value=False)
        with self.assertRaises(ValueError):
            self.panel.action_restart({"name": "demo", "mode": "continue"})
        self.panel.stop_children.assert_not_called()

    def test_restart_runs_command_in_fresh_pty_without_pasting_into_shell(self):
        sid = "11111111-1111-4111-8111-111111111111"
        for mode in ("new", "continue"):
            with self.subTest(mode=mode):
                self.allow_session()
                self.panel.opt.side_effect = lambda name, key: {
                    "@cc_agent": "codex", "@cc_skip": "0", "@cc_sid": sid,
                }.get(key)
                self.panel.saved_source = Mock(return_value=None)
                self.panel.stop_children = Mock()
                self.panel.type_line = Mock()
                self.panel.tmux.side_effect = lambda *args, **kwargs: (
                    str(self.home) if args[0] == "display-message" else
                    "/bin/bash" if args[0] == "show-options" else "")
                self.panel.action_restart({"name": "demo", "mode": mode})
                self.panel.stop_children.assert_called_once_with("demo")
                self.panel.type_line.assert_not_called()
                calls = self.panel.tmux.call_args_list
                self.assertFalse(any(c.args[0] in ("send-keys", "paste-buffer") for c in calls))
                respawn = next(c.args for c in calls if c.args[0] == "respawn-pane")
                self.assertEqual(respawn[1:6], ("-k", "-t", "=cc-demo:", "-c", str(self.home)))
                shell, flag, script = shlex.split(respawn[6])
                self.assertEqual((shell, flag), ("/bin/bash", "-lic"))
                expected = self.panel.agent_cmd("codex", sid, mode == "continue")
                self.assertEqual(script, "clear; " + expected + "; exec /bin/bash")
                self.assertEqual(self.pasted, [])

    def test_kill_cleans_images_and_ttl_keeps_recent_and_ignores_symlinked_folders(self):
        self.allow_session()
        first = self.upload()
        recent = self.upload()
        folder = Path(self.panel.UPLOAD_DIR) / "demo"
        os.utime(folder / first, (0, 0))
        outside = self.home / "outside"
        outside.mkdir()
        (outside / first).write_bytes(PNG)
        os.utime(outside / first, (0, 0))
        (Path(self.panel.UPLOAD_DIR) / "linked").symlink_to(outside)
        self.panel.cleanup_uploads()
        self.assertFalse((folder / first).exists())
        self.assertTrue((folder / recent).exists())
        self.assertTrue((outside / first).exists())
        self.panel.action_kill({"name": "demo"})
        self.assertFalse(folder.exists())

    def test_discard_only_removes_requested_session_image(self):
        self.allow_session()
        image = self.upload()
        other = self.upload(name="other")
        self.panel.action_discard_upload({"name": "demo", "attachments": [image]})
        self.assertFalse((Path(self.panel.UPLOAD_DIR) / "demo" / image).exists())
        self.assertTrue((Path(self.panel.UPLOAD_DIR) / "other" / other).exists())

    def test_github_login_is_tagged_as_shell(self):
        utility = self.panel.run_in_session
        with patch.object(self.panel, "run_in_session") as run:
            self.panel.action_github_login({})
            run.assert_called_once_with("github-login", self.panel.GH_LOGIN_CMD)
        self.panel.session_exists = Mock(return_value=False)
        self.panel.create_session = Mock()
        utility("github-login", self.panel.GH_LOGIN_CMD)
        self.assertEqual(self.panel.create_session.call_args.args[2], "shell")

    def test_iso_z_dates_work_on_python310(self):
        self.assertEqual(self.panel._epoch("2026-10-02T00:00:00Z"), 1790899200)
        self.assertEqual(self.panel._epoch("2026-10-02T00:00:00.123Z"), 1790899200)


class HookTests(PanelCase):
    def setUp(self):
        super().setUp()
        spec = importlib.util.spec_from_file_location("session_hook_test", ROOT / "panel/session_hook.py")
        self.hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.hook)

    def test_registration_keeps_user_hooks_and_is_idempotent(self):
        import json
        spec = importlib.util.spec_from_file_location("register_test", ROOT / "claude/register-hooks.py")
        registration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(registration)
        path = self.home / ".codex/hooks.json"
        path.parent.mkdir(exist_ok=True)
        existing = {"custom": True, "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo original"}]}]}}
        path.write_text(json.dumps(existing))
        registration.register(self.home)
        first = path.read_bytes()
        registration.register(self.home)
        self.assertEqual(path.read_bytes(), first)
        data = json.loads(first)
        self.assertTrue(data["custom"])
        self.assertEqual(len(data["hooks"]["SessionStart"]), 2)
        self.assertEqual(data["hooks"]["SessionStart"][0], existing["hooks"]["SessionStart"][0])
        self.assertTrue((self.home / ".claude/settings.json").exists())

    def test_only_top_level_cli_updates_sid_and_nested_claude_review_is_ignored(self):
        sid = "11111111-1111-4111-8111-111111111111"
        roots = {40: (30, "sh"), 30: (10, "codex"), 10: (1, "bash")}
        nested = {60: (50, "sh"), 50: (40, "claude"), **roots}
        with patch.object(self.hook, "parent_info", side_effect=lambda pid: roots[pid]), patch.object(self.hook.subprocess, "run", return_value=SimpleNamespace(stdout="10\tcc-demo")) as run:
            self.hook.remember({"session_id": sid}, "%1", 40)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][-2:], ["@cc_sid", sid])
        with patch.object(self.hook, "parent_info", side_effect=lambda pid: nested[pid]), patch.object(self.hook.subprocess, "run", return_value=SimpleNamespace(stdout="10\tcc-demo")) as run:
            self.hook.remember({"session_id": sid}, "%1", 60)
            self.assertEqual(run.call_count, 1)

    def test_native_kimi_session_id_and_process_name_are_recorded(self):
        sid = "session_11111111-1111-4111-8111-111111111111"
        roots = {40: (30, "sh"), 30: (10, "kimi-code")}
        with patch.object(self.hook, "parent_info", side_effect=lambda pid: roots[pid]), patch.object(self.hook.subprocess, "run", return_value=SimpleNamespace(stdout="10\tcc-demo")) as run:
            self.hook.remember({"session_id": sid, "client_type": "kimi_code_cli"}, "%1", 40)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][-2:], ["@cc_sid", sid])
