#!/usr/bin/env python3
"""Remember only the top-level Claude/Codex conversation in a managed tmux pane."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def parent_info(pid):
    fields = {}
    for line in (Path("/proc") / str(pid) / "status").read_text().splitlines():
        key, _, value = line.partition(":")
        fields[key] = value.strip()
    return int(fields["PPid"]), fields["Name"]


def top_level(pane_pid, pid):
    agents = 0
    for _ in range(64):
        if pid == pane_pid:
            return agents == 1
        if pid <= 1:
            return False
        pid, name = parent_info(pid)
        if name == "claude" or name.startswith("codex"):
            agents += 1
        if agents > 1:
            return False
    return False


def remember(data, pane, pid):
    sid = data.get("session_id")
    try:
        if str(uuid.UUID(sid)) != sid:
            return
    except (ValueError, TypeError, AttributeError):
        return
    result = subprocess.run(["tmux", "display-message", "-p", "-t", pane,
                             "#{pane_pid}\t#{session_name}"], capture_output=True, text=True, timeout=3)
    pane_pid, session = result.stdout.strip().split("\t")
    if session.startswith("cc-") and top_level(int(pane_pid), pid):
        subprocess.run(["tmux", "set-option", "-t", pane, "@cc_sid", sid],
                       capture_output=True, timeout=3)


def main():
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        return
    try:
        remember(json.load(sys.stdin), pane, os.getppid())
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired):
        pass  # The hook must never prevent a conversation from starting.


if __name__ == "__main__":
    main()
