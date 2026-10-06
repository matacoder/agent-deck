"""Persistent project-directory preference shared by the installer and panel."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading


class ProjectDirectory:
    def __init__(self, home, default):
        self.home = Path(home).resolve()
        self.path = self.home / '.config/cc-panel/projects.json'
        self.lock = threading.RLock()
        self.current = str(default)
        if self.current == str(self.home / 'projects') and (self.home / 'dev').is_dir():
            self.current = str(self.home / 'dev')
        if self.path.exists():
            # Saved data is re-validated at startup; a stale value must not crash-loop the panel.
            try:
                self.current = self.load()
            except (ValueError, KeyError, TypeError, OSError) as error:
                print(f'Agent Deck: ignoring {self.path} ({error}); using {self.current}. '
                      'Choose the project folder again in the panel settings.', file=sys.stderr)

    def load(self):
        if self.path.is_symlink():
            raise ValueError('Project settings must not be a symlink')
        saved = json.loads(self.path.read_text())
        current = self.validate(saved['directory'])
        if current == str(self.home / 'projects') and not saved.get('custom') and (self.home / 'dev').is_dir():
            current = str(self.home / 'dev')
        return current

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
                    json.dump({'directory': directory, 'custom':True}, stream)
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            self.current = directory
            return directory


class NetworkSettings:
    def __init__(self, home):
        self.path = Path(home) / '.config/cc-panel/network.json'
        self.lock = threading.RLock()
        self.data = {'name':'', 'public_url':'', 'isolate_terminals':False}
        if self.path.exists():
            try:
                self.data.update(self.load())
            except (ValueError, KeyError, TypeError, OSError) as error:
                print(f'Agent Deck: ignoring {self.path} ({error}); using default network settings. '
                      'Save the Agent Deck name again in the panel settings.', file=sys.stderr)

    def load(self):
        if self.path.is_symlink():
            raise ValueError('Network settings must not be a symlink')
        saved = json.loads(self.path.read_text())
        if (not isinstance(saved, dict) or not all(isinstance(saved.get(key, ''), str) for key in ('name', 'public_url'))
                or not isinstance(saved.get('isolate_terminals', False), bool)):
            raise TypeError('expected a JSON object with string name and public_url')
        return {key: saved[key] for key in self.data if key in saved}

    def get(self):
        with self.lock:return dict(self.data)

    def save(self, data):
        from urllib.parse import urlsplit
        from .relay import private_write
        name, raw = data.get('name',''), data.get('public_url','')
        isolate = data.get('isolate_terminals', self.get()['isolate_terminals'])
        if not isinstance(isolate, bool):
            raise ValueError('Terminal isolation must be on or off')
        if not isinstance(name,str) or not name.strip() or len(name)>100 or not name.isprintable():
            raise ValueError('Enter an Agent Deck name')
        if not isinstance(raw,str) or len(raw)>2048 or any(c in raw for c in ('\r','\n')):
            raise ValueError('Invalid public URL')
        if raw:
            parsed = urlsplit(raw)
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
                raise ValueError('Enter an http(s) address without a path')
            try:parsed.port
            except ValueError:raise ValueError('Invalid public URL port') from None
        with self.lock:
            value={'name':name.strip(),'public_url':raw.strip().rstrip('/'),'isolate_terminals':isolate}
            private_write(self.path,value)
            self.data=value
            return dict(value)
