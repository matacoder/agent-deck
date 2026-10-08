"""Images an agent mentions on screen (screenshots, previews), served read-only to the panel.

A file is served only if its path is visible in that session's recent output, it is a regular
PNG/JPEG/WebP/GIF by content (never SVG: it can carry script), and it is not too large.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.gif')
MAX_BYTES = 25 * 1024 * 1024
THUMB_SIZE = 480


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


CODERS = {'image/png': 'png', 'image/jpeg': 'jpeg', 'image/gif': 'gif', 'image/webp': 'webp'}
CACHE_DAYS = 7


def thumbnail_command(source, target, kind, which=shutil.which):
    """macOS ships sips; Linux may have ImageMagick. Without either the original is served."""
    if which('sips'):
        return ['sips', '-Z', str(THUMB_SIZE), '-s', 'format', 'jpeg', str(source), '--out', str(target)]
    for tool in ('magick', 'convert'):
        if which(tool):
            # An explicit coder: ImageMagick would otherwise pick SVG/PostScript delegates by content.
            return [tool, f'{CODERS[kind]}:{source}[0]', '-thumbnail', f'{THUMB_SIZE}x{THUMB_SIZE}>', 'jpeg:' + str(target)]
    return None


def prune_cache(cache, now=None):
    limit = (now or time.time()) - CACHE_DAYS * 86400
    for path in Path(cache).glob('*.jpg'):
        try:
            if path.stat().st_mtime < limit:
                path.unlink()
        except OSError:
            pass


def thumbnail(real, cache, kind, run=subprocess.run, which=shutil.which):
    info = real.stat()
    key = hashlib.sha256(f'{real}\0{info.st_mtime_ns}\0{info.st_size}'.encode()).hexdigest()[:32]
    cached = Path(cache) / (key + '.jpg')
    try:
        os.utime(cached)  # Recently viewed thumbnails survive pruning.
        return cached.read_bytes()
    except OSError:
        pass  # Not cached yet, or pruned by a concurrent request: build it again.
    Path(cache).mkdir(parents=True, exist_ok=True, mode=0o700)
    prune_cache(cache)
    fd, temporary = tempfile.mkstemp(dir=cache, suffix='.jpg')
    os.close(fd)
    try:
        command = thumbnail_command(real, temporary, kind, which)
        if not command:
            return None
        result = run(command, input=b'', capture_output=True, timeout=20)
        data = Path(temporary).read_bytes()
        if result.returncode != 0 or image_type(data) != 'image/jpeg':
            return None
        os.replace(temporary, cached)
        return data
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


SEARCH_DEPTH = 4
SEARCH_ENTRIES = 20000
# Dependencies, caches, the panel's settings, and macOS folders whose reading pops privacy prompts.
SKIP_DIRS = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', '.cache', '.config', 'Library', 'Desktop',
             'Documents', 'Downloads', 'Pictures', 'Movies', 'Music'}


def _visit(entry, name, deeper):
    try:
        if entry.is_dir(follow_symlinks=False):
            if entry.name not in SKIP_DIRS and not entry.name.startswith('.'):  # Hidden folders are private.
                deeper.append(Path(entry.path))
        elif entry.name == name and entry.is_file(follow_symlinks=False):
            return entry.stat(follow_symlinks=False).st_mtime, Path(entry.path)
    except OSError:
        pass
    return None


def find_by_name(name, cwd, home=None, depth=SEARCH_DEPTH, limit=SEARCH_ENTRIES):
    """Agents such as Codex print only a file name ("Viewed image shot.png"). Look for it inside the
    session's project folder: a few levels deep, never following links or entering dependency folders, with a
    cap on how much is read. The newest match wins. A session in the home folder itself (or outside it) is
    not searched: that would walk personal folders."""
    home = os.path.realpath(home or os.path.expanduser('~'))
    real = os.path.realpath(cwd)
    if real == home or not real.startswith(home + os.sep):
        return None
    best, seen, level = None, 0, [Path(real)]
    for _ in range(depth + 1):
        deeper = []
        for folder in level:
            try:
                entries = os.scandir(folder)  # Read lazily: a folder with millions of files stops at the cap.
            except OSError:
                continue
            with entries:
                for entry in entries:
                    seen += 1
                    if seen > limit:
                        return best and best[1]
                    found = _visit(entry, name, deeper)
                    if found and (not best or found[0] > best[0]):
                        best = found
        level = deeper
    return best and best[1]


def read_image(path, cwd, home, screen, cache=None):
    if not path.lower().endswith(EXTENSIONS):
        raise ValueError('Показываются только PNG, JPEG, WebP и GIF')
    if not visible(path, screen):
        raise ValueError('Этой картинки нет на экране сессии')
    real = resolve(path, cwd, home)
    if '/' not in path and not real.is_file():
        real = find_by_name(path, cwd, home) or real
    if not real.is_file() or not str(real).lower().endswith(EXTENSIONS):
        raise FileNotFoundError(f'Картинка не найдена: {path}')
    if real.stat().st_size > MAX_BYTES:
        raise ValueError('Картинка больше 25 МБ')
    with open(real, 'rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    # Content is checked before any converter sees the file: the extension alone proves nothing.
    kind = image_type(data)
    if not kind:
        raise ValueError(f'Файл не похож на картинку: {path}')
    if cache:
        small = thumbnail(real, cache, kind)
        if small:
            return 'image/jpeg', small
    return kind, data
