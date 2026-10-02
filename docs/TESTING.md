# Regression tests

Tests exercise the actual Python backend and the actual HTML/CSS/JavaScript in
`panel/index.html`. They do not require a running installation.

## Backend

Python 3.10 or newer; install `tmux` for the isolated terminal integration tests:

```bash
python3 -W error::ResourceWarning -m unittest discover -s tests/backend -v
```

Tests cover signed cookies, login and logout, proxy headers, request limits,
image validation and private storage, ordered Codex/Claude input, session
validation and restoration, ANSI capture, state persistence and cache retries.
Updater tests cover exclusive jobs, release/path validation, download failure, installation,
health-check rollback, downgrade prevention, and authenticated same-origin launch requests.
HTTP tests start a server on an ephemeral loopback port and test the terminal
proxy against a temporary Unix socket, including a WebSocket upgrade and
bidirectional bytes.

All credentials, uploads, state and secrets live in temporary directories.
Unexpected subprocesses and external HTTP calls fail the unit tests. The real tmux tests use a
private socket/server and compare exact input bytes, including leading dashes, semicolons,
Unicode and bracketed paste. No installed credentials or live tmux sessions are used.
Review regressions cover exact conversation IDs, top-level hooks, upload cleanup, active-only
capture, sibling-origin CSRF/WebSocket rejection, concurrent login reservations and JSON errors.
Root ownership and symlink write tests run in a disposable container; they skip on an unprivileged host.

## Frontend

Node.js 18 or newer:

```bash
npm ci
npx playwright install --with-deps chromium webkit
npm test
```

Or use the matching browser image without installing browsers on the host:

```bash
docker run --rm -v "$PWD:/work" -w /work \
  mcr.microsoft.com/playwright:v1.55.0-noble npm ci --no-audit --no-fund
docker run --rm --network none --shm-size=512m -v "$PWD:/work" -w /work \
  mcr.microsoft.com/playwright:v1.55.0-noble npm test
```

The Playwright package and Docker image are pinned to the same version. Update
both together, regenerate `package-lock.json`, and run both browser projects.

Each scenario runs in Chromium and WebKit with an iPhone device profile. Tests
cover portrait widths of 320/390 pixels, desktop layout, keyboard viewport
changes and hiding, usage meters, ANSI styles and safe links, separators,
session restoration, scrolling tabs, drafts, image uploads, retries, duplicate
send prevention, and safe automatic/manual updates.
Release-update scenarios cover progress, retry, duplicate clicks and preservation of unsent text
and attachments when reloading after installation.
Review scenarios cover disappearing sessions and draft recovery, login expiry, delayed polls,
hidden pages, exact terminal targets, colored wrapped links and pinch zoom.

Browser tests load the real page and intercept HTTP requests with isolated API
fixtures. Uncaught JavaScript errors fail the test. External requests are
blocked. Browser traces and screenshots are retained on failure:

```bash
npx playwright show-trace test-results/<failed-test>/trace.zip
```

WebKit emulation does not reproduce iOS system chrome, the native keyboard, or
installed-app status-bar effects. Check those on a real iPhone after changing
viewport or safe-area handling.

## CI

`.github/workflows/tests.yml` runs Python 3.10/3.12, ShellCheck, containerized root ownership checks
and both browser projects on pushes and pull requests.
Frontend failures attach screenshots, traces and an HTML report. No production
services are started or restarted by CI.
