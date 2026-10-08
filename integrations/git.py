"""Read-only git history and uncommitted changes of a session's repository, and feature groups suggested by a cheap model.

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
import stat
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
# Reads must not take optional locks: `git status` would otherwise rewrite .git/index and an agent's
# `git add` running at that moment would fail on index.lock.
# A repository's own config must not start programs just because the panel looked at it.
BASE = ('--no-optional-locks', '-c', 'core.quotepath=off', '-c', 'core.fsmonitor=false', '--no-pager')


def git(folder, *args, run=subprocess.run, timeout=20, env=None):
    result = run(['git', '-C', str(folder), *BASE, *args],
                 input=b'', capture_output=True, timeout=timeout, **({'env': env} if env else {}))
    if result.returncode:
        message = result.stderr.decode('utf-8', 'replace').strip().splitlines()
        if message and 'not a git repository' in message[0]:
            raise ValueError('Эта папка не в git-репозитории')
        raise ValueError('git: ' + (message[0][:200] if message else 'команда не выполнена'))
    return result.stdout.decode('utf-8', 'replace')


def capped(folder, args, limit, timeout=60):
    """git output read up to a size limit: one huge generated commit must not fill the panel's memory. A stalled
    working tree (a hung network folder) must not hold a server thread forever either."""
    process = subprocess.Popen(['git', '-C', str(folder), *BASE, *args],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    watchdog = threading.Timer(timeout, process.kill)
    watchdog.start()
    try:
        data = process.stdout.read(limit)
    finally:
        watchdog.cancel()
        process.kill()
        process.stdout.close()
        process.wait(timeout=10)
    return data.decode('utf-8', 'replace')


def checked_sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError('Неверный коммит')
    return value


def branches(root, run=subprocess.run):
    """The checked-out branch, the local default branch and the remote one (what GitHub has after a fetch).
    A worktree usually sits on its own branch, which may be far behind the default one."""
    current = git(root, 'rev-parse', '--abbrev-ref', 'HEAD', run=run).strip()
    names = git(root, 'for-each-ref', '--format=%(refname:short)', 'refs/heads', 'refs/remotes', run=run).split()
    try:
        remote = git(root, 'symbolic-ref', '--quiet', '--short', 'refs/remotes/origin/HEAD', run=run).strip()
    except ValueError:
        remote = next((n for n in ('origin/main', 'origin/master') if n in names), '')
    local = remote.split('/', 1)[1] if remote and remote.split('/', 1)[1] in names else \
        next((n for n in ('main', 'master') if n in names), '')
    options = [n for i, n in enumerate([current, local, remote]) if n and n not in [current, local, remote][:i]]
    return {'current': current, 'remote': remote, 'names': set(names), 'options': options}


def checked_ref(ref, known):
    if not ref or ref == 'HEAD':
        return 'HEAD'
    if not isinstance(ref, str) or ref.startswith('-') or ref not in known['names'] | {known['current']}:
        raise ValueError('Такой ветки нет в репозитории')
    return ref


def worktrees(folder, run=subprocess.run):
    """Every working tree of the session's repository, the main one first: path, folder name and branch."""
    trees, current = [], None
    for line in git(folder, 'worktree', 'list', '--porcelain', run=run).splitlines() + ['']:
        if line.startswith('worktree '):
            current = {'path': line[9:], 'name': os.path.basename(line[9:]), 'branch': 'HEAD'}
        elif line.startswith('branch ') and current:
            current['branch'] = line[7:].removeprefix('refs/heads/')
        elif not line and current:
            if os.path.isdir(current['path']):  # A deleted folder git has not pruned yet.
                trees.append(current)
            current = None
    return trees


def mentioned_tree(trees, text, home):
    """The worktree the agent named last in its output: absolute, ~ or repository-relative path, its last
    two parts (`worktrees/w2`) or its own branch as a separate word ("branch: w2"). The main tree is left
    out: every prompt line names it."""
    main, best, found = trees[0]['path'], -1, None
    common = {'HEAD', 'main', 'master', trees[0]['branch']}
    for tree in trees[1:]:
        path = tree['path']
        forms = {path, '/'.join(path.split('/')[-2:])} | ({tree['branch']} if tree['branch'] not in common else set())
        if path.startswith(main + '/'):
            forms.add(path[len(main) + 1:])
        if home and path.startswith(home + '/'):
            forms.add('~' + path[len(home):])
        for form in forms:
            for match in re.finditer(r'(?<![\w./-])' * (form[0] not in '/~') + re.escape(form) + r'(?![\w.-])', text):
                if match.start() > best:
                    best, found = match.start(), tree
    return found


def choose_tree(folder, wanted, output, run=subprocess.run):
    """Which working tree to show: the one asked for, else the one the agent's output names, else the main one.
    output() is called only when there is a choice to make."""
    try:
        trees = worktrees(folder, run=run)
    except ValueError:
        return folder, None
    if not trees:
        return folder, None
    if wanted:
        tree = next((t for t in trees if t['path'] == wanted), None)
        if not tree:
            raise ValueError('Такого рабочего дерева нет в репозитории')
        return tree['path'], {'trees': trees, 'tree': tree['path'], 'auto': False}
    tree = (mentioned_tree(trees, output(), os.path.expanduser('~')) if len(trees) > 1 else None) or trees[0]
    # A session opened inside one worktree keeps showing it unless the output names another.
    real = os.path.realpath(folder)
    if tree is trees[0]:
        inside = [t for t in trees if real == t['path'] or real.startswith(t['path'] + '/')]
        tree = max(inside, key=lambda t: len(t['path']), default=trees[0])  # Worktrees often sit inside the main one.
    return tree['path'], {'trees': trees, 'tree': tree['path'], 'auto': True}


def history(folder, skip=0, run=subprocess.run, ref=None):
    if not isinstance(skip, int) or skip < 0:
        raise ValueError('Неверная страница истории')
    root = git(folder, 'rev-parse', '--show-toplevel', run=run).strip()
    known = branches(root, run=run)
    ref = checked_ref(ref, known)
    branch = known['current'] if ref == 'HEAD' else ref
    raw = git(root, 'log', f'--skip={skip}', f'-n{PAGE + 1}', '--shortstat',
              f'--format={REC}%H{SEP}%h{SEP}%an{SEP}%at{SEP}%s', ref, '--', run=run)
    commits = []
    for record in raw.split(REC)[1:]:
        head, _, stats = record.partition('\n')
        sha, short, author, at, subject = (head.split(SEP) + [''] * 5)[:5]
        numbers = {kind: int(n) for n, kind in re.findall(r'(\d+) (file|insertion|deletion)', stats)}
        commits.append({'sha': sha, 'short': short, 'author': author, 'time': int(at or 0), 'subject': subject,
                        'files': numbers.get('file', 0), 'added': numbers.get('insertion', 0),
                        'removed': numbers.get('deletion', 0)})
    ahead = behind = 0
    if known['remote'] and branch != known['remote']:
        counts = git(root, 'rev-list', '--left-right', '--count', f'{ref}...{known["remote"]}', '--', run=run).split()
        ahead, behind = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (0, 0)
    return {'repo': root, 'name': os.path.basename(root), 'branch': branch, 'ref': ref, 'branches': known['options'],
            'remote': known['remote'], 'ahead': ahead, 'behind': behind,
            'commits': commits[:PAGE], 'more': len(commits) > PAGE}


def fetch(folder, run=subprocess.run):
    """Updates remote branches only (never the working tree); never waits for a password prompt."""
    root = git(folder, 'rev-parse', '--show-toplevel', run=run).strip()
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '/bin/false', 'SSH_ASKPASS_REQUIRE': 'never'}
    # The user's own SSH setup (core.sshCommand, GIT_SSH*) wins; only a default ssh gets batch mode.
    try:
        own = git(root, 'config', '--get', 'core.sshCommand', run=run).strip()
    except ValueError:
        own = ''
    if not (own or env.get('GIT_SSH_COMMAND') or env.get('GIT_SSH')):
        env['GIT_SSH_COMMAND'] = 'ssh -o BatchMode=yes -o ConnectTimeout=15'
    try:
        git(root, 'fetch', '--prune', '--quiet', 'origin', run=run, timeout=60, env=env)
    except subprocess.TimeoutExpired:
        raise ValueError('GitHub не ответил за минуту; попробуйте позже') from None
    return {'ok': True}


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
    patch = capped(folder, ['show', '--format=', '--patch', '--find-renames', '--no-color', '--no-ext-diff',
                            '--no-textconv', '--diff-merges=first-parent', sha], MAX_PATCH * 2) \
        if run is subprocess.run else git(folder, 'show', '--format=', '--patch', '--find-renames', '--no-color',
                                          '--no-ext-diff', '--no-textconv', '--diff-merges=first-parent', sha, run=run)
    files, size = [], 0
    for item in split_patch(patch):
        size += len(item['patch'])
        if size > MAX_PATCH:
            item.update(patch='', truncated=True)
        files.append(item)
    return {'sha': full, 'short': short, 'author': author, 'email': email, 'time': int(at or 0),
            'parents': parents.split(), 'message': body.strip(), 'files': files}


def group_diff(folder, shas, run=subprocess.run):
    """Every change of a group's commits, collected per file (oldest commit first). One git process for the
    whole group, read up to a size limit, instead of two per commit."""
    if not isinstance(shas, list) or not 0 < len(shas) <= GROUP_COMMITS:
        raise ValueError('Неверный список коммитов')
    ordered = list(reversed([checked_sha(s) for s in shas]))
    args = ['log', '--no-walk=unsorted', '--patch', '--find-renames', '--no-color', '--no-ext-diff', '--no-textconv',
            '--diff-merges=first-parent', f'--format={REC}%H{SEP}%h{SEP}%s', *ordered, '--']
    raw = capped(folder, args, MAX_PATCH * 2) if run is subprocess.run else git(folder, *args, run=run)
    by_path, size = {}, 0
    for record in raw.split(REC)[1:]:
        head, _, patch = record.partition('\n')
        full, short, subject = (head.split(SEP) + ['', '', ''])[:3]
        for item in split_patch(patch):
            size += len(item['patch'])
            entry = by_path.setdefault(item['path'], {'path': item['path'], 'added': 0, 'removed': 0, 'changes': []})
            entry['added'] += item['added']
            entry['removed'] += item['removed']
            entry['changes'].append({'sha': full, 'short': short, 'subject': subject, 'status': item['status'],
                                     'binary': item['binary'], 'truncated': item['truncated'] or size > MAX_PATCH,
                                     'patch': item['patch'] if size <= MAX_PATCH else ''})
    return {'files': sorted(by_path.values(), key=lambda f: f['path'])}


MAX_UNTRACKED = 50


def private_parts(root):
    """The panel's own folder (passwords, keys) when it lies inside this repository: a home folder kept in git
    would otherwise show its secrets as changes."""
    from integrations.files import _private
    home, real_root = os.path.realpath(os.path.expanduser('~')), os.path.realpath(root)
    parts = set()
    for folder in _private(Path(home)):
        folder = os.path.realpath(folder)
        if folder == real_root or folder.startswith(real_root + os.sep):
            parts.add(os.path.relpath(folder, real_root))
    return parts


def is_private(root, path, parts):
    real = os.path.realpath(os.path.join(root, path))
    return any(real == os.path.join(os.path.realpath(root), p) or real.startswith(os.path.join(os.path.realpath(root), p) + os.sep)
               for p in parts) or any(path == p or path.startswith(p + '/') for p in parts)


def untracked_patch(root, path, run=subprocess.run):
    """A new file as a diff against nothing. `diff --no-index` exits 1 when files differ, which is the point."""
    try:
        info = os.lstat(os.path.join(root, path))
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None  # A new symlink could point at the panel's own secrets; git would read through it.
    if info.st_size > MAX_FILE_PATCH:
        return {'path': path, 'old_path': path, 'status': 'added', 'added': 0, 'removed': 0, 'binary': False,
                'truncated': True, 'patch': ''}
    result = run(['git', '-C', str(root), *BASE, 'diff', '--no-index', '--no-color',
                  '--no-ext-diff', '--no-textconv', '--', '/dev/null', path], input=b'', capture_output=True, timeout=20)
    if result.returncode not in (0, 1):
        return None
    files = split_patch(result.stdout.decode('utf-8', 'replace'))
    return files[0] if files else None


def changes(folder, run=subprocess.run):
    """What the agent changed and has not committed yet: tracked files against HEAD (staged and not), and new
    files git does not ignore. Read-only: the index is never touched."""
    root = git(folder, 'rev-parse', '--show-toplevel', run=run).strip()
    try:
        branch = git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD', run=run).strip()
    except ValueError:
        branch = 'HEAD'  # Detached, e.g. during a rebase.
    try:
        base = head = git(root, 'rev-parse', '--verify', '--quiet', 'HEAD^{commit}', run=run).strip()
    except ValueError:
        head = ''
        # No commits yet: everything staged is new. The empty tree's id depends on the hash (SHA-1 or SHA-256).
        base = git(root, 'hash-object', '-t', 'tree', '/dev/null', run=run).strip()
    private = private_parts(root)
    exclude = [f':(exclude,top){p}' for p in sorted(private)]
    args = ['diff', base, '--patch', '--find-renames', '--no-color', '--no-ext-diff', '--no-textconv', '--', *exclude]
    patch = capped(root, args, MAX_PATCH * 2) if run is subprocess.run else git(root, *args, run=run)
    files, size = [], 0
    for item in split_patch(patch):
        if is_private(root, item['path'], private) or is_private(root, item['old_path'], private):
            continue
        size += len(item['patch'])
        if size > MAX_PATCH:
            item.update(patch='', truncated=True)
        files.append(item)
    status = git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all', '--', *exclude, run=run)
    untracked = [entry[3:] for entry in status.split('\0') if entry.startswith('?? ') and not is_private(root, entry[3:], private)]
    for path in untracked[:MAX_UNTRACKED]:
        item = untracked_patch(root, path, run=run)
        if not item:
            continue
        size += len(item['patch'])
        if size > MAX_PATCH:
            item.update(patch='', truncated=True)
        files.append(item)
    return {'repo': root, 'name': os.path.basename(root), 'branch': branch, 'head': head,
            'files': sorted(files, key=lambda f: f['path']), 'skipped': max(0, len(untracked) - MAX_UNTRACKED)}


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
    # Reasoning models (often the local ones) think aloud before the answer; only the answer counts.
    text = re.sub(r'<think>.*?</think>', '', text or '', flags=re.S)
    match = re.search(r'\{.*\}', text, re.S)
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

    def status(self, folder, ref=None):
        info = history(folder, run=self.run, ref=ref)
        head = info['commits'][0]['sha'] if info['commits'] else ''
        key = self.key(info['repo'], head)
        try:
            return {'phase': 'done', 'head': head, **json.loads((self.cache / (key + '.json')).read_text())}
        except (OSError, ValueError):
            pass
        with self.lock:
            return {'phase': 'idle', 'head': head, **self.jobs.get(key, {})}

    def start(self, folder, language='en', ref=None, model=None):
        """model: None for Claude Haiku through Claude Code, else {'label', 'complete': prompt -> text}
        (a local LM Studio model or Kimi, prepared by the panel)."""
        repo = git(folder, 'rev-parse', '--show-toplevel', run=self.run).strip()
        commits = []
        while len(commits) < GROUP_COMMITS:
            page = history(repo, len(commits), run=self.run, ref=ref)
            commits += page['commits']
            if not page['more']:
                break
        commits = commits[:GROUP_COMMITS]
        if not commits:
            raise ValueError('В репозитории ещё нет коммитов')
        if model is None:
            claude = self.which('claude') or str(Path.home() / '.local/bin/claude')
            if not os.access(claude, os.X_OK):
                raise ValueError('Для группировки нужен Claude Code: войдите в него в настройках агентов')
            model = {'label': 'Claude Haiku', 'complete': lambda prompt: self.claude(claude, prompt)}
        key = self.key(repo, commits[0]['sha'])
        with self.lock:
            if self.jobs.get(key, {}).get('phase') == 'running':
                return {'phase': 'running'}
            self.jobs[key] = {'phase': 'running', 'started': int(time.time())}
        threading.Thread(target=self.work, args=(key, repo, commits, model, language), daemon=True,
                         name='agent-deck-git-groups').start()
        return {'phase': 'running'}

    def claude(self, claude, prompt):
        with tempfile.TemporaryDirectory(prefix='agent-deck-groups-') as empty:
            # No tools and an empty folder: commit text can only shape the answer, never act.
            result = self.run([claude, '-p', '--model', 'haiku', '--tools', '', '--output-format', 'json',
                               '--no-session-persistence', '--strict-mcp-config', '--setting-sources', ''],
                              input=prompt.encode(), capture_output=True, timeout=GROUP_TIMEOUT, cwd=empty)
        if result.returncode:
            raise ValueError('Claude Code не ответил; проверьте вход в Claude в настройках агентов')
        answer = json.loads(result.stdout.decode('utf-8', 'replace'))
        return answer.get('result', '') if isinstance(answer, dict) else ''

    def work(self, key, repo, commits, model, language):
        try:
            names = git(repo, 'log', '--no-walk=unsorted', '--name-only', f'--format={REC}%H',
                        *[c['sha'] for c in commits], '--', run=self.run)
            files = {}
            for record in names.split(REC)[1:]:
                sha, _, rest = record.partition('\n')
                files[sha.strip()] = [line for line in rest.split('\n') if line.strip()]
            prompt = group_prompt(commits, files, language if re.fullmatch(r'[a-zA-Z-]{2,10}', language) else 'en')
            groups = parse_groups(model['complete'](prompt), commits)
            value = {'groups': groups, 'commits': {c['sha']: c for c in commits}, 'created': int(time.time()),
                     'model': model['label']}
            self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
            (self.cache / (key + '.json')).write_text(json.dumps(value))
            with self.lock:
                self.jobs.pop(key, None)
        except Exception as error:  # Any failure must end the job, or it shows "running" until a restart.
            message = str(error) if isinstance(error, ValueError) else 'Группировка не удалась; попробуйте ещё раз'
            with self.lock:
                self.jobs[key] = {'phase': 'error', 'error': message[:300]}
