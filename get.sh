#!/usr/bin/env bash
# One-line install / update of Agent Deck:
#   curl -fsSL https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh | sudo bash
#   curl -fsSL https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh | sudo PUBLIC_DOMAIN=cli.example.com bash
# Clones the latest release to /opt/agent-deck (AGENT_DECK_DIR) and runs install.sh; if it is already
# there, updates it instead. Options are passed through as environment variables (see README).
set -euo pipefail
DIR=${AGENT_DECK_DIR:-/opt/agent-deck}
REPO=${AGENT_DECK_REPO:-https://github.com/matacoder/agent-deck.git}

[ "$(id -u)" = 0 ] || { echo "run with sudo: curl -fsSL ... | sudo bash" >&2; exit 1; }
command -v git >/dev/null || { apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -y -q git; } >/dev/null

if [ -d "$DIR/.git" ]; then
    exec "$DIR/update.sh"
fi
git clone -q "$REPO" "$DIR"
tag=$(git -C "$DIR" tag -l 'v*' --sort=-v:refname | head -1)
[ -z "$tag" ] || git -C "$DIR" -c advice.detachedHead=false checkout -q "$tag"
exec "$DIR/install.sh"
