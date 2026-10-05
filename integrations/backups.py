"""Encrypted backups of Agent Deck settings, integration keys and agent logins.

New backups use AES-256-GCM from `cryptography` (format ADBK2). Files written by 1.5.0 (ADBK1,
keyed BLAKE2b) remain readable so existing copies can still be restored.
"""
import base64
import getpass
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

from .dependencies import require

MAGIC = b'ADBK2\n'
LEGACY_MAGIC = b'ADBK1\n'
MAX_SEALED = 700 * 1024  # Base64 of this still fits the panel's 1 MB JSON request limit.
KEEP = 14
MAX_ORIGINS = 32
ORIGIN = re.compile(r'[0-9a-f]{24}')
# Archive name -> path under $HOME. Restore writes only here; archive names never become paths.
FILES = {
    'deck/kimi.json': '.config/cc-panel/kimi.json',
    'deck/network.json': '.config/cc-panel/network.json',
    'deck/projects.json': '.config/cc-panel/projects.json',
    'deck/update.json': '.config/cc-panel/update.json',
    'deck/instance-id': '.config/cc-panel/instance-id',
    'deck/telegram.json': '.config/cc-panel/integrations/telegram.json',
    'deck/lmstudio.json': '.config/cc-panel/integrations/lmstudio.json',
    'deck/decks.json': '.config/cc-panel/integrations/decks.json',
    'deck/kimi-config.toml': '.config/cc-panel/kimi-native/config.toml',
    'agents/claude-credentials.json': '.claude/.credentials.json',
    'agents/codex-auth.json': '.codex/auth.json',
    'agents/gh-hosts.yml': '.config/gh/hosts.yml',
}
MAX_FILE = 256 * 1024
CLAUDE_FILE = 'agents/claude-credentials.json'


def _derive(key, purpose):
    return hashlib.blake2b(b'', key=key, person=purpose, digest_size=32).digest()


def key_id(key):
    return hashlib.blake2b(key, person=b'adbk-keyid', digest_size=6).hexdigest()


def encode_code(key):
    raw = key + hashlib.blake2b(key, person=b'adbk-check', digest_size=2).digest()
    text = base64.b32encode(raw).decode().rstrip('=')
    return 'AD1-' + '-'.join(text[i:i + 4] for i in range(0, len(text), 4))


def decode_code(code):
    if not isinstance(code, str):
        raise ValueError('Неверный код восстановления')
    text = re.sub(r'[\s-]', '', code.upper()).removeprefix('AD1')
    try:
        raw = base64.b32decode(text + '=' * (-len(text) % 8))
    except (ValueError, TypeError):
        raise ValueError('Неверный код восстановления') from None
    key, check = raw[:32], raw[32:]
    if len(raw) != 34 or not hmac.compare_digest(check, hashlib.blake2b(key, person=b'adbk-check', digest_size=2).digest()):
        raise ValueError('Неверный код восстановления')
    return key


def _keystream_xor(key, nonce, data):
    # Keyed BLAKE2b is a PRF; in counter mode it gives a stream cipher (encrypt-then-MAC below).
    out = bytearray(len(data))
    for block in range(0, len(data), 64):
        pad = hashlib.blake2b(nonce + (block // 64).to_bytes(8, 'big'), key=key, digest_size=64).digest()
        chunk = data[block:block + 64]
        out[block:block + len(chunk)] = bytes(a ^ b for a, b in zip(chunk, pad))
    return bytes(out)


def _aes_key(key):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b'agent-deck backup aes-256-gcm').derive(key)


def seal(key, meta, data):
    require()
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    header = json.dumps({**meta, 'key_id': key_id(key)}, sort_keys=True, separators=(',', ':')).encode()
    prefix = MAGIC + len(header).to_bytes(4, 'big') + header
    nonce = secrets.token_bytes(12)
    # The header (origin, time, key id) is authenticated as associated data.
    return prefix + nonce + AESGCM(_aes_key(key)).encrypt(nonce, data, prefix)


def read_meta(blob):
    if not isinstance(blob, bytes) or not blob.startswith((MAGIC, LEGACY_MAGIC)) or len(blob) > MAX_SEALED:
        raise ValueError('Это не файл бэкапа Agent Deck')
    size = int.from_bytes(blob[len(MAGIC):len(MAGIC) + 4], 'big')
    start = len(MAGIC) + 4
    if size > 4096 or len(blob) < start + size + 12 + 16:
        raise ValueError('Файл бэкапа повреждён')
    try:
        meta = json.loads(blob[start:start + size])
    except ValueError:
        raise ValueError('Файл бэкапа повреждён') from None
    if (not isinstance(meta, dict) or not ORIGIN.fullmatch(str(meta.get('origin', '')))
            or not isinstance(meta.get('created'), int) or not isinstance(meta.get('name', ''), str)):
        raise ValueError('Файл бэкапа повреждён')
    return meta, start + size


def unseal(key, blob):
    meta, offset = read_meta(blob)
    if meta.get('key_id') != key_id(key):
        raise ValueError('Бэкап зашифрован другим кодом восстановления')
    if blob.startswith(LEGACY_MAGIC):
        return meta, _unseal_legacy(key, blob, offset)
    require()
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    try:
        return meta, AESGCM(_aes_key(key)).decrypt(blob[offset:offset + 12], blob[offset + 12:], blob[:offset])
    except InvalidTag:
        raise ValueError('Файл бэкапа повреждён или изменён') from None


def _unseal_legacy(key, blob, offset):
    """Read-only support for ADBK1 files from 1.5.0."""
    signed, tag = blob[:-32], blob[-32:]
    if len(blob) < offset + 24 + 32 or not hmac.compare_digest(
            tag, hashlib.blake2b(signed, key=_derive(key, b'adbk-mac'), digest_size=32).digest()):
        raise ValueError('Файл бэкапа повреждён или изменён')
    return _keystream_xor(_derive(key, b'adbk-enc'), blob[offset:offset + 24], signed[offset + 24:])


CLAUDE_KEYCHAIN = 'Claude Code-credentials'


def keychain_read(run=subprocess.run):
    """macOS Claude Code keeps its login in the Keychain rather than ~/.claude/.credentials.json."""
    try:
        result = run(['security', 'find-generic-password', '-s', CLAUDE_KEYCHAIN, '-w'], input=b'', capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    data = result.stdout.strip() if result.returncode == 0 else b''
    return data if data and len(data) <= MAX_FILE else None


def keychain_write(data, run=subprocess.run, account=None):
    # `security -i` reads the command from stdin and -X takes hex, so the secret is never in argv.
    account = account or getpass.getuser()
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', account):
        return False
    command = f'add-generic-password -U -a {account} -s "{CLAUDE_KEYCHAIN}" -X {data.hex()}\n'.encode()
    try:
        return run(['security', '-i'], input=command, capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def pack(home, keychain=None):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        def add(name, data, mtime):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), 0o600, int(mtime)
            archive.addfile(info, io.BytesIO(data))
        for name, relative in FILES.items():
            path = Path(home) / relative
            # Never follow links: a symlink could pull an unrelated file into the backup.
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE:
                continue
            add(name, path.read_bytes(), path.stat().st_mtime)
        if keychain and not (Path(home) / FILES[CLAUDE_FILE]).is_file():
            data = keychain()
            if data:
                add(CLAUDE_FILE, data, time.time())
    return buffer.getvalue()


def unpack(data):
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive.getmembers():
            if member.name not in FILES or not member.isfile() or member.size > MAX_FILE:
                raise ValueError('Бэкап содержит неожиданный файл: ' + member.name[:80])
            files[member.name] = archive.extractfile(member).read()
    return files


def write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError(f'{path} is a symlink; remove it and retry')
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Backups:
    def __init__(self, home, version, name, platform=sys.platform, keychain=(keychain_read, keychain_write)):
        self.home = Path(home)
        self.root = self.home / '.config/cc-panel'
        self.store_dir = self.root / 'backups'
        self.key_path = self.root / 'backup-key'
        self.version, self.name = version, name
        self.lock = threading.RLock()
        self.mac = platform == 'darwin'
        self.keychain_read, self.keychain_write = keychain

    def instance_id(self):
        path = self.root / 'instance-id'
        with self.lock:
            try:
                value = path.read_text().strip()
                if ORIGIN.fullmatch(value):
                    return value
            except OSError:
                pass
            value = secrets.token_hex(12)
            write_private(path, value.encode())
            return value

    def key(self):
        try:
            raw = self.key_path.read_bytes()
        except FileNotFoundError:
            return None
        if self.key_path.is_symlink() or len(raw) != 32:
            raise ValueError(f'{self.key_path} is invalid; enter the recovery code again')
        return raw

    def setup(self, code=None):
        """Without a code creates the key once and returns its recovery code; with a code joins it."""
        with self.lock:
            if code:
                key = decode_code(code)
                write_private(self.key_path, key)
                return {'key_id': key_id(key)}
            if self.key():
                raise ValueError('Бэкапы уже включены')
            key = secrets.token_bytes(32)
            write_private(self.key_path, key)
            return {'key_id': key_id(key), 'code': encode_code(key)}

    def create(self):
        with self.lock:
            key = self.key()
            if not key:
                raise ValueError('Сначала включите бэкапы')
            meta = {'origin': self.instance_id(), 'name': self.name(), 'created': int(time.time()),
                    'version': self.version(), 'format': 1}
            blob = seal(key, meta, pack(self.home, self.keychain_read if self.mac else None))
            if len(blob) > MAX_SEALED:
                raise ValueError('Бэкап больше 700 КБ; уменьшите файлы настроек')
            self.store(blob)
            return blob

    def store(self, blob):
        meta, _ = read_meta(blob)
        with self.lock:
            folder = self.store_dir / meta['origin']
            # Copies are bounded per machine (KEEP) and in machines, so a client cannot fill the disk.
            if not folder.is_dir() and self.store_dir.is_dir() and sum(1 for p in self.store_dir.iterdir() if p.is_dir()) >= MAX_ORIGINS:
                raise ValueError('Слишком много машин в хранилище бэкапов')
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            write_private(folder / f"{meta['created']}.adbk", blob)
            for old in sorted(folder.glob('*.adbk'), key=lambda p: p.name)[:-KEEP]:
                old.unlink()
        return meta

    def stored(self):
        result = []
        if not self.store_dir.is_dir():
            return result
        for path in sorted(self.store_dir.glob('*/*.adbk')):
            try:
                meta, _ = read_meta(path.read_bytes())
            except (ValueError, OSError):
                continue
            result.append({**meta, 'size': path.stat().st_size})
        return sorted(result, key=lambda m: -m['created'])

    def read(self, origin, created):
        if not ORIGIN.fullmatch(str(origin)) or not isinstance(created, int):
            raise ValueError('Бэкап не найден')
        try:
            return (self.store_dir / origin / f'{created}.adbk').read_bytes()
        except OSError:
            raise ValueError('Бэкап не найден') from None

    def latest(self):
        own = [m for m in self.stored() if m['origin'] == self.instance_id()]
        return own[0] if own else None

    def restore(self, blob, code=None):
        with self.lock:
            key = decode_code(code) if code else self.key()
            if not key:
                raise ValueError('Введите код восстановления')
            meta, data = unseal(key, blob)
            files = unpack(data)
            if code:
                write_private(self.key_path, key)
            if self.key():
                self.create()  # The state being replaced stays recoverable.
            warnings = []
            for name, content in files.items():
                if name == CLAUDE_FILE and self.mac:
                    # On a Mac the login belongs in the Keychain; no plaintext copy is left behind.
                    if not self.keychain_write(content):
                        warnings.append('Не удалось вернуть вход в Claude в связку ключей; войдите в Claude заново')
                    continue
                write_private(self.home / FILES[name], content)
            return {**meta, 'files': sorted(files), 'warnings': warnings}

    def report(self, value=None):
        path = self.store_dir / 'report.json'
        if value is not None:
            write_private(path, json.dumps(value).encode())
            return value
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return None

    def status(self):
        key = self.key()
        latest = self.latest() if key else None
        return {'configured': bool(key), 'key_id': key_id(key) if key else None, 'instance': self.instance_id(),
                'name': self.name(), 'last': latest['created'] if latest else None, 'stored': self.stored(),
                'report': self.report()}


def remote_json(decks, deck, method, path, body=None):
    payload = None if body is None else json.dumps(body).encode()
    status, _, raw = decks.request(deck, method, path, payload, timeout=20)
    try:
        data = json.loads(raw)
    except ValueError:
        data = {}
    if status != 200:
        if status == 404:
            raise ValueError('Обновите этот Agent Deck до версии с бэкапами')
        raise ValueError(data.get('error') or f'HTTP {status}')
    return data


def join_remote(backups, decks, deck):
    """Give a connected machine the shared key, but never replace a different key it already has."""
    key = backups.key()
    state = remote_json(decks, deck, 'GET', '/api/backups')
    if not state.get('configured'):
        remote_json(decks, deck, 'POST', '/api/backup_setup', {'code': encode_code(key)})
    elif state.get('key_id') != key_id(key):
        raise ValueError('На этой машине включены бэкапы с другим кодом восстановления')
    return state


def replicate(backups, decks):
    """Gateway cycle: own backup, a fresh backup from each connected machine, every copy on every other machine."""
    report = {'started': int(time.time()), 'machines': []}
    blobs = [backups.create()]
    reachable = []
    for deck in decks.status().get('decks', []):
        entry = {'id': deck['id'], 'name': deck.get('name', ''), 'ok': False}
        report['machines'].append(entry)
        try:
            join_remote(backups, decks, deck['id'])
            blob = base64.b64decode(remote_json(decks, deck['id'], 'POST', '/api/backup_now', {})['blob'])
            meta, _ = read_meta(blob)
            blobs.append(blob)
            reachable.append(entry)
            entry.update(ok=True, origin=meta['origin'], created=meta['created'])
        except (ValueError, KeyError, TypeError, OSError) as error:
            entry['error'] = str(error)[:200]
    own = backups.instance_id()
    for blob in blobs:
        meta, _ = read_meta(blob)
        if meta['origin'] != own:
            backups.store(blob)
        for entry in reachable:
            if entry['origin'] == meta['origin']:
                continue
            try:
                remote_json(decks, entry['id'], 'POST', '/api/backup_store', {'blob': base64.b64encode(blob).decode()})
                entry['copies'] = entry.get('copies', 0) + 1
            except (ValueError, OSError) as error:
                entry.update(ok=False, error=str(error)[:200])
    report['finished'] = int(time.time())
    return backups.report(report)
