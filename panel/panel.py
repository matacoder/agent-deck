#!/usr/bin/env python3
"""Web panel for Claude Code sessions in tmux (runs as the dev user).

- Login form (PANEL_USER / PANEL_PASSWORD) -> signed HttpOnly cookie on everything else
- /t/...  is proxied (incl. websocket) to ttyd listening on a private unix socket
- tmux sessions are named cc-<name>; each stores its Claude session id in @cc_sid
- sessions are persisted to ~/.config/cc-panel/sessions.json and restored after a reboot
"""
import base64
import binascii
import dataclasses
import hashlib
import hmac
import ipaddress
import json
import os
import re
import shutil
import shlex
import select
import signal
import socket
import urllib.request
import urllib.error
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import parse_qs, urlencode
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
import updater
import session_hook as kimi_config

TAILNET = ipaddress.ip_network("100.64.0.0/10")


def usable_bind_host(host, run=subprocess.run):
    """A Tailscale re-login can give the node a new 100.x address; the panel would then fail to bind and
    restart forever, locking a remote user out. Only a Tailscale address is re-resolved, and only to the
    node's current Tailscale address, so the panel is never exposed more widely than configured."""
    try:
        with socket.socket() as probe:
            probe.bind((host, 0))
        return host
    except OSError:
        pass
    try:
        if ipaddress.ip_address(host) not in TAILNET:
            return host
        found = run(["tailscale", "ip", "-4"], input="", capture_output=True, text=True, timeout=5).stdout.split()
    except (ValueError, OSError, subprocess.SubprocessError):
        return host
    current = next((a for a in found if a.count(".") == 3 and ipaddress.ip_address(a) in TAILNET), None)
    if current:
        print(f"BIND_HOST {host} is no longer an address of this machine; using Tailscale's {current}. "
              "Re-run the installer (sudo ./update.sh) to store it.", flush=True)
        return current
    return host


BIND_HOST = usable_bind_host(os.environ.get("BIND_HOST", "127.0.0.1"))
BIND_PORT = int(os.environ.get("BIND_PORT", "8790"))
PANEL_USER = os.environ.get("PANEL_USER", "dev")
PANEL_PASSWORD = os.environ["PANEL_PASSWORD"]
TTYD_SOCK = os.environ.get("TTYD_SOCK", f"/run/user/{os.getuid()}/cc-ttyd.sock")
PROJECTS = os.path.expanduser(os.environ.get("PROJECTS_DIR", "~/dev"))
TMUX_COMMAND = ["tmux"] + (["-L", os.environ["TMUX_SOCKET_NAME"]] if os.environ.get("TMUX_SOCKET_NAME") else [])
PREFIX = "cc-"
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
PROJ_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
GIT_RE = re.compile(r"^(https://|ssh://|git@)[\w.@:/~+-]+$")
BRANCH_RE = re.compile(r"^[\w][\w./-]{0,63}$")
# requests from these networks are a local reverse proxy (e.g. Traefik in Docker): trust X-Forwarded-*
TRUSTED_PROXIES = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
if os.environ.get("AGENT_DECK_CONTAINER"):
    # Every client of a container arrives from Docker's or Podman's gateway (172.x, 10.0.2.2): trusting
    # X-Forwarded-For there would let anyone pick their own address and dodge the per-IP login limit.
    TRUSTED_PROXIES = [ipaddress.ip_network(n.strip()) for n in os.environ.get("AGENT_DECK_TRUSTED_PROXIES", "").split(",") if n.strip()]
COOKIE = "cc_auth"
COOKIE_DAYS = 90
MAX_IMAGE_BYTES = 200 * 1024 * 1024
MAX_FILE_BYTES = 200 * 1024 * 1024
UPLOAD_DIR = os.path.expanduser("~/.config/cc-panel/uploads")
ATTACHMENT_RE = re.compile(r"^[0-9a-f]{32}(?:\.(png|jpg|webp|gif)|--[A-Za-z0-9_.-]{1,100})$")
HERE = os.path.dirname(os.path.abspath(__file__))
# Source packages live next to panel/; installed packages live inside the runtime.
if os.path.isdir(os.path.join(os.path.dirname(HERE), "integrations")):
    sys.path.insert(0, os.path.dirname(HERE))
try:
    import locales
    if not {'en', 'ru'} <= {item['code'] for item in locales.available()}:
        locales = None
except ModuleNotFoundError:
    locales = None  # Legacy updaters repair the optional catalog package on the next run.
DEFAULT_LANGUAGE = os.environ.get("PANEL_LANGUAGE", "en")
try:
    from integrations.questions import parse_question, transcript_questions, matches_screen, QuestionNotReady
    from integrations.telegram import Telegram
except ModuleNotFoundError:
    Telegram = None  # A pre-0.7 updater installs core files first; its next run repairs packages.
try:
    from integrations.lmstudio import LMStudio
    from integrations.relay import Relay, Bindings
except ModuleNotFoundError:
    LMStudio = None

from integrations.names import unique_name
from integrations.decks import RemoteDecks, UnavailableDecks, remote_path
from integrations.preferences import ProjectDirectory, NetworkSettings
project_directory = ProjectDirectory(os.path.expanduser('~'), PROJECTS)


network_settings = NetworkSettings(os.path.expanduser('~'))
_decks_dir = os.path.expanduser('~/.config/cc-panel/integrations')
try:
    remote_decks = RemoteDecks(_decks_dir, f'http://{BIND_HOST}:{BIND_PORT}')
except (OSError, ValueError) as _error:
    # A broken connection list must not take the whole panel down; the file is left untouched.
    _decks_message = (f'Agent Deck connections are disabled: {os.path.join(_decks_dir, "decks.json")} '
                      f'could not be loaded ({_error}). Fix or remove this file (it must be a regular JSON object '
                      'file, not a symlink) and restart cc-panel.')
    print(_decks_message, flush=True)
    remote_decks = UnavailableDecks(_decks_message)
from integrations.gateway import Gateway
from integrations import usage as usage_limits
gateway = Gateway(lambda: remote_decks)  # Looked up on each call: the service can be replaced.


_lmstudio = None
_model_relay = None
_lm_lock = threading.RLock()


def model_service():
    global _lmstudio, _model_relay
    if LMStudio is None:
        raise ValueError('LM Studio components are not installed; update the panel')
    with _lm_lock:
        if _lmstudio is None:
            directory = os.path.expanduser('~/.config/cc-panel/integrations')
            _lmstudio = LMStudio(directory)
            _model_relay = Relay(directory, _lmstudio)
    return _lmstudio


def saved_source(name):
    try:
        source = json.loads(opt(name, '@cc_source') or 'null')
        return source if isinstance(source, dict) or source is None else {"kind":"invalid"}
    except (ValueError, TypeError):
        return {"kind":"invalid"}


def session_source(data, agent):
    source = data.get('source')
    if source is None:
        if agent == 'pi':
            raise ValueError('Select a local model for Pi')
        return None
    if not isinstance(source, dict):
        raise ValueError('Invalid model source')
    kind = source.get('kind')
    if kind == 'default':
        if agent == 'pi':
            raise ValueError('Select a local model for Pi')
        return None
    if kind == 'kimi' and agent in ('claude', 'claude-kimi', 'kimi'):
        model = source.get('model', kimi_config.status()['model'])
        if model not in kimi_config.MODELS:
            raise ValueError('Unknown Kimi model')
        return {'kind':'kimi','model':model,'label':'Kimi · '+model}
    if kind == 'lmstudio' and agent in ('claude', 'pi'):
        service = model_service()
        profile = service.get(source.get('profile'))
        model = source.get('model')
        models = profile.get('models', [])
        if not isinstance(model, str) or not any(m['id'] == model for m in models):
            raise ValueError('Select a model from the LM Studio profile')
        if agent == 'pi':
            from integrations.pi import executable
            if not executable():
                raise ValueError('Install Pi first')
        elif not kimi_config.executable('claude-kimi'):
            raise ValueError('Install Claude Code first')
        binding = _model_relay.bindings.create(profile, model)
        return {'kind':'lmstudio','profile':profile['id'],'model':model,'binding':binding,
                'label':'LM Studio · '+profile['name']+' · '+model}
    raise ValueError('This model source is not compatible with the selected agent')


def action_lm_save(data):
    service = model_service()
    identity = data.get('id')
    if identity:
        old = service.get(identity)
        from integrations.lmstudio import endpoint
        if endpoint(data.get('url', '')) != old['url']:
            if any((session.get('source') or {}).get('profile') == identity for session in list_sessions() + list(load_state().get('sessions', {}).values())):
                raise ValueError('Close sessions using this profile before changing its address; add a separate profile instead')
    return {'profile': service.save(data)}


def action_lm_remove(data):
    identity = data.get('id')
    for session in list_sessions() + list(load_state().get("sessions", {}).values()):
        source = session.get('source') or {}
        if source.get('profile') == identity:
            raise ValueError('Close sessions using this LM Studio profile before removing it')
    model_service().remove(identity)
    return {'lmstudio': model_service().status()}


try:
    with open(os.path.join(HERE, "VERSION")) as version_file:
        VERSION = version_file.read().strip()
except OSError:
    VERSION = "dev"
UPDATE_REPO = os.environ.get("UPDATE_REPO", "matacoder/agent-deck")   # "" disables the update check
CHECKOUT = os.environ.get("CHECKOUT", "")                             # where install.sh ran from
UPDATE_STATE = os.path.expanduser("~/.config/cc-panel/update.json")
action_lock = threading.Lock()
actions_in_progress = 0
_release_lock = threading.RLock()
_auto_updates_lock = threading.RLock()
_auto_updates = None
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
STATIC = {"/icon-180.png": "image/png", "/icon-192.png": "image/png", "/icon-512.png": "image/png",
          "/manifest.webmanifest": "application/manifest+json"}


metrics_lock = threading.Lock()
metrics_cpu_sample = None
metrics_cpu_percent = None
metrics_sample_time = 0.0


def server_metrics():
    """Host CPU utilization between samples and RAM excluding reclaimable memory."""
    global metrics_cpu_sample, metrics_cpu_percent, metrics_sample_time
    result = {"cpu_percent": None, "memory_used": None, "memory_total": None}
    with metrics_lock:
        if sys.platform == "darwin":
            return mac_server_metrics(result)
        try:
            now = time.monotonic()
            if metrics_cpu_sample is None or now - metrics_sample_time >= 1:
                with open("/proc/stat") as f:
                    fields = f.readline().split()
                if fields[0] != "cpu" or len(fields) < 5:
                    raise ValueError("missing CPU counters")
                # guest/guest_nice are already included in user/nice.
                counters = [int(value) for value in fields[1:9]]
                total = sum(counters)
                idle = counters[3] + (counters[4] if len(counters) > 4 else 0)
                metrics_cpu_percent = None
                if metrics_cpu_sample is not None:
                    delta = total - metrics_cpu_sample[0]
                    idle_delta = idle - metrics_cpu_sample[1]
                    if delta > 0 and idle_delta >= 0:
                        metrics_cpu_percent = round(max(0, min(100, 100 * (delta - idle_delta) / delta)), 1)
                metrics_cpu_sample = (total, idle)
                metrics_sample_time = now
            result["cpu_percent"] = metrics_cpu_percent
        except (OSError, ValueError, IndexError):
            metrics_cpu_sample = None
            metrics_cpu_percent = None
        try:
            with open("/proc/meminfo") as f:
                memory = {parts[0].rstrip(":"): int(parts[1]) * 1024
                          for line in f if len(parts := line.split()) >= 2}
            total = memory["MemTotal"]
            available = memory["MemAvailable"]
            if total > 0:
                result.update(memory_total=total, memory_used=max(0, min(total, total - available)))
        except (OSError, ValueError, KeyError):
            pass
    return result


def mac_server_metrics(result):
    """Use cumulative counters: HTTP handlers run on different threads."""
    global metrics_cpu_sample, metrics_cpu_percent, metrics_sample_time
    try:
        import psutil
        now = time.monotonic()
        if metrics_cpu_sample is None or now - metrics_sample_time >= 1:
            cpu = psutil.cpu_times()
            total, idle = sum(cpu), cpu.idle
            metrics_cpu_percent = None
            if metrics_cpu_sample is not None:
                delta, idle_delta = total - metrics_cpu_sample[0], idle - metrics_cpu_sample[1]
                if delta > 0 and idle_delta >= 0:
                    metrics_cpu_percent = round(max(0, min(100, 100 * (delta - idle_delta) / delta)), 1)
            metrics_cpu_sample = (total, idle)
            metrics_sample_time = now
        memory = psutil.virtual_memory()
        result.update(cpu_percent=metrics_cpu_percent, memory_total=memory.total,
                      memory_used=max(0, min(memory.total, memory.total - memory.available)))
    except (ImportError, OSError):
        pass
    return result


def _cookie_key():
    """Per-install secret mixed with the password: changing the password logs everyone out."""
    path = os.path.expanduser("~/.config/cc-panel/secret")
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, os.urandom(32))
        os.close(fd)
    with open(path, "rb") as f:
        return hashlib.sha256(f.read() + PANEL_PASSWORD.encode()).digest()


COOKIE_KEY = _cookie_key()
failed_logins = {}  # ip -> (count, last_ts), reservations include in-flight attempts
login_lock = threading.Lock()
input_locks = {}
input_locks_lock = threading.Lock()


def make_token():
    exp = str(int(time.time()) + COOKIE_DAYS * 86400)
    sig = hmac.new(COOKIE_KEY, exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def token_valid(token):
    exp, _, sig = (token or "").partition(".")
    if not exp.isdigit() or len(exp) > 12 or int(exp) < time.time():
        return False
    return hmac.compare_digest(sig, hmac.new(COOKIE_KEY, exp.encode(), hashlib.sha256).hexdigest())

# Isolated remote terminals (Settings -> Network): a connected computer's ttyd page is served under a
# signed capability path with `CSP: sandbox`, so its scripts run in an opaque origin and cannot reach
# the gateway's API, cookies or other computers. Its token and WebSocket requests carry no cookie
# (opaque origin), so the path itself is the credential: bound to one computer, valid for 12 hours.
CAPABILITY_TTL = 2 * 3600  # Every terminal opening mints a new one; a leaked link soon stops working.
CAPABILITY_IN_LOG = re.compile(r'/c/[^/\s]+/')
ISOLATED_ROUTE = re.compile(r'^/deck/([0-9a-f]{24})/c/([0-9a-f]{1,12}\.[0-9a-f]{64})(/t(?:/.*)?)$')
SANDBOX = "sandbox allow-scripts allow-forms allow-popups allow-modals allow-downloads"


TERMINAL_EPOCH = os.path.expanduser("~/.config/cc-panel/terminal-epoch")


def terminal_epoch():
    try:
        with open(TERMINAL_EPOCH) as stream:
            return int(stream.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def revoke_terminal_links():
    """Logging out ends every isolated terminal link issued so far, without waiting for them to expire."""
    from pathlib import Path
    from integrations.relay import private_write
    private_write(Path(TERMINAL_EPOCH), terminal_epoch() + 1)


def _capability_signature(identity, expiry):
    message = f"deck-terminal:{identity}:{expiry}:{terminal_epoch()}"
    return hmac.new(COOKIE_KEY, message.encode(), hashlib.sha256).hexdigest()


def terminal_capability(identity, now=None):
    expiry = format(int((now or time.time()) + CAPABILITY_TTL), "x")
    return expiry + "." + _capability_signature(identity, expiry)


def capability_valid(identity, token, now=None):
    expiry, _, sig = token.partition(".")
    if int(expiry, 16) < (now or time.time()):
        return False
    return hmac.compare_digest(sig, _capability_signature(identity, expiry))

os.makedirs(project_directory.get(), exist_ok=True)


def tmux(*args, check=True):
    r = subprocess.run([*TMUX_COMMAND, *args], capture_output=True, text=True, timeout=10)
    if check and r.returncode:
        raise RuntimeError(r.stderr.strip() or f"tmux {args[0]} failed")
    return r.stdout


def session_exists(name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        return False
    return subprocess.run([*TMUX_COMMAND, "has-session", "-t", f"={PREFIX}{name}:"], capture_output=True).returncode == 0


def opt(name, key):
    out = tmux("show-options", "-t", f"={PREFIX}{name}:", "-qv", key, check=False).strip()
    return out or None


def session_group(path):
    roots = {project_directory.get(), os.path.expanduser('~/projects'), os.path.expanduser('~/dev')}
    for root in sorted(roots, key=len, reverse=True):
        root = root.rstrip(os.sep)
        if path.startswith(root + os.sep):
            return os.path.relpath(path, root).split(os.sep)[0].removesuffix('.worktrees')
    return 'другое'


def list_sessions(preview_name=None):
    fmt = ("#{session_name}\t#{session_created}\t#{session_attached}\t#{pane_current_path}\t"
           "#{pane_current_command}\t#{window_activity}\t#{@cc_agent}\t#{@cc_sid}\t#{@cc_skip}\t#{@cc_source}\t#{@cc_title}")
    out = tmux("list-sessions", "-F", fmt, check=False)
    result = []
    for line in out.splitlines():
        sname, created, attached, path, cmd, activity, agent, sid, skip, source, title = (line.split("\t") + [""] * 11)[:11]
        if not sname.startswith(PREFIX):
            continue
        name = sname[len(PREFIX):]
        group = session_group(path)
        agent = agent or "claude"
        item = {
            "name": name, "title": title or name, "created": int(created or 0), "attached": int(attached or 0),
            "activity": int(activity or 0), "group": group, "agent": agent,
            "path": path, "running": is_running(agent, cmd), "command": cmd,
            "sid": sid or None, "skip": skip == "1",
        }
        try:
            model_source = json.loads(source or 'null')
            if isinstance(model_source, dict):
                item['source'] = {k:v for k,v in model_source.items() if k in ('kind','profile','model','binding','label')}
        except ValueError:
            pass
        if name == preview_name:
            if model := session_model(agent, sid):
                item["model"] = model
            preview_ansi = tmux("capture-pane", "-p", "-e", "-J", "-t", f"={sname}:", "-S", "-2000", check=False)
            preview = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", preview_ansi).rstrip().splitlines()
            item.update(preview="\n".join(preview[-2000:]), preview_ansi=preview_ansi)
        result.append(item)
    return sorted(result, key=lambda s: (s["group"], s["name"]))


AGENTS = {
    # name: (label, process names as seen in pane_current_command, skip-permissions flag)
    "claude": ("Claude", {"claude"}, " --dangerously-skip-permissions"),
    "codex": ("Codex", {"codex", "codex-x86_64-un", "codex-aarch64-u"}, " --dangerously-bypass-approvals-and-sandbox"),
    "claude-kimi": ("Claude · Kimi", {"claude"}, " --dangerously-skip-permissions"),
    "kimi": ("Kimi Code", {"kimi", "kimi-code"}, " --auto"),
    "pi": ("Pi", {"pi", "node"}, ""),
    "shell": ("Терминал", set(), ""),
}
SHELLS = {"bash", "zsh", "sh", "fish", "dash"}
INSTALLERS = {
    "claude": "curl -fsSL https://claude.ai/install.sh | bash",
    "codex": "curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh",
}
INSTALLERS["kimi"] = "curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash"
INSTALLERS["pi"] = 'npm install --global --prefix "$HOME/.local" @earendil-works/pi-coding-agent@1.0.2 --no-audit --no-fund'
LOGINS = {
    "claude": "claude",  # first start asks to log in; afterwards /login switches accounts
    "codex": "codex login --device-auth",
}


def is_running(agent, cmd):
    if agent == "shell":
        return cmd not in SHELLS
    return cmd in AGENTS[agent][1]


def agent_cmd(agent, sid=None, resume=False, skip=False, name=None, source=None):
    """Shell command that starts (or resumes) the agent in a pane; None for a plain terminal."""
    if agent == "shell":
        return None
    if source is not None:
        if not isinstance(source, dict) or source.get('kind') not in ('kimi','lmstudio'):
            raise ValueError('Invalid saved model source')
        if source['kind'] == 'lmstudio' and agent not in ('claude', 'pi'):
            raise ValueError('Saved local source is incompatible with this agent')
        if source['kind'] == 'kimi' and (agent not in ('kimi','claude-kimi') or source.get('model') not in kimi_config.MODELS):
            raise ValueError('Invalid saved Kimi source')
    flag = AGENTS[agent][2] if skip else ""
    launcher = ""
    if source and source.get('kind') == 'lmstudio':
        model_service()
        binding = _model_relay.bindings.get(source.get('binding'))
        profile = model_service().get(binding['profile'])
        if binding['profile'] != source.get('profile') or binding['model'] != source.get('model') or binding['url'] != profile['url']:
            raise ValueError('Saved model binding differs from its profile')
        if _model_relay.server is None:
            raise ValueError('Local model relay is unavailable; restart the panel')
        launcher = shlex.join([sys.executable, os.path.join(HERE, 'session_hook.py'), 'pi-local' if agent == 'pi' else 'claude-local', source['binding']])
    elif agent in ("kimi", "claude-kimi"):
        if not kimi_config.status()["configured"]:
            raise ValueError("Сначала сохраните ключ Kimi в настройках панели")
        if not kimi_config.executable(agent):
            raise ValueError("Сначала установите " + ("Claude" if agent == "claude-kimi" else "Kimi Code"))
        launcher = shlex.join([sys.executable, os.path.join(HERE, "session_hook.py"), agent])
        if source and source.get('kind') == 'kimi':
            launcher += ' --deck-model '+shlex.quote(source['model'])
    if agent == "pi":
        if not source or source.get('kind') != 'lmstudio' or not valid_sid(sid):
            raise ValueError('Pi requires a saved local model and conversation ID')
        return launcher + ' --session-id ' + shlex.quote(sid) + (' --deck-resume' if resume else '') + (' --name '+shlex.quote(name) if name else '')
    if agent == "kimi":
        if resume and not (isinstance(sid, str) and sid.startswith("session_") and valid_sid(sid[8:])):
            raise ValueError("ID разговора Kimi не сохранён. Выберите разговор вручную в терминале.")
        return launcher + (" --session " + shlex.quote(sid) if resume else "") + flag
    if agent == "codex":
        if resume and not valid_sid(sid):
            raise ValueError("ID разговора Codex не сохранён. Возобновите нужный разговор через codex resume; автоматический выбор последнего отключён.")
        return f"codex --no-daemon --no-alt-screen resume {shlex.quote(sid)}{flag}" if resume else f"codex --no-daemon --no-alt-screen{flag}"
    if resume:
        if transcript_exists(sid):
            return (launcher or "claude") + f" --resume {sid}{flag}"
        raise ValueError("Транскрипт этого разговора Claude не найден. Выберите разговор вручную или запустите новый.")
    return (launcher or "claude") + f" --session-id {sid}{flag}" + (f" -n {name}" if name else "")


def type_line(name, text):
    paste_to_tmux(name, text, bracketed=False)
    tmux("send-keys", "-t", f"={PREFIX}{name}:", "Enter")


def process_exists(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def stop_children(name):
    """Terminate whatever runs in the pane's shell (normally claude)."""
    shell = int(tmux("display-message", "-p", "-t", f"={PREFIX}{name}:", "#{pane_pid}").strip())
    kids = subprocess.run(["pgrep", "-P", str(shell)], capture_output=True, text=True).stdout.split()
    pids = [int(p) for p in kids]
    for sig, wait in ((signal.SIGTERM, 8), (signal.SIGKILL, 2)):
        for p in pids:
            try:
                os.kill(p, sig)
            except ProcessLookupError:
                pass
        deadline = time.time() + wait
        while time.time() < deadline and any(process_exists(p) for p in pids):
            time.sleep(0.2)
        if not any(process_exists(p) for p in pids):
            return


def add_worktree(repo, project, name, branch):
    """git worktree in ~/projects/<project>.worktrees/<name>, branch created if missing."""
    if not BRANCH_RE.match(branch) or ".." in branch:
        raise ValueError("неверное имя ветки")
    if not os.path.exists(os.path.join(repo, ".git")):
        raise ValueError(f"{project} не git-репозиторий: укажите Git URL или сделайте git init")
    wt = os.path.join(project_directory.get(), f"{project}.worktrees", name)
    if os.path.exists(wt):
        return wt
    exists = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
                            capture_output=True).returncode == 0
    args = ["git", "-C", repo, "worktree", "add", wt] + ([branch] if exists else ["-b", branch])
    r = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise ValueError("git worktree: " + r.stderr.strip()[-500:])
    return wt


def resolve_path(d, name):
    """Either an existing folder under $HOME ("path") or ~/projects/<project> (+clone, +worktree)."""
    home = os.path.realpath(os.path.expanduser("~"))
    if d.get("path"):
        if not isinstance(d["path"], str):
            raise ValueError("неверный путь проекта")
        path = os.path.realpath(d["path"])
        if not (path == home or path.startswith(home + os.sep)) or not os.path.isdir(path):
            raise ValueError("папка должна существовать и быть внутри домашнего каталога")
        return path
    project = d.get("project") or name
    if not isinstance(project, str) or not PROJ_RE.fullmatch(project) or ".." in project or project.endswith(".worktrees"):
        raise ValueError("неверное имя проекта")
    path = os.path.join(project_directory.get(), project)
    git = (d.get("git") or "").strip()
    if git and not os.path.exists(path):
        if not GIT_RE.match(git):
            raise ValueError("неверный git URL")
        r = subprocess.run(["git", "clone", "--", git, path], capture_output=True, text=True, timeout=300,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if r.returncode:
            raise ValueError("git clone: " + r.stderr.strip()[-500:])
    os.makedirs(path, exist_ok=True)
    if d.get("worktree"):
        path = add_worktree(path, project, name, (d.get("branch") or name).strip())
    return path


def create_session(name, path, agent, skip, sid=None, command=None, source=None):
    tmux("new-session", "-d", "-s", f"{PREFIX}{name}", "-c", path, "-x", "200", "-y", "50")
    tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_agent", agent)
    tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_skip", "1" if skip else "0")
    if sid:
        tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_sid", sid)
    if source:
        tmux('set-option', '-t', f'={PREFIX}{name}:', '@cc_source', json.dumps(source, separators=(',',':')))
    if command:
        time.sleep(0.5)
        type_line(name, command)


session_creation_lock = threading.Lock()


def action_new(d):
    with session_creation_lock:
        return _action_new(d)


def _action_new(d):
    name, agent = d.get("name", ""), d.get("agent") or "claude"
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError("имя сессии: латиница, цифры, - и _, до 32 символов")
    if agent not in AGENTS:
        raise ValueError("неизвестный агент")
    name = unique_name(name, session_exists, 32)
    path = resolve_path(d, name)
    skip = bool(d.get("skip")) and agent not in ("shell", "pi")
    sid = str(uuid.uuid4()) if agent in ("claude", "claude-kimi", "pi") else None
    source = session_source(d, agent)
    if source and source.get('kind') == 'kimi' and agent == 'claude':
        agent = 'claude-kimi'
    if source is None:
        create_session(name, path, agent, skip, sid, agent_cmd(agent, sid, False, skip, name))
    else:
        try:
            create_session(name, path, agent, skip, sid, agent_cmd(agent, sid, False, skip, name, source), source)
        except Exception:
            if source.get('binding'):
                _model_relay.bindings.remove(source['binding'])
            raise
    return {"name": name}


def action_rename(d):
    name, title = d.get('name', ''), d.get('title', '')
    if not isinstance(name, str) or not NAME_RE.fullmatch(name) or not session_exists(name):
        raise ValueError('Session not found')
    if not isinstance(title, str) or not title.strip() or len(title) > 100 or not title.isprintable():
        raise ValueError('Invalid session title')
    with session_creation_lock:
        used = {(s.get('title') or s['name']).casefold() for s in list_sessions() if s['name'] != name}
        title = unique_name(title.strip(), lambda value: value.casefold() in used, 100)
        tmux('set-option', '-t', f'={PREFIX}{name}:', '@cc_title', title)
    return {'name': name, 'title': title}


def action_restart(d):
    name = d.get("name", "")
    if not session_exists(name):
        raise ValueError("нет такой сессии")
    skip, agent = opt(name, "@cc_skip") == "1", opt(name, "@cc_agent") or "claude"
    sid = opt(name, "@cc_sid")
    new = d.get("mode") == "new"
    if new and agent in ("claude", "claude-kimi", "pi"):
        sid = str(uuid.uuid4())
    elif new and agent in ("codex", "kimi"):
        sid = None
    source = saved_source(name)
    cmd = agent_cmd(agent, sid, not new, skip, name, source)
    target = f"={PREFIX}{name}:"
    path = tmux("display-message", "-p", "-t", target, "#{pane_current_path}").strip()
    shell = tmux("show-options", "-gv", "default-shell").strip() or "/bin/sh"
    stop_children(name)
    if new and agent != "shell":
        if sid:
            tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_sid", sid)
        else:
            tmux("set-option", "-t", f"={PREFIX}{name}:", "-u", "@cc_sid")
    # A killed TUI can leave mouse reporting and queued input in the old PTY.
    # Respawning resets tmux's terminal modes and runs the command directly,
    # so mouse reports cannot become part of the agent's shell command.
    # An interactive shell puts the agent in the foreground process group;
    # without job control tmux reports bash and the UI treats a running agent as stopped.
    script = "clear; " + (f"{cmd}; " if cmd else "") + "exec " + shlex.quote(shell)
    tmux("respawn-pane", "-k", "-t", target, "-c", path,
         shlex.join([shell, "-lic", script]))


def action_kill(d):
    name = d.get("name", "")
    if session_exists(name):
        source = saved_source(name)
        tmux("kill-session", "-t", f"={PREFIX}{name}:")
        if source and source.get("kind") == "lmstudio":
            model_service()
            _model_relay.bindings.remove(source.get("binding"))
    if isinstance(name, str) and NAME_RE.fullmatch(name):
        shutil.rmtree(os.path.join(UPLOAD_DIR, name), ignore_errors=True)


def attachment_dir(name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError("неверное имя сессии")
    return os.path.join(UPLOAD_DIR, name)


def upload_folder(name, filename):
    folder = attachment_dir(name)
    if not session_exists(name):
        raise ValueError("нет такой сессии")
    if (opt(name, "@cc_agent") or "claude") == "shell":
        raise ValueError("файлы можно приложить к Claude или Codex")
    if filename is not None and (not isinstance(filename, str) or not filename or len(filename) > 255
                                 or any(c in filename for c in ("/", "\\", "\0", "\n", "\r"))):
        raise ValueError("неверное имя файла")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    if os.path.islink(UPLOAD_DIR) or os.path.islink(folder):
        raise ValueError("папка загрузок не должна быть символической ссылкой")
    return folder


def attachment_name(head, filename):
    """Images are recognised by content; anything else keeps its sanitised name."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = "png"
    elif head.startswith(b"\xff\xd8\xff"):
        ext = "jpg"
    elif head.startswith((b"GIF87a", b"GIF89a")):
        ext = "gif"
    elif head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        ext = "webp"
    else:
        ext = None
        if not filename:
            raise ValueError("укажите имя файла")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", filename or "file")[-100:]
    return uuid.uuid4().hex + ("." + ext if ext else "--" + safe_name), ext


def action_upload(d):
    name = d.get("name", "")
    filename = d.get("filename")
    folder = upload_folder(name, filename)
    limit = MAX_FILE_BYTES if filename else MAX_IMAGE_BYTES
    encoded = d.get("data", "")
    if not isinstance(encoded, str) or len(encoded) > ((limit + 2) // 3) * 4:
        raise ValueError("файл слишком большой")
    try:
        image = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("неверные данные файла") from None
    if (not image and not filename) or len(image) > limit:
        raise ValueError("файл слишком большой или пустой")
    attachment, ext = attachment_name(image[:16], filename)
    if ext and len(image) > MAX_IMAGE_BYTES:
        raise ValueError("изображение слишком большое (максимум 200 МБ)")
    fd = os.open(os.path.join(folder, attachment), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(image)
    return {"attachment": attachment, "kind": "image" if ext else "file", "size": len(image)}


def store_streamed_upload(name, filename, length, stream):
    """Raw-body upload: written to disk in chunks, so phones never base64 a large video in memory."""
    if not 0 < length <= MAX_FILE_BYTES:
        raise ValueError("файл слишком большой или пустой")
    folder = upload_folder(name, filename)
    partial = os.path.join(folder, ".incoming-" + uuid.uuid4().hex)
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("загрузка прервана")
                out.write(chunk)
                remaining -= len(chunk)
        with open(partial, "rb") as source:
            head = source.read(16)
        attachment, ext = attachment_name(head, filename)
        os.rename(partial, os.path.join(folder, attachment))
        return {"attachment": attachment, "kind": "image" if ext else "file", "size": length}
    finally:
        if os.path.exists(partial):
            os.unlink(partial)


def attachment_paths(name, attachments):
    if not isinstance(attachments, list) or len(attachments) > 4:
        raise ValueError("можно приложить до 4 файлов")
    folder = attachment_dir(name)
    paths = []
    for attachment in attachments:
        if not isinstance(attachment, str) or not ATTACHMENT_RE.fullmatch(attachment):
            raise ValueError("неверное вложение")
        path = os.path.join(folder, attachment)
        if not os.path.isfile(path) or os.path.islink(path):
            raise ValueError("вложение не найдено; приложите изображение заново")
        paths.append(path)
    return paths


def action_discard_upload(d):
    for path in attachment_paths(d.get("name", ""), d.get("attachments", [])):
        os.unlink(path)


INCOMING_RE = re.compile(r'\.incoming-[0-9a-f]{32}')


def cleanup_uploads(max_age=7 * 86400):
    """Keep sent images long enough for deferred agent reads, but not forever."""
    if not os.path.isdir(UPLOAD_DIR):
        return
    cutoff = time.time() - max_age
    with os.scandir(UPLOAD_DIR) as folders:
        for folder in folders:
            if not folder.is_dir(follow_symlinks=False):
                continue
            with os.scandir(folder.path) as entries:
                for entry in entries:
                    # A restart mid-upload leaves its partial file; none takes longer than an hour.
                    partial = INCOMING_RE.fullmatch(entry.name)
                    if ((ATTACHMENT_RE.fullmatch(entry.name) or partial) and entry.is_file(follow_symlinks=False)
                            and entry.stat(follow_symlinks=False).st_mtime < (time.time() - 3600 if partial else cutoff)):
                        os.unlink(entry.path)
            try:
                os.rmdir(folder.path)
            except OSError:
                pass


_paste_raw_supported = None


def paste_to_tmux(name, text, bracketed=True):
    global _paste_raw_supported
    if _paste_raw_supported is None:
        # tmux 3.7 sanitizes control bytes unless -S is supplied; older tmux
        # rejects that flag. Detect the capability from its command synopsis.
        commands = tmux("list-commands")
        _paste_raw_supported = bool(re.search(r"^paste-buffer[^\n]*\[[^]\n]*S", commands, re.M))
    # stdin avoids tmux's option and command-separator parsing of user text.
    buffer = "cc-input-" + uuid.uuid4().hex
    # Paste markers inside the text would end the paste early and turn the rest into keystrokes
    # (Esc, Shift+Tab switching the agent's permission mode); they are never content of a paste.
    if bracketed:
        text = text.replace("\x1b[200~", "").replace("\x1b[201~", "")
    payload = "\x1b[200~" + text + "\x1b[201~" if bracketed else text
    result = subprocess.run([*TMUX_COMMAND, "load-buffer", "-b", buffer, "-"], input=payload,
                            text=True, capture_output=True, timeout=10)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "не удалось подготовить ввод")
    try:
        tmux("paste-buffer", "-d", "-b", buffer, "-t", f"={PREFIX}{name}:", "-r", *(["-S"] if _paste_raw_supported else []))
    finally:
        tmux("delete-buffer", "-b", buffer, check=False)
    time.sleep(0.2)


def action_send(d):
    name = d.get("name", "")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError("неверное имя сессии")
    with input_locks_lock:
        lock = input_locks.setdefault(name, threading.Lock())
    with lock:
        return send_input(d)


def send_input(d):
    name = d.get("name", "")
    if not session_exists(name):
        raise ValueError("нет такой сессии")
    key = d.get("key")
    if key is not None and not isinstance(key, str):
        raise ValueError("неверная клавиша")
    if key in ("Escape", "Enter", "C-c", "Up", "Down", "Left", "Right", "S-Left", "S-Right", "Tab", "BTab"):
        tmux("send-keys", "-t", f"={PREFIX}{name}:", key)
    elif key and len(key) == 1 and key in "123456789yn":
        tmux("send-keys", "-t", f"={PREFIX}{name}:", "-l", key)
    else:
        text = d.get("text", "")
        if not isinstance(text, str):
            raise ValueError("неверный текст сообщения")
        paths = attachment_paths(name, d.get("attachments", []))
        agent = opt(name, "@cc_agent") or "claude"
        if paths and agent == "shell":
            raise ValueError("файлы можно приложить к Claude или Codex")
        language = d.get('_language', DEFAULT_LANGUAGE)
        def translated(message):
            if locales is None or language not in {item['code'] for item in locales.available()}:
                return message
            return locales.translate(message, language)
        files = [path for path in paths if "--" in os.path.basename(path)]
        if paths:
            text = (text + translated("\n\nВложения временные: удаляются с сервера через 7 дней после загрузки. "
                    "Если они нужны надолго, сохрани их в подходящем месте в проекте.")).lstrip()
        paths = [path for path in paths if "--" not in os.path.basename(path)]
        if files:
            text = (text + translated("\n\nПриложенные файлы (прочитай их с диска):\n") + "\n".join(files)).lstrip()
        if paths and agent == "codex":
            for path in paths:
                paste_to_tmux(name, path)
            if text:
                paste_to_tmux(name, text)
        else:
            if paths:
                text = (text + translated("\n\nПосмотри приложенные изображения:\n") + "\n".join(paths)).lstrip()
            if paths:
                paste_to_tmux(name, text)
            elif text:
                paste_to_tmux(name, text, bracketed=agent != "shell")
        if text or paths:
            wait_for_quiet_screen(name, 4 if paths or files else 1)
        tmux("send-keys", "-t", f"={PREFIX}{name}:", "Enter")


def wait_for_quiet_screen(name, limit):
    # Agents process a paste asynchronously (Claude turns image paths into [Image #N]);
    # an Enter that arrives mid-way is dropped and the message stays in the prompt.
    # Loading an image can pause the screen briefly before the prompt is redrawn, so
    # attachments need a longer stable stretch than plain text.
    deadline, stable_needed = time.monotonic() + limit, 3 if limit > 1 else 1
    previous, stable = None, 0
    while time.monotonic() < deadline:
        screen = tmux("capture-pane", "-p", "-t", f"={PREFIX}{name}:", check=False)
        stable = stable + 1 if screen == previous else 0
        if stable >= stable_needed:
            return
        previous = screen
        time.sleep(0.25)


_gh_cache = {"t": 0, "repos": None}


def gh(*args, timeout=30):
    return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)


def github_status():
    r = gh("api", "user", "--jq", ".login", timeout=15)
    return {"connected": r.returncode == 0, "login": r.stdout.strip() if r.returncode == 0 else None}


def github_repos(refresh=False):
    if not refresh and _gh_cache["repos"] is not None and time.time() - _gh_cache["t"] < 120:
        return _gh_cache["repos"]
    r = gh("api", "--paginate", "user/repos?per_page=100&sort=pushed&affiliation=owner,collaborator,organization_member",
           "--jq", ".[] | [.full_name, .private, .pushed_at, (.description // \"\")] | @tsv", timeout=60)
    if r.returncode:
        raise RuntimeError("GitHub: " + (r.stderr.strip()[-300:] or "ошибка"))
    repos = []
    for line in r.stdout.splitlines():
        full, private, pushed, desc = (line.split("\t") + [""] * 4)[:4]
        repos.append({"full_name": full, "private": private == "true", "pushed_at": pushed, "description": desc})
    repos.sort(key=lambda x: x["pushed_at"], reverse=True)
    _gh_cache.update(t=time.time(), repos=repos)
    return repos


GH_LOGIN_CMD = ("gh auth login --hostname github.com --git-protocol https --web"
                " && gh auth setup-git"
                " && git config --global user.name \"$(gh api user --jq '.name // .login')\""
                " && git config --global user.email \"$(gh api user --jq '\"\\(.id)+\\(.login)@users.noreply.github.com\"')\""
                " && echo && echo '✅ GitHub подключён. Эту сессию можно закрыть.'")


def action_github_login(d):
    run_in_session("github-login", GH_LOGIN_CMD)


def run_in_session(name, command):
    """(Re)create a utility session in $HOME and run a command in it."""
    if session_exists(name):
        tmux("kill-session", "-t", f"={PREFIX}{name}:")
    create_session(name, os.path.expanduser("~"), "shell", False, command=command)


def action_agent_install(d):
    agent = d.get("agent")
    if agent not in INSTALLERS:
        raise ValueError("неизвестный агент")
    run_in_session(f"install-{agent}", f"{INSTALLERS[agent]} && echo && echo '✅ {AGENTS[agent][0]} установлен/обновлён. Сессию можно закрыть.'")


def action_agent_login(d):
    agent = d.get("agent")
    if agent not in LOGINS:
        raise ValueError("неизвестный агент")
    run_in_session(f"{agent}-login", LOGINS[agent])


_version_cache = {}


def agent_status(agent):
    home = os.path.expanduser("~")
    if agent == "claude-kimi":
        return {**agent_status("claude"), "logged_in": kimi_config.status()["configured"]}
    path = kimi_config.executable("kimi") if agent == "kimi" else os.path.join(home, ".local", "bin", agent)
    if agent == "kimi" and not path:
        return {"installed": False, "version": None, "logged_in": kimi_config.status()["configured"]}
    path = path if path and os.path.exists(path) else shutil.which(agent)
    installed = bool(path)
    version = None
    if installed:
        real = os.path.realpath(path)
        key = (real, os.path.getmtime(real))
        if _version_cache.get(agent, (None,))[0] != key:  # re-run --version only after an install/update
            r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
            v = (r.stdout.strip().split() or [None])[-1] if agent == "codex" else (r.stdout.split() or [None])[0]
            _version_cache[agent] = (key, v)
        version = _version_cache[agent][1]
    if agent == "kimi":
        return {"installed": installed, "version": version, "logged_in": kimi_config.status()["configured"]}
    if agent == "pi":
        return {"installed": installed, "version": version, "logged_in": installed}
    auth = {"claude": os.path.join(home, ".claude", ".credentials.json"),
            "codex": os.path.join(home, ".codex", "auth.json")}[agent]
    logged_in = os.path.exists(auth)
    if agent == "claude" and sys.platform == "darwin" and not logged_in and installed:
        logged_in = bool(cached("claude-keychain", 60, claude_credentials).get("claudeAiOauth", {}).get("accessToken"))
    return {"installed": installed, "version": version, "logged_in": logged_in}


# ---- server info & subscription limits ---------------------------------------------------
_cache = {}


_usage_store_lock = threading.Lock()


def usage_store_path():
    return os.path.expanduser("~/.config/cc-panel/usage-cache.json")


def stored_value(key):
    try:
        with open(usage_store_path()) as stream:
            item = json.load(stream).get(key)
        return (float(item[0]), item[1]) if isinstance(item, list) and len(item) == 2 and isinstance(item[1], dict) else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def store_value(key, stamp, value):
    with _usage_store_lock:
        try:
            with open(usage_store_path()) as stream:
                data = json.load(stream)
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        data[key] = [stamp, value]
        try:
            kimi_config.atomic_write(usage_store_path(), json.dumps(data))
        except OSError:
            pass  # Losing the copy only costs one extra request after a restart.


_cache_locks = {}
_cache_locks_lock = threading.Lock()


def cached(key, ttl, fn, persist=False):
    """Return fn() cached for ttl seconds; on failure keep serving the last good value (marked stale).

    persist keeps the last good value across panel restarts: updates restart the panel, and an
    empty cache plus a rate-limited first request would otherwise show no data at all."""
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    # One fetch per key: tabs polling together must not multiply calls to rate-limited endpoints.
    with _cache_locks_lock:
        key_lock = _cache_locks.setdefault(key, threading.Lock())
    with key_lock:
        return _cached_fetch(key, ttl, fn, persist)


def _cached_fetch(key, ttl, fn, persist):
    hit = _cache.get(key)
    if not hit and persist and (hit := stored_value(key)):
        _cache[key] = hit
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception as e:  # network/auth errors must not break the panel
        # remember the failure only briefly (max 5 min), so a transient error doesn't stick for the whole ttl
        backoff = min(ttl, 300)
        if isinstance(e, urllib.error.HTTPError) and e.code == 429:
            # An early retry only extends the block and risks the account; honour Retry-After.
            try:
                wait = int(e.headers.get("Retry-After") or 0)
            except (TypeError, ValueError, AttributeError):
                wait = 0
            backoff = min(max(1800, wait), 6 * 3600)
            e.close()
        _cache[key] = (time.time() - ttl + backoff, {**hit[1], "stale": True} if hit and "error" not in hit[1]
                       else {"error": str(e)[:200]})
        return _cache[key][1]
    _cache[key] = (time.time(), val)
    if persist and "error" not in val:
        store_value(key, *_cache[key])
    return val


def http_json(url, headers=None, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "cc-panel", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _semver(v):
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(map(int, m.groups())) if m else None


def version_info(force=False, fresh=False):
    info = {"version": VERSION, "checkout": CHECKOUT, "repo": UPDATE_REPO,
            "can_update": updater.available(HERE, UPDATE_REPO), "job": updater.status(UPDATE_STATE),
            "auto_update": auto_update_service().status()}
    info['incomplete'] = Telegram is None or locales is None
    info['container'] = bool(os.environ.get('AGENT_DECK_CONTAINER'))  # Updated by a new image, not in place.
    info['update_command'] = os.environ.get('AGENT_DECK_UPDATE_COMMAND', '')
    if not UPDATE_REPO:
        return info

    def fetch():
        r = http_json(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                      {"Accept": "application/vnd.github+json"}, timeout=8)
        return {"latest": (r.get("tag_name") or "").lstrip("v"), "url": r.get("html_url")}
    with _release_lock:
        if force or (fresh and time.time() - _cache.get("release", (0, None))[0] > 60):_cache.pop("release", None)
        rel = cached("release", 1800, fetch)
    if rel.get("latest"):
        cur, new = _semver(VERSION), _semver(rel["latest"])
        info.update(latest=rel["latest"], url=rel["url"], update=bool(cur and new and (new > cur or (new == cur and Telegram is None))))
    if rel.get("error"):info["release_error"] = "Could not check the latest release"
    return info


def auto_update_idle():
    with action_lock:
        if actions_in_progress:return False
    return not updater.local_requests_active()


def start_auto_update():
    with action_lock:
        if actions_in_progress or updater.local_requests_active():return {'job':{'phase':'waiting'}}
        return action_update({})


def auto_update_service():
    global _auto_updates
    from integrations.updates import AutoUpdates
    with _auto_updates_lock:
        if _auto_updates is None:
            _auto_updates = AutoUpdates(os.path.expanduser('~/.config/cc-panel/integrations'),
                lambda:version_info(force=True),start_auto_update,
                lambda:updater.available(HERE,UPDATE_REPO),auto_update_idle)
        return _auto_updates


def action_update(d):
    if not updater.available(HERE, UPDATE_REPO):
        raise ValueError("Обновление по кнопке доступно для установленной панели; чекаут обновляется через git")
    os.makedirs(os.path.dirname(UPDATE_STATE), mode=0o700, exist_ok=True)
    fd = updater.lock(UPDATE_STATE)
    if fd is None:
        return {"job": updater.status(UPDATE_STATE)}
    try:
        updater.write_state(UPDATE_STATE, "checking", message="Проверяю последний релиз…")
        # Do not pass passwords or agent credentials to the update process.
        env = {key: value for key, value in os.environ.items()
               if key in {"PATH", "LANG", "LC_ALL", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"}}
        subprocess.Popen([sys.executable, os.path.join(HERE, "updater.py"),
                          "--repo", UPDATE_REPO, "--target", HERE, "--state", UPDATE_STATE,
                          "--url", f"http://{BIND_HOST}:{BIND_PORT}", "--lock-fd", str(fd)],
                         pass_fds=(fd,), start_new_session=True, env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"job": {"phase": "checking", "message": "Проверяю последний релиз…"}}
    except OSError as error:
        updater.write_state(UPDATE_STATE, "error", message="Не удалось запустить обновление")
        raise ValueError("Не удалось запустить обновление") from error
    finally:
        os.close(fd)


def server_info():
    def fetch():
        geo = http_json("https://ipinfo.io/json", timeout=6)
        return {"ip": geo.get("ip"), "country": geo.get("country"), "city": geo.get("city"), "org": geo.get("org")}
    info = dict(cached("geo", 6 * 3600, fetch))
    info.update(hostname=socket.gethostname(), tailscale_ip=BIND_HOST)
    return info


_epoch = usage_limits.epoch


def claude_credentials():
    try:
        with open(os.path.expanduser("~/.claude/.credentials.json")) as stream:
            return json.load(stream)
    except FileNotFoundError:
        if sys.platform != "darwin":
            return {}
        result = subprocess.run(["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
                                capture_output=True, text=True, timeout=5)
        return json.loads(result.stdout) if result.returncode == 0 else {}


def claude_usage():
    return usage_limits.claude(claude_credentials(), http_json)


def codex_usage():
    return usage_limits.codex(http_json, os.path.expanduser("~/.codex/auth.json"))


def kimi_usage():
    return usage_limits.kimi(kimi_config.read().get("key"), http_json)


def usage():
    out = {}
    for agent, fn in (("claude", claude_usage), ("codex", codex_usage), ("kimi", kimi_usage)):
        if agent_status(agent)["logged_in"]:
            cache_key = f"usage-{agent}"
            if agent == "kimi":
                cache_key += "-" + hashlib.sha256(kimi_config.read().get("key", "").encode()).hexdigest()
            # Anthropic rate-limits the usage endpoint (HTTP 429) that Claude Code itself also polls.
            # Claude quotas are weekly, so a 10-minute view is current enough.
            out[agent] = cached(cache_key, 600 if agent == "claude" else 60, fn, persist=agent != "kimi")
    return out


ACTIONS = {
    "check_update": lambda d: version_info(force=True),
    "auto_update": lambda d: {"auto_update":auto_update_service().save(d.get("enabled"))},
    'decks_save': lambda d: {'deck':remote_decks.save(d)},
    'decks_remove': lambda d: remote_decks.remove(d.get('id')),
    'decks_discover': lambda d: {'discovery':remote_decks.discover(d.get('port',8790))},
    'network_save': lambda d: {'network':network_settings.save(d)},
    'rename': action_rename,
    'project_directory': lambda d: {'directory': project_directory.save(d.get('directory'))},
    'lm_save': action_lm_save,
    'lm_probe': lambda d: {'profile':model_service().probe(d.get('id'))},
    'lm_test': lambda d: model_service().test(d),
    'lm_benchmark': lambda d: model_service().benchmark(d),
    'lm_discover': lambda d: {'discovery':model_service().discover(d)},
    'lm_remove': action_lm_remove,
    "kimi_config": lambda d: {"kimi": kimi_config.save(d)}, "agent_install": action_agent_install, "agent_login": action_agent_login, "github_login": action_github_login, "new": action_new, "restart": action_restart, "kill": action_kill, "send": action_send, "upload": action_upload, "update": action_update, "discard_upload": action_discard_upload}


def current_question(name):
    if not session_exists(name):
        return None
    agent = opt(name, "@cc_agent") or "claude"
    instance = tmux("display-message", "-p", "-t", f"={PREFIX}{name}:",
                    "#{pane_id}:#{pane_pid}:#{@cc_sid}").strip()
    screen = tmux("capture-pane", "-p", "-t", f"={PREFIX}{name}:")
    return parse_question(name, agent, instance, screen)


def scan_questions():
    result = []
    for session in list_sessions():
        if session['agent'] == 'shell' or not session['running']:
            continue
        with input_locks_lock:
            lock = input_locks.setdefault(session['name'], threading.Lock())
        with lock:
            # Notifications, Telegram and the inbox show the name the user gave the session.
            label = session.get('title') or session['name']
            structured = pending_questions(session['name'])
            if structured:
                result.extend(dataclasses.replace(q, label=label) for q in structured)
                continue
            question = current_question(session['name'])
            if question:
                result.append(dataclasses.replace(question, label=label))
    return result


transcript_paths = {}
transcript_models = {}
transcript_models_lock = threading.Lock()


transcript_misses = {}


def transcript_path(agent, sid):
    key = (agent, sid)
    path = transcript_paths.get(key)
    if path and not path.exists():
        path = transcript_paths.pop(key, None) and None
    # A miss (new session, deleted file) would otherwise walk every project directory on each 2 s scan.
    if not path and time.monotonic() - transcript_misses.get(key, -60) >= 30:
        from pathlib import Path
        root = Path(os.path.expanduser('~/.codex/sessions' if agent == 'codex' else '~/.claude/projects'))
        path = next(root.rglob('*' + sid + '*.jsonl'), None)
        for cache in (transcript_paths, transcript_misses):
            if len(cache) > 1000:
                cache.clear()  # Ended sessions; the live ones are found again on the next scan.
        if path:
            transcript_paths[key] = path
            transcript_misses.pop(key, None)
        else:
            transcript_misses[key] = time.monotonic()
    return path


def session_model(agent, sid):
    """Model of the latest turn; re-read only when the transcript changes."""
    if agent not in ('codex', 'claude') or not valid_sid(sid):
        return None
    try:
        from integrations.questions import transcript_model
        path = transcript_path(agent, sid)
        if not path:
            return None
        stat = path.stat()
        with transcript_models_lock:
            cached = transcript_models.get(path)
        if cached and cached[0] == (stat.st_mtime_ns, stat.st_size):
            return cached[1]
        # A huge last turn can push the model record out of the tail; keep the previous answer.
        model = transcript_model(path, agent) or (cached[1] if cached else None)
        with transcript_models_lock:
            transcript_models[path] = ((stat.st_mtime_ns, stat.st_size), model)
        return model
    except (ImportError, OSError, ValueError):
        return None


def pending_questions(name):
    agent = opt(name, '@cc_agent') or 'claude'
    sid = opt(name, '@cc_sid')
    if agent not in ('codex', 'claude', 'claude-kimi') or not valid_sid(sid):
        return []
    path = transcript_path(agent, sid)
    if not path:
        return []
    instance = tmux('display-message', '-p', '-t', f'={PREFIX}{name}:', '#{pane_id}:#{pane_pid}:#{@cc_sid}').strip()
    try:
        return transcript_questions(path, name, agent, instance)
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return []


FREE_TEXT_OPTION = re.compile(r'(Other\b|Type something|Другое\b|Свой ответ)', re.I)


def session_question(name):
    """The question the web composer offers as buttons: transcript first, then the screen menu."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name) or not session_exists(name):
        return None
    with input_locks_lock:
        lock = input_locks.setdefault(name, threading.Lock())
    with lock:
        pending = pending_questions(name)
        return pending[0] if pending else current_question(name)


def question_payload(question):
    return {'id': question.fingerprint, 'title': question.title, 'progress': question.progress,
            'selected': question.selected,
            'options': [{'label': label, 'text': bool(FREE_TEXT_OPTION.match(label))} for label in question.options]}


def questions_payload():
    return {'questions': [{**question_payload(q), 'session': q.session, 'label': q.label, 'agent': q.agent} for q in scan_questions()]}


def remote_questions():
    """Questions of connected Agent Decks, so one Telegram bot on the gateway serves every machine."""
    return gateway.questions()


def all_questions():
    return scan_questions() + remote_questions()


_questions_cache = {'at': -10.0, 'items': [], 'refreshing': False}
_questions_lock = threading.Condition()


def shared_questions():
    """One scan every 2 s serves Telegram, notifications and the inbox instead of one each.
    While one thread refreshes, the others get the previous result instead of waiting on slow computers."""
    with _questions_lock:
        while _questions_cache['refreshing'] and _questions_cache['at'] < 0:
            _questions_lock.wait()  # No result yet: an empty list would look like everything was answered.
        if _questions_cache['refreshing'] or time.monotonic() - _questions_cache['at'] < 2:
            return list(_questions_cache['items'])
        _questions_cache['refreshing'] = True
    items = None
    try:
        items = all_questions()
    finally:
        with _questions_lock:
            if items is not None:
                _questions_cache.update(items=items, at=time.monotonic())
            _questions_cache['refreshing'] = False
            _questions_lock.notify_all()
    return list(items)


def inbox_payload():
    items = []
    for q in shared_questions():
        # A connected computer checks its own fingerprint, which travels as `instance`.
        items.append({**question_payload(q), 'id': q.instance if q.deck else q.fingerprint,
                      'session': q.session, 'label': q.label or q.session, 'agent': q.agent, 'deck': q.deck, 'origin': q.origin})
    return {'questions': items}


def answer_any_question(question, index, text=None):
    return gateway.answer(question, index, text) if question.deck else answer_question(question, index, text)


def answer_text(d):
    text = d.get('text')
    if text is None:
        return None
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError('Введите ответ (до 4000 символов)')
    return text


def action_answer(d):
    index = d.get('index')
    if not isinstance(index, int) or isinstance(index, bool):
        raise ValueError('неверный запрос')
    text = answer_text(d)
    question = session_question(d.get('name'))
    # The fingerprint binds the tap to the exact question the user saw.
    if not question or question.fingerprint != d.get('id'):
        raise ValueError('Этот вопрос уже закрыт или изменился. Обновите панель.')
    answer_question(question, index, text)


def answer_question(question, index, text=None):
    with input_locks_lock:
        lock = input_locks.setdefault(question.session, threading.Lock())
    with lock:
        current = current_question(question.session)
        if question.request_id:
            pending = pending_questions(question.session)
            if not any(q.fingerprint == question.fingerprint for q in pending):
                raise ValueError('Этот вопрос уже закрыт или изменился')
            same = [q for q in pending if q.title == question.title and q.options == question.options and q.progress == question.progress]
            if len(same) != 1:
                raise ValueError('В сессии несколько одинаковых вопросов. Ответьте через панель.')
            if not matches_screen(question, current):
                # Codex async questions can be hidden behind the normal composer.
                if question.agent == 'codex':
                    tmux('send-keys', '-t', f'={PREFIX}{question.session}:', 'S-Left')
                for _ in range(30):
                    time.sleep(.05)
                    current = current_question(question.session)
                    if matches_screen(question, current):
                        break
                    if current and current.progress:
                        tmux('send-keys', '-t', f'={PREFIX}{question.session}:', 'Right')
                    elif current:
                        raise QuestionNotReady('Сначала ответьте на предыдущий вопрос в Telegram, затем повторите нажатие')
                else:
                    raise QuestionNotReady('Не удалось открыть этот вопрос. Повторите нажатие, когда Codex покажет форму.')
            # From this point the terminal overlay is the authority for input.
            question = current
        if not current or current.fingerprint != question.fingerprint:
            raise ValueError('Этот вопрос уже закрыт или изменился. Обновите панель.')
        if not 0 <= index < len(current.options):
            raise ValueError('Неверный вариант ответа')
        free = bool(FREE_TEXT_OPTION.match(current.options[index]))
        if free and text is None:
            raise ValueError('Этот вариант требует ввода текста в панели')
        if text is not None and not free:
            raise ValueError('У этого варианта нет поля для своего ответа')
        delta = index - current.selected
        if delta:
            tmux('send-keys', '-t', f'={PREFIX}{question.session}:', *(['Down' if delta > 0 else 'Up'] * abs(delta)))
            for _ in range(10):
                time.sleep(.05)
                current = current_question(question.session)
                if not current or current.fingerprint != question.fingerprint:
                    raise ValueError('Вопрос изменился до подтверждения ответа')
                if current.selected == index:
                    break
            else:
                raise ValueError('Не удалось выбрать вариант. Ответьте через панель.')
        if text is not None:
            # The highlighted "Other / Type something" row takes typed text; paste keeps exact bytes.
            paste_to_tmux(question.session, text)
        tmux('send-keys', '-t', f'={PREFIX}{question.session}:', 'Enter')


telegram_lock = threading.Lock()
telegram_integration = None


def telegram_service():
    global telegram_integration
    if Telegram is None:
        raise ValueError('Нажмите «Доустановить компоненты» в меню обновлений панели')
    with telegram_lock:
        if telegram_integration is None:
            telegram_integration = Telegram(os.path.expanduser('~/.config/cc-panel/integrations'),
                                            shared_questions, answer_any_question)
        return telegram_integration


_backups = None
_backups_lock = threading.Lock()
backup_run_lock = threading.Lock()


def backup_service():
    global _backups
    from integrations.backups import Backups
    with _backups_lock:
        if _backups is None:
            _backups = Backups(os.path.expanduser('~'), lambda: VERSION,
                               lambda: network_settings.get()['name'] or socket.gethostname())
        return _backups


def run_backups():
    """One backup cycle; the gateway (an instance with connected decks) also replicates every machine."""
    from integrations.backups import replicate
    if not backup_run_lock.acquire(blocking=False):
        raise ValueError('Бэкап уже выполняется')
    try:
        if remote_decks.status().get('decks'):
            return replicate(backup_service(), remote_decks)
        backup_service().create()
        return backup_service().report({'started': int(time.time()), 'finished': int(time.time()), 'machines': []})
    finally:
        backup_run_lock.release()


def backup_loop():
    while True:
        time.sleep(900)
        try:
            service = backup_service()
            latest = service.latest() if service.key() else None
            if service.key() and (not latest or time.time() - latest['created'] > 86400):
                run_backups()
        except Exception as error:  # A failed cycle is retried on the next tick and shown in Settings.
            print(f'Backup cycle failed: {error}', flush=True)


def restart_soon():
    # systemd Restart=always / launchd KeepAlive start the panel again with the restored settings;
    # KillMode=process keeps tmux and the agents running.
    threading.Timer(1.5, os._exit, args=(0,)).start()


def backup_blob_payload(query):
    params = parse_qs(query)
    blob = backup_service().read(params.get('origin', [''])[0], int(params.get('created', ['0'])[0] or 0))
    return {'blob': base64.b64encode(blob).decode()}


def action_backup_now(d):
    return {'blob': base64.b64encode(backup_service().create()).decode()}


def action_backup_store(d):
    from integrations.backups import read_meta
    blob = base64.b64decode(str(d.get('blob', '')), validate=True)
    if read_meta(blob)[0]['origin'] == backup_service().instance_id():
        raise ValueError('Этот компьютер сам хранит свои бэкапы')
    return {'meta': backup_service().store(blob)}


def action_backup_restore(d):
    from integrations.backups import remote_json
    if d.get('blob'):
        blob = base64.b64decode(str(d['blob']), validate=True)
    elif d.get('deck'):
        query = urlencode({'origin': d.get('origin', ''), 'created': d.get('created', 0)})
        encoded = remote_json(remote_decks, d['deck'], 'GET', '/api/backup_blob?' + query).get('blob')
        if not isinstance(encoded, str):
            raise ValueError('Компьютер не прислал файл бэкапа')
        blob = base64.b64decode(encoded, validate=True)
    else:
        blob = backup_service().read(d.get('origin'), d.get('created'))
    result = backup_service().restore(blob, d.get('code') or None)
    restart_soon()
    return {'restored': result}


def action_backup_restore_remote(d):
    from integrations.backups import join_remote, remote_json
    blob = backup_service().read(d.get('origin'), d.get('created'))
    join_remote(backup_service(), remote_decks, d.get('deck'))
    return remote_json(remote_decks, d.get('deck'), 'POST', '/api/backup_restore', {'blob': base64.b64encode(blob).decode()})


_push = None
_push_lock = threading.Lock()


def push_sessions():
    """Local sessions plus connected Agent Decks' lists (refreshed every 10 s) for notification events."""
    return [{**s, 'deck': ''} for s in list_sessions()] + gateway.sessions()


def push_service():
    global _push
    from integrations.push import Push
    with _push_lock:
        if _push is None:
            _push = Push(os.path.expanduser('~/.config/cc-panel/integrations'), push_sessions, shared_questions)
        return _push


def telegram_duplicates(bot):
    """Connected Agent Decks polling the same bot: their questions would arrive twice."""
    def scan():
        return [name for name, state in gateway.telegram_states()
                if state.get('configured') and state.get('enabled') and state.get('bot') == bot]
    result = cached('telegram-duplicates-' + bot, 60, scan) if bot else []
    return result if isinstance(result, list) else []  # cached() reports failures as a dict.


def integration_status():
    if not Telegram:
        return {'telegram': {'available': False}}
    status = telegram_service().status()
    return {'telegram': {**status, 'duplicates': telegram_duplicates(status.get('bot', '')) if status.get('paired') else []}}


def session_folder(name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name) or not session_exists(name):
        raise ValueError("сессия не найдена")
    folder = tmux("display-message", "-p", "-t", f"={PREFIX}{name}:", "#{session_path}", check=False).strip()
    return folder or os.path.expanduser("~")


def file_errors(work):
    """File problems are answers for the user, not server errors."""
    try:
        return work()
    except PermissionError:
        raise ValueError("Нет прав на этот файл или папку") from None
    except (FileNotFoundError, FileExistsError, IsADirectoryError, NotADirectoryError) as error:
        raise ValueError(str(error) if error.args and isinstance(error.args[0], str) and not error.filename
                         else "Файл или папка недоступны") from None
    except OSError:
        raise ValueError("Файл или папка недоступны") from None  # e.g. a name longer than the file system allows


def files_payload(query):
    from integrations import files
    path = query.get("path", [""])[0] or session_folder(query.get("name", [""])[0])
    return file_errors(lambda: files.listing(os.path.expanduser("~"), path))


def file_payload(query):
    from integrations import files
    return file_errors(lambda: files.read_text(os.path.expanduser("~"), query.get("path", [""])[0]))


def file_preview_payload(query):
    from integrations import files
    return file_errors(lambda: files.read_preview(os.path.expanduser("~"), query.get("path", [""])[0]))


def scrollback_payload(query):
    from integrations import scrollback
    name = query.get("name", [""])[0]
    if not NAME_RE.fullmatch(name) or not session_exists(name):
        raise ValueError("сессия не найдена")
    try:
        text = tmux("capture-pane", "-p", "-J", "-t", f"={PREFIX}{name}:", "-S", "-", "-E", "-", check=False)
    except subprocess.TimeoutExpired:
        raise ValueError("tmux не ответил за 10 секунд; попробуйте ещё раз") from None
    return scrollback.search(text, query.get("q", [""])[0])


def action_file_save(d):
    from integrations import files
    expected = d.get("hash")
    if expected is not None and not isinstance(expected, str):
        raise ValueError("Неверная версия файла")
    return file_errors(lambda: files.save_text(os.path.expanduser("~"), d.get("path"), d.get("content"), expected))


_grouper = None
_grouper_lock = threading.Lock()


def git_grouper():
    global _grouper
    from integrations.git import Grouper
    with _grouper_lock:
        if _grouper is None:
            _grouper = Grouper(os.path.expanduser("~/.cache/agent-deck/git-groups"))
        return _grouper


def git_tree(name, wanted):
    """The working tree to show for a session: the one asked for or the one its agent's output names.
    The output stays on the server; only the chosen tree's path is returned."""
    from integrations import git
    folder = session_folder(name)
    output = lambda: tmux("capture-pane", "-p", "-J", "-t", f"={PREFIX}{name}:", "-S", "-3000", check=False)
    return git.choose_tree(folder, wanted if isinstance(wanted, str) else "", output)


def git_payload(route, query):
    from integrations import git
    folder, trees = git_tree(query.get("name", [""])[0], query.get("tree", [""])[0])
    if route == "/api/git/log":
        skip = query.get("skip", ["0"])[0]
        page = git.history(folder, int(skip) if skip.isdigit() else -1, ref=query.get("ref", [""])[0])
        return {**page, **(trees or {})}
    if route == "/api/git/commit":
        return git.commit(folder, query.get("sha", [""])[0])
    if route == "/api/git/changes":
        return {**git.changes(folder), **(trees or {})}
    if route == "/api/git/group_diff":
        return git.group_diff(folder, [s for s in query.get("shas", [""])[0].split(",") if s])
    if route == "/api/git/groups":
        return git_grouper().status(folder, query.get("ref", [""])[0])
    if route == "/api/git/models":
        return grouping_models()
    raise ValueError("Agent Deck route not found")


LOCAL_GROUP_TIMEOUT = 900  # A local model on a laptop can take minutes; it costs nothing.


def grouping_models():
    """Models on this computer that can group commits, local (free) first."""
    options = []
    try:
        for profile in model_service().status().get("profiles", []):
            for item in profile.get("models") or []:
                options.append({"id": f"lmstudio:{profile['id']}:{item['id']}",
                                "label": f"{item.get('name') or item['id']} · {profile.get('name', 'LM Studio')}", "local": True})
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    kimi = kimi_config.read()
    if kimi.get("key"):
        options.append({"id": "kimi", "label": f"Kimi · {kimi.get('model', 'k3')}", "local": False})
    if agent_status("claude")["logged_in"]:
        options.append({"id": "claude", "label": "Claude Haiku", "local": False})
    return {"models": options}


def grouping_model(choice):
    """None means Claude Haiku through Claude Code; others answer through their HTTP API, no tools at all."""
    from integrations import lmstudio
    if not choice or choice == "claude":
        return None
    if choice == "kimi":
        kimi = kimi_config.read()
        if not kimi.get("key"):
            raise ValueError("Сохраните ключ Kimi в настройках агентов")
        model = kimi.get("model", "k3")
        def complete(prompt):
            answer = lmstudio.request("https://api.kimi.com/coding", "/v1/messages", "POST",
                                      {"model": model, "max_tokens": 8192, "messages": [{"role": "user", "content": prompt}]},
                                      key=kimi["key"], timeout=300)
            return "".join(block.get("text", "") for block in answer.get("content", []) if isinstance(block, dict))
        return {"label": f"Kimi · {model}", "complete": complete}
    match = re.fullmatch(r"lmstudio:([^:]+):(.+)", str(choice))
    if not match:
        raise ValueError("Неизвестная модель для группировки")
    profile = model_service().get(match.group(1))
    model = match.group(2)
    if model not in {item.get("id") for item in profile.get("models") or []}:
        raise ValueError("Этой модели больше нет в профиле LM Studio")
    def complete(prompt):
        # Grouping needs no reasoning; on a local machine thinking is the difference between seconds and
        # many minutes. LM Studio turns it off with reasoning_effort "none" (ignored by other models).
        answer = lmstudio.request(profile["url"], "/v1/chat/completions", "POST",
                                  {"model": model, "temperature": 0.2, "reasoning_effort": "none",
                                   "messages": [{"role": "user", "content": prompt}]},
                                  key=profile.get("key", ""), timeout=LOCAL_GROUP_TIMEOUT)
        return ((answer.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return {"label": f"{model} · {profile.get('name', 'LM Studio')}", "complete": complete}


def action_git_group(d):
    return git_grouper().start(git_tree(d.get("name"), d.get("tree"))[0], d.get("_language", DEFAULT_LANGUAGE), d.get("ref") or None,
                               grouping_model(d.get("model")))


def action_git_fetch(d):
    from integrations import git
    return git.fetch(session_folder(d.get("name")))


ACTIONS.update(file_save=action_file_save, git_group=action_git_group, git_fetch=action_git_fetch,
               telegram_config=lambda d: {'telegram': telegram_service().save(d)},
               telegram_pair=lambda d: {'telegram': telegram_service().pair()},
               answer=action_answer,
               backup_setup=lambda d: backup_service().setup(d.get('code') or None),
               backup_now=action_backup_now,
               backup_run=lambda d: {'report': run_backups()},
               backup_store=action_backup_store,
               backup_restore=action_backup_restore,
               backup_restore_remote=action_backup_restore_remote,
               push_subscribe=lambda d: push_service().subscribe(d),
               push_unsubscribe=lambda d: push_service().unsubscribe(d.get('id')),
               push_test=lambda d: push_service().test(d.get('id')),
               push_events=lambda d: {'events': push_service().set_events(d)})


class PanelHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer normally reverse-resolves the bind address here. On macOS
        # this can block startup (including update recovery) waiting on DNS.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Handler(BaseHTTPRequestHandler):
    server_version = "cc-panel/1.0"
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, fmt, *args):
        # The isolated terminal path is a credential; logs keep the route, never the signature.
        print(f"{self.client_ip()} {CAPABILITY_IN_LOG.sub('/c/***/', fmt % args)}", flush=True)

    def via_proxy(self):
        try:
            addr = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        # a proxy on this host (Caddy) connects from our own Tailscale address; tailnet peers have other IPs
        return any(addr in net for net in TRUSTED_PROXIES) or self.client_address[0] == BIND_HOST

    def client_ip(self):
        """Real client IP; behind a trusted proxy take the address the proxy appended (rightmost XFF)."""
        xff = self.headers.get("X-Forwarded-For", "") if self.via_proxy() else ""
        return xff.split(",")[-1].strip() or self.client_address[0]

    def is_https(self):
        # Traefik marks secure WebSocket upgrades as wss; their Origin remains https.
        return self.via_proxy() and self.headers.get("X-Forwarded-Proto", "").lower() in ("https", "wss")

    def same_origin(self, required=False):
        origin = self.headers.get("Origin")
        if not origin:
            return not required and self.headers.get("Sec-Fetch-Site") not in ("cross-site", "same-site")
        try:
            parsed = urlsplit(origin)
            host = urlsplit("//" + self.headers.get("Host", ""))
            scheme = "https" if self.is_https() else "http"
            default = 443 if scheme == "https" else 80
            return (parsed.scheme == scheme and parsed.hostname == host.hostname
                    and (parsed.port or default) == (host.port or default)
                    and not parsed.username and not parsed.password and parsed.path in ("", "/"))
        except ValueError:
            return False

    def cookie(self, name):
        # SimpleCookie drops the whole header when any foreign cookie is malformed.
        for part in self.headers.get("Cookie", "").split(";"):
            key, separator, value = part.partition("=")
            if separator and key.strip() == name:
                return value.strip()
        return None

    def authorized(self):
        if token_valid(self.cookie(COOKIE)):
            return True
        if self.path.startswith("/api/") or self.path.startswith("/t") or self.path.startswith("/deck/"):
            self.send_json(401, {"error": "login required"})
        else:
            self.redirect("/login")
        return False

    def redirect(self, location, cookie=None):
        self.send_response(303)
        self.send_header("Location", location)
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def language(self):
        if locales is None:
            return 'ru'
        allowed = {item['code'] for item in locales.available()}
        choice = self.cookie('cc_lang') or DEFAULT_LANGUAGE
        return choice if choice in allowed else 'en'

    def localized_page(self, page):
        if locales is not None:
            return locales.render_html(page, self.language())
        return page.replace('__PANEL_I18N__', '{"language":"ru","messages":{}}')

    def login_page(self, error=""):
        with open(os.path.join(HERE, "login.html"), encoding="utf-8") as login_file:
            html = login_file.read()
        html = self.localized_page(html)
        error = locales.translate(error, self.language()) if locales is not None else error
        html = html.replace("{{ERROR}}", error).replace("{{USER}}", PANEL_USER)
        self.send_body(200 if not error else 401, html.encode(), "text/html; charset=utf-8")

    def do_login(self):
        ip = self.client_ip()
        if not self.same_origin():
            self.close_connection = True
            return self.send_json(403, {"error": "неверный источник запроса"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= 10_000:
                raise ValueError()
        except ValueError:
            self.close_connection = True
            return self.send_json(400, {"error": "неверный размер запроса"})
        with login_lock:
            now = time.time()
            for old_ip, (_, timestamp) in list(failed_logins.items()):
                if now - timestamp >= 60:
                    failed_logins.pop(old_ip, None)
            count, _ = failed_logins.get(ip, (0, 0))
            if count >= 5 or sum(value[0] for value in failed_logins.values()) >= 100:
                self.close_connection = True
                return self.login_page("Слишком много попыток. Подождите минуту.")
            # Reserve before reading a possibly delayed request body.
            failed_logins[ip] = (count + 1, now)
        form = parse_qs(self.read_body(length).decode("utf-8", "replace"))
        user, pwd = form.get("username", [""])[0], form.get("password", [""])[0]
        ok = hmac.compare_digest(user.encode(), PANEL_USER.encode()) & hmac.compare_digest(pwd.encode(), PANEL_PASSWORD.encode())
        if not ok:
            time.sleep(1)
            return self.login_page("Неверный логин или пароль")
        with login_lock:
            # Release only this successful attempt, not reservations of concurrent requests.
            count, last = failed_logins.get(ip, (1, time.time()))
            if count <= 1:
                failed_logins.pop(ip, None)
            else:
                failed_logins[ip] = (count - 1, last)
        secure = "; Secure" if self.is_https() else ""
        self.redirect("/", f"{COOKIE}={make_token()}; Path=/; Max-Age={COOKIE_DAYS * 86400}; HttpOnly; SameSite=Lax{secure}")

    def upload_raw(self):
        global actions_in_progress
        # application/octet-stream is not a CORS-safelisted type: other sites cannot send it without preflight.
        if (not self.same_origin() or self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/octet-stream"):
            self.close_connection = True
            return self.send_json(403, {"error": "разрешены только загрузки из интерфейса панели"})
        query = parse_qs(urlsplit(self.path).query)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 < length <= MAX_FILE_BYTES:
            self.close_connection = True
            return self.send_json(413, {"error": "файл или сообщение слишком большое"})
        with action_lock:
            if updater.status(UPDATE_STATE).get("phase") in updater.RUNNING:
                self.close_connection = True
                return self.send_json(503, {"error": "панель обновляется; повторите после завершения"})
            actions_in_progress += 1
        try:
            result = store_streamed_upload(query.get("name", [""])[0], query.get("filename", [None])[0], length, self.rfile)
            self.body_pending = False  # Fully read: the connection can serve the next file.
            return self.send_json(200, {"ok": True, **result})
        except (ValueError, OSError) as error:
            self.close_connection = True
            return self.send_json(400, {"error": str(error) if isinstance(error, ValueError) else "не удалось сохранить файл"})
        finally:
            with action_lock:
                actions_in_progress -= 1

    def serve_session_image(self, query):
        from integrations.images import read_image
        name, path = query.get("name", [""])[0], query.get("path", [""])[0]
        if not NAME_RE.fullmatch(name) or not session_exists(name):
            return self.send_json(404, {"error": "сессия не найдена"})
        target = f"={PREFIX}{name}:"
        screen = tmux("capture-pane", "-p", "-J", "-t", target, "-S", "-2000", check=False)
        cwd = tmux("display-message", "-p", "-t", target, "#{pane_current_path}", check=False).strip()
        try:
            cache = os.path.expanduser("~/.cache/agent-deck/thumbnails") if query.get("thumb") == ["1"] else None
            kind, data = read_image(path, cwd or os.path.expanduser("~"), os.path.expanduser("~"), screen, cache)
        except FileNotFoundError as error:
            return self.send_json(404, {"error": str(error)})
        except (ValueError, OSError) as error:
            return self.send_json(400, {"error": str(error)})
        return self.send_image(data, kind)

    def send_image(self, data, kind):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.send_header("X-Content-Type-Options", "nosniff")
        # Opened directly, the response is inert: no scripts, no same-origin access.
        self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        self.end_headers()
        self.wfile.write(data)

    def serve_service_worker(self):
        # Kept inside a Python module: a new file under panel/ would be rejected by older updaters.
        from integrations.webpush import SERVICE_WORKER
        body = SERVICE_WORKER.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self):
        with open(os.path.join(HERE, self.path.lstrip("/")), "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", STATIC[self.path])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def send_body(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, obj):
        if locales is not None:
            obj = locales.response(obj, self.language())
        self.send_body(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

    def framing_rejected(self):
        """Unframed or unread bodies would be parsed as the next keep-alive request."""
        lengths = self.headers.get_all("Content-Length") or []
        if "Transfer-Encoding" in self.headers:
            code, error = 411, "Transfer-Encoding is not supported; send the request with Content-Length"
        elif len(lengths) > 1 or (lengths and not re.fullmatch(r"\d{1,12}", lengths[0].strip())):
            code, error = 400, "неверный размер запроса"
        else:
            self.body_pending = bool(lengths) and int(lengths[0]) > 0
            return False
        self.close_connection = True
        self.send_json(code, {"error": error})
        return True

    def read_body(self, length):
        body = self.rfile.read(length)
        self.body_pending = len(body) != length
        return body

    def handle_safely(self, handler):
        if self.framing_rejected():
            return
        try:
            return handler()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.close_connection = True
            self.send_json(500, {"error": "не удалось обработать запрос"})
        finally:
            if getattr(self, "body_pending", False):
                self.close_connection = True

    def do_GET(self):
        return self.handle_safely(self.get_request)

    def get_request(self):
        if self.path == '/api/locales':
            return self.send_json(200, {'languages': locales.available() if locales is not None else [{'code': 'ru', 'name': 'Русский'}]})
        if self.path in STATIC:
            return self.serve_static()
        if self.path == "/sw.js":
            return self.serve_service_worker()
        if self.path == "/login":
            return self.login_page()
        if ISOLATED_ROUTE.match(self.path):
            return self.proxy_isolated_terminal()  # Authorized by its signed path, not by the cookie.
        if not self.authorized():
            return
        if self.path.startswith('/deck/'):
            return self.proxy_deck()
        if self.path == '/api/decks':
            return self.send_json(200, remote_decks.status())
        if self.path == '/api/network':
            value = network_settings.get()
            return self.send_json(200, {**value, 'name':value['name'] or socket.gethostname(), 'bind_host':BIND_HOST, 'bind_port':BIND_PORT})
        if self.path.startswith("/t/") or self.path == "/t":
            return self.proxy_tty()
        if self.path in ("/", "/index.html"):
            with open(PAGE_FILE, "rb") as f:
                page = f.read()
            revision = hashlib.sha256(page).hexdigest().encode()
            page = self.localized_page(page.decode()).encode()
            page = page.replace(b"__PANEL_REVISION__", revision)
            return self.send_body(200, page, "text/html; charset=utf-8")
        if self.path == "/api/ui-version":
            with open(PAGE_FILE, "rb") as f:
                revision = hashlib.sha256(f.read()).hexdigest()
            return self.send_json(200, {"revision": revision})
        parsed = urlsplit(self.path)
        if parsed.path == "/api/sessions":
            preview_name = parse_qs(parsed.query).get("preview", [None])[0]
            return self.send_json(200, {"sessions": list_sessions(preview_name)})
        if parsed.path == "/api/image":
            return self.serve_session_image(parse_qs(parsed.query))
        if parsed.path.startswith("/api/git/"):
            try:
                return self.send_json(200, git_payload(parsed.path, parse_qs(parsed.query)))
            except (ValueError, OSError, subprocess.TimeoutExpired) as error:
                return self.send_json(400, {"error": str(error) if isinstance(error, ValueError) else "git не ответил"})
        if parsed.path in ("/api/files", "/api/file", "/api/file_preview", "/api/scrollback"):
            try:
                load = {"/api/files": files_payload, "/api/file": file_payload, "/api/file_preview": file_preview_payload,
                        "/api/scrollback": scrollback_payload}[parsed.path]
                return self.send_json(200, load(parse_qs(parsed.query)))
            except ValueError as error:
                return self.send_json(400, {"error": str(error)})
        if parsed.path == "/api/push":
            return self.send_json(200, push_service().status())
        if parsed.path == "/api/backups":
            return self.send_json(200, backup_service().status())
        if parsed.path == "/api/backup_blob":
            try:
                return self.send_json(200, backup_blob_payload(parsed.query))
            except ValueError as error:
                return self.send_json(404, {"error": str(error)})
        if parsed.path == "/api/inbox":
            return self.send_json(200, inbox_payload())
        if parsed.path == "/api/questions":
            return self.send_json(200, questions_payload())
        if parsed.path == "/api/question":
            question = session_question(parse_qs(parsed.query).get("name", [None])[0])
            return self.send_json(200, {"question": question_payload(question) if question else None})
        if self.path == "/api/usage":
            return self.send_json(200, usage())
        if self.path in ("/api/version", "/api/version?fresh=1"):
            # Settings → Network asks for a fresh release check, at most once a minute (GitHub rate limits).
            return self.send_json(200, version_info(fresh=self.path.endswith("fresh=1")))
        if self.path == "/api/server-metrics":
            return self.send_json(200, server_metrics())
        if self.path == "/api/server":
            return self.send_json(200, server_info())
        if self.path == "/api/agents":
            return self.send_json(200, {**{a: agent_status(a) for a in (*INSTALLERS, "claude-kimi")}, "kimi_config": kimi_config.status()})
        if self.path == '/api/lmstudio':
            try:
                return self.send_json(200, model_service().status())
            except (ValueError, OSError):
                return self.send_json(200, {'available':False,'profiles':[],'discovery':{'phase':'idle','results':[]}})
        if self.path == "/api/integrations":
            return self.send_json(200, integration_status())
        if self.path == "/api/github/status":
            return self.send_json(200, github_status())
        if self.path.startswith("/api/github/repos"):
            try:
                return self.send_json(200, {"repos": github_repos("refresh=1" in self.path)})
            except (RuntimeError, subprocess.TimeoutExpired) as e:
                return self.send_json(502, {"error": str(e)})
        if self.path == "/api/project_directory":
            return self.send_json(200, {"directory": project_directory.get()})
        if self.path == "/api/projects":
            dirs = sorted(e.name for e in os.scandir(project_directory.get())
                          if e.is_dir() and not e.name.startswith(".") and not e.name.endswith(".worktrees"))
            return self.send_json(200, {"projects": dirs})
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        return self.handle_safely(self.post_request)

    def post_request(self):
        global actions_in_progress
        if self.path == "/login":
            return self.do_login()
        if self.path == "/logout":
            if not self.same_origin():
                self.close_connection = True
                return self.send_json(403, {"error": "неверный источник запроса"})
            try:
                revoke_terminal_links()
            except (OSError, ValueError):
                pass  # Logging out must work even when the settings folder is read-only.
            return self.redirect("/login", f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
        if not self.authorized():
            return
        if self.path.startswith('/deck/'):
            return self.proxy_deck()
        if urlsplit(self.path).path == "/api/upload_raw":
            return self.upload_raw()
        m = re.match(r"^/api/(\w+)$", self.path)
        if not m or m.group(1) not in ACTIONS:
            return self.send_json(404, {"error": "not found"})
        if (not self.same_origin() or self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json"):
            self.close_connection = True
            return self.send_json(403, {"error": "разрешены только JSON-запросы из интерфейса панели"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            limit = ((MAX_FILE_BYTES + 2) // 3) * 4 + 10_000 if m.group(1) == "upload" else 1_000_000
            if length < 0 or length > limit:
                self.close_connection = True
                return self.send_json(413, {"error": "файл или сообщение слишком большое"})
            data = json.loads(self.read_body(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("неверный запрос")
            action = m.group(1)
            if action in ('send', 'git_group'):
                data['_language'] = self.language()
            with action_lock:
                if action == "update":
                    if actions_in_progress:
                        raise ValueError("Дождитесь окончания отправки или другой операции")
                    result = ACTIONS[action](data)
                else:
                    if updater.status(UPDATE_STATE).get("phase") in updater.RUNNING:
                        return self.send_json(503, {"error": "панель обновляется; повторите после завершения"})
                    actions_in_progress += 1
            if action != "update":
                try:
                    result = ACTIONS[action](data)
                finally:
                    with action_lock:
                        actions_in_progress -= 1
            self.send_json(200, {"ok": True, **(result or {})})
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
            self.close_connection = True
            self.send_json(400, {"error": str(e)})
        except Exception:
            self.close_connection = True
            self.send_json(500, {"error": "не удалось выполнить операцию"})

    def proxy_deck(self):
        match = re.match(r'^/deck/([0-9a-f]{24})(/.*)$', self.path)
        if not match:
            return self.send_json(404, {'error':'Agent Deck route not found'})
        identity, path = match.groups()
        upgrade = self.headers.get('Upgrade','').lower() == 'websocket'
        if (self.command == 'POST' or upgrade) and not self.same_origin():
            self.close_connection = True
            return self.send_json(403, {'error':'неверный источник запроса'})
        try:
            path = remote_path(path)
            if upgrade:
                if self.command != 'GET' or not path.startswith('/t/'):
                    raise ValueError('Only terminal WebSocket upgrades are supported')
                return self.proxy_remote_terminal(identity, path)
            if self.command == 'GET' and path.startswith('/t') and network_settings.get().get('isolate_terminals'):
                # Never render a remote terminal page on the gateway origin while isolation is on.
                return self.redirect(f'/deck/{identity}/c/{terminal_capability(identity)}{path}')
            body = None
            if self.command == 'POST':
                route = urlsplit(path).path
                # Streamed uploads are raw bytes; every other mutation must be JSON.
                expected = 'application/octet-stream' if route == '/api/upload_raw' else 'application/json'
                if self.headers.get('Content-Type','').split(';',1)[0].strip().lower() != expected:
                    return self.send_json(403, {'error':'JSON requests are required'})
                length = int(self.headers.get('Content-Length','0'))
                limit = ((MAX_FILE_BYTES+2)//3)*4+10000 if route == '/api/upload' else MAX_FILE_BYTES if route == '/api/upload_raw' else 1000000
                if not 0 <= length <= limit:
                    self.close_connection = True
                    return self.send_json(413, {'error':'Request is too large'})
                if route != '/api/upload_raw':
                    body = self.read_body(length)
            if self.command == 'POST' and urlsplit(path).path == '/api/upload_raw':
                # Relayed as it arrives: four parallel 200 MB uploads must not sit in the gateway's memory.
                status, headers, payload = remote_decks.request_stream(identity, path, self.rfile, length, self.language())
                self.body_pending = False
            else:
                status, headers, payload = remote_decks.request(identity,self.command,path,body,self.language(),
                    content_type='application/json')
            ctype = next((v for k,v in headers.items() if k.lower()=='content-type'), 'application/octet-stream')
            # Remote HTML/JS under /api/* would run with the gateway origin; only JSON, and raster
            # images from the screenshot endpoint, are passed through.
            base = ctype.split(';',1)[0].strip().lower()
            if urlsplit(path).path == '/api/image' and status == 200 and base in IMAGE_TYPES:
                return self.send_image(payload, base)
            if path.startswith('/api/') and base != 'application/json':
                raise ValueError('Remote Agent Deck returned a non-JSON API response')
            # ttyd's absolute base path must stay on the gateway, including its WebSocket URL.
            if path.startswith('/t') and 'text/html' in ctype:
                prefix = '/deck/'+identity+'/t/'
                payload = payload.replace(b'/t/', prefix.encode())
            return self.send_body(status,payload,ctype)
        except (ValueError,OSError,RuntimeError) as error:
            self.close_connection = True
            return self.send_json(502, {'error':str(error) if isinstance(error,ValueError) else 'Remote Agent Deck is unavailable'})

    def proxy_isolated_terminal(self):
        identity, token, path = ISOLATED_ROUTE.match(self.path).groups()
        upgrade = self.headers.get('Upgrade','').lower() == 'websocket'
        if (self.command != 'GET' or not network_settings.get().get('isolate_terminals')
                or identity not in {d.get('id') for d in remote_decks.status().get('decks', [])}
                or not capability_valid(identity, token)):
            self.close_connection = True
            return self.send_json(404, {'error':'Agent Deck route not found'})
        # The sandboxed page has an opaque origin ("null"); any other foreign origin is refused.
        if upgrade and self.headers.get('Origin') not in (None, 'null') and not self.same_origin():
            self.close_connection = True
            return self.send_json(403, {'error':'неверный источник запроса'})
        try:
            path = remote_path(path)
            if upgrade:
                return self.proxy_remote_terminal(identity, path)
            status, headers, payload = remote_decks.request(identity, 'GET', path, None, self.language())
            ctype = next((v for k,v in headers.items() if k.lower()=='content-type'), 'application/octet-stream')
            if 'text/html' in ctype:
                payload = payload.replace(b'/t/', f'/deck/{identity}/c/{token}/t/'.encode())
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', SANDBOX)
            self.send_header('Referrer-Policy', 'no-referrer')  # The path is the credential.
            self.send_header('Access-Control-Allow-Origin', '*')  # ttyd fetches its token from the opaque origin.
            self.end_headers()
            self.wfile.write(payload)
        except (ValueError,OSError,RuntimeError) as error:
            self.close_connection = True
            return self.send_json(502, {'error':str(error) if isinstance(error,ValueError) else 'Remote Agent Deck is unavailable'})

    def proxy_remote_terminal(self, identity, path):
        backend, origin, cookie = remote_decks.terminal_socket(identity,self.language())
        try:
            lines = [f'GET {path} HTTP/1.1', 'Host: '+urlsplit(origin).netloc,
                     'Origin: '+origin, 'Cookie: '+cookie, 'Connection: Upgrade', 'Upgrade: websocket']
            for key in ('Sec-WebSocket-Key','Sec-WebSocket-Version','Sec-WebSocket-Protocol','Sec-WebSocket-Extensions'):
                value = self.headers.get(key)
                if value:lines.append(key+': '+value)
            backend.sendall(('\r\n'.join(lines)+'\r\n\r\n').encode('latin-1'))
            incoming = b''
            while b'\r\n\r\n' not in incoming:
                chunk = backend.recv(4096)
                if not chunk or len(incoming)>65536:raise ValueError('Invalid remote WebSocket handshake')
                incoming += chunk
            head, pending = incoming.split(b'\r\n\r\n',1)
            rows = head.decode('latin-1').split('\r\n')
            status = rows[0].split()
            if len(status) < 2 or status[1] != '101':raise ValueError('Remote terminal rejected the connection; reconnect the Agent Deck')
            allowed = {'upgrade','connection','sec-websocket-accept','sec-websocket-protocol','sec-websocket-extensions'}
            clean = [row for row in rows[1:] if ':' in row and row.split(':',1)[0].lower() in allowed]
            self.connection.sendall(('HTTP/1.1 101 Switching Protocols\r\n'+'\r\n'.join(clean)+'\r\n\r\n').encode('latin-1')+pending)
            self.close_connection = True
            try:
                while True:
                    readable,_,_ = select.select([self.connection,backend],[],[],300)
                    if not readable:break
                    for connection in readable:
                        chunk = connection.recv(65536)
                        if not chunk:return
                        (backend if connection is self.connection else self.connection).sendall(chunk)
            except OSError:
                pass  # The socket is already upgraded; an HTTP error response would corrupt the stream.
        finally:backend.close()

    def proxy_tty(self):
        """Raw pass-through to ttyd (HTTP + websocket upgrade)."""
        upgrade = "websocket" in self.headers.get("Upgrade", "").lower()
        # Safari sends no Origin on same-origin WebSocket handshakes; a present-but-foreign
        # Origin is still rejected here, and ttyd's own -O re-checks what it receives.
        if upgrade and not self.same_origin():
            return self.send_json(403, {"error": "неверный источник WebSocket"})
        backend = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            backend.connect(TTYD_SOCK)
        except OSError as e:
            backend.close()
            return self.send_json(502, {"error": f"ttyd unavailable: {e}"})
        lines = [f"{self.command} {self.path} HTTP/1.1"]
        for k, v in self.headers.items():
            if k.lower() in ("authorization",) or (not upgrade and k.lower() == "connection"):
                continue
            lines.append(f"{k}: {v}")
        if not upgrade:
            lines.append("Connection: close")
        backend.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        self.close_connection = True
        client = self.connection
        socks = [client, backend]
        try:
            while True:
                readable, _, _ = select.select(socks, [], [], 300)
                if not readable:
                    break
                for s in readable:
                    data = s.recv(65536)
                    if not data:
                        return
                    (backend if s is client else client).sendall(data)
        except OSError:
            pass
        finally:
            backend.close()


PAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


# ---- persistence: survive tmux/server restarts -------------------------------------------
STATE_FILE = os.path.expanduser("~/.config/cc-panel/sessions.json")
state_lock = threading.Lock()


def tmux_server_pid():
    out = tmux("list-sessions", "-F", "#{pid}", check=False).split()
    return out[0] if out else None


def live_sessions():
    fmt = ("#{session_name}\t#{pane_current_path}\t#{pane_current_command}\t#{@cc_sid}\t#{@cc_skip}\t"
           "#{session_created}\t#{@cc_agent}\t#{@cc_source}\t#{@cc_title}")
    live = {}
    for line in tmux("list-sessions", "-F", fmt, check=False).splitlines():
        sname, path, cmd, sid, skip, created, agent, raw_source, title = (line.split("\t") + [""] * 9)[:9]
        agent = agent or "claude"
        try:
            source = json.loads(raw_source or "null")
        except ValueError:
            source = {"kind":"invalid"}
        if sname.startswith(PREFIX):
            live[sname[len(PREFIX):]] = {"path": path, "sid": sid or None, "skip": skip == "1", "agent": agent,
                                         "running": is_running(agent, cmd) if agent != "shell" else False,
                                         "created": int(created or 0), "source": source, "title": title or sname[len(PREFIX):]}
    return live


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def transcript_exists(sid):
    if not valid_sid(sid):
        return False
    root = os.path.expanduser("~/.claude/projects")
    return bool(sid) and any(os.path.exists(os.path.join(root, d, f"{sid}.jsonl"))
                             for d in os.listdir(root)) if os.path.isdir(root) else False


def valid_sid(sid):
    try:
        return str(uuid.UUID(sid)) == sid
    except (ValueError, TypeError, AttributeError):
        return False


def restore_session(name, info):
    path = info.get("path") or ""
    if not os.path.isdir(path):
        print(f"restore {name}: path {path!r} is gone, skipped", flush=True)
        return
    sid, skip, agent = info.get("sid"), bool(info.get("skip")), info.get("agent") or "claude"
    source = info.get("source")
    try:
        if source is not None and (not isinstance(source, dict) or source.get("kind") not in ("kimi", "lmstudio")):
            raise ValueError("Invalid saved model source")
        resume = agent_cmd(agent, sid, True, skip, source=source) if info.get("running") else None
    except ValueError as error:
        print(f"restore {name}: {error}; shell only", flush=True)
        resume = None
    if source is None:
        create_session(name, path, agent, skip, sid, resume)
    else:
        create_session(name, path, agent, skip, sid, resume, source)
    if info.get('title'):
        tmux('set-option', '-t', f'={PREFIX}{name}:', '@cc_title', info['title'])
    print(f"restored {name} ({agent}{', resumed' if resume else ', shell only'})", flush=True)


def sync_state():
    """Save live sessions; if the tmux server changed (reboot/crash), recreate the saved ones."""
    with state_lock:
        pid = tmux_server_pid()
        if not pid:
            return
        state = load_state()
        if state.get("server_pid") and state["server_pid"] != pid:
            live = live_sessions()
            for name, info in (state.get("sessions") or {}).items():
                if name not in live:
                    try:
                        restore_session(name, info)
                    except (RuntimeError, subprocess.TimeoutExpired) as e:
                        print(f"restore {name} failed: {e}", flush=True)
        new = {"server_pid": pid, "sessions": live_sessions()}
        for info in new["sessions"].values():
            info.pop("created", None)
        if new != state:
            save_state(new)


def sync_loop():
    cleanup_at = 0
    while True:
        try:
            sync_state()
            if time.time() >= cleanup_at:
                cleanup_uploads()
                cleanup_at = time.time() + 60
        except Exception as e:  # keep the loop alive whatever happens
            print(f"sync error: {e}", flush=True)
        time.sleep(5)


def main():
    if sys.platform == "darwin" and os.environ.get("TMUX_SOCKET_NAME") and not tmux_server_pid():
        config = os.path.expanduser("~/.config/cc-panel/tmux.conf")
        tmux("-f", config, "new-session", "-d", "-s", "_keep")
    if LMStudio:
        try:
            model_service()
            _model_relay.start()
            references = {source.get("binding") for info in list(load_state().get("sessions", {}).values()) + list(live_sessions().values()) if isinstance(source := info.get("source"), dict) and source.get("kind") == "lmstudio"}
            _model_relay.bindings.prune(references)
        except (OSError, ValueError):
            print('Local model relay could not be started', flush=True)
    auto_update_service().run()
    threading.Thread(target=sync_loop, daemon=True).start()
    threading.Thread(target=backup_loop, name='agent-deck-backups', daemon=True).start()
    try:
        from integrations import dependencies
        dependencies.ensure()  # Downloads pinned cryptography in the background when missing.
        if push_service().config['subscriptions']:
            push_service().start()
    except (ImportError, OSError, ValueError) as error:
        print(f'Notifications could not start: {error}', flush=True)
    if Telegram:
        try:
            telegram_service().start()
        except (OSError, ValueError):
            print('Telegram integration settings could not be loaded', flush=True)
    httpd = PanelHTTPServer((BIND_HOST, BIND_PORT), Handler)
    httpd.daemon_threads = True
    print(f"cc-panel on http://{BIND_HOST}:{BIND_PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
