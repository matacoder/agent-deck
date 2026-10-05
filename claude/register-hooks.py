#!/usr/bin/env python3
"""Add our SessionStart hook without replacing existing user hooks or trust settings."""
import json
import os
from pathlib import Path
import sys
import tempfile


class SettingsError(ValueError):
    pass


def load(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError) as error:
        raise SettingsError(f"{path} is not valid JSON ({error}). Fix or remove it and run the installer again.") from None
    hooks = data.get("hooks", {}) if isinstance(data, dict) else None
    groups = hooks.get("SessionStart", []) if isinstance(hooks, dict) else None
    if not isinstance(groups, list) or not all(
            isinstance(g, dict) and isinstance(g.get("hooks", []), list)
            and all(isinstance(h, dict) for h in g.get("hooks", [])) for g in groups):
        raise SettingsError(f'{path} has an unexpected "hooks" structure. '
                            'Fix hooks.SessionStart and run the installer again.')
    return data


def write(path, data):
    # Write through symlinks (dotfiles/stow) and keep the user's file mode.
    target = path.resolve() if path.is_symlink() else path
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = target.stat().st_mode & 0o7777 if target.exists() else None
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix="hooks-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def register(home, command="python3 ~/.claude/cc-session-hook.py"):
    hook = {"type": "command", "command": command}
    for relative in (".claude/settings.json", ".codex/hooks.json"):
        path = Path(home) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = load(path)
        groups = data.setdefault("hooks", {}).setdefault("SessionStart", [])
        if any(h.get("command") == hook["command"] for g in groups for h in g.get("hooks", [])):
            continue
        groups.append({"hooks": [hook]})
        write(path, data)


if __name__ == "__main__":
    try:
        register(Path.home())
    except SettingsError as error:
        print(f"register-hooks: {error}", file=sys.stderr)
        sys.exit(1)
