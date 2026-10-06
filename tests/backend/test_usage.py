import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock

from support import ROOT
sys.path.insert(0, str(ROOT))
from integrations import usage as U


class UsageTests(unittest.TestCase):
    def test_codex_reads_its_login_and_sorts_windows(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            auth = Path(directory) / 'auth.json'
            auth.write_text(json.dumps({'tokens': {'access_token': 'token', 'account_id': 'acct'}}))
            http = Mock(return_value={'plan_type': 'pro', 'rate_limit': {
                'primary_window': {'limit_window_seconds': 604800, 'used_percent': 40, 'reset_at': 2},
                'secondary_window': {'limit_window_seconds': 18000, 'used_percent': 10, 'reset_at': 1}}})
            data = U.codex(http, str(auth))
        self.assertEqual(data['plan'], 'pro')
        self.assertEqual([w['label'] for w in data['windows']], ['5 ч', 'неделя'])
        self.assertEqual(http.call_args.args[1]['ChatGPT-Account-Id'], 'acct')

    def test_codex_with_an_api_key_has_no_subscription_limits(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            auth = Path(directory) / 'auth.json'
            auth.write_text('{"OPENAI_API_KEY": "sk"}')
            self.assertIn('error', U.codex(Mock(side_effect=AssertionError), str(auth)))

    def test_claude_never_calls_the_api_with_an_expired_token(self):
        expired = {'claudeAiOauth': {'accessToken': 'x', 'expiresAt': (time.time() - 60) * 1000}}
        self.assertIn('error', U.claude(expired, Mock(side_effect=AssertionError)))
        fresh = {'claudeAiOauth': {'accessToken': 'x', 'expiresAt': (time.time() + 3600) * 1000, 'subscriptionType': 'max'}}
        http = Mock(return_value={'seven_day': {'utilization': 30, 'resets_at': 'not a date'}})
        data = U.claude(fresh, http)
        self.assertEqual(data['windows'][0]['percent'], 30)
        self.assertIsNone(data['windows'][0]['resets_at'])  # An unexpected format loses only the reset time.

    def test_kimi_without_a_key_asks_for_one(self):
        self.assertIn('error', U.kimi(None, Mock(side_effect=AssertionError)))
