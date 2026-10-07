# Changelog

Versions follow [semver](https://semver.org). Install a version with `sudo ./update.sh vX.Y.Z` (older than the installed one: `sudo FORCE_DOWNGRADE=1 ./update.sh vX.Y.Z`).

## 1.20.0 — 2026-10-07

- **Feature groups on any model:** Change history lets you pick who groups the commits — a model from your LM Studio profiles (marked "local, free"; runs with reasoning off, so 80 commits take about a minute and a half on a 27B model), Kimi (with a saved key) or Claude Haiku. The choice is remembered per computer, and each result says which model made it. Codex is not offered because it can run commands.
- A feature group's combined diff is read in one git call instead of one per commit (40 commits: from seconds to a quarter of a second).
- Security: logging out ends every isolated terminal link issued before, not only the session cookie.
- "Update all" in Network checks GitHub for a newer release when you open it instead of using an answer up to an hour old.
- Agent cards: a signed-in agent shows one quiet "Update" button instead of a blue one plus a duplicate; Kimi without a key says "Add key".
- The quota line under the input labels the plan value ("plan 40%") so the two percentages are not confused.
- Project files: the path is clickable — each folder on the way from home is one tap.
- Empty states: Waiting for you explains what will appear there; an empty session list has a "New session" button.

## 1.19.0 — 2026-10-07

Design polish from a review on iPhone, iPhone Duo (folded and unfolded), iPad (portrait, landscape, Split View) and desktop.

- **Touch follows the screen, not the width:** iPad and an unfolded iPhone Duo keep the wide layout but now get finger-sized controls, iOS keyboard handling, the Screen view by default, a key row that never wraps, and no sticky hover highlights or ⌥ hints without a keyboard. Dialogs and the menu no longer open with a focus ring after a tap.
- **Short screens** (a folded iPhone Duo): with a question pending the 1/2/3 keys hide (the card answers), the quota line steps aside for the terminal, and the Waiting for you tab is just its icon and count on narrow phones.
- **600–760 px** (an unfolded iPhone Duo upright, half an iPad): dialogs and the ⋯ menu are centred cards instead of stretched edge to edge.
- **Large screens:** question options no longer stretch across the whole screen, Change history is wider with a fixed height, Project files keeps its height between folders, settings cards have a readable width, and the session list can be hidden with the new sidebar button (remembered).
- **Sessions waiting for an answer** are marked "waiting for an answer" in the sidebar, also for other computers; on desktop the digits 1–9 answer the visible question card unless you are typing.
- Dialogs: New session has the same header with ✕ as the others; going back in Change history points left; A− / A+ look like buttons; dialogs open with a subtle fade (off with reduced motion).
- ⋯ menu: everything about the terminal (show it, open in a new tab, new terminal here) is in one group.
- Copy and small fixes: one word "computer" in Network ("Name of this computer", "Other computers"); "Project folder" in New session; the skip-permissions flag no longer breaks mid-word; "Connect GitHub" is secondary to "Create"; quick keys have labels for screen readers; shortcuts show Alt+ outside Apple devices; commit messages read in the regular font; Project files creates a file from a small "+ File" button.

## 1.18.1 — 2026-10-06

Fixes from a review of today's changes.

- Security: Project files kept the panel's settings folder closed only by its literal path; with a symlinked `~/.config` (stow-style dotfiles) the panel password and keys were readable. Both the literal and the real location are now closed.
- Security: isolated terminal paths (the credential for that terminal) are masked in the panel log, and they now expire after 2 hours instead of 12 (each opening issues a new one).
- Security (installer as root): the update lock is opened read-only and never through a symlink, and the rollback snapshot is taken and restored as the panel user, so root never creates or writes files in the user's folders.
- Installer: the health check probes the address and port the panel really uses (its env); any failure after the code was copied, not only a failed health check, puts the previous panel files back; only a Tailscale address is looked up again when it left the machine (others stop with a clear message); the architecture check uses the system's packages, so a 32-bit Raspberry Pi OS on a 64-bit kernel is refused up front.
- Automatic updates: a download error no longer marks a release as failed on this computer; only a failed install does.
- Docker / SteamOS: forwarded client addresses are no longer trusted inside a container (all clients come from the gateway; set `AGENT_DECK_TRUSTED_PROXIES` for a real proxy), the generated password is no longer printed to the container log, and the container stops gracefully. macOS: a failed install unloads the new version before loading the restored one.
- Git: `Fetch from GitHub` keeps your own SSH setup (`core.sshCommand`); Haiku grouping runs without your hooks and settings and can no longer stay "running" after an unexpected answer; very large commits are read up to a size limit.
- Interface: Change history and Project files ignore answers that arrive for a branch, session or folder that is no longer shown, load "Show more" once, and show errors with **Retry** instead of "Loading…" forever; a saved new file appears in its folder; slow reads (GitHub repositories, git, files, other computers) get longer time limits and a clear "did not answer within N s" message; the terminal finishing loading no longer scrolls the Screen view; inputs are 16 px on every touch screen (iPad included); tabs are announced to screen readers.
- An upload that ends early is no longer forwarded to another computer as complete; file names that are too long give a clear error.

## 1.18.0 — 2026-10-06

- The session bar has icon buttons for Project files and Change history; switching between Screen and Terminal moved to the first item of the ⋯ menu ("Open the terminal" / "Show the screen").

## 1.17.0 — 2026-10-06

- Change history shows which branch it lists and lets you pick it: the checked-out one (a worktree usually has its own), the local default branch, or the remote one such as `origin/main`. A note says how many commits the branch is behind the remote, with a button to show the remote. **Fetch from GitHub** runs `git fetch --prune` (remote branches only, the working tree is untouched, never waits for a password). Feature groups follow the chosen branch.

## 1.16.3 — 2026-10-06

- Switching sessions no longer leaves the previous agent's screen up: a screen already seen appears at once, otherwise a skeleton with "Loading the session screen…" stays until the new one arrives. In Term mode a new terminal shows "Connecting to the terminal…" until it has loaded.

## 1.16.2 — 2026-10-06

- Project files: a file opens for reading — wrapped lines with numbers, selectable with a long press without the keyboard popping up or the layout jumping; Copy takes the selection or the whole file. Edit switches to the editor, which also wraps lines; a new file starts in it. A− / A+ share the remembered code size with Change history (the editor never goes below 16 px on phones, so iOS does not zoom).

## 1.16.1 — 2026-10-06

- Change history: diffs wrap long lines instead of running off the screen, all text files of a commit open expanded (binary files are marked "binary" instead of +0 −0), and A− / A+ change the code size, remembered in this browser.
- Fix: iOS enlarged some long lines on its own (text autosizing), so code rows came out in different sizes; the panel now keeps its font sizes as set.

## 1.16.0 — 2026-10-06

- **Change history** (⋯ menu): the commits of the session's repository with author, time and line counts; each commit opens with its full message and a per-file diff with line numbers (large files render when opened). Read-only git, no shell, size-limited patches; works for connected computers.
- **Feature groups:** Claude Haiku, run through the signed-in Claude Code CLI with no tools in an empty folder, groups the last 80 commits by feature from their subjects and file names only. Each group has a summary, its commits and a combined diff per file. The answer is checked against the real commits and cached until the next commit. New `GET /api/git/log|commit|groups|group_diff`, action `git_group`.

## 1.15.1 — 2026-10-06

- Fix: Project files did not scroll on phones; long folders were cut off. Dialog bodies can now always scroll.
- Notifications, Telegram messages and Waiting for you name a session by the title you gave it instead of its original name. Renaming does not re-send questions that were already announced.

## 1.15.0 — 2026-10-06

- **Project files** (⋯ menu): browse the session's folder and the rest of the home folder, open text files up to 1 MB such as `.env`, copy from them, paste a secret in and save, or create a new file. New files are `0600`, existing ones keep their mode, saves are atomic and refuse to overwrite a file that changed on disk after it was opened. The panel's settings folder (`~/.config/cc-panel`) and anything outside the home folder (including through symlinks) are not reachable. Works for connected computers through the gateway. New `GET /api/files`, `GET /api/file`, action `file_save`.

## 1.14.0 — 2026-10-06

- SteamOS (Steam Machine, Steam Deck): `install-steamos.sh` runs Agent Deck as a rootless Podman container built from the Docker image, started by a systemd user service; everything stays in the home folder and survives SteamOS updates, no sudo needed. Re-running the script updates it.
- In a container the update hint shows the command for that install (`docker compose up -d --build` or `install-steamos.sh`).

## 1.13.0 — 2026-10-06

- Debian 12+ and the 64-bit Raspberry Pi OS: the Linux installer no longer needs Ubuntu's `universe`, installs the static ttyd when the distribution has none, takes `gh` from GitHub's signed repository when missing, and stops with a clear message on Python older than 3.10 or 32-bit ARM.
- Docker: `docker compose up -d --build` runs Agent Deck in one container (tmux, ttyd and the panel as an unprivileged user, settings and agents in a volume, health check, log limits), for NAS boxes and distributions without the installer. The port is bound to localhost by default; the in-panel update button explains that a container is updated by rebuilding the image.
- Fix: the static ttyd build (used on Ubuntu 22.04 and now Debian) read the trailing `-t` of `tmux attach -t` as its own option and crashed; ttyd's options now end with `--` in the systemd unit, the macOS launch agent and the container.

## 1.12.0 — 2026-10-06

No breaking changes; the new isolation setting is off by default.

- Settings → Network → "Isolate terminals of other computers" (opt-in): a connected computer's terminal page is served under a signed path (bound to that computer, valid 12 h) with `Content-Security-Policy: sandbox`, so its scripts run in an opaque origin and cannot reach this panel, its cookies or other computers. Alt+1…9, copying the selection and the menu swipe do not work inside such terminals.
- Uploads to a connected computer stream through the gateway in 64 KB blocks instead of being held in memory; the remote login is refreshed first, and a rejected streamed upload is reported, never resent.
- `install.sh` and `deploy.sh` take the same lock as the in-panel updater and wait for a running update instead of copying files over it; installers no longer remove the previous `cryptography` copy while the old panel still runs (the new panel prunes it on start).
- Automatic updates check for releases without holding their lock, so Settings never waits on GitHub.
- macOS: if the new panel does not start, the installer restores the previous version and restarts it; when a Homebrew Python upgrade breaks the venv, the panel starts with Homebrew's current `python3` instead of restarting forever, and the next install rebuilds the venv.

## 1.11.3 — 2026-10-06

- `sudo ./update.sh` / `install.sh`: the running panel code is snapshotted before the update; if the new version does not answer `/login` within 20 s, the previous version is restored and restarted, and the installer exits with the logs command. Previously the new files stayed and the panel restarted forever.
- A changed Tailscale address (after a re-login) no longer locks you out: the panel re-resolves a stale 100.x `BIND_HOST` through `tailscale ip -4` when it starts, and the installer replaces a remembered address that is no longer on this machine in `install.conf` and the panel `env`. Only Tailscale addresses are re-resolved; an explicit `BIND_HOST` that is not local stops the installer with a clear message.

## 1.11.2 — 2026-10-06

- Fix: Codex limits showed "name 'json' is not defined" since 1.11.0; the moved limit parser now has unit tests for Claude, Codex and Kimi.
- Limits and other cached lookups are fetched once per key even when several tabs ask at the same moment, so the rate-limited Claude usage endpoint is not hit in parallel.
- An unexpected reset-time format loses only the reset time instead of the whole quota card.
- A thumbnail pruned by a concurrent request is rebuilt instead of failing; restoring a backup from a computer that sends no file reports that clearly.
- Streamed uploads keep the connection open for the next file; the gateway accepts `Content-Type` in any letter case like the local panel.
- Phones: a request that iOS parks while the app is in the background no longer blocks every later refresh (session list, questions, inbox and the connection status stayed stuck on "Connecting…"); reads now give up after 25 s and retry. Mutations keep waiting for a definite answer.
- Automatic updates no longer retry a release that already failed on this computer (each attempt restarted the panel every 15 minutes); a newer release or a manual update still installs.
- A second finger during the menu swipe no longer leaves the menu half open; Waiting for you cards start clean for a new question in the same session; keyboard focus stays on a computer header after expanding it; error messages are announced immediately by screen readers.

## 1.11.1 — 2026-10-05

- Phones: a swipe from the left edge opens the session menu and follows the finger, also over the terminal in Term mode; a swipe left closes it. Short pulls snap back; vertical scrolling is unaffected.

## 1.11.0 — 2026-10-05

No breaking changes: configuration, API and installers are unchanged.

- Notifications that cannot be sent yet (encryption components still loading) wait up to 10 minutes instead of being dropped; one failing notification no longer drops the others in the same check.
- Typed custom answers are kept per question across reloads, language switches, logout and computer switches, in the question card and in Waiting for you; a question that updates while you type no longer clears the text.
- Accessibility: the ⋯ menu moves keyboard focus into its items and back to its button; the image viewer keeps focus inside until closed and returns it; the sidebar list is replaced only when it changes, so focus, tooltips and the screen-reader position survive refreshes; the message field has a label.
- Sidebar: agents without quota data no longer show a row of dashes (the reason stays in the explanation); healthy quotas are no longer green, only ones that need attention are coloured; with computers connected the host name is not repeated under the selector.
- Translations: all 16 languages use their word for "computer" for connected machines.
- Code structure: connected-computer polling moved to `integrations/gateway.py` (one `get_json` for remote answers, removed computers are forgotten at once), limit parsing to `integrations/usage.py`, the Screen view renderer to `frontend/screen.js`; inline CSS colours became tokens with identical values.
- README screenshots refreshed.

## 1.10.0 — 2026-10-05

No breaking changes: configuration, API and installers are unchanged.

- Backups: a stored copy must decrypt with the group's key and carry a plausible time, so a copy from outside the group or a corrupted one never takes a place in the store. A connected computer may fill only its own folder (the first connection that sent a computer's backups owns it; a removed and re-added connection keeps working). Old copies are pruned by time as a number, and one failing copy no longer stops the replication cycle. The backup list reads only file headers.
- Screenshot thumbnails: the file content is checked before ImageMagick or `sips` sees it, and ImageMagick gets an explicit format, so a file named `.png` that is really SVG/PostScript is never converted. Thumbnails unused for 7 days are deleted.
- Telegram: answering a question on a connected computer no longer blocks the integration settings and status while the answer is delivered (the database claim still prevents a second answer).
- Encryption components: after an update that pins a new `cryptography` and before it downloads (or while offline), the previously installed copy keeps backups and notifications working.
- Updates: every `integrations/*.py` module of a release must import before the running panel is stopped; a broken release is rejected and the current version keeps running.
- Notifications: connected computers' session lists are fetched in parallel; a malformed or unreachable computer no longer stops notifications for the others, and its sessions do not look finished after a blip.
- Partial uploads left by a restart are removed after an hour; a missing session transcript is searched for at most every 30 s instead of on every scan.
- Interface: one word for every connected machine — "computer"; a route an older Agent Deck lacks shows "This feature is unavailable: update Agent Deck on this computer" instead of "Not Found"; on phones, messages over full-screen dialogs appear at the bottom; "Check for updates" (or the update itself) is the primary button in Settings → App; count badges have higher contrast; reduced motion stops all animations; inputs show a focus ring; the custom-answer option uses the pencil icon; the connect-computer button no longer looks like "New session"; the login prompt after an expired session is no longer replaced by another message; logout while offline reports it; all restore warnings are shown together.

## 1.9.2 — 2026-10-05

- Fix: a message with attached images could stay in the agent's input without being sent. Enter is now sent once the agent has finished attaching the files (the screen stops changing, up to 4 s; 1 s for plain text) instead of after a fixed 0.2 s.
- Fix: uploading files to a connected computer through the gateway failed with 403 since 1.9.0; the gateway now relays `POST /api/upload_raw`.
- Fix: switching computers while a request was in flight could show other computers as unavailable, let "Update all" report success too early and re-enable an inbox answer that had already been sent. Gateway requests are no longer discarded on a switch.
- A connected computer that is briefly unreachable keeps its last questions for up to 5 minutes, so Telegram no longer retires and re-sends them and notifications do not fire twice. Connected computers are asked in parallel, and readers no longer wait for a slow one.
- Phones: the custom-answer field no longer grabs focus (and the keyboard) on every refresh, opens the keyboard on tap and no longer zooms the page.
- Selecting text in the Screen view is no longer cleared by refreshes; the image viewer closes on a computer switch; status dots of other computers' quick tabs update; LM Studio is polled only when a profile is configured.

## 1.9.1 — 2026-10-05

- Fix: "undefined is not an object (evaluating 's of list')" after returning to the app. A response that is not the expected JSON (proxy page, restart) is treated as a connection problem instead of breaking the session list.
- Connection status: returning to the app shows "Connecting…" when it takes a moment, "No connection to the panel · retrying" while offline and "Connection restored" afterwards; network failures no longer appear as red error toasts.

## 1.9.0 — 2026-10-05

- **Waiting for you:** one list (sidebar button, first quick tab on phones) with every agent question and finished session on all connected computers; questions are answered in place. New `GET /api/inbox`.
- **Custom text answers:** *Other* / *Type something* options open a text field in the question card and the inbox; the panel moves to that option and types the answer exactly (bracketed paste). `POST /api/answer` accepts `text`; connected computers receive it through the gateway. Telegram: reply to a question message to send a custom answer (owner and chat checked, answered once, never replayed).
- **Update all computers:** Settings → Network shows every computer's version and updates all connected computers through the gateway, then the gateway; the sidebar marks outdated computers with an arrow.
- One shared question scan every 2 s now serves Telegram, notifications and the inbox (previously each scanned tmux on its own).
- Quick tabs on phones include sessions of connected computers.
- Large uploads stream as raw bodies (`POST /api/upload_raw`) with progress instead of base64 JSON; older connected computers fall back automatically.
- Screenshot thumbnails are scaled to 480 px with `sips` (macOS) or ImageMagick when available and cached until the file changes.
- Backups on macOS read the Claude login from the Keychain and restore it there (through `security -i`, never in process arguments); restore shows a warning when that fails.

## 1.8.2 — 2026-10-05

- Fix: tapping a notification opens its session reliably on iPhone. The page checks for the tapped target several times during 3 seconds after it becomes visible (the worker may store it later than iOS shows the app); if the page still has not taken it after 1.5 seconds, the service worker navigates the window to the session's address, and the panel now follows `#session` changes in the address.

## 1.8.1 — 2026-10-05

- Documentation: fresh screenshots for the README, including one-tap answers, screenshots from agents, notifications, sessions of connected computers and backups.

## 1.8.0 — 2026-10-05

- Windows 11 support through WSL2: `install-windows.ps1` (PowerShell as administrator, `irm … | iex`) installs WSL, Tailscale and Ubuntu 24.04, enables mirrored networking (keeping other `.wslconfig` settings, with a backup), runs the regular Linux installer bound to the Windows Tailscale address, opens the panel port for the Tailscale range only, adds a Start menu shortcut and keeps WSL running while signed in. Rerunning updates.
- Notifications: the title is the session name; the agent, its status and the computer move to the body with the question, so nothing is cut off.
- Fix: tapping a notification now opens its session, including on iPhone where a resumed Home Screen app missed the worker message. The tapped target is kept in Cache Storage and opened on start, resume or focus (ignored after 2 minutes); sessions on other computers switch to that computer.

## 1.7.0 — 2026-10-05

- Screenshots in agent output: image paths (absolute, `~/`, relative to the session, including paths the agent wrapped across lines) become links with thumbnails in the Screen view and open in a full-screen viewer with swipe/arrow navigation and "Open original". Works for sessions on connected Agent Decks.
- New `GET /api/image?name=&path=`: serves only paths visible in the session's recent output, only PNG/JPEG/WebP/GIF verified by content, up to 25 MB, with `nosniff` and a sandbox CSP. The gateway relays images only from this endpoint.

## 1.6.0 — 2026-10-05

- **New runtime dependency:** `cryptography`, pinned per platform and Python version (URL + SHA-256 in `integrations/dependency_lock.py`). The installer or the running panel downloads the wheels into `~/.local/share/agent-deck/python/` without pip, virtualenv or root; offline panels keep working and retry every 10 minutes. Intel Macs use cryptography 48.0.1, the last release with Intel macOS wheels.
- Notifications (Web Push) on iPhone (Home Screen app, iOS 16.4+), Android and desktop browsers: an agent asked a question or finished work, on any connected Agent Deck; tapping opens that session on the right computer. Requires the panel over HTTPS. Settings → Connections → Notifications; test message, per-event switches, per-device removal. New API: `GET /api/push`, `POST /api/push_subscribe|push_unsubscribe|push_test|push_events`, public `/sw.js`.
- Backups are now encrypted with AES-256-GCM; backups made by 1.5.0 remain restorable.
- Sessions on other computers show the "done" dot; the menu badge, tab title and the Home Screen icon badge count them.
- Telegram warns when a connected Agent Deck polls the same bot (questions would arrive twice).
- Help: install, update and stop commands are split per platform, one command per block.

## 1.5.0 — 2026-10-05

- Backups of Agent Deck settings, integration keys and agent logins (Codex, Claude on Linux, GitHub CLI) under Settings → Backups: a one-time recovery code, daily and on-demand backups, the last 14 copies per computer.
- The gateway shares the key with connected Agent Decks, collects their backups and stores every copy on every other computer; computers with another key or an older release are reported, never overwritten.
- Restore from this computer, a connected Agent Deck or a downloaded `.adbk` file, onto this computer or (from the gateway) a connected one; the replaced state is backed up first and the panel restarts.
- New files in `~/.config/cc-panel/`: `backup-key`, `instance-id` and `backups/` (all private). New API: `GET /api/backups`, `GET /api/backup_blob`, `POST /api/backup_setup|backup_now|backup_run|backup_store|backup_restore|backup_restore_remote`.

## 1.4.1 — 2026-10-05

- Switching to another Agent Deck happens in place without a page reload: the sidebar and title show the target's known sessions immediately, drafts and attachments stay with their computer, and responses still in flight for the previous computer are discarded.
- A computer without its own saved view keeps the current Screen/Term choice after a switch.

## 1.4.0 — 2026-10-05

- One Telegram bot for several computers: the gateway delivers questions from connected Agent Deck instances (new `GET /api/questions`), labels them with the computer name and relays answers through the authenticated gateway. Unconfirmed remote answers are marked uncertain and never resent. The "already used by another receiver" error now explains this setup.
- Question scans no longer hold the Telegram lock, so a slow computer does not delay button taps.
- The sidebar lists sessions of every connected Agent Deck in collapsible sections (unavailable computers are marked); tapping one switches to that computer and opens the session.
- Wider quota columns so "Remaining" and "Plan" no longer overlap on phones.

## 1.3.0 — 2026-10-05

- Answer agent questions with one tap: the question and its options appear above the message field (`GET /api/question`, `POST /api/answer`); free-text options stay on the key row.
- Phone landscape keeps the phone layout and safe-area insets; the keyboard hides quick tabs and the status line, the header compacts, and controls are at least 44 px.
- Quick tabs end with "+ New session"; long-press a tab for its actions. "Jump to latest" appears when the output is scrolled up. File uploads show progress.
- Desktop header: title, Screen/Term switch, link and one "⋯" menu; the mobile action sheet is grouped with "Close session" last.
- Styled confirmation dialog replaces browser `confirm()`; toasts appear at the top, are announced to screen readers and can be dismissed.
- New session: one-row agent picker, Git URL/worktree under "Git and worktree", branch only with worktree.
- Settings: Kimi and Telegram editors open in place, new Network section, language applies on change, optional message autocorrect (off by default).
- Text contrast meets WCAG AA, minimum text size 11 px, SVG icons instead of emoji, session state shown as text and keyboard-focusable session rows; the sidebar monitor only re-renders on change.
- Login page uses the same iOS status-bar style as the app.

## 1.2.4 — 2026-10-05

- Fix Claude quotas showing "—" after a panel update: the last successful Claude/Codex usage is kept in `~/.config/cc-panel/usage-cache.json` (0600) and served after restarts instead of a fresh request.
- Query the Claude usage endpoint at most every 10 minutes; after HTTP 429 wait at least 30 minutes or the server's `Retry-After` (up to 6 hours).
- "Reconnect terminal" has the same height as the other terminal keys and no longer wraps.

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
