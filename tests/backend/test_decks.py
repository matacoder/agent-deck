import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from support import PanelCase
from integrations.decks import RemoteDecks, deck_url, remote_path
from integrations.preferences import ProjectDirectory, NetworkSettings

ID = 'a'*24
URL = 'http://100.68.39.62:8790'
PROFILE = {'id':ID,'name':'Mac','url':URL,'username':'denis','password':'test-password-only'}


class RemoteDeckTests(PanelCase):
    def setUp(self):
        super().setUp()
        self.decks = RemoteDecks(self.home/'decks','http://100.109.113.79:8790')
        self.decks.profiles[ID] = dict(PROFILE)
        self.transport = self.enterContext(patch('integrations.decks.http_request'))

    def test_only_tailnet_ip_origins_and_deck_paths_are_allowed(self):
        self.assertEqual(deck_url(URL+'/'),URL)
        for invalid in ('http://127.0.0.1:8790','http://192.168.1.1','http://example.com','http://100.68.39.62/path',URL+'?a=b',URL+'#x','http://user:pass@100.68.39.62','file:///tmp/x'):
            with self.subTest(url=invalid), self.assertRaises(ValueError):deck_url(invalid)
        for path in ('/api/sessions?preview=demo','/api/github/repos?refresh=1','/t/ws','/t/?arg=%3Dcc-demo'):
            self.assertEqual(remote_path(path),path)
        for invalid in ('//evil/api/x','https://evil/api/x','/login','/deck/x/api/x','/api/decks','/api/network','/t/../login','/t/%2e%2e/login','/t/ws\r\nHost: evil'):
            with self.subTest(path=invalid), self.assertRaises(ValueError):remote_path(invalid)
        self.transport.assert_not_called()

    def test_successful_connection_stores_credentials_privately_without_exposing_them(self):
        self.transport.side_effect = [(303,{'Set-Cookie':'cc_auth=signed.cookie; HttpOnly','Location':'/'},b''),(200,{},b'{"version":"1.0.7"}')]
        public = self.decks.save(PROFILE)
        self.assertEqual(public, {k:PROFILE[k] for k in ('id','name','url','username')})
        self.assertNotIn('password',json.dumps(self.decks.status()))
        self.assertNotIn('signed.cookie',json.dumps(self.decks.status()))
        self.assertEqual(self.decks.path.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.decks.directory.stat().st_mode & 0o777,0o700)
        restored=RemoteDecks(self.decks.directory,self.decks.local_url)
        self.assertEqual(restored.get(ID)['password'],PROFILE['password'])
        self.assertEqual(restored.cookies,{})
        login=self.transport.call_args_list[0]
        self.assertEqual(login.args[1:3],('POST','/login'))
        self.assertNotIn(PROFILE['password'],login.args[0])
        self.assertEqual(login.args[4]['Origin'],URL)

    def test_bad_credentials_and_foreign_redirects_are_not_saved(self):
        self.decks.profiles.clear()
        for response in ((401,{},b'bad'),(303,{'Set-Cookie':'cc_auth=x','Location':'https://evil/'},b'')):
            self.transport.return_value=response
            with self.assertRaises(ValueError):self.decks.save({k:v for k,v in PROFILE.items() if k!='id'})
            self.assertEqual(self.decks.profiles,{})
            self.assertFalse(self.decks.path.exists())

    def test_cookie_expiry_reauthenticates_once_before_retrying_an_unauthorized_request(self):
        self.decks.cookies[ID]='cc_auth=old'
        self.transport.side_effect=[(401,{},b'{}'),(303,{'Set-Cookie':'cc_auth=new','Location':'/'},b''),(200,{},b'{}')]
        self.assertEqual(self.decks.request(ID,'POST','/api/send',b'{"text":"hello"}')[0],200)
        self.assertEqual([c.args[1] for c in self.transport.call_args_list],['POST','POST','POST'])
        first,last=self.transport.call_args_list[0],self.transport.call_args_list[2]
        self.assertEqual(first.args[3],last.args[3])
        self.assertIn('cc_auth=new',last.args[4]['Cookie'])
        self.assertIn('cc_lang=en',last.args[4]['Cookie'])

    def test_ambiguous_transport_failure_does_not_replay_a_mutation(self):
        self.decks.cookies[ID]='cc_auth=old'
        self.transport.side_effect=TimeoutError('secret must not leak')
        with self.assertRaisesRegex(ValueError,'did not respond') as error:
            self.decks.request(ID,'POST','/api/send',b'{}')
        self.assertNotIn('secret',str(error.exception))
        self.assertEqual(self.transport.call_count,1)

    def test_password_is_never_reused_for_changed_address_or_login(self):
        for change in ({'url':'http://100.68.39.63:8790'},{'username':'someone-else'}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError,'password'):
                self.decks.save({**PROFILE,**change,'password':''})
        self.transport.assert_not_called()

    def test_discovery_probes_only_online_tailnet_peers_and_requested_port(self):
        state={'BackendState':'Running','Peer':{
            'a':{'HostName':'Mac\xa0','Online':True,'TailscaleIPs':['100.68.39.62','fd7a:115c:a1e0::1','192.168.1.2']},
            'b':{'HostName':'Offline','Online':False,'TailscaleIPs':['100.68.39.63']},
            'c':{'HostName':'Duplicate','Online':True,'TailscaleIPs':['100.68.39.62']}}}
        with patch('integrations.decks.shutil.which',return_value='/bin/tailscale'),patch('integrations.decks.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(state))),patch.object(self.decks,'_probe',return_value=True) as probe:
            self.decks._discover(8791)
        probe.assert_called_once_with({'name':'Mac','url':'http://100.68.39.62:8791'})
        self.assertEqual(self.decks.status()['discovery']['phase'],'done')
        self.assertEqual(self.decks.status()['discovery']['results'][0]['name'],'Mac')

    def test_saved_project_choice_is_preserved_but_old_default_detects_home_dev(self):
        (self.home/'dev').mkdir()
        settings=self.home/'.config/cc-panel/projects.json'
        settings.write_text(json.dumps({'directory':str(self.home/'projects')}))
        preference=ProjectDirectory(self.home,self.home/'projects')
        self.assertEqual(preference.get(),str(self.home/'dev'))
        preference.save('~/projects')
        self.assertEqual(ProjectDirectory(self.home,self.home/'dev').get(),str(self.home/'projects'))

    def test_network_settings_persist_privately_and_reject_credential_urls(self):
        settings = NetworkSettings(self.home)
        value = settings.save({'name':'Main server','public_url':'https://deck.example.com/'})
        self.assertEqual(value, {'name':'Main server','public_url':'https://deck.example.com'})
        self.assertEqual(NetworkSettings(self.home).get(), value)
        self.assertEqual(settings.path.stat().st_mode & 0o777, 0o600)
        for url in ('https://user:secret@deck.example.com','https://deck.example.com/path','https://deck.example.com?secret=x','javascript:alert(1)','https://deck.example.com:wrong'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                settings.save({'name':'Main server','public_url':url})
        self.assertEqual(NetworkSettings(self.home).get(), value)

    def handler(self,method='GET',origin=True,authorized=True):
        handler=object.__new__(self.panel.Handler)
        handler.path='/deck/'+ID+'/api/sessions'
        handler.command=method
        handler.headers={'Content-Type':'application/json','Content-Length':'2','Cookie':'cc_auth=GATEWAY_SECRET'}
        handler.rfile=io.BytesIO(b'{}')
        handler.authorized=Mock(return_value=authorized)
        handler.same_origin=Mock(return_value=origin)
        handler.language=Mock(return_value='ru')
        handler.send_json=Mock();handler.send_body=Mock()
        return handler

    def test_gateway_authentication_and_origin_checks_precede_remote_transport(self):
        service=self.enterContext(patch.object(self.panel,'remote_decks'))
        for method in ('GET','POST'):
            handler=self.handler(method,authorized=False)
            (handler.get_request if method=='GET' else handler.post_request)()
            service.request.assert_not_called()
        handler=self.handler('POST',origin=False)
        handler.post_request()
        self.assertEqual(handler.send_json.call_args.args[0],403)
        service.request.assert_not_called()
        service.request.return_value=(200,{'Content-Type':'application/json'},b'{"sessions":[]}')
        handler=self.handler()
        handler.get_request()
        service.request.assert_called_once_with(ID,'GET','/api/sessions',None,'ru')
        self.assertNotIn('GATEWAY_SECRET',str(service.request.call_args))
        handler.send_body.assert_called_once_with(200,b'{"sessions":[]}','application/json')

    def test_terminal_html_stays_on_gateway_and_remote_cookies_are_not_forwarded(self):
        service=self.enterContext(patch.object(self.panel,'remote_decks'))
        service.request.return_value=(200,{'Content-Type':'text/html','Set-Cookie':'cc_auth=REMOTE_SECRET'},b'<base href="/t/"><script src="/t/app.js"></script>')
        handler=self.handler();handler.path='/deck/'+ID+'/t/'
        handler.get_request()
        body=handler.send_body.call_args.args[1]
        self.assertIn(('/deck/'+ID+'/t/').encode(),body)
        self.assertNotIn(b'REMOTE_SECRET',body)

    def test_terminal_websocket_uses_remote_cookie_and_strips_response_cookie(self):
        handler=self.handler();handler.path='/deck/'+ID+'/t/ws';handler.headers.update({'Upgrade':'websocket','Sec-WebSocket-Key':'key','Sec-WebSocket-Version':'13'})
        handler.connection=Mock()
        backend=Mock();backend.recv.side_effect=[b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: accepted\r\nSet-Cookie: cc_auth=REMOTE_SECRET\r\n\r\n',b'']
        with patch.object(self.panel,'remote_decks') as service,patch.object(self.panel.select,'select',return_value=([backend],[],[])):
            service.terminal_socket.return_value=(backend,URL,'cc_auth=remote.cookie')
            handler.get_request()
        sent=backend.sendall.call_args.args[0]
        self.assertIn(b'Cookie: cc_auth=remote.cookie',sent)
        self.assertIn(('Origin: '+URL).encode(),sent)
        self.assertNotIn(b'GATEWAY_SECRET',sent)
        reply=handler.connection.sendall.call_args.args[0]
        self.assertIn(b'101 Switching Protocols',reply);self.assertNotIn(b'Set-Cookie',reply)
        backend.close.assert_called_once()
