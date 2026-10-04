import hmac
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from integrations import pi
from integrations.relay import Bindings, private_write
from support import PanelCase

SID = '11111111-1111-4111-8111-111111111111'


class PiLaunchTests(unittest.TestCase):
    def enterContext(self, context):
        value = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return value

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.directory = Path(self.tmp)
        self.profile = {'id': 'a'*24, 'url': 'http://localhost:1234', 'key': 'upstream-secret', 'models': [{'id': 'qwen', 'context_length': 65536}]}
        private_write(self.directory/'lmstudio.json', {self.profile['id']: self.profile})
        self.identity = Bindings(self.directory).create(self.profile, 'qwen')
        private_write(self.directory/'model-relay.json', {'port': 12345, 'token': 'relay-secret'})
        self.connection = Mock()
        self.connection.getresponse.return_value.status = 200
        self.connection.getresponse.return_value.read.return_value = json.dumps({'proof': hmac.new(b'relay-secret', b'0'*32, 'sha256').hexdigest()}).encode()
        self.enterContext(patch.object(pi, 'executable', return_value='/test/pi'))
        self.enterContext(patch('http.client.HTTPConnection', return_value=self.connection))
        self.enterContext(patch('secrets.token_hex', return_value='0'*32))

    def launch(self, **kwargs):
        return pi.prepare_local(self.directory, self.identity, SID, **kwargs)

    def test_local_configuration_is_private_and_contains_no_credentials(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'cloud-secret'}):
            binary, args, env = self.launch(name='test')
        home = Path(env['PI_CODING_AGENT_DIR'])
        raw = (home/'models.json').read_text()
        self.assertNotIn('relay-secret', raw)
        self.assertNotIn('upstream-secret', raw)
        self.assertNotIn('cloud-secret', json.dumps(args))
        self.assertNotIn('ANTHROPIC_API_KEY', env)
        self.assertEqual(env['AGENT_DECK_LOCAL_TOKEN'], 'relay-secret')
        self.assertEqual(env['PI_OFFLINE'], '1')
        self.assertEqual((home/'models.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(home.stat().st_mode & 0o777, 0o700)
        provider = json.loads(raw)['providers']['agent-deck-local']
        self.assertEqual(provider['models'][0]['contextWindow'], 65536)
        self.assertEqual(args[args.index('--session-id')+1], SID)
        self.assertNotIn('--continue', args)

    def test_resume_requires_exact_conversation_and_project(self):
        _, _, env = self.launch()
        sessions = Path(env['PI_CODING_AGENT_DIR'])/'sessions'
        with self.assertRaises(ValueError): self.launch(resume=True, cwd=self.tmp)
        file = sessions/('2026_'+SID+'.jsonl')
        file.write_text(json.dumps({'type': 'session', 'id': SID, 'cwd': self.tmp})+'\n')
        args = self.launch(resume=True, cwd=self.tmp)[1]
        self.assertEqual(args[args.index('--session')+1], str(file))
        with self.assertRaises(ValueError): self.launch(resume=True, cwd='/different-project')
        file.unlink(); file.symlink_to(self.directory/'lmstudio.json')
        with self.assertRaises(ValueError): self.launch(resume=True, cwd=self.tmp)

    def test_relay_and_profile_changes_fail_closed(self):
        self.connection.getresponse.return_value.read.return_value = b'{"proof":"wrong"}'
        with self.assertRaises(ValueError): self.launch()
        private_write(self.directory/'model-relay.json', {'port': True, 'token': 'relay-secret'})
        with self.assertRaises(ValueError): self.launch()
        self.profile['url'] = 'http://different-host:1234'
        private_write(self.directory/'lmstudio.json', {self.profile['id']: self.profile})
        with self.assertRaises(ValueError): self.launch()

    def test_invalid_id_or_missing_runtime(self):
        with self.assertRaises(ValueError): pi.prepare_local(self.directory, self.identity, '../wrong')
        with patch.object(pi, 'executable', return_value=None):
            with self.assertRaises(ValueError): self.launch()


class PiPanelTests(PanelCase):
    def test_pi_requires_local_source(self):
        for payload in ({}, {'source': {'kind': 'default'}}, {'source': {'kind': 'kimi', 'model': 'k3'}}):
            with self.assertRaises(ValueError): self.panel.session_source(payload, 'pi')
        with self.assertRaises(ValueError): self.panel.agent_cmd('pi', SID)

    def test_pi_local_source_and_command(self):
        service = self.panel.model_service()
        profile = service.save({'name': 'Local', 'url': 'http://localhost:1234'})
        service.profiles[profile['id']]['models'] = [{'id': 'qwen'}]; service.persist()
        with patch.object(pi, 'executable', return_value='/test/pi'):
            source = self.panel.session_source({'source': {'kind': 'lmstudio', 'profile': profile['id'], 'model': 'qwen'}}, 'pi')
        self.panel._model_relay.server = Mock()
        cmd = self.panel.agent_cmd('pi', SID, resume=True, source=source)
        self.assertIn('pi-local', cmd)
        self.assertIn('--deck-resume', cmd)
        self.assertIn(SID, cmd)
        self.assertNotIn('--continue', cmd)
        self.assertTrue(self.panel.is_running('pi', 'node'))
        self.assertFalse(self.panel.is_running('pi', 'bash'))
