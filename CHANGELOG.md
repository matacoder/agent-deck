# Changelog

Versions follow [semver](https://semver.org). Install a version with `sudo ./update.sh vX.Y.Z`.

## 0.6.0 — 2026-10-03

- Install on macOS with one Terminal command, without sudo: Homebrew dependencies,
  Claude/Codex, private local panel, browser launch and LaunchAgent autostart.
- Keep a separate Agent Deck tmux server on Mac; preserve user tmux configuration,
  existing hooks, credentials, panel settings and sessions across reinstalls.
- Support macOS CPU/RAM metrics, process ancestry hooks, Homebrew agent discovery,
  Claude Keychain credentials and launchd-based panel updates.
- Fix Kimi five-hour quota reporting when legacy usage says zero but authoritative
  counters report exhaustion; show the actual used/limit and reset time.
- Handle tmux 3.7 control-byte sanitization while retaining older tmux compatibility.
- Add macOS integration coverage for installation, login, terminal WebSockets,
  shell input, metrics, detached updates and repeated installation.

## 0.5.1 — 2026-10-03

- Keep the composer hint and server metrics on one line on screens as narrow as 320 px.
- Shorten keyboard hints and show CPU/RAM icons with percentages; retain used/total RAM
  in the tooltip and accessible description.
- Verify compact layouts and keyboard hints in Chromium and mobile WebKit.

## 0.5.0 — 2026-10-03

- Show server CPU utilization and used/total RAM on the right of the composer status bar,
  refreshing every five seconds and wrapping cleanly on narrow screens.
- Fix live terminal connections through Traefik: recognize `X-Forwarded-Proto: wss` as
  secure when checking the HTTPS Origin, preventing erroneous WebSocket 403 responses.
  Forwarded headers remain restricted to trusted proxies and foreign origins are rejected.
- Add CPU/RAM calculation, unavailable-metrics, mobile/desktop layout, and secure
  WebSocket proxy regression coverage.

## 0.4.1 — 2026-10-03

- Fix the live terminal for browsers that omit the Origin header on same-origin WebSocket
  handshakes (Safari): the panel rejected them with 403, showing ttyd's "press Enter to
  reconnect". Foreign origins are still rejected, and ttyd's own -O re-checks origins.
- Clarify the desktop toolbar: the view toggle is now "Живой терминал / Экран", and the
  shell-session button reads "Новый терминал" instead of two near-identical "Терминал" labels.

## 0.4.0 — 2026-10-03

- Configure a shared Kimi Code API key and model in the sidebar; detect existing cc-kimi keys.
- Launch Claude Code through Kimi or the native Kimi Code CLI, install/update Kimi from the UI.
- Restore the exact native Kimi conversation with SessionStart hooks and keep credentials
  out of API responses, browser storage and tmux command history.
- Show actual Kimi monthly total/coding quotas, five-hour windows and reset times; only
  show legacy weekly limits when the account returns them.
- Compact quota cards with icon controls and expandable details; show Kimi CLI version
  and saved key status. Keep composer progress/success neutral and real errors red.
- Add backend credential/launch and mobile Chromium/WebKit regression coverage.

## 0.3.0 — 2026-10-03

- Attach arbitrary files, including ZIP archives, documents and text, up to 200 MB each.
  Keep native image attachments and pass other files to Claude/Codex as local paths.
- Run seven-day upload cleanup every minute and remind agents to save needed files in the project.
- Regression coverage for binary/empty files, safe filenames, limits, mixed attachments and refresh.

## 0.2.0 — 2026-10-02

- One-click panel updates from the latest stable GitHub release, without root, with progress,
  retry and rollback on failed startup. Running tmux sessions and ttyd stay running.
- Backend and Chromium/WebKit regression tests with GitHub Actions.
- Review fixes: protected root installer checkout and unprivileged user file writes; same-origin
  JSON mutations and WebSocket checks; bounded, synchronized login throttling and JSON errors.
- Literal tmux input through buffers, exact terminal targets and conversation-specific Claude/Codex
  resume IDs. Nested agent hooks no longer replace the primary conversation ID.
- Safe session fallback, recovery of closed-session drafts, and preservation of text and attachments
  across login expiry. Polling captures only the active session and pauses in hidden tabs.
- Upload cleanup, complete colored wrapped links, correct keyboard hints and stable pinch zoom.

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
