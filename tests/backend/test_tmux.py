"""Real tmux integration on a private socket; no agents or live sessions are started."""
from pathlib import Path
import shlex
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

from support import PanelCase

REAL_RUN = subprocess.run
REAL_POPEN = subprocess.Popen


@unittest.skipUnless(shutil.which("tmux"), "install tmux to run private-socket integration tests")
class TmuxIntegration(PanelCase):
    def setUp(self):
        super().setUp()
        socket = str(self.home / "tmux.sock")
        def run(args, **kwargs):
            if args[0] != "tmux":
                raise AssertionError("only isolated tmux commands are allowed")
            return REAL_RUN(["tmux", "-S", socket, "-f", "/dev/null", *args[1:]], **kwargs)
        self.enterContext(patch.object(self.panel.subprocess, "run", side_effect=run))
        self.enterContext(patch.object(self.panel.subprocess, "Popen", REAL_POPEN))
        def tmux(*args, check=True):
            result = run(["tmux", *args], capture_output=True, text=True, timeout=5)
            if check and result.returncode:
                raise RuntimeError(result.stderr)
            return result.stdout
        self.panel.tmux = tmux
        self.addCleanup(lambda: tmux("kill-server", check=False))
        self.input_file = self.home / "input.bin"
        ready = self.home / "ready"
        script = self.home / "read_input.py"
        script.write_text("import os,sys,tty\nfrom pathlib import Path\ntty.setraw(0)\n"
                          "Path(sys.argv[2]).touch()\n"
                          "with open(sys.argv[1], 'ab', buffering=0) as f:\n"
                          " while True:\n"
                          "  data=os.read(0,4096)\n"
                          "  if not data: break\n"
                          "  f.write(data)\n")
        command = " ".join(shlex.quote(str(part)) for part in ("python3", script, self.input_file, ready))
        tmux("new-session", "-d", "-s", "cc-demo", "-x", "200", "-y", "50", command)
        tmux("set-option", "-t", "=cc-demo:", "@cc_agent", "codex")
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(ready.exists(), "isolated input reader did not start")

    def test_literal_dash_semicolon_backslash_unicode_and_multiline_reach_tmux_intact(self):
        expected = b""
        for text in ("-x", "a;", "b\\;", "- список\n- вторая строка"):
            self.panel.action_send({"name": "demo", "text": text})
            expected += ("\x1b[200~" + text + "\x1b[201~\r").encode()
        deadline = time.monotonic() + 5
        while (not self.input_file.exists() or self.input_file.stat().st_size < len(expected)) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.input_file.read_bytes(), expected)

    def test_shell_input_is_literal_without_agent_bracket_markers(self):
        self.panel.tmux("set-option", "-t", "=cc-demo:", "@cc_agent", "shell")
        self.panel.action_send({"name": "demo", "text": "printf hello;"})
        deadline = time.monotonic() + 5
        while (not self.input_file.exists() or self.input_file.stat().st_size < 14) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.input_file.read_bytes(), b"printf hello;\r")
