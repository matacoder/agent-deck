# Contributing

Issues and pull requests are welcome. A change goes in more easily when it is small, has a test,
and keeps the rules in [AGENTS.md](AGENTS.md). The rules are written for people and for coding agents
alike.

## Set up and check

```bash
npm ci
python3 scripts/build-panel.py          # after editing anything in frontend/
python3 scripts/build-panel.py --check && npm run test:all
```

Python 3.10 or newer and Node 22 are enough. The tests use temporary folders and fake commands, so they
never touch your tmux, your settings or the network. Browser tests and other checks are described in
[docs/TESTING.md](docs/TESTING.md). CI also runs `ruff check .` and ShellCheck on every `*.sh`.

## What to keep in mind

- **Standard library only.** No new Python or npm runtime dependencies; `cryptography` is the single
  pinned exception.
- **New backend code goes into `integrations/`.** List each new module in `PACKAGES` in `panel/updater.py`,
  or installed updaters reject the release. Never add a file to `panel/`.
- **Every interface string goes into all 16 files in `locales/`.** An English value is fine for languages
  you do not speak.
- **Installed paths and settings files keep their names.** Changing them needs a major version and a
  migration.
- **Behaviour changes get a line in [CHANGELOG.md](CHANGELOG.md).**
- **Security-sensitive changes** (sign-in, the proxies, the gateway, installers) need a test that shows
  the attack failing, not only the feature working.

The architecture is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
