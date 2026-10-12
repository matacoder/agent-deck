"""Opening a connected computer's own panel straight from a gateway's page, without its password.

A page served over https cannot talk to a computer's plain address from inside (browsers forbid it), but it may
open that address as a page of its own. The gateway, already signed in to the computer, asks it for a link
that signs a browser in once: the secret rides in the part of the address after `#`, which browsers never send
to a server or put in a Referer, is good for one use within a minute, and is taken out of the address bar and
history before it is spent.
"""
import hmac
import secrets
import threading
import time

TTL = 60
MAX_PENDING = 8
TOKEN = r'[0-9a-f]{64}'

# No markup from outside and nothing to load: the page only hands the secret over and leaves.
PAGE = b"""<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer"><title>DeckAway</title>
<body style="background:#1c1c1e;color:#aaa;font:14px system-ui;padding:24px">Signing in\xe2\x80\xa6
<script>
const token=location.hash.slice(1);history.replaceState(null,"","/direct");
fetch("/api/direct_login",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token})})
  .then(answer=>location.replace(answer.ok?"/":"/login"),()=>location.replace("/login"));
</script>"""
HEADERS = (('Content-Type', 'text/html; charset=utf-8'), ('Cache-Control', 'no-store'), ('Referrer-Policy', 'no-referrer'),
           ('X-Content-Type-Options', 'nosniff'), ('X-Frame-Options', 'DENY'),
           ('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; connect-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'"))


class Links:
    """Secrets waiting to be spent, in memory only: a restart of the panel voids them."""
    def __init__(self, clock=time.time):
        self.clock, self.lock, self.pending = clock, threading.Lock(), {}

    def create(self):
        with self.lock:
            now = self.clock()
            for old in [token for token, expires in self.pending.items() if expires < now]:
                del self.pending[old]
            while len(self.pending) >= MAX_PENDING:
                del self.pending[min(self.pending, key=self.pending.get)]
            token = secrets.token_hex(32)
            self.pending[token] = now + TTL
        return token

    def redeem(self, token):
        """True once for a secret that was made here less than a minute ago."""
        if not isinstance(token, str):
            return False
        with self.lock:
            found = next((known for known in self.pending if hmac.compare_digest(known.encode(), token.encode('utf-8', 'replace'))), None)
            return found is not None and self.pending.pop(found) >= self.clock()
