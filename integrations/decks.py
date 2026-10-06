"""Authenticated Agent Deck connections over known numeric Tailscale addresses."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import http.client
from http.cookies import SimpleCookie
import ipaddress
import json
import re
import secrets
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlencode, urlsplit, unquote

from .names import unique_name
from .relay import private_write, read_json

PUBLIC = ('id', 'name', 'url', 'username')
IDENTITY = re.compile(r'[0-9a-f]{24}\Z')
TAILNET = ipaddress.ip_network('100.64.0.0/10')


def deck_url(raw):
    if not isinstance(raw, str):
        raise ValueError('Enter the Agent Deck Tailscale URL')
    try:
        parsed = urlsplit(raw.strip())
        address = ipaddress.ip_address(parsed.hostname or '')
        port = parsed.port or 80
        # HTTPS cannot work: certificates do not cover bare IPs, and Tailscale already encrypts.
        if (parsed.scheme != 'http' or address.version != 4 or address not in TAILNET
                or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/')
                or not 1 <= port <= 65535):
            raise ValueError()
    except ValueError:
        raise ValueError('Use an http:// URL with a Tailscale IPv4 address and port; Tailscale already encrypts the connection, so https:// is not supported') from None
    return f'{parsed.scheme}://{address}:{port}'


def remote_path(raw):
    if not isinstance(raw, str) or any(ord(c)<32 for c in raw) or '#' in raw:
        raise ValueError('Invalid remote path')
    parsed = urlsplit(raw)
    decoded = unquote(parsed.path)
    if (parsed.scheme or parsed.netloc or '..' in decoded.split('/') or '%' in decoded
            or not re.fullmatch(r'/api/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)?|/t(?:/[a-zA-Z0-9_./-]*)?', decoded)):
        raise ValueError('Only Agent Deck API and terminal paths may be proxied')
    if decoded.startswith('/api/decks') or decoded.startswith('/api/network'):
        raise ValueError('Nested gateway configuration is not supported')
    return raw


def http_request(url, method, path, body=None, headers=None, timeout=30, limit=300*1024*1024):
    """No redirects, environment proxies, DNS targets or credential-bearing exceptions."""
    parsed = urlsplit(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read(limit + 1)
        if len(payload) > limit:
            raise ValueError('Remote response is too large')
        return response.status, dict(response.getheaders()), payload
    finally:
        connection.close()


class LimitedReader:
    """Exactly `length` bytes of a request body for http.client, read in blocks as it sends."""
    def __init__(self, stream, length):
        self.stream, self.remaining = stream, length

    def read(self, size=65536):
        if self.remaining <= 0:
            return b''
        chunk = self.stream.read(min(size, self.remaining, 65536))
        self.remaining -= len(chunk)
        return chunk


class RemoteDecks:
    def __init__(self, directory, local_url):
        self.directory = Path(directory)
        self.path = self.directory / 'decks.json'
        self.local_url = local_url
        self.lock = threading.RLock()
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValueError('Deck configuration must not be a symlink')
        self.profiles = read_json(self.path, {})
        if not isinstance(self.profiles, dict) or not all(isinstance(p, dict) and set(PUBLIC) <= p.keys() for p in self.profiles.values()):
            raise ValueError('Deck configuration must be a JSON object of saved connections')
        self.cookies = {}
        # One login per deck at a time: parallel requests after a restart would trip the remote rate limit.
        self.login_locks = {}
        self.discovery = {'phase': 'idle', 'results': []}

    def status(self):
        with self.lock:
            return {'decks': [{k: p[k] for k in PUBLIC} for p in self.profiles.values()],
                    'discovery': copy.deepcopy(self.discovery)}

    def get(self, identity):
        with self.lock:
            if not isinstance(identity, str) or not IDENTITY.fullmatch(identity) or identity not in self.profiles:
                raise ValueError('Agent Deck connection not found')
            profile = copy.deepcopy(self.profiles[identity])
            profile['url'] = deck_url(profile['url'])
            return profile

    def login(self, profile):
        url = profile['url']
        body = urlencode({'username': profile['username'], 'password': profile['password']}).encode()
        try:
            status, headers, _ = http_request(url, 'POST', '/login', body,
                {'Origin': url, 'Content-Type': 'application/x-www-form-urlencoded'}, timeout=10, limit=1024*1024)
            cookie = SimpleCookie(next((v for k,v in headers.items() if k.lower() == 'set-cookie'), ''))
            location = next((v for k,v in headers.items() if k.lower() == 'location'), '/')
            if status not in (302, 303) or location != '/' or 'cc_auth' not in cookie:
                raise ValueError('Could not sign in to Agent Deck; check the login and password')
            token = cookie['cc_auth'].value
            if not re.fullmatch(r'[A-Za-z0-9_.=-]+', token):
                raise ValueError('Invalid remote login response')
            return 'cc_auth=' + token
        except (OSError, http.client.HTTPException):
            raise ValueError('Remote Agent Deck is unavailable over Tailscale') from None

    def save(self, data):
        name, username, password = data.get('name', ''), data.get('username', ''), data.get('password', '')
        if not all(isinstance(v, str) and v.strip() for v in (name, username)) or len(name) > 100 or not name.isprintable() or len(username) > 100:
            raise ValueError('Enter a connection name and login')
        username = username.strip()
        url = deck_url(data.get('url'))
        if url == self.local_url:
            raise ValueError('This is the current Agent Deck')
        identity = data.get('id') or secrets.token_hex(12)
        old = self.get(identity) if data.get('id') else {}
        if not isinstance(password, str) or len(password) > 4096:
            raise ValueError('Invalid Agent Deck password')
        # Reusing a password is allowed only for the same saved destination and login.
        password = password or (old.get('password', '') if old.get('url') == url and old.get('username') == username else '')
        if not password:
            raise ValueError('Enter the Agent Deck password')
        profile = {'id': identity, 'name': name.strip(), 'url': url, 'username': username, 'password': password}
        cookie = self.login(profile)
        try:
            status, _, body = http_request(url, 'GET', '/api/version', headers={'Cookie': cookie}, timeout=10, limit=1024*1024)
            if status != 200 or not isinstance(json.loads(body).get('version'), str):
                raise ValueError('The destination is not an authenticated Agent Deck')
        except (OSError, http.client.HTTPException, ValueError, AttributeError):
            raise ValueError('Could not verify the remote Agent Deck') from None
        with self.lock:
            names = {p['name'].casefold() for key,p in self.profiles.items() if key != identity}
            profile['name'] = unique_name(profile['name'], lambda n: n.casefold() in names, 100)
            self.profiles[identity] = profile
            try:
                private_write(self.path, self.profiles)
            except Exception:
                if old:self.profiles[identity] = old
                else:self.profiles.pop(identity, None)
                raise
            self.cookies[identity] = cookie
        return {k: profile[k] for k in PUBLIC}

    def remove(self, identity):
        self.get(identity)
        with self.lock:
            old = self.profiles.pop(identity)
            try:private_write(self.path, self.profiles)
            except Exception:
                self.profiles[identity] = old
                raise
            self.cookies.pop(identity, None)

    def authentication(self, identity, language='en', stale=None):
        """Pass the rejected cookie as `stale` to force a new login unless another request already did."""
        profile = self.get(identity)
        with self.lock:
            gate = self.login_locks.setdefault(identity, threading.Lock())
        with gate:
            with self.lock:
                cookie = self.cookies.get(identity)
            if not cookie or (stale is not None and cookie == stale):
                cookie = self.login(profile)
                with self.lock:
                    if self.profiles.get(identity) != profile:
                        raise ValueError('Agent Deck connection changed; retry the request')
                    self.cookies[identity] = cookie
        if re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*', language):
            cookie += '; cc_lang=' + language
        return profile, cookie

    def request(self, identity, method, path, body=None, language='en', timeout=30, content_type='application/json'):
        path = remote_path(path)
        if method not in ('GET','POST'):
            raise ValueError('Unsupported remote method')
        stale = None
        for _ in range(2):
            profile, cookie = self.authentication(identity, language, stale)
            stale = cookie.split('; cc_lang=', 1)[0]
            try:
                result = http_request(profile['url'], method, path, body,
                    {'Cookie': cookie, 'Origin': profile['url'], 'Content-Type': content_type, 'Accept-Encoding': 'identity'},
                    timeout=timeout)
            except (OSError, http.client.HTTPException):
                # Never retry an ambiguous mutation after a transport failure.
                raise ValueError('Remote Agent Deck did not respond; reconnect or retry') from None
            location = next((v for k,v in result[1].items() if k.lower() == 'location'), '')
            if result[0] != 401 and not (result[0] in (302,303) and location == '/login'):
                if result[0] in (301,302,303,307,308):
                    raise ValueError('Remote redirects are not supported')
                return result
        raise ValueError('Remote authentication expired; reconnect this Agent Deck')

    def request_stream(self, identity, path, stream, length, language='en', timeout=300):
        """Raw upload relayed in chunks, so the gateway never holds a whole file in memory. A streamed body
        cannot be sent twice, so the login is refreshed first and a later 401 is reported, never replayed."""
        path = remote_path(path)
        self.request(identity, 'GET', '/api/version', language=language, timeout=10)
        profile, cookie = self.authentication(identity, language)
        try:
            result = http_request(profile['url'], 'POST', path, LimitedReader(stream, length),
                {'Cookie': cookie, 'Origin': profile['url'], 'Content-Type': 'application/octet-stream',
                 'Content-Length': str(length), 'Accept-Encoding': 'identity'}, timeout=timeout, limit=1024*1024)
        except (OSError, http.client.HTTPException):
            raise ValueError('Remote Agent Deck did not respond; retry the upload') from None
        if result[0] in (301,302,303,307,308,401):
            raise ValueError('Remote Agent Deck did not accept the upload; retry it')
        return result

    def terminal_socket(self, identity, language='en'):
        profile, cookie = self.authentication(identity, language)
        parsed = urlsplit(profile['url'])
        try:
            return socket.create_connection((parsed.hostname, parsed.port), timeout=10), profile['url'], cookie
        except OSError:
            raise ValueError('Remote terminal is unavailable over Tailscale') from None

    def discover(self, port=8790):
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError('Enter a valid Agent Deck port')
        with self.lock:
            if self.discovery['phase'] == 'running':return copy.deepcopy(self.discovery)
            self.discovery = {'phase':'running','results':[]}
        threading.Thread(target=self._discover, args=(port,), daemon=True).start()
        return self.status()['discovery']

    def _discover(self, port):
        try:
            binary = shutil.which('tailscale')
            app = Path('/Applications/Tailscale.app/Contents/MacOS/Tailscale')
            binary = binary or (str(app) if app.is_file() else None)
            if not binary:raise ValueError('Tailscale is not installed on the gateway')
            result = subprocess.run([binary,'status','--json'], input='', capture_output=True, text=True, timeout=5, check=True)
            status = json.loads(result.stdout)
            if status.get('BackendState') != 'Running':raise ValueError('Connect the gateway to Tailscale')
            peers, seen = [], set()
            for peer in (status.get('Peer') or {}).values():
                if peer.get('Online') is False:continue
                for raw in peer.get('TailscaleIPs', []):
                    try:address = ipaddress.ip_address(raw)
                    except ValueError:continue
                    if address.version != 4 or address not in TAILNET or str(address) in seen:continue
                    seen.add(str(address));peers.append({'url':f'http://{address}:{port}', 'name':' '.join(str(peer.get('HostName') or address).split())[:100]})
            found = []
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(self._probe, p):p for p in peers[:128]}
                for future in as_completed(futures):
                    if future.result():
                        found.append(futures[future])
                        with self.lock:self.discovery['results'] = copy.deepcopy(found)
            with self.lock:self.discovery = {'phase':'done','results':found}
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
            with self.lock:self.discovery = {'phase':'error','results':[], 'error':'Could not discover Agent Deck instances; check Tailscale on the gateway'}

    @staticmethod
    def _probe(profile):
        try:
            status, headers, body = http_request(profile['url'], 'GET', '/login', timeout=2, limit=1024*1024)
            server = next((v for k,v in headers.items() if k.lower() == 'server'), '')
            return status == 200 and ('cc-panel/' in server or b'<title>Agent Deck' in body)
        except (OSError, http.client.HTTPException, ValueError):return False


class UnavailableDecks:
    """Stands in when decks.json is unreadable so the panel still starts and never overwrites it."""
    def __init__(self, message):
        self.message = message

    def status(self):
        return {'decks': [], 'discovery': {'phase': 'idle', 'results': []}}

    def unavailable(self, *args, **kwargs):
        raise ValueError(self.message)

    get = save = remove = discover = request = terminal_socket = authentication = unavailable
