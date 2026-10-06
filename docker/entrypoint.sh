#!/usr/bin/env bash
# Zero-config start, safe to repeat: settings, password, hooks and agents live in the /home/dev volume.
set -euo pipefail
CONFIG="$HOME/.config/cc-panel"
ENV_FILE="$CONFIG/env"
SOCK=/tmp/agent-deck/cc-ttyd.sock
mkdir -p -m 700 "$CONFIG" /tmp/agent-deck
mkdir -p "$HOME/dev" "$HOME/.claude"

if [ ! -f "$ENV_FILE" ]; then
    password=${PANEL_PASSWORD:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')}
    ( umask 077; cat > "$ENV_FILE" <<CONF
BIND_HOST=0.0.0.0
BIND_PORT=8790
PANEL_LANGUAGE=${PANEL_LANGUAGE:-en}
PANEL_USER=${PANEL_USER:-dev}
PANEL_PASSWORD=$password
TTYD_SOCK=$SOCK
PROJECTS_DIR=$HOME/dev
CONF
    )
    [ -n "${PANEL_PASSWORD:-}" ] || echo "Agent Deck login: ${PANEL_USER:-dev} / $password  (stored in $ENV_FILE)"
fi
# A password given in the environment always wins, so it can be rotated by recreating the container.
if [ -n "${PANEL_PASSWORD:-}" ]; then
    python3 - "$ENV_FILE" <<'PY'
import os, sys
path = sys.argv[1]
lines = [l for l in open(path).read().splitlines() if not l.startswith("PANEL_PASSWORD=")]
open(path, "w").write("\n".join(lines + ["PANEL_PASSWORD=" + os.environ["PANEL_PASSWORD"]]) + "\n")
PY
fi

if [ -f "$HOME/.tmux.conf" ] && ! cmp -s "$HOME/.tmux.conf" /opt/agent-deck/config/tmux.conf; then
    cp "$HOME/.tmux.conf" "$HOME/.tmux.conf.bak.$(date +%s)"
fi
cp /opt/agent-deck/config/tmux.conf "$HOME/.tmux.conf"
install -m 755 /opt/agent-deck/claude/cc-session-hook.py "$HOME/.claude/cc-session-hook.py"
python3 /opt/agent-deck/claude/register-hooks.py

# Agents install into the volume once and update themselves there; a failed download is not fatal.
if [ "${WITH_CLAUDE:-1}" = 1 ] && ! command -v claude >/dev/null; then
    curl -fsSL https://claude.ai/install.sh | bash || echo "Claude Code could not be installed now; it is retried on the next start"
fi
if [ "${WITH_CODEX:-1}" = 1 ] && ! command -v codex >/dev/null; then
    curl -fsSL https://chatgpt.com/codex/install.sh | sh || echo "Codex CLI could not be installed now; it is retried on the next start"
fi

# The same three services as the systemd units: tmux owns the sessions, ttyd and the panel restart on exit.
tmux has-session -t _keep 2>/dev/null || tmux new-session -d -s _keep
( while :; do tmux has-session -t _keep 2>/dev/null || tmux new-session -d -s _keep; sleep 10; done ) &
( while :; do
    rm -f "$SOCK"
    ttyd -i "$SOCK" -b /t -W -a -O -t fontSize=13 -t "fontFamily=Menlo, SF Mono, monospace" \
        -t disableLeaveAlert=true -t macOptionClickForcesSelection=true -t rightClickSelectsWord=true \
        -t titleFixed=AgentDeck -- tmux attach -t || true
    sleep 3
  done ) &
( while :; do
    # KEY=VALUE lines like systemd's EnvironmentFile: values are taken literally, never run by a shell.
    python3 -c 'import os, runpy, sys
for line in open(sys.argv[1]).read().splitlines():
    key, sep, value = line.partition("=")
    if sep and key.strip() and not key.startswith("#"):
        os.environ[key.strip()] = value
sys.path.insert(0, "/opt/cc-panel")
runpy.run_path("/opt/cc-panel/panel.py", run_name="__main__")' "$ENV_FILE" || true
    sleep 2
  done ) &
wait
