# Unit tests

Run `npm ci` once, then `npm run test:all`.

`npm run test:backend` runs isolated Python unit tests with temporary settings,
mocked external commands and ResourceWarning checks. It excludes the legacy
real HTTP-server, tmux, installer-boundary and LM Studio relay integration tests.

`npm test` runs Jest with jsdom. It checks the actual shared frontend logic and
DOM handlers without starting browsers, installing services or using the network.
Coverage includes quota/calendar calculations, model names, project settings,
renaming sessions, failure/retry behavior and localization keys.

CI runs only Python unit tests on 3.10/3.12, the generated HTML check and Jest on
Node 22. It has no browser containers, macOS installation or E2E smoke jobs.

Legacy `*.spec.js` and integration-test sources remain as references for porting
regressions; they are excluded from normal test commands and CI. Screenshot
capture remains an optional manual developer command.

After editing frontend sources, run `python3 scripts/build-panel.py`.
