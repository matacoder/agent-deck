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
import os
import re
import select
import signal
import socket
import urllib.request
from datetime import datetime
import subprocess
import threading
import time
import uuid
from http.cookies import SimpleCookie
from urllib.parse import parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BIND_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("BIND_PORT", "8790"))
PANEL_USER = os.environ.get("PANEL_USER", "dev")
PANEL_PASSWORD = os.environ["PANEL_PASSWORD"]
TTYD_SOCK = os.environ.get("TTYD_SOCK", f"/run/user/{os.getuid()}/cc-ttyd.sock")
PROJECTS = os.path.expanduser(os.environ.get("PROJECTS_DIR", "~/projects"))
PREFIX = "cc-"
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
PROJ_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
GIT_RE = re.compile(r"^(https://|ssh://|git@)[\w.@:/~+-]+$")
BRANCH_RE = re.compile(r"^[\w][\w./-]{0,63}$")
# requests from these networks are a local reverse proxy (e.g. Traefik in Docker): trust X-Forwarded-*
TRUSTED_PROXIES = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
COOKIE = "cc_auth"
COOKIE_DAYS = 90
MAX_IMAGE_BYTES = 8 * 1024 * 1024
UPLOAD_DIR = os.path.expanduser("~/.config/cc-panel/uploads")
ATTACHMENT_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp|gif)$")
HERE = os.path.dirname(os.path.abspath(__file__))
try:
    VERSION = open(os.path.join(HERE, "VERSION")).read().strip()
except OSError:
    VERSION = "dev"
UPDATE_REPO = os.environ.get("UPDATE_REPO", "matacoder/agent-deck")   # "" disables the update check
CHECKOUT = os.environ.get("CHECKOUT", "")                             # where install.sh ran from
STATIC = {"/icon-180.png": "image/png", "/icon-192.png": "image/png", "/icon-512.png": "image/png",
          "/manifest.webmanifest": "application/manifest+json"}


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
failed_logins = {}  # ip -> (count, last_ts)


def make_token():
    exp = str(int(time.time()) + COOKIE_DAYS * 86400)
    sig = hmac.new(COOKIE_KEY, exp.encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def token_valid(token):
    exp, _, sig = (token or "").partition(".")
    if not exp.isdigit() or int(exp) < time.time():
        return False
    return hmac.compare_digest(sig, hmac.new(COOKIE_KEY, exp.encode(), hashlib.sha256).hexdigest())

os.makedirs(PROJECTS, exist_ok=True)


def tmux(*args, check=True):
    r = subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=10)
    if check and r.returncode:
        raise RuntimeError(r.stderr.strip() or f"tmux {args[0]} failed")
    return r.stdout


def session_exists(name):
    return subprocess.run(["tmux", "has-session", "-t", f"={PREFIX}{name}:"], capture_output=True).returncode == 0


def opt(name, key):
    out = tmux("show-options", "-t", f"={PREFIX}{name}:", "-qv", key, check=False).strip()
    return out or None


def list_sessions():
    fmt = ("#{session_name}\t#{session_created}\t#{session_attached}\t#{pane_current_path}\t"
           "#{pane_current_command}\t#{window_activity}")
    out = tmux("list-sessions", "-F", fmt, check=False)
    result = []
    for line in out.splitlines():
        sname, created, attached, path, cmd, activity = (line.split("\t") + [""] * 6)[:6]
        if not sname.startswith(PREFIX):
            continue
        name = sname[len(PREFIX):]
        preview_ansi = tmux("capture-pane", "-p", "-e", "-J", "-t", f"={sname}:", "-S", "-200", check=False)
        preview = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", preview_ansi).rstrip().splitlines()
        rel = os.path.relpath(path, PROJECTS) if path.startswith(PROJECTS + os.sep) else path
        group = rel.split(os.sep)[0].removesuffix(".worktrees") if not rel.startswith("/") else "другое"
        agent = opt(name, "@cc_agent") or "claude"
        result.append({
            "name": name, "created": int(created or 0), "attached": int(attached or 0),
            "activity": int(activity or 0), "group": group, "agent": agent,
            "path": path, "running": is_running(agent, cmd), "command": cmd,
            "sid": opt(name, "@cc_sid"), "skip": opt(name, "@cc_skip") == "1",
            "preview": "\n".join(preview[-200:]), "preview_ansi": preview_ansi,
        })
    return sorted(result, key=lambda s: (s["group"], s["name"]))


AGENTS = {
    # name: (label, process names as seen in pane_current_command, skip-permissions flag)
    "claude": ("Claude", {"claude"}, " --dangerously-skip-permissions"),
    "codex": ("Codex", {"codex", "codex-x86_64-un", "codex-aarch64-u"}, " --dangerously-bypass-approvals-and-sandbox"),
    "shell": ("Терминал", set(), ""),
}
SHELLS = {"bash", "zsh", "sh", "fish", "dash"}
INSTALLERS = {
    "claude": "curl -fsSL https://claude.ai/install.sh | bash",
    "codex": "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
}
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
    if agent == "codex":
        # resume --last is scoped to the current directory
        return f"codex resume --last{flag} || codex{flag}" if resume else f"codex{flag}"
    if resume:
        if transcript_exists(sid):
            return f"claude --resume {sid}{flag}"
        return f"claude --continue{flag} || claude{flag}"
    return f"claude --session-id {sid}{flag}" + (f" -n {name}" if name else "")


def type_line(name, text):
    tmux("send-keys", "-t", f"={PREFIX}{name}:", "-l", text)
    tmux("send-keys", "-t", f"={PREFIX}{name}:", "Enter")


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
        while time.time() < deadline and any(os.path.exists(f"/proc/{p}") for p in pids):
            time.sleep(0.2)
        if not any(os.path.exists(f"/proc/{p}") for p in pids):
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
    home = os.path.expanduser("~")
    if d.get("path"):
        path = os.path.realpath(d["path"])
        if not (path == home or path.startswith(home + os.sep)) or not os.path.isdir(path):
            raise ValueError("папка должна существовать и быть внутри домашнего каталога")
        return path
    project = d.get("project") or name
    if not PROJ_RE.match(project) or ".." in project or project.endswith(".worktrees"):
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
    if not NAME_RE.match(name):
        raise ValueError("имя сессии: латиница, цифры, - и _, до 32 символов")
    if agent not in AGENTS:
        raise ValueError("неизвестный агент")
    if session_exists(name):
        raise ValueError(f"сессия {name} уже есть")
    path = resolve_path(d, name)
    skip = bool(d.get("skip")) and agent != "shell"
    sid = str(uuid.uuid4()) if agent == "claude" else None
    create_session(name, path, agent, skip, sid, agent_cmd(agent, sid, False, skip, name))


def action_restart(d):
    name = d.get("name", "")
    if not session_exists(name):
        raise ValueError("нет такой сессии")
    skip, agent = opt(name, "@cc_skip") == "1", opt(name, "@cc_agent") or "claude"
    stop_children(name)
    sid = opt(name, "@cc_sid")
    if d.get("mode") == "new" and agent == "claude":
        sid = str(uuid.uuid4())
        tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_sid", sid)
    cmd = agent_cmd(agent, sid, d.get("mode") != "new", skip, name)
    time.sleep(0.3)
    tmux("send-keys", "-t", f"={PREFIX}{name}:", "C-u")
    type_line(name, "clear" + (f"; {cmd}" if cmd else ""))


def action_kill(d):
    name = d.get("name", "")
    if session_exists(name):
        tmux("kill-session", "-t", f"={PREFIX}{name}:")


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
        raise ValueError("изображения можно приложить к Claude или Codex")
    encoded = d.get("data", "")
    if not isinstance(encoded, str) or len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        raise ValueError("изображение слишком большое (максимум 8 МБ)")
    try:
        image = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("неверные данные изображения") from None
    if not image or len(image) > MAX_IMAGE_BYTES:
        raise ValueError("изображение слишком большое или пустое")
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = "png"
    elif image.startswith(b"\xff\xd8\xff"):
        ext = "jpg"
    elif image.startswith((b"GIF87a", b"GIF89a")):
        ext = "gif"
    elif image.startswith(b"RIFF") and image[8:12] == b"WEBP":
        ext = "webp"
    else:
        raise ValueError("нужен PNG, JPEG, WebP или GIF")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    attachment = uuid.uuid4().hex + "." + ext
    fd = os.open(os.path.join(folder, attachment), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(image)
    return {"attachment": attachment}


def attachment_paths(name, attachments):
    if not isinstance(attachments, list) or len(attachments) > 4:
        raise ValueError("можно приложить до 4 изображений")
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


def paste_to_tmux(name, text):
    # Codex recognizes an image path through its bracketed-paste handler.
    tmux("send-keys", "-t", f"={PREFIX}{name}:", "-l", "\x1b[200~" + text + "\x1b[201~")
    time.sleep(0.2)


def action_send(d):
    name = d.get("name", "")
    if not session_exists(name):
        raise ValueError("нет такой сессии")
    key = d.get("key")
    if key in ("Escape", "Enter", "C-c", "Up", "Down", "Tab", "BTab"):
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
            raise ValueError("изображения можно приложить к Claude или Codex")
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
                tmux("send-keys", "-t", f"={PREFIX}{name}:", "-l", text)
                time.sleep(0.15)
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
    name = "github-login"
    if session_exists(name):
        tmux("kill-session", "-t", f"={PREFIX}{name}:")
    tmux("new-session", "-d", "-s", f"{PREFIX}{name}", "-c", os.path.expanduser("~"), "-x", "200", "-y", "50")
    time.sleep(0.5)
    type_line(name, GH_LOGIN_CMD)


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
    path = os.path.join(home, ".local", "bin", agent)
    installed = os.path.exists(path)
    version = None
    if installed:
        real = os.path.realpath(path)
        key = (real, os.path.getmtime(real))
        if _version_cache.get(agent, (None,))[0] != key:  # re-run --version only after an install/update
            r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
            v = (r.stdout.strip().split() or [None])[-1] if agent == "codex" else (r.stdout.split() or [None])[0]
            _version_cache[agent] = (key, v)
        version = _version_cache[agent][1]
    auth = {"claude": os.path.join(home, ".claude", ".credentials.json"),
            "codex": os.path.join(home, ".codex", "auth.json")}[agent]
    return {"installed": installed, "version": version, "logged_in": os.path.exists(auth)}


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
    info = {"version": VERSION, "checkout": CHECKOUT, "repo": UPDATE_REPO}
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


def server_info():
    def fetch():
        geo = http_json("https://ipinfo.io/json", timeout=6)
        return {"ip": geo.get("ip"), "country": geo.get("country"), "city": geo.get("city"), "org": geo.get("org")}
    info = dict(cached("geo", 6 * 3600, fetch))
    info.update(hostname=socket.gethostname(), tailscale_ip=BIND_HOST)
    return info


def _epoch(iso):
    return int(datetime.fromisoformat(iso).timestamp()) if iso else None


def claude_usage():
    o = json.load(open(os.path.expanduser("~/.claude/.credentials.json"))).get("claudeAiOauth") or {}
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
    t = json.load(open(os.path.expanduser("~/.codex/auth.json"))).get("tokens") or {}
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


def usage():
    out = {}
    for agent, fn in (("claude", claude_usage), ("codex", codex_usage)):
        if agent_status(agent)["logged_in"]:
            out[agent] = cached(f"usage-{agent}", 60, fn)
    return out


ACTIONS = {"agent_install": action_agent_install, "agent_login": action_agent_login, "github_login": action_github_login, "new": action_new, "restart": action_restart, "kill": action_kill, "send": action_send, "upload": action_upload}


class Handler(BaseHTTPRequestHandler):
    server_version = "cc-panel/1.0"
    protocol_version = "HTTP/1.1"

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
        return self.via_proxy() and self.headers.get("X-Forwarded-Proto", "").lower() == "https"

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
        html = open(os.path.join(HERE, "login.html"), encoding="utf-8").read()
        html = html.replace("{{ERROR}}", error).replace("{{USER}}", PANEL_USER)
        self.send_body(200 if not error else 401, html.encode(), "text/html; charset=utf-8")

    def do_login(self):
        ip = self.client_ip()
        count, last = failed_logins.get(ip, (0, 0))
        if count >= 5 and time.time() - last < 60:
            return self.login_page("Слишком много попыток. Подождите минуту.")
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(min(length, 10_000)).decode("utf-8", "replace"))
        user, pwd = form.get("username", [""])[0], form.get("password", [""])[0]
        ok = hmac.compare_digest(user.encode(), PANEL_USER.encode()) & hmac.compare_digest(pwd.encode(), PANEL_PASSWORD.encode())
        if not ok:
            failed_logins[ip] = (count + 1, time.time())
            time.sleep(1)
            return self.login_page("Неверный логин или пароль")
        failed_logins.pop(ip, None)
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
        if self.path == "/api/sessions":
            return self.send_json(200, {"sessions": list_sessions()})
        if self.path == "/api/usage":
            return self.send_json(200, usage())
        if self.path == "/api/version":
            return self.send_json(200, version_info())
        if self.path == "/api/server":
            return self.send_json(200, server_info())
        if self.path == "/api/agents":
            return self.send_json(200, {a: agent_status(a) for a in INSTALLERS})
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
        if self.path == "/login":
            return self.do_login()
        if self.path == "/logout":
            return self.redirect("/login", f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
        if not self.authorized():
            return
        m = re.match(r"^/api/(\w+)$", self.path)
        if not m or m.group(1) not in ACTIONS:
            return self.send_json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            limit = 12 * 1024 * 1024 if m.group(1) == "upload" else 1_000_000
            if length < 0 or length > limit:
                self.close_connection = True
                return self.send_json(413, {"error": "файл или сообщение слишком большое"})
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("неверный запрос")
            result = ACTIONS[m.group(1)](data)
            self.send_json(200, {"ok": True, **(result or {})})
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
            self.send_json(400, {"error": str(e)})

    def proxy_tty(self):
        """Raw pass-through to ttyd (HTTP + websocket upgrade)."""
        upgrade = "websocket" in self.headers.get("Upgrade", "").lower()
        backend = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            backend.connect(TTYD_SOCK)
        except OSError as e:
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
    root = os.path.expanduser("~/.claude/projects")
    return bool(sid) and any(os.path.exists(os.path.join(root, d, f"{sid}.jsonl"))
                             for d in os.listdir(root)) if os.path.isdir(root) else False


def restore_session(name, info):
    path = info.get("path") or ""
    if not os.path.isdir(path):
        print(f"restore {name}: path {path!r} is gone, skipped", flush=True)
        return
    sid, skip, agent = info.get("sid"), bool(info.get("skip")), info.get("agent") or "claude"
    resume = agent_cmd(agent, sid, True, skip) if info.get("running") else None
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
    while True:
        try:
            sync_state()
        except Exception as e:  # keep the loop alive whatever happens
            print(f"sync error: {e}", flush=True)
        time.sleep(5)


def main():
    threading.Thread(target=sync_loop, daemon=True).start()
    httpd = ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler)
    httpd.daemon_threads = True
    print(f"cc-panel on http://{BIND_HOST}:{BIND_PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
