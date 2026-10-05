import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from support import PanelCase
from integrations.names import unique_name
from integrations.lmstudio import LMStudio


class NamingTests(PanelCase):
    def test_collision_suffixes_are_bounded_and_retried(self):
        with patch('integrations.names.secrets.randbelow', side_effect=[1, 2]):
            self.assertEqual(unique_name('x' * 32, lambda name: name in ('x' * 32, 'x' * 27 + '-1001'), 32), 'x' * 27 + '-1002')
        self.assertEqual(unique_name('free', lambda name: False, 32), 'free')

    def test_duplicate_session_creation_returns_actual_id(self):
        self.panel.session_exists = Mock(side_effect=lambda name: name == 'demo')
        self.panel.resolve_path = Mock(return_value=str(self.home))
        self.panel.create_session = Mock()
        with patch('integrations.names.secrets.randbelow', return_value=17):
            result = self.panel.action_new({'name':'demo', 'agent':'shell'})
        self.assertEqual(result, {'name':'demo-1017'})
        self.assertEqual(self.panel.create_session.call_args.args[0], 'demo-1017')

    def test_duplicate_connections_and_edits_keep_ids_and_credentials(self):
        service = LMStudio(self.home / 'models')
        first = service.save({'name':'Mac', 'url':'http://127.0.0.1:1234', 'key':'test-only'})
        with patch('integrations.names.secrets.randbelow', return_value=42):
            second = service.save({'name':'mac', 'url':'http://127.0.0.1:1234'})
        self.assertEqual(second['name'], 'mac-1042')
        updated = service.save({'id': first['id'], 'name':'Mac', 'url':'http://127.0.0.1:1234'})
        self.assertEqual(updated['id'], first['id'])
        self.assertEqual(service.get(first['id'])['key'], 'test-only')

    def test_rename_only_changes_title_and_restores_it_after_restart(self):
        self.panel.session_exists = Mock(return_value=True)
        self.panel.list_sessions = Mock(return_value=[{'name':'demo','title':'Old'}])
        self.panel.tmux = Mock(return_value='')
        self.assertEqual(self.panel.action_rename({'name':'demo','title':'Новая работа'}), {'name':'demo','title':'Новая работа'})
        self.panel.tmux.assert_called_once_with('set-option','-t','=cc-demo:','@cc_title','Новая работа')
        self.panel.tmux.reset_mock()
        self.panel.create_session = Mock()
        self.panel.restore_session('demo', {'path':str(self.home),'agent':'shell','title':'Новая работа'})
        self.panel.tmux.assert_called_once_with('set-option','-t','=cc-demo:','@cc_title','Новая работа')
        self.panel.tmux.return_value=f'cc-demo\t{self.home}\tbash\t\t0\t1\tshell\t\tНовая работа\n'
        self.assertEqual(self.panel.live_sessions()['demo']['title'], 'Новая работа')
        for invalid in ('', 'x\ny', 'x'*101):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.panel.action_rename({'name':'demo','title':invalid})
