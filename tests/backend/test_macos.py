import importlib.util
import json
import os
from pathlib import Path
import plistlib
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from support import PanelCase, ROOT

spec = importlib.util.spec_from_file_location('mac_installer', ROOT / 'macos/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class MacPlatformTests(PanelCase):
    def test_server_startup_does_not_wait_for_reverse_dns(self):
        with patch.object(self.panel.socket, 'getfqdn', side_effect=AssertionError('reverse DNS must not run')):
            server = self.panel.PanelHTTPServer(('127.0.0.1', 0), self.panel.Handler)
            try:
                self.assertEqual(server.server_name, '127.0.0.1')
                self.assertGreater(server.server_port, 0)
            finally:
                server.server_close()

    def test_question_navigation_keys_are_forwarded_without_text_paste(self):
        self.allow_session()
        for key in ('S-Left', 'S-Right', 'Left', 'Right', 'Up', 'Down', 'Enter'):
            self.panel.action_send({'name': 'demo', 'key': key})
            self.panel.tmux.assert_called_with('send-keys', '-t', '=cc-demo:', key)
        self.assertEqual(self.pasted, [])

    def test_metrics_use_cumulative_cpu_across_request_threads(self):
        from collections import namedtuple
        cpu = namedtuple('cpu', 'user system idle')
        psutil = Mock()
        psutil.cpu_times.side_effect = [cpu(10, 10, 80), cpu(20, 20, 100)]
        psutil.virtual_memory.return_value = SimpleNamespace(total=8192, available=3072)
        with patch.object(self.panel.sys, 'platform', 'darwin'), patch.dict('sys.modules', psutil=psutil), \
                patch.object(self.panel.time, 'monotonic', side_effect=[1, 6]):
            first = self.panel.server_metrics()
            self.assertIsNone(first['cpu_percent'])
            self.assertEqual(self.panel.server_metrics(), {'cpu_percent': 50, 'memory_total': 8192, 'memory_used': 5120})

    def test_process_existence_without_proc(self):
        with patch.object(self.panel.os, 'kill', side_effect=[None, ProcessLookupError, PermissionError]):
            self.assertTrue(self.panel.process_exists(123))
            self.assertFalse(self.panel.process_exists(123))
            self.assertTrue(self.panel.process_exists(123))

    def test_mac_parent_process_and_isolated_hook_socket(self):
        hook = self.panel.kimi_config
        with patch.object(hook.sys, 'platform', 'darwin'), patch.object(hook.subprocess, 'run',
                return_value=SimpleNamespace(stdout='42 /opt/homebrew/bin/codex\n')) as run:
            self.assertEqual(hook.parent_info(50), (42, 'codex'))
            self.assertIn('comm=', run.call_args.args[0])
        with patch.dict(os.environ, TMUX_SOCKET_NAME='agent-deck'), patch.object(hook, 'top_level', return_value=True), \
                patch.object(hook.subprocess, 'run', return_value=SimpleNamespace(stdout='42\tcc-test')) as run:
            hook.remember({'session_id': '11111111-1111-4111-8111-111111111111'}, '%1', 50)
            for call in run.call_args_list:
                self.assertEqual(call.args[0][:3], ['tmux', '-L', 'agent-deck'])

    def test_mac_keychain_credentials_are_not_exposed_in_status(self):
        with patch.object(self.panel.sys, 'platform', 'darwin'), patch.object(self.panel.subprocess, 'run',
                return_value=SimpleNamespace(returncode=0, stdout='{"claudeAiOauth":{"accessToken":"test-only"}}')) as run:
            self.assertEqual(self.panel.claude_credentials()['claudeAiOauth']['accessToken'], 'test-only')
            self.assertEqual(run.call_args.args[0][:2], ['security', 'find-generic-password'])

    def test_mac_updater_uses_launchctl_and_preserves_other_services(self):
        updater = self.panel.updater
        with patch.object(updater.sys, 'platform', 'darwin'), patch.object(updater.subprocess, 'run',
                return_value=SimpleNamespace(returncode=0)) as run:
            updater.service('stop')
            updater.service('start')
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0][:2], ['launchctl', 'bootout'])
            self.assertEqual(commands[1][:2], ['launchctl', 'bootstrap'])
            self.assertIn('com.agent-deck.panel', commands[0][-1])
            self.assertNotIn('ttyd', str(commands))


class MacInstallerTests(unittest.TestCase):
    def test_rerun_preserves_password_hooks_sessions_and_user_tmux_config(self):
        with tempfile.TemporaryDirectory(prefix='mac home ', dir='/tmp') as directory:
            home = Path(directory)
            (home / '.tmux.conf').write_text('user settings')
            (home / '.claude').mkdir()
            (home / '.claude/settings.json').write_text('{"custom":true,"hooks":{"SessionStart":[{"hooks":[{"command":"user-hook"}]}]}}')
            with patch.object(installer.shutil, 'which', side_effect=lambda name: '/opt/homebrew/bin/' + name):
                installer.install(home, start=False)
                config = home / '.config/cc-panel'
                settings = json.loads((config / 'macos.json').read_text())
                (config / 'sessions.json').write_text('{"sessions":{"keep":{}}}')
                installer.install(home, start=False)
            self.assertEqual(json.loads((config / 'macos.json').read_text()), settings)
            self.assertEqual((config / 'sessions.json').read_text(), '{"sessions":{"keep":{}}}')
            self.assertEqual((home / '.tmux.conf').read_text(), 'user settings')
            hooks = json.loads((home / '.claude/settings.json').read_text())
            self.assertTrue(hooks['custom'])
            self.assertEqual(len(hooks['hooks']['SessionStart']), 2)
            for label in installer.LABELS:
                file = home / 'Library/LaunchAgents' / (label + '.plist')
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)
                data = plistlib.loads(file.read_bytes())
                self.assertEqual(data['EnvironmentVariables']['TMUX_SOCKET_NAME'], 'agent-deck')
                if label.endswith('panel'):
                    self.assertTrue(data['AbandonProcessGroup'])
                    self.assertEqual(data['EnvironmentVariables']['BIND_HOST'], '127.0.0.1')
                    self.assertEqual(data['ProgramArguments'][1], str(home / '.local/share/agent-deck/panel/panel.py'))
                else:
                    self.assertNotIn('PANEL_PASSWORD', data['EnvironmentVariables'])
            self.assertEqual((config / 'macos.json').stat().st_mode & 0o777, 0o600)
