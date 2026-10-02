#!/usr/bin/env python3
"""SessionStart hook: remember the current Claude session id on the tmux session (for the panel)."""
import json, os, subprocess, sys
pane = os.environ.get("TMUX_PANE")
try:
    sid = json.load(sys.stdin).get("session_id")
except ValueError:
    sid = None
if pane and sid:
    subprocess.run(["tmux", "set-option", "-t", pane, "@cc_sid", sid], capture_output=True)
