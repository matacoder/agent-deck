#!/usr/bin/env bash
# Update Agent Deck from GitHub and re-run the installer with the remembered options.
#   sudo ./update.sh           # latest release (git tag vX.Y.Z)
#   sudo ./update.sh v0.2.0    # a specific version
#   sudo ./update.sh main      # latest development state
# Running sessions are not interrupted (the tmux server is never restarted).
set -euo pipefail
cd "$(dirname "$0")"
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root: sudo ./update.sh"
owner=$(stat -c %U .)
g() { sudo -u "$owner" git "$@"; }          # the checkout belongs to a normal user
[ -z "$(g status --porcelain --untracked-files=no)" ] || die "local changes in $(pwd); commit or stash them first"
from=$(cat panel/VERSION 2>/dev/null || echo "?")
g fetch -q --tags --force origin
target=${1:-$(g tag -l 'v*' --sort=-v:refname | head -1)}
target=${target:-main}
if [ "$target" = main ]; then
    g checkout -q main && g pull -q --ff-only origin main
else
    g rev-parse -q --verify "refs/tags/$target" >/dev/null || die "no such version: $target"
    g -c advice.detachedHead=false checkout -q "$target"
fi
echo "==> Agent Deck $from -> $(cat panel/VERSION) ($target)"
exec ./install.sh
