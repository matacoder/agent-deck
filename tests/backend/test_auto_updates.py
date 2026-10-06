import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from integrations.updates import AutoUpdates
from test_updater import updater
from support import PanelCase


class AutoUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.now=1000
        self.info=Mock(return_value={'update':True,'can_update':True})
        self.start=Mock(return_value={'job':{'phase':'checking'}})
        self.available=Mock(return_value=True)
        self.idle=Mock(return_value=True)
        self.worker=AutoUpdates(self.root,self.info,self.start,self.available,self.idle,lambda:self.now)

    def test_enabled_by_default_checks_and_starts_once_then_throttles(self):
        self.worker.tick();self.worker.tick()
        self.info.assert_called_once();self.start.assert_called_once()
        self.now+=1801;self.worker.tick()
        self.assertEqual(self.info.call_count,2)

    def test_a_release_that_failed_here_is_not_retried_automatically(self):
        # Every attempt stops the panel: a failing release must not take it down every 15 minutes.
        self.info.return_value={'update':True,'can_update':True,'latest':'2.0.0','job':{'phase':'error','version':'2.0.0'}}
        self.worker.tick()
        self.start.assert_not_called()
        self.assertIn('v2.0.0', self.worker.status()['error'])
        self.info.return_value={'update':True,'can_update':True,'latest':'2.0.1','job':{'phase':'error','version':'2.0.0'}}
        self.now+=1801;self.worker.tick()
        self.start.assert_called_once()  # A newer release is tried again.

    def test_status_does_not_wait_for_the_release_check(self):
        import threading
        started,release=threading.Event(),threading.Event()
        self.info.side_effect=lambda:(started.set(),release.wait(5),{'update':False,'can_update':True})[2]
        worker=threading.Thread(target=self.worker.tick);worker.start()
        self.assertTrue(started.wait(5))
        status=[];reader=threading.Thread(target=lambda:status.append(self.worker.status()));reader.start();reader.join(1)
        self.assertEqual(status[0]['phase'],'checking')
        release.set();worker.join(5)
        self.assertEqual(self.worker.status()['phase'],'idle')

    def test_waits_for_local_generation_then_uses_the_checked_release(self):
        self.idle.return_value=False
        self.worker.tick();self.start.assert_not_called()
        self.assertEqual(self.worker.status()['phase'],'waiting')
        self.now+=60;self.idle.return_value=True;self.worker.tick()
        self.info.assert_called_once();self.start.assert_called_once()

    def test_disabled_setting_is_private_persistent_and_never_checks(self):
        self.worker.save(False);self.worker.tick()
        self.info.assert_not_called()
        restored=AutoUpdates(self.root,self.info,self.start,self.available,self.idle)
        self.assertFalse(restored.status()['enabled'])
        self.assertEqual(self.worker.path.stat().st_mode&0o777,0o600)
        self.worker.save(True);self.worker.tick();self.start.assert_called_once()
        with self.assertRaises(ValueError):self.worker.save('yes')

    def test_checkout_and_current_version_never_install(self):
        self.available.return_value=False;self.worker.tick();self.info.assert_not_called()
        self.available.return_value=True;self.info.return_value={'update':False,'can_update':True}
        self.worker.tick();self.start.assert_not_called()

    def test_failed_check_and_start_are_reported_without_secrets_or_fast_retries(self):
        self.info.side_effect=OSError('secret')
        self.worker.tick();self.assertNotIn('secret',self.worker.status()['error'])
        self.assertEqual(self.worker.status()['phase'],'error')
        self.now+=1801;self.info.side_effect=None;self.start.side_effect=OSError('secret')
        self.worker.tick();self.worker.tick();self.start.assert_called_once()
        self.assertNotIn('secret',self.worker.status()['error'])

    def test_live_request_check_ignores_stale_files_but_waits_for_active_or_malformed(self):
        folder=self.root/'live';folder.mkdir();file=folder/'request.json'
        file.write_text(json.dumps({'updated_at':950}))
        self.assertTrue(updater.local_requests_active(folder,lambda:1000))
        self.assertFalse(updater.local_requests_active(folder,lambda:2000))
        file.write_text('broken');self.assertTrue(updater.local_requests_active(folder,lambda:2000))


class PanelUpdateTests(PanelCase):
    def test_explicit_check_bypasses_a_cached_old_release(self):
        self.panel.UPDATE_REPO='matacoder/agent-deck';self.panel.VERSION='1.0.7'
        self.panel.http_json=Mock(return_value={'tag_name':'v1.2.0','html_url':'https://github.com/matacoder/agent-deck/releases/tag/v1.2.0'})
        self.panel._cache['release']=(self.panel.time.time(),{'latest':'1.0.7','url':'old'})
        self.assertFalse(self.panel.version_info()['update'])
        data=self.panel.ACTIONS['check_update']({})
        self.assertEqual(data['latest'],'1.2.0');self.assertTrue(data['update'])
        self.panel.http_json.assert_called_once()

    def test_auto_update_does_not_race_with_an_active_mutation(self):
        self.panel.actions_in_progress=1
        self.panel.action_update=Mock()
        self.assertFalse(self.panel.auto_update_idle())
        self.assertEqual(self.panel.start_auto_update()['job']['phase'],'waiting')
        self.panel.action_update.assert_not_called()

    def test_auto_update_setting_has_same_action_contract_as_manual_ui(self):
        self.panel.ACTIONS['auto_update']({'enabled':False})
        self.assertFalse(self.panel.version_info()['auto_update']['enabled'])
