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
import tarfile
import tempfile
import time
import urllib.request

REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")
TAG_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
REQUIRED = {"panel.py", "index.html", "login.html", "VERSION", "updater.py", "session_hook.py"}
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
            if len(parts) < 2 or parts[1] != "panel":
                continue
            if member.isdir() and len(parts) <= 3:
                continue
            if len(parts) != 3 or parts[2] not in ALLOWED or not member.isfile():
                raise ValueError("Недопустимый файл в релизе")
            name = parts[2]
            total += member.size
            if name in found or member.size > 16 * 1024 * 1024 or total > 64 * 1024 * 1024:
                raise ValueError("Недопустимый размер или повтор файла релиза")
            with archive.extractfile(member) as stream:
                (stage / name).write_bytes(stream.read())
            (stage / name).chmod(0o644)
            found.add(name)
    if not REQUIRED <= found or (stage / "VERSION").read_text().strip() != version:
        raise ValueError("Релиз неполный или версия не совпадает")
    # Reject broken backend syntax before stopping the running service.
    for name in ("panel.py", "updater.py", "session_hook.py"):
        compile((stage / name).read_text(), name, "exec")
    return found


def service(action):
    subprocess.run(["systemctl", "--user", action, "cc-panel.service"],
                   check=True, timeout=30, capture_output=True)


def healthy(url):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/login", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError("Панель не ответила после перезапуска")


def install(stage, target, names, state, version, url):
    backup = stage / "backup"
    backup.mkdir()
    existing = set()
    for name in names:
        destination = target / name
        if destination.is_symlink():
            raise ValueError("Файл панели оказался символической ссылкой")
        if destination.exists():
            shutil.copy2(destination, backup / name)
            existing.add(name)
    write_state(state, "installing", version=version, message="Устанавливаю файлы панели…")
    stopped = False
    try:
        service("stop")
        stopped = True
        for name in names:
            os.replace(stage / name, target / name)
        write_state(state, "restarting", version=version, message="Перезапускаю панель…")
        service("start")
        healthy(url)
    except Exception:
        if stopped:
            # Stop a failed new version before restoring all files from the previous version.
            service("stop")
            for name in names:
                if name in existing:
                    os.replace(backup / name, target / name)
                else:
                    (target / name).unlink(missing_ok=True)
            service("start")
        raise


def run(repo, target, state, url):
    try:
        if not available(target, repo):
            raise ValueError("Обновление доступно только для установленной панели без root")
        target = Path(target)
        write_state(state, "checking", message="Проверяю последний релиз…")
        release = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases/latest", 1024 * 1024))
        tag = release.get("tag_name", "")
        match = TAG_RE.fullmatch(tag)
        if not match or release.get("draft") or release.get("prerelease"):
            raise ValueError("Нет подходящего стабильного релиза")
        version = tag.lstrip("v")
        current = TAG_RE.fullmatch((target / "VERSION").read_text().strip())
        if not current or tuple(map(int, match.groups())) <= tuple(map(int, current.groups())):
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
