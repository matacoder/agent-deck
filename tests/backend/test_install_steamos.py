"""install-steamos.sh: the generated user service and its input checks, without Podman or systemd."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from support import ROOT

SCRIPT = ROOT / "install-steamos.sh"


def run(env, command='render_unit'):
    with tempfile.TemporaryDirectory() as directory:
        stub = Path(directory) / "podman"
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
        full = {**os.environ, "PATH": f"{directory}:{os.environ['PATH']}", "HOME": directory,
                "AGENT_DECK_SOURCE_ONLY": "1", **env}
        return subprocess.run(["bash", "-c", f'. "$0"; {command}', str(SCRIPT)], capture_output=True, text=True, env=full)


@unittest.skipUnless(os.uname().machine == "x86_64", "SteamOS installer targets x86_64")
class SteamOSInstallerTests(unittest.TestCase):
    def test_default_service_is_local_only_and_keeps_data_in_the_home_volume(self):
        result = run({})
        self.assertEqual(result.returncode, 0, result.stderr)
        start = next(line for line in result.stdout.splitlines() if line.startswith("ExecStart="))
        self.assertIn("-p 127.0.0.1:8790:8790", start)
        self.assertIn("-v agent-deck-home:/home/dev", start)
        self.assertIn("--userns=keep-id:uid=1000,gid=1000", start)
        self.assertIn("AGENT_DECK_UPDATE_COMMAND=" + str(ROOT / "install-steamos.sh"), start)
        self.assertIn("Restart=always", result.stdout)

    def test_projects_folder_and_network_binding_are_opt_in(self):
        with tempfile.TemporaryDirectory() as projects:
            result = run({"AGENT_DECK_BIND": "0.0.0.0", "AGENT_DECK_PROJECTS": projects})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-p 0.0.0.0:8790:8790", result.stdout)
        self.assertIn(f"-v {Path(projects).resolve()}:/home/dev/dev", result.stdout)

    def test_values_that_would_break_the_unit_are_refused(self):
        for env in ({"AGENT_DECK_BIND": "0.0.0.0 --privileged"}, {"AGENT_DECK_PORT": "80"},
                    {"AGENT_DECK_PROJECTS": "/no/such/folder"}):
            with self.subTest(env=env):
                result = run(env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("xx", result.stderr)
