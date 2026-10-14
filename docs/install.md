# Installing and updating DeckAway

[← Back to the overview](../README.md)

## Install

Pick your platform below. Every grey block is one command: copy it as is.

### Linux server (Ubuntu 22.04 / 24.04, Debian 12+, Raspberry Pi OS 64-bit)

The same installer works on Ubuntu, Debian and a Raspberry Pi 4/5 with the 64-bit Raspberry Pi OS
(32-bit systems are not supported: Claude Code needs 64-bit). Run as root on a fresh server:

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/deckaway/main/get.sh | sudo bash
```

The installer prints the panel address, login and password. By default the panel is private:
reachable only from your devices over [Tailscale](https://tailscale.com) (the installer asks you to
log in, or pass `TS_AUTHKEY=tskey-...`).

Russian interface from the first launch:

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/deckaway/main/get.sh | sudo PANEL_LANGUAGE=ru bash
```

Your own domain with automatic HTTPS (needed for [phone notifications](guide.md#notifications)). Point a DNS
A record (for example `cli.example.com`) to the server first:

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/deckaway/main/get.sh | sudo PUBLIC_DOMAIN=cli.example.com bash
```

Certificates are issued and renewed automatically (via Dokploy's Traefik if the server has it,
otherwise via Caddy). This makes a web terminal reachable from the internet, protected by the panel
password.

Other options go before `bash` the same way, for example `sudo MEM_MAX=8G bash`:

| Option | Meaning |
|---|---|
| `MEM_MAX`, `CPU_QUOTA` | Cap memory / CPU for everything the panel runs, e.g. `8G`, `200%` |
| `PANEL_LANGUAGE` | Default interface locale: `en`, `ru`, or another installed catalog; default `en` |
| `DEV_USER` | Name of the (unprivileged) user that runs the sessions, default `dev` |
| `WITH_DOCKER=0`, `WITH_CODEX=0` | Skip rootless Docker / Codex CLI |
| `TS_AUTHKEY` | Join Tailscale without the interactive login |

### macOS (Apple Silicon or Intel)

Run in Terminal **without sudo**:

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/deckaway/main/get.sh | bash
```

The installer sets up Homebrew if needed (follow its prompts), Python, tmux, ttyd,
GitHub CLI, Claude Code and Codex, then opens the panel at the Mac’s Tailscale IPv4
address when Tailscale is connected, or `http://127.0.0.1:8790` otherwise. It prints your
panel login and password. Existing installations and agent credentials are reused.
Homebrew may ask to install Apple's command-line tools on a fresh Mac.

Russian interface from the first launch:

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/deckaway/main/get.sh | PANEL_LANGUAGE=ru bash
```

Choose the project directory (saved for future reinstalls; also changeable in
**Settings → Application → Project directory**):

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/deckaway/main/get.sh | bash -s -- --projects-dir "$HOME/dev"
```

Another port:

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/deckaway/main/get.sh | BIND_PORT=8791 bash
```

Keep the panel local-only (no Tailscale access):

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/deckaway/main/get.sh | BIND_HOST=127.0.0.1 bash
```

`WITH_CLAUDE=0` or `WITH_CODEX=0` before `bash` skips either agent. For phone access, install
Tailscale, connect it and rerun the installer; it selects the Mac’s Tailscale IPv4 address
automatically. The panel starts when you log in to your Mac, runs as your user and uses a separate
`agent-deck` tmux server, preserving your `.tmux.conf`. A sleeping Mac cannot run agents or serve the
panel. Settings/password: `~/.config/cc-panel/macos.json`; logs: `~/Library/Logs/Agent Deck/`.
The panel runs from a virtualenv in `~/.local/share/agent-deck/venv`, created without pip and with no
packages in it, only so the background services keep one interpreter path; processor and memory figures
come from macOS's own `ps`, `sysctl` and `vm_stat`.

Stop autostart without deleting sessions or settings:

```bash
launchctl bootout gui/$(id -u)/com.agent-deck.panel; launchctl bootout gui/$(id -u)/com.agent-deck.ttyd
```

```bash
rm ~/Library/LaunchAgents/com.agent-deck.{panel,ttyd}.plist
```

### Windows 11 (WSL2)

DeckAway runs inside WSL2 (Ubuntu 24.04) with the regular Linux installer; agents work in Linux.
Requirements: Windows 11 22H2 or newer and virtualization enabled (it is on most PCs). Open
**PowerShell as administrator** (Start → type *PowerShell* → *Run as administrator*) and run:

```powershell
irm https://raw.githubusercontent.com/matacoder/deckaway/main/install-windows.ps1 | iex
```

The script installs WSL (on a fresh PC it asks you to restart Windows once and run the command
again), installs and signs in to Tailscale, switches WSL to mirrored networking with host loopback, so this PC opens the panel at its Tailscale
address too (other settings in `%UserProfile%\.wslconfig` are kept, the old file is saved as `.wslconfig.agent-deck-backup`), installs
Ubuntu 24.04 and DeckAway in it, allows the panel port in the firewall for the Tailscale range only,
adds the panel to the Start menu (as **Agent Deck**, the name it had before 1.39) and keeps WSL running while you are signed in. The panel login and
password are printed at the end. If WSL settings had to change, WSL restarts once, which stops other
running Linux programs.

Russian interface from the first launch (run both lines in the same window):

```powershell
$env:AGENT_DECK_LANGUAGE = 'ru'
```

```powershell
irm https://raw.githubusercontent.com/matacoder/deckaway/main/install-windows.ps1 | iex
```

Other options are set the same way before the command: `AGENT_DECK_PORT` (default `8790`),
`AGENT_DECK_DISTRO` (default `Ubuntu-24.04`), `AGENT_DECK_WITH_DOCKER=1` (rootless Docker inside WSL).

Stop autostart (sessions and settings stay in WSL):

```powershell
Unregister-ScheduledTask -TaskName 'Agent Deck' -Confirm:$false; wsl --terminate Ubuntu-24.04
```

Remove the firewall rules:

```powershell
Remove-NetFirewallRule -Name AgentDeck-Tailscale; Remove-NetFirewallHyperVRule -Name AgentDeck-WSL
```

### Docker (NAS, Fedora, Arch, any host with Docker)

One container runs tmux, the terminal and the panel as an unprivileged user; settings, agent logins,
sessions and projects live in the `agent-deck-home` volume. Requires Docker with Compose v2:

```bash
git clone https://github.com/matacoder/deckaway.git && cd deckaway && docker compose up -d --build
```

The first start installs Claude Code and Codex into the volume and creates a login password; show it with:

```bash
docker compose exec agent-deck sed -n 's/^PANEL_PASSWORD=//p' /home/dev/.config/cc-panel/env
```

The panel listens on `127.0.0.1:8790` only. To open it from other devices, put the host on
[Tailscale](https://tailscale.com) and run `tailscale serve --bg 8790`, or publish it on your network by
creating `.env` next to `docker-compose.yml` (the panel gives a shell to whoever logs in, so only on a
trusted network):

```bash
printf 'AGENT_DECK_BIND=0.0.0.0\nPANEL_PASSWORD=choose-a-long-password\n' > .env && docker compose up -d
```

To work on projects from the host instead of the volume, uncomment the `/home/dev/dev` mount in
`docker-compose.yml`. Update by pulling the repository and rebuilding — the in-panel update button is off
in a container:

```bash
git pull && docker compose up -d --build
```

To connect this DeckAway to another one, publish the port on the host's Tailscale address (`AGENT_DECK_BIND=100.x.y.z` in `.env`): connections between DeckAway computers use Tailscale addresses only.

### SteamOS (Steam Machine, Steam Deck)

SteamOS erases system packages on every update, so DeckAway runs as a rootless Podman container
(included in SteamOS 3.5+) with a user service; everything stays in your home folder and survives
updates. No sudo password is needed. In Desktop Mode open Konsole and run:

```bash
git clone https://github.com/matacoder/deckaway.git ~/agent-deck && ~/agent-deck/install-steamos.sh
```

The script prints the address and password. Useful options (add before the command):
`AGENT_DECK_BIND=0.0.0.0` to reach the panel from your home network, `AGENT_DECK_PROJECTS=~/Projects`
to let agents work in a folder of this machine. Update by running the script again; it first updates
its checkout (`git pull --ff-only`, stopping on local changes or a diverged branch; `AGENT_DECK_NO_PULL=1`
builds the checkout as it is):

```bash
~/agent-deck/install-steamos.sh
```

The running image is kept as `localhost/agent-deck:previous` during an update: if the new one does not
answer, the previous image is put back and started again, and the script says so. After a successful
update, the DeckAway image from the update before is removed; no other image is touched.

The panel starts with your session (also in Gaming Mode). A Steam Deck sleeps when idle and pauses the
agents with it; a Steam Machine is meant to stay on. Agents work inside the container, in its `~/dev` or
the folder you pass, not in SteamOS itself.

### After installing

1. Open the printed address and log in.
2. In **Settings → Agents**, sign in to Claude and/or Codex; connect GitHub in **Settings → Connections**.
3. On a phone, add the panel to the Home Screen (see [Phone](guide.md#phone)).

Available interface languages: English, Russian, Spanish, Brazilian Portuguese, German, French,
Simplified/Traditional Chinese, Japanese, Korean, Indonesian, Turkish, Italian, Polish, Ukrainian and
Hindi. [Adding another language](localization.md) only requires a JSON catalog.

**Encryption components.** Backups and notifications use the
[`cryptography`](https://cryptography.io) library. The installer (or the panel itself, later) downloads
the exact wheels pinned in `integrations/dependency_lock.py`, checks each SHA-256 and keeps them in
`~/.local/share/agent-deck/python/`; no pip or root is involved, and nothing is installed into a virtualenv. Without internet access the
panel works normally and retries the download every 10 minutes; only backups and notifications wait.

## Update

The panel shows **↑ vX.Y.Z** in the sidebar when a release is out; click it (or the mobile **⋯** menu)
to update just the panel without root. Settings are kept and running sessions are not interrupted.
See [CHANGELOG.md](../CHANGELOG.md).

Full update on Linux, including system setup:

```bash
sudo /opt/agent-deck/update.sh
```

Full update on Windows 11 — rerun the installer in PowerShell as administrator:

```powershell
irm https://raw.githubusercontent.com/matacoder/deckaway/main/install-windows.ps1 | iex
```

Full update on macOS — rerun the installer:

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/deckaway/main/get.sh | bash
```
