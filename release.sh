#!/usr/bin/env bash
# Cut a release (maintainers): ./release.sh 0.2.0
#   needs a clean, pushed main and a "## 0.2.0" section in CHANGELOG.md (used as release notes)
set -euo pipefail
cd "$(dirname "$0")"
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }
v=${1:?usage: ./release.sh X.Y.Z}
[[ $v =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must look like 1.2.3"
[ "$(git rev-parse --abbrev-ref HEAD)" = main ] || die "release from main"
python3 scripts/build-panel.py --check || die "panel/index.html is stale: run scripts/build-panel.py and commit"
[ -z "$(git status --porcelain)" ] || die "commit your changes first"
git fetch -q --tags origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "main differs from origin/main: pull/push first"
# A tag pushed before a failed "gh release create" is finished by running the same command again.
tagged=$(git rev-parse -q --verify "refs/tags/v$v^{commit}" || true)
[ -z "$tagged" ] || [ "$tagged" = "$(git rev-parse HEAD)" ] || die "v$v already exists on another commit"
notes=$(awk -v v="$v" '$0 ~ "^## " v "( |$)" {f=1; next} /^## / {f=0} f' CHANGELOG.md)
[ -n "$(printf '%s' "$notes" | tr -d '[:space:]')" ] || die "add a '## $v' section to CHANGELOG.md"
if [ -z "$tagged" ]; then
    if [ "$(cat panel/VERSION)" != "$v" ]; then
        echo "$v" > panel/VERSION
        git add panel/VERSION && git commit -q -m "Release v$v"
    fi
    git tag -a "v$v" -m "DeckAway v$v"
fi
git push -q origin main "v$v"
! gh release view "v$v" >/dev/null 2>&1 || die "v$v is already released"
gh release create "v$v" --title "DeckAway v$v" --notes "$notes"
echo "released v$v — installs see it within ~6 h; they update with: sudo ./update.sh"
