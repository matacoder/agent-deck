# AGENTS.md - Agent Deck

Self-hosted panel (Python stdlib + static JS) for tmux sessions running Claude Code/Codex/Kimi/shell; Telegram bot, LM Studio, GitHub, 16 locales, installers for Linux (systemd), macOS (launchd), Windows (WSL2). Runs on other people's machines: installer, proxy or secret-store bugs are incidents.

## Architecture
- Browser -> Tailscale -> `panel.py` (BIND_HOST:8790, signed cookie). `/api/*` JSON; `/t/*` raw proxy to ttyd (unix socket) -> `tmux attach -t cc-<name>`; `/deck/<id>/*` gateway to connected decks.
- User units: cc-tmux (owns tmux server), cc-ttyd, cc-panel (`KillMode=process`).
- tmux session `cc-<name>`, options `@cc_agent`, `@cc_sid`, `@cc_skip`; persisted in `~/.config/cc-panel/sessions.json`.

## Files (read only what you touch)
- `panel/panel.py`: HTTP backend (~2200 lines), no unrelated refactors.
- `panel/updater.py`: update job, release validation (syntax + imports), rollback. `PACKAGES` lists every `integrations/*.py`.
- `panel/session_hook.py`, `claude/*`: conversation-id hooks; nested agents must not overwrite `@cc_sid`.
- `integrations/git.py`: read-only history and diffs; grouping (subjects and file names only) by a chosen model: LM Studio (`reasoning_effort: none`), Kimi, or Haiku via `claude -p --tools ""` in an empty folder; never Codex.
- `integrations/files.py`: file browser; home only, never `~/.config/cc-panel`, atomic hash-checked saves.
- `integrations/`: `telegram.py` + `store.py` (claim-before-input outbox, never delete foreign webhooks), `questions.py`, `gateway.py` (parallel deck polling, `get_json`), `backups.py`, `usage.py`, `lmstudio.py`, `relay.py`, `push.py`/`webpush.py`, `images.py`, `dependencies.py`.
- `frontend/*` bundled into `panel/index.html` by `scripts/build-panel.py`; files before `app.js` must not call `$` at top level.
- `install-windows.ps1`: ASCII, PowerShell 5.1, never `exit`; tests in `tests/windows/`.
- `install-steamos.sh`: rootless Podman + systemd user unit from the same image (SteamOS wipes system packages).
- `docker/` + `docker-compose.yml`: one-container install (entrypoint supervises tmux, ttyd, panel); code is root-owned, updates come from a rebuilt image.
- ttyd command lines end options with `--` before `tmux attach -t` (the static build crashes otherwise).

## Python
- 3.10+ (CI 3.10 + 3.12, no 3.11-only APIs). Deps: stdlib, `tmux`, `gh`, and pinned `cryptography` only (wheels from `dependency_lock.py` via `dependencies.py`, never pip; regenerate with `scripts/lock-dependencies.py`; call `dependencies.require()`, degrade clearly). Use `urllib`.
- Never add files to `panel/` (installed updaters reject them); new code in `integrations/`.
- Threaded server: lock shared mutable state.
- Secrets: files 0600, dirs 0700; never in logs, JSON, URLs, tmux commands.
- `subprocess.run` with explicit `input`; no `shell=True`.
- `/api/*` errors: JSON 4xx/5xx, no tracebacks.

## Security
- Keep the signed-cookie HMAC scheme; new endpoints use the same auth.
- Origin check on all mutations and WebSocket upgrades; reject sibling origins.
- Login rate limit per IP + global; reserve slot under lock before reading body.
- Trust `X-Forwarded-For` only from private/same host; never inside a container (`AGENT_DECK_TRUSTED_PROXIES` to opt in).
- Root never writes into user-owned paths (`as_user` for every write under `$PREFIX`/home; open user files read-only).
- `/api/image`: path must be on the session screen; PNG/JPEG/WebP/GIF by content, max 25 MB, `nosniff` + `CSP: sandbox`; check content before thumbnails. Gateway passes non-JSON `/api/*` only for these.
- Uploads: max 4 files x 200 MB, 7-day TTL, reject symlinks; `/api/upload_raw` streams, JSON `/api/upload` kept for old gateways.
- `/t/*`: unix-socket ttyd, keep ttyd `-O`. `/deck/<id>/t/*` only to an authenticated deck on a numeric Tailscale IPv4; never forward gateway cookies.
- Isolated terminals (opt-in): `/deck/<id>/c/<signed>/t/*` with `CSP: sandbox` (no `allow-same-origin`); the signed path is the only credential there.
- Telegram: one-shot 10-min pairing bound to user+chat; owner-only replies; callbacks bound to owner/chat/message/session/question; never replay ambiguous deliveries.
- tmux input is exact bytes (leading `-`, `;`, Unicode, bracketed paste).
- Never delete foreign tmux sessions, `.tmux.conf`, webhooks, launchd plists.

## Frontend
- Vanilla JS/CSS, no bundler, no npm runtime deps.
- All UI strings via `locales/*.json`, new keys in all 16 (English value allowed). Don't translate agent output, project names, drafts, identifiers. Dates via `Intl`.
- Keep drafts, attachments, typed answers across language switch, reload, logout, computer switch.
- Mobile-first (iOS keyboard, inputs >= 16px); keep desktop Alt+1..9; no polling on hidden tabs.

## Installers
- `install.sh` root-only, rejects user-owned/group-writable/symlinked sources; `update.sh` without root.
- Fixed layout: `/opt/agent-deck`, `~/.config/cc-panel/` (never delete; changes need MAJOR + migration), `~/.config/systemd/user/`, `/etc/agent-deck/install.conf`.
- Keep `KillMode=process`. macOS: no sudo.

## Tests (before every commit)
`npm ci && python3 scripts/build-panel.py --check && npm run test:all`
Python unit + Jest/jsdom only, no browser E2E. Temp dirs for settings/secrets; mock commands and network; new behavior needs tests.

## Release
`panel/VERSION` is the source of truth (semver). Behavior change -> `CHANGELOG.md`; breaking installer/config/API -> MAJOR or `BREAKING`. Never commit `sessions.json`, `env`, `secret/`, `node_modules/`, `test-results/`, `playwright-report/`, `__pycache__/`.

## Style
Reply in the user's language. Neutral UI copy. Errors state what failed, where, how to fix. Stay in scope. Unsure: `docs/DETAILS.md`, `docs/REVIEW-FIXES.md`, `docs/integrations.md`, `docs/localization.md`, `tests/backend/`, then ask.
