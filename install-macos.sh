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
# Only what is missing is installed; tools already present are used as they are. Upgrading them is
# not ours to do, and fails when Homebrew belongs to another account on this Mac.
export HOMEBREW_NO_INSTALL_UPGRADE=1 HOMEBREW_NO_AUTO_UPDATE=1
python_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; }
python_bin="$(brew --prefix)/bin/python3"
python_ok "$python_bin" || python_bin=$(command -v python3 || true)
formulae=() casks=()
[ -n "$python_bin" ] && python_ok "$python_bin" || formulae+=(python)
for tool in tmux ttyd gh; do command -v "$tool" >/dev/null || formulae+=("$tool"); done
[ "${WITH_CLAUDE:-1}" != 1 ] || command -v claude >/dev/null || casks+=(claude-code)
[ "${WITH_CODEX:-1}" != 1 ] || command -v codex >/dev/null || casks+=(codex)
prefix=$(brew --prefix)
if [ $((${#formulae[@]} + ${#casks[@]})) -gt 0 ] && [ ! -w "$prefix" ]; then
    owner=$(stat -f %Su "$prefix" 2>/dev/null || echo 'another user')
    cat >&2 <<MESSAGE
Homebrew at $prefix belongs to "$owner", so "$(id -un)" cannot install with it.
Missing here: ${formulae[*]:-} ${casks[*]:-}
Choose one:
  - run this installer from the "$owner" account, or install the missing tools there:
      brew install ${formulae[*]:-} ${casks[*]:+--cask ${casks[*]}}
  - or take Homebrew over for this account (the "$owner" account loses write access to it):
      sudo chown -R "$(id -un)" "$prefix"
Then run the installer again.
MESSAGE
    exit 1
fi
if [ ${#formulae[@]} -gt 0 ]; then echo "==> Installing ${formulae[*]}"; brew install "${formulae[@]}"; fi
if [ ${#casks[@]} -gt 0 ]; then echo "==> Installing ${casks[*]}"; brew install --cask "${casks[@]}"; fi
python_ok "$python_bin" || python_bin="$prefix/bin/python3"
python_ok "$python_bin" || { echo 'Python 3.10 or newer was not found after installation.' >&2; exit 1; }
runtime="$HOME/.local/share/agent-deck"
mkdir -p "$runtime"
[ ! -L "$runtime" ] || { echo 'Runtime must not be a symlink.' >&2; exit 1; }
# A Homebrew Python upgrade leaves the venv pointing at a removed interpreter: rebuild it.
"$runtime/venv/bin/python3" -c "" 2>/dev/null || rm -rf "$runtime/venv"
"$python_bin" -m venv "$runtime/venv"
"$runtime/venv/bin/python3" -m pip install --disable-pip-version-check 'psutil>=7,<8'
exec "$runtime/venv/bin/python3" "$SRC/macos/install.py" "$@"
