#!/usr/bin/env bash
# Run as the logged-in Mac user; Homebrew may ask for a password on first install.
set -euo pipefail
[ "$(uname -s)" = Darwin ] || { echo 'This installer requires macOS.' >&2; exit 1; }
[ "$(id -u)" != 0 ] || { echo 'Run without sudo, as your normal Mac user.' >&2; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
if ! command -v brew >/dev/null; then
    echo '==> Installing Homebrew (follow its prompts)'
    brew_installer=$(mktemp)
    trap 'rm -f "$brew_installer"' EXIT
    curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$brew_installer"
    /bin/bash "$brew_installer" </dev/tty
fi
command -v brew >/dev/null || { echo 'Homebrew installation did not finish.' >&2; exit 1; }
echo '==> Installing Python, tmux, ttyd and GitHub CLI'
brew install python tmux ttyd gh
python_bin="$(brew --prefix python)/bin/python3"
[ -x "$python_bin" ] || python_bin=$(command -v python3)
if [ "${WITH_CLAUDE:-1}" = 1 ] && ! command -v claude >/dev/null; then
    brew install --cask claude-code
fi
if [ "${WITH_CODEX:-1}" = 1 ] && ! command -v codex >/dev/null; then
    brew install --cask codex
fi
runtime="$HOME/.local/share/agent-deck"
mkdir -p "$runtime"
[ ! -L "$runtime" ] || { echo 'Runtime must not be a symlink.' >&2; exit 1; }
"$python_bin" -m venv "$runtime/venv"
"$runtime/venv/bin/python3" -m pip install --disable-pip-version-check 'psutil>=7,<8'
exec "$runtime/venv/bin/python3" "$SRC/macos/install.py" "$@"
