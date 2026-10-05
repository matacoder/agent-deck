#!/usr/bin/env bash
# Install / upgrade Agent Deck (web panel for Claude Code / Codex / terminal sessions in tmux)
# for one unprivileged user.
#
# Works on a clean Ubuntu 22.04 / 24.04 server: installs Tailscale, tmux, ttyd, gh, Claude Code, Codex CLI,
# rootless Docker for the user, the panel and its systemd user services.
#
#   sudo ./install.sh                          # defaults: user "dev", bind to this host's Tailscale IP
#   sudo TS_AUTHKEY=tskey-... ./install.sh     # join the tailnet without the interactive login link
#   sudo DEV_USER=alice MEM_MAX=8G CPU_QUOTA=200% ./install.sh
#   sudo WITH_DOCKER=0 WITH_CODEX=0 ./install.sh   # skip rootless Docker / Codex CLI
#   sudo PUBLIC_DOMAIN=cli.example.com ./install.sh  # also publish at https://<domain> (Let's Encrypt):
#                                                     # via Dokploy's Traefik if present, else via Caddy
#
# Re-running is safe: code and unit files are updated, the panel and ttyd are restarted,
# the tmux server (and every running Claude session) is left alone.
set -euo pipefail
# Keep this bootstrap check self-contained: never source code from an unchecked checkout.
require_root_checkout() {
    python3 - "$1" "${2:-tree}" <<'ROOT_CHECK'
from pathlib import Path
import stat, sys
root = Path(sys.argv[1]).absolute()
entries = [root, *root.parents]
if sys.argv[2] == "tree":
    entries.extend(root.rglob("*"))
for path in entries:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise SystemExit(f"Refusing untrusted root checkout: {path}. Use the bootstrap installer in a root-owned /opt/agent-deck.")
ROOT_CHECK
}

[ "$(id -u)" = 0 ] || { echo "run as root through the bootstrap installer" >&2; exit 1; }
require_root_checkout "$(cd "$(dirname "$0")" && pwd)"

# Install options are remembered: a later run (e.g. via update.sh) reuses them unless overridden in env.
CONF=/etc/agent-deck/install.conf
CONF_KEYS="DEV_USER DEV_UID PANEL_PORT BIND_HOST MEM_MAX CPU_QUOTA WITH_DOCKER WITH_CODEX PUBLIC_DOMAIN PUBLIC_PROXY TRAEFIK_DYNAMIC"
if [ -e "$(dirname "$CONF")" ]; then
    require_root_checkout "$(dirname "$CONF")"
fi
if [ -f "$CONF" ]; then
    while IFS='=' read -r k v; do
        case " $CONF_KEYS " in *" $k "*) [ -n "${!k+x}" ] || export "$k=$v" ;; esac
    done < "$CONF"
fi

DEV_USER=${DEV_USER:-dev}
DEV_UID=${DEV_UID:-2600}
PANEL_PORT=${PANEL_PORT:-8790}
BIND_HOST=${BIND_HOST:-}
MEM_MAX=${MEM_MAX:-}          # e.g. 8G  -> MemoryMax for everything the user runs
CPU_QUOTA=${CPU_QUOTA:-}      # e.g. 200% -> two cores
WITH_DOCKER=${WITH_DOCKER:-1}
WITH_CODEX=${WITH_CODEX:-1}
TS_AUTHKEY=${TS_AUTHKEY:-}
PUBLIC_DOMAIN=${PUBLIC_DOMAIN:-}
PUBLIC_PROXY=${PUBLIC_PROXY:-auto}   # auto | traefik | caddy
TRAEFIK_DYNAMIC=${TRAEFIK_DYNAMIC:-/etc/dokploy/traefik/dynamic}
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
apt-get install -y -q sudo tmux ttyd git gh python3 curl ca-certificates >/dev/null
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
# owned by the panel user: the panel runs as that user anyway, and ./deploy.sh can update it without root
[ ! -L "$PREFIX" ] || die "panel runtime must not be a symbolic link"
install -d -m 755 "$PREFIX"
chown -h "$DEV_USER:$DEV_USER" "$PREFIX"
as_user find "$SRC/panel" -maxdepth 1 -type f -exec install -m 644 {} "$PREFIX"/ \;
as_user install -d -m 755 "$PREFIX/integrations"
as_user find "$SRC/integrations" -maxdepth 1 -type f -name '*.py' -exec install -m 644 {} "$PREFIX/integrations"/ \;
as_user install -d -m 755 "$PREFIX/locales"
as_user find "$SRC/locales" -maxdepth 1 -type f \( -name '*.py' -o -name '*.json' \) -exec install -m 644 {} "$PREFIX/locales"/ \;

[ -f "$SRC/locales/${PANEL_LANGUAGE:-en}.json" ] && [[ "${PANEL_LANGUAGE:-en}" =~ ^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$ ]] || die "unsupported PANEL_LANGUAGE"
say "config"
as_user install -d -m 700 "$H/.config/cc-panel"
ENV="$H/.config/cc-panel/env"
NEW_PASS=""
[ ! -L "$ENV" ] || die "panel env must not be a symbolic link"
if [ ! -f "$ENV" ]; then
    NEW_PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
    as_user tee "$ENV" >/dev/null <<EOF
BIND_HOST=$BIND_HOST
BIND_PORT=$PANEL_PORT
PANEL_LANGUAGE=${PANEL_LANGUAGE:-en}
PANEL_USER=$DEV_USER
PANEL_PASSWORD=$NEW_PASS
TTYD_SOCK=/run/user/$UID_/cc-ttyd.sock
EOF
    as_user chmod 600 "$ENV"
fi
if [ -f "$H/.tmux.conf" ] && ! cmp -s "$H/.tmux.conf" "$SRC/config/tmux.conf"; then
    as_user cp "$H/.tmux.conf" "$H/.tmux.conf.bak.$(date +%s)"
fi
as_user install -m 644 "$SRC/config/tmux.conf" "$H/.tmux.conf"
# the panel shows this path in the "update available" hint
if as_user grep -q '^CHECKOUT=' "$ENV"; then as_user sed -i "s|^CHECKOUT=.*|CHECKOUT=$SRC|" "$ENV"; else echo "CHECKOUT=$SRC" | as_user tee -a "$ENV" >/dev/null; fi
as_user install -d "$H/dev" "$H/.config" "$H/.config/systemd" "$H/.config/systemd/user" "$H/.claude"
as_user install -m 644 "$SRC"/systemd/*.service "$H/.config/systemd/user/"
as_user sed -i "s|/usr/bin/ttyd|$TTYD_BIN|" "$H/.config/systemd/user/cc-ttyd.service"

say "Claude and Codex SessionStart hooks"
as_user install -m 755 "$SRC/claude/cc-session-hook.py" "$H/.claude/cc-session-hook.py"
as_user python3 "$SRC/claude/register-hooks.py"

if ! as_user bash -lc 'command -v claude' >/dev/null 2>&1; then
    say "Claude Code"
    as_user bash -c 'curl -fsSL https://claude.ai/install.sh | bash'
fi

if [ "$WITH_CODEX" = 1 ] && ! as_user bash -lc 'command -v codex' >/dev/null 2>&1; then
    say "Codex CLI"
    as_user bash -c 'curl -fsSL https://chatgpt.com/codex/install.sh | sh'
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
    as_user install -d "$H/.config/docker"
    [ -f "$H/.config/docker/daemon.json" ] || echo "{\"ip\": \"$BIND_HOST\"}" | as_user tee "$H/.config/docker/daemon.json" >/dev/null
    as_user systemctl --user is-active -q docker || as_user dockerd-rootless-setuptool.sh install
    as_user grep -q 'DOCKER_HOST' "$H/.bashrc" || as_user tee -a "$H/.bashrc" >/dev/null <<'EOF'

# rootless docker
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
EOF
fi

if [ -n "$MEM_MAX$CPU_QUOTA" ]; then
    say "resource limits for user-$UID_.slice"
    # Hard cap only: a MemoryHigh threshold makes the kernel throttle the whole slice (tmux, panel, agents
    # all stall at ~100% memory pressure) instead of OOM-killing the one oversized process.
    # CPUWeight=50: under contention the rest of the server (production services) gets the CPU first.
    props=(MemoryHigh=infinity CPUWeight=50)
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

if [ -n "$PUBLIC_DOMAIN" ]; then
    [ "$PUBLIC_PROXY" != auto ] || { [ -d "$TRAEFIK_DYNAMIC" ] && PUBLIC_PROXY=traefik || PUBLIC_PROXY=caddy; }
    say "public HTTPS: $PUBLIC_DOMAIN via $PUBLIC_PROXY"
    [ -n "$(getent ahostsv4 "$PUBLIC_DOMAIN")" ] \
        || echo "    warning: $PUBLIC_DOMAIN does not resolve yet; the certificate will fail until it does (see README)"
    render() { sed -e "s|__DOMAIN__|$PUBLIC_DOMAIN|g" -e "s|__BACKEND__|http://$BIND_HOST:$PANEL_PORT|g" \
                   -e "s|__UPSTREAM__|$BIND_HOST:$PANEL_PORT|g" "$1"; }
    case "$PUBLIC_PROXY" in
    traefik)
        [ -d "$TRAEFIK_DYNAMIC" ] || die "$TRAEFIK_DYNAMIC not found (Dokploy's Traefik); use PUBLIC_PROXY=caddy or set TRAEFIK_DYNAMIC"
        render "$SRC/deploy/traefik-dokploy.yml" > "$TRAEFIK_DYNAMIC/cc-panel.yml.new"
        cmp -s "$TRAEFIK_DYNAMIC/cc-panel.yml.new" "$TRAEFIK_DYNAMIC/cc-panel.yml" \
            || install -m 644 "$TRAEFIK_DYNAMIC/cc-panel.yml.new" "$TRAEFIK_DYNAMIC/cc-panel.yml"
        rm -f "$TRAEFIK_DYNAMIC/cc-panel.yml.new"
        ;;
    caddy)
        busy=$(ss -ltnpH '( sport = :80 or sport = :443 )' | grep -v '"caddy"' || true)
        [ -z "$busy" ] || die "ports 80/443 are taken by another process; free them or use PUBLIC_PROXY=traefik:
$busy"
        if ! apt-cache policy caddy | grep -q 'Candidate: [0-9]'; then
            # official Caddy apt repository (Ubuntu 22.04 has no caddy package)
            apt-get install -y -q debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null
            curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
                | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
            curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
            apt-get update -q >/dev/null
        fi
        apt-get install -y -q caddy >/dev/null
        install -d /etc/caddy/sites
        render "$SRC/deploy/Caddyfile.cc-panel" > /etc/caddy/sites/cc-panel.caddy
        if ! grep -q '^import sites/\*' /etc/caddy/Caddyfile 2>/dev/null; then
            if grep -q 'root \* /usr/share/caddy' /etc/caddy/Caddyfile 2>/dev/null; then
                cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.orig      # package default "welcome" site
                echo 'import sites/*.caddy' > /etc/caddy/Caddyfile
            else
                printf '\nimport sites/*.caddy\n' >> /etc/caddy/Caddyfile
            fi
        fi
        caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null || die "caddy config is invalid"
        systemctl enable -q --now caddy && systemctl reload caddy
        if ufw status 2>/dev/null | grep -q 'Status: active'; then ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; fi
        ;;
    *) die "PUBLIC_PROXY must be auto, traefik or caddy" ;;
    esac
fi
install -d -m 755 /etc/agent-deck
for k in $CONF_KEYS; do echo "$k=${!k}"; done > "$CONF"

echo
say "Agent Deck v$(cat "$SRC/panel/VERSION") — done: http://$BIND_HOST:$PANEL_PORT  (user: $DEV_USER)"
[ -z "$PUBLIC_DOMAIN" ] || echo "    public: https://$PUBLIC_DOMAIN"
if [ -n "$NEW_PASS" ]; then
    echo "    password: $NEW_PASS"
else
    echo "    password: grep PANEL_PASSWORD $ENV"
fi
echo "    first run: open a session and do /login inside Claude, then 'Connect GitHub' in the sidebar"
