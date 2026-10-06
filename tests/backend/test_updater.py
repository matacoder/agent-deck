import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from support import ROOT, PanelCase

spec = importlib.util.spec_from_file_location("test_updater_module", ROOT / "panel/updater.py")
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class ImportCheckTests(unittest.TestCase):
    def test_a_release_module_that_fails_to_import_is_rejected_before_the_service_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            (stage / "integrations").mkdir()
            (stage / "integrations/__init__.py").write_text("")
            (stage / "integrations/good.py").write_text("from . import helper\n")
            (stage / "integrations/helper.py").write_text("VALUE = 1\n")
            names = {"integrations/__init__.py", "integrations/good.py", "integrations/helper.py"}
            updater.check_imports(stage, names)
            (stage / "integrations/bad.py").write_text("from .helper import MISSING\n")
            with self.assertRaisesRegex(ValueError, "MISSING"):
                updater.check_imports(stage, names | {"integrations/bad.py"})


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.target = self.directory / "runtime"
        self.target.mkdir()
        self.state = self.directory / "state.json"
        self.stage = self.target / ".stage"
        self.stage.mkdir()

    def archive(self, extra=None, version="0.2.0"):
        files = {name: (version if name == "VERSION" else "# release file").encode() for name in updater.REQUIRED}
        for name in updater.LOCALES:
            files[name] = (ROOT/name).read_bytes()
        files.update(extra or {})
        result = io.BytesIO()
        with tarfile.open(fileobj=result, mode="w:gz") as archive:
            for name, content in files.items():
                info = tarfile.TarInfo("repo-release/" + (name if name.startswith(('integrations/', 'locales/')) else 'panel/' + name))
                if content is None:
                    info.type = tarfile.SYMTYPE
                    info.linkname = "/tmp/escape"
                    archive.addfile(info)
                else:
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))
        return result.getvalue()

    def test_rejects_root_development_checkout_symlink_and_invalid_repository(self):
        with patch.object(updater.os, "geteuid", return_value=1000):
            self.assertTrue(updater.available(self.target, "matacoder/agent-deck"))
            self.assertFalse(updater.available(self.target, "../other"))
            (self.directory / ".git").mkdir()
            self.assertFalse(updater.available(self.target, "matacoder/agent-deck"))
        with patch.object(updater.os, "geteuid", return_value=0):
            self.assertFalse(updater.available(self.target, "matacoder/agent-deck"))
        link = self.directory / "link"
        link.symlink_to(self.target)
        self.assertFalse(updater.available(link, "matacoder/agent-deck"))

    def test_lock_prevents_duplicate_jobs_and_detects_interrupted_job(self):
        updater.write_state(self.state, "downloading", version="0.2.0")
        fd = updater.lock(self.state)
        try:
            self.assertIsNone(updater.lock(self.state))
            self.assertEqual(updater.status(self.state)["phase"], "downloading")
        finally:
            os.close(fd)
        self.assertEqual(updater.status(self.state)["phase"], "error")
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)

    def test_archive_validates_paths_symlinks_size_version_and_python_before_install(self):
        self.assertEqual(updater.unpack(self.archive(), self.stage, "0.2.0"), updater.REQUIRED)
        for extra in ({"../escape": b"bad"}, {"index.html": None}, {"panel.py": b"not valid python !"}):
            with self.subTest(extra=list(extra)), self.assertRaises((ValueError, SyntaxError)):
                updater.unpack(self.archive(extra), self.stage, "0.2.0")
        with self.assertRaises(ValueError):
            updater.unpack(self.archive(version="0.1.0"), self.stage, "0.2.0")
        info = tarfile.TarInfo("repo/panel/index.html")
        info.size = 16 * 1024 * 1024 + 1
        with patch.object(updater.tarfile, "open") as archive:
            archive.return_value.__enter__.return_value = [info]
            with self.assertRaises(ValueError):
                updater.unpack(b"", self.stage, "0.2.0")
        self.assertFalse((self.target / "escape").exists())

    def test_additional_locales_are_validated_without_executing_downloaded_code(self):
        spanish = json.dumps({'name':'Español','messages':{'Value {0}':'Valor {0}'}}).encode()
        names = updater.unpack(self.archive({'locales/es.json':spanish}), self.stage, '0.2.0')
        self.assertIn('locales/es.json', names)
        for payload in (b'not JSON', b'{"name":"Test","messages":{"Value {0}":"Value {1}"}}'):
            with self.assertRaises(ValueError):
                updater.unpack(self.archive({'locales/es.json':payload}), self.stage, '0.2.0')
        with self.assertRaises(ValueError):
            updater.unpack(self.archive({'locales/../escape.json':spanish}), self.stage, '0.2.0')

    def test_success_installs_files_and_only_restarts_panel(self):
        names = updater.unpack(self.archive(), self.stage, "0.2.0")
        (self.target / "VERSION").write_text("0.1.0")
        with patch.object(updater, "service") as service, patch.object(updater, "healthy") as healthy:
            updater.install(self.stage, self.target, names, self.state, "0.2.0", "http://127.0.0.1:8790")
        self.assertEqual([call.args for call in service.call_args_list], [("stop",), ("start",)])
        healthy.assert_called_once_with("http://127.0.0.1:8790")
        self.assertEqual((self.target / "VERSION").read_text(), "0.2.0")

    def test_failed_health_check_restores_previous_files_and_removes_new_files(self):
        names = updater.unpack(self.archive(), self.stage, "0.2.0")
        old_files = {"VERSION": "0.1.0", "panel.py": "# old backend", "index.html": "old UI"}
        for name, text in old_files.items():
            (self.target / name).write_text(text)
        with patch.object(updater, "service") as service, patch.object(updater, "healthy", side_effect=RuntimeError("bad release")):
            with self.assertRaisesRegex(RuntimeError, "bad release"):
                updater.install(self.stage, self.target, names, self.state, "0.2.0", "http://127.0.0.1:8790")
        for name, text in old_files.items():
            self.assertEqual((self.target / name).read_text(), text)
        self.assertFalse((self.target / "updater.py").exists())
        self.assertEqual([call.args for call in service.call_args_list], [("stop",), ("start",), ("stop",), ("start",)])

    def test_rollback_restores_files_and_starts_panel_when_stop_fails(self):
        names = updater.unpack(self.archive(), self.stage, "0.2.0")
        old_files = {"VERSION": "0.1.0", "panel.py": "# old backend"}
        for name, text in old_files.items():
            (self.target / name).write_text(text)
        calls = []

        def service(action):
            calls.append(action)
            if calls == ["stop", "start", "stop"]:
                raise updater.subprocess.TimeoutExpired("systemctl", 30)

        with patch.object(updater, "service", side_effect=service), patch.object(updater, "healthy", side_effect=RuntimeError("bad release")):
            with self.assertRaisesRegex(RuntimeError, "bad release"):
                updater.install(self.stage, self.target, names, self.state, "0.2.0", "http://127.0.0.1:8790")
        for name, text in old_files.items():
            self.assertEqual((self.target / name).read_text(), text)
        self.assertFalse((self.target / "updater.py").exists())
        self.assertEqual(calls, ["stop", "start", "stop", "start"])

    def test_version_file_is_replaced_last(self):
        names = updater.unpack(self.archive(), self.stage, "0.2.0")
        replaced = []
        original = updater.os.replace

        def replace(source, destination):
            if Path(destination).parent != self.state.parent:
                replaced.append(Path(destination).relative_to(self.target).as_posix())
            original(source, destination)

        with patch.object(updater, "service"), patch.object(updater, "healthy"), patch.object(updater.os, "replace", side_effect=replace):
            updater.install(self.stage, self.target, names, self.state, "0.2.0", "http://127.0.0.1:8790")
        installed = [name for name in replaced if name in names]
        self.assertEqual(installed[-1], "VERSION")
        self.assertEqual(sorted(installed), sorted(names))

    def test_run_removes_stale_staging_directories_only(self):
        (self.target / "VERSION").write_text("0.2.0")
        stale = self.target / ".update-crashed"
        (stale / "backup").mkdir(parents=True)
        (stale / "panel.py").write_text("# partial")
        outside = self.directory / "outside"
        outside.mkdir()
        (outside / "keep").write_text("keep")
        (self.target / ".update-link").symlink_to(outside)
        (self.target / ".update-file").write_text("not a directory")
        with patch.object(updater, "available", return_value=True), patch.object(updater, "fetch", return_value=b'{"tag_name":"v0.1.0"}'):
            updater.run("matacoder/agent-deck", self.target, self.state, "http://127.0.0.1:8790")
        self.assertFalse(stale.exists())
        self.assertTrue((self.target / ".update-link").is_symlink())
        self.assertTrue((outside / "keep").exists())
        self.assertTrue((self.target / ".update-file").exists())
        self.assertTrue(self.stage.exists())

    def test_every_tracked_panel_file_is_allowed_in_releases(self):
        # A panel file outside the allow-list would make every one-click update reject the release.
        try:
            listed = updater.subprocess.run(["git", "-C", str(ROOT), "ls-files", "panel"], capture_output=True, text=True, check=True).stdout.split()
            files = [name[len("panel/"):] for name in listed]
        except (OSError, updater.subprocess.CalledProcessError):
            files = []
        if not files:
            files = [path.name for path in (ROOT / "panel").iterdir() if path.is_file()]
        self.assertTrue(files)
        self.assertEqual(sorted(set(files) - updater.ALLOWED), [])

    def test_download_failure_does_not_stop_the_running_panel(self):
        with patch.object(updater, "available", return_value=True), patch.object(updater, "fetch", side_effect=OSError("offline")), patch.object(updater, "service") as service:
            updater.run("matacoder/agent-deck", self.target, self.state, "http://127.0.0.1:8790")
        service.assert_not_called()
        self.assertEqual(updater.status(self.state)["phase"], "error")
        self.assertEqual(updater.status(self.state)["message"], "offline")

    def test_a_failed_install_records_which_release_failed(self):
        (self.target / "VERSION").write_text("0.1.0")
        answers = iter([b'{"tag_name":"v0.2.0"}', OSError("tarball unavailable")])
        def fetch(*args):
            answer = next(answers)
            if isinstance(answer, Exception):
                raise answer
            return answer
        with patch.object(updater, "available", return_value=True), patch.object(updater, "fetch", side_effect=fetch):
            updater.run("matacoder/agent-deck", self.target, self.state, "http://127.0.0.1:8790")
        self.assertEqual({k: updater.status(self.state)[k] for k in ("phase", "version")}, {"phase": "error", "version": "0.2.0"})

    def test_existing_or_older_release_never_downgrades(self):
        (self.target / "VERSION").write_text("0.2.0")
        with patch.object(updater, "available", return_value=True), patch.object(updater, "fetch", return_value=b'{"tag_name":"v0.1.0"}') as fetch, patch.object(updater, "service") as service:
            updater.run("matacoder/agent-deck", self.target, self.state, "http://127.0.0.1:8790")
        fetch.assert_called_once()
        service.assert_not_called()
        self.assertEqual(updater.status(self.state)["phase"], "done")

    def test_complete_job_downloads_only_pinned_repository_and_reports_success(self):
        (self.target / "VERSION").write_text("0.1.0")
        release = json.dumps({"tag_name": "v0.2.0", "tarball_url": "https://ignored.example/malicious"}).encode()
        with patch.object(updater, "available", return_value=True), patch.object(updater, "fetch", side_effect=[release, self.archive()]) as fetch, patch.object(updater, "service"), patch.object(updater, "healthy"):
            updater.run("matacoder/agent-deck", self.target, self.state, "http://127.0.0.1:8790")
        self.assertEqual([call.args[0] for call in fetch.call_args_list], [
            "https://api.github.com/repos/matacoder/agent-deck/releases/latest",
            "https://api.github.com/repos/matacoder/agent-deck/tarball/v0.2.0",
        ])
        self.assertEqual(updater.status(self.state)["phase"], "done")
        self.assertEqual((self.target / "VERSION").read_text(), "0.2.0")

    def test_same_version_repairs_packages_missing_after_legacy_update(self):
        (self.target/'VERSION').write_text('0.2.0')
        release=json.dumps({'tag_name':'v0.2.0'}).encode()
        with patch.object(updater,'available',return_value=True),patch.object(updater,'fetch',side_effect=[release,self.archive()]),patch.object(updater,'service'),patch.object(updater,'healthy'):
            updater.run('matacoder/agent-deck',self.target,self.state,'http://127.0.0.1:8790')
        self.assertTrue(all((self.target/name).is_file() for name in updater.REQUIRED))
        self.assertEqual(updater.status(self.state)['phase'],'done')

    def test_symlink_package_directory_is_rejected_before_service_stop(self):
        names=updater.unpack(self.archive(),self.stage,'0.2.0')
        (self.target/'integrations').symlink_to(self.directory,target_is_directory=True)
        with patch.object(updater,'service') as service,self.assertRaises(ValueError):
            updater.install(self.stage,self.target,names,self.state,'0.2.0','http://127.0.0.1:8790')
        service.assert_not_called()


class UpdateActionTests(PanelCase):
    def test_spawns_fixed_detached_helper_without_forwarding_password(self):
        self.panel.UPDATE_REPO = "matacoder/agent-deck"
        with patch.object(self.panel.updater, "available", return_value=True), patch.object(self.panel.subprocess, "Popen") as start:
            result = self.panel.action_update({"command": "ignored", "version": "ignored"})
        args, kwargs = start.call_args
        self.assertEqual(result["job"]["phase"], "checking")
        self.assertIn("--repo", args[0])
        self.assertNotIn("ignored", args[0])
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(len(kwargs["pass_fds"]), 1)
        self.assertNotIn("PANEL_PASSWORD", kwargs["env"])

    def test_existing_job_does_not_start_another_process(self):
        updater.write_state(self.panel.UPDATE_STATE, "downloading")
        fd = updater.lock(self.panel.UPDATE_STATE)
        try:
            with patch.object(self.panel.updater, "available", return_value=True), patch.object(self.panel.subprocess, "Popen") as start:
                self.assertEqual(self.panel.action_update({})["job"]["phase"], "downloading")
            start.assert_not_called()
        finally:
            os.close(fd)

    def test_development_checkout_cannot_update_itself(self):
        self.panel.UPDATE_REPO = "matacoder/agent-deck"
        with self.assertRaises(ValueError):
            self.panel.action_update({})


class PackageListTests(unittest.TestCase):
    def test_updates_ship_every_integration_module(self):
        # Installers copy integrations/*.py; the updater must not silently drop a new module.
        shipped = {"integrations/" + path.name for path in (ROOT / "integrations").glob("*.py")}
        self.assertEqual(updater.PACKAGES, shipped)

    def test_panel_directory_only_holds_files_installed_updaters_accept(self):
        # Updaters already running on users' machines reject unknown panel/ files and would stop
        # updating; new code must live in integrations/*.py (accepted by every release since 0.7).
        files = {path.name for path in (ROOT / "panel").iterdir() if path.is_file() and path.suffix != ".pyc"}
        self.assertLessEqual(files, {name for name in updater.ALLOWED if "/" not in name})
