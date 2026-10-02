#!/usr/bin/env python3
"""Installed compatibility entrypoint; panel updates also update the hook implementation."""
import runpy

runpy.run_path("/opt/cc-panel/session_hook.py", run_name="__main__")
