import unittest

from integrations import direct
from integrations.deck_transport import remote_path


class DirectLinkTests(unittest.TestCase):
    def test_a_link_signs_in_once_and_only_within_a_minute(self):
        now = [1000.0]
        links = direct.Links(clock=lambda: now[0])
        token = links.create()
        self.assertRegex(token, r'\A[0-9a-f]{64}\Z')
        self.assertFalse(links.redeem('0' * 64))
        self.assertFalse(links.redeem(None))
        self.assertFalse(links.redeem('é'))
        self.assertTrue(links.redeem(token))
        self.assertFalse(links.redeem(token))
        late = links.create()
        now[0] += direct.TTL + 1
        self.assertFalse(links.redeem(late))

    def test_only_a_few_links_wait_at_a_time_and_the_oldest_goes_first(self):
        now = [1000.0]
        links = direct.Links(clock=lambda: now[0])
        made = []
        for _ in range(direct.MAX_PENDING + 2):
            now[0] += 1
            made.append(links.create())
        self.assertEqual(len(links.pending), direct.MAX_PENDING)
        self.assertFalse(links.redeem(made[0]))
        self.assertTrue(links.redeem(made[-1]))

    def test_a_page_cannot_ask_for_a_link_through_the_gateway(self):
        for path in ('/api/direct_link', '/api/direct_login'):
            with self.assertRaises(ValueError):
                remote_path(path)

    def test_the_page_loads_nothing_and_cannot_be_framed(self):
        headers = dict(direct.HEADERS)
        self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn(b'src=', direct.PAGE)
        self.assertIn(b'history.replaceState', direct.PAGE)


if __name__ == '__main__':
    unittest.main()
