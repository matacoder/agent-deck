"""Private LM Studio profiles and bounded discovery of known Tailscale peers."""
import concurrent.futures
import copy
import http.client
import ipaddress
import json
import math
from pathlib import Path
import secrets
import shutil
import subprocess
import threading
import time
from urllib.parse import urlsplit
from .relay import IDENTITY, private_write, read_json


class RemoteError(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__('Authentication required' if status in (401, 403) else 'Server request failed (%s)' % status)


def endpoint(value):
    if not isinstance(value, str) or any(ord(c) < 33 for c in value):
        raise ValueError('Invalid server URL')
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use an HTTP or HTTPS URL without credentials')
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError('Invalid port')
    return value.rstrip('/').removesuffix('/v1')


def request(url, path, method='GET', body=None, key='', timeout=3):
    parsed = urlsplit(endpoint(url))
    connection = (http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection)(parsed.hostname, parsed.port, timeout=timeout)
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'anthropic-version': '2023-06-01'}
    if key:
        headers.update({'Authorization': 'Bearer ' + key, 'x-api-key': key})
    try:
        connection.request(method, parsed.path.rstrip('/') + path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        if response.status != 200:
            raise RemoteError(response.status)
        raw = response.read(1048577)
        if len(raw) > 1048576:
            raise ValueError('Server response too large')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError('Invalid server response')
        return result
    finally:
        connection.close()


def models(url, key='', timeout=3):
    result = None
    for path in ('/api/v1/models', '/api/v0/models', '/v1/models'):
        try:
            result = request(url, path, key=key, timeout=timeout)
            break
        except RemoteError as error:
            if error.status != 404:
                raise
    if result is None:
        raise ValueError('Model API unavailable')
    output = []
    for item in (result.get('models') or result.get('data') or [])[:128]:
        if not isinstance(item, dict) or item.get('type') in ('embedding', 'embeddings'):
            continue
        identity = item.get('key') or item.get('id')
        if not isinstance(identity, str) or not identity or len(identity) > 240 or not identity.isprintable():
            continue
        instances = item.get('loaded_instances') or []
        config = instances[0].get('config', {}) if instances and isinstance(instances[0], dict) else {}
        quant = item.get('quantization')
        output.append({'id': identity, 'name': str(item.get('display_name') or identity)[:240], 'loaded': bool(instances) or item.get('state') == 'loaded', 'context_length': config.get('context_length'), 'max_context_length': item.get('max_context_length'), 'quantization': quant.get('name') if isinstance(quant, dict) else quant, 'trained_for_tool_use': (bool(item.get('capabilities', {}).get('trained_for_tool_use')) if isinstance(item.get('capabilities'), dict) else 'tool_use' in (item.get('capabilities') or [])), 'tool_tested': False})
    return output


METRICS = ('tokens_per_second', 'time_to_first_token_seconds', 'input_tokens', 'output_tokens', 'total_output_tokens', 'reasoning_output_tokens', 'model_load_time_seconds', 'request_time_seconds', 'cache_read_input_tokens', 'cache_creation_input_tokens')


class LMStudio:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'lmstudio.json'
        if self.directory.is_symlink() or self.path.is_symlink():
            raise ValueError('Private configuration must not be a symlink')
        self.lock = threading.RLock()
        self.profiles = read_json(self.path, {})
        self.job = {'phase': 'idle', 'results': [], 'checked': 0, 'total': 0, 'error': ''}
        self.cancel = threading.Event()

    def public(self, profile):
        return copy.deepcopy({k: v for k, v in profile.items() if k != 'key'}) | {'key_saved': bool(profile.get('key'))}

    def status(self):
        with self.lock:
            # The relay may belong to an older panel process after a restart.
            self.profiles = read_json(self.path, self.profiles)
            profiles = [self.public(p) for p in self.profiles.values()]
            live = []
            for path in list((self.directory / 'live-requests').glob('*.json'))[:128]:
                try:
                    sample = read_json(path, {})
                    age = time.time() - sample.get('updated_at', 0)
                    if 0 <= age <= 660:
                        sample['request_time_seconds'] = sample.get('request_time_seconds', 0) + age
                        live.append(sample)
                    elif age > 660:
                        path.unlink(missing_ok=True)
                except (ValueError, OSError, TypeError):
                    continue
            for profile in profiles:
                profile['activity'] = [s for s in live if s.get('profile') == profile['id']]
            return {'available': True, 'profiles': profiles, 'discovery': copy.deepcopy(self.job)}

    def get(self, identity):
        with self.lock:
            if not isinstance(identity, str) or not IDENTITY.fullmatch(identity) or identity not in self.profiles:
                raise ValueError('Unknown LM Studio profile')
            return copy.deepcopy(self.profiles[identity])

    def persist(self):
        private_write(self.path, self.profiles)

    def save(self, data):
        url = endpoint(data.get('url', ''))
        name = data.get('name', '')
        if not isinstance(name, str) or not name.strip() or len(name) > 100 or not name.isprintable():
            raise ValueError('Invalid profile name')
        key = data.get('key', '')
        if not isinstance(key, str) or len(key) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in key):
            raise ValueError('Invalid API key')
        if 'clear_key' in data and not isinstance(data['clear_key'], bool):
            raise ValueError('Invalid clear_key value')
        with self.lock:
            identity = data.get('id') or secrets.token_hex(12)
            old = self.get(identity) if data.get('id') else {}
            p = old if old.get('url') == url else {'models': [], 'status': 'unchecked', 'error': '', 'performance': {}, 'measurements': {}}
            p.update(id=identity, name=name.strip(), url=url, key='' if data.get('clear_key') else key or (old.get('key', '') if old.get('url') == url else ''))
            self.profiles[identity] = p
            self.persist()
            return self.public(p)

    def remove(self, identity):
        with self.lock:
            self.get(identity)
            del self.profiles[identity]
            self.persist()

    def probe(self, identity):
        p = self.get(identity)
        try:
            found = models(p['url'], p.get('key', ''))
            verified = {m['id'] for m in p['models'] if m.get('tool_tested')}
            for model in found:
                model['tool_tested'] = model['id'] in verified
            updates = {'models': found, 'status': 'online', 'error': ''}
        except Exception as error:
            updates = {'status': 'needs_key' if isinstance(error, RemoteError) and error.status in (401, 403) else 'offline', 'error': 'Authentication required' if isinstance(error, RemoteError) and error.status in (401, 403) else 'Could not connect to model API'}
        with self.lock:
            current = self.profiles.get(identity)
            if current is None or current['url'] != p['url']:
                raise ValueError('Profile changed during request')
            current.update(updates, last_checked=time.time())
            self.persist()
            return self.public(current)

    def selected(self, data):
        p = self.get(data.get('id'))
        model = data.get('model')
        if model not in [m['id'] for m in p['models']]:
            raise ValueError('Select a known model')
        return p, model

    def test(self, data):
        p, model = self.selected(data)
        try:
            answer = request(p['url'], '/v1/messages', 'POST', {'model': model, 'max_tokens': 512, 'messages': [{'role': 'user', 'content': 'Call deck_healthcheck with ok=true.'}], 'tools': [{'name': 'deck_healthcheck', 'description': 'Connection test', 'input_schema': {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}, 'required': ['ok']}}], 'tool_choice': {'type': 'any'}}, p.get('key', ''), 30)
            ok = any(isinstance(item, dict) and item.get('type') == 'tool_use' and item.get('name') == 'deck_healthcheck' and item.get('input', {}).get('ok') is True for item in answer.get('content', []))
            result = {'ok': ok}
            if not ok:
                result['error'] = 'Model did not return a valid tool call'
            with self.lock:
                if identity := self.profiles.get(p['id']):
                    if identity['url'] != p['url']:
                        raise ValueError('Profile changed during request')
                    for item in identity['models']:
                        if item['id'] == model:
                            item['tool_tested'] = ok
                    self.persist()
        except Exception:
            result = {'ok': False, 'error': 'Tool test failed'}
        return {'profile': self.public(self.get(p['id'])), 'result': result}

    def record(self, identity, model, metrics, source='session'):
        clean = {k: v for k, v in metrics.items() if k in METRICS and isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0}
        with self.lock:
            if identity not in self.profiles:
                return
            sample = dict(clean, model=model, source=source, measured_at=time.time())
            self.profiles[identity]['performance'] = sample
            self.profiles[identity].setdefault('measurements', {}).setdefault(source, {})[model] = sample
            self.persist()

    def benchmark(self, data):
        p, model = self.selected(data)
        try:
            answer = request(p['url'], '/api/v1/chat', 'POST', {'model': model, 'input': 'Count from 1 to 20.', 'max_output_tokens': 96, 'store': False}, p.get('key', ''), 60)
            stats = answer.get('stats')
            if not isinstance(stats, dict) or not any(k in stats for k in METRICS):
                raise ValueError('No measured statistics')
            if self.get(p['id'])['url'] != p['url']:
                raise ValueError('Profile changed during benchmark')
            self.record(p['id'], model, stats, 'benchmark')
            result = {'ok': True}
        except Exception:
            result = {'ok': False, 'error': 'Benchmark unavailable; requires native LM Studio chat statistics'}
        return {'profile': self.public(self.get(p['id'])), 'result': result}

    def discover(self, data):
        if data.get('cancel') is True:
            self.cancel.set()
            return self.status()['discovery']
        ports = data.get('ports', [1234])
        if not isinstance(ports, list) or not 1 <= len(ports) <= 8 or any(type(p) is not int or not 1 <= p <= 65535 for p in ports):
            raise ValueError('Choose up to eight valid ports')
        with self.lock:
            if self.job['phase'] == 'running':
                return copy.deepcopy(self.job)
            self.cancel.clear()
            self.job = {'phase': 'running', 'results': [], 'checked': 0, 'total': 0, 'error': ''}
        threading.Thread(target=self._discover, args=(list(dict.fromkeys(ports)),), daemon=True).start()
        return self.status()['discovery']

    def _discover(self, ports):
        try:
            binary = shutil.which('tailscale')
            mac = Path('/Applications/Tailscale.app/Contents/MacOS/Tailscale')
            binary = binary or (str(mac) if mac.is_file() else None)
            if not binary:
                raise ValueError('Tailscale is not installed')
            result = subprocess.run([binary, 'status', '--json'], capture_output=True, text=True, timeout=5, check=True)
            nodes = json.loads(result.stdout)
            targets, seen = [], set()
            for node in [nodes.get('Self', {})] + list((nodes.get('Peer') or {}).values()):
                if node.get('Online') is False:
                    continue
                for raw in node.get('TailscaleIPs', []):
                    try:
                        ip = ipaddress.ip_address(raw)
                        if ip not in ipaddress.ip_network('100.64.0.0/10') and ip not in ipaddress.ip_network('fd7a:115c:a1e0::/48'):
                            continue
                    except ValueError:
                        continue
                    if str(ip) in seen:
                        continue
                    seen.add(str(ip))
                    host = '[' + str(ip) + ']' if ip.version == 6 else str(ip)
                    targets.extend((str(node.get('HostName') or node.get('DNSName') or ip)[:100], 'http://' + host + ':' + str(port)) for port in ports)
                    break
                if len(seen) >= 128:
                    break
            with self.lock:
                self.job['total'] = len(targets)
            deadline = time.monotonic() + 30
            def check(target):
                if self.cancel.is_set() or time.monotonic() >= deadline:
                    return False
                name, url = target
                try:
                    return {'name': name, 'url': url, 'status': 'online', 'models': models(url, timeout=1.5)}
                except RemoteError as error:
                    return {'name': name, 'url': url, 'status': 'needs_key', 'models': []} if error.status in (401, 403) else None
                except Exception:
                    return None
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                for found in pool.map(check, targets):
                    with self.lock:
                        if found is not False:
                            self.job['checked'] += 1
                        if found:
                            self.job['results'].append(found)
            with self.lock:
                self.job['phase'] = 'cancelled' if self.cancel.is_set() else 'error' if self.job['checked'] < self.job['total'] else 'done'
                if self.job['phase'] == 'error':
                    self.job['error'] = 'Discovery timed out; some nodes were not checked'
        except Exception:
            with self.lock:
                self.job.update(phase='error', error='Could not read Tailscale peers')
