import http.client
import json
import threading
from unittest.mock import MagicMock, Mock, patch
from urllib.parse import parse_qs, urlsplit

from support import PanelCase
from integrations import lan
from integrations.decks import RemoteDecks, Unreachable
from integrations.lmstudio import LMStudio
from integrations.lan import lan_address as real_lan_address
from integrations.lan import Listener, Pairs, deck_proof, gateway_proof

ID = 'a' * 24
TAIL, LOCAL, OTHER = 'http://100.68.39.62:8790', 'http://192.168.1.20:8790', 'http://192.168.1.77:8790'
PASSWORD = 'test-password-only'
PROFILE = {'name': 'Mac', 'url': TAIL, 'username': 'denis', 'password': PASSWORD}


class FakeDeck:
    """A panel on the other side: signs in by password, hands out pair keys and proves them."""
    def __init__(self, directory, instance='b' * 24, pairing=True):
        self.pairs, self.instance, self.pairing = Pairs(directory / (instance + '.json')), instance, pairing

    def __call__(self, method, path, body, headers):
        route, query = urlsplit(path).path, parse_qs(urlsplit(path).query)
        answer = lambda value, extra=None: (200, extra or {}, json.dumps(value).encode())
        if route == '/login':
            ok = ('password=' + PASSWORD).encode() in body
            return (303, {'Set-Cookie': 'cc_auth=by.password; HttpOnly', 'Location': '/'}, b'') if ok else (401, {}, b'')
        if route == '/api/hello':
            return answer({'app': 'away-deck', 'id': self.instance, 'name': 'Mac  Studio'})
        if route == '/api/pair' and self.pairing:
            return answer({**self.pairs.create(), 'instance': self.instance})
        if route == '/api/pair_challenge' and self.pairing:
            found = self.pairs.challenge(query['id'][0], query['nonce'][0])
            return answer(found) if found else (404, {}, b'{}')
        if route == '/api/pair_login' and self.pairing:
            data = json.loads(body)
            ok = self.pairs.accept(data['id'], data['nonce'], data['proof'])
            return answer({'ok': True}, {'Set-Cookie': 'cc_auth=by.pair; HttpOnly'}) if ok else (401, {}, b'{}')
        if route == '/api/version':
            return answer({'version': '1.44.0'})
        return (404, {}, b'{}') if route.startswith('/api/pair') else answer({'ok': True})


class Network:
    """Which machine answers at which address; an address without one does not accept connections."""
    def __init__(self):
        self.hosts, self.calls, self.connects = {}, [], []

    def __call__(self, url, method, path, body=None, headers=None, timeout=30, limit=0, connect=None):
        self.calls.append((url, method, path, body or b'', headers or {}))
        self.connects.append(connect)
        if url not in self.hosts:
            raise Unreachable('no route')
        return self.hosts[url](method, path, body or b'', headers or {})

    def sent_to(self, url):
        return b' '.join(json.dumps([path, body.decode(), headers]).encode() for target, _, path, body, headers in self.calls if target == url)


class SeveralAddressesTests(PanelCase):
    def setUp(self):
        super().setUp()
        self.net = Network()
        self.enterContext(patch('integrations.decks.http_request', self.net))
        self.mac = FakeDeck(self.home)
        self.net.hosts[TAIL] = self.net.hosts[LOCAL] = self.mac
        self.decks = RemoteDecks(self.home / 'decks', 'http://100.109.113.79:8790', lambda: 'c' * 24, lambda: None)

    def connect(self, **extra):
        self.id = self.decks.save({**PROFILE, **extra})['id']

    def restarted(self):
        return RemoteDecks(self.home / 'decks', 'http://100.109.113.79:8790', lambda: 'c' * 24, lambda: None)

    def test_local_address_takes_over_when_tailscale_is_down_without_ever_getting_the_password(self):
        self.connect(urls=[LOCAL])
        self.assertEqual(self.decks.status()['decks'][0]['urls'], [TAIL, LOCAL])
        self.assertEqual(self.decks.request(self.id, 'GET', '/api/sessions')[0], 200)
        self.assertEqual(self.decks.status()['decks'][0]['route'], TAIL)
        self.assertEqual(self.net.connects[-1], 4)  # Another address waits: this one gets a short connect.
        del self.net.hosts[TAIL]
        self.assertEqual(self.decks.request(self.id, 'POST', '/api/send', b'{}')[0], 200)
        self.assertEqual(self.decks.status()['decks'][0]['route'], LOCAL)
        self.assertNotIn(PASSWORD.encode(), self.net.sent_to(LOCAL))
        # The local address proved the key before the cookie went there.
        local = [path.split('?')[0] for url, _, path, _, _ in self.net.calls if url == LOCAL]
        self.assertEqual(local, ['/api/pair_challenge', '/api/send'])
        # After a restart there is no cookie: the gateway signs in with the key, still without the password.
        again = self.restarted()
        self.assertEqual(again.request(self.id, 'GET', '/api/sessions')[0], 200)
        self.assertNotIn(PASSWORD.encode(), self.net.sent_to(LOCAL))
        self.assertIn(b'by.pair', self.net.sent_to(LOCAL))

    def test_another_machine_at_the_local_address_gets_neither_password_nor_cookie(self):
        self.connect(urls=[LOCAL])
        del self.net.hosts[TAIL]
        self.net.hosts[LOCAL] = FakeDeck(self.home, 'd' * 24)  # The same address in somebody else's network.
        with self.assertRaisesRegex(ValueError, 'Another machine answers'):
            self.decks.request(self.id, 'GET', '/api/sessions')
        sent = self.net.sent_to(LOCAL)
        self.assertNotIn(PASSWORD.encode(), sent)
        self.assertNotIn(b'cc_auth', sent)
        self.assertNotIn(b'/login', sent)
        # A machine that answers 401 to everything does not make the gateway sign in with the password either.
        self.net.hosts[LOCAL] = lambda *args: (401, {}, b'{}')
        self.decks.down.clear()
        with self.assertRaises(ValueError):
            self.decks.request(self.id, 'GET', '/api/sessions')
        self.assertNotIn(PASSWORD.encode(), self.net.sent_to(LOCAL))

    def test_computer_known_only_in_the_local_network(self):
        del self.net.hosts[TAIL]
        self.connect(url=LOCAL)
        logins = lambda: sum(path == '/login' for _, _, path, _, _ in self.net.calls)
        self.assertEqual(logins(), 1)  # The owner's own action: the password goes there once.
        again = self.restarted()
        self.assertEqual(again.request(self.id, 'GET', '/api/sessions')[0], 200)
        self.assertEqual(logins(), 1)
        self.net.hosts[LOCAL] = FakeDeck(self.home, 'd' * 24)
        fresh = self.restarted()
        with self.assertRaisesRegex(ValueError, 'Another machine answers'):
            fresh.request(self.id, 'GET', '/api/sessions')
        self.assertEqual(logins(), 1)

    def test_older_panel_cannot_be_connected_over_the_local_network_and_keeps_one_address_over_tailscale(self):
        self.net.hosts[TAIL] = self.net.hosts[LOCAL] = FakeDeck(self.home, pairing=False)
        with self.assertRaisesRegex(ValueError, 'Update DeckAway on that computer'):
            self.connect(url=LOCAL)
        self.connect(urls=[LOCAL])
        self.assertEqual(self.decks.status()['decks'][0]['urls'], [TAIL])

    def test_own_panel_and_wrong_extra_addresses_are_refused(self):
        self.mac.instance = 'c' * 24
        with self.assertRaisesRegex(ValueError, 'current DeckAway'):
            self.connect()
        self.mac.instance = 'b' * 24
        for wrong in (['http://8.8.8.8:8790'], ['https://192.168.1.20:8790'], 'http://192.168.1.20:8790', [LOCAL] * 2 + [OTHER] * 9 + ['x']):
            with self.subTest(urls=wrong), self.assertRaises(ValueError):
                self.connect(urls=wrong)

    def test_a_single_unreachable_address_fails_as_before_and_a_mutation_is_not_replayed(self):
        self.connect()
        # One address: the full wait, as before. Tailscale needs seconds to reach a machine that just woke up.
        self.decks.request(self.id, 'GET', '/api/sessions')
        self.assertIsNone(self.net.connects[-1])
        del self.net.hosts[TAIL]
        with self.assertRaisesRegex(ValueError, 'did not respond'):
            self.decks.request(self.id, 'POST', '/api/send', b'{}')
        # A failure after the request was sent is ambiguous: it is reported, never sent again elsewhere.
        self.net.hosts[TAIL] = self.mac
        self.decks.profiles[self.id]['urls'] = [LOCAL]
        self.decks.down.clear()
        self.net.hosts[TAIL] = Mock(side_effect=TimeoutError('late'))
        self.decks.cookies[self.id] = 'cc_auth=old'
        before = len(self.net.calls)
        with self.assertRaisesRegex(ValueError, 'did not respond'):
            self.decks.request(self.id, 'POST', '/api/send', b'{}')
        self.assertEqual(len(self.net.calls) - before, 1)

    def test_search_merges_one_computer_seen_on_two_networks_and_extends_connected_ones(self):
        hello = lambda instance, name='Mac': {'instance': instance, 'name': name}
        found = [{'url': LOCAL, **hello('b' * 24, '192.168.1.20')}, {'url': TAIL, **hello('b' * 24)},
                 {'url': OTHER, **hello('e' * 24, 'Red')}, {'url': 'http://192.168.1.5:8790', **hello('c' * 24, 'Me')},
                 {'url': 'http://100.70.0.9:8790', 'name': 'old'}]
        self.assertEqual(self.decks.merged(found), [
            {'name': 'Mac', 'url': TAIL, 'urls': [LOCAL], 'instance': 'b' * 24},
            {'name': 'old', 'url': 'http://100.70.0.9:8790', 'urls': [], 'instance': ''},
            {'name': 'Red', 'url': OTHER, 'urls': [], 'instance': 'e' * 24}])
        self.connect()
        # Connected already: not offered again, and its new address is kept for later.
        self.assertEqual([row['name'] for row in self.decks.merged(found)], ['old', 'Red'])
        self.decks.remember(found)
        self.assertEqual(self.restarted().status()['decks'][0]['urls'], [TAIL, LOCAL])

    def test_search_covers_the_local_network_without_tailscale(self):
        self.decks.local_address = lambda: '192.168.1.5'
        self.net.hosts[LOCAL] = self.mac
        with patch.object(self.decks, 'tailscale_peers', side_effect=ValueError('no tailscale')):
            self.decks._discover(8790)
        self.assertEqual(self.decks.status()['discovery'], {'phase': 'done', 'results': [
            {'name': 'Mac Studio', 'url': LOCAL, 'urls': [], 'instance': 'b' * 24}]})
        self.assertEqual(len({url for url, *_ in self.net.calls}), 253)
        self.decks.local_address = lambda: None
        with patch.object(self.decks, 'tailscale_peers', side_effect=ValueError('no tailscale')):
            self.decks._discover(8790)
        self.assertEqual(self.decks.status()['discovery']['phase'], 'error')


class LanBasicsTests(PanelCase):
    def test_addresses(self):
        self.assertTrue(all(lan.is_lan(a) for a in ('192.168.1.5', '10.0.0.7', '172.20.1.1')))
        self.assertFalse(any(lan.is_lan(a) for a in ('100.68.39.62', '8.8.8.8', '127.0.0.1', '169.254.1.1', 'fd00::1', 'x')))
        self.assertEqual(len(lan.neighbours('192.168.1.5')), 253)
        self.assertNotIn('192.168.1.5', lan.neighbours('192.168.1.5'))
        probe = MagicMock()
        probe.return_value.__enter__.return_value.getsockname.return_value = ('192.168.1.5', 1)
        self.assertEqual(real_lan_address(probe), '192.168.1.5')
        probe.return_value.__enter__.return_value.getsockname.return_value = ('203.0.113.9', 1)
        self.assertIsNone(real_lan_address(probe))  # A server with a public address has no local network.
        probe.return_value.__enter__.return_value.connect.side_effect = OSError()
        self.assertIsNone(real_lan_address(probe))

    def test_pair_key_proves_both_sides_once(self):
        now = [1000]
        pairs = Pairs(self.home / 'pairs.json', lambda: now[0])
        pair = pairs.create()
        self.assertEqual(pairs.path.stat().st_mode & 0o777, 0o600)
        ours = 'a' * 32
        answer = pairs.challenge(pair['id'], ours)
        self.assertEqual(answer['proof'], deck_proof(pair['key'], answer['nonce'], ours))
        proof = gateway_proof(pair['key'], answer['nonce'], ours)
        self.assertFalse(pairs.accept(pair['id'], answer['nonce'], 'b' * 64))
        self.assertFalse(pairs.accept(pair['id'], answer['nonce'], proof))  # The challenge was spent by the wrong answer.
        answer = pairs.challenge(pair['id'], ours)
        self.assertTrue(pairs.accept(pair['id'], answer['nonce'], gateway_proof(pair['key'], answer['nonce'], ours)))
        self.assertFalse(pairs.accept(pair['id'], answer['nonce'], gateway_proof(pair['key'], answer['nonce'], ours)))
        answer = pairs.challenge(pair['id'], ours)
        now[0] += 61
        self.assertFalse(pairs.accept(pair['id'], answer['nonce'], gateway_proof(pair['key'], answer['nonce'], ours)))
        self.assertIsNone(pairs.challenge('0' * 16, ours))
        # The oldest keys make room: the file does not grow with every reconnection.
        for _ in range(20):
            pairs.create()
        self.assertEqual(len(pairs.load()), 16)
        self.assertIsNone(pairs.challenge(pair['id'], ours))

    def test_listener_follows_the_switch_and_the_address(self):
        state = {'on': False, 'address': '192.168.1.5'}
        opened = []
        def serve(address):
            server = Mock(address=address)
            opened.append(server)
            return server
        listener = Listener(lambda: state['on'], serve, '100.109.113.79', lambda: state['address'])
        self.assertIsNone(listener.sync())
        self.assertEqual(opened, [])
        state['on'] = True
        self.assertEqual(listener.sync(), '192.168.1.5')
        listener.sync()
        self.assertEqual(len(opened), 1)
        state['address'] = '10.0.0.8'  # The laptop moved to another network.
        self.assertEqual(listener.sync(), '10.0.0.8')
        opened[0].shutdown.assert_called_once()
        opened[0].server_close.assert_called_once()
        state['on'] = False
        self.assertIsNone(listener.sync())
        opened[1].server_close.assert_called_once()
        self.assertIsNone(listener.status())
        # Nothing to add when the panel already listens everywhere (a container) or on that very address.
        state['on'] = True
        self.assertIsNone(Listener(lambda: True, serve, '0.0.0.0', lambda: '172.17.0.2').sync())
        self.assertIsNone(Listener(lambda: True, serve, '10.0.0.8', lambda: '10.0.0.8').sync())
        self.assertEqual(len(opened), 2)


class ModelSearchTests(PanelCase):
    NODES = [{'HostName': 'gateway', 'TailscaleIPs': ['100.64.0.1']},
             {'HostName': 'RED', 'TailscaleIPs': ['100.64.0.2'], 'CurAddr': '192.168.1.30:41641'},
             {'HostName': 'Far', 'TailscaleIPs': ['100.64.0.3'], 'CurAddr': '203.0.113.5:41641'}]

    def test_one_row_per_server_seen_over_tailscale_and_in_the_local_network(self):
        service = LMStudio(self.home / 'models', lambda: '192.168.1.5')
        self.assertEqual(service.local_names(self.NODES, '192.168.1.5'), {'192.168.1.5': 'gateway', '192.168.1.30': 'RED'})
        row = lambda name, url: {'name': name, 'url': url, 'status': 'online', 'models': []}
        service.job['results'] = [row('RED', 'http://100.64.0.2:1234'), row('192.168.1.30', 'http://192.168.1.30:1234'),
                                  row('192.168.1.30', 'http://192.168.1.30:8080'), row('192.168.1.44', 'http://192.168.1.44:1234')]
        with patch.object(service, 'tailscale_nodes', return_value=self.NODES):
            service.merge_local([1234])
        self.assertEqual([(r['name'], r['url']) for r in service.job['results']], [
            ('RED', 'http://100.64.0.2:1234'),            # The Tailscale row stays; its local twin is gone.
            ('RED', 'http://192.168.1.30:8080'),          # Another server of the same machine, named by Tailscale.
            ('192.168.1.44', 'http://192.168.1.44:1234')])  # A machine without Tailscale.

    def test_local_network_is_searched_without_tailscale_and_only_open_ports_are_asked(self):
        service = LMStudio(self.home / 'models', lambda: '192.168.1.5')
        asked = []
        def connect(pair, timeout):
            if pair != ('192.168.1.30', 1234):
                raise OSError('closed')
            return Mock()
        def models(url, key='', timeout=3):
            asked.append(url)
            return [{'id': 'qwen'}]
        with patch('integrations.lmstudio.socket.create_connection', connect), patch('integrations.lmstudio.models', models), \
                patch.object(service, 'tailscale_nodes', side_effect=ValueError('no tailscale')):
            service._discover([1234])
        self.assertEqual(asked, ['http://192.168.1.30:1234'])
        self.assertEqual((service.job['phase'], [r['url'] for r in service.job['results']]), ('done', ['http://192.168.1.30:1234']))
        nowhere = LMStudio(self.home / 'other', lambda: None)
        with patch.object(nowhere, 'tailscale_nodes', side_effect=ValueError('no tailscale')):
            nowhere._discover([1234])
        self.assertEqual(nowhere.job['phase'], 'error')


class LanHTTPTests(PanelCase):
    def setUp(self):
        super().setUp()
        self.panel.list_sessions = Mock(return_value=[])
        self.enterContext(patch.object(self.panel.Handler, 'log_message'))
        self.enterContext(patch.object(self.panel, 'own_instance', return_value='b' * 24))
        self.enterContext(patch.object(self.panel, 'pairs', Pairs(self.home / 'pairs.json')))
        self.server = self.panel.ThreadingHTTPServer(('127.0.0.1', 0), self.panel.Handler)
        self.server.daemon_threads = True
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(5)))
        self.origin = 'http://127.0.0.1:%d' % self.server.server_address[1]

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request(method, path, body=body, headers={'Content-Type': 'application/json', **(headers or {})})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_gateway_pairs_while_signed_in_and_later_signs_in_with_the_key(self):
        status, _, body = self.request('GET', '/api/hello')
        self.assertEqual((status, json.loads(body)['app'], json.loads(body)['id']), (200, 'away-deck', 'b' * 24))
        self.assertEqual(self.request('POST', '/api/pair', b'{}', {'Origin': self.origin})[0], 401)  # Not without a sign-in.
        # A public domain's proxy does not introduce the computer to the internet.
        self.assertNotEqual(self.request('GET', '/api/hello', headers={'X-Forwarded-For': '203.0.113.9'})[0], 200)
        cookie = 'cc_auth=' + self.panel.make_token()
        status, _, body = self.request('POST', '/api/pair', b'{}', {'Origin': self.origin, 'Cookie': cookie})
        pair = json.loads(body)
        self.assertEqual((status, pair['instance']), (200, 'b' * 24))
        ours = '1' * 32
        status, _, body = self.request('GET', f"/api/pair_challenge?id={pair['id']}&nonce={ours}")
        answer = json.loads(body)
        self.assertEqual(answer['proof'], deck_proof(pair['key'], answer['nonce'], ours))
        login = lambda proof, origin=self.origin: self.request('POST', '/api/pair_login', json.dumps(
            {'id': pair['id'], 'nonce': answer['nonce'], 'proof': proof}).encode(), {'Origin': origin})
        proof = gateway_proof(pair['key'], answer['nonce'], ours)
        self.assertEqual(login(proof, 'http://evil.example')[0], 403)
        status, headers, _ = login(proof)
        self.assertEqual(status, 200)
        signed = headers['Set-Cookie'].split(';', 1)[0]
        self.assertEqual(self.request('GET', '/api/version', headers={'Cookie': signed})[0], 200)
        self.assertEqual(login(proof)[0], 401)  # The same answer does not open the door twice.
        for wrong in ('/api/pair_challenge?id=zz&nonce=' + ours, '/api/pair_challenge?id=' + '0' * 16 + '&nonce=' + ours,
                      f"/api/pair_challenge?id={pair['id']}&nonce=short"):
            self.assertEqual(self.request('GET', wrong)[0], 404)

    def test_wrong_keys_are_rate_limited_like_passwords(self):
        codes = [self.request('POST', '/api/pair_login', b'{"id":"x","nonce":"y","proof":"z"}', {'Origin': self.origin})[0] for _ in range(7)]
        self.assertEqual(codes, [401] * 5 + [429] * 2)

    def test_local_network_clients_are_never_taken_for_the_proxy(self):
        handler = self.panel.Handler.__new__(self.panel.Handler)
        handler.client_address = ('192.168.1.50', 5000)
        handler.headers = {'X-Forwarded-For': '1.1.1.1', 'X-Forwarded-Proto': 'https'}
        handler.server = Mock(lan=False)
        self.assertEqual(handler.client_ip(), '1.1.1.1')
        handler.server = Mock(lan=True)
        self.assertEqual(handler.client_ip(), '192.168.1.50')
        self.assertFalse(handler.is_https())

    def test_switch_is_saved_and_reported(self):
        self.enterContext(patch.object(self.panel.lan, 'lan_address', return_value='192.168.1.5'))
        sync = self.enterContext(patch.object(self.panel.lan_listener, 'sync'))
        self.assertEqual(self.panel.lan_status(), {'lan': False, 'lan_address': None, 'lan_found': '192.168.1.5', 'port': self.panel.BIND_PORT})
        self.assertTrue(self.panel.action_lan_save({'enabled': True})['lan'])
        sync.assert_called_once()
        self.assertTrue(self.panel.network_settings.get()['lan'])
        with self.assertRaises(ValueError):
            self.panel.action_lan_save({'enabled': 'yes'})
        # Installed on the local address itself: it is the only door, shown as on and not switchable.
        with patch.object(self.panel, 'BIND_HOST', '192.168.1.5'):
            self.assertEqual(self.panel.lan_status(), {'lan': True, 'lan_address': '192.168.1.5', 'lan_found': '192.168.1.5',
                                                       'port': self.panel.BIND_PORT, 'fixed': True})
            with self.assertRaisesRegex(ValueError, 'BIND_HOST'):
                self.panel.action_lan_save({'enabled': False})
