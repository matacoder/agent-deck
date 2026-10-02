#!/usr/bin/env python3
"""Web panel for Claude Code sessions in tmux (runs as the dev user).

- Login form (PANEL_USER / PANEL_PASSWORD) -> signed HttpOnly cookie on everything else
- /t/...  is proxied (incl. websocket) to ttyd listening on a private unix socket
- tmux sessions are named cc-<name>; each stores its Claude session id in @cc_sid
- sessions are persisted to ~/.config/cc-panel/sessions.json and restored after a reboot
"""
import hashlib
import hmac
import json
import os
import re
import select
import signal
import socket
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
COOKIE = "cc_auth"
COOKIE_DAYS = 90
HERE = os.path.dirname(os.path.abspath(__file__))
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
        preview = tmux("capture-pane", "-p", "-J", "-t", f"={sname}:", "-S", "-40", check=False).rstrip().splitlines()
        rel = os.path.relpath(path, PROJECTS) if path.startswith(PROJECTS + os.sep) else path
        group = rel.split(os.sep)[0].removesuffix(".worktrees") if not rel.startswith("/") else "другое"
        result.append({
            "name": name, "created": int(created or 0), "attached": int(attached or 0),
            "activity": int(activity or 0), "group": group,
            "path": path, "running": cmd == "claude", "command": cmd,
            "sid": opt(name, "@cc_sid"), "skip": opt(name, "@cc_skip") == "1",
            "preview": "\n".join(preview[-25:]),
        })
    return sorted(result, key=lambda s: (s["group"], s["name"]))


def claude_cmd(sid, resume, skip):
    cmd = f"claude --resume {sid}" if resume else f"claude --session-id {sid}"
    if skip:
        cmd += " --dangerously-skip-permissions"
    return cmd


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


def action_new(d):
    name, project = d.get("name", ""), d.get("project") or d.get("name", "")
    if not NAME_RE.match(name):
        raise ValueError("имя сессии: латиница, цифры, - и _, до 32 символов")
    if not PROJ_RE.match(project) or ".." in project or project.endswith(".worktrees"):
        raise ValueError("неверное имя проекта")
    if session_exists(name):
        raise ValueError(f"сессия {name} уже есть")
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
    sid, skip = str(uuid.uuid4()), bool(d.get("skip"))
    tmux("new-session", "-d", "-s", f"{PREFIX}{name}", "-c", path, "-x", "200", "-y", "50")
    tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_sid", sid)
    tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_skip", "1" if skip else "0")
    time.sleep(0.5)
    type_line(name, claude_cmd(sid, False, skip) + f" -n {name}")


def action_restart(d):
    name = d.get("name", "")
    if not session_exists(name):
        raise ValueError("нет такой сессии")
    skip = opt(name, "@cc_skip") == "1"
    stop_children(name)
    if d.get("mode") == "new":
        sid = str(uuid.uuid4())
        tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_sid", sid)
        cmd = claude_cmd(sid, False, skip) + f" -n {name}"
    else:
        sid = opt(name, "@cc_sid")
        cmd = claude_cmd(sid, True, skip) if sid else "claude --continue"
    time.sleep(0.3)
    tmux("send-keys", "-t", f"={PREFIX}{name}:", "C-u")
    type_line(name, "clear; " + cmd)


def action_kill(d):
    name = d.get("name", "")
    if session_exists(name):
        tmux("kill-session", "-t", f"={PREFIX}{name}:")


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
        if text:
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


ACTIONS = {"github_login": action_github_login, "new": action_new, "restart": action_restart, "kill": action_kill, "send": action_send}


class Handler(BaseHTTPRequestHandler):
    server_version = "cc-panel/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} {fmt % args}", flush=True)

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
        ip = self.client_address[0]
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
        self.redirect("/", f"{COOKIE}={make_token()}; Path=/; Max-Age={COOKIE_DAYS * 86400}; HttpOnly; SameSite=Lax")

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
            return self.send_body(200, open(PAGE_FILE, "rb").read(), "text/html; charset=utf-8")
        if self.path == "/api/sessions":
            return self.send_json(200, {"sessions": list_sessions()})
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
            data = json.loads(self.rfile.read(min(length, 1_000_000)) or b"{}")
            ACTIONS[m.group(1)](data)
            self.send_json(200, {"ok": True})
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
    fmt = "#{session_name}\t#{pane_current_path}\t#{pane_current_command}\t#{@cc_sid}\t#{@cc_skip}\t#{session_created}"
    live = {}
    for line in tmux("list-sessions", "-F", fmt, check=False).splitlines():
        sname, path, cmd, sid, skip, created = (line.split("\t") + [""] * 6)[:6]
        if sname.startswith(PREFIX):
            live[sname[len(PREFIX):]] = {"path": path, "sid": sid or None, "skip": skip == "1",
                                         "running": cmd == "claude", "created": int(created or 0)}
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
    tmux("new-session", "-d", "-s", f"{PREFIX}{name}", "-c", path, "-x", "200", "-y", "50")
    sid, skip = info.get("sid"), bool(info.get("skip"))
    if sid:
        tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_sid", sid)
    tmux("set-option", "-t", f"={PREFIX}{name}:", "@cc_skip", "1" if skip else "0")
    if info.get("running"):
        time.sleep(0.5)
        if transcript_exists(sid):
            cmd = claude_cmd(sid, True, skip)
        else:
            flag = " --dangerously-skip-permissions" if skip else ""
            cmd = f"claude --continue{flag} || claude{flag}"
        type_line(name, cmd)
    print(f"restored {name} ({'claude resumed' if info.get('running') else 'shell only'})", flush=True)


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
