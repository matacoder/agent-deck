import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from unittest.mock import Mock

from support import ROOT, PanelCase
sys.path.insert(0, str(ROOT))
from integrations.limits import detect, reset_time
from integrations.quick_prompts import QuickPrompts
from integrations.schedule import Schedule

CLAUDE = "● Working on the tests\n\n  You've hit your session limit · resets 3pm (Europe/Moscow)\n\n> \n"
CODEX = ("■ You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), visit\n"
         "https://chatgpt.com/codex/settings/usage to purchase more credits or try again at 3:15 PM.\n\n› \n")


def at(hour, minute=0, day=10):
    return time.mktime((2026, 10, day, hour, minute, 0, 0, 0, -1))


class LimitNoticeTests(unittest.TestCase):
    def test_claude_and_codex_notices_give_the_reset_time(self):
        self.assertEqual(detect(CLAUDE, at(13))['at'], at(15))
        self.assertEqual(detect(CODEX, at(13))['at'], at(15, 15))
        self.assertEqual(detect("Usage limit reached\n", at(13)), {'notice': 'Usage limit reached', 'at': None})

    def test_dates_twenty_four_hour_clocks_and_midnight(self):
        now = at(13)
        self.assertEqual(reset_time('Oct 14, 9am', now), at(9, day=14))
        self.assertEqual(reset_time('Oct 14th, 2026 9:00 AM.', now), at(9, day=14))
        self.assertEqual(reset_time('15:30', now), at(15, 30))
        self.assertEqual(reset_time('12am', at(23)), at(0, day=11))
        self.assertEqual(reset_time('12:30pm', at(11)), at(12, 30))
        for unreadable in ('soon', '25:00', '13pm', ''):
            self.assertIsNone(reset_time(unreadable, now), unreadable)

    def test_a_time_far_ahead_has_already_passed(self):
        # Seen at 01:00, "resets 11pm" is last evening's window, not one 22 hours away.
        self.assertEqual(reset_time('11pm', at(1)), at(23, day=9))
        self.assertEqual(reset_time('3pm', at(15, 5)), at(15))

    def test_conversation_about_limits_and_spend_limits_are_not_notices(self):
        for screen in ("I think you've hit your session limit, it resets 3pm\n",
                       "You've hit your monthly spend limit.\n",
                       "You've hit your team's shared budget. /model to switch models.\n",
                       "Concurrent subagent limit reached. You can run 3\n"):
            self.assertIsNone(detect(screen, at(13)), screen)

    def test_only_the_bottom_of_the_screen_counts(self):
        self.assertIsNone(detect(CLAUDE + "line\n" * 60, at(13)))


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.now = at(13)
        self.sessions = [{'name': 'api', 'agent': 'claude', 'running': True, 'activity': 1},
                         {'name': 'sh', 'agent': 'shell', 'running': True, 'activity': 1}]
        self.screens, self.questions, self.sent, self.window = {}, set(), [], None
        self.schedule = self.make()

    def make(self):
        schedule = Schedule(self.directory, lambda: self.sessions, lambda name: self.screens.get(name, ''),
                            lambda name: name in self.questions, lambda name, text: self.sent.append((name, text)),
                            lambda agent: self.window, clock=lambda: self.now)
        schedule.start = lambda: None  # Tests call tick() themselves.
        return schedule

    def tick(self, seconds=0):
        self.now += seconds
        self.schedule.tick()

    def test_a_timed_prompt_is_sent_once_at_its_time_and_survives_a_restart(self):
        self.schedule.add('api', 'run the tests', 'time', self.now + 600)
        self.assertEqual(self.schedule.path.stat().st_mode & 0o777, 0o600)
        self.tick(300)
        self.assertEqual(self.sent, [])
        self.schedule = self.make()
        self.tick(300); self.tick(5)
        self.assertEqual(self.sent, [('api', 'run the tests')])
        self.assertEqual(self.schedule.status('api')['prompts'], [])
        self.assertEqual(json.loads(self.schedule.path.read_text())['prompts'], [])

    def test_a_prompt_for_a_free_session_waits_for_quiet_and_goes_one_at_a_time(self):
        self.schedule.add('api', 'first', 'idle')
        self.now += 1
        self.schedule.add('api', 'second', 'idle')
        self.tick()
        self.sessions[0]['activity'] = 2
        self.tick(5); self.tick(5)          # Output 5 s ago: still working.
        self.assertEqual(self.sent, [])
        self.tick(5)
        self.assertEqual(self.sent, [('api', 'first')])
        self.tick(5)
        self.assertEqual(len(self.sent), 1)  # The second waits for the first to finish.
        self.tick(5)
        self.assertEqual(self.sent, [('api', 'first'), ('api', 'second')])

    def test_nothing_is_typed_into_an_open_question_or_a_stopped_agent(self):
        self.schedule.add('api', 'later', 'time', self.now)
        self.questions.add('api')
        self.tick(5)
        self.assertEqual(self.sent, [])
        self.questions.clear()
        self.sessions[0]['running'] = False
        self.tick(5)
        self.assertEqual(self.sent, [])
        self.sessions[0]['running'] = True
        self.tick(5)
        self.assertEqual(self.sent, [('api', 'later')])

    def test_auto_resume_continues_once_after_the_limit_resets(self):
        self.schedule.set_auto('api', True)
        self.screens['api'] = CLAUDE
        self.tick(); self.tick(10)
        self.assertEqual(self.schedule.status('api')['limit']['at'], at(15))
        self.assertEqual(self.sent, [])
        self.now = at(15, 0) + 30
        self.tick()
        self.assertEqual(self.sent, [])     # A minute of margin after the named time.
        self.tick(40)
        self.assertEqual(self.sent, [('api', 'continue')])
        self.tick(20); self.tick(20)
        self.assertEqual(len(self.sent), 1)  # The notice is still on the screen: never repeated.
        self.screens['api'] = '> \n'
        self.tick(20)
        self.assertIsNone(self.schedule.status('api')['limit'])

    def test_auto_resume_is_not_repeated_the_next_day_or_after_a_panel_restart(self):
        self.schedule.set_auto('api', True)
        self.screens['api'] = CLAUDE
        self.tick(); self.tick(10)
        self.now = at(15, 2)
        self.tick()
        self.assertEqual(self.sent, [('api', 'continue')])
        for day in (1, 2):                  # "resets 3pm" reads as that day's 3pm again.
            self.now = at(15, 2) + day * 86400
            self.tick(); self.tick(10); self.tick(10)
        self.schedule = self.make()         # The panel restarted with the notice still on the screen.
        self.tick(); self.tick(10); self.tick(10)
        self.assertEqual(len(self.sent), 1)
        self.screens['api'] = '> \n'
        self.tick(10)
        self.screens['api'] = CLAUDE        # The same words again after the screen moved on: a new limit.
        self.now = at(15, 2) + 3 * 86400
        self.tick(); self.tick(10); self.tick(10)
        self.assertEqual(len(self.sent), 2)

    def test_a_prompt_for_the_limit_reset_replaces_the_plain_continue(self):
        self.schedule.set_auto('api', True)
        self.schedule.add('api', 'finish the migration', 'limit')
        self.screens['api'] = CLAUDE
        self.tick()
        self.now = at(15, 2)
        self.tick()
        self.assertEqual(self.sent, [('api', 'finish the migration')])

    def test_a_notice_without_a_time_uses_the_providers_counters_and_keeps_that_time(self):
        self.schedule.set_auto('api', True)
        self.screens['api'] = 'Usage limit reached\n'
        self.tick(); self.tick(10)
        self.assertEqual(self.sent, [])     # No time known: nothing is guessed.
        self.window = at(14)
        self.tick(10)
        self.window = None                  # After the reset the counters no longer name the window.
        self.now = at(14, 2)
        self.tick()
        self.assertEqual(self.sent, [('api', 'continue')])

    def test_working_sessions_are_not_checked_for_limits(self):
        self.schedule.set_auto('api', True)
        self.screens['api'] = CLAUDE
        self.now = at(16)
        self.tick()
        for activity in (2, 3, 4):
            self.sessions[0]['activity'] = activity
            self.tick(5)
        self.assertEqual(self.sent, [])

    def test_a_failed_send_is_reported_and_not_retried(self):
        def failing(name, text):
            raise RuntimeError('tmux gone')
        self.schedule.send = failing
        self.schedule.add('api', 'later', 'time', self.now)
        self.tick(5)
        self.assertEqual(self.schedule.status('api')['error'], 'RuntimeError')
        self.assertEqual(self.schedule.status('api')['prompts'], [])

    def test_closed_sessions_lose_their_prompts_after_ten_minutes(self):
        self.schedule.add('api', 'later', 'idle')
        self.schedule.set_auto('api', True)
        self.sessions = []
        self.tick(); self.tick(300)
        self.assertEqual(len(self.schedule.status('api')['prompts']), 1)  # A restart is not a close.
        self.tick(301)
        self.assertEqual(self.schedule.status('api'), {'prompts': [], 'auto_resume': False, 'limit': None, 'error': ''})

    def test_requests_are_validated(self):
        for arguments in (('nope', 'x', 'idle'), ('api', '', 'idle'), ('api', 'x' * 20001, 'idle'), ('api', 'x', 'never'),
                          ('api', 'x', 'time'), ('api', 'x', 'time', self.now - 3600), ('api', 'x', 'time', self.now + 31 * 86400),
                          ('api', 'x', 'time', True), ('sh', 'x', 'limit')):
            with self.assertRaises(ValueError, msg=arguments):
                self.schedule.add(*arguments)
        with self.assertRaises(ValueError):
            self.schedule.set_auto('sh', True)
        with self.assertRaises(ValueError):
            self.schedule.set_auto('api', 'yes')
        for _ in range(20):
            self.schedule.add('api', 'x', 'idle')
        with self.assertRaises(ValueError):
            self.schedule.add('api', 'x', 'idle')
        first = self.schedule.status('api')['prompts'][0]['id']
        self.schedule.remove(first)
        self.assertEqual(len(self.schedule.status('api')['prompts']), 19)

    def test_a_damaged_file_starts_empty(self):
        self.schedule.path.write_text('{"prompts": [{"id": 1}, "x"], "auto_resume": [3, "api"]}')
        schedule = self.make()
        self.assertEqual(schedule.status('api'), {'prompts': [], 'auto_resume': True, 'limit': None, 'error': ''})


class QuickPromptTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        self.prompts = QuickPrompts(Path(tmp.name))

    def test_saved_list_is_private_and_labels_default_to_the_text(self):
        self.assertEqual(self.prompts.list(), [])
        saved = self.prompts.save([{'label': '  Tests  ', 'text': 'run the tests'}, {'text': 'commit\nand push ' + 'x' * 40}])
        self.assertEqual(saved[0], {'label': 'Tests', 'text': 'run the tests'})
        self.assertEqual(saved[1]['label'], ('commit and push ' + 'x' * 40)[:30])
        self.assertEqual(self.prompts.list(), saved)
        self.assertEqual(self.prompts.path.stat().st_mode & 0o777, 0o600)

    def test_invalid_lists_are_rejected_and_a_damaged_file_reads_empty(self):
        for bad in (None, [{'text': ''}], [{'text': 'x' * 4001}], ['x'], [{'text': 'x', 'label': 3}], [{'text': 'x'}] * 25):
            with self.assertRaises(ValueError, msg=str(bad)[:40]):
                self.prompts.save(bad)
        self.prompts.path.write_text('not json')
        self.assertEqual(self.prompts.list(), [])


class PanelWiringTests(PanelCase):
    def sessions(self):
        return [{'name': 'api', 'agent': 'claude', 'running': True, 'activity': 1, 'created': 50}]

    def test_schedule_actions_use_the_session_list_and_closing_a_session_drops_its_prompts(self):
        self.panel.list_sessions = self.sessions
        self.panel.schedule_service().start = lambda: None
        status = self.panel.ACTIONS['schedule_add']({'name': 'api', 'text': 'later', 'trigger': 'idle'})
        self.assertEqual([p['text'] for p in status['prompts']], ['later'])
        self.assertTrue(self.panel.ACTIONS['auto_resume']({'name': 'api', 'enabled': True})['auto_resume'])
        stored = self.home / '.config/cc-panel/integrations/schedule.json'
        self.assertEqual(stored.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            self.panel.ACTIONS['schedule_add']({'name': '../x', 'text': 'later', 'trigger': 'idle'})
        self.panel.session_exists = Mock(return_value=False)
        self.panel.action_kill({'name': 'api'})
        self.assertEqual(self.panel.schedule_service().status('api')['prompts'], [])
        self.assertFalse(self.panel.schedule_service().status('api')['auto_resume'])

    def test_a_finished_session_is_summarized_now_and_an_old_or_failed_summary_is_not_used(self):
        answers, calls, pauses = [], [], []
        def info(name, language, fresh):
            calls.append((name, language, fresh))
            return {'summary': answers.pop(0)}
        self.panel.session_info = info
        answers += [{'line': 'old', 'updating': True}, {'line': 'Payments fixed', 'text': 'Done.', 'updating': False}]
        self.assertEqual(self.panel.finished_summary('', 'api', 'ru', pause=pauses.append), {'line': 'Payments fixed', 'text': 'Done.', 'title': '', 'done': ''})
        self.assertEqual((calls, pauses), ([('api', 'ru', True), ('api', 'ru', False)], [2]))
        answers += [{'line': 'old', 'error': 'TimeoutExpired', 'updating': False}]
        self.assertIsNone(self.panel.finished_summary('', 'api', 'ru'))
        answers += [{'line': 'old', 'updating': True}]
        self.assertIsNone(self.panel.finished_summary('', 'api', 'ru', wait=0))  # The model took too long.
        self.panel.session_info = Mock(return_value={'supported': False})
        self.assertIsNone(self.panel.finished_summary('', 'api', 'ru'))
        self.panel.gateway.session_info = Mock(return_value={'summary': {'line': 'Remote', 'text': '', 'updating': False}})
        self.assertEqual(self.panel.finished_summary('a' * 24, 'api', 'ru')['line'], 'Remote')
        self.panel.gateway.session_info.assert_called_once_with('a' * 24, 'api', 'ru', True)
        self.panel.gateway.session_info = Mock(side_effect=ValueError('offline'))
        self.assertIsNone(self.panel.finished_summary('a' * 24, 'api', 'ru'))

    def test_quick_prompts_are_saved_through_the_action(self):
        saved = self.panel.ACTIONS['quick_prompts']({'prompts': [{'text': 'run the tests'}]})
        self.assertEqual(saved, {'prompts': [{'label': 'run the tests', 'text': 'run the tests'}]})
        self.assertEqual(self.panel.quick_prompts().list(), saved['prompts'])

    def test_a_telegram_prompt_reaches_only_the_same_session_without_an_open_question(self):
        self.panel.list_sessions = self.sessions
        self.panel.shared_questions = lambda: []
        self.panel.action_send = Mock()
        self.panel.telegram_prompt('', 'api', 50, 'continue')
        self.panel.action_send.assert_called_once_with({'name': 'api', 'text': 'continue'})
        for name, created in (('api', 51), ('gone', 50)):
            with self.assertRaises(ValueError):  # Closed, or another session that took the name.
                self.panel.telegram_prompt('', name, created, 'continue')
        self.panel.shared_questions = lambda: [Mock(deck='', session='api')]
        with self.assertRaises(ValueError):
            self.panel.telegram_prompt('', 'api', 50, 'continue')
        self.assertEqual(self.panel.action_send.call_count, 1)

    def test_a_telegram_prompt_for_a_connected_computer_goes_through_the_gateway(self):
        deck = 'a' * 24
        self.panel.shared_questions = lambda: []
        self.panel.gateway.sessions = lambda: [{'name': 'ml', 'deck': deck, 'created': 9}]
        self.panel.gateway.send = Mock()
        self.panel.telegram_prompt(deck, 'ml', 9, 'continue')
        self.panel.gateway.send.assert_called_once_with(deck, 'ml', 'continue')

    def test_a_full_limit_window_names_the_reset_for_a_notice_without_a_time(self):
        self.panel.usage = lambda: {'claude': {'windows': [{'percent': 100, 'resets_at': 900}, {'percent': 100, 'resets_at': 500},
                                                           {'percent': 40, 'resets_at': 100}]}, 'kimi': {'error': 'x'}}
        self.assertEqual(self.panel.limit_window_reset('claude'), 500)
        self.assertIsNone(self.panel.limit_window_reset('claude-kimi'))
        self.assertIsNone(self.panel.limit_window_reset('shell'))


if __name__ == '__main__':
    unittest.main()
