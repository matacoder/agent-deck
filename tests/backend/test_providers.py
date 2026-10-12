import json
import os
import stat
import tempfile
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from support import PanelCase
from integrations.providers import Providers, clean_url, environment

GLM = {'name': 'GLM', 'url': 'https://api.z.ai/api/anthropic', 'model': 'glm-5.3', 'key': 'sk-secret-1'}


class ProviderTests(PanelCase):
    def setUp(self):
        super().setUp()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Providers(Path(self.folder.name) / 'cc-panel/providers.json')
        self.patcher = patch.object(self.panel, 'provider_store', return_value=self.store)
        self.patcher.start()
        self.addCleanup(patch.stopall)

    def test_the_key_is_kept_private_and_never_returned(self):
        identity = self.store.save(dict(GLM))
        self.assertEqual(stat.S_IMODE(os.stat(self.store.path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.store.path.parent).st_mode), 0o700)
        self.assertEqual(self.store.public(), [{'id': identity, 'name': 'GLM', 'url': GLM['url'], 'model': 'glm-5.3', 'configured': True}])
        self.assertNotIn('sk-secret-1', json.dumps(self.panel.action_provider_save({**GLM, 'id': identity, 'key': '', 'model': 'glm-5.3-flash'})))
        self.assertEqual(self.store.get(identity)['key'], 'sk-secret-1')  # An empty field keeps the key.
        self.assertEqual(self.store.get(identity)['model'], 'glm-5.3-flash')

    def test_a_changed_address_does_not_inherit_the_key_typed_for_another(self):
        identity = self.store.save(dict(GLM))
        with self.assertRaisesRegex(ValueError, 'Enter the key'):
            self.store.save({**GLM, 'id': identity, 'key': '', 'url': 'https://elsewhere.example/anthropic'})
        self.assertEqual(self.store.get(identity)['url'], GLM['url'])

    def test_only_a_plain_https_address_and_sane_names_are_saved(self):
        for bad in ('http://api.z.ai/api/anthropic', 'https://user:pw@api.z.ai/x', 'https://api.z.ai/x?key=1', 'ftp://x', '', None, 'https://api.z.ai/a b'):
            with self.assertRaises(ValueError):
                clean_url(bad)
        self.assertEqual(clean_url(' https://api.z.ai/api/anthropic/ '), 'https://api.z.ai/api/anthropic')
        for change in ({'model': 'glm 5; rm'}, {'name': ''}, {'key': 'two words'}, {'id': 'gone00000000'}):
            with self.assertRaises(ValueError):
                self.store.save({**GLM, **change})
        with self.assertRaisesRegex(ValueError, 'not saved or has no key'):
            self.store.get('0' * 12)

    def test_a_session_on_a_provider_carries_its_id_and_model_but_no_key(self):
        identity = self.store.save(dict(GLM))
        sid = str(uuid.uuid4())
        with patch.object(self.panel.kimi_config, 'executable', return_value='/usr/bin/claude'):
            source = self.panel.session_source({'source': {'kind': 'provider', 'provider': identity}}, 'claude')
        self.assertEqual(source, {'kind': 'provider', 'provider': identity, 'model': 'glm-5.3', 'label': 'GLM · glm-5.3'})
        command = self.panel.agent_cmd('claude-provider', sid, False, True, None, source)
        self.assertIn(f'session_hook.py claude-provider {identity} glm-5.3 --session-id {sid} --dangerously-skip-permissions', command)
        self.assertNotIn('sk-secret-1', command)
        with self.assertRaisesRegex(ValueError, 'incompatible'):
            self.panel.agent_cmd('claude', sid, False, False, None, source)
        self.store.remove(identity)
        with self.assertRaisesRegex(ValueError, 'not saved or has no key'):
            self.panel.agent_cmd('claude-provider', sid, False, False, None, source)

    def test_a_provider_session_comes_back_after_a_reboot_with_its_containers(self):
        identity, sid = self.store.save(dict(GLM)), str(uuid.uuid4())
        source = {'kind': 'provider', 'provider': identity, 'model': 'glm-5.3', 'label': 'GLM · glm-5.3'}
        self.panel.create_session, self.panel.tmux = Mock(), Mock()
        self.panel.transcript_exists = Mock(return_value=True)
        self.panel.with_containers = Mock(side_effect=lambda command, choice=None: f'DOCKER_HOST={choice} {command}')
        self.panel.note_containers = Mock()
        info = {'path': self.folder.name, 'agent': 'claude-provider', 'sid': sid, 'skip': False, 'running': True,
                'source': source, 'containers': 'a' * 24}
        self.panel.restore_session('glm', info)
        command = self.panel.create_session.call_args.args[5]
        self.assertIn(f'session_hook.py claude-provider {identity} glm-5.3 --resume {sid}', command)
        self.assertTrue(command.startswith('DOCKER_HOST=' + 'a' * 24))
        self.assertIn(('@cc_containers', 'a' * 24), [call.args[-2:] for call in self.panel.tmux.call_args_list])
        self.panel.note_containers.assert_called_once_with('glm', 'a' * 24)

    def test_two_saves_share_one_lock_and_a_damaged_file_shows_no_providers(self):
        self.patcher.stop()
        with patch.dict(os.environ, {'HOME': self.folder.name}):
            self.panel._providers = None
            self.assertIs(self.panel.provider_store(), self.panel.provider_store())
            self.panel._providers = None
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        self.store.path.write_text('{not json')
        self.assertEqual(self.store.public(), [])

    def test_claude_code_starts_on_the_provider_and_not_on_an_inherited_login(self):
        env = environment({**GLM}, 'glm-5.3', {'ANTHROPIC_API_KEY': 'old', 'CLAUDE_CODE_USE_BEDROCK': '1', 'PATH': '/bin'})
        self.assertEqual((env['ANTHROPIC_AUTH_TOKEN'], env['ANTHROPIC_BASE_URL'], env['ANTHROPIC_MODEL']), ('sk-secret-1', GLM['url'], 'glm-5.3'))
        self.assertEqual({env['ANTHROPIC_DEFAULT_' + tier + '_MODEL'] for tier in ('OPUS', 'SONNET', 'HAIKU')}, {'glm-5.3'})
        self.assertNotIn('ANTHROPIC_API_KEY', env)
        self.assertNotIn('CLAUDE_CODE_USE_BEDROCK', env)
        self.assertEqual(env['PATH'], '/bin')


class LauncherTests(PanelCase):
    def test_the_launcher_hands_the_key_to_claude_code_in_the_environment_only(self):
        import session_hook
        with tempfile.TemporaryDirectory() as home:
            store = Providers(Path(home) / '.config/cc-panel/providers.json')
            identity = store.save(dict(GLM))
            started = []
            with patch.object(session_hook.os.path, 'expanduser', side_effect=lambda p: p.replace('~', home, 1)), \
                 patch.object(session_hook, 'executable', return_value='/usr/bin/claude'), \
                 patch.object(session_hook.os, 'execve', side_effect=lambda *call: started.append(call)):
                session_hook.launch_provider(identity, 'glm-5.3', ['--session-id', 'abc'])
                with self.assertRaises(ValueError):
                    session_hook.launch_provider(identity, 'glm 5.3; id', [])
                with self.assertRaises(ValueError):
                    session_hook.launch_provider('0' * 12, 'glm-5.3', [])
        binary, args, env = started[0]
        self.assertEqual((binary, args[0], args[-2:]), ('/usr/bin/claude', '/usr/bin/claude', ['--session-id', 'abc']))
        self.assertNotIn('sk-secret-1', ' '.join(args))
        self.assertEqual((env['ANTHROPIC_AUTH_TOKEN'], env['ANTHROPIC_BASE_URL']), ('sk-secret-1', GLM['url']))
        self.assertEqual(len(started), 1)
