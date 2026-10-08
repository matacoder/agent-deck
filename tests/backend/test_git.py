import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import ROOT, PanelCase
sys.path.insert(0, str(ROOT))
from integrations import git as G


def repo(test):
    tmp = tempfile.TemporaryDirectory(dir='/tmp')
    test.addCleanup(tmp.cleanup)
    path = Path(tmp.name)
    env = ['-c', 'user.name=Dev', '-c', 'user.email=dev@example.test', '-c', 'commit.gpgsign=false']
    def git(*args):
        subprocess.run(['git', *env, '-C', str(path), *args], check=True, capture_output=True)
    git('init', '-q', '-b', 'main')
    (path / 'app.py').write_text('a = 1\nb = 2\n')
    git('add', '.'); git('commit', '-q', '-m', 'Add app')
    (path / 'app.py').write_text('a = 1\nb = 3\nc = 4\n')
    (path / 'README.md').write_text('# Demo\n')
    git('add', '.'); git('commit', '-q', '-m', 'Change b and add readme\n\nLonger explanation.')
    return path


class HistoryTests(unittest.TestCase):
    def test_history_lists_commits_with_their_change_counts(self):
        path = repo(self)
        data = G.history(path)
        self.assertEqual((data['branch'], data['more']), ('main', False))
        self.assertEqual([c['subject'] for c in data['commits']], ['Change b and add readme', 'Add app'])
        self.assertEqual({k: data['commits'][0][k] for k in ('files', 'added', 'removed')}, {'files': 2, 'added': 3, 'removed': 1})

    def test_commit_has_its_message_and_a_diff_per_file(self):
        path = repo(self)
        sha = G.history(path)['commits'][0]['sha']
        detail = G.commit(path, sha)
        self.assertEqual(detail['message'], 'Change b and add readme\n\nLonger explanation.')
        files = {f['path']: f for f in detail['files']}
        self.assertEqual((files['README.md']['status'], files['app.py']['status']), ('added', 'modified'))
        self.assertIn('+c = 4', files['app.py']['patch'])
        self.assertEqual((files['app.py']['added'], files['app.py']['removed']), (2, 1))

    def test_group_diff_collects_every_commit_per_file_oldest_first(self):
        path = repo(self)
        shas = [c['sha'] for c in G.history(path)['commits']]
        app = next(f for f in G.group_diff(path, shas)['files'] if f['path'] == 'app.py')
        self.assertEqual([c['subject'] for c in app['changes']], ['Add app', 'Change b and add readme'])

    def test_only_real_commit_ids_reach_git(self):
        path = repo(self)
        for bad in ('HEAD', '--output=/tmp/x', 'abc', 'a' * 41, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                G.commit(path, bad)
        with self.assertRaisesRegex(ValueError, 'git-репозитории'):
            G.history(tempfile.gettempdir())


class GroupingTests(unittest.TestCase):
    COMMITS = [{'sha': 'a' * 40, 'subject': 'Add login'}, {'sha': 'b' * 40, 'subject': 'Fix login'},
               {'sha': 'c' * 40, 'subject': 'Docs'}]

    def test_model_answer_is_trusted_only_for_structure(self):
        answer = 'Sure! {"groups":[{"title":"Login","summary":"Login flow","commits":["aaaaaaaaaaaa","bbbbbbbbbbbb","bbbbbbbbbbbb","deadbeef0000"]},' \
                 '{"title":"Empty","commits":["ffffffffffff"]}]}'
        groups = G.parse_groups(answer, self.COMMITS)
        self.assertEqual(groups[0]['commits'], ['a' * 40, 'b' * 40])  # Unknown and repeated ids are dropped.
        self.assertEqual(groups[1], {'title': 'Без группы', 'summary': '', 'commits': ['c' * 40], 'ungrouped': True})
        with self.assertRaisesRegex(ValueError, 'формате'):
            G.parse_groups('no json here', self.COMMITS)

    def test_grouping_runs_haiku_without_tools_in_an_empty_folder_and_caches_by_head(self):
        path = repo(self)
        cache = Path(tempfile.mkdtemp(dir='/tmp'))
        self.addCleanup(lambda: __import__('shutil').rmtree(cache))
        calls = []
        def run(command, **kwargs):
            if command[0] != '/bin/claude':
                return subprocess.run(command, **kwargs)
            calls.append((command, kwargs))
            shas = [line.split(' | ')[0] for line in kwargs['input'].decode().split('\n') if ' | ' in line and not line.startswith('Commits')]
            result = json.dumps({'groups': [{'title': 'Демо', 'summary': 'Всё', 'commits': shas}]})
            return subprocess.CompletedProcess(command, 0, json.dumps({'result': result}).encode(), b'')
        grouper = G.Grouper(cache, which=lambda name: '/bin/claude', run=run)
        with patch.object(G.os, 'access', return_value=True), patch.object(G.threading, 'Thread') as thread:
            grouper.start(path, 'ru')
            thread.call_args.kwargs['target'](*thread.call_args.kwargs['args'])  # Run the job inline.
        command, kwargs = calls[0]
        self.assertEqual(command[1:5], ['-p', '--model', 'haiku', '--tools'])
        self.assertEqual(command[5], '')
        self.assertNotIn('a = 1', kwargs['input'].decode())  # Subjects and file names only, never code.
        self.assertIn('app.py', kwargs['input'].decode())
        self.assertEqual(list(Path(kwargs['cwd']).parent.glob(Path(kwargs['cwd']).name)), [])  # Temporary, removed.
        status = grouper.status(path)
        self.assertEqual((status['phase'], status['groups'][0]['title'], len(status['groups'][0]['commits'])), ('done', 'Демо', 2))


class ChangesTests(unittest.TestCase):
    def test_uncommitted_changes_include_staged_unstaged_and_new_files_without_touching_the_index(self):
        path = repo(self)
        (path / 'app.py').write_text('a = 1\nb = 5\nc = 4\n')
        (path / 'README.md').write_text('# Demo\n\nMore.\n')
        subprocess.run(['git', '-C', str(path), 'add', 'README.md'], check=True)
        (path / 'notes.txt').write_text('todo\n')
        (path / '.gitignore').write_text('build/\n')
        (path / 'build').mkdir()
        (path / 'build' / 'out.js').write_text('x\n')
        index = (path / '.git' / 'index').read_bytes()
        data = G.changes(path)
        files = {f['path']: f for f in data['files']}
        self.assertEqual(set(files), {'app.py', 'README.md', 'notes.txt', '.gitignore'})
        self.assertIn('+b = 5', files['app.py']['patch'])
        self.assertIn('+More.', files['README.md']['patch'])
        self.assertEqual((files['notes.txt']['status'], files['notes.txt']['added']), ('added', 1))
        self.assertEqual((path / '.git' / 'index').read_bytes(), index)

    def test_a_clean_tree_has_no_changes_and_a_repository_without_commits_still_works(self):
        clean = repo(self)
        data = G.changes(clean)
        self.assertEqual(data['files'], [])
        # A clean tree names its last commit, which the panel shows instead.
        last = subprocess.run(['git', '-C', str(clean), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(data['head'], last)
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        fresh = Path(tmp.name)
        subprocess.run(['git', 'init', '-q', str(fresh)], check=True)
        (fresh / 'a.txt').write_text('a\n')
        subprocess.run(['git', '-C', str(fresh), 'add', 'a.txt'], check=True)
        (fresh / 'b.txt').write_text('b\n')
        self.assertEqual([f['path'] for f in G.changes(fresh)['files']], ['a.txt', 'b.txt'])
        self.assertEqual(G.changes(fresh)['head'], '')

    def test_new_symlinks_are_not_read_and_big_new_files_have_no_patch(self):
        path = repo(self)
        secret = path.parent / (path.name + '-secret')
        secret.write_text('PANEL_PASSWORD=x\n')
        self.addCleanup(secret.unlink)
        (path / 'link').symlink_to(secret)
        (path / 'big.log').write_bytes(b'x' * (G.MAX_FILE_PATCH + 1))
        files = {f['path']: f for f in G.changes(path)['files']}
        self.assertNotIn('link', files)
        self.assertEqual((files['big.log']['patch'], files['big.log']['truncated']), ('', True))
        self.assertNotIn('PANEL_PASSWORD', json.dumps(files))


class ChangesPrivacyTests(unittest.TestCase):
    def test_a_home_folder_kept_in_git_never_shows_the_panel_secrets(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        env = ['-c', 'user.name=Dev', '-c', 'user.email=dev@example.test', '-c', 'commit.gpgsign=false']
        run = lambda *args: subprocess.run(['git', *env, '-C', str(home), *args], check=True, capture_output=True)
        run('init', '-q')
        (home / '.config/cc-panel').mkdir(parents=True)
        (home / '.config/cc-panel/env').write_text('PANEL_PASSWORD=tracked\n')
        (home / 'notes.txt').write_text('a\n')
        run('add', '.'); run('commit', '-q', '-m', 'dotfiles')
        (home / '.config/cc-panel/env').write_text('PANEL_PASSWORD=changed\n')
        (home / '.config/cc-panel/new-key').write_text('SECRET=new\n')
        (home / 'notes.txt').write_text('b\n')
        index = (home / '.git/index').stat().st_mtime_ns
        with patch.dict('os.environ', {'HOME': str(home)}):
            data = G.changes(home)
        self.assertEqual([f['path'] for f in data['files']], ['notes.txt'])
        self.assertNotIn('PANEL_PASSWORD', json.dumps(data))
        self.assertNotIn('SECRET', json.dumps(data))
        self.assertEqual((home / '.git/index').stat().st_mtime_ns, index)  # Read-only: no index refresh.


class PanelGitTests(PanelCase):
    def test_git_routes_need_a_real_session(self):
        with self.assertRaisesRegex(ValueError, 'сессия не найдена'):
            self.panel.git_payload('/api/git/log', {'name': ['../x']})


class WorktreeBranchTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        env = ['-c', 'user.name=Dev', '-c', 'user.email=dev@example.test', '-c', 'commit.gpgsign=false']
        def git(where, *args):
            subprocess.run(['git', *env, '-C', str(where), *args], check=True, capture_output=True)
        self.git = git
        self.origin, self.clone, self.tree = root / 'origin.git', root / 'clone', root / 'tree'
        subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(self.origin)], check=True, capture_output=True)
        subprocess.run(['git', 'clone', '-q', str(self.origin), str(self.clone)], check=True, capture_output=True)
        (self.clone / 'a.txt').write_text('a\n')
        git(self.clone, 'add', '.'); git(self.clone, 'commit', '-q', '-m', 'Old work'); git(self.clone, 'push', '-q', 'origin', 'main')
        git(self.clone, 'remote', 'set-head', 'origin', 'main')
        git(self.clone, 'worktree', 'add', '-q', '-b', 'feature', str(self.tree))
        (self.clone / 'b.txt').write_text('b\n')
        git(self.clone, 'add', '.'); git(self.clone, 'commit', '-q', '-m', 'Shipped to prod'); git(self.clone, 'push', '-q', 'origin', 'main')

    def test_a_worktree_shows_its_branch_how_far_behind_it_is_and_can_switch_to_the_remote(self):
        own = G.history(self.tree)
        self.assertEqual((own['branch'], own['remote'], own['behind']), ('feature', 'origin/main', 1))
        self.assertEqual(own['branches'], ['feature', 'main', 'origin/main'])
        self.assertEqual([c['subject'] for c in own['commits']], ['Old work'])
        prod = G.history(self.tree, ref='origin/main')
        self.assertEqual(prod['commits'][0]['subject'], 'Shipped to prod')
        with self.assertRaisesRegex(ValueError, 'ветки'):
            G.history(self.tree, ref='--all')

    def test_fetch_brings_new_remote_commits_and_never_prompts(self):
        other = Path(tempfile.mkdtemp(dir='/tmp'))
        self.addCleanup(lambda: __import__('shutil').rmtree(other))
        subprocess.run(['git', 'clone', '-q', str(self.origin), str(other / 'c')], check=True, capture_output=True)
        (other / 'c/c.txt').write_text('c\n')
        self.git(other / 'c', 'add', '.'); self.git(other / 'c', 'commit', '-q', '-m', 'Pushed elsewhere'); self.git(other / 'c', 'push', '-q')
        self.assertNotEqual(G.history(self.tree, ref='origin/main')['commits'][0]['subject'], 'Pushed elsewhere')
        seen = {}
        def run(command, **kwargs):
            if 'fetch' in command:
                seen.update(kwargs.get('env') or {})
            return subprocess.run(command, **kwargs)
        G.fetch(self.tree, run=run)
        self.assertEqual(seen.get('GIT_TERMINAL_PROMPT'), '0')
        self.assertEqual(G.history(self.tree, ref='origin/main')['commits'][0]['subject'], 'Pushed elsewhere')


class ReviewFixTests(unittest.TestCase):
    def test_fetch_keeps_the_users_own_ssh_command(self):
        path = repo(self)
        subprocess.run(['git', '-C', str(path), 'remote', 'add', 'origin', str(path)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(path), 'config', 'core.sshCommand', 'ssh -i ~/.ssh/deploy_key'], check=True)
        seen = {}
        def run(command, **kwargs):
            if 'fetch' in command:
                seen.update(kwargs.get('env') or {})
            return subprocess.run(command, **kwargs)
        G.fetch(path, run=run)
        self.assertEqual(seen.get('GIT_TERMINAL_PROMPT'), '0')
        self.assertNotIn('BatchMode', seen.get('GIT_SSH_COMMAND', ''))

    def test_an_unexpected_model_answer_ends_the_job_instead_of_running_forever(self):
        path = repo(self)
        cache = Path(tempfile.mkdtemp(dir='/tmp'))
        self.addCleanup(lambda: __import__('shutil').rmtree(cache))
        def run(command, **kwargs):
            if command[0] != '/bin/claude':
                return subprocess.run(command, **kwargs)
            return subprocess.CompletedProcess(command, 0, b'["not", "an", "object"]', b'')
        grouper = G.Grouper(cache, which=lambda name: '/bin/claude', run=run)
        with patch.object(G.os, 'access', return_value=True), patch.object(G.threading, 'Thread') as thread:
            grouper.start(path)
            thread.call_args.kwargs['target'](*thread.call_args.kwargs['args'])
        self.assertEqual(grouper.status(path)['phase'], 'error')


class GroupingModelTests(unittest.TestCase):
    def test_a_thinking_answer_is_read_after_its_reasoning(self):
        answer = '<think>maybe {"groups": []} ... hmm</think>{"groups":[{"title":"Login","commits":["aaaaaaaaaaaa"]}]}'
        commits = [{'sha': 'a' * 40, 'subject': 'Add login'}]
        self.assertEqual(G.parse_groups(answer, commits)[0]['title'], 'Login')


class PanelGroupingModelTests(PanelCase):
    def test_local_models_come_first_and_run_without_reasoning(self):
        from unittest.mock import Mock
        service = Mock()
        service.status.return_value = {'profiles': [{'id': 'p1', 'name': 'RED', 'models': [{'id': 'qwen/q', 'name': 'Qwen'}]}]}
        service.get.return_value = {'id': 'p1', 'name': 'RED', 'url': 'http://100.64.0.5:1234', 'key': '', 'models': [{'id': 'qwen/q'}]}
        self.enterContext(patch.object(self.panel, 'model_service', return_value=service))
        self.enterContext(patch.object(self.panel.kimi_config, 'read', return_value={}))
        self.enterContext(patch.object(self.panel, 'agent_status', return_value={'logged_in': True}))
        models = self.panel.grouping_models()['models']
        self.assertEqual([m['id'] for m in models], ['lmstudio:p1:qwen/q', 'claude'])
        self.assertTrue(models[0]['local'])
        from integrations import lmstudio
        with patch.object(lmstudio, 'request', return_value={'choices': [{'message': {'content': '{"groups":[]}'}}]}) as request:
            model = self.panel.grouping_model('lmstudio:p1:qwen/q')
            self.assertEqual(model['complete']('prompt'), '{"groups":[]}')
        body = request.call_args.args[3]
        self.assertEqual((body['model'], body['reasoning_effort']), ('qwen/q', 'none'))
        self.assertIsNone(self.panel.grouping_model('claude'))
        for bad in ('lmstudio:p1:other', 'shell:rm'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.panel.grouping_model(bad)
