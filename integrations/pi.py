"""Isolated Pi configuration and exact local conversation restoration."""
import hmac
import http.client
import json
import os
from pathlib import Path
import secrets
import shutil
import uuid
from .relay import Bindings, private_write, read_json


def executable():
    local = Path.home() / '.local/bin/pi'
    return str(local) if local.is_file() and os.access(local, os.X_OK) else shutil.which('pi')


def session_file(directory, sid, cwd):
    matches = []
    for path in Path(directory).glob('*_'+sid+'.jsonl'):
        if path.is_symlink():
            raise ValueError('Pi conversation must not be a symlink')
        with path.open() as stream:
            header = json.loads(stream.readline(65536))
        if header.get('type') == 'session' and header.get('id') == sid and header.get('cwd') == str(Path(cwd).resolve()):
            matches.append(path)
    if len(matches) != 1:
        raise ValueError('Exact Pi conversation not found for this project')
    return str(matches[0])


def prepare_local(directory, identity, sid, resume=False, name=None, cwd=None):
    if not isinstance(sid, str) or str(uuid.UUID(sid)) != sid:
        raise ValueError('Invalid Pi conversation ID')
    directory = Path(directory)
    binding = Bindings(directory).get(identity)
    profile = read_json(directory/'lmstudio.json', {}).get(binding['profile'])
    if not profile or profile['url'] != binding['url']:
        raise ValueError('Saved model binding differs from its profile')
    model = next((m for m in profile.get('models', []) if m['id'] == binding['model']), None)
    if model is None:
        raise ValueError('Saved local model is unavailable')
    binary = executable()
    if not binary:
        raise ValueError('Install Pi first')
    relay = read_json(directory/'model-relay.json', {})
    port, token = relay.get('port'), relay.get('token')
    if type(port) is not int or not 1 <= port <= 65535 or not isinstance(token, str) or not token:
        raise ValueError('Local model relay is unavailable')
    nonce = secrets.token_hex(16)
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        connection.request('GET', '/health/'+nonce)
        response = connection.getresponse()
        proof = json.loads(response.read(4096)).get('proof', '') if response.status == 200 else ''
        expected = hmac.new(token.encode(), nonce.encode(), 'sha256').hexdigest()
        if not isinstance(proof, str) or not hmac.compare_digest(proof, expected):
            raise ValueError('Local model relay could not be verified')
    finally:
        connection.close()
    home = directory/'pi'/identity
    for path in (directory, directory/'pi', home, home/'sessions'):
        if path.is_symlink():
            raise ValueError('Private Pi directory must not be a symlink')
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)
    context = model.get('context_length') or model.get('max_context_length') or 32768
    if type(context) is not int or context < 4:
        context = 32768
    config = {'providers': {'agent-deck-local': {
        'baseUrl': f'http://127.0.0.1:{port}/providers/{identity}',
        'api': 'anthropic-messages', 'apiKey': '${AGENT_DECK_LOCAL_TOKEN}',
        'models': [{'id': binding['model'], 'name': binding['model'], 'reasoning': False,
                    'input': ['text'], 'contextWindow': context, 'maxTokens': min(8192, context//4),
                    'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0}}]}}}
    private_write(home/'models.json', config)
    env = dict(os.environ)
    for key in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'OPENAI_API_KEY', 'GEMINI_API_KEY', 'GOOGLE_API_KEY', 'PI_CODING_AGENT_DIR', 'ANTHROPIC_BASE_URL', 'OPENAI_BASE_URL'):
        env.pop(key, None)
    env.update(PI_CODING_AGENT_DIR=str(home), PI_OFFLINE='1', AGENT_DECK_LOCAL_TOKEN=token)
    args = [binary, '--provider', 'agent-deck-local', '--model', binding['model'], '--session-dir', str(home/'sessions')]
    if resume:
        args += ['--session', session_file(home/'sessions', sid, cwd or os.getcwd())]
    else:
        args += ['--session-id', sid]
    if name:
        args += ['--name', name]
    return binary, args, env
