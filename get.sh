#!/usr/bin/env bash
# One-line install / update of Agent Deck:
#   curl -fsSL https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh | sudo bash
#   curl -fsSL https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh | sudo PUBLIC_DOMAIN=cli.example.com bash
# Clones the latest release to /opt/agent-deck (AGENT_DECK_DIR) and runs install.sh; if it is already
# there, updates it instead. Options are passed through as environment variables (see README).
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
DIR=${AGENT_DECK_DIR:-/opt/agent-deck}
REPO=${AGENT_DECK_REPO:-https://github.com/matacoder/agent-deck.git}

[ "$(id -u)" = 0 ] || { echo "run with sudo: curl -fsSL ... | sudo bash" >&2; exit 1; }
if ! command -v git >/dev/null || ! command -v python3 >/dev/null; then
    apt-get update -q >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q git python3 >/dev/null
fi

if [ -d "$DIR/.git" ]; then
    require_root_checkout "$DIR"
    exec "$DIR/update.sh"
fi
require_root_checkout "$(dirname "$DIR")" parents
[ ! -e "$DIR" ] && [ ! -L "$DIR" ] || require_root_checkout "$DIR"
git clone -q "$REPO" "$DIR"
tag=$(git -C "$DIR" tag -l 'v*' --sort=-v:refname | awk '/^v[0-9]+\.[0-9]+\.[0-9]+$/ && !found {print; found=1}')
[ -z "$tag" ] || git -C "$DIR" -c advice.detachedHead=false checkout -q "$tag"
require_root_checkout "$DIR"
exec "$DIR/install.sh"
