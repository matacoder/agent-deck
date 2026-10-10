"""Recovery paths of install.sh (stale Tailscale address, rollback of a release that does not start).

Runs only extracted blocks with stubbed commands: never the installer itself, never as root.
"""
import os
import sys
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

    def test_a_remembered_tailscale_address_that_left_this_machine_is_resolved_again(self):
        source = self.HELPERS + block("install.sh", "bind_is_local() {", '    BIND_HOST=\nfi\n') + 'echo "host=$BIND_HOST"'
        for host, explicit, expected in (("127.0.0.1", "", "host=127.0.0.1"), ("100.64.250.250", "", "host="),
                                         ("127.0.0.1", "1", "host=127.0.0.1")):
            with self.subTest(host=host, explicit=explicit):
                result = self.bash(source, {"BIND_HOST": host, "BIND_HOST_EXPLICIT": explicit})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, result.stdout.splitlines())
        for host, explicit, message in (("203.0.113.9", "", "rerun with BIND_HOST"), ("203.0.113.9", "1", "not an address")):
            with self.subTest(host=host, explicit=explicit):
                refused = self.bash(source, {"BIND_HOST": host, "BIND_HOST_EXPLICIT": explicit})
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn(message, refused.stderr)

    def recovery_source(self, restarted, prefix):
        # as_user runs the command (as this test user) and records restarts; curl answers only for the old code.
        stubs = (self.HELPERS + 'sleep() { :; }\n'
                 f'as_user() {{ if [ "$1" = systemctl ]; then touch "{restarted}"; elif [ "$1" = sed ]; then echo 127.0.0.1; else "$@"; fi; }}\n'
                 f'curl() {{ [ -e "{restarted}" ] && grep -q "working old" "{prefix}/panel.py"; }}\n')
        return stubs + block("install.sh", 'ROLLBACK="" PANEL_COPIED=0', "\nPANEL_COPIED=1\n")

    def test_a_new_panel_that_does_not_answer_is_rolled_back_by_the_panel_user(self):
        prefix, restarted = self.directory / "prefix", self.directory / "restarted"
        prefix.mkdir()
        (prefix / "panel.py").write_text("# working old release")
        copy = 'cp -r "$PREFIX/." "$PREFIX.new"; rm -rf "$PREFIX"/*; echo "# broken new release" > "$PREFIX/panel.py"; touch "$PREFIX/new_only.py"\n'
        health = block("install.sh", "# Probe where the panel really listens", "\nPANEL_HEALTHY=1\n")
        source = self.recovery_source(restarted, prefix) + copy + health
        result = self.bash(source, {"PREFIX": str(prefix), "NEW_VERSION": "9.9.9", "ENV": "/dev/null", "DEV_USER": "dev"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("previous version was restored", result.stderr)
        self.assertEqual(sorted(p.name for p in prefix.iterdir()), ["panel.py"])
        self.assertEqual((prefix / "panel.py").read_text(), "# working old release")

    def test_a_failure_after_the_copy_puts_the_previous_files_back(self):
        prefix, restarted = self.directory / "prefix", self.directory / "restarted"
        prefix.mkdir()
        (prefix / "panel.py").write_text("# working old release")
        source = self.recovery_source(restarted, prefix) + 'echo "# half new" > "$PREFIX/panel.py"\nfalse\n'
        result = self.bash(source, {"PREFIX": str(prefix), "DEV_USER": "dev"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("previous panel files were put back", result.stderr)
        self.assertEqual((prefix / "panel.py").read_text(), "# working old release")


class TerminalCommandTests(unittest.TestCase):
    def test_ttyd_options_end_before_the_tmux_command(self):
        # The static ttyd build (Ubuntu 22.04, Debian, Docker) reads a trailing "-t" as its own option and crashes.
        for path in ("systemd/cc-ttyd.service", "docker/entrypoint.sh"):
            with self.subTest(path=path):
                self.assertIn("-- tmux attach -t", (ROOT / path).read_text())
        self.assertIn("'--', tmux, '-L', 'agent-deck', 'attach', '-t'", (ROOT / "macos/install.py").read_text())


class TtydPinTests(unittest.TestCase):
    def test_the_installer_and_the_image_pin_the_same_ttyd(self):
        # Two copies of the version and hashes: a bump in one file only would fail every fresh root install.
        import re
        script, image = (ROOT / 'install.sh').read_text(), (ROOT / 'docker/Dockerfile').read_text()
        self.assertEqual(re.search(r'^TTYD_VERSION=(\S+)$', script, re.M).group(1),
                         re.search(r'^ARG TTYD_VERSION=(\S+)$', image, re.M).group(1))
        for arch in ('x86_64', 'aarch64'):
            with self.subTest(arch=arch):
                pinned = re.search(rf'arch={arch} sum=([0-9a-f]{{64}}) ', script).group(1)
                self.assertEqual(pinned, re.search(rf'^ARG TTYD_SHA256_{arch.upper()}=([0-9a-f]{{64}})$', image, re.M).group(1))


class ContainerTrustTests(unittest.TestCase):
    def test_a_container_does_not_trust_forwarded_addresses_from_its_gateway(self):
        code = ("import sys; sys.path.insert(0, 'panel'); sys.argv=['panel']; import panel; "
                "print(len(panel.TRUSTED_PROXIES))")
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".config/cc-panel"), mode=0o700)
            env = {**os.environ, "HOME": home, "PANEL_PASSWORD": "x", "BIND_HOST": "127.0.0.1"}
            for extra, expected in (({}, "4"), ({"AGENT_DECK_CONTAINER": "1"}, "0"),
                                    ({"AGENT_DECK_CONTAINER": "1", "AGENT_DECK_TRUSTED_PROXIES": "10.0.0.0/8"}, "1")):
                with self.subTest(extra=extra):
                    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env={**env, **extra},
                                            capture_output=True, text=True, timeout=60)
                    self.assertEqual(result.stdout.strip().splitlines()[-1:], [expected], result.stderr[-500:])
