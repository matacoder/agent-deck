# Changelog

Versions follow [semver](https://semver.org). Install a version with `sudo ./update.sh vX.Y.Z`.

## 0.1.0 — 2026-10-02

First public release.

- iTerm2-style web UI for tmux sessions: vertical tabs grouped by project, live terminals (ttyd),
  status and "finished" indicators, hotkeys.
- Session types: Claude Code, Codex CLI, plain terminal; "terminal here"; restart keeping the
  conversation or fresh; git worktree per session; GitHub repo picker (device login via `gh`).
- One-click install / update / login for Claude Code and Codex (official installers).
- Weekly subscription limits for Claude and Codex with pace (norm marker, surplus/overspend, forecast).
- Sessions persisted and restored after a reboot or tmux crash.
- Phone: home-screen app, session screen with ANSI colors, message box, quick keys, image attachments.
- Login form with signed cookie; rootless Docker and resource limits for the panel user.
- `install.sh` for a clean Ubuntu 22.04/24.04 (Tailscale, Docker, agents); `deploy.sh` without root;
  optional public HTTPS via Dokploy's Traefik or Caddy with automatic Let's Encrypt.
- Versioning: `panel/VERSION`, update notice in the panel, `update.sh`, `release.sh`.
