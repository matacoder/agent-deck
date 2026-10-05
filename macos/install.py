#!/usr/bin/env python3
"""Install user-owned macOS runtime and LaunchAgents; preserve sessions and settings."""
import argparse
import importlib.util
import ipaddress
import json
import os
import re
from pathlib import Path
import plistlib
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from integrations.preferences import ProjectDirectory

LABELS = ('com.agent-deck.ttyd', 'com.agent-deck.panel')


def atomic_write(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f'Refusing symlink: {path}')
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def tailscale_ipv4():
    """Use only the connected machine's own tailnet address; never expose its LAN."""
    binary = shutil.which('tailscale')
    app = Path('/Applications/Tailscale.app/Contents/MacOS/Tailscale')
    binary = binary or (str(app) if app.is_file() else None)
    if not binary:
        return None
    try:
        result = subprocess.run([binary, 'status', '--json'], input='',
                                capture_output=True, text=True, timeout=5, check=True)
        status = json.loads(result.stdout)
        if status.get('BackendState') != 'Running':
            return None
        own = status.get('Self') or {}
        if own.get('Online') is False:
            return None
        for value in own.get('TailscaleIPs', []):
            address = ipaddress.ip_address(value)
            if address.version == 4 and address in ipaddress.ip_network('100.64.0.0/10'):
                return str(address)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        return None
    return None


def configuration(home, projects_dir=None):
    config = home / '.config/cc-panel'
    config.mkdir(parents=True, exist_ok=True, mode=0o700)
    if config.is_symlink():
        raise ValueError('Configuration directory must not be a symlink')
    config.chmod(0o700)
    path = config / 'macos.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    automatic = data.get('BIND_HOST_AUTO', '1' if data.get('BIND_HOST', '127.0.0.1') == '127.0.0.1' else '0') == '1'
    if 'BIND_HOST' in os.environ:
        automatic = False
    if automatic:
        data['BIND_HOST'] = tailscale_ipv4() or '127.0.0.1'
    # Remember explicit choices, including an intentionally local-only install.
    data['BIND_HOST_AUTO'] = '1' if automatic else '0'
    defaults = {'BIND_HOST': '127.0.0.1', 'BIND_PORT': '8790',
                'PANEL_LANGUAGE': 'en', 'PANEL_USER': home.name, 'PANEL_PASSWORD': secrets.token_urlsafe(18),
                'PROJECTS_DIR': str(home / 'dev')}
    for key, value in defaults.items():
        data.setdefault(key, value)
    # Explicit installation options override remembered values.
    for key in defaults:
        if key in os.environ:
            data[key] = os.environ[key]
    if projects_dir is not None:
        data['PROJECTS_DIR'] = projects_dir
    preference = ProjectDirectory(home, data['PROJECTS_DIR'])
    if projects_dir is None and 'PROJECTS_DIR' not in os.environ:
        data['PROJECTS_DIR'] = preference.get()
    raw_projects = data['PROJECTS_DIR']
    if not isinstance(raw_projects, str) or not raw_projects.strip():
        raise ValueError('PROJECTS_DIR must be a non-empty directory path')
    projects = home if raw_projects == '~' else home / raw_projects[2:] if raw_projects.startswith('~/') else Path(raw_projects).expanduser()
    projects = projects.resolve()
    if projects.exists() and not projects.is_dir():
        raise ValueError(f'PROJECTS_DIR is not a directory: {projects}')
    data['PROJECTS_DIR'] = preference.validate(str(projects))
    if not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*', data['PANEL_LANGUAGE']) or not (SOURCE / 'locales' / (data['PANEL_LANGUAGE'] + '.json')).is_file():
        raise ValueError('Unsupported PANEL_LANGUAGE')
    if data['BIND_HOST'] in ('0.0.0.0', '::') or ':' in data['BIND_HOST']:
        raise ValueError('Use localhost or a specific IPv4 address for BIND_HOST')
    socket.inet_aton(data['BIND_HOST'])
    if not 1 <= int(data['BIND_PORT']) <= 65535 or not data['PANEL_PASSWORD'] or not data['PANEL_USER']:
        raise ValueError('Invalid port, user or password')
    atomic_write(path, (json.dumps(data, indent=2) + '\n').encode())
    preference.save(data['PROJECTS_DIR'])
    return config, data


def launch_agent(label, arguments, environment, logs):
    return {'Label': label, 'ProgramArguments': list(map(str, arguments)),
            'EnvironmentVariables': environment, 'RunAtLoad': True, 'KeepAlive': True,
            'ThrottleInterval': 3, 'AbandonProcessGroup': True,
            'WorkingDirectory': environment['HOME'],
            'StandardOutPath': str(logs / (label + '.log')),
            'StandardErrorPath': str(logs / (label + '.log'))}


def run(*arguments, check=True):
    return subprocess.run(list(map(str, arguments)), check=check, capture_output=True, text=True, timeout=30)


def install(home, start=True, open_browser=True, projects_dir=None):
    runtime = home / '.local/share/agent-deck'
    target = runtime / 'panel'
    if runtime.is_symlink() or target.is_symlink():
        raise ValueError('Runtime must not be a symlink')
    target.mkdir(parents=True, exist_ok=True)
    config, settings = configuration(home, projects_dir)
    logs = home / 'Library/Logs/Agent Deck'
    logs.mkdir(parents=True, exist_ok=True)
    logs.chmod(0o700)
    agents = home / 'Library/LaunchAgents'
    agents.mkdir(parents=True, exist_ok=True)
    ttyd, tmux = shutil.which('ttyd'), shutil.which('tmux')
    if not ttyd or not tmux:
        raise ValueError('Install ttyd and tmux with Homebrew first')
    socket_path = str(config / 'ttyd.sock')
    if len(socket_path.encode()) >= 104:
        raise ValueError('Home path is too long for the ttyd Unix socket')
    env = {**settings, 'HOME': str(home), 'LANG': 'en_US.UTF-8',
           'PATH': ':'.join([str(home / '.local/bin'), str(Path(sys.executable).parent),
                             '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin']),
           'TTYD_SOCK': socket_path, 'TMUX_SOCKET_NAME': 'agent-deck'}
    python = str(runtime / 'venv/bin/python3')
    definitions = {
        LABELS[0]: launch_agent(LABELS[0], [ttyd, '-i', socket_path, '-b', '/t', '-W', '-a', '-O',
                            '-t', 'fontSize=13', '-t', 'disableLeaveAlert=true', '-t', 'titleFixed=AgentDeck',
                            tmux, '-L', 'agent-deck', 'attach', '-t'],
                            {key: env[key] for key in ('HOME', 'PATH', 'LANG', 'TMUX_SOCKET_NAME')}, logs),
        LABELS[1]: launch_agent(LABELS[1], [python, target / 'panel.py'], env, logs),
    }
    # Compile before stopping anything, and preserve the previous runtime for recovery.
    for source in (SOURCE / 'panel').glob('*.py'):
        compile(source.read_text(), str(source), 'exec')
    for source in (SOURCE / 'integrations').glob('*.py'):
        compile(source.read_text(), str(source), 'exec')
    if (target / 'VERSION').exists():
        shutil.copytree(target, runtime / 'backup', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
    domain = f'gui/{os.getuid()}'
    if start:
        for label in reversed(LABELS):
            run('launchctl', 'bootout', domain + '/' + label, check=False)
    for source in (SOURCE / 'panel').iterdir():
        if source.is_file():
            atomic_write(target / source.name, source.read_bytes(), 0o644)
    for source in (SOURCE / 'integrations').glob('*.py'):
        atomic_write(target / 'integrations' / source.name, source.read_bytes(), 0o644)
    for source in (SOURCE / 'locales').iterdir():
        if source.suffix in ('.py', '.json'):
            atomic_write(target / 'locales' / source.name, source.read_bytes(), 0o644)
    if start:
        # Pinned cryptography wheels for backups and notifications; the panel retries itself when offline.
        try:
            fetched = run(python, '-c', 'import sys; sys.path.insert(0, sys.argv[1]); from integrations import dependencies; '
                          'sys.exit(0 if dependencies.ensure(background=False) else 1)', target, check=False).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            fetched = False
        if not fetched:
            print('Encryption components could not be downloaded now; the panel will retry automatically.', flush=True)
    atomic_write(config / 'tmux.conf', (SOURCE / 'config/tmux.conf').read_bytes(), 0o644)
    wrapper = home / '.claude/cc-session-hook.py'
    atomic_write(wrapper, (SOURCE / 'claude/cc-session-hook.py').read_bytes(), 0o755)
    spec = importlib.util.spec_from_file_location('register_hooks', SOURCE / 'claude/register-hooks.py')
    registration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(registration)
    registration.register(home, shlex.join([python, str(wrapper)]))
    for label, definition in definitions.items():
        atomic_write(agents / (label + '.plist'), plistlib.dumps(definition))
    if start:
        Path(socket_path).unlink(missing_ok=True)
        for label in LABELS:
            run('launchctl', 'enable', domain + '/' + label)
            run('launchctl', 'bootstrap', domain, agents / (label + '.plist'))
        url = f"http://{settings['BIND_HOST']}:{settings['BIND_PORT']}"
        for _ in range(40):
            try:
                with urllib.request.urlopen(url + '/login', timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            time.sleep(.5)
        else:
            raise RuntimeError(f'Panel did not start. Logs: {logs}; previous files: {runtime / "backup"}')
        print(f'Agent Deck is ready: {url}\nLogin: {settings["PANEL_USER"]}\nPassword: {settings["PANEL_PASSWORD"]}')
        print(f'Projects: {settings["PROJECTS_DIR"]}')
        print('Log into Claude/Codex from the sidebar. Your sessions use a separate tmux server.')
        if open_browser:
            run('open', url, check=False)
    return definitions


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--projects-dir', help='Project directory (default: ~/dev; saved on reinstall)')
    parser.add_argument('--no-open', action='store_true', help='Do not open a browser after installation')
    args = parser.parse_args()
    if sys.platform != 'darwin' or os.geteuid() == 0:
        parser.error('Run as your logged-in macOS user, without sudo')
    install(Path.home(), open_browser=not args.no_open, projects_dir=args.projects_dir)
