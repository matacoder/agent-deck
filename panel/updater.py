#!/usr/bin/env python3
"""Unprivileged, detached updater for an installed panel; never runs release scripts."""
import argparse
import fcntl
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")
TAG_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
REQUIRED = {"panel.py", "index.html", "login.html", "VERSION", "updater.py", "session_hook.py"}
PACKAGES = {"integrations/" + name for name in ("__init__.py", "questions.py", "store.py", "telegram.py", "lmstudio.py", "relay.py", "pi.py", "preferences.py", "names.py", "decks.py", "updates.py")}
LOCALES = {"locales/__init__.py", "locales/en.json", "locales/ru.json"}
REQUIRED |= PACKAGES | LOCALES
ALLOWED = REQUIRED | {"icon-180.png", "icon-192.png", "icon-512.png", "manifest.webmanifest", "make_icons.py"}
RUNNING = {"checking", "downloading", "installing", "restarting"}


def available(target, repo):
    target = Path(target)
    if not repo or not REPO_RE.fullmatch(repo):
        return False
    # A development checkout must be updated through git, never overwritten by a release.
    return (os.geteuid() != 0 and target.is_dir() and not target.is_symlink()
            and os.access(target, os.W_OK | os.X_OK)
            and all(not (p / ".git").exists() for p in [target, *target.parents]))


def write_state(path, phase, **fields):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="update-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"phase": phase, "at": time.time(), **fields}, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def lock(path):
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        os.close(fd)
        return None


def status(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {"phase": "idle"}
    if data.get("phase") in RUNNING:
        fd = lock(path)
        if fd is not None:
            os.close(fd)
            return {**data, "phase": "error", "message": "Обновление прервано. Можно повторить."}
    return data


def fetch(url, limit):
    request = urllib.request.Request(url, headers={"User-Agent": "Agent-Deck-Updater", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Релиз превышает допустимый размер")
    return data


def unpack(data, stage, version):
    found = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            parts = member.name.split("/")
            if len(parts) < 2 or parts[1] not in ("panel", "integrations", "locales"):
                continue
            if member.isdir() and len(parts) <= 3:
                continue
            name = '/'.join(parts[1:]) if parts[1] in ('integrations', 'locales') else '/'.join(parts[2:])
            package_module = parts[1] == 'integrations' and len(parts) == 3 and re.fullmatch(r'(?:[a-z][a-z0-9_]*|__init__)\.py', parts[2])
            locale_file = parts[1] == 'locales' and len(parts) == 3 and re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\.json', parts[2])
            if len(parts) != 3 or (name not in ALLOWED and not package_module and not locale_file) or not member.isfile():
                raise ValueError("Недопустимый файл в релизе")
            if locale_file and member.size > 1024 * 1024:
                raise ValueError('Locale catalog exceeds the size limit')
            total += member.size
            if name in found or member.size > 16 * 1024 * 1024 or total > 64 * 1024 * 1024:
                raise ValueError("Недопустимый размер или повтор файла релиза")
            with archive.extractfile(member) as stream:
                (stage / name).parent.mkdir(parents=True, exist_ok=True)
                (stage / name).write_bytes(stream.read())
            (stage / name).chmod(0o644)
            found.add(name)
    if not REQUIRED <= found or (stage / "VERSION").read_text().strip() != version:
        raise ValueError("Релиз неполный или версия не совпадает")
    # Validate catalog structure and placeholders before replacing a running installation.
    for name in found:
        if name.startswith('locales/') and name.endswith('.json'):
            data = json.loads((stage / name).read_text())
            if (not isinstance(data, dict) or not isinstance(data.get('name'), str)
                    or not 1 <= len(data['name']) <= 80 or not isinstance(data.get('messages'), dict)
                    or len(data['messages']) > 3000):
                raise ValueError('Invalid locale catalog')
            for key, value in data['messages'].items():
                if (not isinstance(key, str) or not isinstance(value, str) or len(key) > 10000 or len(value) > 10000
                        or sorted(re.findall(r'\{\d+\}', key)) != sorted(re.findall(r'\{\d+\}', value))):
                    raise ValueError('Invalid locale translation')
    # Reject broken backend syntax before stopping the running service.
    for name in found:
        if not name.endswith('.py'):
            continue
        compile((stage / name).read_text(), name, "exec")
    return found


def service(action):
    if sys.platform == "darwin":
        domain = f"gui/{os.getuid()}"
        label = "com.agent-deck.panel"
        plist = str(Path.home() / "Library/LaunchAgents" / (label + ".plist"))
        command = (["launchctl", "bootout", domain + "/" + label] if action == "stop"
                   else ["launchctl", "bootstrap", domain, plist])
        result = subprocess.run(command, timeout=30, capture_output=True)
        if result.returncode:
            # Stopping a service already absent is harmless during rollback.
            if action == "stop" and subprocess.run(["launchctl", "print", domain + "/" + label],
                                                   capture_output=True, timeout=10).returncode:
                return
            result.check_returncode()
        return
    subprocess.run(["systemctl", "--user", action, "cc-panel.service"],
                   check=True, timeout=30, capture_output=True)


def healthy(url):
    deadline = time.monotonic() + 20
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/login", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError as error:
            last_error = str(error)
        time.sleep(0.5)
    raise RuntimeError("Панель не ответила после перезапуска: " + last_error)


def local_requests_active(directory=None, clock=time.time):
    directory = Path(directory) if directory else Path.home()/'.config/cc-panel/integrations/live-requests'
    for path in directory.glob('*.json'):
        try:
            data = json.loads(path.read_text())
            if clock()-data.get('updated_at', 0)<660:return True
        except (OSError,ValueError,TypeError):return True
    return False


def wait_for_local_requests(directory=None, timeout=660):
    deadline=time.monotonic()+timeout
    while local_requests_active(directory):
        if time.monotonic()>=deadline:raise ValueError('Local model request is still active; retry the update after it finishes')
        time.sleep(1)


def install(stage, target, names, state, version, url):
    wait_for_local_requests(Path(state).parent/'integrations/live-requests')
    backup = stage / "backup"
    backup.mkdir()
    existing = set()
    for name in names:
        destination = target / name
        if destination.is_symlink() or any(p.is_symlink() for p in destination.parents if p != target and target in p.parents):
            raise ValueError("Файл панели оказался символической ссылкой")
        if destination.exists():
            (backup / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup / name)
            existing.add(name)
    write_state(state, "installing", version=version, message="Устанавливаю файлы панели…")
    # VERSION goes last: a crash mid-swap must not leave mixed files reported as up to date.
    ordered = sorted(names - {"VERSION"}) + (["VERSION"] if "VERSION" in names else [])
    stopped = False
    try:
        service("stop")
        stopped = True
        for name in ordered:
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / name, target / name)
        write_state(state, "restarting", version=version, message="Перезапускаю панель…")
        service("start")
        healthy(url)
    except Exception:
        if stopped:
            try:
                rollback(backup, target, ordered, existing)
            except Exception:
                pass  # Report the update failure itself; it explains why the rollback ran.
        raise


def rollback(backup, target, ordered, existing):
    try:
        # Stop a failed new version best-effort: a stop error must not prevent restoring files.
        try:
            service("stop")
        except Exception:
            pass
        # Old VERSION first, so an interrupted rollback is retried by the next update.
        for name in reversed(ordered):
            if name in existing:
                os.replace(backup / name, target / name)
            else:
                (target / name).unlink(missing_ok=True)
    finally:
        service("start")


def remove_stale_stages(target):
    # The flock makes this job the only writer, so any staging directory left here is from a crash.
    for entry in target.iterdir():
        if entry.name.startswith(".update-") and entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)


def run(repo, target, state, url):
    try:
        if not available(target, repo):
            raise ValueError("Обновление доступно только для установленной панели без root")
        target = Path(target)
        remove_stale_stages(target)
        write_state(state, "checking", message="Проверяю последний релиз…")
        release = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases/latest", 1024 * 1024))
        tag = release.get("tag_name", "")
        match = TAG_RE.fullmatch(tag)
        if not match or release.get("draft") or release.get("prerelease"):
            raise ValueError("Нет подходящего стабильного релиза")
        version = tag.lstrip("v")
        current = TAG_RE.fullmatch((target / "VERSION").read_text().strip())
        new_version, old_version = tuple(map(int, match.groups())), tuple(map(int, current.groups())) if current else ()
        needs_repair = bool(current and new_version == old_version and any(not (target / name).is_file() for name in REQUIRED))
        if not current or (new_version <= old_version and not needs_repair):
            write_state(state, "done", version=(target / "VERSION").read_text().strip(), message="Уже установлена последняя версия")
            return
        write_state(state, "downloading", version=version, message=f"Скачиваю v{version}…")
        data = fetch(f"https://api.github.com/repos/{repo}/tarball/{tag}", 32 * 1024 * 1024)
        with tempfile.TemporaryDirectory(prefix=".update-", dir=target) as directory:
            stage = Path(directory)
            names = unpack(data, stage, version)
            install(stage, target, names, state, version, url)
        write_state(state, "done", version=version, message=f"Панель обновлена до v{version}")
    except Exception as error:
        write_state(state, "error", message=str(error)[:300] or "Не удалось обновить панель")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("repo", "target", "state", "url"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--lock-fd", type=int, required=True)
    args = parser.parse_args()
    # The inherited flock descriptor keeps the job exclusive across panel restarts.
    try:
        run(args.repo, args.target, args.state, args.url)
    finally:
        os.close(args.lock_fd)
