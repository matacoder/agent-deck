import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from integrations.lmstudio import LMStudio, endpoint, RemoteError, request
from integrations.relay import Relay, LoopbackHTTPServer, read_json


class LMStudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'private'
        self.service = LMStudio(self.directory)
        self.requests = []
        owner = self
        class Fake(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                owner.requests.append((self.path, self.headers.get('Authorization')))
                if self.headers.get('Authorization') != 'Bearer test-secret':
                    self.send_response(401);self.end_headers();return
                self.respond({'models':[{'key':'local-model','loaded_instances':[{'config':{'context_length':8192}}],'capabilities':{'trained_for_tool_use':True}}]})
            def respond(self, data):
                raw = json.dumps(data).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append((self.path, self.headers.get('Authorization'), body))
                if self.path == '/v1/messages' and body.get('stream'):
                    raw = b'data: {"type":"message_start","message":{"usage":{"input_tokens":8,"output_tokens":0}}}\n\ndata: {"type":"content_block_delta","delta":{"text":"OK"}}\n\ndata: {"type":"message_delta","usage":{"output_tokens":12}}\n\n'
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
                elif self.path == '/v1/messages':
                    self.respond({'content':[{'type':'tool_use','name':'deck_healthcheck','input':{'ok':True}}]})
                else:
                    self.respond({'stats':{'tokens_per_second':42,'time_to_first_token_seconds':0.2,'total_output_tokens':20}})
        self.server = LoopbackHTTPServer(('127.0.0.1',0),Fake)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.url = 'http://127.0.0.1:'+str(self.server.server_port)

    def profile(self):
        return self.service.save({'name':'Workstation','url':self.url,'key':'test-secret'})

    def test_private_storage_and_secret_redaction(self):
        p = self.profile()
        self.assertNotIn('test-secret',json.dumps(self.service.status()))
        self.assertTrue(p['key_saved'])
        self.assertEqual(self.service.path.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.directory.stat().st_mode & 0o777,0o700)
        self.service.save({'id':p['id'],'name':'Renamed','url':self.url,'key':''})
        self.assertEqual(LMStudio(self.directory).get(p['id'])['key'],'test-secret')
        self.service.save({'id':p['id'],'name':'Renamed','url':self.url,'clear_key':True})
        self.assertFalse(self.service.status()['profiles'][0]['key_saved'])

    def test_probe_tool_test_and_separate_benchmark(self):
        p = self.profile();p = self.service.probe(p['id'])
        self.assertEqual(p['status'],'online')
        self.assertEqual(p['models'][0]['context_length'],8192)
        self.assertFalse(p['models'][0]['tool_tested'])
        data = {'id':p['id'],'model':'local-model'}
        self.assertTrue(self.service.test(data)['result']['ok'])
        self.assertTrue(self.service.get(p['id'])['models'][0]['tool_tested'])
        result = self.service.benchmark(data)
        self.assertEqual(result['profile']['performance']['source'],'benchmark')
        self.assertEqual(result['profile']['performance']['tokens_per_second'],42)
        self.service.record(p['id'],'local-model',{'output_tokens':5})
        saved=self.service.get(p['id'])
        self.assertEqual(saved['measurements']['benchmark']['local-model']['tokens_per_second'],42)
        self.assertEqual(saved['measurements']['session']['local-model']['output_tokens'],5)
        self.assertNotIn('model_load_time_seconds',result['profile']['performance'])
        self.assertFalse(self.requests[-1][2]['store'])

    def test_authentication_failure_and_endpoint_reset(self):
        p = self.service.save({'name':'Locked','url':self.url})
        self.assertEqual(self.service.probe(p['id'])['status'],'needs_key')
        self.service.record(p['id'],'local-model',{'tokens_per_second':float('nan'),'input_tokens':True,'output_tokens':5})
        self.assertNotIn('tokens_per_second',self.service.get(p['id'])['performance'])
        changed = self.service.save({'id':p['id'],'name':'Other','url':self.url+'/other'})
        self.assertEqual(changed['models'],[])
        self.assertEqual(changed['performance'],{})

    def test_urls_and_symlinks(self):
        for value in ('file:///tmp/a','http://user:pass@host','https://host?q=secret','http://host:70000','http://host\n'):
            with self.assertRaises(ValueError):endpoint(value)
        self.assertEqual(endpoint('http://[::1]:1234/'),'http://[::1]:1234')
        link = Path(self.temp.name)/'link';link.symlink_to(self.directory)
        with self.assertRaises(ValueError):LMStudio(link)

    def test_relay_preserves_stream_authentication_and_session_measurements(self):
        p = self.profile();relay = Relay(self.directory,self.service);binding = relay.bindings.create(p,'local-model');relay.start()
        self.addCleanup(relay.server.server_close);self.addCleanup(relay.server.shutdown)
        config = read_json(relay.config,{})
        path = '/providers/'+binding+'/v1/messages?beta=true'
        def call(model='local-model', token=None):
            c=http.client.HTTPConnection('127.0.0.1',config['port'],timeout=3)
            c.request('POST',path,json.dumps({'model':model,'stream':True}),{'Authorization':'Bearer '+(token or config['token'])})
            r=c.getresponse();status=r.status;body=r.read();c.close();return status,body
        self.assertEqual(call(token='wrong')[0],401)
        self.assertEqual(call(model='different')[0],400)
        status,body=call();self.assertEqual(status,200);self.assertIn(b'content_block_delta',body)
        self.assertEqual(self.requests[-1][1],'Bearer test-secret')
        performance = self.service.get(p['id'])['performance']
        self.assertEqual(performance['source'],'session')
        self.assertEqual(performance['output_tokens'],12)
        self.assertEqual(performance['input_tokens'],8)
        self.assertEqual(self.service.get(p['id'])['measurements']['session']['local-model']['output_tokens'],12)
        self.assertNotIn('text',json.dumps(performance))
        self.assertEqual(relay.bindings.get(binding)['url'],self.url)

    def test_discovery_only_checks_known_tailnet_ips(self):
        peers = {'Self':{'HostName':'self','TailscaleIPs':['192.168.1.1']},'Peer':{'a':{'HostName':'good','TailscaleIPs':['100.64.1.2','fd7a:115c:a1e0::2']},'b':{'TailscaleIPs':['8.8.8.8']}}}
        result = type('Result',(),{'stdout':json.dumps(peers)})()
        with patch('integrations.lmstudio.shutil.which',return_value='tailscale'),patch('integrations.lmstudio.subprocess.run',return_value=result),patch('integrations.lmstudio.models',return_value=[]) as probe:
            self.service._discover([1234])
        self.assertEqual(probe.call_count,1)
        self.assertEqual(probe.call_args.args[0],'http://100.64.1.2:1234')
        self.assertEqual(self.service.status()['discovery']['total'],1)
        for ports in ([True],[0],[1234]*9):
            with self.assertRaises(ValueError):self.service.discover({'ports':ports})

    def test_key_is_not_carried_to_a_different_server(self):
        p = self.profile()
        changed = self.service.save({'id':p['id'],'name':'Different','url':'http://127.0.0.1:1'})
        self.assertFalse(changed['key_saved'])
        self.assertEqual(self.service.get(p['id'])['key'],'')

    def test_relay_challenge_does_not_require_sending_the_relay_secret(self):
        import hmac
        relay=Relay(self.directory,self.service);relay.start()
        self.addCleanup(relay.server.server_close);self.addCleanup(relay.server.shutdown)
        config=read_json(relay.config,{})
        nonce='a'*32
        c=http.client.HTTPConnection('127.0.0.1',config['port'],timeout=3)
        c.request('GET','/health/'+nonce)
        r=c.getresponse();proof=json.loads(r.read())['proof'];c.close()
        self.assertEqual(proof,hmac.new(config['token'].encode(),nonce.encode(),'sha256').hexdigest())
        self.assertNotIn(config['token'],proof)

    def test_relay_start_does_not_wait_for_reverse_dns(self):
        relay=Relay(self.directory,self.service)
        with patch('socket.getfqdn',side_effect=AssertionError('Reverse DNS must not block relay startup')):
            relay.start()
        self.addCleanup(relay.server.server_close);self.addCleanup(relay.server.shutdown)
        self.assertEqual(relay.server.server_name,'127.0.0.1')
        self.assertGreater(relay.server.server_port,0)
