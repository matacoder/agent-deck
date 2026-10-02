const { test: base, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

const panelDir = path.resolve(__dirname, '../../panel');
const html = fs.readFileSync(path.join(panelDir, 'index.html'), 'utf8');
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1X8AAAAASUVORK5CYII=', 'base64');

function session(name, overrides = {}) {
  return {
    name, agent: 'codex', group: 'demo', path: '/home/test/projects/demo',
    command: 'codex', running: true, activity: 1, created: 1, attached: 0,
    preview: `Output from ${name}`, ...overrides,
  };
}

const test = base.extend({
  app: async ({ page }, use) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const app = {
      page, sessions: [session('tmux'), session('other', { activity: 2 }), session('shell', { agent: 'shell', command: 'bash' })],
      revision: 'fixture-version', sends: [], uploads: [], sendError: null,
      uploadError: null, sendGate: null, navigations: 0, usage: {},
      async open({ active = 'tmux', mode = 'screen', width, height } = {}) {
        if (width) await page.setViewportSize({ width, height: height || 844 });
        await page.addInitScript(({ active, mode }) => {
          if (active !== null && localStorage.getItem('cc.active') === null) localStorage.setItem('cc.active', active);
          for (const key of ['cc.mode.m', 'cc.mode.d']) {
            if (localStorage.getItem(key) === null) localStorage.setItem(key, mode);
          }
        }, { active, mode });
        await page.goto('https://panel.test/');
        await expect(page.locator('#title b')).toBeVisible();
      },
      holdSend() {
        let release;
        const promise = new Promise(resolve => { release = resolve; });
        app.sendGate = { promise, release };
        return { release };
      },
    };
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.hostname !== 'panel.test') return route.abort();
      const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
      switch (url.pathname) {
        case '/':
        case '/index.html':
          app.navigations++;
          return route.fulfill({ contentType: 'text/html', body: html.replace('__PANEL_REVISION__', app.revision) });
        case '/api/ui-version': return json({ revision: app.revision });
        case '/api/sessions': return json({ sessions: app.sessions });
        case '/api/agents': return json({ codex: { installed: true, logged_in: true, version: 'test' }, claude: { installed: true, logged_in: true, version: 'test' } });
        case '/api/github/status': return json({ connected: false });
        case '/api/usage': return json(app.usage);
        case '/api/version': return json({ version: '0.1.0', update: false });
        case '/api/server': return json({ hostname: 'test-server', ip: '192.0.2.1', tailscale_ip: '100.64.0.1', country: 'GB' });
        case '/api/projects': return json({ projects: ['demo'] });
        case '/api/upload': {
          app.uploads.push(route.request().postDataJSON());
          if (app.uploadError) return json({ error: app.uploadError }, 400);
          return json({ ok: true, attachment: `${String(app.uploads.length).padStart(32, '0')}.png` });
        }
        case '/api/send': {
          app.sends.push(route.request().postDataJSON());
          const gate = app.sendGate;
          app.sendGate = null;
          if (gate) await gate.promise;
          if (app.sendError) return json({ error: app.sendError }, 400);
          return json({ ok: true });
        }
        case '/t/': return route.fulfill({ contentType: 'text/html', body: '<p>Isolated terminal frame</p>' });
        case '/manifest.webmanifest': return route.fulfill({ contentType: 'application/manifest+json', body: fs.readFileSync(path.join(panelDir, 'manifest.webmanifest')) });
        default: return route.fulfill({ status: 404, body: 'Not found' });
      }
    });
    await use(app);
    expect(errors, 'No uncaught errors while exercising the real panel script').toEqual([]);
  },
});

module.exports = { test, expect, session, PNG };
