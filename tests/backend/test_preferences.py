import io
import json
from pathlib import Path
from unittest.mock import Mock

from support import PanelCase
from integrations.preferences import ProjectDirectory


class ProjectDirectoryTests(PanelCase):
    def test_change_is_immediate_persistent_and_keeps_existing_sessions(self):
        old = self.panel.resolve_path({'project': 'old'}, 'demo')
        directory = str(self.home / 'dev with spaces')
        self.assertEqual(self.panel.ACTIONS['project_directory']({'directory': directory}), {'directory': directory})
        self.assertEqual(self.panel.resolve_path({'project': 'new'}, 'demo'), str(Path(directory) / 'new'))
        self.assertTrue(Path(old).is_dir())
        restored = ProjectDirectory(self.home, self.home / 'projects')
        self.assertEqual(restored.get(), directory)
        self.assertEqual(restored.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(restored.save('~/dev'), str(self.home / 'dev'))

    def test_invalid_paths_and_symlink_escape_do_not_change_setting(self):
        original = self.panel.project_directory.get()
        file = self.home / 'file'
        file.write_text('test')
        (self.home / 'escape').symlink_to('/tmp')
        for invalid in ('', None, [], 'relative/path', '/tmp', str(file), str(self.home / 'escape')):
            with self.subTest(path=invalid), self.assertRaises(ValueError):
                self.panel.project_directory.save(invalid)
            self.assertEqual(self.panel.project_directory.get(), original)

    def handler(self, authorized=True, same_origin=True):
        handler = object.__new__(self.panel.Handler)
        handler.path = '/api/project_directory'
        handler.authorized = Mock(return_value=authorized)
        handler.same_origin = Mock(return_value=same_origin)
        handler.send_json = Mock()
        payload = json.dumps({'directory': str(self.home / 'dev')}).encode()
        handler.headers = {'Content-Type': 'application/json', 'Content-Length': str(len(payload))}
        handler.rfile = io.BytesIO(payload)
        return handler

    def test_api_requires_authentication_and_same_origin_for_writes(self):
        for authorized, origin in ((False, True), (True, False)):
            handler = self.handler(authorized, origin)
            handler.post_request()
            self.assertFalse((self.home / 'dev').exists())
            if authorized:
                self.assertEqual(handler.send_json.call_args.args[0], 403)
        handler = self.handler()
        handler.post_request()
        self.assertEqual(handler.send_json.call_args.args, (200, {'ok': True, 'directory': str(self.home / 'dev')}))
        handler.get_request()
        self.assertEqual(handler.send_json.call_args.args, (200, {'directory': str(self.home / 'dev')}))
