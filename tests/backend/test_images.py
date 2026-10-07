import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from support import ROOT, PanelCase
sys.path.insert(0, str(ROOT))
from integrations import images as I

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32
SCREEN = '''  Касса (/private/tmp/padel-w1-cashier-
preview/cashier_viewport.png) · Отдельный экран
  Saved shots/home.png and ~/Desktop/report.jpg
'''


class ImageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'project/shots').mkdir(parents=True)
        (self.root / 'project/shots/home.png').write_bytes(PNG)
        (self.root / 'home/Desktop').mkdir(parents=True)
        (self.root / 'home/Desktop/report.jpg').write_bytes(b'\xff\xd8\xff' + b'0' * 32)

    def read(self, path, screen=SCREEN):
        return I.read_image(path, self.root / 'project', self.root / 'home', screen)

    def test_paths_wrapped_by_the_agent_still_count_as_visible(self):
        self.assertTrue(I.visible('/private/tmp/padel-w1-cashier-preview/cashier_viewport.png', SCREEN))
        self.assertFalse(I.visible('/private/tmp/other.png', SCREEN))
        self.assertFalse(I.visible('', SCREEN))

    def test_relative_and_home_paths_resolve_against_session_and_user(self):
        self.assertEqual(self.read('shots/home.png'), ('image/png', PNG))
        self.assertEqual(self.read('~/Desktop/report.jpg')[0], 'image/jpeg')

    def test_only_on_screen_raster_images_are_served(self):
        (self.root / 'project/evil.png').write_bytes(b'<svg onload=alert(1)>')
        (self.root / 'project/logo.svg').write_bytes(b'<svg/>')
        (self.root / 'project/secret.txt').write_text('token')
        (self.root / 'project/link.png').symlink_to(self.root / 'project/secret.txt')
        screen = SCREEN + ' evil.png logo.svg link.png notes.png'
        with self.assertRaisesRegex(ValueError, 'нет на экране'):
            self.read(str(self.root / 'project/shots/home.png'))
        with self.assertRaisesRegex(ValueError, 'не похож'):
            self.read('evil.png', screen)
        with self.assertRaisesRegex(ValueError, 'PNG, JPEG'):
            self.read('logo.svg', screen)
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.read('link.png', screen)
        with self.assertRaises(FileNotFoundError):
            self.read('notes.png', screen)

    def test_a_bare_file_name_is_found_inside_the_session_folder_newest_first(self):
        old, new = self.root / 'project/test-results/a', self.root / 'project/test-results/b'
        old.mkdir(parents=True); new.mkdir()
        (old / 'chromium-1440.png').write_bytes(PNG)
        (new / 'chromium-1440.png').write_bytes(PNG + b'new')
        os.utime(old / 'chromium-1440.png', (1, 1))
        screen = SCREEN + '\n• Viewed image chromium-1440.png'
        self.assertEqual(self.read('chromium-1440.png', screen)[1], PNG + b'new')

    def test_name_search_skips_dependencies_links_and_stops_early(self):
        (self.root / 'project/node_modules/pkg').mkdir(parents=True)
        (self.root / 'project/node_modules/pkg/only.png').write_bytes(PNG)
        (self.root / 'outside.png').write_bytes(PNG)
        (self.root / 'project/link').symlink_to(self.root)
        self.assertIsNone(I.find_by_name('only.png', self.root / 'project'))
        self.assertIsNone(I.find_by_name('outside.png', self.root / 'project'))
        with self.assertRaises(FileNotFoundError):
            self.read('only.png', SCREEN + ' only.png')
        self.assertIsNone(I.find_by_name('home.png', self.root / 'project', limit=1))

    def test_large_files_are_refused(self):
        with patch.object(I, 'MAX_BYTES', 10):
            with self.assertRaisesRegex(ValueError, '25'):
                self.read('shots/home.png')


class ImageEndpointTests(PanelCase):
    def test_endpoint_checks_the_session_and_sends_inert_image_headers(self):
        (self.home / 'shot.png').write_bytes(PNG)
        self.panel.session_exists = Mock(return_value=True)
        self.panel.tmux = Mock(side_effect=lambda *args, **kw: 'saved shot.png' if args[0] == 'capture-pane' else str(self.home))
        handler = object.__new__(self.panel.Handler)
        handler.send_json = Mock()
        sent = {}
        handler.send_response = lambda code: sent.setdefault('code', code)
        handler.send_header = lambda k, v: sent.setdefault('headers', {}).__setitem__(k, v)
        handler.end_headers = Mock()
        handler.wfile = Mock()
        handler.serve_session_image({'name': ['demo'], 'path': ['shot.png']})
        self.assertEqual(sent['code'], 200)
        self.assertEqual(sent['headers']['Content-Type'], 'image/png')
        self.assertEqual(sent['headers']['X-Content-Type-Options'], 'nosniff')
        self.assertIn('sandbox', sent['headers']['Content-Security-Policy'])
        handler.wfile.write.assert_called_once_with(PNG)
        handler.serve_session_image({'name': ['../x'], 'path': ['shot.png']})
        self.assertEqual(handler.send_json.call_args.args[0], 404)
        handler.serve_session_image({'name': ['demo'], 'path': ['other.png']})
        self.assertEqual(handler.send_json.call_args.args[0], 400)


class ThumbnailTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / 'shot.png'
        self.source.write_bytes(PNG)

    def test_tools_are_chosen_per_platform_and_never_through_a_shell(self):
        sips = I.thumbnail_command(self.source, self.root / 't.jpg', 'image/png', which=lambda t: '/usr/bin/sips' if t == 'sips' else None)
        self.assertEqual(sips[:6], ['sips', '-Z', '480', '-s', 'format', 'jpeg'])
        magick = I.thumbnail_command(self.source, self.root / 't.jpg', 'image/png', which=lambda t: '/usr/bin/convert' if t == 'convert' else None)
        self.assertEqual(magick[0], 'convert')
        self.assertEqual(magick[1], f'png:{self.source}[0]')  # The coder is fixed by checked content.
        self.assertIsNone(I.thumbnail_command(self.source, self.root / 't.jpg', 'image/png', which=lambda t: None))

    def test_thumbnail_is_cached_until_the_file_changes_and_falls_back_on_failure(self):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            Path(command[-1]).write_bytes(b'\xff\xd8\xff small')
            return Mock(returncode=0)
        which = lambda t: '/usr/bin/sips' if t == 'sips' else None
        cache = self.root / 'cache'
        self.assertEqual(I.thumbnail(self.source, cache, 'image/png', run=run, which=which), b'\xff\xd8\xff small')
        self.assertEqual(I.thumbnail(self.source, cache, 'image/png', run=run, which=which), b'\xff\xd8\xff small')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'sips')
        os.utime(self.source, ns=(1, 1))
        I.thumbnail(self.source, cache, 'image/png', run=run, which=which)
        self.assertEqual(len(calls), 2)
        broken = lambda command, **kwargs: Mock(returncode=1)
        os.utime(self.source, ns=(2, 2))
        self.assertIsNone(I.thumbnail(self.source, cache, 'image/png', run=broken, which=which))
        self.assertEqual([p.suffix for p in cache.iterdir()], ['.jpg', '.jpg'])


class ThumbnailSafetyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_a_disguised_file_never_reaches_a_converter(self):
        fake = self.root / 'shot.png'
        fake.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>')
        with patch.object(I, 'thumbnail') as thumbnail, self.assertRaisesRegex(ValueError, 'не похож'):
            I.read_image(str(fake), str(self.root), str(self.root), str(fake), cache=self.root / 'cache')
        thumbnail.assert_not_called()

    def test_old_thumbnails_are_pruned(self):
        cache = self.root / 'cache'; cache.mkdir()
        old, fresh = cache / 'old.jpg', cache / 'fresh.jpg'
        old.write_bytes(b'x'); fresh.write_bytes(b'x')
        os.utime(old, (1, 1))
        I.prune_cache(cache)
        self.assertEqual([p.name for p in cache.iterdir()], ['fresh.jpg'])
