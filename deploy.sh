#!/usr/bin/env bash
# Deploy panel changes from this checkout without root (run as the panel user, e.g. dev).
#   ./deploy.sh            # copy panel/ to /opt/cc-panel, refresh units/tmux.conf, restart panel + ttyd
# Never restarts cc-tmux: running sessions are untouched. System-level changes (packages, Traefik/Caddy,
# new users) still need: sudo ./install.sh
set -euo pipefail
SRC=$(cd "$(dirname "$0")" && pwd)
PREFIX=/opt/cc-panel
[ "$(id -u)" != 0 ] || { echo "run as the panel user, not root (root: use install.sh)" >&2; exit 1; }
[ -w "$PREFIX" ] || { echo "$PREFIX is not writable by $(id -un); run once: sudo ./install.sh" >&2; exit 1; }
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}

PYTHONDONTWRITEBYTECODE=1 python3 - "$SRC" <<'PYTHON'
from pathlib import Path
import sys
for path in (Path(sys.argv[1]) / "panel").glob("*.py"):
    compile(path.read_text(), str(path), "exec")
for path in (Path(sys.argv[1]) / "integrations").glob("*.py"):
    compile(path.read_text(), str(path), "exec")
PYTHON
find "$SRC/panel" -maxdepth 1 -type f -exec install -m 644 {} "$PREFIX"/ \;
install -d -m 755 "$PREFIX/integrations"
find "$SRC/integrations" -maxdepth 1 -type f -name '*.py' -exec install -m 644 {} "$PREFIX/integrations"/ \;
install -d -m 755 "$PREFIX/locales"
find "$SRC/locales" -maxdepth 1 -type f \( -name '*.py' -o -name '*.json' \) -exec install -m 644 {} "$PREFIX/locales"/ \;
rm -rf "$SRC/panel/__pycache__"

units_changed=0
for u in "$SRC"/systemd/*.service; do
    dst="$HOME/.config/systemd/user/$(basename "$u")"
    ttyd=$(grep -o '^ExecStart=[^ ]*ttyd' "$dst" 2>/dev/null | cut -d= -f2 || true)
    tmp=$(mktemp); sed "s|/usr/bin/ttyd|${ttyd:-/usr/bin/ttyd}|" "$u" > "$tmp"   # keep the ttyd path install.sh chose
    cmp -s "$tmp" "$dst" || { install -m 644 "$tmp" "$dst"; units_changed=1; }
    rm -f "$tmp"
done
cmp -s "$SRC/config/tmux.conf" "$HOME/.tmux.conf" || { install -m 644 "$SRC/config/tmux.conf" "$HOME/.tmux.conf"; tmux source-file "$HOME/.tmux.conf" 2>/dev/null || true; }
install -m 755 "$SRC/claude/cc-session-hook.py" "$HOME/.claude/cc-session-hook.py"
python3 "$SRC/claude/register-hooks.py"

[ "$units_changed" = 0 ] || systemctl --user daemon-reload
systemctl --user restart cc-ttyd.service cc-panel.service
sleep 1
systemctl --user is-active -q cc-panel cc-ttyd && echo "deployed: panel and ttyd restarted (sessions untouched)"
