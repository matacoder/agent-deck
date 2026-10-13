# Changelog

Versions follow [semver](https://semver.org). Install a version with `sudo ./update.sh vX.Y.Z` (older than the installed one: `sudo FORCE_DOWNGRADE=1 ./update.sh vX.Y.Z`).

## 1.52.5 — 2026-10-13

- **The selected computer is not named twice.** With several computers the list began with a heading that repeated the name already chosen in the selector above it; that heading is gone, so the sessions start right under the row with the flag. A computer further down the list keeps its heading. Where the selector is not shown, the name stands next to the flag.

## 1.52.4 — 2026-10-13

- **The top of the session list is one row.** The address and the search field took two rows above the sessions. Now there is the country flag (the address, city and Tailscale address are in its hint), a search button, the new-session button and the waiting-for-answer button. The search field opens from its button; Esc closes it and clears the filter, so a hidden field never keeps sessions out of the list.

## 1.52.3 — 2026-10-13

- **An event is told once, not as a notification and in Telegram.** With both in use, Telegram now gets what needs you: an agent's question (answered there by a button, no longer also a notification) and finished work where the agent waits for your answer or approval, which the summary's model marks. Everything else that finished is a notification only. With no subscribed device, or when no device's push service accepted the notification, it goes to Telegram instead; whether a device then showed it cannot be known.

## 1.52.2 — 2026-10-13

- **Telegram messages open with their meaning.** A message began with the computer, the agent and the session, so the chat list showed only those. A "finished" message now opens with what was done and a question with the question itself; the session, computer and agent follow below.
- **A session is not announced as finished again when nothing happened in it.** "Finished" is read from the terminal going quiet after activity, and activity is not always work: typing, a redraw, a background task's counter. The same notification could arrive several times in a few minutes. A "finished" message whose summary is the one already sent for that session is now dropped, as push and in Telegram; sessions without a summary are announced as before.
- **The three headers of a desktop page are one height.** The computer switcher on the left was 54 px, the session bar 44 px and the project panel's tabs 49 px, so the line under them broke twice; all are 44 px now.

## 1.52.1 — 2026-10-13

- **A "finished" notification says what has just been done.** It carried the summary's topic line and the start of its text, which opens with the goal: the two lines a notification shows told what the session is about, not what happened. The model now also writes one sentence about what the agent has just finished or is asking, with the concrete result, and the notification is that sentence under the conversation's name; the Telegram message opens with it. The agent's latest message reaches the model four times longer than the earlier ones, so the result is not cut off.

## 1.52.0 — 2026-10-13

- **The conversation can be read when the terminal no longer holds it.** A restarted or shortened conversation leaves only its last screens in the terminal, and a question from the agent then refers to options that are nowhere to scroll back to. A **Conversation** button in the line under the message field (and in the **⋯** menu) shows what was said — your messages and the agent's answers, without tool output — from the agent's own conversation file, including what came before a compaction. Claude Code (and services run through it) and Codex; a connected computer shows it once it has this version.
- **Sessions are named after what is going on in them.** The model that already writes the summary also gives the session a short name in Latin letters (`fix-payment-webhook`), in the same request, and is asked to keep it until the work really moves to another task. It is shown wherever the session's name was: the list, the bar, notifications, Telegram. A session you renamed yourself keeps your name. On by default; **Settings → General → Session names** turns it off for the sessions of that computer. Claude Code and Codex.
- **Notifications say what was done, not that something finished.** A "finished" notification with a summary is now headed by the conversation's name (and the computer's, for a connected one) and carries only the summary; the line "Claude finished working" stays only when there is no summary to show. The Telegram message drops the same line.

## 1.51.1 — 2026-10-13

- **The context size is right at once after a conversation is shortened.** After `/compact` (or Claude Code's own compaction) the line under the message field went on showing the size from before until the agent answered again, because the size was read from the last answer. It is now taken from the compaction record itself.

## 1.51.0 — 2026-10-12

- **Pictures of messages copied from Telegram (and other apps) are attached.** Safari gives a text field only the text of such a copy — no files, no pictures — but pastes the pictures too into an editable block, as Notes receives them. A paste by ⌘V / Ctrl+V into the message field is now caught by such a block out of sight: the text goes into the field as before (undo included), the pictures are attached. A paste by the menu (a phone, a right click) cannot be caught that way: when its text names a picture, a notice offers **Paste with pictures**, a dialog with an editable block, also in the **⋯** menu.
- **A page left open says when it is outdated.** The interface reloads itself for a new version only when nothing is in use, which on a desktop with a terminal open was never: the page stayed on an old version for days and went on showing what later versions had fixed. A **Reload the page** button now appears in the top bar when the interface was updated and the page could not reload itself; drafts and attachments are kept. The check also runs every five minutes, not only when the tab comes back.
- **The line under the message field no longer disappears by itself.** One answer saying the session has no conversation hid the context, age and restart buttons until the next check half a minute later; the line now goes only when a second answer says the same.
- **A sent picture leaves the field together with the text**, not a moment later when the session list comes back.

## 1.50.0 — 2026-10-12

- **The message field no longer loses the keyboard in the middle of typing.** Every refresh of the session view put the whole message area back where it already was, which takes it out of the page for a moment, and the field lost focus: right after the page opened (now that it opens with the remembered list, typing starts before the first answer), after a session switch, whenever the view was redrawn. It is moved only when it really changes place, and then keeps focus and caret.
- **Folded keys use the whole row.** 1.49.1 always kept room for the quick prompts, so keys stayed hidden beside empty space. The room is kept only for saved quick prompts; without them the folded row takes the full width.
- **Terminals of the sessions in the list are opened ahead** on a desktop that uses terminals: the five most recent running agents, one at a time, after the open one is ready, so a switch shows a live terminal instead of "connecting". Each is a real tmux client laid out at its real size. Not on phones, not for shells or stopped sessions.
- **The project panel remembers what it showed per session**: commits, feature groups, the picture gallery and the home folder are on screen at once on a switch back and are replaced by the fresh answer; a failed read of the gallery shows the error instead of remembered pictures. Where nothing is known yet, placeholders stand in for "Loading…" in Commits, Feature groups, diffs, Files and Gallery.
- **Open a connected computer directly.** With a computer selected, the arrow beside the computer list opens that computer's own panel in a new tab at its Tailscale address, already signed in, so on the machine under your hands nothing travels through the gateway and back. The link signs in once and within a minute; its secret is given by the computer to the gateway only, and the attempt limit is the one passwords have. Both sides need this version. (A page served over https may not call a plain-http address, so the shortcut cannot happen silently inside the gateway's page.)
- **"This computer" can be set by hand** where the browser does not allow the automatic check (Safari): Settings → Network → ⋯ of the computer.
- A commit or a group's combined diff opened once is not fetched again; folders of the file browser open from memory and refresh behind; commits and feature groups survive a reload of the tab.
- README: a new opening and feature overview, screenshots retaken on current demo data.
- CPU and RAM show the last figures of that computer until the next ones; the GitHub block of the New session dialog shows the known sign-in and repositories at once.

## 1.49.1 — 2026-10-12

- **The key row no longer blinks.** At some window widths the row hid a key that did not fit, became narrower by that, was measured again, showed the key, and so on without end; the last key was drawn cut in half. The row is now fitted when the room it is given changes, not when its own width does, and that room no longer depends on whether the quick prompts are shown.

## 1.49.0 — 2026-10-12

The page stops jumping while it loads and stops showing "loading" for what it already knew.

- **The page opens with what it showed last time.** Sessions, the computer switcher and the other computers' lists, limits, local models, the version: all are drawn at once from what this browser saw before, per computer, and replaced in place by the fresh answers. Before, the list was empty, the switcher and the computer headings arrived a second later and pushed everything down. The very first time on a computer, placeholders of the final size stand in for the session list, the limits, the footer and the CPU/RAM figures. Signing out forgets all of it.
- **Switching sessions shows the screen at once.** The screens of sessions not opened yet are fetched quietly after the list (the eight most recent), so a switch shows text immediately and the fresh screen replaces it. A switch made while a list request was on its way no longer waits for that one and then for its own. Screens survive a reload of the tab (kept only in the tab's own storage, the end of each screen, gone with the tab).
- **A switch back keeps the summary, the context bar, the "send later" count and the Changes tab** of that session on screen while they are read again, instead of collapsing and reappearing. An unchanged diff is not redrawn, so a comment being typed under it stays.
- **The last lines of the screen are no longer cut off after a switch.** A row appearing above or below the screen (summary, context, a question) made it shorter without scrolling it; text that was being followed now stays followed.
- **Pictures of a pasted chat message are attached more often.** Most sites do not let another page read their pictures, so the pictures of rich text copied from a chat were silently left out. The panel now fetches such a picture itself: only from a public https address on the usual port (every address of the name is checked and the checked one is dialled, so a name cannot lead into your network), without cookies, up to 12 MB, and only if the bytes are a picture. A picture that needs its site's sign-in, or exists only inside that page, still cannot be fetched: save it and attach the file.
- **A terminal that finishes connecting no longer takes the keyboard away.** The terminal focused itself when its connection opened, seconds after the session was shown and again after every reconnect, so text being typed into the message field, the search or an answer went nowhere from that moment. It now leaves the focus alone while a field of the page is in use; a click on the terminal focuses it as before.
- The New session dialog opens at once instead of after the list of folders; the question card is asked for alongside the session list, not after it.
- With the project panel docked, switching to another computer that has a session of the same name no longer leaves the previous computer's changes on screen.

## 1.48.1 — 2026-10-12

- **The session list no longer slides sideways on a phone.** The enlarged touch area of the "+" in a group's row reached past the right edge of the list, so the sidebar could be dragged left and right. The area now stays inside the row, and the sidebar does not scroll horizontally at all.

## 1.48.0 — 2026-10-12

Fixes from a review of the last week, a first step towards talking to your own computer directly, and a tidier screen.

**Both sides must be updated for a computer to be reached at an address of the local network** (or at any address other than the Tailscale one it was connected by): the proof of the pair key changed. Until then such a computer is reached over Tailscale as before; one connected only by its local address does not answer the gateway until both have updated, which each does by itself within six hours.

- **"Continue after the limit resets" answers a limit notice once.** A notice without a date ("resets 3pm") left on an idle screen was answered with `continue` again the next day and after every panel restart; what was answered is now kept in the file and forgotten only when the notice leaves the screen.
- **A typed service key no longer outlives Settings.** The editor of "Claude on other models" stayed open behind a closed Settings dialog, so a key typed for one computer could be saved to another after a switch. It now closes with Settings and asks before dropping a typed key, like the other editors.
- **Local network sign-in is stricter.** An address that proved the pair key is asked again after a minute and in every other network; the proof names the address the gateway dialled, so a machine that only passes the question on to the real computer gets nothing; pair keys stop working when the panel password changes; a search answer no longer pushes out an address already kept; renaming a saved connection does not send its password again; a panel installed on its local address no longer trusts `X-Forwarded-For` from its neighbours.
- **Sessions come back after a reboot as they were:** Claude Code on another service's model resumes instead of opening a bare terminal, and an agent keeps the Docker it was started with.
- **"Send later" stays with its session.** The dialog names the session, a shortcut does not switch sessions under an open dialog, and if another session is on screen by the time you press the button nothing is sent until you press again. It moved from the message field into the three-dots menu; while something waits, the clock with the count is back by the field.
- **The quick message editor reads the list before it opens**, so a list that did not load, or was changed on another device, is not replaced by an empty or old one.
- **"This computer".** When the browser runs on one of the connected computers, the list and the bottom line of a session say so. The page asks `127.0.0.1` whether the installation with that id is here; only the right id gets a readable answer, and nothing else is served there. Asked on a desktop with more than one computer.
- **Keys that do not fit go behind "…" on a desktop too**, instead of wrapping into three half-empty rows in a narrow window; on a phone the row is spread over the whole width. Settings is a gear in the top row on a phone as well.
- **Settings → Agents is shorter:** agents that are not installed wait folded under "Other agents", a working agent's card drops its line about signing in, and "Add another service" is a visible button. A session on another service's model says so in the header and in the message field.
- A picture that failed to load once is tried again after a minute instead of never; a pasted fragment with dozens of pictures downloads only the ones that fit, never asks addresses inside the local network, and gives up on a slow or huge one.
- An update no longer restarts the panel in the middle of a `docker build` or a pull going through it; a computer that fell asleep is noticed by the Docker tunnel in about two minutes.
- A terminal-only agent that is not installed is refused with a message instead of opening a session on `command not found`; one that hangs on `--version` no longer holds up the list of agents; Codex is no longer told to hand a task to Codex.
- `sudo ./update.sh` points an existing checkout at the renamed repository.
- `integrations/decks.py` is split into connections, transport (`deck_transport.py`) and search (`deck_discovery.py`).

## 1.47.0 — 2026-10-12

- **Five more agents: Cursor, Gemini CLI, GitHub Copilot, OpenCode and Qwen Code.** Settings → Agents installs each with its vendor's own command and opens its sign-in; an installed one appears in the new session dialog with its "without questions" switch. A session keeps its conversation across restarts (OpenCode continues the last one of the folder), and the agent's own compact and "new conversation" commands sit behind the "more" chip. Context size, summaries and limits are not shown for them yet.
- **Claude Code on other models.** Settings → Agents → "Claude on other models" saves a service with an Anthropic-compatible address — GLM in one tap, or any https address — and a new Claude session offers it under "Model source". The key stays in a 0600 file and reaches Claude Code only through its environment.
- **Claude Code leads.** A Claude Code or Codex session is told in one line which other agents on the computer take a task in one command, so it can ask one for a second opinion or hand a task over when you say so.
- **Agents of the "program in a terminal" kind are described once** (`integrations/agents.py`, `frontend/agents.js`), so the next one is an entry, not new code paths.
- **The compact button has an icon that looks like compressing**, not like leaving full screen.

## 1.46.1 — 2026-10-12

- **The repository is now `matacoder/deckaway`.** Install commands, the update check and the installers use the new address. The old address keeps working: GitHub redirects it, so installed panels update as before and earlier install commands still run.

## 1.46.0 — 2026-10-12

- **Away Deck is now DeckAway.** The name changed in the panel, its 16 languages, the sign-in page, the installed app, Telegram messages, the installers and the documentation. Nothing moves on disk: `/opt/agent-deck`, `~/.config/cc-panel/` and the service names stay. Computers on earlier versions are still found and connected; Docker contexts created as `Away Deck: ...` are still kept in step and removed, new ones are described `DeckAway: ...`.
- **Pictures on the session screen no longer blink** while the agent's timer runs: the screen was rebuilt on every change of its text, and each thumbnail with it. Thumbnails already drawn are now kept.

## 1.45.1 — 2026-10-12

- **The bottom of the session list takes less room on a desktop.** Limit rows are lower, a local model is one line (its name, the last answer and the speed), and Settings is a gear in the top row next to the actions and the search instead of a wide button below. A phone keeps its Settings button in the session list.

## 1.45.0 — 2026-10-12

- **Text copied together with pictures (a chat message, a page fragment) is pasted with them.** The text goes where a paste always goes; the pictures are attached beside it, up to four. Emoji and avatars drawn as small pictures are left out. A picture its site does not let other pages read cannot be fetched by the browser: the panel says how many were attached, the rest are saved and attached as files.
- **A "compact the conversation" button** sits third in the bottom line of a session, after the two restarts; it sends `/compact` to Claude Code or Codex.

## 1.44.1 — 2026-10-12

- **A computer that takes a few seconds to answer is no longer reported as "did not respond".** 1.44.0 gave every connection four seconds; a waking Mac needs longer over Tailscale. The short wait now applies only when the computer has another address to try.
- **A picture is pasted from the clipboard anywhere on the page**, the live terminal included, not only with the cursor in the message field.
- **Scrollbars are dark on Windows**, in the panel and in the live terminal.
- **Claude Code on a Mac is no longer shown as "not running".** Its own installer starts the program from a file named after the version (`2.1.296`), and macOS reports that name; the panel took it for a stopped agent, so the state, "finished" notifications and resuming after a restart were wrong for such sessions.

## 1.44.0 — 2026-10-12

- **Works in an ordinary local network, next to Tailscale.** **Settings → Computers → Local network** has a switch per computer: when on, the panel also answers at the computer's local address (`192.168.x`, `10.x`, `172.16–31.x`). It is off by default and asks first, because the connection there is plain HTTP. The gateway can switch it for every connected computer.
- **One computer, several addresses.** **Find on the network** searches Tailscale peers and the local network (the `/24` around the gateway) and shows a computer seen in both as one row. A connected computer is reached over Tailscale first and over the local network when Tailscale does not answer; its row says which is in use. Connections accept local addresses, so computers without Tailscale can be connected.
- **A password never follows an address into another network.** The saved password is sent by itself only to the Tailscale address you entered. Any other address first proves a key the two panels agreed on while signed in; a foreign machine holding the same local address gets neither the password nor the cookie.
- **LM Studio is searched in the local network too**; a server found over Tailscale and locally is listed once.
- **Wide windows lose two rows.** The keys and the quick prompts share one row, and the computer and container names sit on the line of the context instead of below it. Phones are unchanged.
- Computers before this version keep working over Tailscale; they get a local address after they are updated.

## 1.43.2 — 2026-10-12

- **The bottom line changes after a restart.** It was drawn only when a session was opened, so a session moved to another computer's Docker kept showing the old name until the page was reloaded.

## 1.43.1 — 2026-10-11

- **One "…" on a phone instead of two.** Where the keys row has its own three-dots button, it now opens the agent commands (`/compact`, `/clear`, `/new`) together with the other keys; the second button is gone, and so is the row that held only the pencil (it appears with the commands).

- **The bottom line names the Docker the session really uses.** It showed this computer's default, so a session started before a computer was chosen for containers looked as if it already ran them there. Now the session remembers what its agent was started with; sessions started before this version show this computer until their next restart.

## 1.43.0 — 2026-10-11

- **Each session chooses where its containers run.** The new-session dialog has a **Containers** list (this computer or one marked for containers), and a new line at the bottom of the status bar names the computer the session runs on (left) and the one that runs its containers (right, with the Docker whale); tap the right one to change it, then restart the session to apply. The choice in Settings → Computers is now the default for new sessions. Sessions started before keep following that default.
- **Agent commands moved behind "…".** `/compact`, `/clear` and `/new` no longer sit in the row of quick prompts: the three-dots button shows them, and they hide again after one is sent.

## 1.42.0 — 2026-10-11

- **A closed Docker is opened by the panel.** A computer whose Docker is installed but not running can now be marked for containers: marking it opens Docker, and so does a command that arrives later while it is closed (the command waits up to a minute instead of failing). Works for Docker Desktop and OrbStack on macOS, Colima, rootless Docker on Linux and Docker Desktop on Windows; a system Docker that needs root is not started.
- The Containers card tells a Docker that is closed ("not running") from one the panel cannot find or start ("not found").

## 1.41.0 — 2026-10-11

- **Containers run on the computer you choose.** In Settings → Computers, mark a connected computer as one that runs containers and pick it for this computer's sessions: `docker` and `docker compose` typed by an agent then run on that computer's Docker, with no change to the commands. Agents stay on the weak machine, builds and checks go to the strong one. Nothing to set up between the machines: the panels already trust each other over Tailscale, so there is no SSH and there are no keys. Applies to a new or restarted agent session.
- **A Docker context per such computer**, named after it (`docker --context red ps`), created and removed by the panel; contexts it did not create are never touched.
- **The agent is told where its containers run**: at the start of a session it learns the computer's name and address, that local folders cannot be bind-mounted there, that published ports open on that computer, and how to run a container locally instead.
- A computer that is asleep or no longer marked answers the Docker command with the reason instead of a connection error.
- Limits of this version: folders of the session's computer are not mounted into remote containers (put code into the image, use named volumes or `docker compose watch`), ports are reached on the other computer's address, and only the computer the others are connected to (the gateway) can send its containers elsewhere.

## 1.40.0 — 2026-10-11

- **"Finished" notifications and Telegram messages say what was done.** When an agent finishes, the panel rewrites the session's summary right away and adds it to the notification and to the Telegram message: one line and a few sentences on the goal, what is done and what is next. Written by a model of the session's own provider, in the language of each device and of the bot, also for sessions on connected computers. The message waits for the model up to 30 seconds; a session whose provider cannot summarize (Kimi Code, Pi, not logged in) gets the earlier short message.

## 1.39.0 — 2026-10-11

- **Agent Deck is now Away Deck.** Another project already uses the earlier name. The new name is shown in the panel, the login page, the home-screen app, notifications, Telegram messages, installer output and the documentation. Nothing moves on disk and no setting changes: `/opt/agent-deck`, `~/.config/cc-panel`, service and container names, the repository address, the Windows Start menu shortcut and scheduled task, and the macOS log folder keep their names, and computers on earlier versions stay connected.

## 1.38.0 — 2026-10-11

- **Quick prompts.** A row of buttons above the message field sends a message with one tap: your own saved prompts (edited with the pencil at the end of the row, up to 24, one list for every connected computer) and the agent's commands, `/compact` and `/clear` for Claude, `/compact` and `/new` for Codex. Commands that drop the conversation ask first.
- **Send later.** The clock next to the send button holds a message until a set time, until the agent is free, or until the subscription limit that stopped the session resets. Waiting messages are listed there and can be removed; they survive a panel restart, are never typed into an open agent question and are sent at most once.
- **Continue after the limit resets.** A per-session switch in the same dialog, off by default: when an agent stops with a limit notice, the panel waits for the reset time named in it (Claude Code and Codex notices; the provider's counters when no time is named) and sends `continue`, once per reset.
- **Telegram says when an agent finishes,** and a reply to that message is sent to that session as the next prompt, also on connected computers. On by default for a linked bot; the **Tell me when an agent finishes** switch in the Telegram card turns it off. Installations on a plain Tailscale address, where browser notifications are unavailable, get the "finished" event this way.

## 1.37.0 — 2026-10-10

- Claude and Codex sessions started from the panel are asked, at the start of a conversation, to show a finished task: screenshots of the result (their paths appear as pictures on the Screen and in the gallery) and, for anything that opens in a browser, a link on this computer's Tailscale address instead of `localhost`. Work with nothing to look at is left alone. On by default; **Settings → General → Finished task** turns it off. It reaches a session at its next start, restart, `/clear` or compaction, and never agents started inside another agent or outside the panel.

## 1.36.4 — 2026-10-10

Fixes from a review of the last two days of changes.

- The panel no longer freezes while a session shows a very long line (`base64 -w0`, minified code): the picture search for the gallery took seconds on such a line, every five seconds, and every request waited for it.
- Feature groups: a deleted or failing repository no longer stops the grouping of the others; groups keep their language across a panel restart instead of being sorted again; a failed re-sort in another language keeps the groups there are; "Refresh" pressed while a pass is running is not lost; a model that answers with nothing is followed by the next model instead of sending commits to "No group" within seconds.
- Context size no longer drops to zero after Claude Code's own notices (an API error, an interrupt), and is still shown, with the conversation age, when the last message is a pasted picture of several megabytes.
- A session whose saved model source cannot be read gets no summary instead of one written by Claude; a provider that cannot summarize is asked again every few minutes, not on every poll.
- The gallery folder `~/.cache/agent-deck/gallery` and its lists are private to the user (the folder was created readable by others).
- The background fetch refuses `ext::` remotes.
- Phone project drawer: messages are no longer cut off inside it or laid over its tabs; a wide table, code block or diff scrolls sideways both ways before a swipe closes the drawer; it comes back with the file it showed, and unsaved text is never dropped without the question; closed, it is skipped by Tab and screen readers from the start.
- With the keyboard up on a phone, an opened summary gives its room to the conversation. A failed check no longer blanks the summary and the session strip for half a minute. Selecting summary text with the mouse does not close it.
- The gallery of a session is not shown for a session of the same name on another computer, and keeps refreshing after a computer switch.
- A download says it started, and more taps on the same file do not start it again.
- Context limits in Settings can be typed in any order; nothing is saved until red is above yellow.
- A commit opened from "not sorted yet" goes back "To groups"; the line-number column on a phone fits four-digit new line numbers.
- Tests for the 1.27.0 terminal-link, framing and paste fixes now run with the unit tests; the ttyd pins of the installer and the image are checked against each other.

## 1.36.3 — 2026-10-10

- The closed summary under the session bar is its headline only, shown in full (wrapped, not cut with an ellipsis); the first sentence of the description is no longer shown until the note is opened.

## 1.36.2 — 2026-10-10

- The summary under the session bar reads as a note: an accent edge, a tinted background, a bold headline and brighter text; the expand arrow is gone, and a tap anywhere on the note, the opened text included, opens or closes it.
- The conversation age is shown for conversations that begin with a picture: their first record is a single line of megabytes, which the start lookup now skips.

## 1.36.1 — 2026-10-10

- iPhone and iPad, panel opened from the Home Screen: downloading a file no longer leaves a blank white page. The file is offered through the share sheet (**Save to Files**); when the download took long enough for the tap to expire, a message with **Save** appears instead. The picture and PDF preview in **Files** downloads the same way.
- A notification that replaces an earlier one for the same session (or a repeated test) alerts again in Safari on iPhone and Mac: the earlier one is closed first, because Safari replaces a notification with the same tag silently.

## 1.36.0 — 2026-10-10

- Session strip, bottom row: **new conversation** and **restart** moved to the left, slightly larger and further apart; the context bar moved to the right, and before it a clock shows how long the conversation has been running (from the first timestamp in the agent's conversation file). `/api/session_info` returns it as `started`.
- The closed summary under the session bar takes two or three lines: its headline and the first sentence of the description; a tap still shows all of it.

## 1.35.0 — 2026-10-10

- The context bar's limits are set in **Settings → General** (this browser): yellow from 80k and red from 150k tokens by default (red was 160k). No official number exists; Claude Code users most often report the quality drop around 150k.
- Every file in **Files** has a download button right in the list, so a video, an archive or a huge log downloads without opening it first.

## 1.34.0 — 2026-10-10

- Session strip: under the session bar a quiet one-line summary of what the conversation is about (tap for a few sentences and when it was written); at the bottom, where the session tabs were, how full the context is (green, orange from 80k tokens, red from 160k; Codex also against its window) next to **new conversation** and **restart** icons. Read from the agent's own conversation file (Claude Code, also on Kimi or LM Studio, and Codex); the summary is written by a model of the same provider as the session, at most every 5 minutes while the session is open. New endpoint `/api/session_info`.
- The bottom row of session tabs is gone; sessions and **Waiting for you** are in the menu.

## 1.33.1 — 2026-10-10

- The phone project drawer no longer blinks or jumps back when a swipe lets go (half way or at the end) and slides in when opened with its button: the fade-in all dialogs share also moved it and restarted on every release, overriding the slide.
- The phone project drawer moves on its own compositor layer, isolated from the page, so iOS does not repaint a long diff on every frame of a swipe; the check for new changes on reopening waits until the drawer has slid in and the finger has let go.

## 1.33.0 — 2026-10-10

- The phone project drawer opens as smoothly as the menu on the left: closed, it now stays laid out past the right edge instead of being re-laid out on every swipe (with a long diff that took most of a second on a phone). On a phone it is no longer a modal dialog; the dimmed area beside it closes it, as with the menu.
- The code font size moved to **Settings → General** (Этот браузер); on a phone the A−/A+ buttons are gone from the project drawer and its five tabs share the full width. A wide screen keeps A−/A+ in the panel.

## 1.32.0 — 2026-10-10

- On a phone the project drawer keeps its tabs at the bottom, under the thumb, and diffs and files show one narrow line-number column (the new number, or the old one for a removed line) with less padding, so code gets most of the width.
- The phone project drawer moves as smoothly as the menu: reopening it keeps what it showed while a quiet check runs (no "Loading…" and full redraw mid-swipe), it slides out when closed, and letting go of a half-open drag no longer restarts the slide from the edge.

## 1.31.1 — 2026-10-10

- On a phone the right-hand project drawer is as wide as the menu on the left (it covered almost the whole screen).

## 1.31.0 — 2026-10-10

- On a phone the project panel (changes, commits, feature groups, files, gallery) is a drawer on the right, mirroring the menu on the left: it follows a swipe from the right edge, closes with a swipe back or a tap beside it, and the sidebar button at the top right toggles it. The session bar keeps only search, **⋯** and that button; the separate files and history icons are gone.

## 1.30.0 — 2026-10-10

- Gallery: a fifth tab in the project panel shows every picture the session's agents showed on screen, newest first, three per row, with the full-screen viewer to swipe through them. The panel keeps a private copy of each picture as it appears, so screenshots no longer vanish when the path scrolls away, the screen is redrawn, or the agent overwrites or deletes the file; the thumbnails under the output use that copy too. Up to 200 pictures and 300 MB per session, kept 30 days. Connected computers need this version for their gallery.

## 1.29.1 — 2026-10-10

- A session no longer disappears when the computer runs out of memory (Linux). systemd stopped the whole tmux session, shell included, when the kernel killed one of its processes, so a heavy agent with subagents and test stands could take its tab with it. The panel now tells systemd to end only the killed process (`OOMPolicy=continue` for tmux sessions and `cc-tmux.service`); the session stays and the agent can be started again with its conversation.
- Feature groups ask Claude Haiku from one fixed empty folder (`~/.cache/agent-deck/feature-groups/model`) instead of a new temporary folder each time, which Claude Code kept as a new empty project.

## 1.29.0 — 2026-10-09

- Any file can be downloaded: a file path an agent prints on the Screen (`/home/me/trip/plan.pdf`, `src/app.py`) is a link that downloads the file, and Project files offers **Download** for text files and for files it cannot show (archives, spreadsheets). Inside the home folder only, never the panel's settings, up to 40 MB; also for sessions on connected computers (they need this version too).

## 1.28.1 — 2026-10-08

- Feature groups are written in the panel's language: a repository nobody opened yet uses the language last seen in the panel instead of English, and groups written in another language are sorted again in the current one.

## 1.28.0 — 2026-10-08

- Feature groups are a tab of their own in the project panel and are always ready: the panel sorts new commits into features in the background, a few at a time, instead of regrouping 80 commits on a button press and dropping the result at the next commit. **Now** on top shows who works on what (each author active in the last 7 days and the feature of their latest commit); commits not sorted yet are listed as plain commits; groups show their authors, commit count and last change. A pass waits until the newest commit is 10 minutes old (or 20 wait); **Sort now** skips the wait.
- The repositories of this computer's sessions are fetched quietly every 15 minutes, so a collaborator's pushed branches appear without "Fetch from GitHub".
- Grouping models are tried in a fixed order: Claude Haiku (`claude -p`, no tools) and Codex's light model (`codex exec`, read-only sandbox without network), both on the subscription in an empty folder, then Kimi, then the first LM Studio model. The model picker is gone. Only subjects, authors and file names are sent, never code.
- BREAKING for connected computers on different versions: `GET /api/git/models` is gone, `/api/git/groups` answers with `now`, `pending`, `groups` and `commits` instead of `phase` and `head`, and the `git_group` action ignores `model` and `ref`. Feature groups of a connected computer need this version on both sides; an older one shows a note asking to update it.

## 1.27.0 — 2026-10-08

- Switching computers no longer waits for a message to be sent: it keeps going to the computer it was typed on, and once it arrives its text and attachments leave that computer's draft, so nothing comes back on return. If it fails, the draft stays and a notice says so.
- Security: a terminal link may only name one session. ttyd runs with `-a`, which appends every `arg` of the URL to `tmux attach -t`, and a bare `;` there chains any tmux command such as `run-shell`; a crafted link opened while logged in would have run a command on the machine. The panel and the gateway now refuse terminal URLs with anything but a single `arg=cc-<name>`. Update every computer: the check runs on the deck that owns the terminal.
- Security: the panel, its login page and the terminal can no longer be framed by another page (`X-Frame-Options: SAMEORIGIN`, `frame-ancestors 'self'`); another service on the same host could otherwise hide a terminal in an invisible frame and catch keystrokes.
- Security: text sent to an agent cannot end its paste early with a paste marker nested in another one; markers are removed until none is left.
- Security: the installers run Python as root in isolated mode (`-I`), so a module planted in the current folder is never imported; the static ttyd build is checked against a pinned SHA-256 before it is installed.
- Security: a connected computer can no longer exhaust the gateway's memory or stall question delivery for all computers: background polls accept at most 8 MB, other answers 48 MB, and every answer has a total deadline, not only a per-read timeout.
- A malformed login cookie (non-ASCII bytes) is a refusal instead of a server error; the login page escapes the user name and the error text.

## 1.26.4 — 2026-10-08

- Quieter logs and browser console: idle connections that the browser or proxy leave open no longer log "Request timed out" (hundreds of lines a day), a connection that times out before its first request no longer prints a traceback, and a picture an agent mentions that is not on disk answers the thumbnail with an empty 204 instead of a red 404 (opening it still says it is missing).

## 1.26.3 — 2026-10-08

- Text screen: the physical keyboard drives an agent's menu again — digits 1–9, Enter, Esc, arrows, Tab and Shift+Tab go to the session (as the on-screen keys do) whenever no field, menu or dialog has the focus, also for prompts the panel does not recognise as a question.

## 1.26.2 — 2026-10-08

- How it works is now a network topology with icons: you and your domain outside, then a private Tailscale network with three computers in different countries (the gateway with two agents, a laptop with its own Agent Deck and three agents, a workstation with LM Studio), links named by protocol and the internet services they call; three lines below explain Tailscale, the domain and several instances. The README shows the same topology. Phones scroll the diagram sideways.

## 1.26.1 — 2026-10-08

- How it works (the **?** next to search) is now an architecture diagram: your Tailscale network, your computer with the panel, ttyd, tmux, agents, projects and the private settings folder, and the internet services, with the protocol on each link. The README diagram shows the same zones.

## 1.26.0 — 2026-10-08

- A **?** next to the search field (in the sidebar on a phone) explains how Agent Deck works with a small diagram and how to check results remotely; the README has the same diagram. The search field no longer widens on focus.
- Sidebar: every computer heading and project heading has a **+** (on hover; always shown on touch screens). It opens the new session form on that computer, and for a project with its folder already chosen.

## 1.25.1 — 2026-10-08

- Desktop: the **⋯** menu opens under its button again instead of at the window's right edge over the project sidebar.

## 1.25.0 — 2026-10-08

- Session bar, tidied: the Link button is gone (links in the output open on a tap); on desktop the Files and History icons give way to the project sidebar, whose tabs are now icons. Output search is a field in the bar on desktop (the search icon opens it on a phone) with results in a card under it instead of a dimmed full-screen dialog.
- The **⋯** menu keeps what is used: restart with a new conversation, restart continuing it, duplicate the session with a new conversation (same folder, agent, permissions and model), rename and close; an update or closed-session drafts appear there only when they exist. Terminal in a new tab and New terminal in this folder are removed; the live terminal mode is a **Terminal** toggle among the keys.
- The sidebar keeps the place of limits and local models while they load (a skeleton the size it had last time), so the session list no longer jumps.
- Changes checks again every 15 seconds while it is on screen, so the agent moving to another worktree or a new edit appears without a tap; it never redraws under a comment being typed.
- Diffs open by themselves only for source code (up to 8 files, none over 600 changed lines); tests, translations, docs, configs, generated and vendored files stay folded until tapped. The same rule applies to Changes, a commit and a feature group.
- Telegram: when the same bot is still on on a connected computer, the warning offers **Turn off on <computer>**; the Telegram card's **⋯** menu disconnects the bot here.

## 1.24.0 — 2026-10-08

- Changes and Commits follow the worktree the agent works in: the panel looks for the last worktree the agent named in its output (its path or its branch) and shows that tree, marked "auto"; with several worktrees a quiet picker in the Changes header lets you choose one by hand. The output itself never leaves the server.
- A dialog no longer gets a blue outline around the whole window after a button inside it disappears (Update all in Settings → Computers).

## 1.23.3 — 2026-10-08

- Changes is more compact: repository and branch on one line with an icon refresh button; a clean tree shows one short note and the last commit's subject, author and time (the full message stays in Commits).

## 1.23.2 — 2026-10-08

- Commit rows are calm again: no coloured background or stripe, a neutral highlight on hover; only the author's name keeps its colour.

## 1.23.1 — 2026-10-08

- Desktop: a sidebar button at the right end of the session bar, mirroring the one on the left, shows and hides the project panel on its last tab.

## 1.23.0 — 2026-10-08

- Changes, Commits and Files are one project panel with three tabs. On desktop it is a right sidebar that the folder and git icons show and hide; it stays open across session switches and is remembered in this browser. On a phone the same icons open it full screen. Changes shows the last commit when nothing is uncommitted; Feature groups moved to a button in Commits.
- On desktop both sidebars (sessions on the left, project on the right) can be resized by dragging their inner edge or with the arrow keys on it; a double click restores the default width. Widths are remembered in this browser.

## 1.22.10 — 2026-10-08

Fixes from a four-way review (backend and installers, settings, the rest of the interface, security) of everything released on 2026-10-07.

- **Security:** Changes in history never shows the panel's own folder (`~/.config/cc-panel`) when the home folder is a git repository. A diff line quoted into a comment loses hidden control characters, and paste markers inside sent text are removed, so repository content cannot end a paste early and act as keys (Esc, Shift+Tab) in an agent. Git reads take no optional locks (an agent's `git add` no longer fails on `index.lock`) and never start a repository's `core.fsmonitor`.
- Images named without a folder are searched only inside a project folder under home, never in the home folder itself, hidden or personal folders (`Documents`, `Library`, …), reading folders lazily.
- Output search cuts multi-megabyte lines around the match; a stuck tmux is a clear error. The working-tree diff has a time limit; repositories using SHA-256 without commits work.
- macOS installer: Intel Macs (Homebrew in `/usr/local`) install again; the fix-up hint names only Homebrew's own folders. Windows installer: a host that refuses UTF-8 output (PowerShell ISE) no longer aborts the installation.
- Settings: a background refresh no longer steals focus or the phone keyboard from an editor being typed in, and never overwrites fields being edited; opening the Kimi or Telegram editor no longer reloads the dialog. Unsaved changes are judged per editor (no false "unsaved" prompts, no silently dropped edits), and Escape closes the editor of the section on screen. Backups, a recovery code and an update entry no longer carry over to another computer; backup errors toast only in Backups. Getting started ignores steps that cannot be done here (no HTTPS). The Telegram switch is not undone by polling; notification events can be set from any device; the "encryption components" state refreshes by itself.
- Desktop and iPad with a keyboard keep the typing focus when switching tabs (the iOS keyboard fix now applies to touch devices only). Option+K types "˚" on a Mac again (Cmd+K opens the switcher). New session on another computer never opens on the current one when the switch is refused. A diff comment always goes to the session whose history is open. Output search drops a late answer from the previous session. Large Markdown headings with long runs of spaces render at once; a 10 MB preview decodes without freezing; preview memory is freed when Files closes. The drop frame no longer blinks during a held drag and ignores pictures dragged from the page. A failed thumbnail is retried after a minute, per computer, and not after an offline moment. The message field stays correct when it is off screen or loses lines.

## 1.22.9 — 2026-10-07

- The message field no longer creeps while typing (seen in desktop Safari): its height now includes the border, so it never ends up 2 px short and scrolled, and it is re-measured only when a line is added or text is removed instead of collapsing on every key.

## 1.22.8 — 2026-10-07

- Computers: a machine found on Tailscale that is already connected shows "Connected" (or "Connected as …" when it was added under another name) with an Open button, instead of offering to connect it again. Machines are matched by address, not name.

## 1.22.7 — 2026-10-07

- Windows: the panel opens on the PC itself. Mirrored WSL networking does not let Windows reach a WSL server on the PC's own (Tailscale) address unless `[experimental] hostAddressLoopback=true` is set; the installer now adds it to `.wslconfig` (other settings kept, a backup saved) and restarts WSL once. A `localhostForwarding` line, which mirrored mode ignores and warns about, is commented out.
- Windows: WSL and Ubuntu output is shown in UTF-8 instead of garbled characters.
- Codex CLI installs without asking "Start Codex now?" (Linux, Windows/WSL, Docker and the in-panel installer), which stopped the Windows installation until a key was pressed.
- The installer no longer prints a connection error while the panel is still starting; it reports only if the panel never answers.

## 1.22.6 — 2026-10-07

- A connected computer without sessions shows a "New session" button in its sidebar section: it switches to that computer and opens the new-session dialog.

## 1.22.5 — 2026-10-07

- macOS installer installs only what is missing and never upgrades tools that are already there (tmux, gh, Python, Claude Code, Codex). On a Mac where Homebrew belongs to another account it no longer fails halfway with Homebrew's permission list: if nothing is missing it just continues, otherwise it names the owner, lists what to install and shows the two ways to fix it. Python 3.10+ is checked before use.

## 1.22.4 — 2026-10-07

- iPhone: switching to another app with the keyboard open no longer leaves an empty band where the keyboard was. The page drops focus when it goes to the background, measures the screen again a few times on return, and ignores a keyboard height iOS keeps reporting while nothing is focused.
- Images an agent names without a folder (Codex: "Viewed image shot.png") now show: a bare name is looked up in the session folder, a few levels deep, skipping links and dependency folders, newest match first. A picture that cannot be loaded is not retried on every screen refresh for five minutes, so its empty thumbnail no longer blinks.

## 1.22.3 — 2026-10-07

- Quota plan counts days of the limit window, not calendar days: a weekly limit is split into 7 equal days from its reset, so the plan steps by sevenths (86%, 71%, …). It used to aim at the browser's midnight, which gave values like 90% on the first day of a week that started in the morning. The explanation under the quotas says so.

## 1.22.2 — 2026-10-07

- Switching computers no longer moves the sidebar: each computer's last known address is cached in the browser and shown at once (a skeleton only the very first time), then refreshed in place.
- "Waiting for you" is an icon with a number at the right of the address line, in a row of fixed height.
- Sessions of other computers in the sidebar are grouped under their project headings, as on the selected one.

## 1.22.1 — 2026-10-07

- Sidebar stays still when switching computers: the address line keeps its place (dimmed until the new computer answers) instead of collapsing and reappearing.
- "Waiting for you" is a fixed icon with a count in the search row instead of a bar that appeared above the session list and pushed it down.
- Change history colours each commit row by its author (blue, orange, purple first, so the first few people never look alike); a person keeps their colour in this browser, also on the commit page.

## 1.22.0 — 2026-10-07

Settings redesigned after a five-way review (structure, copy, visual design, phone and accessibility).

- **Sections say what they hold:** Agents (Claude, Codex, Kimi with its key, Pi, GitHub), Notifications (devices and Telegram), Local models (LM Studio only), Computers (other Agent Decks first, then this computer's address), Backups, General (this browser, new sessions, version and updates). "Computer" now always means another Agent Deck; LM Studio is a "server". With other computers connected, the title names the one being configured.
- **One card pattern:** icon, title, a coloured status (works / needs a step / broken / off), address or version, one main action and a ⋯ menu for the rest. Editors open in place of the card they edit; removing something is always red, on the left, and asks first (LM Studio servers, connected computers, other devices' notifications).
- **Getting started:** a card with three steps (sign in to an agent, notifications on this device, backups) until they are done or hidden, and a dot on every section that needs attention.
- Signing in or installing an agent closes Settings so its session is visible. Escape first closes an open editor and asks before dropping a typed key or password.
- Clearer states and fixes: "Not signed in" instead of a second "Log in", "first token" instead of TTFT, no "No limits" label, an unreachable LM Studio says how to start its server, notifications that need HTTPS point to the public address, Telegram's update hint names the real place. Restore folds into one link while there is nothing to restore.
- Phone and iPad: buttons never break inside a word, the active section stays visible in the tab row (fades on both sides), a section opens at its top, the ports field takes commas, logins are not capitalised, keys and tokens are no longer offered as new passwords, touch iPads get 16 px fields and finger-sized controls; tab list semantics, labelled list buttons and status announcements for screen readers.
- About 135 strings per language that were still English in 14 locales are translated; the Spanish "complete installation" label no longer says "installation complete".
- **Sidebar:** computers keep one order whichever is selected; switching only moves the highlight instead of reshuffling the list.
- **Drop files onto the window** (desktop, iPad Split View) to attach them to the open session, including over the terminal; a frame shows where they will go or why they cannot.

## 1.21.0 — 2026-10-07

- **Uncommitted changes with comments for the agent:** Change history opens on a new Changes tab — what the agent changed since the last commit (staged, unstaged and new files git does not ignore), read-only. Tap a line, write a comment, and it is added to the session's message as `file:line`, the quoted line and your note; send it when ready.
- **Search in session output:** a search button in the session bar finds text in the whole terminal output including scrollback, newest first, with two lines of context and a copy button.
- **Quick switcher:** Alt+K (anywhere, also inside the terminal), Ctrl+K or ⌘K opens one field for the sessions of this and every connected computer and for common actions.
- **Project files:** Markdown opens rendered (switch to text to read or edit the source); PNG, JPEG, WebP, GIF and PDF up to 10 MB open as previews, checked by content, with Download and, for PDF, Open in a new tab.

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
