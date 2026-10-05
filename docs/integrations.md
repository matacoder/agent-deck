# Integrations

The panel owns sessions and input locks. `integrations/questions.py` normalizes
agent questions; `integrations/store.py` owns the durable outbox;
`integrations/telegram.py` delivers questions and authenticates replies.
The Telegram transport receives `scan` and `answer` callbacks and does not execute
shell commands or know how an agent accepts an answer. These boundaries permit
another delivery channel without changing the agent adapters.

## Telegram setup

Open **Integrations** from the phone actions menu, or **Telegram → Configure** in
the sidebar. Save your existing bot token from @BotFather. Open the generated
pairing link and press **Start** in the bot's private chat. Pairing expires after
ten minutes and binds both Telegram user ID and private chat ID. The panel shows
the linked account. You can pause delivery, bind another account, or remove the
token. Use a dedicated bot: another `getUpdates` consumer or an existing webhook
conflicts with the panel. The integration never removes another webhook.

The bot uses outbound HTTPS long polling. No public webhook, additional listening
port, database server, or Python dependency is needed. It works on Linux and Mac.

Telegram hands updates (button taps) to exactly one receiver, so a bot cannot be
polled by two panels. For several computers, configure the bot on the gateway only
and connect the others under **Settings → Network**. The gateway reads their
questions from `/deck/<id>/api/questions` (5 s timeout; an unreachable or pre-1.4
instance is skipped for 30 s), prefixes the message with the computer name and
answers through the remote `/api/answer`, which re-checks the question fingerprint.
A remote answer that is not confirmed is stored as uncertain and never resent.

## Questions and answers

Codex and Claude adapters read pending structured questions from the exact
conversation transcript identified by the session hook. Claude through Kimi uses
the Claude adapter. Native Kimi and other recognized terminal menus use the active
screen as a fallback. Only the question and its options are sent; conversation
history and terminal output are not forwarded. Secret and multiple-selection
structured questions are excluded. Free-text/Other answers currently use the panel.

A callback is bound to its owner, chat, Telegram message, session, pane, process,
conversation, request, and question contents. Input uses the panel's existing
per-session lock. For hidden Codex questions the adapter opens the question UI,
matches its title/options, moves the cursor, checks the resulting selection, and
confirms. Unknown menus or changed questions fail closed and direct the user to
the panel. Codex CLI 0.160's **Queued follow-up inputs** form uses an `enter submit`
footer and is supported in addition to the numbered question overlay. This path
was verified with a real Telegram button response reaching the live Codex session.
A temporary opening failure leaves the buttons available for another user click;
the integration does not blindly navigate an unrelated queued form.
A newer direct user message supersedes older asynchronous questions.
Terminal formats vary between agent versions; unrecognized forms are not answered.
The transcript reader reads a bounded two-megabyte tail to avoid scanning large
conversations repeatedly.

Questions are deduplicated across panel restarts. Answer input is claimed in SQLite
before terminal input; an interrupted claim is marked uncertain and never replayed.
This favors avoiding a duplicate answer over retrying an answer whose delivery is
unknown. Telegram notification delivery can be repeated after an ambiguous network
failure; only the current message can answer that question. Closed question buttons
are removed. Finished records are removed after seven days.

## Storage

Existing panel state remains in `~/.config/cc-panel/sessions.json` and other JSON
settings. New integration files are under `~/.config/cc-panel/integrations/`:

- `telegram.json`: bot token, enabled state, linked account and expiring pairing hash.
- `questions.sqlite3`: questions, delivery/answer states and Telegram polling offset.

Both files have mode `600`; the directory is created with mode `700`. The token is
never returned by panel APIs or saved in browser storage, URLs, the repository, or
agent commands. Telegram API errors are sanitized to exclude token-bearing URLs.
Back up this directory alongside panel settings; it contains private data.

## Packaging and older installations

The source package is next to `panel/`; installers put it inside the installed
runtime. The updater restricts package files to Python modules, compiles all downloaded
Python before stopping the panel, rejects symlinks and traversals, and rolls back
the complete runtime on failed startup.

Updaters before 0.7 install only core files and ignore the source package. That
first update leaves the panel operational and shows **Install integrations**.
Click it once to install the package using the newly installed updater, even at
the same version. Rerunning the full installer installs everything in one step.
