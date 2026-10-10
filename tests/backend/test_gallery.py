from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT
sys.path.insert(0, str(ROOT))
from integrations import gallery as G

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 20


class GalleryTests(unittest.TestCase):
    NOW = 1_800_000_000

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.project = self.home / 'dev/app'
        (self.project / 'shots').mkdir(parents=True)
        self.gallery = G.Gallery(self.home / '.cache/gallery', clock=lambda: self.NOW)

    def collect(self, screen):
        return self.gallery.collect('demo', screen, str(self.project), str(self.home))

    def test_paths_are_found_like_on_the_screen_including_wrapped_ones(self):
        screen = 'Saved (/tmp/padel-w1-cashier-\npreview/cashier.png) and shots/a.PNG, ~/b.webp; https://x/y.png?\nnotes.png.bak'
        self.assertEqual(G.mentioned(screen), ['/tmp/padel-w1-cashier-preview/cashier.png', 'shots/a.PNG', '~/b.webp'])  # Web links are not files.

    def test_a_very_long_line_does_not_stall_the_panel(self):
        import time
        long = 'QUJD' * 50_000  # `base64 -w0` of a picture: 200 000 characters and no path at the end.
        began = time.monotonic()
        self.assertEqual(G.mentioned(long + '=\n' + long + '\nshots/wide-\nscreen.png'), ['shots/wide-screen.png'])
        self.assertLess(time.monotonic() - began, 1)

    def test_the_gallery_and_its_list_are_private_to_the_user(self):
        import os
        (self.project / 'shots/a.png').write_bytes(PNG)
        old = os.umask(0o002)
        self.addCleanup(os.umask, old)
        self.assertEqual(self.collect('shots/a.png'), 1)
        root = self.gallery.root
        modes = [oct(path.stat().st_mode & 0o777) for path in (root, root / 'demo', root / 'demo/index.json')]
        self.assertEqual(modes, ['0o700', '0o700', '0o600'])
        root.chmod(0o775)  # Left open by an earlier version.
        (self.project / 'shots/b.png').write_bytes(PNG + b'1')
        self.collect('shots/b.png')
        self.assertEqual(oct(root.stat().st_mode & 0o777), '0o700')

    def test_pictures_stay_after_the_file_is_replaced_or_deleted(self):
        shot = self.project / 'shots/home.png'
        shot.write_bytes(PNG)
        self.assertEqual(self.collect('see shots/home.png'), 1)
        self.assertEqual(self.collect('see shots/home.png'), 0)  # Unchanged: not read or kept again.
        shot.write_bytes(PNG + b'v2')
        self.assertEqual(self.collect('see shots/home.png'), 1)  # Overwritten: a second picture.
        shot.unlink()
        items = self.gallery.items('demo')
        self.assertEqual([i['name'] for i in items], ['home.png', 'home.png'])
        kind, path = self.gallery.picture('demo', items[1]['id'])
        self.assertEqual((kind, path.read_bytes()), ('image/png', PNG))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        kind, latest = self.gallery.latest('demo', 'shots/home.png', str(self.project), str(self.home))
        self.assertEqual(latest.read_bytes(), PNG + b'v2')
        self.assertIsNone(self.gallery.latest('other', 'shots/home.png', str(self.project), str(self.home)))

    def test_only_real_raster_pictures_named_on_screen_are_kept(self):
        (self.project / 'shots/fake.png').write_text('<svg onload=alert(1)></svg>')
        (self.project / 'shots/big.png').write_bytes(PNG)
        with patch.object(G, 'MAX_BYTES', 10):
            self.assertEqual(self.collect('shots/fake.png shots/big.png missing/none.png'), 0)
        self.assertEqual(self.gallery.items('demo'), [])
        with self.assertRaises(ValueError):
            self.gallery.items('../etc')
        with self.assertRaises(FileNotFoundError):
            self.gallery.picture('demo', 'a' * 24)

    def test_a_bare_name_is_looked_up_in_the_project(self):
        (self.project / 'shots/codex.png').write_bytes(PNG)
        self.assertEqual(self.collect('Viewed image codex.png'), 1)
        self.assertEqual(self.gallery.items('demo')[0]['path'], str(self.project / 'shots/codex.png'))

    def test_limits_drop_the_oldest_and_expired_galleries_go(self):
        with patch.object(G, 'KEEP', 2):
            for n in range(3):
                (self.project / f'shots/{n}.png').write_bytes(PNG + bytes([n]))
                self.collect(f'shots/{n}.png')
        self.assertEqual([i['name'] for i in self.gallery.items('demo')], ['2.png', '1.png'])
        self.assertEqual(len(list((self.home / '.cache/gallery/demo').glob('*.png'))), 2)
        self.NOW += G.DAYS * 86400 + 1
        self.gallery.expire()
        self.assertFalse((self.home / '.cache/gallery/demo').exists())


if __name__ == '__main__':
    unittest.main()
