"""Images an agent mentions on screen (screenshots, previews), served read-only to the panel.

A file is served only if its path is visible in that session's recent output, it is a regular
PNG/JPEG/WebP/GIF by content (never SVG: it can carry script), and it is not too large.
"""
import os
from pathlib import Path
import re

EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.gif')
MAX_BYTES = 25 * 1024 * 1024


def image_type(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def visible(path, screen):
    """Agents and terminals hard-wrap long paths, so compare without any whitespace."""
    needle = re.sub(r'\s+', '', path)
    return bool(needle) and needle in re.sub(r'\s+', '', screen)


def resolve(path, cwd, home):
    if not isinstance(path, str) or not path or len(path) > 4096 or '\x00' in path:
        raise ValueError('Неверный путь к картинке')
    if path.startswith('~/'):
        candidate = Path(home) / path[2:]
    elif path.startswith('/'):
        candidate = Path(path)
    else:
        candidate = Path(cwd) / path
    return Path(os.path.realpath(candidate))


def read_image(path, cwd, home, screen):
    if not path.lower().endswith(EXTENSIONS):
        raise ValueError('Показываются только PNG, JPEG, WebP и GIF')
    if not visible(path, screen):
        raise ValueError('Этой картинки нет на экране сессии')
    real = resolve(path, cwd, home)
    if not real.is_file() or not str(real).lower().endswith(EXTENSIONS):
        raise FileNotFoundError(f'Картинка не найдена: {path}')
    if real.stat().st_size > MAX_BYTES:
        raise ValueError('Картинка больше 25 МБ')
    with open(real, 'rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    kind = image_type(data)
    if not kind:
        raise ValueError(f'Файл не похож на картинку: {path}')
    return kind, data
