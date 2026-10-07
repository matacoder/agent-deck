# Workspace tools (ideas from Orca)

Four small tools around a running session. No new dependencies, every route is JSON so connected
computers work through the gateway unchanged.

## 1. Uncommitted changes with comments for the agent
- New first tab "Changes" in History: working tree against HEAD (staged + unstaged), plus untracked
  files that are not ignored. Read-only: never `git add -N` or any index change.
- Untracked files: one `git diff --no-index` each, at most 50, files over the per-file limit are listed
  without a patch (never read into memory).
- A repository without commits diffs against the empty tree.
- Tapping a diff line opens a comment field; "Add" appends `path:line` + the line + the comment to the
  session's message draft. The draft is the only storage, so it survives reload, language switch and
  computer switch like any draft. Nothing is sent automatically.

## 2. Search in session output
- `/api/scrollback`: whole tmux scrollback (`capture-pane -J -S -`), plain case-insensitive substring
  (no regex: no ReDoS), newest first, 200 matches max, 2 lines of context.
- Button in the session bar, dialog with results; a result can be copied. Jumping inside the terminal
  (copy-mode) is left out: it blocks agent input until the mode is closed.

## 3. Quick switcher
- Alt+K anywhere, Ctrl/Cmd+K outside the terminal (Ctrl+K is kill-line in shells).
- Sessions of this and connected computers, plus actions (new session, files, history, output search,
  settings). Substring match on every word; arrows, Enter, Esc.

## 4. Markdown, images and PDF in Files
- `.md` opens rendered (own small renderer, DOM via textContent, links only http/https/mailto), with a
  toggle to raw text and editing as before.
- Images and PDF: `/api/file_blob` returns base64 JSON after a content check (PNG/JPEG/WebP/GIF magic,
  `%PDF-`), max 10 MB; the browser builds a Blob of exactly that type (never HTML/SVG). PDF opens in a
  new tab from a link (a user gesture, so no popup blocker) or downloads.
