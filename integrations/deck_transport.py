"""Requests to a connected computer: which addresses and paths are allowed, and one HTTP exchange."""
import http.client
import ipaddress
import re
import time
from urllib.parse import parse_qsl, urlsplit, unquote

from .lan import is_lan

TAILNET = ipaddress.ip_network('100.64.0.0/10')
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
    # A key or a link for signing in without the password is asked for only by the gateway itself
    # (`RemoteDecks.pair`, `RemoteDecks.direct`), never by a page through it.
    if decoded.startswith(('/api/decks', '/api/network', '/api/pair', '/api/direct')):
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
