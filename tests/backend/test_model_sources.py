import json
from pathlib import Path
from unittest.mock import Mock, patch
from support import PanelCase
from integrations.relay import Bindings, private_write


class ModelSourceTests(PanelCase):
    def profile(self):
        service=self.panel.model_service()
        p=service.save({'name':'Local','url':'http://100.64.1.2:1234','key':'private-test-key'})
        service.profiles[p['id']]['models']=[{'id':'qwen-coder'}]
        service.persist()
        return p

    def test_local_source_pins_model_and_command_contains_no_upstream_key(self):
        p=self.profile()
        self.panel.kimi_config.executable=Mock(return_value='/test/claude')
        source=self.panel.session_source({'source':{'kind':'lmstudio','profile':p['id'],'model':'qwen-coder'}},'claude')
        binding=self.panel._model_relay.bindings.get(source['binding'])
        self.assertEqual(binding['url'],p['url'])
        self.panel._model_relay.server=Mock()
        cmd=self.panel.agent_cmd('claude','11111111-1111-4111-8111-111111111111',source=source)
        self.assertIn('claude-local',cmd)
        self.assertNotIn('private-test-key',cmd)
        self.assertNotIn(p['url'],cmd)
        with self.assertRaises(ValueError):
            self.panel.session_source({'source':{'kind':'lmstudio','profile':p['id'],'model':'qwen-coder'}},'codex')

    def test_referenced_profile_cannot_be_removed_or_redirected(self):
        p=self.profile()
        self.panel.list_sessions=Mock(return_value=[{'source':{'kind':'lmstudio','profile':p['id']}}])
        with self.assertRaises(ValueError):self.panel.action_lm_remove({'id':p['id']})
        with self.assertRaises(ValueError):self.panel.action_lm_save({'id':p['id'],'name':'Same','url':'http://100.64.1.3:1234'})
        self.assertEqual(self.panel.model_service().get(p['id'])['url'],p['url'])
        self.panel.action_lm_save({'id':p['id'],'name':'Renamed','url':p['url'],'key':'rotated-key'})
        self.assertEqual(self.panel.model_service().get(p['id'])['key'],'rotated-key')

    def test_local_launcher_uses_private_loopback_token_and_clears_other_providers(self):
        p=self.profile();directory=self.home/'.config/cc-panel/integrations'
        binding=Bindings(directory).create(p,'qwen-coder')
        private_write(directory/'model-relay.json',{'port':12345,'token':'relay-token'})
        cfg=self.panel.kimi_config
        import hmac
        connection=Mock();connection.getresponse.return_value.status=200
        connection.getresponse.return_value.read.return_value=json.dumps({'proof':hmac.new(b'relay-token',b'0'*32,'sha256').hexdigest()}).encode()
        self.enterContext(patch('http.client.HTTPConnection',return_value=connection))
        self.enterContext(patch('secrets.token_hex',return_value='0'*32))
        with patch.object(cfg,'executable',return_value='/test/claude'),patch.object(cfg.os,'execve') as execute,patch.dict(cfg.os.environ,{'ANTHROPIC_API_KEY':'inherited-secret','CLAUDE_CODE_USE_BEDROCK':'1'}):
            cfg.launch_local(binding,['--resume','11111111-1111-4111-8111-111111111111'])
        binary,args,env=execute.call_args.args
        self.assertEqual(args[:3],['/test/claude','--model','qwen-coder'])
        self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'],'relay-token')
        self.assertEqual(env['ANTHROPIC_BASE_URL'],'http://127.0.0.1:12345/providers/'+binding)
        self.assertNotIn('ANTHROPIC_API_KEY',env)
        self.assertNotIn('CLAUDE_CODE_USE_BEDROCK',env)
        self.assertNotIn('private-test-key',json.dumps(args))
        self.assertEqual(env['ANTHROPIC_DEFAULT_OPUS_MODEL'],'qwen-coder')

    def test_kimi_model_override_is_pinned_without_replacing_account_default(self):
        cfg=self.panel.kimi_config;cfg.save({'key':'test-key','model':'k3'})
        with patch.object(cfg,'executable',return_value='/test/claude'),patch.object(cfg.os,'execve') as execute:
            cfg.launch('claude-kimi',['--deck-model','kimi-for-coding','--resume','id'])
        self.assertEqual(execute.call_args.args[1],['/test/claude','--resume','id'])
        self.assertEqual(execute.call_args.args[2]['ANTHROPIC_MODEL'],'kimi-for-coding')
        self.assertEqual(cfg.status()['model'],'k3')

    def test_restore_uses_snapshot_source_instead_of_missing_tmux_options(self):
        path=self.home/'projects/demo';path.mkdir(parents=True)
        source={'kind':'lmstudio','profile':'a'*24,'model':'qwen-coder','binding':'b'*24}
        self.panel.agent_cmd=Mock(return_value='local-resume-command')
        self.panel.create_session=Mock()
        self.panel.restore_session('demo',{'path':str(path),'agent':'claude','sid':'id','skip':False,'running':True,'source':source})
        self.panel.agent_cmd.assert_called_once_with('claude','id',True,False,source=source)
        self.assertEqual(self.panel.create_session.call_args.args[-1],source)

    def test_missing_local_binding_restores_a_shell_and_keeps_the_source(self):
        path=self.home/'projects/demo';path.mkdir(parents=True)
        source={'kind':'lmstudio','profile':'a'*24,'model':'qwen-coder','binding':'b'*24}
        self.panel.create_session=Mock()
        self.panel.restore_session('demo',{'path':str(path),'agent':'claude','sid':'id','running':True,'source':source})
        self.assertIsNone(self.panel.create_session.call_args.args[5])
        self.assertEqual(self.panel.create_session.call_args.args[6],source)

    def test_malformed_saved_source_never_falls_back_to_default_provider(self):
        self.panel.opt=Mock(return_value='{"kind":"not-a-provider"}')
        with self.assertRaises(ValueError):self.panel.agent_cmd('claude','id',source=self.panel.saved_source('demo'))

    def test_snapshot_records_source_and_legacy_sessions_still_have_no_source(self):
        source={'kind':'lmstudio','binding':'a'*24,'profile':'b'*24,'model':'qwen-coder'}
        self.panel.tmux=Mock(return_value='cc-local\t/tmp\tclaude\tid\t0\t1\tclaude\t'+json.dumps(source)+'\ncc-old\t/tmp\tcodex\tid\t0\t1\tcodex\n')
        snapshot=self.panel.live_sessions()
        self.assertEqual(snapshot['local']['source'],source)
        self.assertIsNone(snapshot['old']['source'])
