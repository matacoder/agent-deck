# Changelog

Versions follow [semver](https://semver.org). Install a version with `sudo ./update.sh vX.Y.Z` (older than the installed one: `sudo FORCE_DOWNGRADE=1 ./update.sh vX.Y.Z`).

## 1.2.3 — 2026-10-05

- Show the running agent and model, remaining quota, today's plan and reset time under the message field for Claude, Codex and Kimi sessions; the model follows `/model` switches from the conversation transcript.
- Mobile key row fills the screen width and moves keys that do not fit behind "…" instead of always hiding all secondary keys.

## 1.2.2 — 2026-10-05

- Claude Code on LM Studio and Kimi starts with a compact tool set instead of ~30k tokens of Anthropic-only tool schemas per request; questions and plan mode keep working.
- Local sessions auto-compact at the context length LM Studio loaded for the model (last profile check as fallback); Claude through Kimi uses the model's real window instead of an assumed 200k.
- Tool search stays off for third-party endpoints even when the user's Claude settings enable it.

## 1.2.1 — 2026-10-05

- Fix automatic-update switch sizing: full-width field styles exclude checkboxes and radios; toggle labels retain readable width.

## 1.2.0 — 2026-10-05

- Enable automatic stable-release updates for installed Linux/macOS panels with a settings toggle, 30-minute checks, single-flight installation and rollback.
- Add an explicit update check that bypasses the release cache; show check failures instead of silently hiding available updates.
- Wait for active local model requests before update installation.
- Restart agents in an interactive shell so tmux reports the foreground Claude/Pi process correctly and local sessions accept screen messages after restart.

## 1.1.4 — 2026-10-05

- Open links to the current panel through the browser origin instead of its internal address; panel login links reuse the existing authenticated interface.

- Show the shared message composer and attachments in live terminal mode without losing drafts while switching views.
- Add a mobile-friendly terminal reconnect button that reconnects ttyd without restarting the session.
- Fix closed-session draft action layout and clipboard fallback inside modal dialogs; show an empty-list state.

## 1.1.3 — 2026-10-05

- Security: proxied connected-deck `/api/*` responses must be JSON; all responses send `X-Content-Type-Options: nosniff`; requests with `Transfer-Encoding`, invalid `Content-Length` or unread bodies close the connection instead of being parsed as a second request.
- Connected decks: http:// URLs only (Tailscale already encrypts; https never worked), one login per deck under parallel requests, no HTTP error written into an upgraded WebSocket. A broken `decks.json` disables connections instead of stopping the panel.
- Session titles set by rename are shown again; a malformed foreign cookie no longer causes a login loop; symlinked upload folders are rejected.
- Telegram: a failing update no longer blocks polling; an identical question that returns after being answered is sent again; a corrupt `telegram.json` can be reset from the UI.
- Corrupt project/network settings fall back to defaults instead of crash-looping the panel; the model relay picks a new port if the saved one is busy; hook registration keeps symlinked `settings.json` and its mode.
- Updater: rollback always restores files and restarts the panel, `VERSION` is replaced last, leftover `.update-*` folders are removed.
- Installer: Tailscale auth key is no longer passed on the command line; `get.sh` cannot run a partial download; options are saved before installation starts; a foreign group owning the default GID is not adopted; re-running the installer refuses to downgrade a newer self-updated panel unless `FORCE_DOWNGRADE=1`; `deploy.sh` backs up `~/.tmux.conf`.
- UI: drafts survive logout and browser reloads; ⌥+digit keeps typing brackets on non-US Mac layouts; hidden tabs stop polling; open model details and running benchmarks are no longer reset by refreshes; a new session is selected reliably; malformed URL hashes or blocked storage no longer break the app.

## 1.1.2 — 2026-10-05

- Show the shared session key toolbar in live terminal mode, preserve terminal focus on button presses, and retain mobile expanded-key controls.

## 1.1.1 — 2026-10-05

- Preserve project groups for existing sessions in ~/projects while using ~/dev as the new default, including worktrees.

- Fetch current LM Studio model catalogs when opening settings or creating sessions, refresh visible model settings every 30 seconds, and provide a manual refresh button.

- Group remote connection actions into styled buttons with mobile spacing.
- Separate discovery names, addresses and connect buttons; match the port field to the dark settings theme.

## 1.1.0 — 2026-10-05

- Connect other Agent Deck instances by Tailscale URL and their own login/password;
  discover online instances on known tailnet peers and switch from the sidebar.
- Proxy remote API operations, file uploads and live terminal WebSockets through
  the gateway, without requiring browser access to the remote tailnet address.
- Keep per-instance sessions, drafts, attachments and display preferences separate;
  retain remote credentials only in private server-side storage.
- Add gateway name, public address and effective listening-address settings.
- Default new installs to `~/dev`; detect an existing `~/dev` for older default
  `~/projects` settings while retaining explicitly saved custom directories.
- Add Python/Jest unit coverage for gateway authorization, remote authentication,
  terminal routing, tailnet-only discovery and cross-instance draft isolation.

## 1.0.7 — 2026-10-05

- Automatically bind the macOS panel to its own connected Tailscale IPv4 address,
  including when reinstalling an older localhost-only installation.
- Detect both command-line and application-bundled Tailscale clients, fall back to
  localhost when unavailable, and preserve explicit bind addresses and credentials.
- Add a saved `--projects-dir` installation option, forwarded by the bootstrap,
  so directories such as `~/dev` can be selected without editing configuration.
- Change the project directory from Application settings, with immediate use for new
  sessions and persistence across panel restarts and macOS reinstalls.
- Keep mobile connection-name fields at a readable size and constrain settings
  to the visible keyboard viewport. Add numeric suffixes to duplicate connection
  and session names, and rename session labels without interrupting conversations.
- Replace browser end-to-end and installation smoke jobs with Python unit tests
  and Jest frontend unit tests.
- Rerun the macOS installer to apply this network setting; panel-only updates do
  not rewrite launchd configuration.

## 1.0.6 — 2026-10-04

- Restart agents in a fresh tmux pane so terminal mouse reports and queued input
  cannot corrupt the launch command, including Codex's `--no-alt-screen` flag.
- Unify interface icon sizes and use SVG marks for session and settings controls.
- Separate panel HTML, CSS and JavaScript sources and build the compatible single-file
  release bundle; verify generated output in CI.

## 1.0.5 — 2026-10-04

- Add Pi coding harness with local LM Studio models, isolated configuration and exact conversation restoration.
- Show compact quota remaining and end-of-day plan, with monthly Kimi calculation and pacing colours.
- Show local generation activity and speed beside the composer; shorten model names and improve provider icons.
- Prevent input into a stopped local agent and preserve drafts when refreshing the interface.
- Fix application settings layout, update status and refresh controls; use a readable 22 px settings icon.

## 1.0.4 — 2026-10-04

- Show live local-model request activity: first-token waiting time, reasoning,
  tool-call generation, streamed fragment counts and available token statistics.
  Retain measurements of the last completed response while a new request runs.
- Read relay measurements across panel processes and expire stale activity without
  storing conversation text or treating stream fragments as tokens.
- Label local sessions with their model and computer instead of Claude, use a
  monitor icon, and enlarge session and quota-chip provider marks.
- Add regressions for stream phases, cross-process metrics and local session identity.

## 1.0.3 — 2026-10-03

- Identify Claude sessions backed by local models in the sidebar, header and
  message status, including the connection name in the sidebar. Translate the
  local-model label into all supported locales.
- Allow up to ten minutes between upstream events for local inference rather
  than truncating streams after two minutes. Report interrupted SSE streams
  explicitly instead of silently closing them.
- Add mobile identity and stalled-stream regression coverage.

## 1.0.2 — 2026-10-03

- Fix LM Studio 500 errors with strict model templates when Claude Code sends
  mid-conversation system messages. Preserve their instructions in the initial
  system prompt while keeping ordinary messages and tool calls unchanged.
- Add regression coverage and verify the failing request against a real local model.

## 1.0.1 — 2026-10-03

- Redesign the drawer usage monitor with aligned headings, compact metrics and
  expandable long model names instead of multi-line blocks.
- Unify modal spacing, controls and card actions; use a sidebar for desktop settings
  and a compact navigation strip on phones.
- Keep mobile modal headers fixed while content scrolls, and correct inherited
  dialog dimensions on inline integration forms.
- Refresh public demo screenshots and verify narrow-phone layouts across locales.

## 1.0.0 — 2026-10-03

- Unify desktop and mobile settings into Agents, Models, Connections and Application.
  Move setup/key forms out of the sidebar; keep subscription quota monitoring there.
- Select the coding runtime and model source separately. Keep existing Claude/Kimi
  sessions compatible and pin each new source/model across restarts and recovery.
- Add LM Studio profiles, manual URL/key configuration, custom ports and cancellable
  discovery restricted to known Tailscale peers. Check models and tool support explicitly.
- Measure real local-session speed and TTFT through an authenticated loopback relay;
  store native synthetic benchmarks separately. Do not store relay conversation text
  or invent subscription quotas/hardware metrics for local models.
- Keep model keys out of browser responses and launch commands; protect private files,
  verify the relay before sending its token and prevent accidental provider fallback.
- Translate new controls in all 16 locales and update public demo screenshots/docs.

## 0.9.2 — 2026-10-03

- Start and resume Codex with `--no-alt-screen` so new terminal output enters tmux
  scrollback instead of being lost when the alternate screen redraws. Running agents
  are not restarted; the change takes effect on their next normal start/resume.
- Expand screen capture from 200 to 2000 lines. This does not recover terminal text
  already discarded; older conversations remain in agent transcripts.

## 0.9.1 — 2026-10-03

- Move sign out from the sidebar footer into a separate account section in Settings
  to avoid accidental taps beside the settings button on phones.

## 0.9.0 — 2026-10-03

- Add complete interface catalogs for Spanish, Brazilian Portuguese, German, French,
  Simplified Chinese, Japanese, Korean, Indonesian, Turkish, Italian, Polish,
  Ukrainian, Hindi and Traditional Chinese — 16 languages including English/Russian.
- Translate interface controls, login, errors, usage hints, Telegram confirmations
  and attachment notices; preserve terminal output and user messages.
- Discover every language automatically in Settings and support `PANEL_LANGUAGE`
  during installation. Keep existing browser/server preferences.
- Validate complete catalogs, placeholders, CLI flags and concatenation whitespace;
  exercise all new languages at 320 px in Chromium and mobile WebKit.

## 0.8.0 — 2026-10-03

- Add English and Russian interface catalogs, browser-specific language selection in Settings,
  localized login/errors/usage/Telegram acknowledgments and language-aware dates.
- Default fresh installations to English; allow `PANEL_LANGUAGE=ru` at installation.
  Support additional JSON catalogs with English fallback and validated placeholders.
- Preserve unsent drafts, attachments, active session and view when switching languages.
  Package locales for Linux, macOS and safe in-panel updates.
- Recognize Codex's queued follow-up input form and its `enter submit` footer,
  fixing Telegram answers that previously failed to open the question in Codex CLI 0.160.
- Preserve Telegram answer buttons when opening a pending question temporarily fails;
  never navigate blindly between unrelated forms or retry uncertain terminal input.
- Polish Telegram setup with a compact card, connection indicator, delivery switch,
  collapsed token controls and a compact mobile dialog.
- Document one-time administrator pairing, private JSON/SQLite storage and the verified
  Telegram-to-Codex reply flow. Add native-form and retry regression coverage.
- Refresh desktop/mobile screenshots and repository documentation for macOS, Kimi,
  Telegram replies, file attachments and host resource indicators.

## 0.7.0 — 2026-10-03

- Add an Integrations section with Telegram bot configuration, expiring private-chat
  pairing, delivery pause and token removal. Keep tokens private on the server.
- Forward pending structured Codex and Claude questions, plus recognized active
  terminal questions, with answer buttons. Validate the owner, message, session,
  pane, conversation and current question before selecting and confirming an answer.
- Persist delivery and answer claims in a private SQLite outbox; prevent repeated
  terminal input and remove stale buttons. Do not replay uncertain answers after crashes.
- Separate agent adapters, durable state and Telegram transport from panel HTTP/UI.
  Install the integration package on Linux and Mac and support package repair after
  updates made by legacy core-only updaters.
- Verify real tmux answer delivery, authorization, stale/repeated callbacks,
  restart recovery and mobile Chromium/WebKit setup.

## 0.6.0 — 2026-10-03

- Keep Codex question navigation, arrow keys and answer confirmation visible on phones;
  put secondary keys in an expandable row and make the hide-keyboard button compact.
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
