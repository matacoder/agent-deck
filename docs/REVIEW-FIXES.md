# Review fixes — 2026-10-02

Claude reviewed commit `63584c4`. Release 0.2.0 addresses its 15 findings:

| Finding | Change | Regression coverage |
| --- | --- | --- |
| 1. Root trusts user-writable code/files | Root-owned protected checkout required; home/runtime writes run as the panel user | Installer guard and actual unprivileged symlink writes in a disposable container |
| 2. Literal tmux input loses flags/semicolons | stdin buffers and serialized input per session | Real private tmux server compares exact input bytes |
| 3. Deleted session transfers drafts | Common activation; closed drafts recoverable; removed attachments cleared | Session disappearance with two drafts and an image; immediate kill fallback |
| 4. Sibling-origin CSRF/WebSocket access | JSON mutations, origin checks and ttyd `-O` | API/login/logout/WS rejection and valid WebSocket byte forwarding |
| 5. Wrong conversation resumed | Saved UUIDs for both agents; missing IDs fail before stopping; no guessed fallback | Distinct Codex IDs in one project; missing-ID restart |
| 6. Excessive/overlapping polls | One metadata call, only selected preview captured, hidden pages paused, serialized polls | Backend call count; delayed responses and hidden-page browser checks |
| 7. Login throttle races/grows | Locked reservations before body reads; expired entries removed; global/per-IP limits | Five simultaneous delayed bodies block the sixth attempt |
| 8. Ambiguous terminal targets | Exact `=cc-name` targets for iframe and popout | Browser URL checks |
| 9. Uploads retained forever | Explicit discard, session deletion cleanup, seven-day TTL for deferred agent reads | Scoped deletion, retention and symlink boundaries |
| 10. GitHub login has wrong agent | Login utility uses a shell session | Backend session tag check |
| 11. Dropped malformed requests/errors | Validated body lengths; JSON 400/500; bounded connection timeout | Malformed lengths and unexpected backend/action exceptions |
| 12. Colored wrapped URLs truncated | Join ANSI runs before safe link rendering | Complete styled URL in both browsers |
| 13. Wrong desktop Enter hint | Device-appropriate send hint | Desktop hint and existing send behavior checks |
| 14. Login expiry loses input | Persist text, session, drafts and image IDs before redirect | Login-page round trip with text/image restoration |
| 15. Nested review overwrites session ID | Hook checks top-level process ancestry; registration preserves user hooks | Root versus nested hook ancestry and idempotent registration |

CI also checks Python 3.10/3.12 and shell scripts with ShellCheck. Browser fixtures now
serve active-only previews like production. Tests use temporary credentials and a separate
tmux socket, never production sessions.

Codex needs the newly registered user hook reviewed/trusted on first launch. Legacy sessions
without a recorded conversation ID require manual selection with `codex resume`; a reboot
restores those sessions to a recovery shell rather than opening an unrelated conversation.
Native iPhone keyboard/status-bar rendering still needs a physical-device check; emulation
covers layout, viewport resizing and pinch-zoom guards.

One-click release updates install the panel as its unprivileged user, with exclusive jobs,
validated release archives and rollback after failed startup. The initial installation and
changes to system packages, proxy configuration or user-service definitions use the protected
root installer. Ordinary deployment updates hooks and service definitions without root.
