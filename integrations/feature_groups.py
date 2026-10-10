"""Feature groups of a repository, kept up to date in the background.

A repository (all its worktrees share one history) has one store: groups with stable ids and the commits
already sorted into them. A pass sends a cheap model only what is new: the existing group titles and up to
BATCH new commits (subject, author, file names; never code). Claude and Codex run through their CLIs on the
user's subscription, with no tools (Claude) or a read-only sandbox without network (Codex), in an empty
folder. The answer is trusted only for structure: shas must be real new commits, each used once.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time

from .git import REC, fetch, git, log_commits

SEED = 200            # commits looked at; older ones are never grouped
BATCH = 40            # new commits per model request
SETTLE = 600          # an agent commits in a row: wait until the newest is 10 minutes old...
BACKLOG = 20          # ...unless this many are waiting
POLL = 300
FETCH_EVERY = 900
ACTIVE_DAYS = 7
PROMPT_GROUPS = 60
PASSES_PER_TICK = 5
MODEL_TIMEOUT = 300
TRIES = 2             # a commit the model keeps leaving out goes to "no group" after this many passes


def cli_model(name, run=subprocess.run, which=shutil.which):
    """Claude Haiku or Codex Luna through the installed CLI, or None when it is not installed."""
    path = which(name) or str(Path.home() / '.local/bin' / name)
    if not os.access(path, os.X_OK):
        return None
    if name == 'claude':
        return {'label': 'Claude Haiku', 'complete': lambda prompt: claude_answer(path, prompt, run)}
    model = luna_model()
    return {'label': 'Codex · ' + model, 'complete': lambda prompt: codex_answer(path, model, prompt, run)}


def claude_answer(claude, prompt, run):
    # One fixed empty folder: Claude Code registers every new working folder as a project of its own.
    empty = Path.home() / '.cache/agent-deck/feature-groups/model'
    empty.mkdir(parents=True, exist_ok=True, mode=0o700)
    result = run([claude, '-p', '--model', 'haiku', '--tools', '', '--output-format', 'json',
                  '--no-session-persistence', '--strict-mcp-config', '--setting-sources', ''],
                 input=prompt.encode(), capture_output=True, timeout=MODEL_TIMEOUT, cwd=str(empty))
    if result.returncode:
        raise ValueError('Claude Code не ответил; проверьте вход в Claude в настройках агентов')
    answer = json.loads(result.stdout.decode('utf-8', 'replace'))
    return answer.get('result', '') if isinstance(answer, dict) else ''


def luna_model(home=None):
    """Codex's light model: the newest "luna" in its model list, else a known name."""
    try:
        data = json.loads((Path(home or Path.home()) / '.codex/models_cache.json').read_text())
        for item in data.get('models', []) if isinstance(data, dict) else []:
            slug = item.get('slug', '') if isinstance(item, dict) else ''
            if re.fullmatch(r'[a-z0-9.-]*luna[a-z0-9.-]*', slug):
                return slug
    except (OSError, ValueError):
        pass
    return 'gpt-6-luna'


def codex_answer(codex, model, prompt, run):
    with tempfile.TemporaryDirectory(prefix='agent-deck-groups-') as empty:
        out = Path(empty) / 'answer.txt'
        # Commit subjects are someone else's text: no writes, no network, no user config or rules.
        result = run([codex, 'exec', '-m', model, '-s', 'read-only', '--ephemeral', '--ignore-user-config',
                      '--ignore-rules', '--skip-git-repo-check', '-c', 'approval_policy="never"',
                      '-c', 'model_reasoning_effort="low"', '-C', empty, '-o', str(out), '-'],
                     input=prompt.encode(), capture_output=True, timeout=MODEL_TIMEOUT, cwd=empty)
        if result.returncode:
            raise ValueError('Codex не ответил; проверьте вход в Codex в настройках агентов')
        return out.read_text(encoding='utf-8', errors='replace') if out.exists() else ''


def commit_files(root, shas, run=subprocess.run):
    names = git(root, 'log', '--no-walk=unsorted', '--name-only', f'--format={REC}%H', *shas, '--', run=run)
    files = {}
    for record in names.split(REC)[1:]:
        sha, _, rest = record.partition('\n')
        files[sha.strip()] = [line for line in rest.split('\n') if line.strip()]
    return files


def pass_prompt(groups, commits, files, language):
    known = [f"{g['id']} | {g['title']} | {g['summary'][:160]}" for g in groups if not g.get('ungrouped')][-PROMPT_GROUPS:]
    lines = [f"{c['sha'][:12]} | {c['author'][:40]} | {c['subject'][:160]} | {', '.join(files.get(c['sha'], [])[:12])}"
             for c in commits]
    return ('Sort new git commits into feature groups: commits that implement, fix or polish the same feature '
            'belong together. Put a commit into an existing group when it continues that feature, otherwise '
            'start a new group. Use only the information below. Answer with JSON only, no prose: '
            '{"assign":[{"group":"existing id, or new","title":"short feature name, only for new",'
            '"summary":"2-4 sentences: what was done and why; for an existing group the updated summary",'
            '"commits":["sha12", ...]}]}. Every new commit goes to exactly one entry; keep the given sha prefixes. '
            f'Write titles and summaries in the language with code "{language}".\n\n'
            'Existing groups: id | title | summary\n' + ('\n'.join(known) or '(none yet)') +
            '\n\nNew commits (oldest first): sha | author | subject | changed files\n' + '\n'.join(lines))


def apply_answer(store, text, commits):
    """Merges the model's answer into the store; returns the shas it placed."""
    text = re.sub(r'<think>.*?</think>', '', text if isinstance(text, str) else '', flags=re.S)
    match = re.search(r'\{.*\}', text, re.S)
    try:
        data = json.loads(match.group(0)) if match else None
    except ValueError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get('assign'), list):
        raise ValueError('Модель вернула ответ не в том формате; попробуйте ещё раз')
    full = {c['sha'][:12]: c['sha'] for c in commits}
    groups = {g['id']: g for g in store['groups']}
    placed = set()
    for item in data['assign'][:60]:
        if not isinstance(item, dict) or not isinstance(item.get('commits'), list):
            continue
        shas = [full[v[:12]] for v in item['commits'] if isinstance(v, str) and v[:12] in full and full[v[:12]] not in placed]
        if not shas:
            continue
        placed.update(shas)
        group = groups.get(str(item.get('group') or ''))
        if group is None or group.get('ungrouped'):
            group = {'id': secrets.token_hex(4), 'title': str(item.get('title') or '')[:100] or 'Без названия',
                     'summary': '', 'commits': []}
            store['groups'].append(group)
            groups[group['id']] = group
        group['commits'] = list(dict.fromkeys(shas + group['commits']))
        if isinstance(item.get('summary'), str) and item['summary'].strip():
            group['summary'] = item['summary'].strip()[:1200]
    return placed


def empty_store():
    return {'groups': [], 'commits': {}, 'tries': {}, 'model': '', 'at': 0, 'error': '', 'language': ''}


class FeatureGroups:
    """One store per repository; a background thread groups new commits and fetches remote branches."""

    def __init__(self, cache, models, folders, run=subprocess.run, clock=time.time, language='en'):
        self.cache = Path(cache)
        self.language = language  # the panel language last seen; repositories nobody opened use it
        self.models, self.folders = models, folders   # callables: model chain, session folders
        self.run, self.clock = run, clock
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.state = {}    # key -> {'running': bool, 'forced': bool, 'fetched': ts, 'language': code}

    def locate(self, folder):
        common = git(folder, 'rev-parse', '--path-format=absolute', '--git-common-dir', run=self.run).strip()
        root = git(folder, 'rev-parse', '--show-toplevel', run=self.run).strip()
        return hashlib.sha256(common.encode()).hexdigest()[:24], root

    def load(self, key):
        try:
            store = json.loads((self.cache / (key + '.json')).read_text())
            if isinstance(store, dict) and isinstance(store.get('groups'), list):
                return {**empty_store(), **store}  # A store with fields missing still reads.
        except (OSError, ValueError):
            pass
        return empty_store()

    def save(self, key, store):
        self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temp = tempfile.mkstemp(dir=self.cache, prefix='.groups-')
        with os.fdopen(fd, 'w') as handle:
            json.dump(store, handle)
        os.replace(temp, self.cache / (key + '.json'))

    def status(self, folder, language='en'):
        key, root = self.locate(folder)
        recent = log_commits(root, ['--branches', '--remotes', f'-n{SEED}'], run=self.run)
        with self.lock:
            self.language = language
            first = 'language' not in self.state.get(key, {})
            state = self.state.setdefault(key, {})
            state.update(language=language, folder=root)
            running = bool(state.get('running'))
        if first:
            self.wake.set()  # Opened for the first time: group it now, not at the next tick.
        return view(self.load(key), recent, running, self.clock())

    def refresh(self, folder):
        key, root = self.locate(folder)
        with self.lock:
            self.state.setdefault(key, {}).update(forced=True, folder=root)
        self.wake.set()
        return {'ok': True}

    def run_forever(self):
        while True:
            try:
                self.tick()
            except Exception as error:  # The loop must survive anything one repository does.
                print(f'Feature groups: {type(error).__name__}', flush=True)
            self.wake.wait(POLL)
            self.wake.clear()

    def tick(self):
        for folder in self.folders():
            try:
                key, root = self.locate(folder)
            except (ValueError, OSError, subprocess.TimeoutExpired):
                continue
            with self.lock:
                self.state.setdefault(key, {}).setdefault('folder', root)
        with self.lock:
            for key in [key for key, state in self.state.items() if not os.path.isdir(state['folder'])]:
                del self.state[key]  # The repository was deleted or moved: nothing to fetch or group.
            work = [(key, dict(state)) for key, state in self.state.items()]
        for key, state in work:
            try:
                self.fetch_if_due(key, state)
                self.group(key, state)
            except Exception as error:  # One repository failing must not stop the ones after it.
                print(f'Feature groups: {type(error).__name__}', flush=True)

    def fetch_if_due(self, key, state):
        if self.clock() - state.get('fetched', 0) < FETCH_EVERY:
            return
        with self.lock:
            if key in self.state:
                self.state[key]['fetched'] = self.clock()
        try:
            fetch(state['folder'], run=self.run)
        except (ValueError, OSError, subprocess.TimeoutExpired):
            pass  # No remote, offline or no access: grouping goes on with what is here.

    def group(self, key, state):
        with self.lock:
            live = self.state.get(key)
            if live is None or live.get('running'):
                return
            # Read here, not from the tick's snapshot: a refresh or a language asked for meanwhile counts.
            forced, language = live.get('forced'), live.get('language')
            live.update(running=True, forced=False)
        try:
            for _ in range(PASSES_PER_TICK):
                if not self.one_pass(key, state['folder'], language, forced):
                    break
                forced = False
        finally:
            with self.lock:
                if key in self.state:
                    self.state[key]['running'] = False

    def one_pass(self, key, root, language, forced):
        kept = store = self.load(key)
        # Nobody opened this repository since the panel started: its groups stay in their own language.
        language = language or kept.get('language') or self.language
        language = language if re.fullmatch(r'[a-zA-Z-]{2,10}', language) else 'en'
        if store['groups'] and store.get('language') != language:
            # Titles and summaries are written in one language; another panel language sorts again.
            store = empty_store()
        grouped = {sha for g in store['groups'] for sha in g['commits']}
        pending = [c for c in log_commits(root, ['--branches', '--remotes', f'-n{SEED}'], run=self.run)
                   if c['sha'] not in grouped][::-1]
        now = self.clock()
        if not pending or not (forced or len(pending) >= BACKLOG or now - pending[-1]['time'] >= SETTLE):
            return False
        batch = pending[:BATCH]
        prompt = pass_prompt(store['groups'], batch, commit_files(root, [c['sha'] for c in batch], run=self.run), language)
        errors, placed, answered = [], set(), None
        for model in self.models():
            try:
                placed = apply_answer(store, model['complete'](prompt), batch)
            except (ValueError, OSError, subprocess.TimeoutExpired) as error:
                errors.append(str(error) if isinstance(error, ValueError) else 'Модель не ответила; группировка повторится позже')
                continue
            answered = model
            if placed:
                break  # An answer that places nothing is as good as none: the next model is asked.
        if answered is None:
            # The first model's reason: it is the one the user expects to work. A plain message, so it is translated.
            # Saved with the groups there are: a failed re-sort in another language must not erase them.
            kept['error'] = (errors[0] if errors else
                             'Нет модели для группировки: войдите в Claude, Codex или Kimi, или подключите LM Studio')[:300]
            self.save(key, kept)
            return False
        store['language'] = language
        self.record(store, batch, placed, answered['label'], now)
        self.save(key, store)
        return bool(placed)  # Nothing placed counts one try; the next one waits for the next tick.

    def record(self, store, batch, placed, label, now):
        for c in batch:
            if c['sha'] in placed:
                store['commits'][c['sha']] = c
                store['tries'].pop(c['sha'], None)
            else:
                store['tries'][c['sha']] = store['tries'].get(c['sha'], 0) + 1
        stuck = [c for c in batch if store['tries'].get(c['sha'], 0) >= TRIES]
        if stuck:
            rest = next((g for g in store['groups'] if g.get('ungrouped')), None)
            if rest is None:
                rest = {'id': 'ungrouped', 'title': 'Без группы', 'summary': '', 'commits': [], 'ungrouped': True}
                store['groups'].append(rest)
            for c in stuck:
                rest['commits'].insert(0, c['sha'])
                store['commits'][c['sha']] = c
                store['tries'].pop(c['sha'], None)
        store.update(model=label, at=int(now), error='')


def view(store, recent, running, now):
    """What the tab shows: who works on what, commits not sorted yet, groups by their latest commit."""
    commits = {**store['commits'], **{c['sha']: c for c in recent}}
    owner = {sha: g for g in store['groups'] for sha in g['commits']}
    groups = []
    for g in store['groups']:
        rows = [commits[sha] for sha in g['commits'] if sha in commits]
        if rows:
            groups.append({**g, 'commits': [c['sha'] for c in sorted(rows, key=lambda c: -c['time'])],
                           'authors': sorted({c['author'] for c in rows}), 'last': max(c['time'] for c in rows)})
    groups.sort(key=lambda g: (bool(g.get('ungrouped')), -g['last']))
    now_list, seen = [], set()
    for c in recent:
        if c['author'] in seen or now - c['time'] > ACTIVE_DAYS * 86400:
            continue
        seen.add(c['author'])
        group = owner.get(c['sha'])
        now_list.append({'author': c['author'], 'time': c['time'], 'subject': c['subject'],
                         'group': group['id'] if group and not group.get('ungrouped') else '',
                         'title': group['title'] if group and not group.get('ungrouped') else ''})
    return {'phase': 'running' if running else 'ready', 'now': now_list,
            'pending': [c for c in recent if c['sha'] not in owner][:50], 'groups': groups,
            'commits': {sha: commits[sha] for g in groups for sha in g['commits']},
            'model': store.get('model', ''), 'at': store.get('at', 0), 'error': store.get('error', '')}
