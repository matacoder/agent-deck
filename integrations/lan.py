"""DeckAway on an ordinary local network, next to Tailscale.

A computer answers on its local address only while its owner switched that on: the connection there is plain
HTTP. A gateway that reaches a computer on an address other than the one its owner typed first asks it to
prove a key both agreed on over a signed-in connection; a stored password or cookie never goes to another
machine that happens to hold the address in a different network.
"""
import hashlib
import hmac
import ipaddress
import os
import secrets
import socket
import threading
import time
from pathlib import Path

from .relay import private_write, read_json

PRIVATE = [ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]
TAILNET = ipaddress.ip_network('100.64.0.0/10')
KEY_ID = r'[0-9a-f]{16}'
NONCE = r'[0-9a-f]{32}'
MAX_PAIRS = 16
CHALLENGE_TTL = 60
MAX_PENDING = 256
MAX_PENDING_PER_KEY = 16  # The key's id travels in clear: one who saw it must not fill the table for everyone.
ADDRESS = r'\d{1,3}(?:\.\d{1,3}){3}:\d{1,5}'
SCAN_LIMIT = 254


def is_lan(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.version == 4 and any(ip in network for network in PRIVATE)


def is_tailnet(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.version == 4 and ip in TAILNET


def lan_address(create=socket.socket):
    """This machine's address on the local network: the one its default route leaves from. None on a server
    with a public address, or when every packet leaves through Tailscale."""
    try:
        with create(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('192.0.2.1', 9))  # Chooses the route; UDP sends nothing here.
            found = probe.getsockname()[0]
    except OSError:
        return None
    return found if is_lan(found) else None


def neighbours(address):
    """The other addresses of the /24 around ours: a home or office network, checked within seconds."""
    network = ipaddress.ip_network(address + '/24', strict=False)
    return [str(host) for host in network.hosts() if str(host) != address][:SCAN_LIMIT]


def forwarded():
    """Inside a container or WSL the address a gateway dials is the host's, never one of ours."""
    if os.environ.get('AGENT_DECK_CONTAINER'):
        return True
    try:
        return 'microsoft' in Path('/proc/version').read_text(errors='replace').lower()
    except OSError:
        return False


def own_address(address, local):
    """Whether `host:port` a gateway says it dialled is the address its connection really reached: a machine
    that only passes the question on to the real computer is dialled at another one."""
    return forwarded() or address.rsplit(':', 1)[0] == local


def fingerprint(secret):
    """Names the sign-in secret without revealing it: pair keys made under another password stop working."""
    return hashlib.sha256(b'pairs|' + secret).hexdigest()[:32]


# Both proofs name the address the gateway dialled, so an answer relayed from another address does not fit.
def deck_proof(key, ours, theirs, address):
    return hmac.new(bytes.fromhex(key), f'deck|{ours}|{theirs}|{address}'.encode(), hashlib.sha256).hexdigest()


def gateway_proof(key, ours, theirs, address):
    return hmac.new(bytes.fromhex(key), f'gateway|{ours}|{theirs}|{address}'.encode(), hashlib.sha256).hexdigest()


class Pairs:
    """Keys of the gateways that may sign in to this computer without its password."""
    def __init__(self, path, clock=time.time, owner=''):
        self.path, self.clock, self.owner = Path(path), clock, owner
        self.lock = threading.Lock()
        self.pending = {}  # our nonce -> (key id, gateway nonce, expires, address)
        self.adopt()

    def adopt(self):
        """Keys from before they were tied to the password get the current one's mark once, at start."""
        saved = read_json(self.path, {})
        if not self.owner or not isinstance(saved, dict) or all(not isinstance(v, dict) or 'owner' in v for v in saved.values()):
            return
        for pair in saved.values():
            if isinstance(pair, dict):
                pair.setdefault('owner', self.owner)
        try:
            private_write(self.path, saved)
        except OSError:
            pass  # Marked at the next start; until then they count as current.

    def load(self):
        """Keys made under the current password; ones from before keys were tied to it count as current."""
        saved = read_json(self.path, {})
        saved = saved if isinstance(saved, dict) else {}
        return {k: v for k, v in saved.items() if isinstance(v, dict) and isinstance(v.get('key'), str)
                and v.get('owner', self.owner) == self.owner}

    def create(self):
        """Called over a signed-in connection only: the key is the gateway's later proof of that sign-in."""
        with self.lock:
            pairs = self.load()
            for old in sorted(pairs, key=lambda k: pairs[k].get('created', 0))[:max(0, len(pairs) - MAX_PAIRS + 1)]:
                del pairs[old]
            identity, key = secrets.token_hex(8), secrets.token_hex(32)
            for pair in pairs.values():
                pair.setdefault('owner', self.owner)
            pairs[identity] = {'key': key, 'created': int(self.clock()), 'owner': self.owner}
            private_write(self.path, pairs)
        return {'id': identity, 'key': key}

    def challenge(self, identity, nonce, address):
        """Proves to a gateway that this is the computer it paired with; None for a key it does not have."""
        with self.lock:
            pair = self.load().get(identity)
            if not pair:
                return None
            now = self.clock()
            for old in [n for n, entry in self.pending.items() if entry[2] < now]:
                del self.pending[old]
            if len(self.pending) >= MAX_PENDING or sum(p[0] == identity for p in self.pending.values()) >= MAX_PENDING_PER_KEY:
                return None
            ours = secrets.token_hex(16)
            self.pending[ours] = (identity, nonce, now + CHALLENGE_TTL, address)
        return {'nonce': ours, 'proof': deck_proof(pair['key'], ours, nonce, address)}

    def accept(self, identity, nonce, proof):
        """The gateway's answer to our challenge; each challenge is good for one attempt."""
        with self.lock:
            pending = self.pending.pop(nonce, None)
            pair = self.load().get(identity)
            if not pending or not pair or pending[0] != identity or pending[2] < self.clock() or not isinstance(proof, str):
                return False
            return hmac.compare_digest(proof.encode('ascii', 'replace'), gateway_proof(pair['key'], nonce, pending[1], pending[3]).encode())


class Listener:
    """A second door of the panel on the local address, kept in step with the switch and with the address
    itself: a laptop gets a new one in every network."""
    def __init__(self, enabled, serve, primary, address=lambda: lan_address(), pause=30):
        self.enabled, self.serve, self.primary, self.address, self.pause = enabled, serve, primary, address, pause
        self.lock = threading.Lock()
        self.current, self.server, self.started = None, None, False

    def wanted(self):
        # Listening on every address already covers the local one; a second bind would only fail.
        if self.primary in ('0.0.0.0', '::') or not self.enabled():
            return None
        found = self.address()
        return found if found and found != self.primary else None

    def sync(self):
        wanted = self.wanted()
        with self.lock:
            if wanted == self.current:
                return wanted
            if self.server:
                self.server.shutdown()
                self.server.server_close()
            self.server, self.current = None, None
            if wanted:
                try:
                    self.server = self.serve(wanted)
                except OSError as error:
                    print(f'Local network address {wanted} could not be opened: {error}', flush=True)
                    return None
                self.current = wanted
                threading.Thread(target=self.server.serve_forever, name='agent-deck-lan', daemon=True).start()
                print(f'cc-panel also on http://{wanted} (local network, not encrypted)', flush=True)
        return wanted

    def status(self):
        with self.lock:
            return self.current

    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True
        threading.Thread(target=self.loop, name='agent-deck-lan-watch', daemon=True).start()

    def loop(self):
        while True:
            try:
                self.sync()
            except Exception as error:  # The main address keeps working; the next pass tries again.
                print(f'Local network check failed: {type(error).__name__}', flush=True)
            time.sleep(self.pause)
