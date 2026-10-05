import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from support import ROOT
sys.path.insert(0, str(ROOT))
from integrations import dependencies as D
from integrations import dependency_lock
import copy

PINNED = copy.deepcopy(dependency_lock.WHEELS)  # Tests below patch the shared dict.


def wheel(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data, mode in files:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            archive.writestr(info, data)
    return buffer.getvalue()


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *args): return False


class DependencyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.good = wheel([('fake_pkg/__init__.py', b'VALUE = 1\n', 0o100644), ('fake_pkg-1.dist-info/METADATA', b'', 0o100644)])
        self.lock = {'cp312-linux-x86_64': [{'filename': 'fake.whl', 'url': 'https://files.pythonhosted.org/fake.whl',
                                             'sha256': hashlib.sha256(self.good).hexdigest()}]}
        self.enterContext = lambda c: (c.__enter__(), self.addCleanup(c.__exit__, None, None, None))
        self.enterContext(patch.dict(D.WHEELS, self.lock, clear=True))
        self.downloads = []

    def opener(self, payload):
        def open_(request, timeout):
            self.downloads.append(request.full_url)
            return Response(payload)
        return open_

    def test_platform_keys_match_the_lock_for_supported_systems(self):
        cases = [('linux', 'x86_64', ('glibc', '2.35'), 'cp312-linux-x86_64'), ('linux', 'aarch64', ('glibc', '2.39'), 'cp312-linux-aarch64'),
                 ('darwin', 'arm64', ('', ''), 'cp312-darwin-arm64'), ('darwin', 'x86_64', ('', ''), 'cp312-darwin-x86_64'),
                 ('linux', 'x86_64', ('', ''), None), ('win32', 'AMD64', ('', ''), None)]
        for system, machine, libc, expected in cases:
            with patch.object(D.sys, 'platform', system), patch.object(D.platform, 'machine', return_value=machine), \
                 patch.object(D.platform, 'libc_ver', return_value=libc), patch.object(D.sys, 'version_info', (3, 12, 0)):
                self.assertEqual(D.platform_key(), expected, (system, machine))
        for key in PINNED:
            self.assertRegex(key, r'^cp3(10|11|12|13|14)-(linux-(x86_64|aarch64)|darwin-(arm64|x86_64))$')

    def test_every_pinned_wheel_comes_from_pypi_with_a_sha256(self):
        for key, wheels in PINNED.items():
            names = [w['filename'].split('-')[0] for w in wheels]
            self.assertIn('cryptography', names, key)
            self.assertIn('cffi', names, key)
            for item in wheels:
                self.assertTrue(item['url'].startswith('https://files.pythonhosted.org/'), item)
                self.assertRegex(item['sha256'], r'^[0-9a-f]{64}$')

    def test_install_verifies_hashes_and_is_idempotent(self):
        folder = D.install('cp312-linux-x86_64', self.root, self.opener(self.good))
        self.assertEqual((folder / 'fake_pkg/__init__.py').read_text(), 'VALUE = 1\n')
        self.assertTrue((folder / '.complete').is_file())
        D.install('cp312-linux-x86_64', self.root, self.opener(self.good))
        self.assertEqual(len(self.downloads), 1)

    def test_tampered_or_unsafe_wheels_leave_nothing_installed(self):
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            D.install('cp312-linux-x86_64', self.root, self.opener(self.good + b'x'))
        for files in ([('../escape.py', b'x', 0o100644)], [('/abs.py', b'x', 0o100644)], [('link', b'/etc/passwd', 0o120777)]):
            bad = wheel(files)
            D.WHEELS['cp312-linux-x86_64'][0]['sha256'] = hashlib.sha256(bad).hexdigest()
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                D.install('cp312-linux-x86_64', self.root, self.opener(bad))
        self.assertEqual([p for p in self.root.iterdir()], [])
        self.assertFalse((self.root.parent / 'escape.py').exists())

    def test_unsupported_platform_reports_what_is_supported(self):
        with self.assertRaisesRegex(ValueError, 'Linux \\(glibc\\) and macOS'):
            D.install('cp312-win32-amd64', self.root, self.opener(self.good))

    def test_a_new_lock_replaces_the_previous_directory(self):
        old = D.install('cp312-linux-x86_64', self.root, self.opener(self.good))
        newer = wheel([('fake_pkg/__init__.py', b'VALUE = 2\n', 0o100644)])
        D.WHEELS['cp312-linux-x86_64'][0].update(sha256=hashlib.sha256(newer).hexdigest(), filename='fake2.whl')
        new = D.install('cp312-linux-x86_64', self.root, self.opener(newer))
        self.assertNotEqual(old, new)
        self.assertFalse(old.exists())
        self.assertEqual((new / 'fake_pkg/__init__.py').read_text(), 'VALUE = 2\n')
