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


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.target = self.directory / "runtime"
        self.target.mkdir()
        self.state = self.directory / "state.json"
        self.stage = self.target / ".stage"
        self.stage.mkdir()

    def archive(self, extra=None, version="0.2.0"):
        files = {name: (version if name == "VERSION" else "# release file").encode() for name in updater.REQUIRED}
        files.update(extra or {})
        result = io.BytesIO()
        with tarfile.open(fileobj=result, mode="w:gz") as archive:
            for name, content in files.items():
                info = tarfile.TarInfo("repo-release/panel/" + name)
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

    def test_download_failure_does_not_stop_the_running_panel(self):
        with patch.object(updater, "available", return_value=True), patch.object(updater, "fetch", side_effect=OSError("offline")), patch.object(updater, "service") as service:
            updater.run("matacoder/agent-deck", self.target, self.state, "http://127.0.0.1:8790")
        service.assert_not_called()
        self.assertEqual(updater.status(self.state)["phase"], "error")
        self.assertEqual(updater.status(self.state)["message"], "offline")

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
