"""Loopback-only Anthropic pass-through and text-free per-request measurements."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
import hmac
import http.client
import json
import math
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from urllib.parse import urlsplit

IDENTITY = re.compile(r'^[0-9a-f]{24}$')
_lock = threading.RLock()


def read_json(path, default):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Private provider configuration must not be a symlink')
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def private_write(path, data):
    path = Path(path)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError('Private provider configuration must not be a symlink')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Bindings:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'model-bindings.json'

    def create(self, profile, model):
        identity = secrets.token_hex(12)
        with _lock:
            data = read_json(self.path, {})
            if len(data) >= 2000:
                raise ValueError('Too many saved model sessions')
            data[identity] = {'profile': profile['id'], 'url': profile['url'], 'model': model}
            private_write(self.path, data)
        return identity

    def prune(self, references):
        with _lock:
            data = read_json(self.path, {})
            kept = {key:value for key,value in data.items() if key in references}
            if kept != data:
                private_write(self.path, kept)

    def get(self, identity):
        if not isinstance(identity, str) or not IDENTITY.fullmatch(identity):
            raise ValueError('Invalid model session')
        with _lock:
            item = read_json(self.path, {}).get(identity)
        if not item:
            raise ValueError('Model session not found')
        return item

    def remove(self, identity):
        with _lock:
            data = read_json(self.path, {})
            data.pop(identity, None)
            private_write(self.path, data)


class Measurements:
    def __init__(self, started):
        self.started, self.first = started, None
        self.usage, self.buffer = {}, b''

    def event(self, data):
        if not isinstance(data, dict):
            return
        if data.get('type') == 'content_block_delta':
            delta = data.get('delta', {})
            if isinstance(delta, dict) and any(delta.get(k) for k in ('text', 'thinking', 'partial_json')):
                if self.first is None:
                    self.first = time.monotonic()
        usage = data.get('usage') or data.get('message', {}).get('usage')
        if isinstance(usage, dict):
            for key, value in usage.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                    self.usage[key] = value

    def feed(self, chunk):
        self.buffer += chunk
        if len(self.buffer) > 1024 * 1024:
            self.buffer = b''
            return
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if line.startswith(b'data:'):
                try:
                    self.event(json.loads(line[5:].strip()))
                except (ValueError, UnicodeError, AttributeError):
                    pass

    def result(self):
        now = time.monotonic()
        result = {'request_time_seconds': now-self.started}
        for key in ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'):
            if key in self.usage:
                result[key] = self.usage[key]
        if self.first is not None:
            result['time_to_first_token_seconds'] = self.first-self.started
            tokens = self.usage.get('output_tokens', 0)
            duration = now-self.first
            if tokens > 1 and duration > 0:
                result['tokens_per_second'] = (tokens-1)/duration
        return result


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer's reverse DNS lookup can block launchd startup on macOS.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Relay:
    def __init__(self, directory, profiles):
        self.directory, self.profiles = Path(directory), profiles
        self.bindings = Bindings(directory)
        self.config = self.directory / 'model-relay.json'
        self.server = None

    def start(self):
        with _lock:
            if self.server:
                return
            old = read_json(self.config, {})
            token = old.get('token') or secrets.token_hex(32)
            port = old.get('port', 0)
            if not isinstance(port, int) or not 0 <= port <= 65535:
                raise ValueError('Invalid model relay port')
            relay = self
            semaphore = threading.BoundedSemaphore(16)

            class Handler(BaseHTTPRequestHandler):
                protocol_version = 'HTTP/1.1'

                def log_message(self, *args):
                    pass

                def error(self, status, message):
                    body = json.dumps({'type':'error','error':{'type':'api_error','message':message}}).encode()
                    self.send_response(status)
                    self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(body)))
                    self.send_header('Connection','close')
                    self.end_headers()
                    self.close_connection = True
                    self.wfile.write(body)

                def do_GET(self):
                    match = re.fullmatch(r'/health/([0-9a-f]{32})', self.path)
                    if not match:
                        return self.error(404, 'Unknown endpoint')
                    proof = hmac.new(token.encode(), match[1].encode(), 'sha256').hexdigest()
                    body = json.dumps({'proof':proof}).encode()
                    self.send_response(200)
                    self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def do_POST(self):
                    authorization = self.headers.get('Authorization','')
                    supplied = authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else self.headers.get('x-api-key','')
                    if not hmac.compare_digest(supplied.encode(), token.encode()):
                        return self.error(401, 'Model relay authentication required')
                    match = re.fullmatch(r'/providers/([0-9a-f]{24})(/v1/messages(?:/count_tokens)?)', urlsplit(self.path).path)
                    if not match:
                        return self.error(404, 'Unknown model relay endpoint')
                    if not semaphore.acquire(blocking=False):
                        return self.error(503, 'Too many concurrent model requests')
                    connection = None
                    headers_sent = False
                    try:
                        length = int(self.headers.get('Content-Length','-1'))
                        if not 0 <= length <= 16*1024*1024:
                            return self.error(413, 'Model request too large or missing length')
                        self.connection.settimeout(30)
                        body = self.rfile.read(length)
                        if len(body) != length:
                            return self.error(400, 'Incomplete model request')
                        payload = json.loads(body)
                        binding = relay.bindings.get(match[1])
                        if not isinstance(payload, dict) or payload.get('model') != binding['model']:
                            return self.error(400, 'Model does not match the saved session')
                        profile = relay.profiles.get(binding['profile'])
                        if profile['url'] != binding['url']:
                            return self.error(409, 'Saved session server differs from the current profile')
                        upstream = urlsplit(binding['url'])
                        klass = http.client.HTTPSConnection if upstream.scheme == 'https' else http.client.HTTPConnection
                        connection = klass(upstream.hostname, upstream.port, timeout=120)
                        headers = {'Content-Type':'application/json','Accept':'text/event-stream, application/json'}
                        for key in ('anthropic-version','anthropic-beta'):
                            if self.headers.get(key):
                                headers[key] = self.headers[key]
                        if profile.get('key'):
                            headers['Authorization'] = 'Bearer '+profile['key']
                            headers['x-api-key'] = profile['key']
                        measurement = Measurements(time.monotonic())
                        connection.request('POST',upstream.path.rstrip('/')+match[2],body,headers)
                        response = connection.getresponse()
                        if 300 <= response.status < 400:
                            return self.error(502, 'Model server redirects are not supported')
                        self.send_response(response.status)
                        content_type = response.getheader('Content-Type','application/json')
                        self.send_header('Content-Type',content_type)
                        self.send_header('Cache-Control','no-store')
                        self.send_header('Connection','close')
                        self.end_headers()
                        headers_sent = True
                        self.close_connection = True
                        streaming = 'text/event-stream' in content_type
                        collected = bytearray()
                        while True:
                            chunk = response.read1(8192)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()
                            if streaming:
                                measurement.feed(chunk)
                            elif len(collected) < 1024*1024:
                                collected.extend(chunk)
                        if not streaming:
                            try:
                                measurement.event(json.loads(collected))
                            except (ValueError, UnicodeError, AttributeError):
                                pass
                        if response.status == 200 and match[2] == '/v1/messages':
                            relay.profiles.record(binding['profile'],binding['model'],measurement.result())
                    except (ValueError, KeyError, TypeError, OSError, http.client.HTTPException):
                        if not headers_sent:
                            self.error(502, 'Local model request failed; check server and credentials')
                    finally:
                        if connection:
                            connection.close()
                        semaphore.release()

            self.server = LoopbackHTTPServer(('127.0.0.1',port),Handler)
            self.server.daemon_threads = True
            self.server.block_on_close = False
            private_write(self.config, {'port':self.server.server_port,'token':token})
            threading.Thread(target=self.server.serve_forever,daemon=True,name='model-relay').start()

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
