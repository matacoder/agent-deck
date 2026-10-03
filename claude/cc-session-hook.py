#!/usr/bin/env python3
"""Installed compatibility entrypoint; panel updates also update the hook implementation."""
import runpy
import os
import sys

runtime = os.path.expanduser("~/.local/share/agent-deck/panel") if sys.platform == "darwin" else "/opt/cc-panel"
runpy.run_path(os.path.join(runtime, "session_hook.py"), run_name="__main__")
