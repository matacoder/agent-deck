#!/usr/bin/env python3
"""Add our SessionStart hook without replacing existing user hooks or trust settings."""
import json
import os
from pathlib import Path
import tempfile


def register(home):
    hook = {"type": "command", "command": "python3 ~/.claude/cc-session-hook.py"}
    for relative in (".claude/settings.json", ".codex/hooks.json"):
        path = Path(home) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(path.read_text()) if path.exists() else {}
        groups = data.setdefault("hooks", {}).setdefault("SessionStart", [])
        if any(h.get("command") == hook["command"] for g in groups for h in g.get("hooks", [])):
            continue
        groups.append({"hooks": [hook]})
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix="hooks-")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream, indent=2)
                stream.write("\n")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


if __name__ == "__main__":
    register(Path.home())
