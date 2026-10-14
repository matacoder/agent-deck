"""install-steamos.sh: the generated user service and its input checks, without Podman or systemd."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from support import ROOT

SCRIPT = ROOT / "install-steamos.sh"


def run(env, command='render_unit', stubs=None, directory=None):
    if directory is None:
        with tempfile.TemporaryDirectory() as directory:
            return run(env, command, stubs, directory)
    for name, body in {"podman": "exit 0", **(stubs or {})}.items():
        stub = Path(directory) / name
        stub.write_text("#!/bin/sh\n" + body + "\n")
        stub.chmod(0o755)
    full = {**os.environ, "PATH": f"{directory}:{os.environ['PATH']}", "HOME": directory,
            "AGENT_DECK_SOURCE_ONLY": "1", "LOG": f"{directory}/log", **env}
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

    def test_settings_update_command_is_the_script_that_updates_itself(self):
        self.assertIn('update_checkout "$@"', SCRIPT.read_text())


FLOW_STUBS = {
    "podman": 'echo "podman $*" >> "$LOG"\nif [ "$1 $2" = "image exists" ]; then [ -n "$HAD_IMAGE" ]; exit $?; fi\n'
              'if [ "$1 $2" = "image inspect" ]; then [ -n "$HAD_IMAGE" ] && echo sha256:older; exit $?; fi\nexit 0',
    "systemctl": 'echo "systemctl $*" >> "$LOG"',
    # The panel answers only after this many restarts of the service.
    "curl": 'n=$(grep -c "systemctl --user restart" "$LOG"); [ "$n" -ge "$ANSWER_AFTER" ]',
    "sleep": "exit 0",
    "git": 'echo "git must not run here" >&2; exit 1',
}


@unittest.skipUnless(os.uname().machine == "x86_64", "SteamOS installer targets x86_64")
class SteamOSUpdateTests(unittest.TestCase):
    def flow(self, had_image, answer_after):
        with tempfile.TemporaryDirectory() as directory:
            result = run({"HAD_IMAGE": "1" if had_image else "", "ANSWER_AFTER": str(answer_after),
                          "AGENT_DECK_NO_PULL": "1"}, "main", FLOW_STUBS, directory)
            log = Path(directory, "log").read_text().splitlines()
        return result, [line for line in log if line.startswith("podman")]

    def test_a_successful_update_keeps_the_previous_image_and_removes_only_its_own_older_one(self):
        result, podman = self.flow(True, 1)
        self.assertEqual(result.returncode, 0, result.stderr)
        tag = podman.index("podman tag localhost/agent-deck:latest localhost/agent-deck:previous")
        build = next(i for i, line in enumerate(podman) if line.startswith("podman build"))
        self.assertLess(tag, build)
        self.assertIn("podman rmi sha256:older", podman)
        self.assertFalse([line for line in podman if "prune" in line or line.startswith("podman rmi -")], podman)
        self.assertNotIn("podman tag localhost/agent-deck:previous localhost/agent-deck:latest", podman)

    def test_an_update_that_does_not_answer_is_rolled_back(self):
        result, podman = self.flow(True, 2)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rolled back", result.stderr)
        self.assertEqual(podman[-1], "podman tag localhost/agent-deck:previous localhost/agent-deck:latest")
        self.assertFalse([line for line in podman if "rmi" in line or "prune" in line], podman)

    def test_a_rolled_back_image_that_does_not_answer_either_is_reported(self):
        result, _ = self.flow(True, 99)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not answer either", result.stderr)

    def test_a_first_install_that_does_not_answer_has_nothing_to_roll_back(self):
        result, podman = self.flow(False, 99)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("the panel did not start", result.stderr)
        self.assertFalse([line for line in podman if line.startswith("podman tag")], podman)


GIT = ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"]


@unittest.skipUnless(os.uname().machine == "x86_64", "SteamOS installer targets x86_64")
class SteamOSCheckoutTests(unittest.TestCase):
    """update_checkout against throwaway repositories; the real checkout is never pulled."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.origin, self.upstream, self.checkout = root / "origin.git", root / "upstream", root / "checkout"
        self.git("init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git("clone", "-q", str(self.origin), str(self.upstream))
        self.commit("first")
        self.git("clone", "-q", str(self.origin), str(self.checkout))

    def git(self, *arguments, cwd=None):
        subprocess.run([*GIT, *arguments], cwd=cwd, check=True, capture_output=True, env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"})

    def commit(self, label):
        # The checkout's own script is a stand-in that says which version was started.
        script = self.upstream / "install-steamos.sh"
        script.write_text(f'#!/bin/sh\necho "started {label} no_pull=$AGENT_DECK_NO_PULL"\n')
        script.chmod(0o755)
        self.git("add", ".", cwd=self.upstream)
        self.git("commit", "-q", "-m", label, cwd=self.upstream)
        self.git("push", "-q", "origin", "HEAD:main", cwd=self.upstream)

    def update(self, env=None):
        return run({"GIT_CONFIG_NOSYSTEM": "1", **(env or {})}, f'SRC="{self.checkout}"; update_checkout; echo "kept running"')

    def test_an_up_to_date_checkout_goes_on_without_restarting(self):
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("kept running", result.stdout)

    def test_a_pulled_change_runs_the_new_script_once(self):
        self.commit("second")
        result = self.update()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("started second no_pull=1", result.stdout)
        self.assertNotIn("kept running", result.stdout)

    def test_local_changes_stop_the_update_with_what_to_do(self):
        self.commit("second")
        (self.checkout / "install-steamos.sh").write_text("#!/bin/sh\necho local edit\n")
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("has local changes", result.stderr)
        self.assertIn("AGENT_DECK_NO_PULL=1", result.stderr)

    def test_a_diverged_branch_stops_the_update(self):
        self.commit("second")
        (self.checkout / "other").write_text("local commit\n")
        self.git("add", ".", cwd=self.checkout)
        self.git("commit", "-q", "-m", "local", cwd=self.checkout)
        result = self.update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("git pull --ff-only failed", result.stderr)

    def test_no_pull_builds_the_checkout_as_it_is(self):
        self.commit("second")
        result = self.update({"AGENT_DECK_NO_PULL": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("kept running", result.stdout)
