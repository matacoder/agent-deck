"""Authenticated DeckAway connections over known numeric addresses: Tailscale, or the local network.

A connection may know several addresses of one computer. The saved password goes by itself only to the
Tailscale address its owner entered; every other address must first prove the key agreed at sign-in
(`lan.py`), so a local address that belongs to someone else in another network gets nothing."""
import copy
import http.client
from http.cookies import SimpleCookie
import json
import re
import secrets
import socket
import sys
import time
import threading
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from . import deck_transport as transport
from . import lan
from .deck_discovery import Discovery
# Callers and tests name these through this module.
from .deck_transport import (BAD_URL, POLL_LIMIT, PROXY_LIMIT, LimitedReader, Unreachable, deck_url,  # noqa: F401
                             http_request, remote_path, terminal_query_ok)
from .lan import NONCE, deck_proof, gateway_proof, is_tailnet
from .names import unique_name
from .relay import private_write, read_json

PUBLIC = ('id', 'name', 'url', 'username')
IDENTITY = re.compile(r'[0-9a-f]{24}\Z')
MAX_ADDRESSES = 4
CONNECT_TIMEOUT = 4   # With another address to try, a sleeping one must not hold the request for the whole timeout.
RETRY_AFTER = 60      # An address that did not answer is left alone this long while another one works.
PROOF_TTL = 60        # A local address is asked for the pair key again this often, and after every failure.


class RemoteDecks(Discovery):
    def __init__(self, directory, local_url, instance=lambda: '', local_address=lambda: lan.lan_address()):
        self.directory = Path(directory)
        self.path = self.directory / 'decks.json'
        self.local_url = local_url
        self.instance, self.local_address = instance, local_address
        self.proven = {}    # deck -> {address: until when its proof of the pair key holds}
        self.network = None  # Our local address when the proofs were taken: another network voids them.
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
                decks.append({**{k: p[k] for k in PUBLIC}, 'urls': urls, 'route': route if route in urls else urls[0],
                              'instance': p.get('instance', '')})
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
            self.proven.get(identity, {}).pop(url, None)

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
            status, headers, _ = transport.http_request(url, 'POST', '/login', body,
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
        ours, at = secrets.token_hex(16), urlsplit(url).netloc
        wrong = ValueError('Another machine answers at this address')
        try:
            status, _, body = transport.http_request(url, 'GET', f"/api/pair_challenge?id={pair['id']}&nonce={ours}&at={at}", timeout=5, limit=65536)
            answer = json.loads(body) if status == 200 else {}
            theirs, proof = answer.get('nonce', ''), answer.get('proof', '')
            if (not isinstance(theirs, str) or not re.fullmatch(NONCE, theirs) or not isinstance(proof, str)
                    or not secrets.compare_digest(proof.encode('ascii', 'replace'), deck_proof(pair['key'], theirs, ours, at).encode())):
                raise wrong
            if not sign_in:
                return None
            body = json.dumps({'id': pair['id'], 'nonce': theirs, 'proof': gateway_proof(pair['key'], theirs, ours, at)}).encode()
            status, headers, _ = transport.http_request(url, 'POST', '/api/pair_login', body,
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
            status, _, body = transport.http_request(url, 'POST', '/api/pair', b'{}',
                {'Cookie': cookie, 'Origin': url, 'Content-Type': 'application/json'}, timeout=10, limit=65536)
            answer = json.loads(body) if status == 200 else {}
            pair = {'id': answer['id'], 'key': answer['key']}
            if not re.fullmatch(r'[0-9a-f]{16}', pair['id']) or not re.fullmatch(r'[0-9a-f]{64}', pair['key']):
                return None
            instance = answer.get('instance', '')
            return pair, instance if isinstance(instance, str) and len(instance) <= 64 else ''
        except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError, AttributeError):
            return None

    def kept_pair(self, old, url):
        """The key this connection already has, while the computer still answers to it: a new one on every
        edit would push other gateways' keys out of the computer's short list."""
        if not old.get('pair'):
            return None
        try:
            self.prove(url, old['pair'], False)
        except (OSError, ValueError):
            return None
        return old['pair'], old.get('instance', '')

    def cookie_for(self, profile, url, stale):
        identity, here = profile['id'], self.local_address()
        with self.lock:
            if here != self.network:
                self.network, self.proven = here, {}
            cookie = self.cookies.get(identity)
            proven = self.proven.get(identity, {}).get(url, 0) > time.monotonic()
        fresh = bool(cookie) and not (stale is not None and cookie == stale)
        if url == profile['url'] and is_tailnet(urlsplit(url).hostname):
            return cookie if fresh else self.learn_pair(profile, self.login(profile, url))
        pair = profile.get('pair')
        if not pair:
            raise ValueError('Reconnect this DeckAway: its local network address needs a new sign-in')
        if proven and fresh:
            return cookie
        cookie = self.prove(url, pair, not fresh) or cookie
        with self.lock:
            self.proven.setdefault(identity, {})[url] = time.monotonic() + PROOF_TTL
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
        same = bool(old) and old.get('url') == url and old.get('username') == username
        typed, password = bool(password), password or (old.get('password', '') if same else '')
        if not password:
            raise ValueError('Enter the DeckAway password')
        extras = data.get('urls', old.get('urls', []) if old.get('url') == url else [])
        if not isinstance(extras, list) or len(extras) > MAX_ADDRESSES:
            raise ValueError(BAD_URL)
        extras = [u for u in dict.fromkeys(deck_url(u) for u in extras) if u not in (url, self.local_url)]
        profile = {'id': identity, 'name': name.strip(), 'url': url, 'username': username, 'password': password}
        try:
            # A typed password is the owner's own action: the only time it goes to an address of the local
            # network. A rename of a saved connection signs in the way every later request does.
            cookie = self.login(profile) if typed or not same else self.cookie_for(old, url, None)
        except Unreachable:
            raise ValueError('Remote DeckAway is unavailable') from None
        try:
            status, _, body = transport.http_request(url, 'GET', '/api/version', headers={'Cookie': cookie}, timeout=10, limit=1024*1024)
            if status != 200 or not isinstance(json.loads(body).get('version'), str):
                raise ValueError('The destination is not an authenticated DeckAway')
        except (OSError, http.client.HTTPException, ValueError, AttributeError):
            raise ValueError('Could not verify the remote DeckAway') from None
        paired = self.kept_pair(old, url) if same else None
        paired = paired or self.pair(url, cookie)
        if paired:
            profile['pair'], profile['instance'] = paired
            if profile['instance'] and profile['instance'] == self.instance():
                raise ValueError('This is the current DeckAway')
        elif not is_tailnet(urlsplit(url).hostname):
            raise ValueError('Update DeckAway on that computer first: this version cannot be connected over the local network')
        if paired and extras:
            profile['urls'] = extras  # Without a pair key another address could never be trusted.
        self.keep(profile, old, cookie)
        return {k: profile[k] for k in PUBLIC}

    def keep(self, profile, old, cookie):
        """Write a verified connection down and start its addresses afresh."""
        identity, url = profile['id'], profile['url']
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
            self.proven[identity] = {url: time.monotonic() + PROOF_TTL}
            self.routes.pop(identity, None)
            for key in [k for k in self.down if k[0] == identity]:
                del self.down[key]

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

    def direct(self, identity, language='en'):
        """A link that opens the computer's own panel signed in, once: its address is the one the owner entered,
        the secret after `#` comes from the computer itself (`integrations/direct.py`)."""
        profile, cookie = self.authentication(identity, language)
        try:
            status, _, body = transport.http_request(profile['url'], 'POST', '/api/direct_link', b'{}',
                {'Cookie': cookie, 'Origin': profile['url'], 'Content-Type': 'application/json'}, timeout=10, limit=65536)
            token = json.loads(body).get('token') if status == 200 else None
        except (OSError, http.client.HTTPException, ValueError, AttributeError):
            raise ValueError('Remote DeckAway did not respond; retry') from None
        if status == 404:
            raise ValueError('Update DeckAway on that computer first: this version cannot be opened directly')
        if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{64}', token):
            raise ValueError('The computer did not give a sign-in link; reconnect it and retry')
        return self.get(identity)['url'] + '/direct#' + token

    def learn_pair(self, profile, cookie):
        """A connection saved before pairing existed gets its key at a password sign-in, asked once per run.
        Returns the cookie; the saved profile changes underneath, which the caller's check then reports."""
        with self.lock:
            if profile.get('pair') or profile['id'] in self.unpaired:
                return cookie
            self.unpaired.add(profile['id'])
        paired = self.pair(profile['url'], cookie)
        with self.lock:
            if paired and self.profiles.get(profile['id']) == profile:
                updated = {**profile, 'pair': paired[0], 'instance': paired[1]}
                self.profiles[profile['id']] = updated
                try:
                    private_write(self.path, self.profiles)
                    profile.update(updated)  # The caller goes on with what is now saved.
                except (OSError, ValueError):
                    self.profiles[profile['id']] = {k: v for k, v in profile.items()}
        return cookie

    def request(self, identity, method, path, body=None, language='en', timeout=30, content_type='application/json',
                limit=PROXY_LIMIT):
        path = remote_path(path)
        if method not in ('GET','POST'):
            raise ValueError('Unsupported remote method')
        stale, rejected = None, 0
        for _ in range(2 + MAX_ADDRESSES):
            profile, cookie = self.authentication(identity, language, stale)
            try:
                result = transport.http_request(profile['url'], method, path, body,
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
        body = LimitedReader(stream, length)
        try:
            result = transport.http_request(profile['url'], 'POST', path, body,
                {'Cookie': cookie, 'Origin': profile['url'], 'Content-Type': 'application/octet-stream',
                 'Content-Length': str(length), 'Accept-Encoding': 'identity'}, timeout=timeout, limit=1024*1024)
        except (OSError, http.client.HTTPException) as error:
            # How far it got tells a browser that sent less than it declared from a computer that stopped reading.
            print(f'deck upload: {type(error).__name__} after {length - body.remaining} of {length} bytes',
                  file=sys.stderr, flush=True)
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



class UnavailableDecks:
    """Stands in when decks.json is unreadable so the panel still starts and never overwrites it."""
    def __init__(self, message):
        self.message = message

    def status(self):
        return {'decks': [], 'discovery': {'phase': 'idle', 'results': []}}

    def unavailable(self, *args, **kwargs):
        raise ValueError(self.message)

    get = save = remove = discover = request = terminal_socket = authentication = direct = unavailable

    def fail(self, *args):
        pass
