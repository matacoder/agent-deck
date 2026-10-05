import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from support import PanelCase, ROOT
sys.path.insert(0, str(ROOT))
from integrations.questions import parse_question, transcript_questions, transcript_model, matches_screen, QuestionNotReady
from integrations.store import Store
from integrations.telegram import API, Telegram, TelegramError

TOKEN = '1234567890:' + 'test_token_only_' * 3
SCREEN = '''Question 1/2 (2 unanswered)
Which installation should we use?

› 1. Homebrew (Recommended)
  2. Manual
  3. Other

tab to add notes · enter to submit answer · ←/→ to navigate questions
'''


def question(screen=SCREEN, instance='%1:123:conversation-1'):
    return parse_question('demo', 'codex', instance, screen)


class QuestionTests(unittest.TestCase):
    def test_actual_codex_async_form_with_enter_submit_footer(self):
        screen='''• Working (2m • esc to interrupt)
• Queued follow-up inputs

Проверка ответа Telegram:
какую плотность интерфейса выбрать?

› 1. Компактно
  2. Крупнее
  3. Other

enter submit   ctrl+] skip   shift+→ main prompt
'''
        q=question(screen)
        self.assertIsNotNone(q)
        self.assertEqual(q.title,'Проверка ответа Telegram:\nкакую плотность интерфейса выбрать?')
        self.assertEqual(q.options,('Компактно','Крупнее','Other'))
        from dataclasses import replace
        self.assertTrue(matches_screen(replace(q,title=q.title.replace('\n',' '),request_id='async:0'),q))
    def test_cursor_is_not_identity_but_pane_conversation_and_question_are(self):
        q = question()
        moved = question(SCREEN.replace('› 1.', '  1.').replace('  2.', '› 2.'))
        self.assertEqual(q.fingerprint, moved.fingerprint)
        self.assertEqual(moved.selected, 1)
        self.assertNotEqual(q.fingerprint, question(instance='%2:456:new-conversation').fingerprint)
        self.assertNotEqual(q.fingerprint, question(SCREEN.replace('1/2', '2/2')).fingerprint)

    def test_rejects_scrollback_plain_lists_partial_menus_and_notes_focus(self):
        for screen in ('ordinary output\n1. Yes\n2. No', SCREEN + '\n› New command',
                       SCREEN.replace('  2.', '  4.'), SCREEN.replace('› 1.', '  1.'),
                       SCREEN.replace('tab to add notes', 'tab or esc to clear notes')):
            with self.subTest(screen=screen):
                self.assertIsNone(question(screen))
        self.assertIsNone(parse_question('demo', 'shell', '%1:123', SCREEN))

    def test_claude_and_kimi_question_menus(self):
        for agent in ('claude', 'claude-kimi', 'kimi'):
            screen = 'Do you want to proceed?\n❯ 1. Yes\n  2. No\nEnter to select · Esc to cancel\n'
            self.assertEqual(parse_question('demo', agent, '%1:123', screen).options, ('Yes', 'No'))
        screen = 'Choose a model\n❯ 1. Fast\n  2. Slow\nEnter to select'
        # Generic settings menu without a question is not a notification.
        self.assertIsNone(parse_question('demo', 'claude', '%1:123', screen.replace('Choose', 'Model:')))

    def transcript(self, records, agent='codex'):
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            path = Path(directory)/'session.jsonl'
            path.write_text('\n'.join(json.dumps(r) for r in records) + '\npartial unfinished record')
            return transcript_questions(path,'demo',agent,'%1:123:conversation-1')

    def test_hidden_codex_async_question_survives_acceptance_but_not_direct_reply(self):
        call={'type':'response_item','payload':{'type':'function_call','name':'request_user_input_async','call_id':'call-1',
              'arguments':json.dumps({'questions':[{'title':'Which installation should we use?', 'options':['Homebrew (Recommended)','Manual']}]})}}
        accepted={'type':'response_item','payload':{'type':'function_call_output','call_id':'call-1','output':'{"accepted":true}'}}
        pending=self.transcript([call,accepted])
        self.assertEqual(len(pending),1)
        self.assertEqual(pending[0].request_id,'call-1:0')
        reply={'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'Manual'}]}}
        self.assertEqual(self.transcript([call,accepted,reply]),[])
        closed={**accepted,'payload':{**accepted['payload'],'output':'{"answers":{"choice":"Manual"}}'}}
        self.assertEqual(self.transcript([call,closed]),[])

    def test_claude_structured_questions_end_on_tool_result_and_secret_questions_are_skipped(self):
        call={'type':'assistant','message':{'content':[{'type':'tool_use','name':'AskUserQuestion','id':'tool-1',
              'input':{'questions':[{'question':'Pick a route?', 'options':[{'label':'One','description':'A'},{'label':'Two','description':'B'}]}]}}]}}
        self.assertEqual(self.transcript([call], 'claude')[0].options,('One','Two'))
        result={'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'tool-1','content':'One'}]}}
        self.assertEqual(self.transcript([call,result],'claude'),[])
        call['message']['content'][0]['input']['questions'][0]['multiSelect']=True
        self.assertEqual(self.transcript([call],'claude'),[])

    def test_transcript_model_follows_latest_turn_and_ignores_synthetic_and_other_records(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            path=Path(directory)/'session.jsonl'
            def model(records,agent):
                path.write_text('\n'.join(json.dumps(r) for r in records)+'\npartial unfinished record')
                return transcript_model(path,agent)
            opus={'type':'assistant','message':{'model':'claude-opus-5-5','content':[]}}
            self.assertEqual(model([{'type':'assistant','message':{'model':'claude-sonnet-5-5'}},opus,
                                    {'type':'assistant','message':{'model':'<synthetic>'}},{'type':'user','message':{'model':'spoofed'}}],'claude'),'claude-opus-5-5')
            codex=[{'type':'turn_context','payload':{'model':'gpt-6.1'}},{'type':'turn_context','payload':{'model':'gpt-6.1-sol'}},
                   {'type':'response_item','payload':{'model':'other'}}]
            self.assertEqual(model(codex,'codex'),'gpt-6.1-sol')
            self.assertIsNone(model([opus],'codex'))
            self.assertIsNone(model([{'type':'assistant','message':{'model':'x'*121}}],'claude'))

    def test_structured_answer_matches_title_pane_options_and_progress(self):
        q=question()
        self.assertTrue(matches_screen(q,q))
        self.assertFalse(matches_screen(q,question(instance='%2:456:other')))
        self.assertFalse(matches_screen(q,question(SCREEN.replace('1/2','2/2'))))


class FakeAPI:
    def __init__(self):
        self.calls = []
        self.message_id = 0

    def call(self, token, method, **data):
        self.calls.append((method, data))
        if method == 'getMe': return {'is_bot': True, 'username': 'deck_test_bot'}
        if method == 'getWebhookInfo': return {'url': ''}
        if method == 'sendMessage':
            self.message_id += 1
            return {'message_id': self.message_id}
        return True


class TelegramTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.api = FakeAPI()
        self.questions = [question()]
        self.answer = Mock()
        self.service = Telegram(self.directory, lambda: self.questions, self.answer, self.api)
        self.service.start = Mock()  # Tests drive workers deterministically; never contact Telegram.
        self.service.save({'token': TOKEN})

    def pair(self, user=100):
        status = self.service.pair()
        code = status['pair_url'].split('?start=deck_', 1)[1]
        self.service.handle({'message': {'text': '/start deck_' + code,
            'chat': {'id': user, 'type': 'private'}, 'from': {'id': user, 'username': 'tester'}}})

    def callback(self, row, user=100, chat=100, index=1, message=None):
        return {'callback_query': {'id': 'callback', 'from': {'id': user},
            'message': {'message_id': message if message is not None else row['message_id'],
                        'chat': {'id': chat, 'type': 'private'}},
            'data': f"q:{row['id']}:{index}"}}

    def test_pair_code_private_owner_and_secret_redaction(self):
        status = self.service.pair()
        self.assertNotIn(TOKEN, json.dumps(status))
        self.assertNotIn('token', status)
        self.service.handle({'message': {'text': '/start deck_wrong',
            'chat': {'id': 100, 'type': 'private'}, 'from': {'id': 100}}})
        self.assertFalse(self.service.status()['paired'])
        self.pair()
        self.assertTrue(self.service.status()['paired'])
        self.assertEqual(self.service.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.service.database().path.stat().st_mode & 0o777, 0o600)
        self.assertIsNone(self.service.status()['pair_url'])

    def test_delivery_buttons_and_restart_deduplication(self):
        self.pair()
        self.service.deliver()
        self.service.deliver()
        sent = [data for method, data in self.api.calls if method == 'sendMessage' and 'reply_markup' in data]
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(sent[0]['reply_markup']['inline_keyboard']), 2)  # Other needs typing.
        restarted = Telegram(self.directory, lambda: self.questions, self.answer, self.api)
        restarted.deliver()
        self.assertEqual(len([m for m, d in self.api.calls if m == 'sendMessage' and 'reply_markup' in d]), 1)

    def test_callbacks_are_bound_to_owner_chat_message_and_only_run_once(self):
        self.pair(); self.service.deliver()
        row = self.service.database().pending()[0]
        for callback in (self.callback(row, user=999), self.callback(row, chat=999), self.callback(row, message=999)):
            self.service.handle(callback)
        self.answer.assert_not_called()
        self.service.handle(self.callback(row))
        self.service.handle(self.callback(row))
        self.answer.assert_called_once()
        self.assertEqual(self.answer.call_args.args[1], 1)
        self.assertEqual(self.service.database().get(row['id'])['status'], 'answered')

    def test_stale_question_fails_closed_and_does_not_retry(self):
        self.pair(); self.service.deliver()
        row = self.service.database().pending()[0]
        self.answer.side_effect = ValueError('Этот вопрос уже закрыт')
        self.service.handle(self.callback(row))
        self.service.handle(self.callback(row))
        self.answer.assert_called_once()
        self.assertIn('закрыт', [d['text'] for m, d in self.api.calls if m == 'answerCallbackQuery'][0])

    def test_temporary_open_failure_keeps_buttons_for_a_user_retry(self):
        self.pair();self.service.deliver()
        row=self.service.database().pending()[0]
        self.answer.side_effect=QuestionNotReady('Сначала ответьте на предыдущий вопрос')
        self.service.handle(self.callback(row))
        self.assertEqual(self.service.database().get(row['id'])['status'],'sent')
        self.assertFalse(any(m=='editMessageReplyMarkup' for m,d in self.api.calls))
        self.answer.side_effect=None
        self.service.handle(self.callback(row))
        self.assertEqual(self.service.database().get(row['id'])['status'],'answered')

    def test_crash_during_input_is_not_replayed(self):
        self.pair(); self.service.deliver()
        row = self.service.database().pending()[0]
        self.assertTrue(self.service.database().claim(row['id']))
        restarted = Telegram(self.directory, lambda: self.questions, self.answer, self.api)
        restarted.handle(self.callback(row))
        self.answer.assert_not_called()
        self.assertEqual(restarted.database().get(row['id'])['status'], 'uncertain')

    def test_disabled_integration_does_not_read_or_send_questions(self):
        self.pair()
        self.service.save({'enabled': False})
        self.service.scan = Mock(side_effect=AssertionError('must not inspect panes'))
        self.service.deliver()
        self.service.scan.assert_not_called()
        self.assertFalse(self.service.status()['enabled'])

    def test_transport_never_exposes_token_in_network_error(self):
        with patch('urllib.request.urlopen', side_effect=OSError('https://api.telegram.org/bot' + TOKEN)):
            with self.assertRaises(TelegramError) as caught:
                API().call(TOKEN, 'getMe')
        self.assertNotIn(TOKEN, str(caught.exception))

    def test_expired_question_is_retired_and_new_occurrence_can_be_sent(self):
        self.pair(); self.service.deliver()
        first = self.service.database().pending()[0]
        self.questions = []
        self.service.seen.clear()
        self.service.deliver()
        self.questions = [question()]
        self.service.deliver()
        second = self.service.database().pending()[0]
        self.assertNotEqual(first['id'], second['id'])


    def test_answered_prompt_lingering_on_screen_is_not_resent(self):
        self.pair(); self.service.deliver()
        row = self.service.database().pending()[0]
        self.service.handle(self.callback(row))
        for _ in range(3):
            self.service.deliver()  # The answered menu is still visible for a few scans.
        sent = [d for m, d in self.api.calls if m == 'sendMessage' and 'reply_markup' in d]
        self.assertEqual(len(sent), 1)

    def deliver_at(self, *moments):
        for moment in moments:
            with patch('integrations.telegram.time.monotonic', return_value=moment):
                self.service.deliver()

    def test_answered_prompt_missing_for_one_scan_is_not_resent(self):
        self.pair(); self.deliver_at(100)
        row = self.service.database().pending()[0]
        self.service.handle(self.callback(row))
        self.questions = []
        self.deliver_at(102)  # One flickering scan while the answered menu still lingers.
        self.questions = [question()]
        self.deliver_at(104)
        sent = [d for m, d in self.api.calls if m == 'sendMessage' and 'reply_markup' in d]
        self.assertEqual(len(sent), 1)

    def test_identical_prompt_reappearing_after_answer_is_sent_again(self):
        self.pair(); self.deliver_at(100)
        row = self.service.database().pending()[0]
        self.service.handle(self.callback(row))
        self.questions = []
        self.deliver_at(102, 104)  # Gone for two scans, still inside the 6 s grace window.
        self.questions = [question()]
        self.deliver_at(106)
        sent = [d for m, d in self.api.calls if m == 'sendMessage' and 'reply_markup' in d]
        self.assertEqual(len(sent), 2)
        self.assertNotEqual(self.service.database().pending()[0]['id'], row['id'])

    def test_failed_callback_acknowledgement_does_not_wedge_polling(self):
        self.pair(); self.service.deliver()
        row = self.service.database().pending()[0]
        start = self.service.database().offset()
        updates = [[{'update_id': start, **self.callback(row)},
                    {'update_id': start + 1, 'callback_query': {'id': 'other', 'from': {'id': 100},
                     'message': {'message_id': 999, 'chat': {'id': 100, 'type': 'private'}}, 'data': 'x'}}]]
        original = self.api.call

        def call(token, method, **data):
            if method == 'getUpdates':
                if not updates:
                    self.service.stop.set()
                    return []
                return updates.pop(0)
            if method == 'answerCallbackQuery' and data['callback_query_id'] == 'callback':
                original(token, method, **data)
                raise TelegramError('Telegram: запрос не выполнен')
            return original(token, method, **data)
        self.api.call = call
        self.service.poll_loop()
        self.assertEqual(self.service.database().offset(), start + 2)
        self.answer.assert_called_once()
        acknowledged = [d['callback_query_id'] for m, d in self.api.calls if m == 'answerCallbackQuery']
        self.assertEqual(acknowledged, ['callback', 'other'])
        self.assertEqual(self.service.database().get(row['id'])['status'], 'answered')

    def test_failed_keyboard_edit_still_acknowledges_callback(self):
        self.pair(); self.service.deliver()
        row = self.service.database().pending()[0]
        original = self.api.call

        def call(token, method, **data):
            if method == 'editMessageReplyMarkup':
                raise TelegramError('Telegram: запрос не выполнен')
            return original(token, method, **data)
        self.api.call = call
        self.assertEqual(self.service.handle(self.callback(row)), 'Telegram: запрос не выполнен')
        self.assertTrue(any(m == 'answerCallbackQuery' for m, d in self.api.calls))
        self.assertEqual(self.service.database().get(row['id'])['status'], 'answered')

    def test_corrupt_settings_file_does_not_block_service_or_clear(self):
        for content in ('{broken', '[]'):
            with self.subTest(content=content):
                self.service.path.write_text(content)
                service = Telegram(self.directory, lambda: [], self.answer, self.api)
                self.assertFalse(service.status()['configured'])
                self.assertIn(str(service.path), service.status()['error'])
                service.save({'clear': True})
                self.assertEqual(json.loads(service.path.read_text()), {})
                self.assertEqual(service.status()['error'], '')

class QuestionInputTests(PanelCase):
    def test_moves_cursor_validates_question_then_confirms(self):
        q = question()
        moved = question(SCREEN.replace('› 1.', '  1.').replace('  2.', '› 2.'))
        self.panel.current_question = Mock(side_effect=[q, moved])
        self.panel.tmux = Mock(return_value='')
        with patch.object(self.panel.time, 'sleep'):
            self.panel.answer_question(q, 1)
        self.assertEqual([c.args[-1] for c in self.panel.tmux.call_args_list], ['Down', 'Enter'])

    def test_changed_session_or_question_never_receives_enter(self):
        q = question()
        self.panel.current_question = Mock(return_value=question(instance='%2:456:other'))
        with self.assertRaises(ValueError): self.panel.answer_question(q, 1)
        self.panel.tmux.assert_not_called()

    def test_cursor_change_followed_by_new_question_never_confirms(self):
        q = question()
        self.panel.current_question = Mock(side_effect=[q, None])
        self.panel.tmux = Mock(return_value='')
        with patch.object(self.panel.time, 'sleep'), self.assertRaises(ValueError):
            self.panel.answer_question(q, 1)
        self.assertEqual([c.args[-1] for c in self.panel.tmux.call_args_list], ['Down'])

    def test_hidden_question_is_opened_and_validated_before_answer(self):
        from dataclasses import replace
        visible=question()
        structured=replace(visible,request_id='call-1:0')
        moved=question(SCREEN.replace('› 1.','  1.').replace('  2.','› 2.'))
        self.panel.pending_questions=Mock(return_value=[structured])
        self.panel.current_question=Mock(side_effect=[None,visible,moved])
        self.panel.tmux=Mock(return_value='')
        with patch.object(self.panel.time,'sleep'):
            self.panel.answer_question(structured,1)
        self.assertEqual([c.args[-1] for c in self.panel.tmux.call_args_list],['S-Left','Down','Enter'])

    def test_no_longer_pending_question_does_not_open_overlay(self):
        from dataclasses import replace
        q=replace(question(),request_id='call-1:0')
        self.panel.pending_questions=Mock(return_value=[])
        self.panel.current_question=Mock(return_value=None)
        with self.assertRaises(ValueError):self.panel.answer_question(q,0)
        self.panel.tmux.assert_not_called()
