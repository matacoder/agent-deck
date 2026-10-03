"""Exercise an installed macOS panel on a disposable CI runner, including a real update."""
import http.client
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.parse import urlencode

if sys.platform != 'darwin' or os.environ.get('CI') != 'true':
    raise SystemExit('This smoke test only runs on disposable macOS CI runners')

home = Path.home()
runtime = home / '.local/share/agent-deck/panel'
sys.path.insert(0, str(runtime))
import updater
settings = json.loads((home / '.config/cc-panel/macos.json').read_text())
port = int(settings['BIND_PORT'])
cookie = ''


def request(method, path, data=None, form=False):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    headers = {'Cookie': cookie}
    body = None
    if data is not None:
        body = urlencode(data) if form else json.dumps(data)
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    try:
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def tmux(*args):
    return subprocess.check_output(['tmux', '-L', 'agent-deck', *args], text=True).strip()


assert request('GET', '/api/server-metrics')[0] == 401
status, headers, _ = request('POST', '/login', {'username': settings['PANEL_USER'], 'password': settings['PANEL_PASSWORD']}, form=True)
assert status == 303
cookie = headers['Set-Cookie'].split(';', 1)[0]
assert request('POST', '/api/new', {'name': 'mac-smoke', 'project': 'mac-smoke', 'agent': 'shell', 'skip': False})[0] == 200
assert request('POST', '/api/send', {'name': 'mac-smoke', 'text': 'printf mac-smoke-ok'})[0] == 200
for _ in range(20):
    data = json.loads(request('GET', '/api/sessions?preview=mac-smoke')[2])
    if any('mac-smoke-ok' in session.get('preview', '') for session in data['sessions']):
        break
    time.sleep(.2)
else:
    raise AssertionError('Shell output did not reach the panel')
request('GET', '/api/server-metrics')
time.sleep(1.1)
metrics = json.loads(request('GET', '/api/server-metrics')[2])
assert metrics['memory_total'] > 0 and 0 <= metrics['cpu_percent'] <= 100, metrics
with socket.create_connection(('127.0.0.1', port), timeout=5) as client:
    client.sendall((f'GET /t/ws?arg=%3Dcc-mac-smoke HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n'
                    f'Origin: http://127.0.0.1:{port}\r\nCookie: {cookie}\r\n'
                    'Connection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\n'
                    'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Protocol: tty\r\n\r\n').encode())
    response = b''
    while b'\r\n\r\n' not in response:
        chunk = client.recv(4096)
        assert chunk, 'WebSocket closed before handshake'
        response += chunk
    assert b'101 Switching Protocols' in response, response

pid_before = tmux('display-message', '-p', '-t', '=cc-mac-smoke:', '#{pid}')
pane_before = tmux('display-message', '-p', '-t', '=cc-mac-smoke:', '#{pane_pid}')
# Exercise the actual detached updater launched by the running panel. Replace only
# its network fetch in this disposable installation with a local release fixture.
with tempfile.TemporaryDirectory(prefix='deck-update-', dir='/tmp') as directory:
    fixture = Path(directory)
    version = (runtime / 'VERSION').read_text().strip()
    updater_source = (runtime / 'updater.py').read_text()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w:gz') as bundle:
        for source in runtime.rglob('*'):
            relative = str(source.relative_to(runtime))
            if source.is_file() and relative in updater.REQUIRED | updater.ALLOWED:
                payload = source.read_bytes()
                member = tarfile.TarInfo('release/' + (relative if relative.startswith(('integrations/', 'locales/')) else 'panel/' + relative))
                member.size = len(payload)
                bundle.addfile(member, io.BytesIO(payload))
    (fixture / 'release.tar.gz').write_bytes(archive.getvalue())
    (fixture / 'release.json').write_text(json.dumps({'tag_name': 'v' + version}))
    shim = '\ndef fetch(url, limit):\n    from pathlib import Path\n    return (Path(' + repr(str(fixture)) + ') / ("release.json" if url.endswith("/latest") else "release.tar.gz")).read_bytes()\n\n'
    (runtime / 'updater.py').write_text(updater_source.replace('if __name__ == "__main__":', shim + 'if __name__ == "__main__":'))
    (runtime / 'VERSION').write_text('0.0.0\n')
    assert request('POST', '/api/update', {})[0] == 200
    state_path = home / '.config/cc-panel/update.json'
    for _ in range(100):
        state = json.loads(state_path.read_text())
        if state.get('phase') in ('done', 'error'):
            break
        time.sleep(.5)
    assert state.get('phase') == 'done', state
    assert (runtime / 'updater.py').read_text() == updater_source
    assert request('GET', '/api/sessions')[0] == 200
assert tmux('display-message', '-p', '-t', '=cc-mac-smoke:', '#{pid}') == pid_before
assert tmux('display-message', '-p', '-t', '=cc-mac-smoke:', '#{pane_pid}') == pane_before
print('macOS install, authenticated API, shell input, CPU/RAM, WebSocket and detached update: OK')
