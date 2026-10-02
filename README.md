# Claude Sessions

A tiny self-hosted "iTerm2 in the browser" for running many [Claude Code](https://claude.com/claude-code)
sessions on a remote Linux box: vertical tabs on the left, a live terminal on the right, a phone-friendly
view with a message box, and sessions that survive browser disconnects **and server reboots**.

Everything is reachable only over [Tailscale](https://tailscale.com); nothing listens on a public interface.

## Features

- **Tabs for tmux sessions**, grouped by project, with search and status: Claude working (pulsing),
  waiting for you, or not running. A blue dot marks background tabs that just finished.
- **Live terminal** (xterm.js via ttyd) per tab; switching tabs is instant. `⌥1…9`, `⌥↑/↓`, `⌥T`.
- **Restart Claude** keeping the conversation (`--resume <id>`) or with a fresh one.
- **Persistence**: sessions (folder, conversation id, permission mode) are saved every 5 s and recreated
  with `claude --resume` after a reboot or a tmux crash. A Claude `SessionStart` hook keeps the id
  current across `/clear` and `/resume`.
- **GitHub**: one-click device login (`gh`), repo picker with search, clone into `~/projects`,
  optional **git worktree per session** (many Claudes on one repo, one branch each).
- **Mobile**: installable to the home screen (icon + manifest), session screen with clickable links,
  message box and keys `1 2 3 Esc ↑ ↓ ⏎ ⇧Tab ^C` for answering Claude prompts.
- **Login form** with password-manager support; signed HttpOnly cookie, 90 days.

## Install (clean Ubuntu 22.04 / 24.04)

```bash
gh repo clone matacoder/tmux && cd tmux     # or git clone
sudo ./install.sh
```

The script is idempotent: run it again after `git pull` to upgrade. It never restarts the tmux
server, so running sessions are not interrupted.

| Variable      | Default            | Meaning                                                        |
|---------------|--------------------|----------------------------------------------------------------|
| `DEV_USER`    | `dev`              | Unprivileged user that owns tmux, Claude and the panel         |
| `DEV_UID`     | `2600`             | UID for a new user (avoid 999/1000: container processes)       |
| `BIND_HOST`   | Tailscale IPv4     | Address the panel listens on                                   |
| `PANEL_PORT`  | `8790`             |                                                                |
| `TS_AUTHKEY`  | —                  | Join the tailnet non-interactively                             |
| `WITH_DOCKER` | `1`                | Rootless Docker for the user (isolated from any root Docker)   |
| `MEM_MAX`     | —                  | e.g. `8G`: memory cap for everything the user runs             |
| `CPU_QUOTA`   | —                  | e.g. `200%`: CPU cap (two cores)                               |

After install:

1. Open `http://<tailscale-ip>:8790`, log in (password is printed once; later:
   `grep PANEL_PASSWORD ~dev/.config/cc-panel/env`).
2. Create a session and run `/login` inside Claude once (subscription or API key).
3. Click **Connect GitHub** in the sidebar.
4. On a phone: Share → *Add to Home Screen*.

## How it works

```
browser ──tailscale──> panel.py (BIND_HOST:8790, login cookie)
                         ├─ /api/*   tmux commands, state, GitHub (gh)
                         └─ /t/*     raw proxy ──> ttyd (unix socket, user-only) ──> tmux attach -t cc-<name>
systemd --user (linger):  cc-tmux  (owns the tmux server: restarts of the panel never kill sessions)
                          cc-ttyd
                          cc-panel (KillMode=process)
```

- tmux sessions are named `cc-<name>`; options `@cc_sid` (Claude conversation id) and `@cc_skip`
  (`--dangerously-skip-permissions`) live on the session.
- State: `~/.config/cc-panel/sessions.json`. If the tmux server PID changes, missing sessions are recreated.
- Files: code in `/opt/cc-panel`, config in `~/.config/cc-panel/`, units in `~/.config/systemd/user/`.

## Security model

- The panel is a **web terminal**: whoever logs in gets a shell as `DEV_USER`. It binds only to the
  Tailscale address; restrict the port further with Tailscale ACLs.
- `DEV_USER` has no sudo and is not in the `docker` group; its Docker is rootless and cannot see
  root containers. Use `MEM_MAX` / `CPU_QUOTA` on shared machines.
- ttyd listens on a unix socket in `/run/user/<uid>` (mode 700), so other local users cannot reach it.
- `gh` login grants access to all your repositories. For tighter scope, log in with a fine-grained
  token instead: `gh auth login --with-token`.

## Useful commands

```bash
sudo -u dev tmux ls                                   # sessions
sudo -u dev tmux attach -t cc-<name>                  # attach over SSH
sudo -u dev XDG_RUNTIME_DIR=/run/user/$(id -u dev) systemctl --user status cc-panel cc-ttyd cc-tmux
sudo journalctl _UID=$(id -u dev) -f                  # logs
python3 panel/make_icons.py                           # re-render icons
```
