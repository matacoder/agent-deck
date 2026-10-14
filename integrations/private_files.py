"""Settings and secrets only their owner may read: written whole or not at all, never through a symlink."""
import contextlib
import json
import os
from pathlib import Path
import tempfile


def write_private(path, data):
    """Replace path with data (bytes or text) in mode 0600; a crash leaves the old file or the new one."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f'{path} is a symbolic link; remove it and retry')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # mkstemp creates the file 0600, so the secret is never readable by others, not even for a moment.
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data.encode() if isinstance(data, str) else data)
            stream.flush()
            os.fsync(stream.fileno())  # Otherwise a power cut after the rename can leave an empty file.
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def write_json(path, value, **options):
    write_private(path, json.dumps(value, **options))


def read_json(path, default):
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f'{path} is a symbolic link; remove it and retry')
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
