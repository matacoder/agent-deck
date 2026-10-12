import http.client
import json
import unittest

from integrations import here

ID = 'b' * 24


class HereTests(unittest.TestCase):
    def test_only_the_right_id_gets_an_answer_another_page_may_read(self):
        status, headers, body = here.answer('/api/here?id=' + ID, ID)
        self.assertEqual((status, json.loads(body), headers['Access-Control-Allow-Origin']), (200, {'same': True}, '*'))
        for path, instance in (('/api/here?id=' + 'c' * 24, ID), ('/api/here?id=', ID), ('/api/here?id=' + ID, ''), ('/api/here?id=é', ID)):
            self.assertEqual(here.answer(path, instance), (404, {}, b'{}'), path)

    def test_the_loopback_answerer_serves_that_one_question_and_nothing_of_the_panel(self):
        self.assertIsNone(here.start('0.0.0.0', 8790, lambda: ID))  # The panel itself already listens there.
        server = here.start('100.64.0.1', 0, lambda: ID)
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))

        def ask(method, path):
            link = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=5)
            try:
                link.request(method, path)
                answer = link.getresponse()
                return answer.status, answer.getheader('Access-Control-Allow-Origin'), answer.read()
            finally:
                link.close()
        self.assertEqual(ask('GET', '/api/here?id=' + ID), (200, '*', b'{"same": true}'))
        self.assertEqual(ask('GET', '/api/here?id=' + 'c' * 24), (404, None, b'{}'))
        self.assertEqual(ask('GET', '/login')[:2], (404, None))
        self.assertEqual(ask('GET', '/api/sessions')[:2], (404, None))
        self.assertEqual(ask('OPTIONS', '/api/here?id=' + ID)[:2], (204, '*'))

    def test_a_taken_port_only_means_pages_do_not_learn_they_are_local(self):
        def taken(address, handler):
            raise OSError('in use')
        self.assertIsNone(here.start('100.64.0.1', 8790, lambda: ID, serve=taken))


if __name__ == '__main__':
    unittest.main()
