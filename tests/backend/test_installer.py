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
