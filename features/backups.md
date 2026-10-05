# Backups of Agent Deck settings and keys

Goal: a dead or replaced computer comes back with its Agent Deck settings, integration keys and agent logins; copies live on the other connected Agent Decks.

## Decisions

### Contents (paths relative to `$HOME`)
- Agent Deck: `kimi.json`, `network.json`, `projects.json`, `update.json`, `integrations/telegram.json`, `integrations/lmstudio.json`, `integrations/decks.json`, `kimi-native/config.toml`, the instance id.
- Agent logins: `~/.claude/.credentials.json` (Linux; on macOS Claude keeps it in Keychain — log in again), `~/.codex/auth.json`, `~/.config/gh/hosts.yml`.
- Not included: panel login (`env`: also holds machine-specific bind address/socket; the installer sets login and password), `secret`, `sessions.json` (refers to local folders/conversations), uploads, caches, logs, relay tokens, per-session Pi/model bindings, Kimi conversation history.

### Encryption (stdlib only, no new dependencies)
- One random 256-bit backup key per user, shown once as a recovery code (`AD1-…`, base32 with a checksum). Stored on each instance as `~/.config/cc-panel/backup-key` (0600) so daily backups run unattended.
- Sealed file: plaintext header (format, origin id/name, created, app version, key id — no secrets) + keyed-BLAKE2b counter-mode keystream + keyed-BLAKE2b tag over header and ciphertext (encrypt-then-MAC, separate derived keys, 24-byte random nonce).
- Size cap 768 KB per sealed backup (fits the 1 MB JSON request limit as base64).

### Storage and replication
- Every instance with a key makes a local backup daily and on demand; keeps the last 14 per origin in `~/.config/cc-panel/backups/<origin-id>/` (0700/0600).
- The gateway (the instance with connected decks) orchestrates: sets the same key on connected decks, asks each for a fresh backup, then stores every backup on every other instance. Instances only ever see ciphertext of others.
- Older/unreachable decks are reported per machine, never block the cycle.

### Restore
- From a copy on this machine, on a connected deck, or an uploaded file; the recovery code is needed only when this machine has no key yet.
- The gateway can restore a backup onto a connected machine (fresh install replacing a dead one).
- Before restoring, the current state is backed up locally. Files are written only to their whitelisted destinations (archive names never become paths), 0600, then the panel restarts (systemd `Restart=always` / launchd `KeepAlive`; tmux keeps running).

### API
- `GET /api/backups`, `GET /api/backup_blob?origin=&created=`
- `POST /api/backup_setup {code?}`, `backup_now`, `backup_run`, `backup_store {meta, blob}`, `backup_restore {origin, created, deck?, blob?, code?}`, `backup_restore_remote {deck, origin, created}`

### UI
- Settings → Backups: enable (show code once, confirm saved) or enter an existing code; status per machine with last backup; "Back up now"; download this machine's backup; restore list per source with target selection on the gateway.
