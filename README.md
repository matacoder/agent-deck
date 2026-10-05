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
- Under the message field: the running agent and model (including after `/model`), remaining quota and today's plan, so limits stay visible on phones.
- Server CPU/RAM indicators beside the message composer.
- Phone friendly (tuned for large iPhones, portrait and landscape): home-screen app, one-tap answers to agent questions, quick session tabs with long-press actions, and file attachments up to 200 MB with upload progress.
- One Settings hub for agents, model sources, GitHub/Telegram connections, network and application preferences.
- LM Studio profiles: discover known Tailscale nodes or add a custom address, port and API key.
- Local models in Claude Code, with session speed/TTFT measurements and a separate benchmark; no subscription quotas.
- UI in 16 languages, switchable in Settings → Application; extensible file-based locales.
- Telegram bot integration: receive agent questions with answer buttons in your private chat.
- One-command installation on Linux and macOS, autostart and panel updates; in-panel agent setup and login.

<img src="docs/screenshots/mobile-settings.png" width="260" alt="Interface language settings">

## Install

New installations open in English. Change **Settings → Application → Interface language** at any
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
GitHub CLI, Claude Code and Codex, then opens the panel at the Mac’s Tailscale IPv4
address when Tailscale is connected, or `http://127.0.0.1:8790` otherwise.
It prints your panel login and password. Sign in to your own Claude/Codex accounts
from the sidebar. Existing installations and agent credentials are reused.
Homebrew may ask to install Apple's command-line tools on a fresh Mac.

The panel starts when you log in to your Mac and runs as your user. It uses a separate
`agent-deck` tmux server and preserves your `.tmux.conf` and other tmux sessions.
Without a connected Tailscale client it is local-only; Docker and Tailscale are not required. A sleeping or
powered-off Mac cannot run agents or serve the panel.

Run the same command to reinstall/update, or update the panel from its sidebar.
Settings/password: `~/.config/cc-panel/macos.json`; logs: `~/Library/Logs/Agent Deck/`.
To choose your project directory during installation (for example `~/dev`):

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh | bash -s -- --projects-dir "$HOME/dev"
```

The path is saved for future reinstalls. It can also be changed immediately in
**Settings → Application → Project directory** without moving existing sessions. `PROJECTS_DIR` is also supported as an
installation environment variable; `--projects-dir` takes precedence.
To change the port, use `... | BIND_PORT=8791 bash`. Use `WITH_CLAUDE=0` or
`WITH_CODEX=0` before `bash` to skip either agent. For phone access, install Tailscale
separately, connect it and rerun the installer; it automatically selects the Mac’s
Tailscale IPv4 address, including for older localhost installations. The panel password
is still required. Explicit `BIND_HOST` overrides are remembered; use
`... | BIND_HOST=127.0.0.1 bash` to keep access local-only. Keep the Mac awake while using remote sessions.

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

1. Open **Settings → Connections → Telegram → Configure** on desktop or phone.
2. Paste your existing bot token from [@BotFather](https://t.me/BotFather) and save.
3. Follow **Link my Telegram** and press **Start** in the bot's private chat.
4. Answer a question using its buttons. The bot confirms when the answer reaches the agent.

The pairing link contains a one-time code and expires after ten minutes. The panel
gets the administrator's user/chat IDs from that authorized `/start` message;
an ordinary `/start` does not grant access. Only the paired account can answer.
Pause delivery with the switch or remove the token from the integration card.
Use a dedicated bot without another polling consumer or webhook. No public server
address, webhook endpoint or extra dependency is needed.

**Several computers, one bot.** Telegram delivers button taps to a single receiver,
so configure the bot only on the Agent Deck you open in the browser and connect the
others in **Settings → Network → Other Agent Deck instances**. Their questions arrive
in the same bot, labelled with the computer name, and answers are relayed back through
the authenticated gateway. Leave Telegram off on the connected computers.

Settings stay in JSON files. Telegram credentials and pairing are in
`~/.config/cc-panel/integrations/telegram.json`; the durable question outbox is in
`questions.sqlite3` alongside it. Both files are private (`600`), and SQLite needs
no database server. Tokens are never returned to the browser or committed to git.
Answers are protected against stale buttons, repeated clicks and uncertain replays
after a restart. See [integration setup and architecture](docs/integrations.md).

## Backups

**Settings → Backups** protects Agent Deck settings, integration keys (Telegram, Kimi,
LM Studio, connected Agent Decks) and agent logins (`~/.codex/auth.json`,
`~/.claude/.credentials.json` on Linux, `~/.config/gh/hosts.yml`). The panel login and
password are set by the installer and are not part of a backup; on macOS Claude keeps
its login in the Keychain, so log in to Claude again after a restore.

1. Click **Turn on backups** and store the recovery code (`AD1-…`) in a password manager.
   It is shown once; without it a backup cannot be decrypted on a new computer.
2. The Agent Deck you open in the browser gives the same key to every connected
   computer, backs up each of them daily (and on **Back up now**) and keeps every copy on
   every other computer. Each computer keeps its last 14 copies per machine.
3. To replace a dead computer, install Agent Deck on the new one, connect it under
   **Settings → Network**, then pick its backup and **Restore to** the new computer. To
   rebuild the main computer, connect any surviving one, choose it as the copy source,
   enter the recovery code and restore. **Download this machine's backup** gives an
   offline `.adbk` file for **Restore from file**.

Backups are encrypted with keyed BLAKE2b (counter-mode stream and a separate
authentication tag) from the Python standard library, so other computers only hold
ciphertext. Restoring first backs up the state it replaces, writes files only to their
known locations with `600` permissions and restarts the panel; tmux sessions keep running.

## Security

The panel gives a shell to whoever logs in. On Ubuntu it runs as the dedicated unprivileged
user (with rootless Docker); on macOS it runs as your logged-in Mac user. Keep the password private, and prefer the default Tailscale-only setup unless you need public
access.

## More

Architecture, all options, troubleshooting and development: [docs/DETAILS.md](docs/DETAILS.md).

Backend and browser regression tests: [docs/TESTING.md](docs/TESTING.md).

## License

[MIT](LICENSE)

### LM Studio Connector

<img src="docs/screenshots/desktop-models.png" width="760" alt="Unified model settings with a demo local server">

1. Enable the LM Studio server on the machine hosting your model, with its
   Anthropic-compatible `/v1/messages` API reachable over your tailnet.
2. Open **Settings → Models**. Choose **Find servers** to probe known Tailscale
   peers on port 1234, or enter comma-separated custom ports. This checks addresses
   returned by `tailscale status --json`; it does not scan arbitrary networks.
3. Add a discovered server, or use **Add server** with a custom HTTP/HTTPS URL
   and optional API key. Saving checks the connection and lists available models.
4. **Test tools** explicitly verifies a synthetic tool call. **Measure speed**
   runs a small synthetic benchmark; neither test sends an existing conversation.
5. In **New session**, select **Claude** and the local server/model as its source.
   Install Claude Code under **Settings → Agents** if needed.

The selected server and model are pinned to the session, including restarts and
recovery. A missing profile or binding leaves a shell; it never falls back to a
cloud provider. Add a separate profile to change servers while sessions use the
original one. API keys can be rotated without changing the pinned address.

Local models have no subscription quota cards. The panel reports observed
streaming tokens/s and time to first token from real session responses when the
server provides token usage. Native benchmark results are stored separately.
Context length and loaded state come from the model API. Missing GPU, RAM or
other hardware statistics are not estimated. Small context windows and models
without tool support may be unsuitable for coding-agent workloads.

Claude Code started against a local model receives a compact tool set (shell,
files, search, questions and plan mode) instead of roughly 30k tokens of
Anthropic-only tool schemas on every request. Its auto-compact window is the
context length LM Studio reports for the loaded model at launch, or the value
from the last profile check when the server does not answer. Reload the model
with a different context length, then restart the session to apply it.

Profiles and keys live in `~/.config/cc-panel/integrations/lmstudio.json` (0600).
`model-bindings.json` stores private session bindings and `model-relay.json` stores
loopback relay credentials. A local authenticated relay forwards requests to the
pinned server and records timing/usage only; it does not store conversation text.
An in-progress local-model request may need retrying when the panel service updates.

### Multiple Agent Deck instances

Use **Settings → Network → Other Agent Deck instances** on the server whose
web address you normally open. Click **Discover** to search online Tailscale peers
on port 8790 (or a custom port), or enter a remote `http://100.x.y.z:8790` URL.
Provide that instance's panel login and password, then connect. Select the instance
in the sidebar (the switcher appears once an instance is connected), or tap any of its
sessions: the sidebar lists the sessions of every connected computer under its name, so
switching environments is one tap and happens in place, without reloading the page. Manage its sessions, files, models and live terminal through the
gateway. Your browser does not need direct access to the remote Tailscale address.
The gateway and remote computer must both be connected to the tailnet.

Credentials remain in a private file on the gateway. Existing remote Agent Deck
1.0.7 instances can be connected; only the gateway needs the new UI. Connection
settings always belong to the gateway; session and project settings belong to the
currently selected instance. Switching preserves separate drafts on each machine.

**Network and panel address** shows the listening address and browser address and
lets you name the gateway and record its public URL. Recording a URL does not
create DNS records, provision HTTPS or change the reverse proxy. Public hosting
is configured using the installer's `PUBLIC_DOMAIN` and proxy options.

New installs use `~/dev`. Existing explicit project directories are retained;
older default `~/projects` settings pick up `~/dev` when that directory exists.

### Kimi Code

Open **Settings → Models → Kimi → Configure**. Save a Kimi Code API key
and choose a model. Create a session with **Claude Code** and a **Kimi** model source (the Anthropic-compatible endpoint), or choose **Kimi Code** for the native CLI. Install Claude or Kimi
under **Settings → Agents** if needed. An existing `~/.config/cc-kimi/env` key is detected automatically.
Claude through Kimi uses the compact tool set described for local models plus
subagents, web fetch and skills, and compacts at the model's real window (1M for K3).

The key stays on the server in a private file; API responses and tmux commands do not contain it.
Leaving the password field empty preserves the key; **Remove key** removes it from the panel.
The model setting is the default for new native Kimi sessions; existing sessions keep their selected model. Key changes apply on the next agent launch. Native sessions/configuration use
`~/.config/cc-panel/kimi-native/`, preserving the user's independent Kimi configuration.

Kimi quota cards show the account’s returned monthly total/coding and short-period limits,
with reset dates. Monthly windows do not assume a fixed 30-day duration for pace forecasts.

Installed Agent Deck panels automatically check stable releases every 30 minutes.
Disable this in **Settings → App → Automatically update Agent Deck** if desired.
**Check for updates** bypasses the cached release check. Updates preserve tmux
sessions, wait for active local-model requests, and roll back after a failed health check.
Development git checkouts remain excluded. Existing versions need one update to
1.2.0 or later to enable the background updater.
