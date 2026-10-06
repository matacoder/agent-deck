"""Pinned Python dependencies (cryptography) without pip, venv or root.

The panel downloads the exact wheels listed in dependency_lock.py, checks each SHA-256 and unpacks
them into a per-interpreter directory under ~/.local/share/agent-deck. The directory survives panel
updates; a changed lock or a new Python version gets a fresh directory.
"""
import hashlib
import importlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

from .dependency_lock import WHEELS

MAX_WHEEL = 32 * 1024 * 1024
ROOT = Path.home() / '.local/share/agent-deck/python'
_state = {'ready': False, 'installing': False, 'error': '', 'previous': False}
_lock = threading.Lock()


def platform_key():
    system, machine = sys.platform, platform.machine().lower()
    arch = {'amd64': 'x86_64', 'x86_64': 'x86_64', 'aarch64': 'aarch64', 'arm64': 'arm64'}.get(machine, machine)
    if system == 'linux':
        libc, _ = platform.libc_ver()
        if libc != 'glibc':
            return None  # musl (Alpine) has no matching wheels.
        arch = 'aarch64' if arch == 'arm64' else arch
    elif system == 'darwin':
        arch = 'arm64' if arch in ('arm64', 'aarch64') else arch
    else:
        return None
    return f'cp{sys.version_info[0]}{sys.version_info[1]}-{system}-{arch}'


def target(key, root=None):
    wheels = WHEELS[key]
    digest = hashlib.sha256(json.dumps(wheels, sort_keys=True).encode()).hexdigest()[:12]
    return (root or ROOT) / f'{key}-{digest}'


def _download(wheel, opener=None):
    request = urllib.request.Request(wheel['url'], headers={'User-Agent': 'Agent-Deck'})
    with (opener or urllib.request.urlopen)(request, timeout=60) as response:
        data = response.read(MAX_WHEEL + 1)
    if len(data) > MAX_WHEEL:
        raise ValueError(f"{wheel['filename']} is larger than expected")
    if hashlib.sha256(data).hexdigest() != wheel['sha256']:
        raise ValueError(f"{wheel['filename']} does not match its pinned SHA-256")
    return data


def _extract(data, folder):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            name = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            # Wheels are plain files under relative paths; anything else is refused.
            if name.is_absolute() or '..' in name.parts or (mode and (mode & 0o170000) == 0o120000):
                raise ValueError('Unsafe path in wheel: ' + member.filename[:80])
            if member.is_dir():
                continue
            path = folder / Path(*name.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, open(path, 'wb') as out:
                shutil.copyfileobj(source, out)
            path.chmod(0o755 if mode & 0o111 else 0o644)


def prune(folder):
    for old in folder.parent.glob(folder.name.rsplit('-', 1)[0] + '-*'):
        if old != folder and not old.name.startswith('.'):
            shutil.rmtree(old, ignore_errors=True)  # Superseded lock or interpreter build.


def install(key=None, root=None, opener=None, keep_previous=False):
    key = key or platform_key()
    if key not in WHEELS:
        raise ValueError(f'No prebuilt cryptography for {key or sys.platform}; Linux (glibc) and macOS are supported')
    folder = target(key, root)
    if (folder / '.complete').is_file():
        return folder
    base = folder.parent
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix='.install-', dir=base))
    try:
        for wheel in WHEELS[key]:
            _extract(_download(wheel, opener), staging)
        (staging / '.complete').write_text(json.dumps([w['filename'] for w in WHEELS[key]]))
        try:
            os.rename(staging, folder)
        except OSError:
            if not (folder / '.complete').is_file():
                raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    if not keep_previous:
        prune(folder)
    return folder


def previous_install(key, root=None):
    """The newest complete directory of an earlier lock for this interpreter, kept until the new one installs."""
    base = (root or ROOT)
    found = [p for p in base.glob(key + '-*') if (p / '.complete').is_file()] if base.is_dir() else []
    return max(found, key=lambda p: (p / '.complete').stat().st_mtime, default=None)


def activate(root=None, prune_old=True):
    """Prefer the pinned wheels; a cryptography that is already importable (system package) also works."""
    key = platform_key()
    folder = target(key, root) if key in WHEELS else None
    if folder and not (folder / '.complete').is_file() and key:
        # After an update that changed the lock and before the download finishes (or while offline),
        # the previous wheels keep backups and notifications working.
        previous = previous_install(key, root)
        if previous:
            folder, _state['previous'] = previous, True
    elif prune_old and folder and (folder / '.complete').is_file() and 'cryptography' not in sys.modules:
        prune(folder)  # Nothing is loaded yet, so copies of earlier locks can go.
    if folder and (folder / '.complete').is_file() and str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
        importlib.invalidate_caches()
    try:
        importlib.import_module('cryptography.hazmat.primitives.ciphers.aead')
    except ImportError as error:
        if folder and (folder / '.complete').is_file():
            _state['error'] = f'cryptography could not be loaded from {folder}: {error}'
        return False
    _state.update(ready=True, error='')
    return True


def ensure(background=True, retry=600, prune_old=True):
    """Make cryptography importable; downloads once, retries while offline.

    Installers pass prune_old=False: the panel they replace may still import from the old copy until it
    restarts, and the new panel prunes on its own start."""
    if (_state['ready'] or activate(prune_old=prune_old)) and not _state['previous']:
        return True

    def work():
        while True:
            with _lock:
                if _state['ready'] and not _state['previous']:
                    return
                _state['installing'] = True
                try:
                    # The running panel may still import modules lazily from the previous copy.
                    install(keep_previous=_state['previous'] or not prune_old)
                    _state['previous'] = False  # Loaded next start; the running copy keeps working.
                    if _state['ready'] or activate(prune_old=prune_old):
                        return
                except Exception as error:  # Network, disk or unsupported platform: report and retry.
                    _state['error'] = f'Could not install encryption components: {error}'
                finally:
                    _state['installing'] = False
            if not background:
                return
            time.sleep(retry)
    if background:
        threading.Thread(target=work, name='agent-deck-dependencies', daemon=True).start()
        return False
    work()
    return _state['ready']


def status():
    return dict(_state)


def require():
    if not _state['ready'] and not activate():
        detail = _state['error'] or 'the panel is still downloading them'
        raise ValueError('Компоненты шифрования ещё не установлены: ' + detail)


if __name__ == '__main__':
    # Installers run this as the panel user so a fresh install has the components right away.
    ensure(background=False, prune_old=False)
    print('cryptography ready' if _state['ready'] else _state['error'], flush=True)
    sys.exit(0 if _state['ready'] else 1)
