"""Load the real application with only temporary files and test credentials."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
PNG = bytes.fromhex("89504e470d0a1a0a") + b"test-image"


class PanelCase(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory(prefix="agent-deck-test-"))
        self.home = Path(temporary)
        (self.home / ".config/cc-panel").mkdir(parents=True)
        self.enterContext(patch.dict(os.environ, {
            "PANEL_PASSWORD": "test-password-only", "PANEL_USER": "test-user",
            "BIND_HOST": "127.0.0.1", "PROJECTS_DIR": str(self.home / "projects"),
            "TTYD_SOCK": str(self.home / "ttyd.sock"),
            "UPDATE_REPO": "", "CHECKOUT": "",
        }))
        # Redirect expanduser, rather than change HOME or touch installed secrets.
        original = os.path.expanduser
        self.enterContext(patch("os.path.expanduser", side_effect=lambda path:
            str(self.home) + path[1:] if path == "~" or path.startswith("~/") else original(path)))
        spec = importlib.util.spec_from_file_location("isolated_panel", ROOT / "panel/panel.py")
        self.panel = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.panel)
        self.panel.tmux = Mock(side_effect=AssertionError("unexpected real tmux command"))
        self.enterContext(patch.object(self.panel.subprocess, "run",
            side_effect=AssertionError("unexpected external command")))
        self.panel.http_json = Mock(side_effect=AssertionError("unexpected external HTTP request"))

    def allow_session(self, agent="codex"):
        self.panel.session_exists = Mock(return_value=True)
        self.panel.opt = Mock(return_value=agent)
        self.panel.tmux = Mock(return_value="")
        self.enterContext(patch.object(self.panel.time, "sleep"))

    def upload(self, name="demo", image=PNG):
        import base64
        return self.panel.action_upload({"name": name, "data": base64.b64encode(image).decode()})["attachment"]
