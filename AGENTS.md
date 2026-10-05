# AGENTS.md — Agent Deck

Instructions for AI agents (Claude, Codex, Kimi, pi, etc.) working in this repository.

## 1. What this is

Agent Deck is a self-hosted web panel (Python + static frontend) that manages
tmux sessions running Claude Code / Codex / Kimi / a plain shell. It also ships:
- a Telegram bot for answering agent questions,
- an LM Studio connector, GitHub integration, i18n in 16 languages,
- installers for Linux (systemd) and macOS (launchd).

**This is production code running on other people's servers and in their home
directories. Any bug in the installer, the proxy, or the secret store is an incident.**

## 2. Architecture — short reference

```
browser ──tailscale──> panel.py (BIND_HOST:8790, signed cookie)
                         ├─ /api/*   tmux, state, GitHub (gh), limits, version
                         └─ /t/*     raw proxy → ttyd (unix socket) → tmux attach -t cc-<name>
systemd --user:  cc-tmux (owns the tmux server) / cc-ttyd / cc-panel (KillMode=process)
```

Key files (don't read everything — only what you're touching):

| File | Purpose |
|---|---|
| `panel/panel.py` | Entire HTTP backend: login, ttyd proxy, tmux commands, uploads, limits. **~1600 lines; don't refactor without a reason.** |
| `panel/updater.py` | Single-flight update job, release validation, rollback after failed startup |
| `panel/session_hook.py` | SessionStart hook: records the top-level conversation ID (Claude/Codex) |
| `claude/register-hooks.py`, `claude/cc-session-hook.py` | Claude hook registration. **Nested review agents must not overwrite `@cc_sid`.** |
| `integrations/telegram.py` | Long-polling, pairing, callback validation. **Never deletes foreign webhooks.** |
| `integrations/questions.py` | Question normalization (question + options only, no history) |
| `integrations/store.py` | SQLite outbox: claim-before-input, uncertain state, 7-day TTL |
| `integrations/lmstudio.py`, `relay.py` | LM Studio profiles + loopback relay (timing/usage only, no conversation text) |
| `locales/*.json` | 16 catalogs. New language = one JSON + a row in `docs/localization.md` |
| `install.sh`, `get.sh`, `update.sh`, `deploy.sh` | Installers. **Root entrypoints** — see §5 |
| `frontend/*`, `panel/index.html` | Static UI. Localization via `locales/`, no hardcoded strings in HTML |
| `tests/backend/`, `tests/frontend/` | Regression. **Always run** (§4) |

tmux sessions: name `cc-<name>`, options `@cc_agent` (claude\|codex\|shell),
`@cc_sid` (conversation id), `@cc_skip` (skip-permissions). Persistence:
`~/.config/cc-panel/sessions.json`.

## 3. Code rules

### 3.1. Python
- 3.10+, **no runtime third-party dependencies** (stdlib + `tmux` + `gh` only).
- Do not add `requests`, `aiohttp`, `pydantic`, etc. — use `urllib` from stdlib.
- No global mutable state without an explicit lock — the server is threaded (`ThreadingHTTPServer`).
- Secret files: `0600`; directories: `0700`. Never write tokens/passwords to logs, JSON responses, query strings, or tmux commands.
- All subprocess calls: `subprocess.run(..., input=<bytes>)` with an explicit `input`. Never `shell=True` with f-strings.
- Every `/api/*` response sets `Content-Type: application/json`. Errors are JSON 4xx/5xx, not tracebacks in the body.

### 3.2. Security (critical)
- **Signed cookies** — do not break the HMAC scheme. New endpoints go through the same `check_auth`.
- **Origin check** on every mutable JSON request and on the WebSocket upgrade. Sibling origins (same port, different host) **must be rejected**.
- **Login rate limit**: per-IP + global. Reserve a slot *before* reading the body, with a lock, so five delayed requests cannot create five slots.
- **`X-Forwarded-For` proxy header** — trusted only from private networks or the same host; otherwise client IP = socket peer.
- **Uploads**: ≤4 files, ≤200 MB each, 7-day TTL, per-minute cleanup. Symlinks inside the upload directory **must be rejected**.
- **`/t/*`** — unix-socket ttyd only, `-O` (no origin), raw bytes. Do not proxy over HTTP.
- **Telegram**: pairing is one-shot, 10-minute expiry, bound to `user_id` + `chat_id`. Replies only from the paired account. Callbacks are bound to owner + chat + message_id + session + conversation + question contents. On ambiguous delivery failure — **do not replay** (avoiding a duplicate is preferred to risking a double-send).
- **Input to tmux**: exact bytes, including leading dashes, semicolons, Unicode, and bracketed paste. Tests assert exact bytes.

### 3.3. Frontend (`panel/index.html`, `frontend/`)
- Vanilla HTML/CSS/JS, no bundler. Do not add npm runtime dependencies.
- **All UI strings go through `locales/<lang>.json`**. A new key must be added to **all 16** catalogs (`en` and `ru` are mandatory; other languages may fall back to `en`).
- Preserve draft + attachments across language switch, interface reload, and logout (login-page round-trip).
- Mobile-first: iPhone viewport, pinch-zoom guards, iOS keyboard. Do not break the desktop `⌥1…9` hotkeys.
- No blocking requests on hidden tabs (respect `visibilitychange`).

### 3.4. Installers and deployment
- `install.sh` is **root-only**; `get.sh` is the bootstrap. Root entrypoints **reject** user-owned / group-writable / symlinked source files.
- Do not change the layout: code in `/opt/agent-deck`, config in `~/.config/cc-panel/`, user units in `~/.config/systemd/user/`, install options in `/etc/agent-deck/install.conf`.
- `update.sh` updates the panel **without root**; single-flight job, release validation, health-check rollback.
- **Never delete** `~/.config/cc-panel/` on reinstall.
- `cc-panel` uses `KillMode=process` — do not change to `mixed`/`control-group`, that would kill tmux.
- macOS: launchd, **no sudo**. Do not break the user's `.tmux.conf`.

### 3.5. i18n
- New language: add `locales/<code>.json` + a row in `docs/localization.md` (+ optionally a mention in README).
- **Do not translate**: agent output, project names, message drafts, technical identifiers.
- Dates via `Intl` with the selected locale.
- Telegram bot: uses the language of the browser that last saved the integration settings.

## 4. Tests — required

**Before any commit:**

```bash
npm ci
python3 scripts/build-panel.py --check
npm run test:all
```

The active test suite is Python unit tests and Jest/jsdom frontend unit tests.
Do not add browser E2E or macOS installation smoke jobs. Legacy integration and
Playwright sources are retained for reference, excluded from normal tests and CI.
All settings and secrets in tests must stay in temporary directories. Mock external
commands and network calls. New endpoints and behavior require unit coverage.
CI checks Python 3.10/3.12 and Jest on Node 22.

## 5. Release / Changelog

- Versions follow semver. `panel/VERSION` is the single source of truth.
- Behavior changes → a line in `CHANGELOG.md` (Unreleased → version).
- Breaking changes to the installer, config layout, or API → **MAJOR** bump or an explicit `BREAKING` note in CHANGELOG.
- Never commit: `sessions.json`, `env`, `secret/`, `node_modules/`, `test-results/`, `playwright-report/`, `__pycache__/`.

## 6. Communication style

- Reply in the user's language (RU/EN).
- UI copy: neutral tone, no "clever" phrasing.
- Log and UI errors must be concrete: what failed, which file/line, how to fix it.
- Do not invent features beyond the task. If the task is "fix bug X", do not rewrite module Y.

## 7. Do **not** do (anti-patterns)

- ❌ Add npm runtime dependencies to the frontend.
- ❌ Change the signed-cookie scheme "because it's cleaner".
- ❌ Remove `KillMode=process` or ttyd's `-O`.
- ❌ Write tokens/passwords to logs, tmux commands, JSON responses, or query strings.
- ❌ Use `shell=True` with f-strings.
- ❌ Translate agent output.
- ❌ Replay uncertain Telegram answers.
- ❌ Break exact-bytes input into tmux (leading `-`, `;`, bracketed paste).
- ❌ Change the `~/.config/cc-panel/` layout without a MAJOR release + migration.
- ❌ Delete foreign tmux sessions, `.tmux.conf`, webhooks, or launchd plists.
- ❌ "Improve" `panel/panel.py` with refactors unrelated to the task.

## 8. When in doubt

1. Read `docs/DETAILS.md` — architecture and troubleshooting.
2. Read `docs/REVIEW-FIXES.md` — the last known bugs and their fixes.
3. Read `docs/integrations.md` for Telegram / LM Studio, `docs/localization.md` for i18n.
4. Look at `tests/backend/` — that is **how it should work**.
5. If still unclear — **ask the user**, don't guess.
