"""Authenticated DeckAway connections over known numeric addresses: Tailscale, or the local network.

A connection may know several addresses of one computer. The saved password goes by itself only to the
Tailscale address its owner entered; every other address must first prove the key agreed at sign-in
(`lan.py`), so a local address that belongs to someone else in another network gets nothing."""
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
import time
import threading
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, unquote

from . import lan
from .lan import NONCE, deck_proof, gateway_proof, is_lan, is_tailnet, neighbours
from .names import unique_name
from .relay import private_write, read_json

PUBLIC = ('id', 'name', 'url', 'username')
IDENTITY = re.compile(r'[0-9a-f]{24}\Z')
TAILNET = ipaddress.ip_network('100.64.0.0/10')
MAX_ADDRESSES = 4
CONNECT_TIMEOUT = 4   # With another address to try, a sleeping one must not hold the request for the whole timeout.
RETRY_AFTER = 60      # An address that did not answer is left alone this long while another one works.
BAD_URL = ('Use an http:// URL with a Tailscale or local network IPv4 address and port; '
           'https:// is not supported for bare addresses')


class Unreachable(OSError):
    """Nothing was sent: the address did not accept the connection, so another one may be tried."""


def deck_url(raw):
    if not isinstance(raw, str):
        raise ValueError('Enter the DeckAway URL')
    try:
        parsed = urlsplit(raw.strip())
        address = ipaddress.ip_address(parsed.hostname or '')
        port = parsed.port or 80
        # HTTPS cannot work: certificates do not cover bare IPs, and Tailscale already encrypts.
        if (parsed.scheme != 'http' or address.version != 4 or not (address in TAILNET or is_lan(str(address)))
                or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/')
                or not 1 <= port <= 65535):
            raise ValueError()
    except ValueError:
        raise ValueError(BAD_URL) from None
    return f'{parsed.scheme}://{address}:{port}'


def terminal_query_ok(path):
    """ttyd runs with -a: every URL arg becomes an argument of `tmux attach -t`, and a bare `;` there
    chains any tmux command (run-shell). A link opened while logged in would run it, so the only
    accepted query is the one the panel builds: a single session target."""
    pairs = parse_qsl(urlsplit(path).query, keep_blank_values=True)
    return not pairs or (len(pairs) == 1 and pairs[0][0] == 'arg'
                         and re.fullmatch(r'=?cc-[A-Za-z0-9_-]{1,32}', pairs[0][1]) is not None)


def remote_path(raw):
    if not isinstance(raw, str) or any(ord(c)<32 for c in raw) or '#' in raw:
        raise ValueError('Invalid remote path')
    parsed = urlsplit(raw)
    decoded = unquote(parsed.path)
    if (parsed.scheme or parsed.netloc or '..' in decoded.split('/') or '%' in decoded
            or not re.fullmatch(r'/api/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)?|/t(?:/[a-zA-Z0-9_./-]*)?', decoded)):
        raise ValueError('Only DeckAway API and terminal paths may be proxied')
    if decoded.startswith('/api/decks') or decoded.startswith('/api/network'):
        raise ValueError('Nested gateway configuration is not supported')
    if decoded.startswith('/t') and not terminal_query_ok(raw):
        raise ValueError('A terminal link may only name one session')
    return raw


# Largest answers a deck sends: a 25 MB picture, a 10 MB file preview as base64 JSON.
PROXY_LIMIT = 48 * 1024 * 1024
POLL_LIMIT = 8 * 1024 * 1024


def http_request(url, method, path, body=None, headers=None, timeout=30, limit=300*1024*1024, connect=None):
    """No redirects, environment proxies, DNS targets or credential-bearing exceptions."""
    parsed = urlsplit(url)
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=min(timeout, connect or timeout))
    try:
        try:
            connection.connect()
        except OSError as error:
            raise Unreachable(str(error)) from None
        connection.sock.settimeout(timeout)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        # The socket timeout is per read: a deck trickling bytes would hold the caller (and the
        # parallel poll of every deck) for ever, so the whole body also has a deadline.
        deadline, chunks, size = time.monotonic() + timeout * 4, [], 0
        while True:
            chunk = response.read1(min(65536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk);size += len(chunk)
            if size > limit:
                raise ValueError('Remote response is too large')
            if time.monotonic() > deadline:
                raise ValueError('Remote DeckAway answered too slowly')
        return response.status, dict(response.getheaders()), b''.join(chunks)
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
        if not chunk:
            # The browser went away mid-upload: fail here instead of sending a short body as a whole one.
            raise OSError('Upload ended before its declared length')
        self.remaining -= len(chunk)
        return chunk


class RemoteDecks:
    def __init__(self, directory, local_url, instance=lambda: '', local_address=lambda: lan.lan_address()):
        self.directory = Path(directory)
        self.path = self.directory / 'decks.json'
        self.local_url = local_url
        self.instance, self.local_address = instance, local_address
        self.proven = {}    # deck -> addresses that proved the pair key since they last failed
        self.down = {}      # (deck, address) -> when it may be tried again
        self.routes = {}    # deck -> address of its last answered request
        self.unpaired = set()  # Decks before pairing existed: asked once per run, not on every sign-in.
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
            decks = []
            for p in self.profiles.values():
                urls = self.addresses(p)
                route = self.routes.get(p['id'], urls[0])
                decks.append({**{k: p[k] for k in PUBLIC}, 'urls': urls, 'route': route if route in urls else urls[0]})
            return {'decks': decks, 'discovery': copy.deepcopy(self.discovery)}

    @staticmethod
    def addresses(profile):
        """Every known address: Tailscale first (encrypted), the local network as the other way in."""
        urls = [profile['url']] + [u for u in profile.get('urls', []) if u != profile['url']]
        return sorted(urls, key=lambda url: not is_tailnet(urlsplit(url).hostname))

    def candidates(self, profile):
        urls, now = self.addresses(profile), time.monotonic()
        with self.lock:
            up = [u for u in urls if self.down.get((profile['id'], u), 0) <= now]
        return up or urls  # All marked: try them anyway, a single address behaves as it always did.

    def fail(self, identity, url):
        """This address did not answer or did not prove itself: use another one for a while."""
        with self.lock:
            self.down[(identity, url)] = time.monotonic() + RETRY_AFTER
            self.proven.get(identity, set()).discard(url)

    def get(self, identity):
        with self.lock:
            if not isinstance(identity, str) or not IDENTITY.fullmatch(identity) or identity not in self.profiles:
                raise ValueError('DeckAway connection not found')
            profile = copy.deepcopy(self.profiles[identity])
            profile['url'] = deck_url(profile['url'])
            return profile

    def login(self, profile, url=None):
        url = url or profile['url']
        body = urlencode({'username': profile['username'], 'password': profile['password']}).encode()
        try:
            status, headers, _ = http_request(url, 'POST', '/login', body,
                {'Origin': url, 'Content-Type': 'application/x-www-form-urlencoded'}, timeout=10, limit=1024*1024)
            cookie = SimpleCookie(next((v for k,v in headers.items() if k.lower() == 'set-cookie'), ''))
            location = next((v for k,v in headers.items() if k.lower() == 'location'), '/')
            if status not in (302, 303) or location != '/' or 'cc_auth' not in cookie:
                raise ValueError('Could not sign in to DeckAway; check the login and password')
            token = cookie['cc_auth'].value
            if not re.fullmatch(r'[A-Za-z0-9_.=-]+', token):
                raise ValueError('Invalid remote login response')
            return 'cc_auth=' + token
        except Unreachable:
            raise
        except (OSError, http.client.HTTPException):
            raise ValueError('Remote DeckAway is unavailable') from None

    def prove(self, url, pair, sign_in):
        """Ask the machine at this address for the pair key's proof before it gets anything of ours; with
        `sign_in` the gateway then proves the same key and receives a cookie, without the password."""
        ours = secrets.token_hex(16)
        wrong = ValueError('Another machine answers at this address')
        try:
            status, _, body = http_request(url, 'GET', f"/api/pair_challenge?id={pair['id']}&nonce={ours}", timeout=5, limit=65536)
            answer = json.loads(body) if status == 200 else {}
            theirs, proof = answer.get('nonce', ''), answer.get('proof', '')
            if (not isinstance(theirs, str) or not re.fullmatch(NONCE, theirs) or not isinstance(proof, str)
                    or not secrets.compare_digest(proof.encode('ascii', 'replace'), deck_proof(pair['key'], theirs, ours).encode())):
                raise wrong
            if not sign_in:
                return None
            body = json.dumps({'id': pair['id'], 'nonce': theirs, 'proof': gateway_proof(pair['key'], theirs, ours)}).encode()
            status, headers, _ = http_request(url, 'POST', '/api/pair_login', body,
                {'Origin': url, 'Content-Type': 'application/json'}, timeout=10, limit=65536)
            cookie = SimpleCookie(next((v for k, v in headers.items() if k.lower() == 'set-cookie'), ''))
            if status != 200 or 'cc_auth' not in cookie or not re.fullmatch(r'[A-Za-z0-9_.=-]+', cookie['cc_auth'].value):
                raise wrong
            return 'cc_auth=' + cookie['cc_auth'].value
        except Unreachable:
            raise
        except (OSError, http.client.HTTPException, ValueError, AttributeError, TypeError):
            raise wrong from None

    def pair(self, url, cookie):
        """A key for later sign-ins without the password, and the computer's own id; None from a panel
        that cannot pair yet."""
        try:
            status, _, body = http_request(url, 'POST', '/api/pair', b'{}',
                {'Cookie': cookie, 'Origin': url, 'Content-Type': 'application/json'}, timeout=10, limit=65536)
            answer = json.loads(body) if status == 200 else {}
            pair = {'id': answer['id'], 'key': answer['key']}
            if not re.fullmatch(r'[0-9a-f]{16}', pair['id']) or not re.fullmatch(r'[0-9a-f]{64}', pair['key']):
                return None
            instance = answer.get('instance', '')
            return pair, instance if isinstance(instance, str) and len(instance) <= 64 else ''
        except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError, AttributeError):
            return None

    def cookie_for(self, profile, url, stale):
        identity = profile['id']
        with self.lock:
            cookie = self.cookies.get(identity)
            proven = url in self.proven.get(identity, ())
        fresh = bool(cookie) and not (stale is not None and cookie == stale)
        if url == profile['url'] and is_tailnet(urlsplit(url).hostname):
            return cookie if fresh else self.login(profile, url)
        pair = profile.get('pair')
        if not pair:
            raise ValueError('Reconnect this DeckAway: its local network address needs a new sign-in')
        if proven and fresh:
            return cookie
        cookie = self.prove(url, pair, not fresh) or cookie
        with self.lock:
            self.proven.setdefault(identity, set()).add(url)
        return cookie

    def save(self, data):
        name, username, password = data.get('name', ''), data.get('username', ''), data.get('password', '')
        if not all(isinstance(v, str) and v.strip() for v in (name, username)) or len(name) > 100 or not name.isprintable() or len(username) > 100:
            raise ValueError('Enter a connection name and login')
        username = username.strip()
        url = deck_url(data.get('url'))
        if url == self.local_url:
            raise ValueError('This is the current DeckAway')
        identity = data.get('id') or secrets.token_hex(12)
        old = self.get(identity) if data.get('id') else {}
        if not isinstance(password, str) or len(password) > 4096:
            raise ValueError('Invalid DeckAway password')
        # Reusing a password is allowed only for the same saved destination and login.
        password = password or (old.get('password', '') if old.get('url') == url and old.get('username') == username else '')
        if not password:
            raise ValueError('Enter the DeckAway password')
        extras = data.get('urls', old.get('urls', []) if old.get('url') == url else [])
        if not isinstance(extras, list) or len(extras) > MAX_ADDRESSES:
            raise ValueError(BAD_URL)
        extras = [u for u in dict.fromkeys(deck_url(u) for u in extras) if u not in (url, self.local_url)]
        profile = {'id': identity, 'name': name.strip(), 'url': url, 'username': username, 'password': password}
        try:
            # The owner's own action: the only time the password goes to an address of the local network.
            cookie = self.login(profile)
        except Unreachable:
            raise ValueError('Remote DeckAway is unavailable') from None
        try:
            status, _, body = http_request(url, 'GET', '/api/version', headers={'Cookie': cookie}, timeout=10, limit=1024*1024)
            if status != 200 or not isinstance(json.loads(body).get('version'), str):
                raise ValueError('The destination is not an authenticated DeckAway')
        except (OSError, http.client.HTTPException, ValueError, AttributeError):
            raise ValueError('Could not verify the remote DeckAway') from None
        paired = self.pair(url, cookie)
        if paired:
            profile['pair'], profile['instance'] = paired
            if profile['instance'] and profile['instance'] == self.instance():
                raise ValueError('This is the current DeckAway')
        elif not is_tailnet(urlsplit(url).hostname):
            raise ValueError('Update DeckAway on that computer first: this version cannot be connected over the local network')
        if paired and extras:
            profile['urls'] = extras  # Without a pair key another address could never be trusted.
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
            self.proven[identity] = {url}
            self.routes.pop(identity, None)
            for key in [k for k in self.down if k[0] == identity]:
                del self.down[key]
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
            self.proven.pop(identity, None)
            self.routes.pop(identity, None)

    def authentication(self, identity, language='en', stale=None):
        """Pass the rejected cookie as `stale` to force a new login unless another request already did."""
        profile = self.get(identity)
        with self.lock:
            gate = self.login_locks.setdefault(identity, threading.Lock())
        with gate:
            cookie, error = None, None
            for url in self.candidates(profile):
                try:
                    cookie = self.cookie_for(profile, url, stale)
                    break
                except Unreachable:
                    self.fail(identity, url)
                    error = ValueError('Remote DeckAway is unavailable')
                except ValueError as failure:
                    if len(self.addresses(profile)) == 1:
                        raise
                    self.fail(identity, url)
                    error = error or failure
            if cookie is None:
                raise error
            with self.lock:
                if self.profiles.get(identity) != profile:
                    raise ValueError('DeckAway connection changed; retry the request')
                self.cookies[identity] = cookie
                self.routes[identity] = url
        if re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*', language):
            cookie += '; cc_lang=' + language
        # Callers talk to `url`: here it is the address that answered, not always the saved one.
        return {**profile, 'url': url}, cookie

    def learn_pair(self, profile, cookie):
        """A connection saved before pairing existed gets its key at the next password sign-in."""
        paired = self.pair(profile['url'], cookie)
        with self.lock:
            if not paired:
                self.unpaired.add(profile['id'])
                return profile
            if self.profiles.get(profile['id']) != profile:
                return profile
            updated = {**profile, 'pair': paired[0], 'instance': paired[1]}
            self.profiles[profile['id']] = updated
            try:
                private_write(self.path, self.profiles)
            except (OSError, ValueError):
                self.profiles[profile['id']] = profile
                return profile
            return copy.deepcopy(updated)

    def request(self, identity, method, path, body=None, language='en', timeout=30, content_type='application/json',
                limit=PROXY_LIMIT):
        path = remote_path(path)
        if method not in ('GET','POST'):
            raise ValueError('Unsupported remote method')
        stale, rejected = None, 0
        for _ in range(2 + MAX_ADDRESSES):
            profile, cookie = self.authentication(identity, language, stale)
            try:
                result = http_request(profile['url'], method, path, body,
                    {'Cookie': cookie, 'Origin': profile['url'], 'Content-Type': content_type, 'Accept-Encoding': 'identity'},
                    timeout=timeout, limit=limit, connect=CONNECT_TIMEOUT if profile.get('urls') else None)
            except Unreachable:
                # Nothing was sent, so the request may go to the computer's other address.
                self.fail(identity, profile['url'])
                if len(self.addresses(self.get(identity))) == 1:
                    raise ValueError('Remote DeckAway did not respond; reconnect or retry') from None
                continue
            except (OSError, http.client.HTTPException):
                # Never retry an ambiguous mutation after a transport failure.
                raise ValueError('Remote DeckAway did not respond; reconnect or retry') from None
            location = next((v for k,v in result[1].items() if k.lower() == 'location'), '')
            if result[0] != 401 and not (result[0] in (302,303) and location == '/login'):
                if result[0] in (301,302,303,307,308):
                    raise ValueError('Remote redirects are not supported')
                return result
            stale, rejected = cookie.split('; cc_lang=', 1)[0], rejected + 1
            if rejected == 2:
                break
        raise ValueError('Remote authentication expired; reconnect this DeckAway' if rejected else
                         'Remote DeckAway did not respond; reconnect or retry')

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
            raise ValueError('Remote DeckAway did not respond; retry the upload') from None
        if result[0] in (301,302,303,307,308,401):
            raise ValueError('Remote DeckAway did not accept the upload; retry it')
        return result

    def terminal_socket(self, identity, language='en'):
        for _ in range(1 + MAX_ADDRESSES):
            profile, cookie = self.authentication(identity, language)
            parsed = urlsplit(profile['url'])
            try:
                # A computer with one address may take its time: Tailscale builds the path to a waking machine.
                link = socket.create_connection((parsed.hostname, parsed.port), timeout=CONNECT_TIMEOUT if profile.get('urls') else 10)
                link.settimeout(10)
                return link, profile['url'], cookie
            except OSError:
                self.fail(identity, profile['url'])
                if len(self.addresses(self.get(identity))) == 1:
                    break
        raise ValueError('Remote terminal is unavailable')

    def discover(self, port=8790):
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError('Enter a valid DeckAway port')
        with self.lock:
            if self.discovery['phase'] == 'running':return copy.deepcopy(self.discovery)
            self.discovery = {'phase':'running','results':[]}
        threading.Thread(target=self._discover, args=(port,), daemon=True).start()
        return self.status()['discovery']

    def tailscale_peers(self, port):
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
        return peers[:128]

    def _discover(self, port):
        try:
            try:
                peers = self.tailscale_peers(port)
            except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
                peers = None  # A computer without Tailscale still has its local network.
            local = self.local_address()
            if peers is None and not local:
                raise ValueError('No network to search')
            targets = (peers or []) + [{'url': f'http://{address}:{port}', 'name': address} for address in (neighbours(local) if local else [])]
            found = []
            with ThreadPoolExecutor(max_workers=32) as pool:
                futures = {pool.submit(self._probe, p):p for p in targets}
                for future in as_completed(futures):
                    answer = future.result()
                    if answer:
                        found.append({**futures[future], **(answer if isinstance(answer, dict) else {})})
                        with self.lock:self.discovery['results'] = self.merged(found)
            with self.lock:
                results = self.merged(found)
                self.remember(found)
                self.discovery = {'phase':'done','results':results}
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
            with self.lock:self.discovery = {'phase':'error','results':[], 'error':'Could not discover DeckAway instances; check Tailscale or the local network on the gateway'}

    def merged(self, found):
        """One row per computer: the same one seen over Tailscale and in the local network names itself by
        the same id. This computer and the ones already connected are left out."""
        with self.lock:
            saved = {p.get('instance') for p in self.profiles.values() if p.get('instance')}
            known = {u for p in self.profiles.values() for u in self.addresses(p)}
        rows, own = {}, self.instance()
        for item in sorted(found, key=lambda i: not is_tailnet(urlsplit(i['url']).hostname)):
            instance = item.get('instance', '')
            if item['url'] in known or item['url'] == self.local_url or (instance and instance in saved | {own}):
                continue
            row = rows.setdefault(instance or item['url'], {'name': item['name'], 'url': item['url'], 'urls': [], 'instance': instance})
            if item['url'] != row['url'] and len(row['urls']) < MAX_ADDRESSES:
                row['urls'].append(item['url'])
        return sorted(rows.values(), key=lambda row: row['name'].casefold())

    def remember(self, found):
        """A connected computer found on one more address keeps it. The address is only a claim until it
        proves the pair key, so nothing is trusted here."""
        changed = False
        for profile in self.profiles.values():
            if not profile.get('instance') or not profile.get('pair'):
                continue
            new = [i['url'] for i in found if i.get('instance') == profile['instance'] and i['url'] not in self.addresses(profile)]
            if new:
                profile['urls'] = (profile.get('urls', []) + new)[-MAX_ADDRESSES:]
                changed = True
        if changed:
            try:private_write(self.path, self.profiles)
            except (OSError, ValueError):pass  # Found again by the next search.

    @staticmethod
    def _probe(profile):
        try:
            status, headers, body = http_request(profile['url'], 'GET', '/api/hello', timeout=2, limit=65536)
            if status == 200:
                answer = json.loads(body)
                if answer.get('app') != 'away-deck' or not isinstance(answer.get('id'), str) or not IDENTITY.fullmatch(answer['id']):
                    return False
                name = answer.get('name')
                return {'instance': answer['id'], **({'name': ' '.join(name.split())[:100]} if isinstance(name, str) and name.strip() and name.isprintable() else {})}
            # A panel before 1.44 does not introduce itself; its sign-in page still tells what it is.
            status, headers, body = http_request(profile['url'], 'GET', '/login', timeout=2, limit=1024*1024)
            server = next((v for k,v in headers.items() if k.lower() == 'server'), '')
            return status == 200 and ('cc-panel/' in server or b'<title>DeckAway' in body
                                      or b'<title>Away Deck' in body or b'<title>Agent Deck' in body)  # Earlier names.
        except (OSError, http.client.HTTPException, ValueError, AttributeError):return False


class UnavailableDecks:
    """Stands in when decks.json is unreadable so the panel still starts and never overwrites it."""
    def __init__(self, message):
        self.message = message

    def status(self):
        return {'decks': [], 'discovery': {'phase': 'idle', 'results': []}}

    def unavailable(self, *args, **kwargs):
        raise ValueError(self.message)

    get = save = remove = discover = request = terminal_socket = authentication = unavailable

    def fail(self, *args):
        pass
