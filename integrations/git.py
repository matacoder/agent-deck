"""Read-only git history of a session's repository, and feature groups suggested by a cheap model.

git runs without a shell and with explicit arguments; patches are size-limited. Grouping sends only commit
subjects and file names (never code) to Claude Haiku through the installed `claude` CLI, with no tools and
an empty working folder; the answer is validated against the real commit list and cached per HEAD.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time

SHA = re.compile(r'[0-9a-f]{7,40}')
PAGE = 50
MAX_FILE_PATCH = 120 * 1024
MAX_PATCH = 600 * 1024
GROUP_COMMITS = 80
GROUP_TIMEOUT = 180
SEP, REC = '\x1f', '\x1e'


def git(folder, *args, run=subprocess.run):
    result = run(['git', '-C', str(folder), '-c', 'core.quotepath=off', '--no-pager', *args],
                 input=b'', capture_output=True, timeout=20)
    if result.returncode:
        message = result.stderr.decode('utf-8', 'replace').strip().splitlines()
        if message and 'not a git repository' in message[0]:
            raise ValueError('Эта папка не в git-репозитории')
        raise ValueError('git: ' + (message[0][:200] if message else 'команда не выполнена'))
    return result.stdout.decode('utf-8', 'replace')


def checked_sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError('Неверный коммит')
    return value


def history(folder, skip=0, run=subprocess.run):
    if not isinstance(skip, int) or skip < 0:
        raise ValueError('Неверная страница истории')
    root = git(folder, 'rev-parse', '--show-toplevel', run=run).strip()
    branch = git(root, 'rev-parse', '--abbrev-ref', 'HEAD', run=run).strip()
    raw = git(root, 'log', f'--skip={skip}', f'-n{PAGE + 1}', '--shortstat',
              f'--format={REC}%H{SEP}%h{SEP}%an{SEP}%at{SEP}%s', run=run)
    commits = []
    for record in raw.split(REC)[1:]:
        head, _, stats = record.partition('\n')
        sha, short, author, at, subject = (head.split(SEP) + [''] * 5)[:5]
        numbers = {kind: int(n) for n, kind in re.findall(r'(\d+) (file|insertion|deletion)', stats)}
        commits.append({'sha': sha, 'short': short, 'author': author, 'time': int(at or 0), 'subject': subject,
                        'files': numbers.get('file', 0), 'added': numbers.get('insertion', 0),
                        'removed': numbers.get('deletion', 0)})
    return {'repo': root, 'name': os.path.basename(root), 'branch': branch,
            'commits': commits[:PAGE], 'more': len(commits) > PAGE}


def split_patch(text):
    """Unified diff -> one entry per file, each limited in size."""
    files = []
    for chunk in re.split(r'(?m)^(?=diff --git )', text):
        if not chunk.startswith('diff --git '):
            continue
        header = chunk.split('\n', 1)[0]
        match = re.match(r'diff --git a/(.*) b/(.*)$', header)
        path = match.group(2) if match else header[11:]
        old = match.group(1) if match else path
        status = ('added' if '\nnew file mode' in chunk else 'deleted' if '\ndeleted file mode' in chunk
                  else 'renamed' if old != path else 'modified')
        lines = chunk.split('\n')
        added = sum(1 for l in lines if l.startswith('+') and not l.startswith('+++'))
        removed = sum(1 for l in lines if l.startswith('-') and not l.startswith('---'))
        truncated = len(chunk) > MAX_FILE_PATCH
        files.append({'path': path, 'old_path': old, 'status': status, 'added': added, 'removed': removed,
                      'binary': '\nBinary files ' in chunk, 'truncated': truncated,
                      'patch': chunk[:MAX_FILE_PATCH]})
    return files


def commit(folder, sha, run=subprocess.run):
    sha = checked_sha(sha)
    meta = git(folder, 'show', '-s', f'--format=%H{SEP}%h{SEP}%an{SEP}%ae{SEP}%at{SEP}%P{SEP}%B', sha, run=run)
    full, short, author, email, at, parents, body = (meta.split(SEP, 6) + [''] * 7)[:7]
    patch = git(folder, 'show', '--format=', '--patch', '--find-renames', '--no-color', '--no-ext-diff',
                '--diff-merges=first-parent', sha, run=run)
    files, size = [], 0
    for item in split_patch(patch):
        size += len(item['patch'])
        if size > MAX_PATCH:
            item.update(patch='', truncated=True)
        files.append(item)
    return {'sha': full, 'short': short, 'author': author, 'email': email, 'time': int(at or 0),
            'parents': parents.split(), 'message': body.strip(), 'files': files}


def group_diff(folder, shas, run=subprocess.run):
    """Every change of a group's commits, collected per file (oldest commit first)."""
    if not isinstance(shas, list) or not 0 < len(shas) <= GROUP_COMMITS:
        raise ValueError('Неверный список коммитов')
    by_path, size = {}, 0
    for sha in reversed([checked_sha(s) for s in shas]):
        detail = commit(folder, sha, run=run)
        for item in detail['files']:
            size += len(item['patch'])
            entry = by_path.setdefault(item['path'], {'path': item['path'], 'added': 0, 'removed': 0, 'changes': []})
            entry['added'] += item['added']
            entry['removed'] += item['removed']
            entry['changes'].append({'sha': detail['sha'], 'short': detail['short'], 'subject':
                                     detail['message'].split('\n', 1)[0], 'status': item['status'],
                                     'binary': item['binary'], 'truncated': item['truncated'] or size > MAX_PATCH,
                                     'patch': item['patch'] if size <= MAX_PATCH else ''})
    return {'files': sorted(by_path.values(), key=lambda f: f['path'])}


def group_prompt(commits, files, language):
    lines = [f"{c['sha'][:12]} | {c['subject'][:160]} | {', '.join(files.get(c['sha'], [])[:12])}" for c in commits]
    return ('Group these git commits into feature groups: commits that implement, fix or polish the same feature or '
            'change belong together. Use only the information below. Answer with JSON only, no prose: '
            '{"groups":[{"title":"short feature name","summary":"2-4 sentences: what was done and why",'
            '"commits":["sha12", ...]}]}. Make 5 to 15 groups; summaries stay short. Every commit belongs to exactly one '
            'group; keep the given sha prefixes. '
            f'Write titles and summaries in the language with code "{language}".\n\n'
            'Commits (newest first): sha | subject | changed files\n' + '\n'.join(lines))


def parse_groups(text, commits):
    """The model's JSON, trusted only for structure: shas must be real commits, each used once."""
    match = re.search(r'\{.*\}', text or '', re.S)
    try:
        data = json.loads(match.group(0)) if match else None
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get('groups'), list):
        raise ValueError('Модель вернула ответ не в том формате; попробуйте ещё раз')
    full = {c['sha'][:12]: c['sha'] for c in commits}
    used, groups = set(), []
    for item in data['groups'][:40]:
        if not isinstance(item, dict):
            continue
        shas = []
        for value in item.get('commits', []) if isinstance(item.get('commits'), list) else []:
            sha = full.get(value[:12]) if isinstance(value, str) else None
            if sha and sha not in used:
                used.add(sha)
                shas.append(sha)
        if not shas:
            continue
        groups.append({'title': str(item.get('title') or '')[:100] or 'Без названия',
                       'summary': str(item.get('summary') or '')[:1200], 'commits': shas})
    rest = [c['sha'] for c in commits if c['sha'] not in used]
    if rest:
        groups.append({'title': 'Без группы', 'summary': '', 'commits': rest, 'ungrouped': True})
    return groups


class Grouper:
    """One grouping job per repository and HEAD; finished results are reused until new commits arrive."""

    def __init__(self, cache, which=shutil.which, run=subprocess.run):
        self.cache = Path(cache)
        self.which, self.run = which, run
        self.lock = threading.Lock()
        self.jobs = {}

    def key(self, repo, head):
        return hashlib.sha256(f'{repo}\0{head}'.encode()).hexdigest()[:24]

    def status(self, folder):
        info = history(folder, run=self.run)
        head = info['commits'][0]['sha'] if info['commits'] else ''
        key = self.key(info['repo'], head)
        try:
            return {'phase': 'done', 'head': head, **json.loads((self.cache / (key + '.json')).read_text())}
        except (OSError, ValueError):
            pass
        with self.lock:
            return {'phase': 'idle', 'head': head, **self.jobs.get(key, {})}

    def start(self, folder, language='en'):
        repo = git(folder, 'rev-parse', '--show-toplevel', run=self.run).strip()
        commits = []
        while len(commits) < GROUP_COMMITS:
            page = history(repo, len(commits), run=self.run)
            commits += page['commits']
            if not page['more']:
                break
        commits = commits[:GROUP_COMMITS]
        if not commits:
            raise ValueError('В репозитории ещё нет коммитов')
        claude = self.which('claude') or str(Path.home() / '.local/bin/claude')
        if not os.access(claude, os.X_OK):
            raise ValueError('Для группировки нужен Claude Code: войдите в него в настройках агентов')
        key = self.key(repo, commits[0]['sha'])
        with self.lock:
            if self.jobs.get(key, {}).get('phase') == 'running':
                return {'phase': 'running'}
            self.jobs[key] = {'phase': 'running', 'started': int(time.time())}
        threading.Thread(target=self.work, args=(key, repo, commits, claude, language), daemon=True,
                         name='agent-deck-git-groups').start()
        return {'phase': 'running'}

    def work(self, key, repo, commits, claude, language):
        try:
            names = git(repo, 'log', f'-n{len(commits)}', '--name-only', f'--format={REC}%H', run=self.run)
            files = {}
            for record in names.split(REC)[1:]:
                sha, _, rest = record.partition('\n')
                files[sha.strip()] = [line for line in rest.split('\n') if line.strip()]
            prompt = group_prompt(commits, files, language if re.fullmatch(r'[a-zA-Z-]{2,10}', language) else 'en')
            with tempfile.TemporaryDirectory(prefix='agent-deck-groups-') as empty:
                # No tools and an empty folder: commit text can only shape the answer, never act.
                result = self.run([claude, '-p', '--model', 'haiku', '--tools', '', '--output-format', 'json',
                                   '--no-session-persistence', '--strict-mcp-config'],
                                  input=prompt.encode(), capture_output=True, timeout=GROUP_TIMEOUT, cwd=empty)
            if result.returncode:
                raise ValueError('Claude Code не ответил; проверьте вход в Claude в настройках агентов')
            answer = json.loads(result.stdout.decode('utf-8', 'replace'))
            groups = parse_groups(answer.get('result', ''), commits)
            value = {'groups': groups, 'commits': {c['sha']: c for c in commits}, 'created': int(time.time())}
            self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
            (self.cache / (key + '.json')).write_text(json.dumps(value))
            with self.lock:
                self.jobs.pop(key, None)
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            message = str(error) if isinstance(error, ValueError) else 'Группировка не удалась; попробуйте ещё раз'
            with self.lock:
                self.jobs[key] = {'phase': 'error', 'error': message[:300]}
