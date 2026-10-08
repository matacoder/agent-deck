import json
import sys
import unittest
from unittest.mock import Mock

from support import ROOT
sys.path.insert(0, str(ROOT))
from integrations import gateway as G

ITEM = {'id': 'fp', 'session': 'api', 'agent': 'claude', 'title': 'Proceed?', 'selected': 0,
        'options': [{'label': 'Yes'}, {'label': 'No'}]}


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.decks = Mock()
        self.decks.status.return_value = {'decks': [{'id': 'a' * 24, 'name': 'Mac'}, {'id': 'b' * 24, 'name': 'Server'}]}
        self.now = [100.0]
        self.gateway = G.Gateway(lambda: self.decks, clock=lambda: self.now[0])

    def test_only_json_objects_count_as_answers(self):
        for raw in (b'[1]', b'<html>', b'null'):
            self.decks.request.return_value = (200, {}, raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                G.get_json(self.decks, 'a' * 24, '/api/sessions')
        self.decks.request.return_value = (200, {}, b'{"ok":true}')
        self.assertEqual(G.get_json(self.decks, 'a' * 24, '/api/x'), (200, {'ok': True}))

    def test_one_failing_computer_does_not_hide_the_others(self):
        def request(deck, method, path, *args, **kwargs):
            if deck == 'b' * 24:
                raise OSError('timed out')
            return 200, {}, json.dumps({'questions': [ITEM]}).encode()
        self.decks.request.side_effect = request
        [question] = self.gateway.questions()
        self.assertEqual((question.deck, question.origin), ('a' * 24, 'Mac'))
        self.assertIn('b' * 24, self.gateway.backoff)

    def test_a_removed_computer_forgets_its_questions_at_once(self):
        self.decks.request.return_value = (200, {}, json.dumps({'questions': [ITEM]}).encode())
        self.assertEqual(len(self.gateway.questions()), 2)
        self.decks.status.return_value = {'decks': [{'id': 'a' * 24, 'name': 'Mac'}]}
        self.assertEqual([q.deck for q in self.gateway.questions()], ['a' * 24])
        self.assertEqual(set(self.gateway.snapshot), {'a' * 24})

    def test_session_lists_are_refreshed_every_ten_seconds(self):
        self.decks.request.return_value = (200, {}, b'{"sessions":[{"name":"api"}]}')
        self.assertEqual(len(self.gateway.sessions()), 2)
        self.gateway.sessions()
        self.assertEqual(self.decks.request.call_count, 2)
        self.now[0] += 11
        self.gateway.sessions()
        self.assertEqual(self.decks.request.call_count, 4)

    def test_telegram_states_skip_computers_that_did_not_answer(self):
        def request(deck, method, path, *args, **kwargs):
            if deck == 'b' * 24:
                return 200, {}, b'not json'
            return 200, {}, b'{"telegram":{"bot":"deck_bot","enabled":true}}'
        self.decks.request.side_effect = request
        self.assertEqual(self.gateway.telegram_states(), [('a' * 24, 'Mac', {'bot': 'deck_bot', 'enabled': True})])
