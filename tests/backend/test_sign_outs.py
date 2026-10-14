import os
from pathlib import Path
import tempfile
import unittest

from support import ROOT  # noqa: F401  (puts the repository on the import path)
from integrations.sign_outs import SignOuts


class SignOutTests(unittest.TestCase):
    def test_an_ended_cookie_is_refused_until_it_expires_and_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path, now = Path(directory) / 'cc-panel/sign-outs.json', [1000]
            store = SignOuts(path, clock=lambda: now[0])
            store.end('1500.' + 'a' * 64, 1500)
            self.assertTrue(store.ended_token('1500.' + 'a' * 64))
            self.assertFalse(store.ended_token('1501.' + 'a' * 64))
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertNotIn('1500.' + 'a' * 64, path.read_text())  # Only a hash is kept.
            self.assertTrue(SignOuts(path).ended_token('1500.' + 'a' * 64))
            now[0] = 2000  # Past its expiry the cookie is refused anyway; the next write forgets it.
            store.end('3000.' + 'b' * 64, 3000)
            self.assertFalse(store.ended_token('1500.' + 'a' * 64))

    def test_a_damaged_file_ends_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sign-outs.json'
            path.write_text('[broken')
            self.assertFalse(SignOuts(path).ended_token('1.' + 'a' * 64))


if __name__ == '__main__':
    unittest.main()
