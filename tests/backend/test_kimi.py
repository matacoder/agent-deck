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

    def test_native_installer_runs_in_bash_not_posix_sh(self):
        self.panel.run_in_session = Mock()
        self.panel.action_agent_install({'agent': 'kimi'})
        command = self.panel.run_in_session.call_args.args[1]
        self.assertIn('https://code.kimi.com/kimi-code/install.sh | bash', command)

    def test_api_key_accepts_base64_and_other_printable_token_formats(self):
        key = 'sk:test/with+base64==and~symbols'
        self.panel.kimi_config.save({'key': key})
        self.assertEqual(self.panel.kimi_config.read()['key'], key)

    def test_monthly_and_five_hour_quotas_do_not_invent_week_or_calendar_pace(self):
        self.panel.kimi_config.save({'key': 'sk-test-key-123456789'})
        self.panel.http_json = Mock(return_value={'usages': {
            'limit_month_total': {'used_ratio': '0.32', 'reset_time': '2026-11-03T12:00:00Z'},
            'limit_month_code': {'used_ratio': 0.15, 'reset_time': '2026-11-03T12:00:00Z'},
            'limit_5h': {'used_ratio': 0.01},
        }})
        data = self.panel.kimi_usage()
        self.assertEqual([w['percent'] for w in data['windows']], [32, 15, 1])
        self.assertEqual([w['secs'] for w in data['windows']], [0, 0, 18000])
        self.assertNotIn('неделя', [w['label'] for w in data['windows']])
        self.assertIsNotNone(data['windows'][0]['resets_at'])

    def test_invalid_quota_values_and_network_errors_are_safe(self):
        import urllib.error
        self.panel.kimi_config.save({'key': 'sk-test-key-123456789'})
        self.panel.http_json = Mock(return_value={'usages': {'limit_month_total': {'used_ratio': 'NaN'}}})
        self.assertIn('error', self.panel.kimi_usage())
        self.panel.http_json.side_effect = urllib.error.HTTPError('https://api.kimi.com/coding/v1/usages', 401, 'private upstream error', {}, None)
        self.assertEqual(self.panel.kimi_usage()['error'], 'Kimi: проверьте ключ')
