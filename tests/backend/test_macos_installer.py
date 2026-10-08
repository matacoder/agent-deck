import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from support import ROOT

FAKE = {
    'uname': 'echo Darwin',
    'id': '[ "$1" = -u ] && echo 501 || echo tata',
    'stat': 'echo admin',
    'brew': 'echo "brew $*" >> "$LOG"; case "$1" in --prefix) echo "$PREFIX";; --repository) echo "$REPO";; esac; exit 0',
    'python3': 'echo "python3 $*" >> "$LOG"; exit 0',
}


class MacInstallerTests(unittest.TestCase):
    """install-macos.sh with stand-ins for macOS tools: which Homebrew commands it would run."""

    def run_installer(self, present, writable=True, intel=False):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        bin_dir, prefix, home, log = root / 'bin', root / 'homebrew', root / 'home', root / 'log'
        for path in (bin_dir, prefix / 'bin', home):
            path.mkdir(parents=True)
        tools = dict(FAKE, **{name: 'exit 0' for name in present})
        for name, body in tools.items():
            target = (prefix / 'bin' / name) if name == 'python3' else bin_dir / name
            target.write_text('#!/bin/bash\n' + body + '\n')
            target.chmod(0o755)
        # Only these system commands are reachable, so tools installed on the test machine do not leak in.
        for name in ('dirname', 'mkdir', 'rm', 'cat'):
            (bin_dir / name).symlink_to(subprocess.run(['which', name], capture_output=True, text=True).stdout.strip())
        if not writable:
            prefix.chmod(0o555)
            self.addCleanup(prefix.chmod, 0o755)
        repo = prefix / 'Homebrew' if intel else prefix
        repo.mkdir(exist_ok=True)
        if intel:
            prefix.chmod(0o555)  # /usr/local stays root-owned on Intel Macs even for Homebrew's own account.
            self.addCleanup(prefix.chmod, 0o755)
        env = {'PATH': str(bin_dir), 'HOME': str(home), 'LOG': str(log), 'PREFIX': str(prefix), 'REPO': str(repo)}
        result = subprocess.run([subprocess.run(['which', 'bash'], capture_output=True, text=True).stdout.strip(), str(ROOT / 'install-macos.sh')], env=env, capture_output=True, text=True,
                                input='', timeout=30)
        calls = log.read_text().splitlines() if log.exists() else []
        return result, [c for c in calls if c.startswith('brew install')]

    def test_tools_already_installed_are_used_as_they_are(self):
        result, installs = self.run_installer({'tmux', 'ttyd', 'gh', 'claude', 'codex'})
        self.assertEqual(installs, [], result.stderr)

    def test_only_missing_tools_are_installed(self):
        result, installs = self.run_installer({'tmux', 'gh', 'claude'})
        self.assertEqual(installs, ['brew install ttyd', 'brew install --cask codex'], result.stderr)

    def test_homebrew_of_another_account_stops_with_what_to_do(self):
        if os.geteuid() == 0:
            self.skipTest('root can write anywhere')
        result, installs = self.run_installer({'tmux', 'gh', 'claude', 'codex'}, writable=False)
        self.assertEqual((result.returncode, installs), (1, []))
        self.assertIn('belongs to "admin"', result.stderr)
        self.assertIn('brew install ttyd', result.stderr)
        self.assertIn('sudo chown -R "tata"', result.stderr)

    def test_an_intel_mac_with_a_root_owned_usr_local_still_installs(self):
        result, installs = self.run_installer({'tmux', 'gh', 'claude', 'codex'}, intel=True)
        self.assertEqual(installs, ['brew install ttyd'], result.stderr)


if __name__ == '__main__':
    unittest.main()
