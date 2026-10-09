import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import importlib.util
import threading
import time

from support import PanelCase, ROOT
from integrations.decks import RemoteDecks, UnavailableDecks, deck_url, http_request, remote_path
from integrations.preferences import ProjectDirectory, NetworkSettings

ID = 'a'*24
URL = 'http://100.68.39.62:8790'
PROFILE = {'id':ID,'name':'Mac','url':URL,'username':'denis','password':'test-password-only'}


class DeckResponseLimitTests(PanelCase):
    def serve(self, chunks, pause):
        import socket
        listener = socket.socket();listener.bind(('127.0.0.1', 0));listener.listen(1)
        self.addCleanup(listener.close)
        def answer():
            connection = listener.accept()[0]
            try:
                connection.recv(4096)
                connection.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n')
                for chunk in chunks:
                    connection.sendall(chunk);time.sleep(pause)
            except OSError:
                pass
            finally:
                connection.close()
        threading.Thread(target=answer, daemon=True).start()
        return 'http://127.0.0.1:%d' % listener.getsockname()[1]

    def test_a_trickling_deck_is_cut_off_by_the_body_deadline(self):
        url = self.serve([b'x'] * 400, .01)
        started = time.monotonic()
        with self.assertRaisesRegex(ValueError, 'too slowly'):
            http_request(url, 'GET', '/api/sessions', timeout=.5)
        self.assertLess(time.monotonic() - started, 3.5)

    def test_an_oversized_answer_is_refused(self):
        url = self.serve([b'x' * 4096] * 4, 0)
        with self.assertRaisesRegex(ValueError, 'too large'):
            http_request(url, 'GET', '/api/sessions', timeout=2, limit=10000)


class RemoteDeckTests(PanelCase):
    def setUp(self):
        super().setUp()
        self.decks = RemoteDecks(self.home/'decks','http://100.109.113.79:8790')
        self.decks.profiles[ID] = dict(PROFILE)
        self.transport = self.enterContext(patch('integrations.decks.http_request'))

    def test_only_tailnet_ip_origins_and_deck_paths_are_allowed(self):
        self.assertEqual(deck_url(URL+'/'),URL)
        for invalid in ('http://127.0.0.1:8790','http://192.168.1.1','http://example.com','http://100.68.39.62/path',URL+'?a=b',URL+'#x','http://user:pass@100.68.39.62','file:///tmp/x','https://100.68.39.62:8790'):
            with self.subTest(url=invalid), self.assertRaises(ValueError):deck_url(invalid)
        for path in ('/api/sessions?preview=demo','/api/github/repos?refresh=1','/t/ws','/t/?arg=%3Dcc-demo'):
            self.assertEqual(remote_path(path),path)
        for invalid in ('//evil/api/x','https://evil/api/x','/login','/deck/x/api/x','/api/decks','/api/network','/t/../login','/t/%2e%2e/login','/t/ws\r\nHost: evil',
                        '/t/?arg=_keep&arg=%3B&arg=run-shell&arg=id','/t/ws?arg=%3Dcc-demo&arg=x','/t/?arg=cc-a%3Bb'):
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
        self.assertEqual(value, {'name':'Main server','public_url':'https://deck.example.com','isolate_terminals':False})
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
        service.request.assert_called_once_with(ID,'GET','/api/sessions',None,'ru',content_type='application/json')
        self.assertNotIn('GATEWAY_SECRET',str(service.request.call_args))
        handler.send_body.assert_called_once_with(200,b'{"sessions":[]}','application/json')

    def test_streamed_upload_is_relayed_as_raw_bytes_but_other_posts_stay_json_only(self):
        service=self.enterContext(patch.object(self.panel,'remote_decks'))
        service.request_stream.return_value=(200,{'Content-Type':'application/json'},b'{"attachment":"a.png"}')
        handler=self.handler('POST');handler.path='/deck/'+ID+'/api/upload_raw?name=demo&filename=a.png'
        handler.headers.update({'Content-Type':'application/octet-stream','Content-Length':'4'});handler.rfile=io.BytesIO(b'\x89PNG')
        handler.post_request()
        # The body is handed over as the request stream, not read into memory first.
        service.request_stream.assert_called_once_with(ID,'/api/upload_raw?name=demo&filename=a.png',handler.rfile,4,'ru')
        service.request.assert_not_called()
        handler=self.handler('POST');handler.path='/deck/'+ID+'/api/send'
        handler.headers['Content-Type']='application/octet-stream'
        handler.post_request()
        self.assertEqual(handler.send_json.call_args.args[0],403)
        service.request.assert_not_called()

    def test_streamed_upload_refreshes_the_login_first_and_never_replays(self):
        from integrations import decks as module
        service=RemoteDecks(self.home,'http://100.64.0.1:8790')
        service.authentication=Mock(return_value=({'url':'http://100.64.0.2:8790'},'cc_auth=remote'))
        service.request=Mock(return_value=(200,{},b'{}'))
        sent=[]
        def fake(url,method,path,body=None,headers=None,timeout=30,limit=0):
            chunks=[]
            while (chunk:=body.read(3)):chunks.append(chunk)
            sent.append((headers['Content-Length'],b''.join(chunks)))
            return 200,{},b'{"ok":true}'
        with patch.object(module,'http_request',side_effect=fake):
            result=service.request_stream(ID,'/api/upload_raw?name=a&filename=b.png',io.BytesIO(b'0123456789extra'),10)
        self.assertEqual(result[0],200)
        self.assertEqual(sent,[('10',b'0123456789')])  # Exactly the declared length, never the next request.
        service.request.assert_called_once()           # The login refresh happens before any byte is sent.
        with patch.object(module,'http_request',return_value=(401,{},b'')) as transport:
            with self.assertRaisesRegex(ValueError,'retry'):
                service.request_stream(ID,'/api/upload_raw?name=a&filename=b.png',io.BytesIO(b'x'),1)
        transport.assert_called_once()

    def isolation(self, on):
        settings=Mock();settings.get.return_value={'name':'gw','public_url':'','isolate_terminals':on}
        self.enterContext(patch.object(self.panel,'network_settings',settings))
        service=self.enterContext(patch.object(self.panel,'remote_decks'))
        service.status.return_value={'decks':[{'id':ID}]}
        return service

    def isolated(self, path, headers=None, authorized=False, origin=True):
        handler=self.handler(authorized=authorized,origin=origin);handler.path=path;handler.headers.update(headers or {})
        handler.redirect=Mock();handler.send_response=Mock();handler.send_header=Mock();handler.end_headers=Mock()
        handler.wfile=io.BytesIO();handler.proxy_remote_terminal=Mock()
        handler.get_request()
        return handler

    def test_isolated_terminals_move_remote_pages_to_a_sandboxed_signed_path(self):
        service=self.isolation(True)
        handler=self.isolated('/deck/'+ID+'/t/?arg=%3Dcc-api',authorized=True)
        location=handler.redirect.call_args.args[0]
        self.assertRegex(location,'^/deck/'+ID+'/c/[0-9a-f]+\\.[0-9a-f]{64}/t/\\?arg=%3Dcc-api$')
        service.request.assert_not_called()  # Nothing remote is rendered on the gateway origin.
        service.request.return_value=(200,{'Content-Type':'text/html'},b'<script src="/t/x.js"></script>')
        page=self.isolated(location)  # No cookie: the signed path is the credential.
        headers={c.args[0]:c.args[1] for c in page.send_header.call_args_list}
        self.assertTrue(headers['Content-Security-Policy'].startswith('sandbox allow-scripts'))
        self.assertNotIn('allow-same-origin',headers['Content-Security-Policy'])
        self.assertEqual(headers['Referrer-Policy'],'no-referrer')
        prefix=location.split('/t/')[0]
        self.assertEqual(page.wfile.getvalue(),('<script src="'+prefix+'/t/x.js"></script>').encode())
        socket=self.isolated(prefix+'/t/ws',{'Upgrade':'websocket','Origin':'null'})
        socket.proxy_remote_terminal.assert_called_once_with(ID,'/t/ws')
        foreign=self.isolated(prefix+'/t/ws',{'Upgrade':'websocket','Origin':'https://evil.example'},origin=False)
        foreign.proxy_remote_terminal.assert_not_called()
        self.assertEqual(foreign.send_json.call_args.args[0],403)

    def test_signed_terminal_paths_are_bound_to_one_computer_time_and_the_setting(self):
        service=self.isolation(True)
        token=self.panel.terminal_capability(ID)
        for path in ('/deck/'+'b'*24+'/c/'+token+'/t/','/deck/'+ID+'/c/'+self.panel.terminal_capability(ID,now=1)+'/t/',
                     '/deck/'+ID+'/c/'+token[:-1]+('0' if token[-1]!='0' else '1')+'/t/'):
            with self.subTest(path=path):
                self.assertEqual(self.isolated(path).send_json.call_args.args[0],404)
        service.request.assert_not_called()
        self.isolation(False)
        self.assertEqual(self.isolated('/deck/'+ID+'/c/'+token+'/t/').send_json.call_args.args[0],404)

    def test_an_upload_that_ends_early_is_not_forwarded_as_complete(self):
        from integrations.decks import LimitedReader
        reader = LimitedReader(io.BytesIO(b'abc'), 10)
        self.assertEqual(reader.read(), b'abc')
        with self.assertRaises(OSError):
            reader.read()

    def test_isolated_terminal_signatures_never_reach_the_log(self):
        handler=self.handler();handler.client_ip=Mock(return_value='100.64.0.9')
        token=self.panel.terminal_capability(ID)
        with patch('builtins.print') as printed:
            handler.log_message('"%s" %s %s', f'GET /deck/{ID}/c/{token}/t/ws HTTP/1.1', '101', '-')
        line=printed.call_args.args[0]
        self.assertNotIn(token,line)
        self.assertIn(f'/deck/{ID}/c/***/t/ws',line)

    def test_logging_out_ends_every_isolated_terminal_link(self):
        epoch=self.home/'terminal-epoch'
        self.enterContext(patch.object(self.panel,'TERMINAL_EPOCH',str(epoch)))
        token=self.panel.terminal_capability(ID)
        self.assertTrue(self.panel.capability_valid(ID,token))
        self.panel.revoke_terminal_links()
        self.assertFalse(self.panel.capability_valid(ID,token))
        self.assertTrue(self.panel.capability_valid(ID,self.panel.terminal_capability(ID)))
        self.assertEqual(epoch.stat().st_mode & 0o777, 0o600)

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

    def test_https_is_rejected_with_a_concrete_reason(self):
        with self.assertRaisesRegex(ValueError, 'https:// is not supported'):
            deck_url('https://100.68.39.62:8790')

    def test_remote_api_must_answer_json_and_html_is_not_relayed(self):
        service=self.enterContext(patch.object(self.panel,'remote_decks'))
        for ctype in ('text/html','application/javascript','application/jsonp',None):
            with self.subTest(ctype=ctype):
                service.request.return_value=(200,{'Content-Type':ctype} if ctype else {},b'<script>alert(1)</script>')
                handler=self.handler();handler.get_request()
                handler.send_body.assert_not_called()
                self.assertEqual(handler.send_json.call_args.args[0],502)
        service.request.return_value=(400,{'Content-Type':'application/json; charset=utf-8'},b'{"error":"x"}')
        handler=self.handler();handler.get_request()
        handler.send_body.assert_called_once_with(400,b'{"error":"x"}','application/json; charset=utf-8')

    def test_corrupt_configuration_fails_soft_without_overwriting(self):
        directory=self.home/'.config/cc-panel/integrations'
        directory.mkdir(parents=True)
        target=self.home/'real.json';target.write_text('{}')
        for content in ('[]','{"x":1}','{"x":{"id":"x"}}','not json',None):
            with self.subTest(content=content):
                path=directory/'decks.json'
                if path.exists() or path.is_symlink():path.unlink()
                if content is None:path.symlink_to(target)
                else:path.write_text(content)
                with self.assertRaises(ValueError):RemoteDecks(directory,'http://127.0.0.1:8790')
                spec=importlib.util.spec_from_file_location('isolated_panel_decks',ROOT/'panel/panel.py')
                panel=importlib.util.module_from_spec(spec)
                with patch('builtins.print') as output:spec.loader.exec_module(panel)
                self.assertIsInstance(panel.remote_decks,UnavailableDecks)
                self.assertEqual(panel.remote_decks.status()['decks'],[])
                self.assertIn(str(path),output.call_args.args[0])
                with self.assertRaisesRegex(ValueError,'decks.json'):panel.remote_decks.save(PROFILE)
                if content is not None:self.assertEqual(path.read_text(),content)

    def test_parallel_requests_share_one_login(self):
        def login(profile):
            time.sleep(.1)
            return 'cc_auth=fresh'
        login_mock=self.enterContext(patch.object(self.decks,'login',side_effect=login))
        cookies=[]
        threads=[threading.Thread(target=lambda:cookies.append(self.decks.authentication(ID)[1])) for _ in range(5)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(5)
        self.assertEqual(login_mock.call_count,1)
        self.assertEqual({c.split(';')[0] for c in cookies},{'cc_auth=fresh'})
        # A request that saw an older cookie rejected reuses the newer one instead of logging in again.
        self.decks.authentication(ID,stale='cc_auth=old')
        self.assertEqual(login_mock.call_count,1)
        self.decks.authentication(ID,stale='cc_auth=fresh')
        self.assertEqual(login_mock.call_count,2)

    def test_terminal_websocket_transport_error_after_upgrade_sends_no_http_error(self):
        handler=self.handler();handler.path='/deck/'+ID+'/t/ws';handler.headers.update({'Upgrade':'websocket','Sec-WebSocket-Key':'key','Sec-WebSocket-Version':'13'})
        handler.connection=Mock()
        backend=Mock();backend.recv.side_effect=[b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n',ConnectionResetError()]
        with patch.object(self.panel,'remote_decks') as service,patch.object(self.panel.select,'select',return_value=([backend],[],[])):
            service.terminal_socket.return_value=(backend,URL,'cc_auth=remote.cookie')
            handler.get_request()
        handler.send_json.assert_not_called()
        self.assertEqual(handler.connection.sendall.call_count,1)
        backend.close.assert_called_once()

    def test_gateway_relays_downloads_as_attachments_named_by_the_request(self):
        service=self.enterContext(patch.object(self.panel,'remote_decks'))
        service.request.return_value=(200,{'Content-Type':'application/octet-stream','Content-Disposition':'inline; filename=x.html'},b'%PDF-1.7')
        handler=self.handler();handler.path='/deck/'+ID+'/api/download?name=demo&path=%2Fhome%2Fd%2Fplan.pdf';handler.send_download=Mock()
        handler.get_request()
        handler.send_download.assert_called_once_with('plan.pdf',b'%PDF-1.7')
        service.request.return_value=(200,{'Content-Type':'text/html'},b'<script>')
        handler=self.handler();handler.path='/deck/'+ID+'/api/download?path=%2Fa.html';handler.send_download=Mock()
        handler.get_request()
        handler.send_download.assert_not_called();self.assertEqual(handler.send_json.call_args.args[0],502)

    def test_local_download_resolves_screen_paths_from_the_agent_folder(self):
        handler=self.handler();handler.path='/api/download?name=demo&path=docs%2Fplan.pdf';handler.send_download=Mock()
        tmux=lambda *args,**kw:'/home/demo/project\n' if 'display-message' in args else ''
        with patch.object(self.panel,'session_exists',return_value=True),patch.object(self.panel,'tmux',side_effect=tmux),\
             patch('integrations.files.read_download',return_value=('plan.pdf',b'%PDF')) as read:
            handler.get_request()
        self.assertEqual(read.call_args.args[1],'/home/demo/project/docs/plan.pdf')
        handler.send_download.assert_called_once_with('plan.pdf',b'%PDF')
        with patch('integrations.files.read_download',side_effect=FileNotFoundError('Файл не найден')):
            handler=self.handler();handler.path='/api/download?path=%2Fnope.pdf';handler.get_request()
        handler.send_json.assert_called_once_with(400,{'error':'Файл не найден'})
        handler=object.__new__(self.panel.Handler);handler.send_response=Mock();handler.send_header=Mock();handler.end_headers=Mock();handler.wfile=io.BytesIO()
        handler.send_download('план <1>.pdf',b'%PDF')
        headers=dict(c.args for c in handler.send_header.call_args_list)
        self.assertEqual(headers['Content-Disposition'],"attachment; filename*=UTF-8''%D0%BF%D0%BB%D0%B0%D0%BD%20%3C1%3E.pdf")
        self.assertEqual((headers['Content-Type'],headers['X-Content-Type-Options']),('application/octet-stream','nosniff'))
        self.assertIn('sandbox',headers['Content-Security-Policy'])

    def test_gateway_passes_raster_images_only_from_the_image_endpoint(self):
        service=self.enterContext(patch.object(self.panel,'remote_decks'))
        png=b'\x89PNG\r\n\x1a\n'+b'x'*10
        service.request.return_value=(200,{'Content-Type':'image/png'},png)
        handler=self.handler();handler.path='/deck/'+ID+'/api/image?name=demo&path=%2Ftmp%2Fa.png';handler.send_image=Mock()
        handler.get_request()
        handler.send_image.assert_called_once_with(png,'image/png')
        for path,ctype in (('/api/image?name=demo&path=x.svg','image/svg+xml'),('/api/images?x=1','image/png'),('/api/sessions','image/png'),('/api/image?name=d&path=a.png','text/html')):
            with self.subTest(path=path,ctype=ctype):
                service.request.return_value=(200,{'Content-Type':ctype},b'<svg onload=alert(1)>')
                handler=self.handler();handler.path='/deck/'+ID+path;handler.send_image=Mock()
                handler.get_request()
                handler.send_image.assert_not_called();handler.send_body.assert_not_called()
                self.assertEqual(handler.send_json.call_args.args[0],502)
