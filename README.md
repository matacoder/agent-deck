# Agent Deck

A self-hosted workspace for [Claude Code](https://claude.com/claude-code),
[Codex](https://github.com/openai/codex), Kimi and terminals. Install on Linux or
macOS, work from a desktop or phone browser, and answer agent questions in Telegram.
Sessions live in tmux, keep working after you close the tab, and can be restored
after a reboot.

![Agent Deck on desktop](docs/screenshots/desktop.png)

| Session on a phone | Sessions & limits | New session from GitHub |
|:---:|:---:|:---:|
| <img src="docs/screenshots/mobile-screen.png" width="260" alt="Phone: session screen"> | <img src="docs/screenshots/mobile-sessions.png" width="260" alt="Phone: session list"> | <img src="docs/screenshots/mobile-new.png" width="260" alt="Phone: new session"> |

<sub>Screenshots use demo data.</sub>

## Features

- Tabs for all your sessions, grouped by project, with live terminals and "working / waiting / done" status.
- Claude Code, Codex, Claude through Kimi, native Kimi Code or a plain terminal per tab; restart an agent keeping the conversation.
- Pick a GitHub repo and start working; optional git worktree per session (one branch per agent).
- Claude / Codex subscription limits with a pace forecast; Kimi usage windows and reset times.
- Server CPU/RAM indicators beside the message composer.
- Phone friendly: home-screen app, message box, question controls and file attachments up to 200 MB.
- UI in 16 languages, switchable in Settings; extensible file-based locales.
- Telegram bot integration: receive agent questions with answer buttons in your private chat.
- One-command installation on Linux and macOS, autostart and panel updates; in-panel agent setup and login.

<img src="docs/screenshots/mobile-settings.png" width="260" alt="Interface language settings">

## Install

New installations open in English. Change **Settings → Interface language** at any
time; the choice is saved in your browser and preserves message drafts. For Russian
from the first launch, set `PANEL_LANGUAGE=ru` on the installer:

```bash
# Linux
curl -fsSL https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh | sudo PANEL_LANGUAGE=ru bash
# macOS
curl -fsSL https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh | PANEL_LANGUAGE=ru bash
```

Available: English, Russian, Spanish, Brazilian Portuguese, German, French,
Simplified/Traditional Chinese, Japanese, Korean, Indonesian, Turkish, Italian,
Polish, Ukrainian and Hindi. For example, `PANEL_LANGUAGE=ja` starts in Japanese.

[Adding another language](docs/localization.md) only requires a JSON catalog.


On a fresh **Ubuntu 22.04 / 24.04** server:

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh | sudo bash
```

It sets everything up and prints the panel address and password. By default the panel is private:
reachable only from your devices over [Tailscale](https://tailscale.com) (the installer will ask you to
log in to it, or pass `TS_AUTHKEY=tskey-...`).

Then:

1. Open the printed address and log in.
2. In the sidebar, click **Sign in** next to Claude and/or Codex, and **Connect** next to GitHub.
3. On a phone: Share → *Add to Home Screen*.

### macOS (Apple Silicon or Intel)

Run in Terminal **without sudo**:

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh | bash
```

The installer sets up Homebrew if needed (follow its prompts), Python, tmux, ttyd,
GitHub CLI, Claude Code and Codex, then opens `http://127.0.0.1:8790`.
It prints your panel login and password. Sign in to your own Claude/Codex accounts
from the sidebar. Existing installations and agent credentials are reused.
Homebrew may ask to install Apple's command-line tools on a fresh Mac.

The panel starts when you log in to your Mac and runs as your user. It uses a separate
`agent-deck` tmux server and preserves your `.tmux.conf` and other tmux sessions.
It is local-only by default; Docker and Tailscale are not required. A sleeping or
powered-off Mac cannot run agents or serve the panel.

Run the same command to reinstall/update, or update the panel from its sidebar.
Settings/password: `~/.config/cc-panel/macos.json`; logs: `~/Library/Logs/Agent Deck/`.
To change the port, use `... | BIND_PORT=8791 bash`. Use `WITH_CLAUDE=0` or
`WITH_CODEX=0` before `bash` to skip either agent. For phone access, install Tailscale
separately and rerun with `BIND_HOST=<your Mac's Tailscale IPv4 address>`; the panel
password is still required. Keep the Mac awake while using remote sessions.

To stop autostart without deleting sessions or settings:

```bash
launchctl bootout gui/$(id -u)/com.agent-deck.panel
launchctl bootout gui/$(id -u)/com.agent-deck.ttyd
rm ~/Library/LaunchAgents/com.agent-deck.{panel,ttyd}.plist
```

### Your own domain (optional)

Point a DNS A record (e.g. `cli.example.com`) to the server, then:

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh | sudo PUBLIC_DOMAIN=cli.example.com bash
```

HTTPS certificates are issued and renewed automatically (via Dokploy's Traefik if the server has it,
otherwise via Caddy). Note: this makes a web terminal reachable from the internet, protected by the panel
password.

### Other options

Put them before `bash` the same way, e.g. `sudo MEM_MAX=8G bash`:

| Option | Meaning |
|---|---|
| `MEM_MAX`, `CPU_QUOTA` | Cap memory / CPU for everything the panel runs, e.g. `8G`, `200%` |
| `PANEL_LANGUAGE` | Default interface locale: `en`, `ru`, or another installed catalog; default `en`. |
| `DEV_USER` | Name of the (unprivileged) user that runs the sessions, default `dev` |
| `WITH_DOCKER=0`, `WITH_CODEX=0` | Skip rootless Docker / Codex CLI |
| `TS_AUTHKEY` | Join Tailscale without the interactive login |

## Update

When a new version is out, the panel shows **↑ vX.Y.Z** in the sidebar. To update, run the install
command again, or click **Update to vX.Y.Z** in the sidebar / mobile **⋯** menu to update just the
panel without root. For a full update including system setup:

```bash
sudo /opt/agent-deck/update.sh
```

Your settings are kept and running sessions are not interrupted. See [CHANGELOG.md](CHANGELOG.md).

## Telegram

<img src="docs/screenshots/mobile-integrations.png" width="300" alt="Telegram integration: linked demo account, delivery switch and private token controls">

Receive questions from Codex and Claude in your bot's private chat and answer by
tapping a button. Codex questions can arrive while the agent continues working;
the panel opens the queued question, selects your answer and confirms it in the
correct session. Claude through Kimi uses the same Claude adapter; native Kimi uses
recognized active terminal menus. Custom text and multiple selections use the panel.

1. Open **⋯ → Integrations** on a phone, or **Telegram → Configure** in the sidebar.
2. Paste your existing bot token from [@BotFather](https://t.me/BotFather) and save.
3. Follow **Link my Telegram** and press **Start** in the bot's private chat.
4. Answer a question using its buttons. The bot confirms when the answer reaches the agent.

The pairing link contains a one-time code and expires after ten minutes. The panel
gets the administrator's user/chat IDs from that authorized `/start` message;
an ordinary `/start` does not grant access. Only the paired account can answer.
Pause delivery with the switch or remove the token from the integration card.
Use a dedicated bot without another polling consumer or webhook. No public server
address, webhook endpoint or extra dependency is needed.

Settings stay in JSON files. Telegram credentials and pairing are in
`~/.config/cc-panel/integrations/telegram.json`; the durable question outbox is in
`questions.sqlite3` alongside it. Both files are private (`600`), and SQLite needs
no database server. Tokens are never returned to the browser or committed to git.
Answers are protected against stale buttons, repeated clicks and uncertain replays
after a restart. See [integration setup and architecture](docs/integrations.md).

## Security

The panel gives a shell to whoever logs in. On Ubuntu it runs as the dedicated unprivileged
user (with rootless Docker); on macOS it runs as your logged-in Mac user. Keep the password private, and prefer the default Tailscale-only setup unless you need public
access.

## More

Architecture, all options, troubleshooting and development: [docs/DETAILS.md](docs/DETAILS.md).

Backend and browser regression tests: [docs/TESTING.md](docs/TESTING.md).

## License

[MIT](LICENSE)

### Kimi Code

Open the sidebar integrations and choose **Kimi → Настроить ключ**. Save a Kimi Code API key
and choose a model. Create a session with **Claude · Kimi** (Claude Code through the Kimi
Anthropic-compatible endpoint) or **Kimi Code** (the native CLI). Install Claude or Kimi
from the integrations if needed. An existing `~/.config/cc-kimi/env` key is detected automatically.

The key stays on the server in a private file; API responses and tmux commands do not contain it.
Clearing the password field preserves the key; **Удалить ключ** removes it from the panel.
Model/key changes apply on the next agent launch. Native sessions/configuration use
`~/.config/cc-panel/kimi-native/`, preserving the user's independent Kimi configuration.

Kimi quota cards show the account’s returned monthly total/coding and short-period limits,
with reset dates. Monthly windows do not assume a fixed 30-day duration for pace forecasts.
