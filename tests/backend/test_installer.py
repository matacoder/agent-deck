"""Run the real bootstrap trust guard, never the full installer."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from support import ROOT


def guard(script):
    text = (ROOT / script).read_text()
    begin = text.index("require_root_checkout() {")
    end = text.index("\n}", begin) + 2
    return text[begin:end]


class InstallerGuardTests(unittest.TestCase):
    def test_all_bootstrap_entrypoints_reject_the_development_checkout(self):
        # The workspace is dev-owned on the host or group-writable in the rootless test container.
        for script in ("get.sh", "install.sh", "update.sh"):
            with self.subTest(script=script):
                result = subprocess.run(["bash", "-c", guard(script) + '\nrequire_root_checkout "$1"', "guard-test", str(ROOT)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Refusing untrusted root checkout", result.stderr)


def block(script, begin, end):
    text = (ROOT / script).read_text()
    start = text.index(begin)
    return text[start:text.index(end, start) + len(end)]


class InstallerScriptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def bash(self, source, env=None):
        return subprocess.run(["bash", "-c", "set -euo pipefail\n" + source], capture_output=True, text=True,
                              env={**os.environ, **(env or {})})

    def test_truncated_get_sh_defines_functions_only(self):
        lines = (ROOT / "get.sh").read_text().rstrip("\n").splitlines()
        self.assertEqual(lines[-1], 'main "$@"')
        result = subprocess.run(["bash", "-c", "\n".join(lines[:-1])], capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_tailscale_auth_key_is_never_passed_in_argv(self):
        text = (ROOT / "install.sh").read_text()
        self.assertNotIn('--authkey "$TS_AUTHKEY"', text)
        self.assertIn('tailscale up --auth-key="file:$key_file"', text)

    def test_install_options_are_written_atomically(self):
        conf = self.directory / "etc/install.conf"
        source = block("install.sh", "write_conf() {", "\n}\n") + "write_conf"
        result = self.bash(source, {"CONF": str(conf), "CONF_KEYS": "DEV_USER PANEL_PORT", "DEV_USER": "alice", "PANEL_PORT": "8791"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(conf.read_text(), "DEV_USER=alice\nPANEL_PORT=8791\n")
        self.assertEqual(conf.stat().st_mode & 0o777, 0o644)
        self.assertEqual(sorted(path.name for path in conf.parent.iterdir()), ["install.conf"])

    def test_installer_refuses_silent_downgrade(self):
        source = block("install.sh", "NEW_VERSION=$(cat", "\nfi\n")
        prefix, checkout = self.directory / "prefix", self.directory / "src/panel"
        prefix.mkdir()
        checkout.mkdir(parents=True)
        helpers = "die() { echo \"$*\" >&2; exit 1; }\n"
        for installed, new, force, refused in (("0.10.0", "0.9.0", "", True), ("0.10.0", "0.9.0", "1", False),
                                               ("0.9.0", "0.10.0", "", False), ("0.9.0", "0.9.0", "", False)):
            with self.subTest(installed=installed, new=new, force=force):
                (prefix / "VERSION").write_text(installed + "\n")
                (checkout / "VERSION").write_text(new + "\n")
                result = self.bash(helpers + source, {"PREFIX": str(prefix), "SRC": str(checkout.parent), "FORCE_DOWNGRADE": force})
                self.assertEqual(result.returncode != 0, refused, result.stderr)
                if refused:
                    self.assertIn("FORCE_DOWNGRADE=1", result.stderr)


@unittest.skipUnless(os.geteuid() == 0, "run in the disposable rootless container for root ownership tests")
class RootOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="agent-deck-guard-", dir="/opt"))
        import shutil
        self.addCleanup(shutil.rmtree, self.directory)
        self.source = guard("get.sh")

    def check(self):
        return subprocess.run(["bash", "-c", self.source + '\nrequire_root_checkout "$1"', "guard-test", str(self.directory)], capture_output=True, text=True)

    def test_root_owned_protected_checkout_is_accepted(self):
        (self.directory / "install.sh").write_text("# trusted code")
        self.assertEqual(self.check().returncode, 0)

    def test_user_owned_file_writable_file_and_symlink_are_rejected(self):
        path = self.directory / "install.sh"
        path.write_text("# code")
        path.chmod(0o666)
        self.assertNotEqual(self.check().returncode, 0)
        path.chmod(0o644)
        os.chown(path, 1000, 1000)
        self.assertNotEqual(self.check().returncode, 0)
        path.unlink()
        path.symlink_to("/etc/passwd")
        self.assertNotEqual(self.check().returncode, 0)

    def test_unprivileged_user_file_writes_cannot_follow_symlink_into_root_file(self):
        import re
        import shutil
        if not shutil.which("runuser"):
            self.skipTest("runuser is required for the privilege boundary test")
        self.directory.chmod(0o755)
        protected = self.directory / "root-file"
        protected.write_text("protected")
        protected.chmod(0o600)
        link = self.directory / "env"
        link.symlink_to(protected)
        binary = self.directory / "bin"
        binary.mkdir()
        sudo = binary / "sudo"
        sudo.write_text('#!/bin/sh\ntask_user=$2; shift 2; shift\nexec runuser -u "$task_user" -- "$@"\n')
        sudo.chmod(0o755)
        helper = re.search(r"^as_user\(\) \{.*\}$", (ROOT / "install.sh").read_text(), re.M).group()
        env = {**os.environ, "PATH": str(binary) + ":" + os.environ["PATH"]}
        for operation in ('printf injected | as_user tee "$1"', 'as_user chmod 666 "$1"'):
            result = subprocess.run(["bash", "-c", 'DEV_USER=nobody; UID_=65534\n' + helper + '\n' + operation,
                                     "user-file-test", str(link)], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(protected.read_text(), "protected")
            self.assertEqual(protected.stat().st_mode & 0o777, 0o600)


class CodexInstallTests(unittest.TestCase):
    def test_codex_is_installed_without_its_start_now_question_everywhere(self):
        # The question waits for a key and stopped the Windows (WSL) installation halfway.
        for name in ('install.sh', 'panel/panel.py', 'docker/entrypoint.sh'):
            text = (ROOT / name).read_text()
            calls = [line for line in text.splitlines() if 'codex/install.sh' in line]
            self.assertTrue(calls, name)
            for line in calls:
                self.assertIn('CODEX_NON_INTERACTIVE=1 sh', line, name)
