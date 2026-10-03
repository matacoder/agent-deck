# Agent Deck

Run [Claude Code](https://claude.com/claude-code), [Codex](https://github.com/openai/codex) and plain
terminals on your own server and use them from any browser — desktop or phone. Every session lives in
tmux, so it keeps working when you close the tab and comes back after a reboot.

![Agent Deck on desktop](docs/screenshots/desktop.png)

| Session on a phone | Sessions & limits | New session from GitHub |
|:---:|:---:|:---:|
| <img src="docs/screenshots/mobile-screen.png" width="260" alt="Phone: session screen"> | <img src="docs/screenshots/mobile-sessions.png" width="260" alt="Phone: session list"> | <img src="docs/screenshots/mobile-new.png" width="260" alt="Phone: new session"> |

<sub>Screenshots use demo data.</sub>

## Features

- Tabs for all your sessions, grouped by project, with live terminals and "working / waiting / done" status.
- Claude Code, Codex, Claude through Kimi, native Kimi Code or a plain terminal per tab; restart an agent keeping the conversation.
- Pick a GitHub repo and start working; optional git worktree per session (one branch per agent).
- Weekly Claude / Codex subscription limits with a pace forecast.
- Phone friendly: home-screen app, message box, quick keys for agent prompts, image attachments.
- Survives disconnects and reboots; one-click install and login for Claude and Codex.

## Install

On a fresh **Ubuntu 22.04 / 24.04** server:

```bash
curl -fsSL https://raw.githubusercontent.com/matacoder/agent-deck/main/get.sh | sudo bash
```

It sets everything up and prints the panel address and password. By default the panel is private:
reachable only from your devices over [Tailscale](https://tailscale.com) (the installer will ask you to
log in to it, or pass `TS_AUTHKEY=tskey-...`).

Then:

1. Open the printed address and log in.
2. In the sidebar, click **Log in** next to Claude and/or Codex, and **Connect** next to GitHub.
3. On a phone: Share → *Add to Home Screen*.

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

## Security

The panel gives a shell to whoever logs in (as an unprivileged user without sudo; its Docker is
rootless). Keep the password private, and prefer the default Tailscale-only setup unless you need public
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
