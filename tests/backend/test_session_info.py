import json
from pathlib import Path
import sys
import tempfile
import unittest

from support import ROOT
sys.path.insert(0, str(ROOT))
from integrations import session_info as S


def jsonl(path, records):
    Path(path).write_text(''.join(json.dumps(r) + '\n' for r in records))
    return path


CLAUDE = [
    {'type': 'user', 'message': {'role': 'user', 'content': '<command-name>/clear</command-name>'}},
    {'type': 'user', 'message': {'role': 'user', 'content': 'Fix the payment webhook'}},
    {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Looking at it.'}, {'type': 'tool_use', 'name': 'Bash'}],
                                      'usage': {'input_tokens': 2, 'cache_read_input_tokens': 90000, 'cache_creation_input_tokens': 1000, 'output_tokens': 500}}},
    {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'tool_result', 'content': 'secret output'}]}},
    {'type': 'assistant', 'isSidechain': True, 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'subagent'}], 'usage': {'input_tokens': 5}}},
]
CODEX = [
    {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '<environment_context>cwd</environment_context>'}]}},
    {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Add a gallery'}]}},
    {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Done.'}]}},
    {'type': 'event_msg', 'payload': {'type': 'token_count', 'info': {'last_token_usage': {'total_tokens': 171390}, 'model_context_window': 258400}}},
]


class SessionInfoTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_context_and_dialogue_come_from_the_conversation_not_tools_or_subagents(self):
        records = S.tail_records(jsonl(self.dir / 'c.jsonl', CLAUDE))
        self.assertEqual(S.context('claude', records), {'tokens': 91502, 'window': None, 'level': 'heavy'})
        self.assertEqual(S.dialogue('claude', records), [('user', 'Fix the payment webhook'), ('assistant', 'Looking at it.')])
        records = S.tail_records(jsonl(self.dir / 'x.jsonl', CODEX))
        self.assertEqual(S.context('codex', records), {'tokens': 171390, 'window': 258400, 'level': 'full'})
        self.assertEqual(S.dialogue('codex', records), [('user', 'Add a gallery'), ('assistant', 'Done.')])
        self.assertIsNone(S.context('claude', []))

    def test_the_conversation_start_is_the_first_timestamp_in_the_head(self):
        records = [{'type': 'custom-title'}, ['not a record'], {'type': 'user', 'timestamp': '2026-10-10T08:30:00.123Z'},
                   {'type': 'assistant', 'timestamp': '2026-10-10T09:00:00.000Z'}]
        path = jsonl(self.dir / 's.jsonl', records)
        self.assertEqual(S.started(path), 1791621000)
        self.assertIsNone(S.started(path, size=30))  # Only the head is read.
        # A first message with a picture is one huge line: the next record answers.
        picture = {'type': 'user', 'timestamp': '2026-10-10T08:00:00.000Z', 'message': {'content': 'x' * (S.PIECE + 100)}}
        self.assertEqual(S.started(jsonl(self.dir / 'p.jsonl', [picture] + records)), 1791621000)
        self.assertIsNone(S.started(jsonl(self.dir / 'n.jsonl', [{'timestamp': 'yesterday'}, {'timestamp': 5}])))

    def test_only_the_tail_is_read_and_a_cut_line_is_skipped(self):
        path = jsonl(self.dir / 'big.jsonl', [{'type': 'user', 'message': {'role': 'user', 'content': 'x' * 500}}] * 50 + CLAUDE)
        records = S.tail_records(path, size=2000)
        self.assertLess(len(records), 20)
        self.assertEqual(S.context('claude', records)['tokens'], 91502)

    def test_the_newest_turns_fit_the_prompt(self):
        turns = [('user', 'n' * 600)] * 40
        kept = S.dialogue('claude', [{'type': 'user', 'message': {'role': 'user', 'content': f'{i} ' + 'n' * 700}} for i in range(40)])
        self.assertLessEqual(sum(len(t) for _, t in kept), S.SUMMARY_CHARS)
        self.assertTrue(kept[-1][1].startswith('39 '))
        self.assertIn('"ru"', S.summary_prompt(turns[:1], 'ru'))
        self.assertEqual(S.parse_summary('Sure: {"line":"Payments","text":"Webhook done."}'), ('Payments', 'Webhook done.'))
        with self.assertRaises(ValueError):
            S.parse_summary('no json')

    def test_a_summary_is_rewritten_once_when_the_conversation_grew_and_kept_when_the_model_fails(self):
        now, jobs, asked = [1000], [], []
        store = S.Summaries(self.dir / 'summaries', clock=lambda: now[0], start=jobs.append)
        model = {'label': 'Claude Haiku', 'complete': lambda prompt: asked.append(prompt) or '{"line":"Payments","text":"Done."}'}
        turns = [('user', 'Fix it')]
        first = store.get('sid', 'en', 10, turns, lambda: model)
        self.assertEqual((first['line'], first['updating']), ('', True))
        self.assertTrue(store.get('sid', 'en', 10, turns, lambda: model)['updating'])
        self.assertEqual(len(jobs), 1)  # One rewrite at a time.
        jobs.pop()()
        kept = store.get('sid', 'en', 10, turns, lambda: self.fail('unchanged: no model needed'))
        self.assertEqual((kept['line'], kept['text'], kept['model'], kept['updating']), ('Payments', 'Done.', 'Claude Haiku', False))
        self.assertEqual(oct(store.file('sid', 'en').stat().st_mode & 0o777), '0o600')
        self.assertFalse(store.get('sid', 'en', 20, turns, lambda: model)['updating'])  # Grew, but too soon.
        now[0] += S.SUMMARY_EVERY
        broken = {'label': 'x', 'complete': lambda prompt: 'nonsense'}
        store.get('sid', 'en', 20, turns, lambda: broken)
        jobs.pop()()
        after = store.get('sid', 'en', 20, turns, lambda: None)
        self.assertEqual((after['line'], after['error']), ('Payments', 'Модель не прислала пересказ'))
        self.assertFalse(store.get('other', 'en', 5, turns, lambda: None)['updating'])  # No model for this provider.
        self.assertEqual(len(asked), 1)


if __name__ == '__main__':
    unittest.main()
