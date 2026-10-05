"""Background stable-release updates using the panel's existing detached updater."""
import threading
import time
from pathlib import Path
from .relay import private_write, read_json


class AutoUpdates:
    INTERVAL = 1800
    RETRY = 900

    def __init__(self, directory, info, start, available, idle, clock=time.time):
        self.path = Path(directory) / 'updates.json'
        self.info, self.start, self.available, self.idle, self.clock = info, start, available, idle, clock
        self.lock = threading.RLock()
        error = ''
        try:
            self.enabled = read_json(self.path, {}).get('enabled', True) is True
        except (OSError,ValueError,AttributeError):
            self.enabled = False
            error = 'Could not read automatic update settings'
        self.last_check = None
        self.last_attempt = None
        self.latest = None
        self.phase = 'idle'
        self.error = error
        self.thread = None
        self.stop = threading.Event()

    def status(self):
        with self.lock:
            return {'enabled': self.enabled, 'phase': self.phase, 'last_check': self.last_check, 'error': self.error}

    def save(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError('Automatic updates must be enabled or disabled')
        with self.lock:
            private_write(self.path, {'enabled': enabled})
            self.enabled = enabled
            self.last_check = None
            self.latest = None
            self.phase = 'idle'
            self.error = ''
            return self.status()

    def tick(self):
        with self.lock:
            if not self.enabled or not self.available():return
            now = self.clock()
            if self.last_check is None or now-self.last_check >= self.INTERVAL:
                self.last_check = now
                self.phase = 'checking'
                try:
                    self.latest = self.info()
                    self.error = ''
                except Exception:
                    self.latest = None
                    self.phase = 'error'
                    self.error = 'Could not check the latest release'
                    return
            info = self.latest or {}
            if not info.get('update') or not info.get('can_update'):
                self.phase = 'idle'
                return
            if self.last_attempt is not None and now-self.last_attempt < self.RETRY:return
            if not self.idle():
                self.phase = 'waiting'
                return
            try:
                result = self.start()
                self.last_attempt = now
                self.phase = result.get('job', {}).get('phase', 'checking')
            except Exception:
                self.last_attempt = now
                self.phase = 'error'
                self.error = 'Could not start automatic update'

    def run(self):
        if self.thread and self.thread.is_alive():return
        def loop():
            if self.stop.wait(30):return
            while not self.stop.is_set():
                try:self.tick()
                except Exception:pass
                self.stop.wait(60)
        self.thread = threading.Thread(target=loop, daemon=True, name='agent-deck-updates')
        self.thread.start()
