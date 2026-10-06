"""Recovery paths of install.sh (stale Tailscale address, rollback of a release that does not start).

Runs only extracted blocks with stubbed commands: never the installer itself, never as root.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from support import ROOT


def block(script, begin, end):
    text = (ROOT / script).read_text()
    start = text.index(begin)
    return text[start:text.index(end, start) + len(end)]


class InstallerRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def bash(self, source, env=None):
        return subprocess.run(["bash", "-c", "set -euo pipefail\n" + source], capture_output=True, text=True,
                              env={**os.environ, **(env or {})})

    HELPERS = 'die() { echo "$*" >&2; exit 1; }\nsay() { echo "$*"; }\n'

    def test_a_remembered_address_that_left_this_machine_is_resolved_again(self):
        source = self.HELPERS + block("install.sh", "bind_is_local() {", '    BIND_HOST=\nfi\n') + 'echo "host=$BIND_HOST"'
        for host, explicit, expected in (("127.0.0.1", "", "host=127.0.0.1"), ("203.0.113.9", "", "host="),
                                         ("127.0.0.1", "1", "host=127.0.0.1")):
            with self.subTest(host=host, explicit=explicit):
                result = self.bash(source, {"BIND_HOST": host, "BIND_HOST_EXPLICIT": explicit})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout.splitlines())
        refused = self.bash(source, {"BIND_HOST": "203.0.113.9", "BIND_HOST_EXPLICIT": "1"})
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("not an address of this machine", refused.stderr)

    def test_a_new_panel_that_does_not_answer_is_rolled_back(self):
        prefix, snapshot = self.directory / "prefix", self.directory / "rollback"
        prefix.mkdir(); snapshot.mkdir()
        (prefix / "panel.py").write_text("# broken new release")
        (prefix / "new_only.py").write_text("# added by the new release")
        (snapshot / "panel.py").write_text("# working old release")
        restored = self.directory / "restarted"
        # The panel answers only after the old version was put back and restarted.
        stubs = (self.HELPERS + 'sleep() { :; }\n'
                 f'as_user() {{ touch "{restored}"; }}\n'
                 f'curl() {{ [ -e "{restored}" ] && grep -q "working old" "{prefix}/panel.py"; }}\n')
        source = stubs + block("install.sh", "panel_answers() {", "\nfi\n")
        result = self.bash(source, {"PREFIX": str(prefix), "ROLLBACK": str(snapshot), "NEW_VERSION": "9.9.9",
                                    "BIND_HOST": "127.0.0.1", "PANEL_PORT": "8790", "DEV_USER": "dev"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("previous version was restored", result.stderr)
        self.assertEqual(sorted(p.name for p in prefix.iterdir()), ["panel.py"])
        self.assertEqual((prefix / "panel.py").read_text(), "# working old release")


class TerminalCommandTests(unittest.TestCase):
    def test_ttyd_options_end_before_the_tmux_command(self):
        # The static ttyd build (Ubuntu 22.04, Debian, Docker) reads a trailing "-t" as its own option and crashes.
        for path in ("systemd/cc-ttyd.service", "docker/entrypoint.sh"):
            with self.subTest(path=path):
                self.assertIn("-- tmux attach -t", (ROOT / path).read_text())
        self.assertIn("'--', tmux, '-L', 'agent-deck', 'attach', '-t'", (ROOT / "macos/install.py").read_text())
