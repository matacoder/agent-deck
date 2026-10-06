"""Small file browser for project folders: list, read and save text files (e.g. moving a secret into .env).

Everything stays inside the user's home. The panel's own folder (~/.config/cc-panel: password, keys,
integration tokens) is never listed, read or written. Saves are atomic, keep the file's mode, create new
files as 0600 and refuse to overwrite a file that changed since it was opened.
"""
import hashlib
import os
from pathlib import Path
import stat
import tempfile

MAX_TEXT = 1024 * 1024
MAX_ENTRIES = 2000
PRIVATE = ('.config/cc-panel',)


def _private(home):
    """Both the literal location and where it really is: ~/.config is often a symlink (stow, dotfiles)."""
    return {home / p for p in PRIVATE} | {Path(os.path.realpath(home / p)) for p in PRIVATE}


def _blocked(real, home):
    return any(real == blocked or blocked in real.parents for blocked in _private(home))


def _resolve(home, path):
    home = Path(os.path.realpath(home))
    if not isinstance(path, str) or not path or len(path) > 4096 or '\x00' in path:
        raise ValueError('Неверный путь')
    real = Path(os.path.realpath(os.path.expanduser(path) if path.startswith('~') else path))
    if real != home and home not in real.parents:
        raise ValueError('Файлы доступны только внутри домашней папки')
    if _blocked(real, home):
        raise ValueError('Эта папка хранит настройки и ключи панели и недоступна здесь')
    return home, real


def digest(data):
    return hashlib.sha256(data).hexdigest()


def listing(home, path):
    home, real = _resolve(home, path)
    if not real.is_dir():
        raise FileNotFoundError('Папка не найдена')
    entries = []
    with os.scandir(real) as items:
        for item in items:
            if len(entries) >= MAX_ENTRIES:
                break
            try:
                info = item.stat(follow_symlinks=True)
            except OSError:
                continue  # Broken symlink or no permission: not shown.
            child = real / item.name
            if child.resolve() != home and home not in child.resolve().parents:
                continue  # A symlink out of home is not followed.
            if _blocked(child, home) or _blocked(child.resolve(), home):
                continue
            entries.append({'name': item.name, 'dir': stat.S_ISDIR(info.st_mode), 'size': info.st_size,
                            'mtime': int(info.st_mtime)})
    entries.sort(key=lambda e: (not e['dir'], e['name'].lower()))
    return {'path': str(real), 'home': str(home), 'parent': str(real.parent) if real != home else None,
            'entries': entries, 'truncated': len(entries) >= MAX_ENTRIES}


def read_text(home, path):
    _, real = _resolve(home, path)
    if not real.is_file():
        raise FileNotFoundError('Файл не найден')
    if real.stat().st_size > MAX_TEXT:
        raise ValueError('Файл больше 1 МБ; откройте его в терминале')
    data = real.read_bytes()
    if b'\x00' in data:
        raise ValueError('Это не текстовый файл')
    try:
        content = data.decode('utf-8')
    except UnicodeDecodeError:
        raise ValueError('Файл не в кодировке UTF-8; откройте его в терминале') from None
    return {'path': str(real), 'content': content, 'hash': digest(data), 'size': len(data)}


def save_text(home, path, content, expected):
    """expected: hash from read_text, or None to create a new file that must not exist yet."""
    if not isinstance(content, str):
        raise ValueError('Неверное содержимое файла')
    data = content.encode('utf-8')
    if len(data) > MAX_TEXT:
        raise ValueError('Файл больше 1 МБ')
    _, real = _resolve(home, path)
    if not real.parent.is_dir():
        raise FileNotFoundError('Папка не найдена')
    exists = real.exists()
    if expected is None and exists:
        raise FileExistsError('Такой файл уже есть; откройте его, чтобы изменить')
    if expected is not None:
        if not real.is_file():
            raise FileNotFoundError('Файл не найден')
        if digest(real.read_bytes()) != expected:
            raise FileExistsError('Файл изменился после открытия; откройте его заново')
    mode = stat.S_IMODE(real.stat().st_mode) if exists else 0o600
    fd, temporary = tempfile.mkstemp(prefix='.agent-deck-', dir=real.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, real)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {'path': str(real), 'hash': digest(data), 'size': len(data)}
