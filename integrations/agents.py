"""Agents that are a command-line program in a terminal and nothing more: one description each.

Claude Code, Codex, Kimi and Pi keep their own code in the panel (hooks, limits, model sources). Everything
else is described here once: how it is installed, signed in, started with or without questions, and how its
conversation is continued after a restart. A new agent of this kind is one more entry and its tests.
"""
import json
import os
import re
import shlex
import shutil
from pathlib import Path

SELECTED = re.compile(r'"selectedType"\s*:\s*"[\w-]+"')


def chose_provider(folder):
    """Qwen Code and Gemini CLI write the chosen sign-in into settings.json, which may carry comments."""
    def check(home):
        try:
            text = (home / folder / 'settings.json').read_text(encoding='utf-8', errors='replace')
        except OSError:
            return False
        try:
            return bool(json.loads(text).get('security', {}).get('auth', {}).get('selectedType'))
        except (ValueError, AttributeError):
            return SELECTED.search(text) is not None
    return check


def has_file(*names):
    return lambda home: any((home / name).is_file() for name in names)


def mentions(name, word):
    def check(home):
        try:
            return word in (home / name).read_text(encoding='utf-8', errors='replace')
        except OSError:
            return False
    return check


def either(*checks):
    return lambda home: any(check(home) for check in checks)


def files(*patterns):
    """A conversation is on disk when one of the patterns matches; `{sid}` and `{short}` name it."""
    def check(sid, home):
        return any(next(home.glob(pattern.format(sid=sid, short=sid[:8])), None) for pattern in patterns)
    return check


# label      what people call it
# binary     the program; `places` are folders its installer uses besides ~/.local/bin and PATH
# processes  what tmux reports while it runs
# skip       the switch that stops it asking before every action
# install    the vendor's own command, run in a terminal of the panel
# login      the command that opens sign-in in a terminal; None: the vendor has none, the agent asks by itself
# start      how a new conversation gets the panel's id; '' when the program only makes ids itself
# resume     how the conversation is continued: by that id, or the program's "last one in this folder"
# signed_in  home -> bool; None: usable without signing in
# recorded   (id, home) -> bool, whether the conversation reached the disk; None: not checked
# headless   how another agent asks it one question without a terminal
CLI = {
    'qwen': dict(
        label='Qwen Code', binary='qwen', processes=('qwen', 'node'), skip=' --yolo',
        install='curl -fsSL https://qwen-code-assets.oss-cn-hangzhou.aliyuncs.com/installation/install-qwen-standalone.sh | bash',
        login='qwen', start=' --session-id {sid}', resume=' --resume {sid}',
        signed_in=chose_provider('.qwen'), recorded=files('.qwen/projects/*/chats/{sid}.jsonl', '.qwen/tmp/*/chats/{sid}.jsonl'),
        headless='qwen -p'),
    'gemini': dict(
        label='Gemini CLI', binary='gemini', processes=('gemini', 'node'), skip=' --yolo',
        install='npm install --global --prefix "$HOME/.local" @google/gemini-cli --no-audit --no-fund',
        login='gemini', start=' --session-id {sid}', resume=' --resume {sid}',
        signed_in=either(has_file('.gemini/oauth_creds.json'), chose_provider('.gemini')),
        recorded=files('.gemini/tmp/*/chats/session-*-{short}.jsonl'),
        headless='gemini -p'),
    'opencode': dict(
        label='OpenCode', binary='opencode', places=('.opencode/bin',), processes=('opencode',), skip=' --auto',
        install='curl -fsSL https://opencode.ai/install | bash',
        login='opencode auth login', start='', resume=' --continue',
        signed_in=None, recorded=None,   # It answers on its free model without an account.
        headless='opencode run'),
    'cursor': dict(
        label='Cursor', binary='cursor-agent', processes=('cursor-agent', 'agent'), skip=' --force',
        install='curl https://cursor.com/install -fsS | bash',
        login='cursor-agent login', start=' --new-session-id {sid}', resume=' --resume {sid}',
        signed_in=has_file('.config/cursor/auth.json'), recorded=files('.cursor/chats/*/{sid}/store.db'),
        headless='cursor-agent -p'),
    'copilot': dict(
        label='GitHub Copilot', binary='copilot', processes=('copilot',), skip=' --allow-all',
        install='curl -fsSL https://gh.io/copilot-install | bash',
        login='copilot login',
        # One switch both starts a conversation under our id and returns to it; an empty one is not resumable.
        start=' --session-id={sid}', resume=' --session-id={sid}',
        # It uses the GitHub CLI's sign-in when there is one; its own goes to the keychain or this file.
        signed_in=either(has_file('.config/gh/hosts.yml'), mentions('.copilot/config.json', 'logged_in')), recorded=None,
        headless='copilot --allow-all-tools -p'),
}
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z')


def executable(agent, home=None):
    spec, home = CLI[agent], Path(home or Path.home())
    for folder in ('.local/bin', *spec.get('places', ())):
        path = home / folder / spec['binary']
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return shutil.which(spec['binary'])


def keeps_id(agent):
    """Whether the panel gives the conversation its id; otherwise the program continues its last one."""
    return agent in CLI and bool(CLI[agent]['start'])


def signed_in(agent, home=None):
    check = CLI[agent]['signed_in']
    return True if check is None else bool(check(Path(home or Path.home())))


def command(agent, sid=None, resume=False, skip=False, home=None):
    """The shell command for a pane. The full path: an installer's PATH line is not in a running tmux."""
    spec, home = CLI[agent], Path(home or Path.home())
    program = shlex.quote(executable(agent, home) or spec['binary'])
    flag = spec['skip'] if skip else ''
    if not spec['start']:
        return program + (spec['resume'] if resume else '') + flag
    if not isinstance(sid, str) or not UUID.match(sid):
        raise ValueError(f"{spec['label']} conversation ID is not saved; choose the conversation in its terminal")
    # A conversation without a single message was never written down: the same id simply starts it.
    known = resume and (spec['recorded'] is None or spec['recorded'](sid, home))
    return program + (spec['resume'] if known else spec['start']).format(sid=shlex.quote(sid)) + flag


def leader_note(home=None, hosts=()):
    """One paragraph for a leading agent: which other agents on this machine answer a task in one command.

    `hosts` are the names of the leader's own program, left out of the list."""
    home = Path(home or Path.home())
    ready = [f"`{spec['headless']} \"<task>\"` ({spec['label']})" for agent, spec in CLI.items()
             if agent not in hosts and executable(agent, home) and signed_in(agent, home)]
    if 'codex' not in hosts and (home / '.codex/auth.json').is_file() and ((home / '.local/bin/codex').is_file() or shutil.which('codex')):
        ready.insert(0, '`codex exec "<task>"` (Codex)')
    if not ready:
        return None
    return ('Other coding agents on this machine, for when the user asks for a second opinion or to hand a task over; '
            'run one in the project folder and read its answer: ' + '; '.join(ready) + '.')
