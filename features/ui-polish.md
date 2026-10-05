# UI polish: design review fixes (iPhone 15 Pro Max first)

Source: design/UX review of 2026-10-05. Primary device: iPhone 15 Pro Max (430×932 pt), installed as a home-screen app.

## Decisions

### Answer questions with one tap
- Reuse the existing question parser and `answer_question` (Telegram path) — no new parsing.
- `GET /api/question?name=` returns the active question of one session (structured transcript question first, then the screen menu); `POST /api/answer {name, id, index}` answers by fingerprint, so a changed question fails closed.
- Options that need free text (Other / Type something) are not buttons; the key row stays for manual input.
- The question card sits above the composer; the key row remains as fallback.

### Mobile layout
- "Mobile" = width ≤ 760 **or** a coarse pointer with height ≤ 500 (phone landscape keeps the phone layout and safe-area insets).
- Keyboard open: hide quick tabs and the status line, compact the top bar.
- Enter key hint is "enter" (mobile Enter inserts a newline; the send button sends).
- Touch targets ≥ 44 px for keys, quick tabs, segment, send/attach.
- Quick tabs end with "+ new session"; long-press a tab opens its actions.
- Toasts appear at the top on mobile, are announced (`aria-live`) and errors stay until dismissed or 8 s.
- "Jump to latest output" button when the preview is scrolled up.
- Autocorrect in the message field is an opt-in setting (off by default: iOS smart punctuation would change `--` and quotes).
- Login and app use the same status-bar style.

### Actions
- Desktop top bar: title, Screen|Term segment, contextual link, "⋯" menu. The menu is the same list as the mobile sheet (popover on desktop).
- Sheet groups: session actions → app actions → "Close session" last before Cancel.
- Native `confirm()` replaced with one styled confirm dialog.

### New session dialog
- Agent picker in one row; Kimi gets its glyph.
- Git URL / worktree / branch move under "Advanced"; branch shows only with worktree on.
- Skip-permissions checkbox is styled as a warning.

### Settings
- Kimi and Telegram editors open inside their cards (no duplicated heading block).
- Language applies on change.
- Deck switcher in the sidebar only when other decks are connected.

### Visual system
- Contrast: text tokens meet WCAG AA on sidebar/background; primary buttons use a darker blue for white text; minimum text size 11 px.
- One blue scale as tokens; no hardcoded duplicates.
- Inline SVG icons instead of emoji/glyph buttons.
- style.css consolidated: one definition per component, one mobile media block.
- Sessions in the sidebar show state as text, not only colour; rows are keyboard-focusable.
- Sidebar monitor re-renders only when its content changes.

### Out of scope
- Streaming uploads (JSON base64 protocol stays; upload progress is shown instead).
- Web Push notifications.

## Follow-up (after UI polish) — done in 1.4.0
- Telegram: one bot for several Agent Deck instances. Today each panel long-polls `getUpdates`, so a second instance fails with "bot is already used by another update receiver". Investigate why a panel must own the update stream instead of, e.g., one owner routing answers (deep links / callback data with instance id) to the others.
- Sessions from all connected Agent Deck instances in one sidebar on the gateway, grouped by instance. Feasible on the existing `/deck/<id>/api/sessions` gateway route: poll remote lists without previews at a slower pace than the active instance; selecting a remote session switches instance and opens that session. Step 1 reuses the current reload-based switch (pre-set the target's `cc.active`); step 2 removes the reload by making the instance per-request instead of page-global.

### Decisions (1.4.0)
- Only the gateway owns the bot (Telegram allows one update receiver). It scans connected instances via `/deck/<id>/api/questions` (5 s timeout, 30 s backoff for unreachable or older instances) and answers via their `/api/answer` using the remote fingerprint; transport failures are `uncertain`, never replayed.
- Sidebar: other instances refresh every 10 s without previews; switching keeps the reload-based instance switch and pre-selects the session.
- In-place switch (1.4.1): per-computer state is reset by `resetInstanceState()` and restored by `restoreInstance()` (same code as page load); an epoch counter drops responses for the previous computer.
