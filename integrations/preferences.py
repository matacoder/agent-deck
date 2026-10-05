"""Persistent project-directory preference shared by the installer and panel."""
import json
import os
from pathlib import Path
import tempfile
import threading


class ProjectDirectory:
    def __init__(self, home, default):
        self.home = Path(home).resolve()
        self.path = self.home / '.config/cc-panel/projects.json'
        self.lock = threading.RLock()
        self.current = str(default)
        if self.path.exists():
            if self.path.is_symlink():
                raise ValueError('Project settings must not be a symlink')
            self.current = self.validate(json.loads(self.path.read_text())['directory'])

    def validate(self, raw):
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError('Project directory must be a non-empty path')
        path = self.home if raw == '~' else self.home / raw[2:] if raw.startswith('~/') else Path(raw).expanduser()
        if not path.is_absolute():
            raise ValueError('Project directory must be an absolute path or start with ~/')
        path = path.resolve()
        if not path.is_relative_to(self.home):
            raise ValueError('Project directory must be inside your home directory')
        if path.exists() and not path.is_dir():
            raise ValueError('Project path is not a directory')
        return str(path)

    def get(self):
        with self.lock:
            return self.current

    def save(self, raw):
        with self.lock:
            directory = self.validate(raw)
            Path(directory).mkdir(parents=True, exist_ok=True)
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.path.is_symlink() or self.path.parent.is_symlink():
                raise ValueError('Project settings must not be a symlink')
            fd, temporary = tempfile.mkstemp(dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump({'directory': directory}, stream)
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self.current = directory
            return directory
