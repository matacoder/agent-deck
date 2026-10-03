#!/usr/bin/env python3
"""Remember only the top-level Claude/Codex conversation in a managed tmux pane."""
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


def parent_info(pid):
    if sys.platform == "darwin":
        result = subprocess.run(["ps", "-p", str(pid), "-o", "ppid=", "-o", "comm="],
                                capture_output=True, text=True, timeout=3)
        parent, name = result.stdout.strip().split(None, 1)
        return int(parent), os.path.basename(name)
    fields = {}
    for line in (Path("/proc") / str(pid) / "status").read_text().splitlines():
        key, _, value = line.partition(":")
        fields[key] = value.strip()
    return int(fields["PPid"]), fields["Name"]


def top_level(pane_pid, pid):
    agents = 0
    for _ in range(64):
        if pid == pane_pid:
            return agents == 1
        if pid <= 1:
            return False
        pid, name = parent_info(pid)
        if name in ("claude", "kimi", "kimi-code") or name.startswith("codex"):
            agents += 1
        if agents > 1:
            return False
    return False


def remember(data, pane, pid):
    sid = data.get("session_id")
    try:
        value = sid.removeprefix("session_") if data.get("client_type") == "kimi_code_cli" else sid
        if str(uuid.UUID(value)) != value:
            return
    except (ValueError, TypeError, AttributeError):
        return
    command = ["tmux"] + (["-L", os.environ["TMUX_SOCKET_NAME"]] if os.environ.get("TMUX_SOCKET_NAME") else [])
    result = subprocess.run([*command, "display-message", "-p", "-t", pane,
                             "#{pane_pid}\t#{session_name}"], capture_output=True, text=True, timeout=3)
    pane_pid, session = result.stdout.strip().split("\t")
    if session.startswith("cc-") and top_level(int(pane_pid), pid):
        subprocess.run([*command, "set-option", "-t", pane, "@cc_sid", sid],
                       capture_output=True, timeout=3)


def main():
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        return
    try:
        remember(json.load(sys.stdin), pane, os.getppid())
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired):
        pass  # The hook must never prevent a conversation from starting.



# Kimi launcher shares this existing release file so older updaters accept the archive.
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import threading

MODELS = ('k3', 'kimi-for-coding', 'kimi-for-coding-highspeed')
_lock = threading.Lock()


def config_path():
    return os.path.expanduser('~/.config/cc-panel/kimi.json')


def read():
    try:
        with open(config_path()) as stream:
            return json.load(stream)
    except FileNotFoundError:
        # Existing cc-kimi installations can be used without re-entering their key.
        try:
            with open(os.path.expanduser('~/.config/cc-kimi/env')) as stream:
                for line in stream:
                    match = re.fullmatch(r'(?:export\s+)?ANTHROPIC_API_KEY\s*=\s*(.*?)\s*', line.strip())
                    if match:
                        key = match[1].strip('\"\'')
                        if re.fullmatch(r'[!-~]{1,4096}', key):
                            return {'key': key, 'model': 'k3'}
        except FileNotFoundError:
            pass
        return {'key': '', 'model': 'k3'}


def status():
    data = read()
    return {'configured': bool(data.get('key')), 'model': data.get('model', 'k3')}


def atomic_write(path, content):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save(data):
    model = data.get('model', 'k3')
    key = data.get('key', '')
    if model not in MODELS:
        raise ValueError('неизвестная модель Kimi')
    if not isinstance(key, str) or (key and not re.fullmatch(r'[!-~]{1,4096}', key)):
        raise ValueError('Ключ должен содержать до 4096 символов без пробелов и переносов строк')
    if 'clear' in data and not isinstance(data['clear'], bool):
        raise ValueError('неверный запрос')
    with _lock:
        old = read()
        key = '' if data.get('clear') else (key or old.get('key', ''))
        atomic_write(config_path(), json.dumps({'key': key, 'model': model}))
    return status()


def executable(mode):
    if mode == 'claude-kimi':
        return os.path.expanduser('~/.local/bin/claude') if os.path.exists(os.path.expanduser('~/.local/bin/claude')) else shutil.which('claude')
    native = os.path.expanduser('~/.kimi-code/bin/kimi')
    return native if os.path.isfile(native) else shutil.which('kimi')


def launch(mode, args):
    data = read()
    if not data.get('key'):
        raise ValueError('Сначала сохраните ключ Kimi в настройках панели')
    binary = executable(mode)
    if not binary:
        raise ValueError('Сначала установите ' + ('Claude' if mode == 'claude-kimi' else 'Kimi Code'))
    env = dict(os.environ)
    # OAuth or another inherited provider must not override the selected Kimi key.
    for key in ('ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
        env.pop(key, None)
    model = data['model']
    if mode == 'claude-kimi':
        env.update(ANTHROPIC_API_KEY=data['key'], ANTHROPIC_BASE_URL='https://api.kimi.com/coding/', ANTHROPIC_MODEL=model,
                   CLAUDE_CODE_SUBAGENT_MODEL=model)
        for tier in ('OPUS', 'SONNET', 'HAIKU'):
            env['ANTHROPIC_DEFAULT_' + tier + '_MODEL'] = model
    else:
        home = os.path.expanduser('~/.config/cc-panel/kimi-native')
        hook = shlex.join([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'session_hook.py')])
        content = '\n'.join([
            'default_model = ' + json.dumps(model), 'telemetry = false',
            '[providers.deck]', 'type = "kimi"', 'base_url = "https://api.kimi.com/coding/v1"',
            'api_key_env = "AGENT_DECK_KIMI_API_KEY"', '[models.' + json.dumps(model) + ']',
            'provider = "deck"', 'model = ' + json.dumps(model),
            'max_context_size = ' + str(1048576 if model == 'k3' else 262144),
            'capabilities = ["thinking", "image_in", "video_in", "tool_use"]',
            '[[hooks]]', 'event = "SessionStart"', 'command = ' + json.dumps(hook), 'timeout = 5', ''])
        atomic_write(os.path.join(home, 'config.toml'), content)
        env.update(KIMI_CODE_HOME=home, AGENT_DECK_KIMI_API_KEY=data['key'])
    os.execve(binary, [binary, *args], env)



if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ('kimi', 'claude-kimi'):
        try:
            launch(sys.argv[1], sys.argv[2:])
        except (ValueError, OSError):
            print('Не удалось запустить Kimi. Проверьте установку агента и ключ в настройках панели.', file=sys.stderr)
            sys.exit(1)
    else:
        main()
