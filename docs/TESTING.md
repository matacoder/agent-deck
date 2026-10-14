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

The browser specs (`tests/frontend/*.spec.js`, Chromium and WebKit on an iPhone
size) pass as of 1.54.0 but are not in CI or `npm run test:all`: they need a
Playwright browser, for example the `mcr.microsoft.com/playwright:v1.55.0-noble`
image with `npx playwright test`. Run them after a change to layout or flows.
`tests/backend/test_http.py` (a real server on a local port) is also outside
`test:all`: `python3 -m unittest discover -s tests/backend -p test_http.py`.
Screenshot capture remains an optional manual developer command.

After editing frontend sources, run `python3 scripts/build-panel.py`.
