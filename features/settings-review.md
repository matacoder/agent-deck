# Settings review (2026-10-07)

Five review passes: information architecture, copy and first run, visual design, phone/touch and
accessibility, plus 388 screenshots (desktop / iPhone / iPad, en / ru) in /tmp/ad-settings-review/shots.

## Root causes
- Tab names do not predict content: "Connections" = notifications + GitHub + Telegram, "Network" = panel
  address + other computers, "App" = a mix of browser, server and update settings.
- "Computer" means two things: an LM Studio server (Models) and another Agent Deck (Network).
- One task is split across places: Kimi (agent in Agents, key in Models), notifications (push and Telegram
  in Connections, HTTPS in Network), updates (sidebar, menu, App, fleet in Network).
- Scope is invisible: settings mix this browser, the selected computer and the gateway under one title.
- No common card pattern: six different layouts, status as grey text, `.pri` looks different by place,
  delete has four looks, editors open far from the card they edit.
- About 100 strings per locale are still English in the 14 non-ru/en catalogs; es has a wrong meaning.

## Wave 1: fixes (small, no structure change)
- Translate the ~100 untranslated strings in 14 locales; fix es "Доустановить компоненты".
- Inputs: `lm_ports` text keyboard (comma), `deck_username` no autocapitalize, keys/tokens `autocomplete=off`,
  `deck_password` `current-password`, `enterkeyhint`, 16px/44px also on touch iPad.
- Buttons never break mid-word; destructive actions always red on touch and separated.
- Confirm before deleting an LM Studio profile; deck disconnect: same verb in title and button, name the computer.
- Hide Disconnect / Remove key until something is configured.
- Status wording: "not signed in" instead of "Log in"; "No limits" removed; TTFT -> "first token".
- Hints that say how to fix: LM Studio unavailable, push needs HTTPS (where to set it), Telegram "update" path.
- Tabs: active tab centred, left fade, scroll to top on switch.
- Close Settings after agent Log in / Install (the login session must be visible).
- No auto-focus of key fields on phones; Escape / close first closes an open editor.

## Wave 2: structure (renames and moves)
- Agents: Claude, Codex, Kimi Code (with its key editor), Pi, GitHub.
- Notifications: push + Telegram; HTTPS problem links to Computers -> public address.
- Local models: LM Studio only; "Add LM Studio server", "Find on Tailscale".
- Computers: other Agent Decks first (discover, connect, update all, isolation), then this computer's address.
- Backups: unchanged; collapse restore when nothing is configured.
- General: this browser (language, autocorrect), new sessions (project folder), version and updates, log out.
- Title shows the configured computer when another one is selected.

## Wave 3: card pattern
- One anatomy: icon, title, coloured status line, meta line, body, actions (danger left, one primary right).
- Section head with one-line intro; editors open in place of the card ("Edit · name").
- First-run "Getting started" card (sign in, notifications, backups) and dots on tabs that need action;
  Settings opens on the first such tab.
