import json
import os
from pathlib import Path
from unittest.mock import Mock, patch
from support import PanelCase


class KimiTests(PanelCase):
    def test_private_key_replacement_preservation_removal_and_no_status_leak(self):
        cfg = self.panel.kimi_config
        key = 'sk-test-key-123456789'
        result = cfg.save({'key': key, 'model': 'k3'})
        self.assertNotIn(key, json.dumps(result))
        self.assertEqual(os.stat(cfg.config_path()).st_mode & 0o777, 0o600)
        cfg.save({'model': 'kimi-for-coding'})
        self.assertEqual(cfg.read()['key'], key)
        cfg.save({'clear': True})
        self.assertFalse(cfg.status()['configured'])

    def test_import_existing_cc_kimi_and_explicit_clear_blocks_fallback(self):
        env = self.home / '.config/cc-kimi/env'
        env.parent.mkdir(parents=True)
        env.write_text('ANTHROPIC_API_KEY="sk-existing-123456789"\n')
        cfg = self.panel.kimi_config
        self.assertTrue(cfg.status()['configured'])
        cfg.save({'clear': True})
        self.assertFalse(cfg.status()['configured'])

    def test_invalid_input_does_not_overwrite_key(self):
        cfg = self.panel.kimi_config
        cfg.save({'key': 'sk-valid-key-12345678'})
        for data in ({'key': 'bad\nsecret'}, {'model': '../../foo'}, {'key': []}, {'clear': 'yes'}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                cfg.save(data)
        self.assertTrue(cfg.status()['configured'])

    def test_modes_launch_without_key_in_command_and_resume_exact_session(self):
        cfg = self.panel.kimi_config
        cfg.save({'key': 'sk-test-key-123456789'})
        sid = '11111111-1111-4111-8111-111111111111'
        with patch.object(cfg, 'executable', return_value='/fake/cli'), patch.object(self.panel, 'transcript_exists', return_value=True):
            for agent in ('kimi', 'claude-kimi'):
                actual_sid = "session_" + sid if agent == "kimi" else sid
                cmd = self.panel.agent_cmd(agent, actual_sid, True, True)
                self.assertIn(sid, cmd)
                self.assertNotIn(cfg.read()['key'], cmd)
                self.assertNotIn('--continue', cmd)
                self.assertIn('--session' if agent == 'kimi' else '--resume', cmd)
            with self.assertRaises(ValueError):
                self.panel.agent_cmd('kimi', None, True)

    def test_launch_environments_native_config_and_oauth_isolation(self):
        cfg = self.panel.kimi_config
        key = 'sk-test-key-123456789'
        cfg.save({'key': key})
        with patch.object(cfg, 'executable', return_value='/fake/cli'), patch.object(cfg.os, 'execve') as execute, patch.dict(os.environ, {'ANTHROPIC_AUTH_TOKEN': 'old-oauth'}):
            cfg.launch('claude-kimi', ['--session-id', 'id'])
            env = execute.call_args.args[2]
            self.assertEqual(env['ANTHROPIC_API_KEY'], key)
            self.assertNotIn('ANTHROPIC_AUTH_TOKEN', env)
            cfg.launch('kimi', ['--session', 'id'])
            env = execute.call_args.args[2]
            self.assertEqual(env['AGENT_DECK_KIMI_API_KEY'], key)
            config = Path(env['KIMI_CODE_HOME']) / 'config.toml'
            self.assertNotIn(key, config.read_text())
            self.assertIn('SessionStart', config.read_text())
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)

    def test_missing_key_restart_keeps_running_process_and_saved_id(self):
        self.panel.session_exists = Mock(return_value=True)
        self.panel.opt = Mock(side_effect=lambda name, key: {'@cc_agent': 'kimi', '@cc_sid': 'session_11111111-1111-4111-8111-111111111111', '@cc_skip': '0'}[key])
        self.panel.stop_children = Mock()
        with self.assertRaises(ValueError):
            self.panel.action_restart({'name': 'demo', 'mode': 'new'})
        self.panel.stop_children.assert_not_called()
        self.panel.tmux.assert_not_called()
