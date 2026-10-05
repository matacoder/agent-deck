"""Recovery from user-edited or conflicting local state in hooks and the model relay."""
from contextlib import redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from support import ROOT
sys.path.insert(0, str(ROOT))
from integrations.relay import Relay

HOOK = 'python3 ~/.claude/cc-session-hook.py'


def registration():
    spec = importlib.util.spec_from_file_location('register_recovery', ROOT / 'claude/register-hooks.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RegisterHooksTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        (self.home / '.claude').mkdir()

    def test_symlinked_settings_are_written_through_with_original_mode(self):
        dotfiles = self.home / 'dotfiles/claude-settings.json'
        dotfiles.parent.mkdir()
        dotfiles.write_text(json.dumps({'theme': 'dark'}))
        dotfiles.chmod(0o644)
        link = self.home / '.claude/settings.json'
        link.symlink_to(dotfiles)
        registration().register(self.home)
        self.assertTrue(link.is_symlink())
        self.assertEqual(dotfiles.stat().st_mode & 0o777, 0o644)
        data = json.loads(dotfiles.read_text())
        self.assertEqual(data['theme'], 'dark')
        self.assertEqual(data['hooks']['SessionStart'][0]['hooks'][0]['command'], HOOK)

    def test_invalid_settings_are_left_untouched_and_exit_with_file_name(self):
        path = self.home / '.claude/settings.json'
        for content in ('{broken', json.dumps({'hooks': []}), json.dumps({'hooks': {'SessionStart': [1]}})):
            with self.subTest(content=content):
                path.write_text(content)
                with self.assertRaises(ValueError) as caught:
                    registration().register(self.home)
                self.assertIn(str(path), str(caught.exception))
                self.assertEqual(path.read_text(), content)
        result = subprocess.run([sys.executable, str(ROOT / 'claude/register-hooks.py')], input=b'',
                                capture_output=True, env={**os.environ, 'HOME': str(self.home)})
        self.assertEqual(result.returncode, 1)
        self.assertIn(str(path).encode(), result.stderr)
        self.assertNotIn(b'Traceback', result.stderr)


class RelayPortTests(unittest.TestCase):
    def test_busy_saved_port_falls_back_to_a_free_port_and_is_persisted(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        busy = socket.socket()
        self.addCleanup(busy.close)
        busy.bind(('127.0.0.1', 0))
        busy.listen()
        port = busy.getsockname()[1]
        config = Path(tmp.name) / 'model-relay.json'
        config.write_text(json.dumps({'port': port, 'token': 'a' * 64}))
        relay = Relay(tmp.name, Mock())
        relay.start()
        self.addCleanup(relay.close)
        saved = json.loads(config.read_text())
        self.assertNotEqual(relay.server.server_port, port)
        self.assertEqual(saved, {'port': relay.server.server_port, 'token': 'a' * 64})


if __name__ == '__main__':
    unittest.main()
