"""Sign-in cookies ended by logging out before they expire.

A cookie is `expiry.HMAC(expiry)`, valid for 90 days, so a copy kept elsewhere (another browser, a gateway
that was removed) would work until then. Logging out records the cookie's hash here, until its own expiry,
so that copy stops working too; other devices stay signed in.
"""
import hashlib
import json
from pathlib import Path
import threading
import time

from integrations.relay import private_write

MOST = 10000  # Hashes kept at most; the oldest expiries go first.


class SignOuts:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.lock = threading.Lock()
        self.ended = None  # hash -> expiry, read on first use

    def load(self):
        if self.ended is None:
            try:
                data = json.loads(self.path.read_text())
                self.ended = {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, int)} if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self.ended = {}
        return self.ended

    @staticmethod
    def key(token):
        return hashlib.sha256(token.encode('ascii', 'replace')).hexdigest()

    def ended_token(self, token):
        with self.lock:
            return self.key(token) in self.load()

    def end(self, token, expiry):
        with self.lock:
            now = int(self.clock())
            kept = {k: v for k, v in self.load().items() if v > now}
            kept[self.key(token)] = int(expiry)
            self.ended = dict(sorted(kept.items(), key=lambda item: item[1])[-MOST:])
            private_write(self.path, self.ended)
