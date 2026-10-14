"""Pictures named by pasted text, fetched by the panel when the browser is not allowed to read them.

Most sites do not let another page read their pictures; the panel has no such limit, so it must set its own:
only https on the usual port, only a public address (checked, then dialled as checked, so a name cannot turn
into a machine of this network in between), no cookies or sign-in, a few redirects, a size cap, and the bytes
must be a picture.
"""
import base64
import http.client
import ipaddress
import socket
import ssl
import threading
from urllib.parse import urljoin, urlsplit

from .images import image_type

MAX_BYTES = 12 * 1024 * 1024
TIMEOUT = 10
REDIRECTS = 3
SLOTS = threading.BoundedSemaphore(2)  # A pasted page may name a dozen; they wait their turn.
AGENT = 'Mozilla/5.0 (compatible; DeckAway picture fetch)'


NAT64 = ipaddress.ip_network('64:ff9b::/96')


def public(address):
    """An IPv6 address that only carries an IPv4 one is judged by that one: it is where the connection ends."""
    if address.version == 6:
        inner = address.ipv4_mapped or address.sixtofour or (address.teredo or (None, None))[1]
        if address in NAT64:
            inner = ipaddress.ip_address(int(address) & 0xffffffff)
        if inner is not None:
            return inner.is_global
    return address.is_global


def public_addresses(host, resolve=socket.getaddrinfo):
    """Every address the name has, when all of them are on the public internet; ValueError otherwise."""
    try:
        found = {info[4][0] for info in resolve(host, 443, type=socket.SOCK_STREAM)}
    except (OSError, UnicodeError):
        raise ValueError('The picture address could not be found') from None
    if not found or not all(public(ipaddress.ip_address(address.split('%')[0])) for address in found):
        raise ValueError('The picture address is not on the public internet')
    return sorted(found)


def target(url):
    parts = urlsplit(url if isinstance(url, str) else '')
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or len(url) > 4096:
        raise ValueError('Only https picture addresses without a login can be fetched')
    try:
        port = parts.port
    except ValueError:
        port = 0
    if port not in (None, 443):
        raise ValueError('Only https picture addresses on the usual port can be fetched')
    return parts.hostname, (parts.path or '/') + ('?' + parts.query if parts.query else '')


class Pinned(http.client.HTTPSConnection):
    """Connects to the address that was checked, while the certificate is still checked against the name."""
    def __init__(self, host, address, timeout):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def exchange(host, address, path, timeout=TIMEOUT):
    """(status, location, body) of one GET; the body is read only for a 200 and never past the cap."""
    connection = Pinned(host, address, timeout)
    try:
        connection.request('GET', path, headers={'User-Agent': AGENT, 'Accept': 'image/*', 'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        if response.status != 200:
            return response.status, response.getheader('Location'), b''
        body = response.read(MAX_BYTES + 1)
        return 200, None, body
    finally:
        connection.close()


def fetch(url, resolve=socket.getaddrinfo, ask=exchange):
    """The picture's type and bytes; ValueError says what was wrong with the address or the answer."""
    with SLOTS:
        for _ in range(REDIRECTS + 1):
            host, path = target(url)
            address = public_addresses(host, resolve)[0]
            try:
                status, location, body = ask(host, address, path)
            except (OSError, http.client.HTTPException):
                raise ValueError('The picture could not be downloaded') from None
            if status in (301, 302, 303, 307, 308) and location:
                url = urljoin(url, location)
                continue
            if status != 200:
                raise ValueError(f'The picture could not be downloaded: its site answered {status}')
            if len(body) > MAX_BYTES:
                raise ValueError('The picture is larger than 12 MB')
            kind = image_type(body)
            if not kind:
                raise ValueError('The address did not return a PNG, JPEG, WebP or GIF picture')
            return kind, body
    raise ValueError('The picture address redirects too many times')


def action(data):
    kind, body = fetch(data.get('url'))
    return {'type': kind, 'data': base64.b64encode(body).decode('ascii')}
