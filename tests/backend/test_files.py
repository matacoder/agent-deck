from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT, PanelCase
sys.path.insert(0, str(ROOT))
from integrations import files as F


class FileBrowserTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.project = self.home / 'dev/api'
        self.project.mkdir(parents=True)
        (self.project / '.env').write_text('TOKEN=old\n')
        (self.project / 'src').mkdir()
        (self.home / '.config/cc-panel').mkdir(parents=True)
        (self.home / '.config/cc-panel/env').write_text('PANEL_PASSWORD=secret\n')

    def test_listing_shows_folders_first_and_hidden_files_but_never_the_panel_settings(self):
        data = F.listing(self.home, str(self.project))
        self.assertEqual([e['name'] for e in data['entries']], ['src', '.env'])
        self.assertEqual(data['parent'], str(self.home / 'dev'))
        config = F.listing(self.home, str(self.home / '.config'))
        self.assertEqual(config['entries'], [])
        for path in (str(self.home / '.config/cc-panel'), str(self.home / '.config/cc-panel/env')):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'ключи панели'):
                F.listing(self.home, path) if path.endswith('panel') else F.read_text(self.home, path)

    def test_nothing_outside_home_is_reachable_even_through_symlinks(self):
        (self.project / 'escape').symlink_to('/etc')
        self.assertNotIn('escape', [e['name'] for e in F.listing(self.home, str(self.project))['entries']])
        for path in ('/etc/passwd', str(self.project / 'escape/passwd'), str(self.home / '..'), ''):
            with self.subTest(path=path), self.assertRaises(ValueError):
                F.read_text(self.home, path)

    def test_text_is_read_and_binary_or_large_files_are_refused(self):
        data = F.read_text(self.home, str(self.project / '.env'))
        self.assertEqual(data['content'], 'TOKEN=old\n')
        (self.project / 'blob.bin').write_bytes(b'\x00\x01')
        (self.project / 'big.txt').write_bytes(b'x' * (F.MAX_TEXT + 1))
        for name in ('blob.bin', 'big.txt'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                F.read_text(self.home, str(self.project / name))

    def test_images_and_pdf_are_previewed_by_content_never_html_or_svg(self):
        import base64
        (self.project / 'shot.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'0' * 20)
        (self.project / 'doc.pdf').write_bytes(b'%PDF-1.7\n...')
        (self.project / 'fake.png').write_text('<svg onload=alert(1)></svg>')
        png = F.read_preview(self.home, str(self.project / 'shot.png'))
        self.assertEqual((png['type'], base64.b64decode(png['data'])[:4]), ('image/png', b'\x89PNG'))
        self.assertEqual(F.read_preview(self.home, str(self.project / 'doc.pdf'))['type'], 'application/pdf')
        with self.assertRaisesRegex(ValueError, 'PNG, JPEG'):
            F.read_preview(self.home, str(self.project / 'fake.png'))
        with self.assertRaises(ValueError):
            F.read_preview(self.home, str(self.home / '.config/cc-panel/env'))
        (self.project / 'huge.pdf').write_bytes(b'%PDF-' + b'0' * F.MAX_PREVIEW)
        with self.assertRaisesRegex(ValueError, '10 МБ'):
            F.read_preview(self.home, str(self.project / 'huge.pdf'))

    def test_any_file_downloads_except_the_panel_settings_files_outside_home_and_huge_ones(self):
        (self.project / 'plan.zip').write_bytes(b'PK\x03\x04\x00')
        self.assertEqual(F.read_download(self.home, str(self.project / 'plan.zip')), ('plan.zip', b'PK\x03\x04\x00'))
        (self.project / 'escape').symlink_to('/etc')
        for path in (str(self.home / '.config/cc-panel/env'), '/etc/passwd', str(self.project / 'escape/passwd'), str(self.project)):
            with self.subTest(path=path), self.assertRaises((ValueError, FileNotFoundError)):
                F.read_download(self.home, path)
        with patch.object(F, 'MAX_DOWNLOAD', 4), self.assertRaisesRegex(ValueError, '40 МБ'):
            F.read_download(self.home, str(self.project / 'plan.zip'))

    def test_save_keeps_mode_and_refuses_to_overwrite_a_file_that_changed(self):
        env = self.project / '.env'
        env.chmod(0o640)
        opened = F.read_text(self.home, str(env))
        saved = F.save_text(self.home, str(env), 'TOKEN=new\n', opened['hash'])
        self.assertEqual(env.read_text(), 'TOKEN=new\n')
        self.assertEqual(env.stat().st_mode & 0o777, 0o640)
        with self.assertRaisesRegex(FileExistsError, 'изменился'):
            F.save_text(self.home, str(env), 'TOKEN=stale\n', opened['hash'])
        self.assertEqual(saved['hash'], F.digest(b'TOKEN=new\n'))
        self.assertEqual(sorted(p.name for p in self.project.iterdir()), ['.env', 'src'])  # No temp files left.

    def test_new_files_are_private_and_never_replace_an_existing_one(self):
        secret = self.project / 'src/.env.local'
        F.save_text(self.home, str(secret), 'KEY=pasted\n', None)
        self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(FileExistsError, 'уже есть'):
            F.save_text(self.home, str(secret), 'KEY=other\n', None)
        with self.assertRaises(ValueError):
            F.save_text(self.home, str(self.home / '.config/cc-panel/env'), 'PANEL_PASSWORD=x\n', None)


class SymlinkedConfigTests(unittest.TestCase):
    def test_the_panel_folder_stays_closed_when_config_is_a_symlink(self):
        import os
        tmp = tempfile.TemporaryDirectory(dir='/tmp'); self.addCleanup(tmp.cleanup)
        home = Path(tmp.name).resolve()
        (home / 'dotfiles/config/cc-panel').mkdir(parents=True)
        (home / 'dotfiles/config/cc-panel/env').write_text('PANEL_PASSWORD=secret\n')
        os.symlink(home / 'dotfiles/config', home / '.config')  # stow-style dotfiles
        for path in (home / '.config/cc-panel/env', home / 'dotfiles/config/cc-panel/env'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'ключи панели'):
                F.read_text(home, str(path))
        self.assertEqual(F.listing(home, str(home / '.config'))['entries'], [])
        self.assertEqual(F.listing(home, str(home / 'dotfiles/config'))['entries'], [])


class PanelFileTests(PanelCase):
    def test_file_errors_reach_the_user_as_clear_messages(self):
        with self.assertRaisesRegex(ValueError, 'Папка не найдена|недоступны'):
            # The panel's idea of home (patched in tests), not the runner's.
            self.panel.files_payload({'path': [self.panel.os.path.expanduser('~') + '/no-such-folder-agent-deck']})
        with self.assertRaisesRegex(ValueError, 'сессия не найдена'):
            self.panel.files_payload({'name': ['../x']})

    def test_any_other_file_system_error_is_a_clear_message(self):
        with self.assertRaisesRegex(ValueError, 'недоступны'):
            self.panel.files_payload({'path': [self.panel.os.path.expanduser('~') + '/' + 'x' * 300]})
