#!/usr/bin/env bash
# Agent Deck on SteamOS (Steam Machine, Steam Deck) without root.
#
# SteamOS wipes system packages on every update, so Agent Deck runs as a rootless Podman container
# (Podman ships with SteamOS 3.5+) built from docker/Dockerfile, started by a systemd user service.
# Everything lives in the home directory and survives SteamOS updates. Re-run to update.
#
#   ./install-steamos.sh                                  # panel on this machine only (127.0.0.1:8790)
#   AGENT_DECK_BIND=0.0.0.0 ./install-steamos.sh          # reachable from your home network
#   AGENT_DECK_PROJECTS=~/Projects ./install-steamos.sh   # agents work in a folder of this machine
set -euo pipefail
say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" != 0 ] || die "run as your desktop user (e.g. deck), not as root"
[ "$(uname -m)" = x86_64 ] || die "SteamOS on x86_64 is expected; on other systems use install.sh or docker compose"
PODMAN=$(command -v podman) || die "Podman not found; update SteamOS to 3.5 or newer (it includes Podman)"
SRC=$(cd "$(dirname "$0")" && pwd)
[ -f "$SRC/docker/Dockerfile" ] || die "run from a checkout of the repository (docker/Dockerfile not found)"
# Paths end up in a systemd unit, where spaces split arguments and % starts a specifier.
[[ "$SRC" != *[[:space:]\"\'\\%]* ]] || die "move the repository to a folder without spaces, quotes or %"

BIND=${AGENT_DECK_BIND:-127.0.0.1}
PORT=${AGENT_DECK_PORT:-8790}
PROJECTS=${AGENT_DECK_PROJECTS:-}
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/agent-deck.service"

# The service file is the whole installation state; values are checked before they reach it.
[[ "$BIND" =~ ^[0-9.]+$ ]] || die "AGENT_DECK_BIND must be an IPv4 address"
[[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1024 ] && [ "$PORT" -le 65535 ] || die "AGENT_DECK_PORT must be 1024-65535"
if [ -n "$PROJECTS" ]; then
    PROJECTS=$(cd "$PROJECTS" 2>/dev/null && pwd) || die "AGENT_DECK_PROJECTS: folder not found"
    [[ "$PROJECTS" != *[[:space:]\"\'\\%]* ]] || die "AGENT_DECK_PROJECTS: use a path without spaces or quotes"
fi

render_unit() {
    # keep-id maps this user to the container's user, so the volume and a projects folder stay yours.
    local mount=""
    [ -z "$PROJECTS" ] || mount=" -v $PROJECTS:/home/dev/dev"
    cat <<UNIT
[Unit]
Description=Agent Deck (Podman)
Wants=network-online.target
After=network-online.target

[Service]
ExecStartPre=-$PODMAN rm -f agent-deck
ExecStart=$PODMAN run --rm --name agent-deck --init --userns=keep-id:uid=1000,gid=1000 -p $BIND:$PORT:8790 -v agent-deck-home:/home/dev$mount -e AGENT_DECK_UPDATE_COMMAND=$SRC/install-steamos.sh localhost/agent-deck:latest
ExecStop=$PODMAN stop -t 10 agent-deck
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
UNIT
}

main() {
    say "building the Agent Deck image (first time: a few minutes)"
    "$PODMAN" build --format docker -t localhost/agent-deck:latest -f "$SRC/docker/Dockerfile" "$SRC"
    "$PODMAN" volume exists agent-deck-home || "$PODMAN" volume create agent-deck-home >/dev/null

    say "user service"
    mkdir -p "$UNIT_DIR"
    render_unit > "$UNIT.new" && mv -f "$UNIT.new" "$UNIT"
    systemctl --user daemon-reload
    systemctl --user enable agent-deck.service >/dev/null
    systemctl --user restart agent-deck.service

    say "waiting for the panel (the first start also installs Claude Code and Codex)"
    for _ in $(seq 180); do
        curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/login" 2>/dev/null && break
        sleep 2
    done
    curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/login" \
        || die "the panel did not start; logs: journalctl --user -u agent-deck -n 50"
    password=$("$PODMAN" exec agent-deck sed -n 's/^PANEL_PASSWORD=//p' /home/dev/.config/cc-panel/env)
    echo
    echo "Agent Deck is ready: http://$([ "$BIND" = 0.0.0.0 ] && echo "<this machine's address>" || echo "$BIND"):$PORT"
    echo "Login: dev"
    echo "Password: $password"
    echo "It starts with the desktop session. To keep it running without anyone logged in, run once:"
    echo "  sudo loginctl enable-linger $USER     (needs a sudo password: set one with passwd)"
}

[ "${AGENT_DECK_SOURCE_ONLY:-}" = 1 ] || main "$@"
