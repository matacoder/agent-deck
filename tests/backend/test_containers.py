import http.client
import importlib.util
import json
import os
import socket
import stat
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from support import PanelCase, ROOT
sys.path.insert(0, str(ROOT))
from integrations import containers
from integrations.containers import Containers, context_name

DECK = 'a' * 24


class FakeEngine:
    """A Docker socket: /info answers as the engine does, /echo returns what it was sent after the sender's end closes."""
    def __init__(self, path):
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(path))
        self.server.listen(8)
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while True:
            try:
                link, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(link,), daemon=True).start()

    def serve(self, link):
        with link:
            head, rest = containers.read_head(link)
            if head.startswith('GET /info'):
                body = json.dumps({'ServerVersion': '28.3.3', 'NCPU': 16, 'MemTotal': 64 * 2**30}).encode()
                return link.sendall(b'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n' + body)
            link.sendall(b'HTTP/1.1 200 OK\r\n\r\n')
            while True:
                chunk = link.recv(4096)
                if not chunk:
                    break
                rest += chunk
            link.sendall(rest + b' done')


class FakeDecks:
    """The gateway's saved connection to the panel under test."""
    def __init__(self, address, cookie):
        self.url, self.cookie = 'http://%s:%d' % address, cookie
        self.logins = 0

    def status(self):
        return {'decks': [{'id': DECK, 'name': 'Red PC', 'url': self.url, 'username': 'test-user'}]}

    def authentication(self, identity, language='en', stale=None):
        self.logins += stale is not None
        return {'url': self.url}, self.cookie

    def request(self, identity, method, path, body=None, timeout=5, limit=None):
        connection = http.client.HTTPConnection(self.url[7:], timeout=timeout)
        try:
            connection.request(method, path, headers={'Cookie': self.cookie})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()


class TunnelTests(PanelCase):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(self.panel.Handler, 'log_message'))
        self.server = self.panel.ThreadingHTTPServer(('127.0.0.1', 0), self.panel.Handler)
        self.server.daemon_threads = True
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(timeout=5)))
        engine = self.home / 'engine.sock'
        self.engine = FakeEngine(engine)
        self.addCleanup(self.engine.server.close)
        # The panel under test is the machine with Docker; `gateway` is the other computer that uses it.
        self.host = Containers(self.home / 'host', self.home / 'host-sockets', lambda: None, home=self.home,
                               environ={'DOCKER_HOST': 'unix://' + str(engine)})
        self.panel._containers = self.host
        self.decks = FakeDecks(self.server.server_address, self.login())
        self.gateway = Containers(self.home / 'gateway', self.home / 'docker', lambda: self.decks, home=self.home,
                                  environ={'XDG_RUNTIME_DIR': str(self.home / 'none')})
        self.enterContext(patch.object(containers.shutil, 'which', return_value=None))

    def request(self, path, headers=None, method='GET', body=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def login(self):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request('POST', '/login', urlencode({'username': 'test-user', 'password': 'test-password-only'}),
                               {'Content-Type': 'application/x-www-form-urlencoded'})
            response = connection.getresponse()
            response.read()
            return response.getheader('Set-Cookie').split(';', 1)[0]
        finally:
            connection.close()

    def through(self, payload):
        link = containers.connect_unix(str(self.gateway.socket_path(DECK)))
        try:
            link.sendall(b'POST /echo HTTP/1.1\r\nHost: docker\r\n\r\n')
            head, rest = containers.read_head(link)
            link.sendall(payload)
            link.shutdown(socket.SHUT_WR)
            while True:
                chunk = link.recv(4096)
                if not chunk:
                    return head, rest
                rest += chunk
        finally:
            link.close()

    def test_marked_computer_lends_docker_through_a_local_socket(self):
        machine = self.gateway.refresh()['machines'][0]
        self.assertEqual((machine['name'], machine['address'], machine['host'], machine['state']), ('Red PC', '127.0.0.1', False, 'ok'))
        self.assertEqual(machine['docker'], {'version': '28.3.3', 'cpus': 16, 'memory': 64 * 2**30})
        self.assertFalse(self.gateway.socket_path(DECK).exists())
        self.assertEqual(self.gateway.environment(), {})
        with self.assertRaisesRegex(ValueError, 'не отмечен'):
            self.gateway.save({'use': DECK})

        status, body = self.request('/api/containers_save', {'Cookie': self.decks.cookie, 'Content-Type': 'application/json'},
                                    'POST', json.dumps({'host': True}))
        self.assertEqual((status, json.loads(body)['containers']['host']), (200, True))
        self.assertTrue(self.gateway.refresh()['machines'][0]['host'])
        path = self.gateway.socket_path(DECK)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        head, body = self.through(b'ping')
        self.assertIn('200 OK', head)
        self.assertEqual(body, b'ping done')  # The half-close reached the engine and its answer came back.

        self.assertEqual(self.gateway.save({'use': DECK})['use'], DECK)
        self.assertEqual(self.gateway.environment(), {'DOCKER_HOST': 'unix://' + str(path)})
        note = json.loads(path.with_suffix('.json').read_text())
        self.assertEqual(note, {'name': 'Red PC', 'address': '127.0.0.1', 'local': ''})
        self.assertEqual(Containers(self.home / 'gateway', self.home / 'docker', lambda: self.decks).use, DECK)

    def test_unmarked_or_silent_computer_answers_as_docker_would(self):
        self.host.save({'host': True})
        self.gateway.refresh()
        self.host.save({'host': False})
        link = containers.connect_unix(str(self.gateway.socket_path(DECK)))
        self.addCleanup(link.close)
        link.sendall(b'GET /_ping HTTP/1.1\r\nHost: docker\r\n\r\n')
        head, body = containers.read_head(link)
        self.assertIn('502', head)
        self.assertIn('Red PC', json.loads(body)['message'])
        self.assertIn('not marked', json.loads(body)['message'])
        # The computer answers that it is no longer marked: its socket goes away.
        self.gateway.refresh()
        self.assertFalse(self.gateway.socket_path(DECK).exists())
        self.assertEqual(self.gateway.listeners, {})

    def test_sleeping_computer_keeps_its_socket(self):
        self.host.save({'host': True})
        self.gateway.refresh()
        self.decks.request = Mock(side_effect=ValueError('Remote Away Deck did not respond'))
        machine = self.gateway.refresh()['machines'][0]
        self.assertEqual((machine['state'], machine['host']), ('offline', True))
        self.assertTrue(self.gateway.socket_path(DECK).exists())

    def test_tunnel_needs_login_same_origin_and_the_mark(self):
        origin = 'http://%s:%d' % self.server.server_address
        headers = {'Cookie': self.decks.cookie, 'Upgrade': containers.UPGRADE, 'Connection': 'Upgrade', 'Origin': origin}
        self.assertEqual(self.request('/api/docker_tunnel', {**headers, 'Cookie': 'x=1'})[0], 401)
        self.assertEqual(self.request('/api/docker_tunnel', {**headers, 'Origin': 'http://sibling.test'})[0], 403)
        self.assertEqual(self.request('/api/docker_tunnel', {k: v for k, v in headers.items() if k != 'Origin'})[0], 403)
        self.assertEqual(self.request('/api/docker_tunnel', {**headers, 'Upgrade': 'websocket'})[0], 403)
        status, body = self.request('/api/docker_tunnel', headers)
        self.assertEqual(status, 409)
        self.assertIn('not marked', json.loads(body)['error'])

    def test_marking_needs_a_running_docker(self):
        without = Containers(self.home / 'other', self.home / 'other-sockets', lambda: None, home=self.home,
                             environ={'XDG_RUNTIME_DIR': str(self.home / 'none')})
        with patch.object(containers, 'engine_paths', return_value=[str(self.home / 'missing.sock')]):
            with self.assertRaisesRegex(ValueError, 'не отвечает'):
                without.save({'host': True})
            self.assertEqual(without.local(), {'host': False, 'docker': None})
        for wrong in ({'host': 'yes'}, {'use': 5}):
            with self.assertRaises(ValueError):
                self.host.save(wrong)

    def test_new_agent_gets_the_chosen_computer_in_its_command(self):
        self.assertEqual(self.panel.with_containers('claude --session-id x'), 'claude --session-id x')
        self.host.save({'host': True})
        self.gateway.refresh()
        self.gateway.save({'use': DECK})
        self.panel._containers = self.gateway
        command = self.panel.with_containers('claude --session-id x')
        self.assertEqual(command, 'DOCKER_HOST=unix://%s claude --session-id x' % self.gateway.socket_path(DECK))
        self.assertIsNone(self.panel.with_containers(None))  # A plain terminal has no agent command.


class ContextTests(PanelCase):
    def service(self, rows):
        calls = []
        def run(args, **kwargs):
            self.assertNotIn('DOCKER_HOST', kwargs['env'])
            calls.append(args[2:])
            out = '\n'.join(json.dumps(row) for row in rows) if args[2] == 'ls' else ''
            return SimpleNamespace(returncode=0, stdout=out, stderr='')
        service = Containers(self.home / 'c', self.home / 'docker', lambda: None, home=self.home,
                             environ={'DOCKER_HOST': 'unix:///run/user/1/docker.sock', 'PATH': '/usr/bin'}, run=run)
        return service, calls

    def test_contexts_follow_marked_computers_and_foreign_ones_are_left_alone(self):
        rows = [{'Name': 'default', 'Description': 'Current DOCKER_HOST based configuration', 'DockerEndpoint': 'unix:///x'},
                {'Name': 'red-pc', 'Description': 'my own', 'DockerEndpoint': 'ssh://red'},
                {'Name': 'old-mac', 'Description': 'Away Deck: Old Mac', 'DockerEndpoint': 'unix:///gone'}]
        service, calls = self.service(rows)
        service.machines = {DECK: {'id': DECK, 'name': 'Red PC', 'host': True}, 'b' * 24: {'id': 'b' * 24, 'name': 'Air', 'host': False}}
        service.listeners = {DECK: None}
        with patch.object(containers.shutil, 'which', return_value='/usr/bin/docker'):
            service.sync_contexts()
            endpoint = 'host=unix://' + str(service.socket_path(DECK))
            self.assertEqual(calls, [['ls', '--format', '{{json .}}'], ['rm', '-f', 'old-mac'],
                                     ['create', 'red-pc-2', '--description', 'Away Deck: Red PC', '--docker', endpoint]])
            service.sync_contexts()
            self.assertEqual(len(calls), 3)  # Nothing changed: Docker is not asked again.

    def test_context_names(self):
        self.assertEqual(context_name('MacBook Pro (Denis)', set()), 'macbook-pro-denis')
        self.assertEqual(context_name('Сервер', set()), 'away-deck')
        self.assertEqual(context_name('default', set()), 'default-2')
        self.assertEqual(context_name('red', {'red', 'red-2'}), 'red-3')


class HookNoteTests(PanelCase):
    def test_agent_is_told_where_its_containers_run(self):
        spec = importlib.util.spec_from_file_location('session_hook_containers', ROOT / 'panel/session_hook.py')
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        directory = self.home / '.config/cc-panel/docker'
        directory.mkdir(parents=True)
        sock = 'unix://' + str(directory / (DECK + '.sock'))
        self.assertIsNone(hook.containers_note({'DOCKER_HOST': 'unix:///run/user/1000/docker.sock'}))
        self.assertIsNone(hook.containers_note({'DOCKER_HOST': sock}))  # The panel wrote nothing: say nothing.
        (directory / (DECK + '.json')).write_text(json.dumps({'name': 'Red PC', 'address': '100.64.0.9',
                                                               'local': 'unix:///run/user/1000/docker.sock'}))
        note = hook.containers_note({'DOCKER_HOST': sock})
        for expected in ('Red PC (100.64.0.9)', 'http://100.64.0.9:<port>', 'DOCKER_HOST=unix:///run/user/1000/docker.sock docker', 'bind mounts'):
            self.assertIn(expected, note)
        self.assertNotIn('{', note)
        (directory / (DECK + '.json')).write_text(json.dumps({'name': 'Red PC', 'address': '', 'local': ''}))
        self.assertIn('no Docker of its own', hook.containers_note({'DOCKER_HOST': sock}))
