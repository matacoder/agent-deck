import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT
sys.path.insert(0, str(ROOT))
from integrations import feature_groups as F


def repo(test, commits):
    """commits: [(author, subject, file, unix time)] oldest first."""
    tmp = tempfile.TemporaryDirectory(dir='/tmp')
    test.addCleanup(tmp.cleanup)
    path = Path(tmp.name)
    subprocess.run(['git', 'init', '-q', '-b', 'main', str(path)], check=True, capture_output=True)
    for author, subject, name, at in commits:
        (path / name).write_text(subject + '\n')
        env = {'GIT_AUTHOR_DATE': f'@{at}', 'GIT_COMMITTER_DATE': f'@{at}', 'PATH': '/usr/bin:/bin'}
        subprocess.run(['git', '-C', str(path), 'add', '.'], check=True, capture_output=True)
        subprocess.run(['git', '-c', f'user.name={author}', '-c', 'user.email=a@example.test', '-c', 'commit.gpgsign=false',
                        '-C', str(path), 'commit', '-q', '-m', subject], check=True, capture_output=True, env=env)
    return path


def sorter(calls, fail=False):
    """A fake model: every new commit about "login" goes to one group, the rest to another."""
    def complete(prompt):
        calls.append(prompt)
        if fail:
            raise ValueError('offline')
        shas = [line.split(' | ') for line in prompt.split('New commits')[1].split('\n')[1:] if ' | ' in line]
        login = [s[0] for s in shas if 'login' in s[2].lower()]
        rest = [s[0] for s in shas if 'login' not in s[2].lower()]
        known = [line.split(' | ')[0] for line in prompt.split('New commits')[0].split('\n') if ' | Login | ' in line]
        return json.dumps({'assign': [
            {'group': known[0] if known else 'new', 'title': 'Login', 'summary': 'Sign in', 'commits': login},
            {'group': 'new', 'title': 'Docs', 'summary': 'Docs', 'commits': rest}]})
    return complete


class FeatureGroupTests(unittest.TestCase):
    NOW = 1_800_000_000

    def service(self, path, models):
        cache = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(cache.cleanup)
        groups = F.FeatureGroups(cache.name, lambda: models, lambda: [str(path)], clock=lambda: self.NOW)
        return groups

    def test_new_commits_are_grouped_in_the_background_and_only_new_ones_are_sent_next_time(self):
        old = self.NOW - 3600
        path = repo(self, [('Denis', 'Add login form', 'login.py', old), ('Pasha', 'Write docs', 'README.md', old + 60)])
        calls = []
        groups = self.service(path, [{'label': 'Fake', 'complete': sorter(calls)}])
        with patch.object(F, 'fetch'):
            groups.tick()
        self.assertEqual(len(calls), 1)
        self.assertNotIn('Add login form\n', calls[0].split('New commits')[0])  # No code, only subjects and files.
        self.assertIn('login.py', calls[0])
        state = groups.status(str(path), 'ru')
        self.assertEqual([g['title'] for g in state['groups']], ['Docs', 'Login'])  # Latest commit first.
        self.assertEqual(state['pending'], [])
        self.assertEqual([(n['author'], n['title']) for n in state['now']], [('Pasha', 'Docs'), ('Denis', 'Login')])
        self.assertEqual(state['model'], 'Fake')
        # A fresh commit waits until it settles: an agent committing in a row is grouped once.
        repo_commit(path, 'Denis', 'Fix login redirect', 'login.py', self.NOW - 60)
        with patch.object(F, 'fetch'):
            groups.tick()
        self.assertEqual(len(calls), 1)
        state = groups.status(str(path))
        self.assertEqual([c['subject'] for c in state['pending']], ['Fix login redirect'])
        self.assertEqual(state['now'][0]['title'], '')  # Not sorted yet: the tab shows the commit subject.
        groups.refresh(str(path))
        with patch.object(F, 'fetch'):
            groups.tick()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1].count(' | Denis | '), 1)  # Only the new commit is sent.
        state = groups.status(str(path))
        login = next(g for g in state['groups'] if g['title'] == 'Login')
        self.assertEqual(len(login['commits']), 2)
        self.assertEqual(state['groups'][0]['title'], 'Login')

    def test_a_failing_model_falls_through_to_the_next_and_all_failing_is_reported(self):
        path = repo(self, [('Denis', 'Add login', 'login.py', self.NOW - 3600)])
        first, second = [], []
        groups = self.service(path, [{'label': 'Haiku', 'complete': sorter(first, fail=True)},
                                     {'label': 'Luna', 'complete': sorter(second)}])
        with patch.object(F, 'fetch'):
            groups.tick()
        self.assertEqual((len(first), len(second)), (1, 1))
        self.assertEqual(groups.status(str(path))['model'], 'Luna')
        path = repo(self, [('Denis', 'Add login', 'login.py', self.NOW - 3600)])
        groups = self.service(path, [{'label': 'Haiku', 'complete': sorter([], fail=True)}])
        with patch.object(F, 'fetch'):
            groups.tick()
        self.assertEqual(groups.status(str(path))['error'], 'offline')

    def test_groups_are_written_in_the_panel_language_and_sorted_again_when_it_changes(self):
        path = repo(self, [('Denis', 'Add login', 'login.py', self.NOW - 3600)])
        calls = []
        groups = self.service(path, [{'label': 'Fake', 'complete': sorter(calls)}])
        groups.language = 'ru'  # Last seen in the panel; nobody opened this repository yet.
        with patch.object(F, 'fetch'):
            groups.tick()
        self.assertIn('language with code "ru"', calls[0])
        groups.status(str(path), 'de')
        with patch.object(F, 'fetch'):
            groups.tick()
        self.assertEqual(len(calls), 2)
        self.assertIn('language with code "de"', calls[1])
        self.assertIn('(none yet)', calls[1])  # Started over: no Russian titles carried into German.
        self.assertEqual(len(groups.status(str(path), 'de')['groups']), 1)

    def test_background_fetch_runs_every_fifteen_minutes_per_repository(self):
        path = repo(self, [('Denis', 'Add login', 'login.py', self.NOW - 3600)])
        groups = self.service(path, [{'label': 'Fake', 'complete': sorter([])}])
        with patch.object(F, 'fetch') as fetched:
            groups.tick();groups.tick()
            self.assertEqual(fetched.call_count, 1)
            self.NOW += F.FETCH_EVERY
            groups.tick()
            self.assertEqual(fetched.call_count, 2)

    def test_the_answer_is_trusted_only_for_structure(self):
        commits = [{'sha': 'a' * 40}, {'sha': 'b' * 40}, {'sha': 'c' * 40}]
        store = {'groups': [{'id': 'g1', 'title': 'Login', 'summary': 'old', 'commits': ['f' * 40]}]}
        answer = 'Sure: <think>{"assign": []}</think>{"assign":[{"group":"g1","summary":"new","commits":["aaaaaaaaaaaa","aaaaaaaaaaaa","deadbeef0000"]},' \
                 '{"group":"forged","title":"","commits":["bbbbbbbbbbbb"]},{"group":"new","title":"Empty","commits":["eeeeeeeeeeee"]}]}'
        placed = F.apply_answer(store, answer, commits)
        self.assertEqual(placed, {'a' * 40, 'b' * 40})
        self.assertEqual(store['groups'][0]['commits'], ['a' * 40, 'f' * 40])
        self.assertEqual(store['groups'][0]['summary'], 'new')
        self.assertEqual([g['title'] for g in store['groups']], ['Login', 'Без названия'])  # Unknown id = new group.
        with self.assertRaisesRegex(ValueError, 'формате'):
            F.apply_answer(store, 'no json', commits)

    def test_a_commit_the_model_keeps_leaving_out_ends_up_without_a_group(self):
        path = repo(self, [('Denis', 'Add login', 'login.py', self.NOW - 3600), ('Denis', 'Bump', 'v.txt', self.NOW - 3500)])
        lazy = lambda prompt: json.dumps({'assign': [{'group': 'new', 'title': 'Login', 'commits': [
            line.split(' | ')[0] for line in prompt.split('\n') if ' | Add login' in line]}]})
        groups = self.service(path, [{'label': 'Fake', 'complete': lazy}])
        with patch.object(F, 'fetch'):
            groups.tick()
        state = groups.status(str(path))
        self.assertEqual([(g['title'], g.get('ungrouped', False)) for g in state['groups']], [('Login', False), ('Без группы', True)])

    def test_cli_models_run_without_tools_or_writes_in_an_empty_folder(self):
        calls = []
        def run(command, **kwargs):
            calls.append((command, kwargs))
            if command[1] == 'exec':
                Path(command[command.index('-o') + 1]).write_text('{"assign":[]}')
                return subprocess.CompletedProcess(command, 0, b'', b'')
            return subprocess.CompletedProcess(command, 0, json.dumps({'result': '{"assign":[]}'}).encode(), b'')
        with patch.object(F.os, 'access', return_value=True):
            claude = F.cli_model('claude', run=run, which=lambda name: '/bin/' + name)
            codex = F.cli_model('codex', run=run, which=lambda name: '/bin/' + name)
        self.assertEqual(claude['complete']('p'), '{"assign":[]}')
        self.assertEqual(codex['complete']('p'), '{"assign":[]}')
        command, kwargs = calls[0]
        self.assertEqual(command[1:6], ['-p', '--model', 'haiku', '--tools', ''])
        command, kwargs = calls[1]
        self.assertEqual(command[command.index('-s') + 1], 'read-only')
        for flag in ('--ephemeral', '--ignore-user-config', '--ignore-rules'):
            self.assertIn(flag, command)
        self.assertEqual(command[command.index('-C') + 1], kwargs['cwd'])
        self.assertFalse(Path(kwargs['cwd']).exists())  # The temporary folder is gone.
        with patch.object(F.os, 'access', return_value=False):
            self.assertIsNone(F.cli_model('codex', run=run, which=lambda name: None))

    def test_luna_is_read_from_the_codex_model_list(self):
        home = Path(tempfile.mkdtemp(dir='/tmp'))
        self.addCleanup(lambda: __import__('shutil').rmtree(home))
        self.assertEqual(F.luna_model(home), 'gpt-6-luna')
        (home / '.codex').mkdir()
        (home / '.codex/models_cache.json').write_text(json.dumps({'models': [{'slug': 'gpt-7-sol'}, {'slug': 'gpt-7-luna'}]}))
        self.assertEqual(F.luna_model(home), 'gpt-7-luna')


def repo_commit(path, author, subject, name, at):
    (path / name).write_text(subject + '\n')
    env = {'GIT_AUTHOR_DATE': f'@{at}', 'GIT_COMMITTER_DATE': f'@{at}', 'PATH': '/usr/bin:/bin'}
    subprocess.run(['git', '-C', str(path), 'add', '.'], check=True, capture_output=True)
    subprocess.run(['git', '-c', f'user.name={author}', '-c', 'user.email=a@example.test', '-c', 'commit.gpgsign=false',
                    '-C', str(path), 'commit', '-q', '-m', subject], check=True, capture_output=True, env=env)


if __name__ == '__main__':
    unittest.main()
