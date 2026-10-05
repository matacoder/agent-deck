"""Web Push (RFC 8030/8291/8292): payload encryption and VAPID signatures via `cryptography`.

The library is installed by integrations.dependencies; callers check dependencies.require() first.
"""
import base64
import json
import secrets
import struct
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def _ec():
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def unb64url(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def private_key(raw=None):
    ec = _ec()
    return ec.derive_private_key(int.from_bytes(raw, 'big'), ec.SECP256R1()) if raw else ec.generate_private_key(ec.SECP256R1())


def private_bytes(key):
    return key.private_numbers().private_value.to_bytes(32, 'big')


def public_bytes(key):
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    return key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)


def _hkdf(salt, ikm, info, length):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def encrypt(plaintext, receiver_public, auth_secret, sender=None, salt=None):
    """aes128gcm content coding (RFC 8188/8291), one record."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ec = _ec()
    sender = sender or private_key()
    salt = salt or secrets.token_bytes(16)
    # from_encoded_point rejects points that are not on P-256 (invalid-curve attacks).
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), receiver_public)
    sender_public = public_bytes(sender)
    shared = sender.exchange(ec.ECDH(), receiver)
    ikm = _hkdf(auth_secret, shared, b'WebPush: info\x00' + receiver_public + sender_public, 32)
    cek = _hkdf(salt, ikm, b'Content-Encoding: aes128gcm\x00', 16)
    nonce = _hkdf(salt, ikm, b'Content-Encoding: nonce\x00', 12)
    header = salt + struct.pack('>I', 4096) + bytes([len(sender_public)]) + sender_public
    return header + AESGCM(cek).encrypt(nonce, plaintext + b'\x02', None)


def sign(key, message):
    """ES256 JWS signature: raw r||s, as RFC 7518 requires."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    r, s = decode_dss_signature(key.sign(message, _ec().ECDSA(hashes.SHA256())))
    return r.to_bytes(32, 'big') + s.to_bytes(32, 'big')


# ---------- VAPID (RFC 8292) and delivery ----------
PUSH_HOSTS = ('push.apple.com', 'fcm.googleapis.com', 'push.services.mozilla.com', 'notify.windows.com')


def allowed_endpoint(url):
    # Only real push services: an arbitrary URL would turn the panel into a request proxy.
    parts = urlsplit(url) if isinstance(url, str) else None
    host = (parts.hostname or '') if parts else ''
    return bool(parts and parts.scheme == 'https' and not parts.username and not parts.password and parts.port in (None, 443)
                and any(host == h or host.endswith('.' + h) for h in PUSH_HOSTS))


def vapid_header(private, endpoint, subject, now=None):
    parts = urlsplit(endpoint)
    claims = {'aud': f'{parts.scheme}://{parts.hostname}', 'exp': int((now or time.time()) + 12 * 3600), 'sub': subject}
    signing = b64url(b'{"typ":"JWT","alg":"ES256"}') + '.' + b64url(json.dumps(claims, separators=(',', ':')).encode())
    token = signing + '.' + b64url(sign(private, signing.encode()))
    return f'vapid t={token}, k={b64url(public_bytes(private))}'


def send(private, subject, subscription, payload, ttl=3600, urgency='normal', topic=None, opener=None):
    """Returns the push service's HTTP status; 404/410 mean the subscription is gone."""
    endpoint = subscription['endpoint']
    if not allowed_endpoint(endpoint):
        raise ValueError('Unsupported push service')
    body = encrypt(json.dumps(payload, ensure_ascii=False).encode(), unb64url(subscription['keys']['p256dh']),
                   unb64url(subscription['keys']['auth']))
    headers = {'Authorization': vapid_header(private, endpoint, subject), 'Content-Encoding': 'aes128gcm',
               'Content-Type': 'application/octet-stream', 'TTL': str(ttl), 'Urgency': urgency}
    if topic:
        headers['Topic'] = topic
    request = urllib.request.Request(endpoint, body, headers, method='POST')
    try:
        with (opener or urllib.request.urlopen)(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        error.close()
        return error.code
    except OSError:
        raise ValueError('Push service did not respond') from None


SERVICE_WORKER = r"""
// Agent Deck notifications. Served by the panel at /sw.js; no caching, no offline mode.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) {}
  const title = data.title || 'Agent Deck';
  event.waitUntil(Promise.all([
    self.registration.showNotification(title, {body: data.body || '', tag: data.tag || undefined, renotify: Boolean(data.tag),
      icon: '/icon-192.png', badge: '/icon-192.png', data: {url: data.url || '/', deck: data.deck || '', session: data.session || ''}}),
    self.navigator && self.navigator.setAppBadge && data.badge ? self.navigator.setAppBadge(data.badge).catch(() => {}) : null,
  ]));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const data = event.notification.data || {};
  event.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(list => {
    for (const client of list) {
      if (new URL(client.url).origin === self.location.origin) {
        client.postMessage({type: 'agent-deck-open', deck: data.deck, session: data.session});
        return client.focus();
      }
    }
    return self.clients.openWindow(data.url || '/');
  }));
});
"""
