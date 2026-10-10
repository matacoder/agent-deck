"""Pictures a session showed, kept so they stay viewable after the path leaves the screen.

A picture is collected only under the screenshot rule (its path is on that session's screen, it is PNG,
JPEG, WebP or GIF by content, up to 25 MB) and kept as a private copy: an agent overwriting /tmp/shot.png
or deleting it does not take earlier pictures with it.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time

from .images import MAX_BYTES, find_by_name, image_type, resolve

PATH_RE = re.compile(r'(?<![\w/.~@+-])(?:~?/)?(?:[\w.@+-]+/)*[\w.@+-]+\.(?:png|jpe?g|webp|gif)(?![\w-]|\.\w)', re.I)
HEAD_RE = re.compile(r'^[\w./@+-]+\.(?:png|jpe?g|webp|gif)(?![\w-]|\.\w)', re.I)
TAIL_RE = re.compile(r'[\w.~@+-]*/[\w./@+-]*$')
EXT = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif', 'image/webp': 'webp'}
KEEP = 200
KEEP_BYTES = 300 * 1024 * 1024
DAYS = 30
NAME_RE = re.compile(r'[A-Za-z0-9_-]{1,32}')


def mentioned(screen):
    """Picture paths on a screen; a path the agent hard-wrapped across lines is glued back first."""
    lines, out = screen.split('\n'), []
    i = 0
    while i < len(lines):
        line = lines[i]
        while i + 1 < len(lines):
            tail = TAIL_RE.search(line.rstrip())
            if not tail or PATH_RE.fullmatch(tail.group(0)) or not HEAD_RE.match(lines[i + 1]):
                break
            line = line.rstrip() + lines[i + 1]
            i += 1
        out.extend(m.group(0) for m in PATH_RE.finditer(line))
        i += 1
    return list(dict.fromkeys(out))


class Gallery:
    def __init__(self, root, clock=time.time):
        self.root, self.clock = Path(root), clock
        self.lock = threading.Lock()
        self.seen = {}  # (session, real path) -> (mtime_ns, size): unchanged files are not read again
        self.names = {}  # (session, bare name, folder) -> resolved path: a project search runs once

    def folder(self, session):
        if not NAME_RE.fullmatch(session or ''):
            raise ValueError('сессия не найдена')
        return self.root / session

    def load(self, session):
        index = self.folder(session) / 'index.json'
        try:
            data = json.loads(index.read_text())
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def save(self, session, items):
        folder = self.folder(session)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = folder / 'index.json.tmp'
        temporary.write_text(json.dumps(items, ensure_ascii=False))
        os.replace(temporary, folder / 'index.json')

    def locate(self, session, path, cwd, home):
        real = resolve(path, cwd, home)
        if '/' in path or real.is_file():
            return real
        key = (session, path, cwd)
        if key not in self.names:
            found = find_by_name(path, cwd, home)
            if not found:
                return None  # Not written yet: looked for again on a later screen.
            self.names[key] = found
        return self.names[key]

    def collect(self, session, screen, cwd, home):
        """Copies new pictures from this screen; returns how many were added."""
        added = 0
        for path in mentioned(screen):
            try:
                real = self.locate(session, path, cwd, home)
                if real and self.keep(session, Path(real), path):
                    added += 1
            except (OSError, ValueError):
                continue  # Missing, unreadable or not a picture: the screen shows it as text.
        return added

    def keep(self, session, real, mentioned_as):
        info = real.stat()
        stamp = (info.st_mtime_ns, info.st_size)
        if not real.is_file() or self.seen.get((session, str(real))) == stamp:
            return False
        self.seen[(session, str(real))] = stamp
        if info.st_size > MAX_BYTES:
            return False
        with open(real, 'rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        kind = image_type(data)
        if not kind or len(data) > MAX_BYTES:
            return False
        ident = hashlib.sha256(data).hexdigest()[:24]
        with self.lock:
            items = self.load(session)
            if any(item['id'] == ident for item in items):
                return False
            folder = self.folder(session)
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            target = folder / f'{ident}.{EXT[kind]}'
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
            items.append({'id': ident, 'file': target.name, 'path': str(real), 'shown': mentioned_as,
                          'name': real.name, 'kind': kind, 'size': len(data), 'at': int(self.clock())})
            self.save(session, self.prune(folder, items))
        return True

    def prune(self, folder, items):
        limit = self.clock() - DAYS * 86400
        items = [item for item in items if item['at'] >= limit][-KEEP:]
        while len(items) > 1 and sum(item['size'] for item in items) > KEEP_BYTES:
            items = items[1:]
        keep = {item['file'] for item in items} | {'index.json'}
        for path in folder.iterdir():
            if path.name not in keep:
                path.unlink(missing_ok=True)
        return items

    def items(self, session):
        """Newest first, without the copy's file name."""
        return [{key: item[key] for key in ('id', 'name', 'path', 'kind', 'size', 'at')}
                for item in reversed(self.load(session))]

    def picture(self, session, ident):
        item = next((item for item in self.load(session) if item['id'] == ident), None)
        if not item:
            raise FileNotFoundError('Картинки нет в галерее')
        path = self.folder(session) / item['file']
        return item['kind'], path

    def latest(self, session, path, cwd, home):
        """The newest kept copy of a picture the screen named: for a path that left the screen or a file
        that is gone or replaced."""
        try:
            real = str(resolve(path, cwd, home))
        except ValueError:
            return None
        for item in reversed(self.load(session)):
            if item['path'] == real or ('/' not in path and item['name'] == path):
                return item['kind'], self.folder(session) / item['file']
        return None

    def expire(self):
        """Galleries of sessions that are gone are deleted once their newest picture is 30 days old."""
        if not self.root.is_dir():
            return
        for folder in self.root.iterdir():
            if folder.is_dir() and NAME_RE.fullmatch(folder.name):
                with self.lock:
                    items = self.prune(folder, self.load(folder.name))
                    if items:
                        self.save(folder.name, items)
                    else:
                        for path in folder.iterdir():
                            path.unlink(missing_ok=True)
                        folder.rmdir()
