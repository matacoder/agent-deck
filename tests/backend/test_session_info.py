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

    def test_claude_codes_own_notices_do_not_reset_the_context(self):
        notice = {'type': 'assistant', 'message': {'role': 'assistant', 'model': '<synthetic>', 'content': [{'type': 'text', 'text': 'API Error'}],
                                                   'usage': {'input_tokens': 0, 'output_tokens': 0}}}
        self.assertEqual(S.context('claude', CLAUDE + [notice])['tokens'], 91502)

    def test_a_shortened_conversation_shows_its_new_size_before_the_next_answer(self):
        boundary = {'type': 'system', 'subtype': 'compact_boundary', 'isSidechain': False,
                    'compactMetadata': {'trigger': 'manual', 'preTokens': 91502, 'postTokens': 12022}}
        summary = {'type': 'user', 'isCompactSummary': True, 'message': {'role': 'user', 'content': 'Summary'}}
        self.assertEqual(S.context('claude', CLAUDE + [boundary, summary]), {'tokens': 12022, 'window': None, 'level': 'fine'})
        self.assertEqual(S.context('claude', [boundary, summary] + CLAUDE)['tokens'], 91502)  # An answer after it counts again.
        del boundary['compactMetadata']['postTokens']
        self.assertIsNone(S.context('claude', CLAUDE + [boundary, summary]))  # Unknown, never the size from before.

    def test_the_conversation_for_reading_is_longer_than_the_one_for_a_summary(self):
        long = {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'A' * 3000}]}}
        retold = {'type': 'user', 'isCompactSummary': True, 'message': {'role': 'user', 'content': 'This session is being continued'}}
        path = jsonl(self.dir / 'talk.jsonl', CLAUDE + [retold, long])
        turns = S.conversation('claude', path)
        # No tool output, no subagent, no command echo, no retelling; a long answer is whole.
        self.assertEqual([(t['role'], len(t['text'])) for t in turns], [('user', 23), ('assistant', 14), ('assistant', 3000)])
        # For a summary the turns are cut short; the latest one, which says what just happened, less so.
        self.assertEqual(len(S.dialogue('claude', S.tail_records(path))[-1][1]), S.TURN_CHARS * S.LAST_TURN)
        self.assertEqual(len(S.dialogue('claude', S.tail_records(path) + CLAUDE[1:2])[-2][1]), S.TURN_CHARS)

    def test_a_last_line_bigger_than_the_tail_is_still_read(self):
        picture = {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'image', 'data': 'x' * 5000}]}}
        path = jsonl(self.dir / 'big.jsonl', CLAUDE[:3] + [picture])
        records = S.tail_records(path, size=1000)
        self.assertEqual(records[-1], picture)  # A longer tail was read, not nothing.
        self.assertEqual(S.context('claude', records)['tokens'], 91502)
        self.assertEqual(S.tail_records(path, size=1000, most=1000), [])  # Bounded: a huge line is given up on.

    def test_the_newest_turns_fit_the_prompt(self):
        turns = [('user', 'n' * 600)] * 40
        kept = S.dialogue('claude', [{'type': 'user', 'message': {'role': 'user', 'content': f'{i} ' + 'n' * 700}} for i in range(40)])
        self.assertLessEqual(sum(len(t) for _, t in kept), S.SUMMARY_CHARS)
        self.assertTrue(kept[-1][1].startswith('39 '))
        self.assertIn('"ru"', S.summary_prompt(turns[:1], 'ru'))
        self.assertEqual(S.parse_summary('Sure: {"line":"Payments","text":"Webhook done."}'), ('Payments', 'Webhook done.'))
        with self.assertRaises(ValueError):
            S.parse_summary('no json')

    def test_the_title_is_a_short_latin_name_and_the_model_is_asked_to_keep_it(self):
        self.assertEqual(S.extras_of('{"line":"x","text":"y","title":" Fix Payment_webhook ","done":"Tests\\n pass."}'), ('fix-payment-webhook', 'Tests pass.'))
        for bad in ('Платежи', 'a-b-c-d-e', 'x' * 40, 'rm -rf; echo', '', 5):
            self.assertEqual(S.clean_title(bad), '')
        self.assertEqual((S.extras_of('no json'), S.extras_of('{"done":5}')), (('', ''), ('', '')))
        self.assertNotIn('title so far', S.summary_prompt([('user', 'hi')], 'ru'))
        self.assertIn('"fix-payments": repeat it unless', S.summary_prompt([('user', 'hi')], 'ru', 'fix-payments'))

    def test_a_rewrite_keeps_the_title_when_the_model_sends_none(self):
        jobs, answers = [], ['{"line":"a","text":"b","title":"fix-payments","done":"Webhook fixed."}', '{"line":"c","text":"d","title":"Не то"}']
        prompts = []
        model = {'label': 'm', 'complete': lambda prompt: prompts.append(prompt) or answers.pop(0)}
        store = S.Summaries(self.dir / 's', clock=lambda: 1000, start=jobs.append)
        store.get('sid', 'ru', 10, [('user', 'hi')], lambda: model, fresh=True); jobs.pop()()
        self.assertEqual([store.get('sid', 'ru', 10, [], lambda: model)[key] for key in ('title', 'done')], ['fix-payments', 'Webhook fixed.'])
        store.get('sid', 'ru', 20, [('user', 'hi')], lambda: model, fresh=True); jobs.pop()()
        self.assertEqual((store.get('sid', 'ru', 20, [], lambda: model)['title'], 'fix-payments' in prompts[1]), ('fix-payments', True))
        self.assertEqual(store.get('sid', 'ru', 20, [], lambda: model)['done'], '')  # What was done then is not what was done now.

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
        # A notification about finished work does not wait for the pause.
        self.assertTrue(store.get('sid', 'en', 15, turns, lambda: model, fresh=True)['updating'])
        jobs.pop()()
        now[0] += S.SUMMARY_EVERY
        broken = {'label': 'x', 'complete': lambda prompt: 'nonsense'}
        store.get('sid', 'en', 20, turns, lambda: broken)
        jobs.pop()()
        after = store.get('sid', 'en', 20, turns, lambda: None)
        self.assertEqual((after['line'], after['error']), ('Payments', 'Модель не прислала пересказ'))
        self.assertFalse(store.get('other', 'en', 5, turns, lambda: None)['updating'])  # No model for this provider.
        self.assertEqual(len(asked), 2)

    def test_a_provider_that_cannot_summarize_is_asked_again_only_after_a_while(self):
        now, picks = [1000], []
        store = S.Summaries(self.dir / 'summaries', clock=lambda: now[0], start=lambda job: self.fail('no model'))
        pick = lambda: picks.append(store.lock.locked())
        for _ in range(3):
            self.assertFalse(store.get('sid', 'en', 10, [('user', 'Fix it')], pick)['updating'])
        self.assertEqual(picks, [False])  # Once, and not under the lock every session's summary waits for.
        now[0] += S.SUMMARY_EVERY
        store.get('sid', 'en', 10, [('user', 'Fix it')], pick)
        self.assertEqual(len(picks), 2)


if __name__ == '__main__':
    unittest.main()
