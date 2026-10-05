# Notifications and the cryptography dependency

## Decisions
- Web Push (RFC 8030/8291/8292), no third-party push account: the panel keeps its own VAPID key in `~/.config/cc-panel/integrations/push.json` (0600) with device subscriptions.
- Only known push services are contacted (Apple, FCM, Mozilla, Windows) — an arbitrary endpoint would make the panel a request proxy.
- Events are detected on the gateway for local and connected decks: new question fingerprints; "finished" = output stopped for 8 s (25 s for remote, polled every 10 s) after at least 20 s of work, not for shells or sessions with a pending question. The first pass after a restart only learns state.
- The service worker is served from `integrations/webpush.py` at `/sw.js`; new files under `panel/` would break installed updaters.
- `cryptography` is the single allowed runtime package: pinned wheels with SHA-256, downloaded by `integrations/dependencies.py` into `~/.local/share/agent-deck/python/<cpXY-platform-digest>`; a system package is used only if the pinned one is absent. Intel macOS stays on 48.0.1.
- Backups moved to AES-256-GCM (ADBK2); ADBK1 stays readable.
