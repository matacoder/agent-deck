#!/usr/bin/env bash
# Install / upgrade the Claude Sessions panel for one unprivileged user.
#
# Works on a clean Ubuntu 22.04 / 24.04 server: installs Tailscale, tmux, ttyd, gh, Claude Code,
# rootless Docker for the user, the panel and its systemd user services.
#
#   sudo ./install.sh                          # defaults: user "dev", bind to this host's Tailscale IP
#   sudo TS_AUTHKEY=tskey-... ./install.sh     # join the tailnet without the interactive login link
#   sudo DEV_USER=alice MEM_MAX=8G CPU_QUOTA=200% ./install.sh
#   sudo WITH_DOCKER=0 ./install.sh            # skip rootless Docker
#
# Re-running is safe: code and unit files are updated, the panel and ttyd are restarted,
# the tmux server (and every running Claude session) is left alone.
set -euo pipefail

DEV_USER=${DEV_USER:-dev}
DEV_UID=${DEV_UID:-2600}
PANEL_PORT=${PANEL_PORT:-8790}
BIND_HOST=${BIND_HOST:-}
MEM_MAX=${MEM_MAX:-}          # e.g. 8G  -> MemoryMax for everything the user runs
CPU_QUOTA=${CPU_QUOTA:-}      # e.g. 200% -> two cores
WITH_DOCKER=${WITH_DOCKER:-1}
TS_AUTHKEY=${TS_AUTHKEY:-}
TTYD_VERSION=1.7.7
PREFIX=/opt/cc-panel
SRC=$(cd "$(dirname "$0")" && pwd)

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root (sudo ./install.sh)"
[ -f "$SRC/panel/panel.py" ] || die "run from a checkout of the repository (panel/ not found next to install.sh)"
export DEBIAN_FRONTEND=noninteractive

say "packages"
if ! grep -rqsE '^(deb .*universe|Components:.*universe)' /etc/apt/sources.list /etc/apt/sources.list.d/; then
    apt-get install -y -q software-properties-common >/dev/null && add-apt-repository -y universe >/dev/null
fi
apt-get update -q >/dev/null
apt-get install -y -q tmux ttyd git gh python3 curl ca-certificates >/dev/null
systemctl disable --now ttyd 2>/dev/null || true   # the distro unit would listen on 0.0.0.0:7681

TTYD_BIN=/usr/bin/ttyd
if ! ttyd --help 2>&1 | grep -q -- '--writable'; then
    # Ubuntu 22.04 ships ttyd 1.6 (no -W); use the official static build instead
    say "ttyd $TTYD_VERSION (static build)"
    case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) die "unsupported arch $(uname -m)" ;; esac
    curl -fsSL -o /usr/local/bin/ttyd "https://github.com/tsl0922/ttyd/releases/download/$TTYD_VERSION/ttyd.$arch"
    chmod 755 /usr/local/bin/ttyd
    TTYD_BIN=/usr/local/bin/ttyd
fi

if [ -z "$BIND_HOST" ]; then
    if ! command -v tailscale >/dev/null; then
        say "Tailscale"
        curl -fsSL https://tailscale.com/install.sh | sh >/dev/null
    fi
    if ! tailscale ip -4 >/dev/null 2>&1; then
        say "joining the tailnet${TS_AUTHKEY:+ (auth key)}: open the link below if asked"
        if [ -n "$TS_AUTHKEY" ]; then tailscale up --authkey "$TS_AUTHKEY"; else tailscale up; fi
    fi
    BIND_HOST=$(tailscale ip -4 | head -1)
fi
[ -n "$BIND_HOST" ] || die "could not determine the Tailscale IP; set BIND_HOST explicitly"
[ "$BIND_HOST" != "0.0.0.0" ] || die "refusing to expose a web terminal on all interfaces"

say "user $DEV_USER"
if ! id "$DEV_USER" >/dev/null 2>&1; then
    getent group "$DEV_UID" >/dev/null || groupadd -g "$DEV_UID" "$DEV_USER"
    useradd -u "$DEV_UID" -g "$DEV_UID" -m -s /bin/bash "$DEV_USER"
fi
UID_=$(id -u "$DEV_USER")
H=$(getent passwd "$DEV_USER" | cut -d: -f6)
loginctl enable-linger "$DEV_USER"
for _ in $(seq 20); do [ -S "/run/user/$UID_/bus" ] && break; sleep 0.5; done
as_user() { sudo -u "$DEV_USER" -H env XDG_RUNTIME_DIR="/run/user/$UID_" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID_/bus" "$@"; }

say "panel code -> $PREFIX"
install -d -m 755 "$PREFIX"
install -m 644 "$SRC"/panel/* "$PREFIX"/

say "config"
install -d -o "$DEV_USER" -g "$DEV_USER" -m 700 "$H/.config/cc-panel"
ENV="$H/.config/cc-panel/env"
NEW_PASS=""
if [ ! -f "$ENV" ]; then
    NEW_PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
    cat > "$ENV" <<EOF
BIND_HOST=$BIND_HOST
BIND_PORT=$PANEL_PORT
PANEL_USER=$DEV_USER
PANEL_PASSWORD=$NEW_PASS
TTYD_SOCK=/run/user/$UID_/cc-ttyd.sock
EOF
    chown "$DEV_USER:$DEV_USER" "$ENV"; chmod 600 "$ENV"
fi
if [ -f "$H/.tmux.conf" ] && ! cmp -s "$H/.tmux.conf" "$SRC/config/tmux.conf"; then
    cp "$H/.tmux.conf" "$H/.tmux.conf.bak.$(date +%s)"
fi
install -o "$DEV_USER" -g "$DEV_USER" -m 644 "$SRC/config/tmux.conf" "$H/.tmux.conf"
install -d -o "$DEV_USER" -g "$DEV_USER" "$H/projects" "$H/.config" "$H/.config/systemd" "$H/.config/systemd/user" "$H/.claude"
install -o "$DEV_USER" -g "$DEV_USER" -m 644 "$SRC"/systemd/*.service "$H/.config/systemd/user/"
sed -i "s|/usr/bin/ttyd|$TTYD_BIN|" "$H/.config/systemd/user/cc-ttyd.service"

say "Claude SessionStart hook"
install -o "$DEV_USER" -g "$DEV_USER" -m 755 "$SRC/claude/cc-session-hook.py" "$H/.claude/cc-session-hook.py"
as_user python3 - <<'EOF'
import json, os
p = os.path.expanduser("~/.claude/settings.json")
s = json.load(open(p)) if os.path.exists(p) else {}
hook = {"type": "command", "command": "python3 ~/.claude/cc-session-hook.py"}
groups = s.setdefault("hooks", {}).setdefault("SessionStart", [])
if not any(h.get("command") == hook["command"] for g in groups for h in g.get("hooks", [])):
    groups.append({"hooks": [hook]})
json.dump(s, open(p, "w"), indent=2)
EOF

if ! as_user bash -lc 'command -v claude' >/dev/null 2>&1; then
    say "Claude Code"
    as_user bash -c 'curl -fsSL https://claude.ai/install.sh | bash'
fi

if [ "$WITH_DOCKER" = 1 ]; then
    say "rootless Docker"
    apt-get install -y -q uidmap dbus-user-session slirp4netns >/dev/null
    if ! command -v dockerd-rootless-setuptool.sh >/dev/null; then
        if command -v dockerd >/dev/null; then
            apt-get install -y -q docker-ce-rootless-extras >/dev/null \
                || die "Docker is installed but docker-ce-rootless-extras is unavailable; install it or use WITH_DOCKER=0"
        else
            # fresh box: install Docker CE, then switch the root daemon off (only the rootless one is used)
            curl -fsSL https://get.docker.com | sh >/dev/null
            systemctl disable --now docker.service docker.socket
        fi
    fi
    if [ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null)" = 1 ]; then
        # Ubuntu 24.04+: allow user namespaces for rootlesskit only (as documented by Docker)
        cat > /etc/apparmor.d/usr.bin.rootlesskit <<'EOF'
abi <abi/4.0>,
include <tunables/global>

/usr/bin/rootlesskit flags=(unconfined) {
  userns,

  include if exists <local/usr.bin.rootlesskit>
}
EOF
        apparmor_parser -r /etc/apparmor.d/usr.bin.rootlesskit
    fi
    install -d -o "$DEV_USER" -g "$DEV_USER" "$H/.config/docker"
    [ -f "$H/.config/docker/daemon.json" ] || echo "{\"ip\": \"$BIND_HOST\"}" | as_user tee "$H/.config/docker/daemon.json" >/dev/null
    as_user systemctl --user is-active -q docker || as_user dockerd-rootless-setuptool.sh install
    grep -q 'DOCKER_HOST' "$H/.bashrc" || cat >> "$H/.bashrc" <<'EOF'

# rootless docker
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
EOF
fi

if [ -n "$MEM_MAX$CPU_QUOTA" ]; then
    say "resource limits for user-$UID_.slice"
    props=()
    [ -n "$MEM_MAX" ] && props+=("MemoryMax=$MEM_MAX")
    [ -n "$CPU_QUOTA" ] && props+=("CPUQuota=$CPU_QUOTA")
    systemctl set-property "user-$UID_.slice" "${props[@]}"
fi

say "services"
as_user systemctl --user daemon-reload
as_user systemctl --user enable -q cc-tmux.service cc-ttyd.service cc-panel.service
as_user systemctl --user start cc-tmux.service          # never restarted: it owns the sessions
as_user systemctl --user restart cc-ttyd.service cc-panel.service
sleep 1
as_user systemctl --user is-active -q cc-tmux cc-ttyd cc-panel || die "a service failed: journalctl --user -M $DEV_USER@ -n 50"

echo
say "done: http://$BIND_HOST:$PANEL_PORT  (user: $DEV_USER)"
if [ -n "$NEW_PASS" ]; then
    echo "    password: $NEW_PASS"
else
    echo "    password: grep PANEL_PASSWORD $ENV"
fi
echo "    first run: open a session and do /login inside Claude, then 'Connect GitHub' in the sidebar"
