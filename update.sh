#!/usr/bin/env bash
# Update Agent Deck from GitHub and re-run the installer with the remembered options.
#   sudo ./update.sh           # latest release (git tag vX.Y.Z)
#   sudo ./update.sh v0.2.0    # a specific version
#   sudo ./update.sh main      # latest development state
# Running sessions are not interrupted (the tmux server is never restarted).
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
cd "$(dirname "$0")"
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root: sudo ./update.sh"
require_root_checkout "$PWD"
g() { git -c core.hooksPath=/dev/null "$@"; }
[ -z "$(g status --porcelain --untracked-files=no)" ] || die "local changes in $(pwd); commit or stash them first"
from=$(cat panel/VERSION 2>/dev/null || echo "?")
g fetch -q --tags --force origin
target=${1:-$(g tag -l 'v*' --sort=-v:refname | awk '/^v[0-9]+\.[0-9]+\.[0-9]+$/ && !found {print; found=1}')}
target=${target:-main}
if [ "$target" = main ]; then
    g checkout -q main && g pull -q --ff-only origin main
else
    g rev-parse -q --verify "refs/tags/$target" >/dev/null || die "no such version: $target"
    g -c advice.detachedHead=false checkout -q "$target"
fi
echo "==> Agent Deck $from -> $(cat panel/VERSION) ($target)"
require_root_checkout "$PWD"
exec ./install.sh
