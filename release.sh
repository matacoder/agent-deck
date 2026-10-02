#!/usr/bin/env bash
# Cut a release (maintainers): ./release.sh 0.2.0
#   needs a clean, pushed main and a "## 0.2.0" section in CHANGELOG.md (used as release notes)
set -euo pipefail
cd "$(dirname "$0")"
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }
v=${1:?usage: ./release.sh X.Y.Z}
[[ $v =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must look like 1.2.3"
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || die "release from main"
[ -z "$(git status --porcelain)" ] || die "commit your changes first"
git fetch -q --tags origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "main differs from origin/main: pull/push first"
! git rev-parse -q --verify "refs/tags/v$v" >/dev/null || die "v$v already exists"
notes=$(awk -v v="$v" '$0 ~ "^## " v "( |$)" {f=1; next} /^## / {f=0} f' CHANGELOG.md)
[ -n "$(printf '%s' "$notes" | tr -d '[:space:]')" ] || die "add a '## $v' section to CHANGELOG.md"
if [ "$(cat panel/VERSION)" != "$v" ]; then
    echo "$v" > panel/VERSION
    git add panel/VERSION && git commit -q -m "Release v$v"
fi
git tag -a "v$v" -m "Agent Deck v$v"
git push -q origin main "v$v"
gh release create "v$v" --title "Agent Deck v$v" --notes "$notes"
echo "released v$v — installs see it within ~6 h; they update with: sudo ./update.sh"
