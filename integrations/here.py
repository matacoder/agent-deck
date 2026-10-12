"""Lets a page learn that it is open on this very computer.

The panel listens on its Tailscale address, and a browser on the same machine also reaches 127.0.0.1. A page
of a gateway, opened from anywhere, asks the loopback address one question: "are you installation X?". Only
the right id gets an answer that another site's page may read; nothing else of the panel is served here.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import re
import threading
from urllib.parse import parse_qs, urlsplit

INSTANCE = re.compile(r'[0-9a-f]{24}\Z')
EVERYWHERE = ('0.0.0.0', '::', '127.0.0.1', 'localhost')  # The panel's own listener already covers loopback.
OPEN = {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Private-Network': 'true', 'Cache-Control': 'no-store'}


def answer(path, instance):
    """(status, headers, body) for `/api/here?id=...`. A wrong id looks like no panel at all: without the
    headers a page of another origin cannot read the answer, so it learns nothing it did not know."""
    asked = parse_qs(urlsplit(path).query).get('id', [''])[0]
    if not INSTANCE.match(instance or '') or not hmac.compare_digest(asked.encode('utf-8', 'replace'), instance.encode()):
        return 404, {}, b'{}'
    return 200, OPEN, b'{"same": true}'


def responder(instance):
    class Responder(BaseHTTPRequestHandler):
        timeout = 5  # One short question per connection; nobody holds a thread here.

        def reply(self, status, headers, body):
            self.send_response(status)
            for name, value in {**headers, 'Content-Type': 'application/json', 'Content-Length': str(len(body))}.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def do_GET(self):
            self.reply(*(answer(self.path, instance()) if self.path.startswith('/api/here?') else (404, {}, b'{}')))

        def do_OPTIONS(self):  # A browser may ask first whether a public page may talk to this machine.
            self.reply(204, {**OPEN, 'Access-Control-Allow-Methods': 'GET'}, b'')

        def log_message(self, *args):
            pass
    return Responder


def start(bind_host, port, instance, serve=ThreadingHTTPServer):
    """The loopback answerer next to a panel bound to another address; None when it is not needed or the
    port is taken (then pages simply do not learn they are local)."""
    if bind_host in EVERYWHERE:
        return None
    try:
        server = serve(('127.0.0.1', port), responder(instance))
    except OSError as error:
        print(f'Loopback answer on port {port} is not available: {error}', flush=True)
        return None
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name='agent-deck-here', daemon=True).start()
    return server
