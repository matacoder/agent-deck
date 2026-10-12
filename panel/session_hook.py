#!/usr/bin/env python3
"""Remember only the top-level Claude/Codex conversation in a managed tmux pane; ask it to show results."""
import http.client
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
        return True


RESULTS_NOTE = """DeckAway session: the user follows it remotely, often from a phone, and cannot open localhost or files on this machine.
When a finished task has a visible result (page, UI, picture, document, chart), before the final message:
1. Screenshot the result and print each PNG/JPEG absolute path on its own line; the panel shows it as a picture.
2. If it opens in a browser, {link}
Nothing to look at: skip both silently."""
LINK_KNOWN = "serve it on {0} (not 0.0.0.0) and give the link http://{0}:<port>/<path>, never localhost."
LINK_UNKNOWN = "give a link on this machine's Tailscale address (`tailscale ip -4`), never localhost; no Tailscale: no link."


def show_results():
    # Read directly: the hook runs outside the panel. Missing or unreadable settings mean the default, on.
    try:
        with open(os.path.expanduser("~/.config/cc-panel/network.json")) as stream:
            return json.load(stream).get("show_results") is not False
    except (OSError, ValueError, AttributeError):
        return True


def tailscale_address():
    try:
        found = subprocess.run(["tailscale", "ip", "-4"], input="", capture_output=True, text=True,
                               timeout=2).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    return next((a for a in found if a.startswith("100.") and a.count(".") == 3
                 and a.replace(".", "").isdigit()), None)


def results_note():
    address = tailscale_address()
    return RESULTS_NOTE.format(link=LINK_KNOWN.format(address) if address else LINK_UNKNOWN)


CONTAINERS_NOTE = """Containers: `docker` and `docker compose` in this session run on another, stronger computer, {name}{at}, not on this one.
- This machine's files are not there: bind mounts of local paths (`-v ./src:/app`, compose `volumes: - ./...`) do not work. Put code into the image (`COPY`), use named volumes, `docker cp` or `docker compose watch`.
- Published ports open on that computer, not on localhost: {ports}
{local}"""
PORTS_KNOWN = "connect to {0}:<port>, and for a container's page give the link http://{0}:<port>/<path>."
PORTS_UNKNOWN = "connect to that computer's Tailscale address."
LOCAL_KNOWN = "- A container that must run on this machine: `DOCKER_HOST={0} docker ...`."
LOCAL_UNKNOWN = "- This machine has no Docker of its own running."


def containers_note(environ=os.environ):
    """What the panel wrote next to the Docker socket it gave this session; nothing when Docker is local."""
    host = environ.get("DOCKER_HOST", "")
    directory = os.path.expanduser("~/.config/cc-panel/docker/")
    if not host.startswith("unix://" + directory) or not host.endswith(".sock"):
        return None
    try:
        with open(host[7:-5] + ".json") as stream:
            data = json.load(stream)
        name, address, local = str(data["name"])[:100], str(data.get("address") or ""), str(data.get("local") or "")
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return CONTAINERS_NOTE.format(name=name, at=f" ({address})" if address else "",
                                  ports=PORTS_KNOWN.format(address) if address else PORTS_UNKNOWN,
                                  local=LOCAL_KNOWN.format(local) if local else LOCAL_UNKNOWN)


def session_agent(pane):
    """The agent the panel started in this pane, as it named it; '' when tmux does not say."""
    command = ["tmux"] + (["-L", os.environ["TMUX_SOCKET_NAME"]] if os.environ.get("TMUX_SOCKET_NAME") else [])
    try:
        return subprocess.run([*command, "display-message", "-p", "-t", pane, "#{@cc_agent}"],
                              capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def other_agents_note(host=""):
    """The leading agent learns which other agents here take a task in one command; never itself."""
    try:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.isdir(os.path.join(here, 'integrations')) and here not in sys.path:
            sys.path.insert(0, here)
        from integrations.agents import leader_note
        return leader_note(hosts=(host,))
    except Exception:  # The hook must never prevent a conversation from starting.
        return None


def main():
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        return
    try:
        data = json.load(sys.stdin)
        # Kimi's own CLI is left out: what it does with hook output is not known.
        if remember(data, pane, os.getppid()) and data.get("client_type") != "kimi_code_cli":
            notes = [note for note in (results_note() if show_results() else None, containers_note(), other_agents_note(session_agent(pane))) if note]
            if notes:
                print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                         "additionalContext": "\n\n".join(notes)}}))
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
# Tool search needs Anthropic's server-side tool_reference expansion, so other
# endpoints receive every schema (~30k tokens, mostly claude.ai-only tools) on
# each request. AskUserQuestion stays: Telegram relays questions from it.
LOCAL_TOOLS = 'Bash,Read,Edit,Write,Glob,Grep,AskUserQuestion,EnterPlanMode,ExitPlanMode'
KIMI_TOOLS = LOCAL_TOOLS + ',Agent,WebFetch,Skill'
_lock = threading.Lock()


def kimi_context(model):
    return 1048576 if model == 'k3' else 262144


def provider_args(tools, context=None):
    # Flag settings outrank the user's settings.json env, which may enable tool search for Anthropic.
    # Claude Code assumes 200k for unknown models, so auto-compact needs the real window.
    env = {'ENABLE_TOOL_SEARCH': 'false'}
    if context:
        env['CLAUDE_CODE_MAX_CONTEXT_TOKENS'] = str(context)
    return ['--tools', tools, '--settings', json.dumps({'env': env})]


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
    if len(args) >= 2 and args[0] == '--deck-model':
        if args[1] not in MODELS:
            raise ValueError('Unknown Kimi model')
        data['model'] = args[1]
        args = args[2:]
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
        for tier in ('FABLE', 'OPUS', 'SONNET', 'HAIKU'):
            env['ANTHROPIC_DEFAULT_' + tier + '_MODEL'] = model
        args = [*provider_args(KIMI_TOOLS, kimi_context(model)), *args]
    else:
        home = os.path.expanduser('~/.config/cc-panel/kimi-native')
        hook = shlex.join([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'session_hook.py')])
        content = '\n'.join([
            'default_model = ' + json.dumps(model), 'telemetry = false',
            '[providers.deck]', 'type = "kimi"', 'base_url = "https://api.kimi.com/coding/v1"',
            'api_key_env = "AGENT_DECK_KIMI_API_KEY"', '[models.' + json.dumps(model) + ']',
            'provider = "deck"', 'model = ' + json.dumps(model),
            'max_context_size = ' + str(kimi_context(model)),
            'capabilities = ["thinking", "image_in", "video_in", "tool_use"]',
            '[[hooks]]', 'event = "SessionStart"', 'command = ' + json.dumps(hook), 'timeout = 5', ''])
        atomic_write(os.path.join(home, 'config.toml'), content)
        env.update(KIMI_CODE_HOME=home, AGENT_DECK_KIMI_API_KEY=data['key'])
    os.execve(binary, [binary, *args], env)



def local_context(directory, binding):
    """Context window LM Studio actually loaded for the bound model."""
    from integrations.lmstudio import LMStudio, models
    profile = LMStudio(directory).get(binding['profile'])
    if profile['url'] != binding['url']:
        return None
    found = []
    try:
        found = models(profile['url'], profile.get('key', ''))
    except (OSError, ValueError, http.client.HTTPException):
        pass  # An unreachable server keeps the window seen at the last profile check.
    for model in found + profile.get('models', []):
        size = model.get('context_length') if isinstance(model, dict) and model.get('id') == binding['model'] else None
        if type(size) is int and size > 0:
            return size
    return None


def launch_provider(identity, model, args):
    """Claude Code on a saved Anthropic-compatible provider; the key travels in the environment only."""
    here = Path(__file__).resolve().parent
    if (here.parent / 'integrations').is_dir():
        sys.path.insert(0, str(here.parent))
    from integrations.providers import MODEL, Providers, environment
    if not MODEL.match(model):
        raise ValueError('Invalid model')
    provider = Providers(os.path.expanduser('~/.config/cc-panel/providers.json')).get(identity)
    binary = executable('claude-kimi')
    if not binary:
        raise ValueError('Install Claude Code first')
    os.execve(binary, [binary, *provider_args(KIMI_TOOLS), *args], environment(provider, model, os.environ))


def launch_local(identity, args):
    here = Path(__file__).resolve().parent
    if (here.parent / 'integrations').is_dir():
        sys.path.insert(0, str(here.parent))
    from integrations.relay import Bindings, read_json
    directory = Path(os.path.expanduser('~/.config/cc-panel/integrations'))
    binding = Bindings(directory).get(identity)
    relay = read_json(directory / 'model-relay.json', {})
    port, token = relay.get('port'), relay.get('token')
    if not isinstance(port, int) or not 1 <= port <= 65535 or not isinstance(token, str) or not token:
        raise ValueError('Local model relay is unavailable; restart the panel')
    import http.client
    import hmac
    import secrets
    nonce = secrets.token_hex(16)
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        connection.request('GET', '/health/'+nonce)
        response = connection.getresponse()
        body = response.read(4096)
        proof = json.loads(body).get('proof', '') if response.status == 200 else ''
        expected = hmac.new(token.encode(), nonce.encode(), 'sha256').hexdigest()
        if not isinstance(proof, str) or not hmac.compare_digest(proof, expected):
            raise ValueError('Local model relay could not be verified')
    finally:
        connection.close()
    binary = executable('claude-kimi')
    if not binary:
        raise ValueError('Install Claude Code first')
    env = dict(os.environ)
    for key in ('ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','CLAUDE_CODE_USE_BEDROCK','CLAUDE_CODE_USE_VERTEX','CLAUDE_CODE_USE_FOUNDRY'):
        env.pop(key, None)
    model = binding['model']
    env.update(ANTHROPIC_BASE_URL=f'http://127.0.0.1:{port}/providers/{identity}',
               ANTHROPIC_AUTH_TOKEN=token, ANTHROPIC_MODEL=model, CLAUDE_CODE_SUBAGENT_MODEL=model,
               CLAUDE_CODE_ATTRIBUTION_HEADER='0')
    for tier in ('FABLE','OPUS','SONNET','HAIKU'):
        env['ANTHROPIC_DEFAULT_'+tier+'_MODEL'] = model
    tuning = provider_args(LOCAL_TOOLS, local_context(directory, binding))
    os.execve(binary, [binary, '--model', model, *tuning, *args], env)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == 'pi-local':
        try:
            here = Path(__file__).resolve().parent
            if (here.parent / 'integrations').is_dir():
                sys.path.insert(0, str(here.parent))
            from integrations.pi import prepare_local
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument('--session-id', required=True)
            parser.add_argument('--deck-resume', action='store_true')
            parser.add_argument('--name')
            options = parser.parse_args(sys.argv[3:])
            binary, args, env = prepare_local(Path.home()/'.config/cc-panel/integrations', sys.argv[2], options.session_id, options.deck_resume, options.name)
            os.execve(binary, args, env)
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            print('Could not start Pi; check local profile, relay and saved conversation', file=sys.stderr)
            sys.exit(1)
    elif len(sys.argv) > 2 and sys.argv[1] == 'claude-local':
        try:
            launch_local(sys.argv[2], sys.argv[3:])
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            print('Could not start local model; check profile, relay and Claude Code installation', file=sys.stderr)
            sys.exit(1)
    elif len(sys.argv) > 3 and sys.argv[1] == 'claude-provider':
        try:
            launch_provider(sys.argv[2], sys.argv[3], sys.argv[4:])
        except (OSError, ValueError, KeyError, TypeError):
            print('Could not start Claude Code on this provider; check its key in Settings → Agents', file=sys.stderr)
            sys.exit(1)
    elif len(sys.argv) > 1 and sys.argv[1] in ('kimi', 'claude-kimi'):
        try:
            launch(sys.argv[1], sys.argv[2:])
        except (ValueError, OSError):
            print('Не удалось запустить Kimi. Проверьте установку агента и ключ в настройках панели.', file=sys.stderr)
            sys.exit(1)
    else:
        main()
