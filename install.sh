#!/usr/bin/env bash
# Install / upgrade Agent Deck (web panel for Claude Code / Codex / terminal sessions in tmux)
# for one unprivileged user.
#
# Works on a clean Ubuntu 22.04 / 24.04, Debian 12+ or 64-bit Raspberry Pi OS 12+ server: installs Tailscale, tmux, ttyd, gh, Claude Code, Codex CLI,
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
    python3 -I - "$1" "${2:-tree}" <<'ROOT_CHECK'
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
BIND_HOST_EXPLICIT=${BIND_HOST:+1}
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
# The packages' architecture, not the kernel's: 32-bit Raspberry Pi OS boots a 64-bit kernel on a Pi 4/5.
case "$(dpkg --print-architecture 2>/dev/null || uname -m)" in
    amd64|arm64|x86_64|aarch64) ;;
    armhf|armel|armv7l|armv6l) die "32-bit ARM is not supported (Claude Code needs a 64-bit system); install the 64-bit Raspberry Pi OS" ;;
    *) die "unsupported architecture $(dpkg --print-architecture 2>/dev/null || uname -m); x86_64 and arm64 are supported" ;;
esac

# An in-panel self-update may have installed a newer release than this checkout; never silently downgrade.
NEW_VERSION=$(cat "$SRC/panel/VERSION")
if [ ! -L "$PREFIX" ] && [ -f "$PREFIX/VERSION" ] && [ ! -L "$PREFIX/VERSION" ]; then
    OLD_VERSION=$(head -c 64 "$PREFIX/VERSION" | tr -d '[:space:]')
    OLD_VERSION=${OLD_VERSION#v}
    if [[ "$OLD_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] && [ "$OLD_VERSION" != "$NEW_VERSION" ] \
        && [ "$(printf '%s\n%s\n' "$OLD_VERSION" "$NEW_VERSION" | sort -V | tail -1)" = "$OLD_VERSION" ] \
        && [ "${FORCE_DOWNGRADE:-0}" != 1 ]; then
        die "installed v$OLD_VERSION is newer than this checkout (v$NEW_VERSION); run update.sh to fetch the latest release, or set FORCE_DOWNGRADE=1 to downgrade"
    fi
fi

# Remember options before anything can fail, so a re-run does not fall back to defaults.
write_conf() {
    install -d -m 755 "$(dirname "$CONF")"
    local tmp
    tmp=$(mktemp "$CONF.XXXXXX")
    for k in $CONF_KEYS; do echo "$k=${!k}"; done > "$tmp"
    chmod 644 "$tmp"
    mv -f "$tmp" "$CONF"
}
write_conf

say "packages"
OS_ID=$( . /etc/os-release 2>/dev/null; echo "${ID:-}" )
# ttyd lives in Ubuntu's universe component (Debian and Raspberry Pi OS use the static build below).
if [ "$OS_ID" = ubuntu ] && ! grep -rqsE '^(deb .*universe|Components:.*universe)' /etc/apt/sources.list /etc/apt/sources.list.d/; then
    apt-get install -y -q software-properties-common >/dev/null && add-apt-repository -y universe >/dev/null
fi
apt-get update -q >/dev/null
apt-get install -y -q sudo tmux git python3 curl ca-certificates >/dev/null
# Debian has no ttyd package; without it (or with a ttyd too old for -W) the static build below is used.
apt-get install -y -q ttyd >/dev/null 2>&1 || true
python3 -I -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
    || die "Python 3.10+ is required (this system has $(python3 -V 2>&1)); use Ubuntu 22.04+, Debian 12+ or Raspberry Pi OS 12+"
if ! apt-get install -y -q gh >/dev/null 2>&1; then
    # Older Debian releases have no gh package: use GitHub's own signed repository.
    say "GitHub CLI repository"
    install -d -m 755 /etc/apt/keyrings
    curl -fsSL -o /etc/apt/keyrings/githubcli-archive-keyring.gpg https://cli.github.com/packages/githubcli-archive-keyring.gpg
    chmod 644 /etc/apt/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list
    apt-get update -q >/dev/null
    apt-get install -y -q gh >/dev/null
fi
systemctl disable --now ttyd 2>/dev/null || true   # the distro unit would listen on 0.0.0.0:7681

TTYD_BIN=/usr/bin/ttyd
if ! ttyd --help 2>&1 | grep -q -- '--writable'; then
    # Ubuntu 22.04 ships ttyd 1.6 (no -W); use the official static build instead
    say "ttyd $TTYD_VERSION (static build)"
    # Pinned like docker/Dockerfile: root installs this binary, so TLS alone is not enough.
    case "$(uname -m)" in
        x86_64) arch=x86_64 sum=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55 ;;
        aarch64|arm64) arch=aarch64 sum=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165 ;;
        *) die "unsupported arch $(uname -m)" ;;
    esac
    tmp_ttyd=$(mktemp)
    curl -fsSL -o "$tmp_ttyd" "https://github.com/tsl0922/ttyd/releases/download/$TTYD_VERSION/ttyd.$arch"
    echo "$sum  $tmp_ttyd" | sha256sum -c - >/dev/null || { rm -f "$tmp_ttyd"; die "ttyd download does not match its pinned SHA-256"; }
    install -m 755 "$tmp_ttyd" /usr/local/bin/ttyd; rm -f "$tmp_ttyd"
    TTYD_BIN=/usr/local/bin/ttyd
fi

# A Tailscale re-login can assign a new address. A remembered one that is no longer on this host would
# leave the panel unable to start (remote lockout), so it is resolved again; an explicit one is only checked.
bind_is_local() { python3 -I -c 'import socket,sys; socket.socket().bind((sys.argv[1], 0))' "$1" 2>/dev/null; }
if [ -n "$BIND_HOST" ] && ! bind_is_local "$BIND_HOST"; then
    [ -z "$BIND_HOST_EXPLICIT" ] || die "BIND_HOST=$BIND_HOST is not an address of this machine"
    # Only a Tailscale address is looked up again (as the panel does); any other one needs a decision.
    python3 -I -c 'import ipaddress,sys; sys.exit(ipaddress.ip_address(sys.argv[1]) not in ipaddress.ip_network("100.64.0.0/10"))' "$BIND_HOST" 2>/dev/null \
        || die "remembered BIND_HOST=$BIND_HOST is no longer an address of this machine; rerun with BIND_HOST=<address>, or BIND_HOST= to use Tailscale"
    say "remembered address $BIND_HOST is no longer on this machine; asking Tailscale again"
    BIND_HOST=
fi
if [ -z "$BIND_HOST" ]; then
    if ! command -v tailscale >/dev/null; then
        say "Tailscale"
        curl -fsSL https://tailscale.com/install.sh | sh >/dev/null
    fi
    if ! tailscale ip -4 >/dev/null 2>&1; then
        say "joining the tailnet${TS_AUTHKEY:+ (auth key)}: open the link below if asked"
        if [ -n "$TS_AUTHKEY" ]; then
            # Pass the key through a 0600 file: command-line arguments are readable by every local user.
            key_file=$(mktemp)
            trap 'rm -f "$key_file"' EXIT
            printf '%s' "$TS_AUTHKEY" > "$key_file"
            tailscale up --auth-key="file:$key_file"
            rm -f "$key_file"
            trap - EXIT
        else
            tailscale up
        fi
    fi
    BIND_HOST=$(tailscale ip -4 | head -1)
fi
[ -n "$BIND_HOST" ] || die "could not determine the Tailscale IP; set BIND_HOST explicitly"
[ "$BIND_HOST" != "0.0.0.0" ] || die "refusing to expose a web terminal on all interfaces"
write_conf  # Keep the address that was actually resolved.

say "user $DEV_USER"
if ! id "$DEV_USER" >/dev/null 2>&1; then
    # Never adopt a foreign group that already owns the preferred GID as the user's primary group.
    if ! getent group "$DEV_USER" >/dev/null; then
        if getent group "$DEV_UID" >/dev/null; then groupadd "$DEV_USER"; else groupadd -g "$DEV_UID" "$DEV_USER"; fi
    fi
    useradd -u "$DEV_UID" -g "$DEV_USER" -m -s /bin/bash "$DEV_USER"
fi
UID_=$(id -u "$DEV_USER")
H=$(getent passwd "$DEV_USER" | cut -d: -f6)
loginctl enable-linger "$DEV_USER"
for _ in $(seq 20); do [ -S "/run/user/$UID_/bus" ] && break; sleep 0.5; done
as_user() { sudo -u "$DEV_USER" -H env XDG_RUNTIME_DIR="/run/user/$UID_" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID_/bus" "$@"; }

# The in-panel updater (manual or automatic) holds this lock while it swaps files; copying at the same
# time would let its rollback overwrite this install. The lock file is the panel user's, never root's.
UPDATE_LOCK="$H/.config/cc-panel/update.json.lock"
if [ -d "$H/.config/cc-panel" ]; then
    as_user sh -c 'umask 077; : >> "$1"' sh "$UPDATE_LOCK"
    # Read-only: root never creates or writes a file in the user's folder (a swapped-in symlink to a
    # system file would otherwise be created or truncated by root); flock works on a read descriptor.
    [ ! -L "$UPDATE_LOCK" ] || die "$UPDATE_LOCK must not be a symbolic link"
    exec 9<"$UPDATE_LOCK"
    flock -n 9 || { say "waiting for the running panel update to finish"; flock -w 600 9 || die "a panel update is still running; retry later"; }
fi
say "panel code -> $PREFIX"
# Snapshot of the running panel code: if the new version does not answer, it is put back, so a remote
# user is never left with a panel that cannot start.
# Taken and restored as the panel user, like every other write into $PREFIX: root never writes into a
# folder the user owns. A failure anywhere after the copy (not only a failed health check) restores it.
ROLLBACK="" PANEL_COPIED=0 PANEL_HEALTHY=0 PANEL_RESTORED=0
restore_panel() {
    as_user find "$PREFIX" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    as_user cp -a "$ROLLBACK/." "$PREFIX/"
    PANEL_RESTORED=1
}
finish_install() {
    local status=$?
    if [ -n "$ROLLBACK" ]; then
        if [ "$status" != 0 ] && [ "$PANEL_COPIED" = 1 ] && [ "$PANEL_HEALTHY" != 1 ] && [ "$PANEL_RESTORED" != 1 ]; then
            echo "installation stopped; the previous panel files were put back" >&2
            restore_panel || true
        fi
        as_user rm -rf "$ROLLBACK"
    fi
}
if [ ! -L "$PREFIX" ] && [ -f "$PREFIX/panel.py" ]; then
    ROLLBACK=$(as_user mktemp -d /var/tmp/agent-deck-rollback.XXXXXX)
    trap finish_install EXIT
    as_user cp -a "$PREFIX/." "$ROLLBACK/"
fi
PANEL_COPIED=1
# owned by the panel user: the panel runs as that user anyway, and ./deploy.sh can update it without root
[ ! -L "$PREFIX" ] || die "panel runtime must not be a symbolic link"
install -d -m 755 "$PREFIX"
chown -h "$DEV_USER:" "$PREFIX"
as_user find "$SRC/panel" -maxdepth 1 -type f -exec install -m 644 {} "$PREFIX"/ \;
as_user install -d -m 755 "$PREFIX/integrations"
as_user find "$SRC/integrations" -maxdepth 1 -type f -name '*.py' -exec install -m 644 {} "$PREFIX/integrations"/ \;
# Pinned cryptography wheels (SHA-256 checked) for backups and notifications; the panel retries on its own if offline.
say "encryption components (cryptography) -> ~$DEV_USER/.local/share/agent-deck"
as_user /usr/bin/python3 -c "import sys; sys.path.insert(0, '$PREFIX'); from integrations import dependencies; sys.exit(0 if dependencies.ensure(background=False, prune_old=False) else 1)" \
    || say "encryption components could not be downloaded now; the panel will retry automatically"
as_user install -d -m 755 "$PREFIX/locales"
as_user find "$SRC/locales" -maxdepth 1 -type f \( -name '*.py' -o -name '*.json' \) -exec install -m 644 {} "$PREFIX/locales"/ \;

[ -f "$SRC/locales/${PANEL_LANGUAGE:-en}.json" ] && [[ "${PANEL_LANGUAGE:-en}" =~ ^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$ ]] || die "unsupported PANEL_LANGUAGE"
say "config"
as_user install -d -m 700 "$H/.config/cc-panel"
ENV="$H/.config/cc-panel/env"
NEW_PASS=""
[ ! -L "$ENV" ] || die "panel env must not be a symbolic link"
if [ ! -f "$ENV" ]; then
    NEW_PASS=$(python3 -I -c 'import secrets; print(secrets.token_urlsafe(18))')
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
# A stale address in an existing env (see BIND_HOST above) is replaced; a working one is left as configured.
ENV_BIND=$(as_user sed -n 's/^BIND_HOST=//p' "$ENV" | head -1)
if [ -n "$ENV_BIND" ] && [ "$ENV_BIND" != "$BIND_HOST" ] && ! bind_is_local "$ENV_BIND"; then
    say "panel address $ENV_BIND -> $BIND_HOST"
    as_user sed -i "s|^BIND_HOST=.*|BIND_HOST=$BIND_HOST|" "$ENV"
fi
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
    # Non-interactive: its "Start Codex now?" question would stop the whole installation.
    as_user bash -c 'curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh'
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
# Probe where the panel really listens: its env, which may differ from this run's options.
PROBE="$(as_user sed -n 's/^BIND_HOST=//p' "$ENV" | head -1):$(as_user sed -n 's/^BIND_PORT=//p' "$ENV" | head -1)"
panel_answers() {
    for _ in $(seq 40); do
        # Quiet while the panel is still starting; a real failure is reported below.
        curl -fs -o /dev/null --max-time 2 "http://$PROBE/login" && return 0
        sleep 0.5
    done
    return 1
}
PANEL_LOGS="journalctl --user -M $DEV_USER@ -u cc-panel -n 50"
if ! panel_answers; then
    [ -n "$ROLLBACK" ] || die "the panel does not answer at http://$PROBE: $PANEL_LOGS"
    say "v$NEW_VERSION did not answer; restoring the previous panel"
    restore_panel
    as_user systemctl --user restart cc-panel.service
    panel_answers || die "the restored panel does not answer either: $PANEL_LOGS"
    die "v$NEW_VERSION did not start; the previous version was restored and is running. Logs: $PANEL_LOGS"
fi
PANEL_HEALTHY=1
as_user systemctl --user is-active -q cc-tmux cc-ttyd cc-panel || die "a service failed: journalctl --user -M $DEV_USER@ -n 50"
exec 9>&-  # Release the update lock; nothing started later may inherit it.

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
write_conf   # again: BIND_HOST and PUBLIC_PROXY may have been resolved above

echo
say "Agent Deck v$NEW_VERSION — done: http://$BIND_HOST:$PANEL_PORT  (user: $DEV_USER)"
[ -z "$PUBLIC_DOMAIN" ] || echo "    public: https://$PUBLIC_DOMAIN"
if [ -n "$NEW_PASS" ]; then
    echo "    password: $NEW_PASS"
else
    echo "    password: grep PANEL_PASSWORD $ENV"
fi
echo "    first run: open a session and do /login inside Claude, then 'Connect GitHub' in the sidebar"
