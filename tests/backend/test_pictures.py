import base64
import unittest

from integrations import pictures

PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32


def resolver(*addresses):
    return lambda host, port, type=None: [(None, None, None, '', (address, port)) for address in addresses]


class PictureFetchTest(unittest.TestCase):
    def test_public_picture_is_returned_with_its_type(self):
        asked = []

        def ask(host, address, path):
            asked.append((host, address, path))
            return 200, None, PNG
        kind, body = pictures.fetch('https://cdn.example/a.png?x=1', resolver('93.184.216.34'), ask)
        self.assertEqual((kind, body), ('image/png', PNG))
        # Dialled at the address that was checked, never resolved a second time.
        self.assertEqual(asked, [('cdn.example', '93.184.216.34', '/a.png?x=1')])

    def test_addresses_inside_a_network_are_refused_before_any_connection(self):
        def ask(*_):
            raise AssertionError('must not connect')
        for address in ('127.0.0.1', '10.0.0.5', '192.168.1.1', '172.16.3.4', '100.109.113.79', '169.254.169.254', '::1', 'fd00::1'):
            with self.assertRaises(ValueError):
                pictures.fetch('https://router.example/logo.png', resolver(address), ask)
        # One private address among public ones is enough to refuse: the name may answer differently next time.
        with self.assertRaises(ValueError):
            pictures.fetch('https://mixed.example/a.png', resolver('93.184.216.34', '10.0.0.5'), ask)

    def test_only_plain_https_addresses_are_accepted(self):
        for url in ('http://cdn.example/a.png', 'https://user:pw@cdn.example/a.png', 'https://cdn.example:8443/a.png',
                    'file:///etc/passwd', 'https:///a.png', None, 'https://cdn.example/' + 'a' * 5000):
            with self.assertRaises(ValueError):
                pictures.fetch(url, resolver('93.184.216.34'), lambda *_: (200, None, PNG))

    def test_redirect_is_followed_only_to_another_public_https_address(self):
        def ask(host, address, path):
            return (302, 'https://img.example/b.png', b'') if host == 'cdn.example' else (200, None, PNG)
        self.assertEqual(pictures.fetch('https://cdn.example/a', resolver('93.184.216.34'), ask)[0], 'image/png')
        with self.assertRaises(ValueError):
            pictures.fetch('https://cdn.example/a', resolver('93.184.216.34'), lambda *_: (302, 'http://127.0.0.1:8790/api/image', b''))
        inside = lambda host, port, type=None: resolver('10.0.0.5' if host == 'inside.example' else '93.184.216.34')(host, port)
        with self.assertRaises(ValueError):
            pictures.fetch('https://cdn.example/a', inside, lambda *_: (302, 'https://inside.example/x.png', b''))
        with self.assertRaises(ValueError):
            pictures.fetch('https://cdn.example/a', resolver('93.184.216.34'), lambda *_: (302, 'https://cdn.example/a', b''))

    def test_answer_must_be_a_picture_within_the_size_cap(self):
        with self.assertRaises(ValueError):
            pictures.fetch('https://cdn.example/a', resolver('93.184.216.34'), lambda *_: (200, None, b'<html>sign in</html>'))
        with self.assertRaises(ValueError):
            pictures.fetch('https://cdn.example/a', resolver('93.184.216.34'), lambda *_: (200, None, PNG + b'0' * pictures.MAX_BYTES))
        with self.assertRaises(ValueError):
            pictures.fetch('https://cdn.example/a', resolver('93.184.216.34'), lambda *_: (403, None, b''))

        def broken(*_):
            raise OSError('connection reset')
        with self.assertRaises(ValueError):
            pictures.fetch('https://cdn.example/a', resolver('93.184.216.34'), broken)

    def test_action_answers_base64_for_the_page(self):
        original = pictures.fetch
        pictures.fetch = lambda url: ('image/png', PNG)
        try:
            self.assertEqual(pictures.action({'url': 'https://cdn.example/a'}), {'type': 'image/png', 'data': base64.b64encode(PNG).decode()})
        finally:
            pictures.fetch = original


if __name__ == '__main__':
    unittest.main()
