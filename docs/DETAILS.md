# Agent Deck — details

Everything the [README](../README.md) leaves out: how it works, all install options, publishing,
troubleshooting and development.

## How it works

```
browser ──tailscale──> panel.py (BIND_HOST:8790, login cookie)
                         ├─ /api/*   tmux commands, state, GitHub (gh), limits, version
                         └─ /t/*     raw proxy ──> ttyd (unix socket, user-only) ──> tmux attach -t cc-<name>
systemd --user (linger):  cc-tmux  (owns the tmux server: restarts of the panel never kill sessions)
                          cc-ttyd
                          cc-panel (KillMode=process)
```

- tmux sessions are named `cc-<name>`; options `@cc_agent` (claude|codex|shell), `@cc_sid` (Claude
  conversation id) and `@cc_skip` (skip-permissions / bypass-approvals) live on the session.
- Persistence: sessions are saved to `~/.config/cc-panel/sessions.json` every 5 s. If the tmux server PID
  changes (reboot, crash), missing sessions are recreated and agents resumed (`claude --resume <id>`,
  `codex resume --last`). A Claude `SessionStart` hook keeps the id current across `/clear` and `/resume`.
- Files: code in `/opt/cc-panel`, config in `~/.config/cc-panel/` (`env` holds the password),
  user units in `~/.config/systemd/user/`, install options in `/etc/agent-deck/install.conf`.
- Interface updates: the page checks for a new UI every 30 s and when it returns from the background and
  reloads when idle (no draft or attachments); the mobile action menu has **Обновить интерфейс**, which keeps
  the draft and uploaded attachments.
- Image attachments: up to four images, 8 MB each; uploads stay on the server, Codex receives them in its
  current conversation.
- Hotkeys (desktop): `⌥1…9` switch tabs, `⌥↑/↓` previous / next, `⌥T` new session.

## Install options

`install.sh` (run directly or through `get.sh` / `update.sh`) reads these from the environment. They are
remembered in `/etc/agent-deck/install.conf`, so later runs keep them unless overridden.

| Variable | Default | Meaning |
|---|---|---|
| `DEV_USER` | `dev` | Unprivileged user that owns tmux, the agents and the panel |
| `DEV_UID` | `2600` | UID for a new user (avoid 999/1000: often used by container processes) |
| `BIND_HOST` | Tailscale IPv4 | Address the panel listens on (never `0.0.0.0`) |
| `PANEL_PORT` | `8790` | |
| `TS_AUTHKEY` | — | Join the tailnet non-interactively |
| `WITH_DOCKER` | `1` | Rootless Docker for the user (isolated from any root Docker) |
| `WITH_CODEX` | `1` | Codex CLI via its official installer |
| `MEM_MAX` / `CPU_QUOTA` | — | systemd limits for everything the user runs, e.g. `8G` / `200%` |
| `PUBLIC_DOMAIN` | — | Also publish at `https://<domain>` with Let's Encrypt |
| `PUBLIC_PROXY` | `auto` | `traefik` (Dokploy present) or `caddy` (plain VPS) |
| `TRAEFIK_DYNAMIC` | `/etc/dokploy/traefik/dynamic` | Traefik file-provider directory |

`get.sh` additionally honours `AGENT_DECK_DIR` (default `/opt/agent-deck`) and `AGENT_DECK_REPO`.

Manual install from a checkout: `git clone https://github.com/matacoder/agent-deck && cd agent-deck && sudo ./install.sh`.

## Public HTTPS

The panel itself always listens only on the Tailscale IP; a reverse proxy on the same host terminates TLS.

- **Dokploy / Traefik** (`PUBLIC_PROXY=traefik`): [`deploy/traefik-dokploy.yml`](../deploy/traefik-dokploy.yml)
  is rendered to `/etc/dokploy/traefik/dynamic/cc-panel.yml`. Traefik picks it up immediately, gets the
  certificate via HTTP-01 on the first request and renews it ~30 days before expiry.
- **Plain VPS / Caddy** (`PUBLIC_PROXY=caddy`): Caddy is installed from its official apt repository and
  [`deploy/Caddyfile.cc-panel`](../deploy/Caddyfile.cc-panel) goes to `/etc/caddy/sites/cc-panel.caddy`
  (imported from `/etc/caddy/Caddyfile`; the package's default site is replaced, other config is kept).
  The installer refuses to run if another process listens on 80/443 and opens them in `ufw` if it is active.

Behind the proxy the panel takes the client IP from `X-Forwarded-For` (only from private-network proxies or
a proxy on the same host), so the login rate limit stays per client, and sets the cookie `Secure` on HTTPS.

### Troubleshooting certificates

If the certificate was requested before the DNS record existed, the log shows `acme: error ... NXDOMAIN`
and resolvers cache that answer for the zone's SOA minimum (`dig SOA <zone>`, often 5–15 min). Wait, then
retry:

- Traefik ignores edits that don't change the parsed config (a comment is not enough) and doesn't retry on
  its own. Remove and re-add the file (no Traefik restart needed):
  `cd /etc/dokploy/traefik/dynamic && mv cc-panel.yml /tmp/ && sleep 3 && mv /tmp/cc-panel.yml .`
- Caddy retries by itself with backoff, or `systemctl reload caddy`.

Check: `docker logs dokploy-traefik 2>&1 | grep <domain>` / `journalctl -u caddy | grep <domain>`, and
`echo | openssl s_client -connect <domain>:443 -servername <domain> | openssl x509 -noout -issuer -enddate`.

## Security model

- The panel is a web terminal: whoever logs in gets a shell as `DEV_USER`. Login form, signed HttpOnly
  cookie (90 days), 5 failed attempts per client → 1 min pause. Changing `PANEL_PASSWORD` in
  `~/.config/cc-panel/env` logs out every browser.
- `DEV_USER` has no sudo and is not in the `docker` group; its Docker is rootless and cannot see root
  containers. Use `MEM_MAX` / `CPU_QUOTA` on shared machines.
- ttyd listens on a unix socket in `/run/user/<uid>` (mode 700), so other local users cannot reach it.
- `gh` device login grants access to all your repositories; for tighter scope log in with a fine-grained
  token: `gh auth login --with-token`.
- Public access: consider a Traefik `ipAllowList` middleware or SSO forward-auth in front of the panel.

## Subscription limits

The weekly limits come from the same places the agents use for `/usage` (Claude Code) and `/status`
(Codex): `api.anthropic.com/api/oauth/usage` and `chatgpt.com/backend-api/wham/usage`, called with the
agents' own tokens from `~/.claude/.credentials.json` and `~/.codex/auth.json`. These endpoints are **not
documented** and may change; the panel then shows "no data". Tokens are only read, never refreshed (the
agents rotate refresh tokens; a second refresher would log them out), and never sent anywhere else.

The pace line compares the share of the limit used with the share of the week elapsed (the marker on the
bar) and extrapolates linearly to the reset.

## Updates and releases

- The panel checks the latest GitHub release every 6 h (`UPDATE_REPO=` in `~/.config/cc-panel/env`
  disables it) and shows **↑ vX.Y.Z** with the update command.
- `sudo ./update.sh` checks out the latest tag (or `./update.sh v0.2.0`, `./update.sh main`) and re-runs
  `install.sh` with the remembered options. It refuses to run with local changes in the checkout.
- Releasing (maintainers): add a `## X.Y.Z` section to [CHANGELOG.md](../CHANGELOG.md), then
  `./release.sh X.Y.Z` — bumps `panel/VERSION`, tags, pushes and creates the GitHub release.

## Development

- Day-to-day changes need no root: as the panel user (e.g. from a terminal session in the panel) run
  `./deploy.sh` in your checkout. It copies `panel/` to `/opt/cc-panel`, refreshes units / `tmux.conf` /
  the Claude hook and restarts the panel and ttyd; the tmux server and sessions keep running.
- Root (`sudo ./install.sh`) is only needed for system-level changes: packages, users, Traefik / Caddy.
- `python3 panel/make_icons.py` re-renders the app icons.

## Useful commands

```bash
sudo -u dev tmux ls                                   # sessions
sudo -u dev tmux attach -t cc-<name>                  # attach over SSH
sudo -u dev XDG_RUNTIME_DIR=/run/user/$(id -u dev) systemctl --user status cc-panel cc-ttyd cc-tmux
sudo journalctl _UID=$(id -u dev) -f                  # logs
grep PANEL_PASSWORD ~dev/.config/cc-panel/env         # panel password
```
