"""Services that speak Anthropic's API, so Claude Code can run on their models: GLM and whatever the owner adds.

A provider is a name, an https address, a key and a model. The key stays in a 0600 file and reaches Claude Code
only through its environment; it never appears in a tmux command, a log or an answer of the panel.
"""
import re
import secrets
import threading
from pathlib import Path
from urllib.parse import urlsplit

from .relay import private_write, read_json

PRESETS = {
    # The address is the service's own; the model is only a suggestion, the owner types the one their plan has.
    'glm': {'name': 'GLM', 'url': 'https://api.z.ai/api/anthropic', 'model': 'glm-5.3'},
}
IDENTITY = re.compile(r'[0-9a-f]{12}\Z')
MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,99}\Z')
KEY = re.compile(r'[!-~]{1,4096}\Z')
MAX_PROVIDERS = 16


def clean_url(raw):
    """An https address without credentials, query or fragment: the key is sent there."""
    parts = urlsplit(raw.strip() if isinstance(raw, str) else '')
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('The provider address must be an https:// address without a login, query or fragment')
    if len(raw) > 300 or not all(33 <= ord(c) < 127 for c in raw.strip()):
        raise ValueError('The provider address is too long or has characters an address cannot have')
    return raw.strip().rstrip('/')


class Providers:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def load(self):
        try:
            saved = read_json(self.path, {})
        except (OSError, ValueError):
            saved = {}  # A damaged file shows no providers instead of failing the whole list of agents.
        return {k: v for k, v in saved.items() if IDENTITY.match(k) and isinstance(v, dict)} if isinstance(saved, dict) else {}

    def public(self):
        """What the page may know: everything but the keys."""
        return [{'id': identity, 'name': p.get('name', ''), 'url': p.get('url', ''), 'model': p.get('model', ''),
                 'configured': bool(p.get('key'))} for identity, p in self.load().items()]

    def get(self, identity):
        """A provider ready to run on, key included; ValueError when it is gone or has no key."""
        provider = self.load().get(identity) if isinstance(identity, str) else None
        if not provider or not provider.get('key'):
            raise ValueError('This provider is not saved or has no key; open Settings → Agents')
        return provider

    def save(self, data):
        identity = data.get('id')
        name = ' '.join(str(data.get('name') or '').split())[:40]
        model, key = data.get('model'), data.get('key') or ''
        if not name or not name.isprintable():
            raise ValueError('Give the provider a name')
        if not isinstance(model, str) or not MODEL.match(model):
            raise ValueError('The model name has characters a model name cannot have')
        if not isinstance(key, str) or (key and not KEY.match(key)):
            raise ValueError('The key must be up to 4096 characters without spaces or line breaks')
        url = clean_url(data.get('url'))
        with self.lock:
            saved = self.load()
            if identity is None:
                if len(saved) >= MAX_PROVIDERS:
                    raise ValueError('Too many providers; remove one first')
                identity = secrets.token_hex(6)
            elif identity not in saved:
                raise ValueError('This provider is no longer saved')
            old = saved.get(identity, {})
            # A changed address never inherits the key that was typed for another one.
            key = key or (old.get('key', '') if old.get('url') == url else '')
            if not key:
                raise ValueError('Enter the key for this provider')
            saved[identity] = {'name': name, 'url': url, 'model': model, 'key': key}
            private_write(self.path, saved)
        return identity

    def remove(self, identity):
        with self.lock:
            saved = self.load()
            if saved.pop(identity, None) is not None:
                private_write(self.path, saved)


def environment(provider, model, inherited):
    """The environment Claude Code starts with on this provider."""
    env = dict(inherited)
    # A login or another inherited service must not outrank the provider chosen for this session.
    for name in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
        env.pop(name, None)
    env.update(ANTHROPIC_AUTH_TOKEN=provider['key'], ANTHROPIC_BASE_URL=provider['url'], ANTHROPIC_MODEL=model,
               CLAUDE_CODE_SUBAGENT_MODEL=model, API_TIMEOUT_MS='3000000')
    for tier in ('FABLE', 'OPUS', 'SONNET', 'HAIKU'):
        env['ANTHROPIC_DEFAULT_' + tier + '_MODEL'] = model
    return env
