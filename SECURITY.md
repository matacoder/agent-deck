# Security policy

DeckAway gives a shell to whoever signs in, so a flaw in it is a flaw in the computer it runs on.

## Reporting a vulnerability

Please do not open a public issue. Report it privately through
[GitHub security advisories](https://github.com/matacoder/deckaway/security/advisories/new) with the
version (shown in Settings, or `/opt/cc-panel/VERSION`), the platform, and the steps to reproduce it.
A fix is released as soon as it is ready, and the advisory is published with it, crediting you unless
you prefer otherwise.

## Supported versions

Only the latest release. The panel updates itself from Settings, so a fix reaches installations without
a new install.

## Scope

In scope: the panel and its API, the terminal proxy, the gateway and connected computers, the
installers and the updater, Telegram and Web Push, backups.

Out of scope: what an agent itself does once it is allowed to act. Out of scope too: an attacker who
already has the password or a valid sign-in, and setups that publish the panel on the internet without
the HTTPS proxy described in [docs/install.md](docs/install.md).

How the panel is protected is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#trust-boundaries).
