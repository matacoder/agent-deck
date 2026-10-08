import sys
import unittest
from unittest.mock import patch

from support import ROOT, PanelCase
sys.path.insert(0, str(ROOT))
from integrations import scrollback as S


class ScrollbackTests(unittest.TestCase):
    def test_matches_are_case_insensitive_newest_first_with_context(self):
        text = 'start\nError: first\nok\nmiddle\nERROR again\nend\n\n\n'
        data = S.search(text, '  error ')
        self.assertEqual((data['total'], data['lines']), (2, 6))
        self.assertEqual([m['line'] for m in data['matches']], [5, 2])
        self.assertEqual(data['matches'][0]['before'], ['ok', 'middle'])
        self.assertEqual(data['matches'][0]['after'], ['end'])

    def test_a_huge_line_is_cut_around_the_match(self):
        line = 'x' * 50000 + 'NEEDLE' + 'y' * 50000
        hit = S.search(line + '\n' + 'z' * 10000, 'needle')['matches'][0]
        self.assertIn('NEEDLE', hit['text'])
        self.assertLessEqual(len(hit['text']), S.MAX_LINE + 2)
        self.assertLessEqual(len(hit['after'][0]), S.MAX_LINE + 2)

    def test_query_is_plain_text_and_results_are_capped(self):
        self.assertEqual(S.search('a.*b\naxxb\n', 'a.*b')['total'], 1)
        data = S.search('hit\n' * 500, 'hit')
        self.assertEqual((data['total'], len(data['matches'])), (500, S.MAX_MATCHES))
        for bad in ('', '   ', 'x' * 201, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                S.search('text', bad)


class PanelScrollbackTests(PanelCase):
    def test_search_reads_the_whole_scrollback_of_a_real_session_only(self):
        with self.assertRaisesRegex(ValueError, 'сессия не найдена'):
            self.panel.scrollback_payload({'name': ['../x'], 'q': ['a']})
        calls = []
        def tmux(*args, check=True):
            calls.append(args)
            return 'one\nneedle here\n'
        with patch.object(self.panel, 'session_exists', return_value=True), patch.object(self.panel, 'tmux', tmux):
            data = self.panel.scrollback_payload({'name': ['work'], 'q': ['needle']})
        self.assertEqual(data['matches'][0]['text'], 'needle here')
        self.assertEqual(calls[0][:3], ('capture-pane', '-p', '-J'))
        self.assertIn('-S', calls[0])
        self.assertEqual(calls[0][calls[0].index('-S') + 1], '-')

    def test_a_stuck_tmux_is_a_clear_error_not_a_server_error(self):
        import subprocess
        def stuck(*args, check=True):
            raise subprocess.TimeoutExpired('tmux', 10)
        with patch.object(self.panel, 'session_exists', return_value=True), patch.object(self.panel, 'tmux', stuck):
            with self.assertRaisesRegex(ValueError, 'tmux не ответил'):
                self.panel.scrollback_payload({'name': ['work'], 'q': ['x']})


if __name__ == '__main__':
    unittest.main()
