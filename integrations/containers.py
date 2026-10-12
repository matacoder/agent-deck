"""Containers on another computer: a machine marked for containers lends its Docker engine to the others.

The marked machine's panel pipes an authenticated connection into its Docker socket. Every other panel
keeps a local socket per such machine (and a Docker context named after it) that leads into that pipe,
so `docker` and `docker compose` work unchanged. No SSH and no keys: the panels already trust each other.
"""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from .gateway import FAILURES, each, get_json
from .relay import private_write, read_json

TUNNEL, UPGRADE = '/api/docker_tunnel', 'away-deck-docker'
MARK = 'Away Deck: '   # Only contexts described this way are ever updated or removed.
REFRESH = 30
START_EVERY = 60   # Docker Desktop takes this long to come up; asking again sooner only opens it twice.
START_WAIT = 60
DESKTOP_EXE = '/mnt/c/Program Files/Docker/Docker/Docker Desktop.exe'
SOCKET = re.compile(r'[0-9a-f]{24}\.sock\Z')


def engine_paths(home, environ, skip):
    runtime = environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
    host = environ.get('DOCKER_HOST', '')
    found = [host[7:]] if host.startswith('unix://') else []
    found += [runtime + '/docker.sock'] + [str(Path(home) / tail) for tail in (
        '.docker/run/docker.sock', '.orbstack/run/docker.sock', '.colima/default/docker.sock', '.rd/docker.sock')]
    # A panel started inside a session would find the pipe to another machine instead of its own engine.
    return [path for path in found + ['/var/run/docker.sock'] if Path(path).parent != Path(skip)]


def start_command(home, environ, run, platform=sys.platform):
    """How this computer's own Docker is started without a password, or None when the panel cannot."""
    if platform == 'darwin':
        for app in ('Docker', 'OrbStack'):
            if any((Path(root) / (app + '.app')).is_dir() for root in ('/Applications', Path(home) / 'Applications')):
                return ['open', '-ga', app]
        return ['colima', 'start'] if shutil.which('colima', path=environ.get('PATH')) else None
    try:
        # Rootless Docker is a user service; the system one needs root, which the panel never has.
        if run(['systemctl', '--user', 'cat', 'docker.service'], input='', capture_output=True, text=True, timeout=5).returncode == 0:
            return ['systemctl', '--user', 'start', 'docker.service']
    except (OSError, subprocess.SubprocessError):
        pass
    # Windows: the panel lives in WSL and Docker Desktop is a Windows program.
    return [DESKTOP_EXE] if environ.get('WSL_DISTRO_NAME') and os.path.isfile(DESKTOP_EXE) else None


def connect_unix(path, timeout=5):
    link = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    link.settimeout(timeout)
    try:
        link.connect(path)
    except OSError:
        link.close()
        raise
    return link


def read_head(link, limit=65536):
    """Bytes up to the end of the HTTP head and whatever arrived after it."""
    data = b''
    while b'\r\n\r\n' not in data:
        chunk = link.recv(4096)
        if not chunk or len(data) > limit:
            raise ValueError('Invalid answer from Docker or Away Deck')
        data += chunk
    head, rest = data.split(b'\r\n\r\n', 1)
    return head.decode('latin-1'), rest


def engine_info(path):
    link = connect_unix(path)
    try:
        link.sendall(b'GET /info HTTP/1.0\r\nHost: docker\r\n\r\n')
        body = b''
        while len(body) < 4 * 1024 * 1024:
            chunk = link.recv(65536)
            if not chunk:
                break
            body += chunk
    finally:
        link.close()
    head, _, raw = body.partition(b'\r\n\r\n')
    if b' 200 ' not in head.split(b'\r\n', 1)[0]:
        raise ValueError('Docker did not answer')
    data = json.loads(raw)
    return {'version': str(data.get('ServerVersion', ''))[:40], 'cpus': int(data.get('NCPU') or 0),
            'memory': int(data.get('MemTotal') or 0)}


def pump(first, second):
    """Bytes both ways until both sides finish; a half-close is passed on, as `docker run -i` needs."""
    def copy(source, target):
        try:
            while True:
                chunk = source.recv(65536)
                if not chunk:
                    break
                target.sendall(chunk)
            target.shutdown(socket.SHUT_WR)
        except OSError:
            # A broken side must not leave the other direction waiting forever.
            for link in (source, target):
                try:
                    link.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
    back = threading.Thread(target=copy, args=(second, first), daemon=True)
    back.start()
    copy(first, second)
    back.join()


def context_name(name, taken):
    base = re.sub(r'[^a-z0-9_.-]+', '-', name.lower()).strip('-.') or 'away-deck'
    candidate, number = base, 2
    while candidate in taken or candidate == 'default':
        candidate, number = f'{base}-{number}', number + 1
    return candidate


class Containers:
    def __init__(self, directory, sockets, decks, home=None, environ=None, run=subprocess.run, spawn=subprocess.Popen,
                 pause=time.sleep):
        self.path = Path(directory) / 'containers.json'
        self.sockets = Path(sockets)
        self.decks = decks  # Callable returning the connected-decks service, which the panel may replace.
        self.home, self.environ, self.run = home or os.path.expanduser('~'), environ or os.environ, run
        self.spawn, self.pause = spawn, pause
        self.start_asked = None  # When this computer's Docker was last asked to start.
        self.lock = threading.RLock()
        self.machines = {}    # deck id -> {'id', 'name', 'address', 'host', 'docker', 'state'}
        self.listeners = {}   # deck id -> listening socket
        self.contexts = None  # What the Docker contexts were last made from.
        self.checked = (0, None)
        self.started = False
        saved = read_json(self.path, {})
        saved = saved if isinstance(saved, dict) else {}
        self.host = saved.get('host') is True
        self.use = saved.get('use') if isinstance(saved.get('use'), str) else ''

    # ----- this machine's own engine -----
    def engine(self):
        for path in engine_paths(self.home, self.environ, self.sockets):
            try:
                return path, engine_info(path)
            except (OSError, ValueError, TypeError):
                continue
        return None, None

    def local(self):
        """This computer's Docker for the settings page, checked at most every 30 s."""
        with self.lock:
            at, known = self.checked
        if known is None or time.monotonic() - at > REFRESH:
            docker = self.engine()[1]
            known = {'docker': docker, 'can_start': not docker and self.starter() is not None}
            with self.lock:
                self.checked = (time.monotonic(), known)
        return {'host': self.host, **known}

    def starter(self):
        return start_command(self.home, self.environ, self.run)

    def start_engine(self):
        """Ask this computer's Docker to start; True when it was asked now or a moment ago."""
        command = self.starter()
        if not command:
            return False
        with self.lock:
            if self.start_asked is not None and time.monotonic() - self.start_asked < START_EVERY:
                return True
            self.start_asked = time.monotonic()
            self.checked = (0, None)
        try:
            self.spawn(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       start_new_session=True)
        except OSError:
            return False
        return True

    def connect(self):
        """A connection into this machine's Docker for another computer; only while marked for containers."""
        if not self.host:
            raise ValueError('This computer is not marked for containers; turn it on in its Away Deck settings')
        path = self.engine()[0]
        if not path and self.start_engine():
            # A command arrived while Docker was closed: open it and let the command wait.
            deadline = time.monotonic() + START_WAIT
            while not path and time.monotonic() < deadline:
                self.pause(2)
                path = self.engine()[0]
        if not path:
            raise ValueError('Docker is not running on this computer')
        link = connect_unix(path)
        link.settimeout(None)
        return link

    # ----- other machines -----
    def status(self):
        local = self.local()  # Asks Docker: kept outside the lock.
        with self.lock:
            machines = [dict(machine) for machine in self.machines.values()]
            return {**local, 'use': self.use, 'machines': sorted(machines, key=lambda m: m['name'].lower())}

    def save(self, data):
        host, use = data.get('host', self.host), data.get('use', self.use)
        if not isinstance(host, bool) or not isinstance(use, str):
            raise ValueError('Запуск контейнеров можно только включить или выключить')
        if host and not self.host:
            with self.lock:
                self.checked = (0, None)
            # A closed Docker that the panel can open is opened; it is also opened later, when a command arrives.
            if not self.local()['docker'] and not self.start_engine():
                raise ValueError('Docker на этом компьютере не отвечает; запустите его и повторите')
        with self.lock:
            if use != self.use and use and not (self.machines.get(use) or {}).get('host'):
                raise ValueError('Этот компьютер не отмечен для контейнеров')
            self.host, self.use = host, use
            private_write(self.path, {'host': self.host, 'use': self.use})
        return self.status()

    def fetch(self, deck):
        try:
            status, data = get_json(self.decks(), deck['id'], '/api/containers')
        except FAILURES:
            return {'state': 'offline'}
        if status != 200 or not isinstance(data.get('host'), bool):
            return {'state': 'old'}  # A panel before this feature: it cannot be marked yet.
        docker = data.get('docker') if isinstance(data.get('docker'), dict) else None
        return {'state': 'ok', 'host': data['host'], 'docker': docker, 'can_start': data.get('can_start') is True}

    def refresh(self):
        """Ask every connected computer whether it runs containers; keep sockets and contexts in step."""
        decks = [deck for deck in self.decks().status().get('decks', []) if deck.get('id')]
        found = {}
        for deck, result, error in each(decks, self.fetch):
            result = result or {'state': 'offline'}
            with self.lock:
                known = self.machines.get(deck['id'], {})
            if result['state'] == 'offline':
                # A sleeping machine keeps its socket: Docker then says who does not answer.
                result = {'state': 'offline', 'host': known.get('host', False), 'docker': known.get('docker'), 'can_start': False}
            found[deck['id']] = {'id': deck['id'], 'name': deck.get('name') or deck['id'],
                                 'address': urlsplit(deck.get('url', '')).hostname or '',
                                 'host': False, 'docker': None, 'can_start': False, **result}
        with self.lock:
            self.machines = found
        self.listen({identity for identity, machine in found.items() if machine['host']})
        self.sync_contexts()
        return self.status()

    def socket_path(self, identity):
        return self.sockets / (identity + '.sock')

    def listen(self, wanted):
        with self.lock:
            for identity in set(self.listeners) - wanted:
                self.listeners.pop(identity).close()
                self.socket_path(identity).unlink(missing_ok=True)
            missing = wanted - set(self.listeners)
            if not missing:
                return
            self.sockets.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.sockets, 0o700)
            for identity in missing:
                path = self.socket_path(identity)
                path.unlink(missing_ok=True)  # Left by the previous run of the panel.
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(str(path))
                os.chmod(path, 0o600)
                server.listen(32)
                self.listeners[identity] = server
                threading.Thread(target=self.accept, args=(identity, server), daemon=True,
                                 name='agent-deck-containers').start()

    def accept(self, identity, server):
        while True:
            try:
                client, _ = server.accept()
            except OSError:
                return  # Closed: the machine is no longer marked.
            threading.Thread(target=self.serve, args=(identity, client), daemon=True).start()

    def serve(self, identity, client):
        try:
            try:
                backend = self.dial(identity)
            except (ValueError, OSError) as error:
                return self.refuse(client, identity, error)
            try:
                pump(client, backend)
            finally:
                backend.close()
        finally:
            client.close()

    def refuse(self, client, identity, error):
        """Answer as Docker would, so the command line shows why nothing ran."""
        with self.lock:
            name = (self.machines.get(identity) or {}).get('name', identity)
        reason = str(error) if isinstance(error, ValueError) else 'it does not answer over Tailscale; it may be asleep'
        body = json.dumps({'message': f'Away Deck: containers run on {name}, but {reason}'}).encode()
        try:
            client.settimeout(5)
            client.recv(65536)  # The request must be read before the answer is believed.
            client.sendall(b'HTTP/1.1 502 Bad Gateway\r\nContent-Type: application/json\r\nConnection: close\r\n'
                           b'Content-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
        except OSError:
            pass

    def dial(self, identity):
        stale = None
        for _ in range(2):
            profile, cookie = self.decks().authentication(identity, 'en', stale)
            stale = cookie.split('; cc_lang=', 1)[0]
            target = urlsplit(profile['url'])
            try:
                link = socket.create_connection((target.hostname, target.port or 80), timeout=10)
            except OSError:
                self.decks().fail(identity, profile['url'])  # Its other address, if it has one, is tried next.
                raise
            try:
                link.sendall('\r\n'.join([f'GET {TUNNEL} HTTP/1.1', 'Host: ' + target.netloc, 'Origin: ' + profile['url'],
                                          'Cookie: ' + cookie, 'Connection: Upgrade', 'Upgrade: ' + UPGRADE,
                                          '', '']).encode('latin-1'))
                link.settimeout(START_WAIT + 15)  # The other computer may be opening its Docker first.
                head, rest = read_head(link)
                code = (head.split('\r\n', 1)[0].split() + ['', ''])[1]
                if code == '101' and not rest:
                    link.settimeout(None)
                    link.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    return link
            except BaseException:
                link.close()
                raise
            link.close()
            if code not in ('401', '302', '303'):
                # 404 is a panel before this feature; anything else means the machine was unmarked or has no Docker.
                raise ValueError('it needs a newer Away Deck' if code == '404' else
                                 'it is not marked for containers or its Docker is not running')
        raise ValueError('its saved login expired; reconnect it in the Away Deck settings')

    # ----- what a session gets -----
    def available(self, identity):
        with self.lock:
            machine = self.machines.get(identity)
            return bool(machine and machine['host'] and identity in self.listeners)

    def target(self, choice=None):
        """The session's own choice ('local' or a computer's id), else this computer's default."""
        identity = self.use if choice is None else choice
        with self.lock:
            return dict(self.machines[identity]) if self.available(identity) else None

    def environment(self, choice=None):
        """Variables for an agent started now: Docker commands go to the chosen machine."""
        machine = self.target(choice)
        if not machine:
            return {}
        path = self.socket_path(machine['id'])
        local = self.engine()[0]
        # The session hook reads this next to the socket: who runs the containers and how to run one here.
        private_write(path.with_suffix('.json'), {'name': machine['name'], 'address': machine['address'],
                                                  'local': 'unix://' + local if local else ''})
        return {'DOCKER_HOST': 'unix://' + str(path)}

    # ----- docker contexts -----
    def docker_cli(self, *args):
        env = {key: value for key, value in self.environ.items() if key not in ('DOCKER_HOST', 'DOCKER_CONTEXT')}
        return self.run(['docker', 'context', *args], input='', capture_output=True, text=True, timeout=10, env=env)

    def sync_contexts(self):
        """One Docker context per machine marked for containers, named after it; ours are told by their description."""
        with self.lock:
            wanted = {m['id']: m['name'] for m in self.machines.values() if m['host'] and m['id'] in self.listeners}
        if wanted == self.contexts or not shutil.which('docker', path=self.environ.get('PATH')):
            return
        try:
            listed = self.docker_cli('ls', '--format', '{{json .}}')
            rows = [json.loads(line) for line in listed.stdout.splitlines() if line.strip()] if not listed.returncode else None
            if rows is None:
                return
            ours = {row['Name']: row for row in rows if str(row.get('Description', '')).startswith(MARK)}
            taken = {row['Name'] for row in rows} - set(ours)
            keep = {}
            for identity, name in sorted(wanted.items(), key=lambda item: item[1]):
                keep[context_name(name, taken | set(keep))] = (identity, name)
            for name in set(ours) - set(keep):
                self.docker_cli('rm', '-f', name)
            for name, (identity, machine) in keep.items():
                endpoint = 'unix://' + str(self.socket_path(identity))
                if name not in ours:
                    self.docker_cli('create', name, '--description', MARK + machine, '--docker', 'host=' + endpoint)
                elif ours[name].get('DockerEndpoint') != endpoint:
                    self.docker_cli('update', name, '--description', MARK + machine, '--docker', 'host=' + endpoint)
            self.contexts = wanted
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            pass  # Contexts are a convenience; sessions use the socket directly.

    # ----- background -----
    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True
        threading.Thread(target=self.loop, name='agent-deck-containers', daemon=True).start()

    def loop(self):
        while True:
            try:
                self.refresh()
            except Exception as error:  # A failed pass must not stop later ones; it runs again in 30 s.
                print(f'Container machines check failed: {type(error).__name__}', flush=True)
            time.sleep(REFRESH)
