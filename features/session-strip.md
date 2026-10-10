# Session strip: summary, context fullness, restart

The user wants to see, for the open session, what the agent is doing and when the conversation has grown
too big, with one tap to start over. The bottom row of session tabs goes (sessions stay in the menu).

## Placement
- Under the session bar: a quiet one-line summary (muted, like a hint). A tap expands the full summary and
  when it was written; the choice is remembered in this browser.
- Where the session tabs were (bottom): how full the context is (a short bar and "166k"), and two icons:
  new conversation in this session (restart, new) and restart with the same conversation. Same confirms as
  the ⋯ menu. On a wide screen the row sits under the message field.
- Hidden for shells and agents whose conversation files are unknown (Pi, Kimi Code); a computer without this
  version shows nothing.

## Context ("загрязнённость")
- Read from the conversation file, tail only: Claude's last answer usage (input + cache read + cache write +
  output), Codex's last `token_count` (and its context window).
- Levels by size, not by the window, because quality drops long before the limit: under 80k fine, under
  160k getting heavy, above that time for a new conversation. Codex shows % of its window too.

## Summary
- Written by a model of the same provider as the session, so the conversation does not go anywhere new:
  Claude on the subscription → Claude Haiku; Codex → Codex Luna; Claude on Kimi → Kimi; on LM Studio → the
  same local model. No fallback to another provider.
- Input: the last user messages and agent replies as text (no tool output), at most ~12k characters.
- Rewritten only when the conversation grew and the last summary is 5+ minutes old, and only while someone
  looks at the session; in the background, one at a time. Kept in `~/.cache/agent-deck/summaries/`
  (0700/0600), per conversation and language; a new conversation starts empty.
- In the panel language: 1 short line (shown collapsed) and 2–4 sentences.
