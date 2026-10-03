#!/usr/bin/env python3
"""Web panel for Claude Code sessions in tmux (runs as the dev user).

- Login form (PANEL_USER / PANEL_PASSWORD) -> signed HttpOnly cookie on everything else
- /t/...  is proxied (incl. websocket) to ttyd listening on a private unix socket
- tmux sessions are named cc-<name>; each stores its Claude session id in @cc_sid
- sessions are persisted to ~/.config/cc-panel/sessions.json and restored after a reboot
"""
import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import shutil
import shlex
import select
import signal
import socket
import urllib.request
import urllib.error
from datetime import datetime
import subprocess
import sys
import threading
import time
import uuid
from http.cookies import SimpleCookie
from urllib.parse import parse_qs
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
import updater
import session_hook as kimi_config

BIND_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("BIND_PORT", "8790"))
PANEL_USER = os.environ.get("PANEL_USER", "dev")
PANEL_PASSWORD = os.environ["PANEL_PASSWORD"]
TTYD_SOCK = os.environ.get("TTYD_SOCK", f"/run/user/{os.getuid()}/cc-ttyd.sock")
PROJECTS = os.path.expanduser(os.environ.get("PROJECTS_DIR", "~/projects"))
TMUX_COMMAND = ["tmux"] + (["-L", os.environ["TMUX_SOCKET_NAME"]] if os.environ.get("TMUX_SOCKET_NAME") else [])
PREFIX = "cc-"
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
PROJ_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
GIT_RE = re.compile(r"^(https://|ssh://|git@)[\w.@:/~+-]+$")
BRANCH_RE = re.compile(r"^[\w][\w./-]{0,63}$")
# requests from these networks are a local reverse proxy (e.g. Traefik in Docker): trust X-Forwarded-*
TRUSTED_PROXIES = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
COOKIE = "cc_auth"
COOKIE_DAYS = 90
MAX_IMAGE_BYTES = 200 * 1024 * 1024
MAX_FILE_BYTES = 200 * 1024 * 1024
UPLOAD_DIR = os.path.expanduser("~/.config/cc-panel/uploads")
ATTACHMENT_RE = re.compile(r"^[0-9a-f]{32}(?:\.(png|jpg|webp|gif)|--[A-Za-z0-9_.-]{1,100})$")
HERE = os.path.dirname(os.path.abspath(__file__))
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

os.makedirs(PROJECTS, exist_ok=True)


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


def list_sessions(preview_name=None):
    fmt = ("#{session_name}\t#{session_created}\t#{session_attached}\t#{pane_current_path}\t"
           "#{pane_current_command}\t#{window_activity}\t#{@cc_agent}\t#{@cc_sid}\t#{@cc_skip}")
    out = tmux("list-sessions", "-F", fmt, check=False)
    result = []
    for line in out.splitlines():
        sname, created, attached, path, cmd, activity, agent, sid, skip = (line.split("\t") + [""] * 9)[:9]
        if not sname.startswith(PREFIX):
            continue
        name = sname[len(PREFIX):]
        rel = os.path.relpath(path, PROJECTS) if path.startswith(PROJECTS + os.sep) else path
        group = rel.split(os.sep)[0].removesuffix(".worktrees") if not rel.startswith("/") else "другое"
        agent = agent or "claude"
        item = {
            "name": name, "created": int(created or 0), "attached": int(attached or 0),
            "activity": int(activity or 0), "group": group, "agent": agent,
            "path": path, "running": is_running(agent, cmd), "command": cmd,
            "sid": sid or None, "skip": skip == "1",
        }
        if name == preview_name:
            preview_ansi = tmux("capture-pane", "-p", "-e", "-J", "-t", f"={sname}:", "-S", "-200", check=False)
            preview = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", preview_ansi).rstrip().splitlines()
            item.update(preview="\n".join(preview[-200:]), preview_ansi=preview_ansi)
        result.append(item)
    return sorted(result, key=lambda s: (s["group"], s["name"]))


AGENTS = {
    # name: (label, process names as seen in pane_current_command, skip-permissions flag)
    "claude": ("Claude", {"claude"}, " --dangerously-skip-permissions"),
    "codex": ("Codex", {"codex", "codex-x86_64-un", "codex-aarch64-u"}, " --dangerously-bypass-approvals-and-sandbox"),
    "claude-kimi": ("Claude · Kimi", {"claude"}, " --dangerously-skip-permissions"),
    "kimi": ("Kimi Code", {"kimi", "kimi-code"}, " --auto"),
    "shell": ("Терминал", set(), ""),
}
SHELLS = {"bash", "zsh", "sh", "fish", "dash"}
INSTALLERS = {
    "claude": "curl -fsSL https://claude.ai/install.sh | bash",
    "codex": "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
}
INSTALLERS["kimi"] = "curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash"
LOGINS = {
    "claude": "claude",  # first start asks to log in; afterwards /login switches accounts
    "codex": "codex login --device-auth",
}


def is_running(agent, cmd):
    if agent == "shell":
        return cmd not in SHELLS
    return cmd in AGENTS[agent][1]


def agent_cmd(agent, sid=None, resume=False, skip=False, name=None):
    """Shell command that starts (or resumes) the agent in a pane; None for a plain terminal."""
    if agent == "shell":
        return None
    flag = AGENTS[agent][2] if skip else ""
    launcher = ""
    if agent in ("kimi", "claude-kimi"):
        if not kimi_config.status()["configured"]:
            raise ValueError("Сначала сохраните ключ Kimi в настройках панели")
        if not kimi_config.executable(agent):
            raise ValueError("Сначала установите " + ("Claude" if agent == "claude-kimi" else "Kimi Code"))
        launcher = shlex.join([sys.executable, os.path.join(HERE, "session_hook.py"), agent])
    if agent == "kimi":
        if resume and not (isinstance(sid, str) and sid.startswith("session_") and valid_sid(sid[8:])):
            raise ValueError("ID разговора Kimi не сохранён. Выберите разговор вручную в терминале.")
        return launcher + (" --session " + shlex.quote(sid) if resume else "") + flag
    if agent == "codex":
        if resume and not valid_sid(sid):
            raise ValueError("ID разговора Codex не сохранён. Возобновите нужный разговор через codex resume; автоматический выбор последнего отключён.")
        return f"codex --no-daemon resume {shlex.quote(sid)}{flag}" if resume else f"codex --no-daemon{flag}"
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
    wt = os.path.join(PROJECTS, f"{project}.worktrees", name)
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
    path = os.path.join(PROJECTS, project)
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


def create_session(name, path, agent, skip, sid=None, command=None):
    tmux("new-session", "-d", "-s", f"{PREFIX}{name}", "-c", path, "-x", "200", "-y", "50")
    tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_agent", agent)
    tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_skip", "1" if skip else "0")
    if sid:
        tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_sid", sid)
    if command:
        time.sleep(0.5)
        type_line(name, command)


def action_new(d):
    name, agent = d.get("name", ""), d.get("agent") or "claude"
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError("имя сессии: латиница, цифры, - и _, до 32 символов")
    if agent not in AGENTS:
        raise ValueError("неизвестный агент")
    if session_exists(name):
        raise ValueError(f"сессия {name} уже есть")
    path = resolve_path(d, name)
    skip = bool(d.get("skip")) and agent != "shell"
    sid = str(uuid.uuid4()) if agent in ("claude", "claude-kimi") else None
    create_session(name, path, agent, skip, sid, agent_cmd(agent, sid, False, skip, name))


def action_restart(d):
    name = d.get("name", "")
    if not session_exists(name):
        raise ValueError("нет такой сессии")
    skip, agent = opt(name, "@cc_skip") == "1", opt(name, "@cc_agent") or "claude"
    sid = opt(name, "@cc_sid")
    new = d.get("mode") == "new"
    if new and agent in ("claude", "claude-kimi"):
        sid = str(uuid.uuid4())
    elif new and agent in ("codex", "kimi"):
        sid = None
    cmd = agent_cmd(agent, sid, not new, skip, name)
    stop_children(name)
    if new and agent != "shell":
        if sid:
            tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_sid", sid)
        else:
            tmux("set-option", "-t", f"={PREFIX}{name}:", "-u", "@cc_sid")
    time.sleep(0.3)
    tmux("send-keys", "-t", f"={PREFIX}{name}:", "C-u")
    type_line(name, "clear" + (f"; {cmd}" if cmd else ""))


def action_kill(d):
    name = d.get("name", "")
    if session_exists(name):
        tmux("kill-session", "-t", f"={PREFIX}{name}:")
    if isinstance(name, str) and NAME_RE.fullmatch(name):
        shutil.rmtree(os.path.join(UPLOAD_DIR, name), ignore_errors=True)


def attachment_dir(name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError("неверное имя сессии")
    return os.path.join(UPLOAD_DIR, name)


def action_upload(d):
    name = d.get("name", "")
    folder = attachment_dir(name)
    if not session_exists(name):
        raise ValueError("нет такой сессии")
    if (opt(name, "@cc_agent") or "claude") == "shell":
        raise ValueError("файлы можно приложить к Claude или Codex")
    filename = d.get("filename")
    if filename is not None and (not isinstance(filename, str) or not filename or len(filename) > 255
                                 or any(c in filename for c in ("/", "\\", "\0", "\n", "\r"))):
        raise ValueError("неверное имя файла")
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
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = "png"
    elif image.startswith(b"\xff\xd8\xff"):
        ext = "jpg"
    elif image.startswith((b"GIF87a", b"GIF89a")):
        ext = "gif"
    elif image.startswith(b"RIFF") and image[8:12] == b"WEBP":
        ext = "webp"
    else:
        ext = None
        if not filename:
            raise ValueError("укажите имя файла")
    if ext and len(image) > MAX_IMAGE_BYTES:
        raise ValueError("изображение слишком большое (максимум 200 МБ)")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", filename or "file")[-100:]
    attachment = uuid.uuid4().hex + ("." + ext if ext else "--" + safe_name)
    fd = os.open(os.path.join(folder, attachment), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(image)
    return {"attachment": attachment, "kind": "image" if ext else "file", "size": len(image)}


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
                    if (ATTACHMENT_RE.fullmatch(entry.name) and entry.is_file(follow_symlinks=False)
                            and entry.stat(follow_symlinks=False).st_mtime < cutoff):
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
        files = [path for path in paths if "--" in os.path.basename(path)]
        if paths:
            text = (text + "\n\nВложения временные: удаляются с сервера через 7 дней после загрузки. "
                    "Если они нужны надолго, сохрани их в подходящем месте в проекте.").lstrip()
        paths = [path for path in paths if "--" not in os.path.basename(path)]
        if files:
            text = (text + "\n\nПриложенные файлы (прочитай их с диска):\n" + "\n".join(files)).lstrip()
        if paths and agent == "codex":
            for path in paths:
                paste_to_tmux(name, path)
            if text:
                paste_to_tmux(name, text)
        else:
            if paths:
                text = (text + "\n\nПосмотри приложенные изображения:\n" + "\n".join(paths)).lstrip()
            if paths:
                paste_to_tmux(name, text)
            elif text:
                paste_to_tmux(name, text, bracketed=agent != "shell")
        tmux("send-keys", "-t", f"={PREFIX}{name}:", "Enter")


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
    auth = {"claude": os.path.join(home, ".claude", ".credentials.json"),
            "codex": os.path.join(home, ".codex", "auth.json")}[agent]
    logged_in = os.path.exists(auth)
    if agent == "claude" and sys.platform == "darwin" and not logged_in and installed:
        logged_in = bool(cached("claude-keychain", 60, claude_credentials).get("claudeAiOauth", {}).get("accessToken"))
    return {"installed": installed, "version": version, "logged_in": logged_in}


# ---- server info & subscription limits ---------------------------------------------------
_cache = {}


def cached(key, ttl, fn):
    """Return fn() cached for ttl seconds; on failure keep serving the last good value (marked stale)."""
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception as e:  # network/auth errors must not break the panel
        # remember the failure only briefly (max 5 min), so a transient error doesn't stick for the whole ttl
        _cache[key] = (time.time() - ttl + min(ttl, 300), {**hit[1], "stale": True} if hit and "error" not in hit[1]
                       else {"error": str(e)[:200]})
        return _cache[key][1]
    _cache[key] = (time.time(), val)
    return val


def http_json(url, headers=None, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "cc-panel", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _semver(v):
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", v or "")
    return tuple(map(int, m.groups())) if m else None


def version_info():
    info = {"version": VERSION, "checkout": CHECKOUT, "repo": UPDATE_REPO,
            "can_update": updater.available(HERE, UPDATE_REPO), "job": updater.status(UPDATE_STATE)}
    if not UPDATE_REPO:
        return info

    def fetch():
        r = http_json(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                      {"Accept": "application/vnd.github+json"}, timeout=8)
        return {"latest": (r.get("tag_name") or "").lstrip("v"), "url": r.get("html_url")}
    rel = cached("release", 6 * 3600, fetch)
    if rel.get("latest"):
        cur, new = _semver(VERSION), _semver(rel["latest"])
        info.update(latest=rel["latest"], url=rel["url"], update=bool(cur and new and new > cur))
    return info


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


def _epoch(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) if iso else None


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
    o = claude_credentials().get("claudeAiOauth") or {}
    if not o.get("accessToken"):
        return {"error": "Войдите в Claude Code для просмотра лимитов"}
    if (o.get("expiresAt") or 0) / 1000 < time.time():
        # never refresh here: Claude rotates refresh tokens, a second refresher would log it out
        return {"plan": o.get("subscriptionType"), "error": "токен истёк — запустите Claude, он обновит его"}
    d = http_json("https://api.anthropic.com/api/oauth/usage",
                  {"Authorization": "Bearer " + o["accessToken"], "anthropic-beta": "oauth-2025-04-20"})
    windows = []
    week = 7 * 86400
    for key, label, secs in (("seven_day", "неделя", week),
                             ("seven_day_opus", "неделя Opus", week), ("seven_day_sonnet", "неделя Sonnet", week)):
        w = d.get(key)
        if w and w.get("utilization") is not None:
            windows.append({"label": label, "percent": w["utilization"], "resets_at": _epoch(w.get("resets_at")),
                            "secs": secs})
    return {"plan": o.get("subscriptionType"), "windows": windows}


def codex_usage():
    with open(os.path.expanduser("~/.codex/auth.json")) as stream:
        t = json.load(stream).get("tokens") or {}
    if not t.get("access_token"):
        return {"error": "Codex вошёл по API-ключу: лимитов подписки нет"}
    d = http_json("https://chatgpt.com/backend-api/wham/usage",
                  {"Authorization": "Bearer " + t["access_token"], "ChatGPT-Account-Id": t.get("account_id", "")})
    windows = []
    for w in ((d.get("rate_limit") or {}).get("primary_window"), (d.get("rate_limit") or {}).get("secondary_window")):
        if not w:
            continue
        secs = w.get("limit_window_seconds") or 0
        label = {18000: "5 ч", 604800: "неделя"}.get(secs, f"{round(secs / 3600)} ч")
        windows.append({"label": label, "percent": w.get("used_percent"), "resets_at": w.get("reset_at"), "secs": secs})
    windows.sort(key=lambda w: w["secs"])
    return {"plan": d.get("plan_type"), "windows": windows}


def kimi_usage():
    key = kimi_config.read().get("key")
    if not key:
        return {"error": "Сохраните ключ Kimi в настройках панели"}
    try:
        data = http_json("https://api.kimi.com/coding/v1/usages", {"Authorization": "Bearer " + key, "Accept": "application/json"})
    except urllib.error.HTTPError as error:
        error.close()
        return {"error": "Kimi: проверьте ключ" if error.code in (401, 403) else "Kimi: лимиты временно недоступны"}
    except (OSError, ValueError):
        return {"error": "Kimi: лимиты временно недоступны"}
    windows = []
    authoritative = set()
    # The counters in limits are authoritative. The legacy usages.limit_5h can
    # incorrectly report zero even while the service rejects calls at 100/100.
    for limit in data.get("limits") or []:
        if not isinstance(limit, dict):
            continue
        window, detail = limit.get("window") or {}, limit.get("detail") or {}
        try:
            multiplier = {"TIME_UNIT_SECOND": 1, "TIME_UNIT_MINUTE": 60,
                          "TIME_UNIT_HOUR": 3600, "TIME_UNIT_DAY": 86400}[window["timeUnit"]]
            secs = float(window["duration"]) * multiplier
            if not math.isfinite(secs) or secs <= 0:
                continue
            authoritative.add(secs)
            total, used = float(detail["limit"]), float(detail["used"])
            if not all(map(math.isfinite, (total, used))) or total <= 0 or used < 0:
                continue
            reset = _epoch(detail.get("resetTime"))
            label = {18000: "5 часов", 604800: "неделя"}.get(secs, f"{secs / 3600:g} ч")
            windows.append({"label": label, "percent": used / total * 100,
                            "resets_at": reset, "secs": secs, "period": "hours"})
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    for name, label, secs, period in (
            ("limit_month_total", "Общий · месяц", 0, "month"),
            ("limit_month_code", "Kimi Code · месяц", 0, "month"),
            ("limit_5h", "5 часов", 18000, "hours"),
            ("limit_7d", "неделя", 604800, "week")):
        if secs and secs in authoritative:
            continue
        value = (data.get("usages") or {}).get(name)
        if not isinstance(value, dict):
            continue
        try:
            ratio = float(value["used_ratio"])
            if not math.isfinite(ratio) or ratio < 0:
                continue
            reset = _epoch(value.get("reset_time"))
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
        # Calendar months vary in length. Do not invent a 30-day pace/forecast.
        windows.append({"label": label, "percent": ratio * 100, "resets_at": reset, "secs": secs, "period": period})
    return {"windows": windows} if windows else {"error": "Kimi не вернул данные о квотах"}


def usage():
    out = {}
    for agent, fn in (("claude", claude_usage), ("codex", codex_usage), ("kimi", kimi_usage)):
        if agent_status(agent)["logged_in"]:
            cache_key = f"usage-{agent}"
            if agent == "kimi":
                cache_key += "-" + hashlib.sha256(kimi_config.read().get("key", "").encode()).hexdigest()
            out[agent] = cached(cache_key, 60, fn)
    return out


ACTIONS = {"kimi_config": lambda d: {"kimi": kimi_config.save(d)}, "agent_install": action_agent_install, "agent_login": action_agent_login, "github_login": action_github_login, "new": action_new, "restart": action_restart, "kill": action_kill, "send": action_send, "upload": action_upload, "update": action_update, "discard_upload": action_discard_upload}


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
        print(f"{self.client_ip()} {fmt % args}", flush=True)

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

    def authorized(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if COOKIE in cookie and token_valid(cookie[COOKIE].value):
            return True
        if self.path.startswith("/api/") or self.path.startswith("/t"):
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

    def login_page(self, error=""):
        with open(os.path.join(HERE, "login.html"), encoding="utf-8") as login_file:
            html = login_file.read()
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
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
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
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, obj):
        self.send_body(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

    def do_GET(self):
        try:
            return self.get_request()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.close_connection = True
            self.send_json(500, {"error": "не удалось обработать запрос"})

    def get_request(self):
        if self.path in STATIC:
            return self.serve_static()
        if self.path == "/login":
            return self.login_page()
        if not self.authorized():
            return
        if self.path.startswith("/t/") or self.path == "/t":
            return self.proxy_tty()
        if self.path in ("/", "/index.html"):
            with open(PAGE_FILE, "rb") as f:
                page = f.read()
            revision = hashlib.sha256(page).hexdigest().encode()
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
        if self.path == "/api/usage":
            return self.send_json(200, usage())
        if self.path == "/api/version":
            return self.send_json(200, version_info())
        if self.path == "/api/server-metrics":
            return self.send_json(200, server_metrics())
        if self.path == "/api/server":
            return self.send_json(200, server_info())
        if self.path == "/api/agents":
            return self.send_json(200, {**{a: agent_status(a) for a in (*INSTALLERS, "claude-kimi")}, "kimi_config": kimi_config.status()})
        if self.path == "/api/github/status":
            return self.send_json(200, github_status())
        if self.path.startswith("/api/github/repos"):
            try:
                return self.send_json(200, {"repos": github_repos("refresh=1" in self.path)})
            except (RuntimeError, subprocess.TimeoutExpired) as e:
                return self.send_json(502, {"error": str(e)})
        if self.path == "/api/projects":
            dirs = sorted(e.name for e in os.scandir(PROJECTS)
                          if e.is_dir() and not e.name.startswith(".") and not e.name.endswith(".worktrees"))
            return self.send_json(200, {"projects": dirs})
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        try:
            return self.post_request()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.close_connection = True
            self.send_json(500, {"error": "не удалось обработать запрос"})

    def post_request(self):
        global actions_in_progress
        if self.path == "/login":
            return self.do_login()
        if self.path == "/logout":
            if not self.same_origin():
                self.close_connection = True
                return self.send_json(403, {"error": "неверный источник запроса"})
            return self.redirect("/login", f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
        if not self.authorized():
            return
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
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("неверный запрос")
            action = m.group(1)
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
           "#{session_created}\t#{@cc_agent}")
    live = {}
    for line in tmux("list-sessions", "-F", fmt, check=False).splitlines():
        sname, path, cmd, sid, skip, created, agent = (line.split("\t") + [""] * 7)[:7]
        agent = agent or "claude"
        if sname.startswith(PREFIX):
            live[sname[len(PREFIX):]] = {"path": path, "sid": sid or None, "skip": skip == "1", "agent": agent,
                                         "running": is_running(agent, cmd) if agent != "shell" else False,
                                         "created": int(created or 0)}
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
    try:
        resume = agent_cmd(agent, sid, True, skip) if info.get("running") else None
    except ValueError as error:
        print(f"restore {name}: {error}; shell only", flush=True)
        resume = None
    create_session(name, path, agent, skip, sid, resume)
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
    threading.Thread(target=sync_loop, daemon=True).start()
    httpd = PanelHTTPServer((BIND_HOST, BIND_PORT), Handler)
    httpd.daemon_threads = True
    print(f"cc-panel on http://{BIND_HOST}:{BIND_PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
