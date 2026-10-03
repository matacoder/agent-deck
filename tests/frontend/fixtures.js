const { test: base, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

const panelDir = path.resolve(__dirname, '../../panel');
const html = fs.readFileSync(path.join(panelDir, 'index.html'), 'utf8');
const loginHtml = fs.readFileSync(path.join(panelDir, 'login.html'), 'utf8').replace('{{USER}}', 'test-user').replace('{{ERROR}}', '');
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
      metrics: { cpu_percent: 24, memory_used: 3221225472, memory_total: 8589934592 }, metricsError: false,
      revision: 'fixture-version', sends: [], uploads: [], sendError: null,
      uploadError: null, sendGate: null, navigations: 0, usage: {},
      version: { version: '0.1.0', update: false, can_update: true, job: { phase: 'idle' } },
      updates: [], updateError: null, kimiConfig: {configured: false, model: "k3"}, kimiSaves: [],
      sessionRequests: [], sessionGate: null, sessionCaptured: false, authExpired: false,
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
      holdSessions() {
        let release;
        const promise = new Promise(resolve => { release = resolve; });
        app.sessionCaptured = false;app.sessionGate = { promise };
        return { release };
      },
    };
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.hostname !== 'panel.test') return route.abort();
      const json = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
      if (url.pathname.startsWith('/api/') && app.authExpired) return json({ error: 'login required' }, 401);
      switch (url.pathname) {
        case '/login':
          if (route.request().method() === 'POST') {
            app.authExpired = false;
            // WebKit routing cannot synthesize redirects; backend tests cover the real 303.
            return route.fulfill({ contentType: 'text/html', body: '<script>location.replace("/")</script>' });
          }
          return route.fulfill({ contentType: 'text/html', body: loginHtml });
        case '/':
        case '/index.html':
          app.navigations++;
          return route.fulfill({ contentType: 'text/html', body: html.replace('__PANEL_REVISION__', app.revision) });
        case '/api/ui-version': return json({ revision: app.revision });
        case '/api/sessions': {
          app.sessionRequests.push(url.searchParams.get('preview'));
          const snapshot = app.sessions.map(s => {
          if (s.name === url.searchParams.get('preview')) return s;
          const { preview, preview_ansi, ...metadata } = s;
          return metadata;
          });
          const gate = app.sessionGate;app.sessionGate = null;
          if (gate) { app.sessionCaptured = true;await gate.promise; }
          return json({ sessions: snapshot });
        }
        case '/api/discard_upload': return json({ ok: true });
        case '/api/kill':
          app.sessions = app.sessions.filter(s => s.name !== route.request().postDataJSON().name);
          return json({ ok: true });
        case '/api/kimi_config': {
          const data=route.request().postDataJSON();app.kimiSaves.push(data);
          app.kimiConfig={configured: data.clear?false:!!data.key||app.kimiConfig.configured, model:data.model};
          return json({ok:true,kimi:app.kimiConfig});
        }
        case '/api/agents': return json({ kimi_config:app.kimiConfig, kimi:{installed:true,logged_in:app.kimiConfig.configured,version:'2.1.1'}, codex: { installed: true, logged_in: true, version: 'test' }, claude: { installed: true, logged_in: true, version: 'test' } });
        case '/api/github/status': return json({ connected: false });
        case '/api/usage': return json(app.usage);
        case '/api/version': return json(app.version);
        case '/api/update':
          app.updates.push(route.request().postDataJSON());
          if (app.updateError) return json({ error: app.updateError }, 400);
          app.version.job = { phase: 'checking', message: 'Проверяю последний релиз…' };
          return json({ ok: true, job: app.version.job });
        case '/api/server-metrics': return app.metricsError ? json({}, 503) : json(app.metrics);
        case '/api/server': return json({ hostname: 'test-server', ip: '192.0.2.1', tailscale_ip: '100.64.0.1', country: 'GB' });
        case '/api/projects': return json({ projects: ['demo'] });
        case '/api/upload': {
          app.uploads.push(route.request().postDataJSON());
          if (app.uploadError) return json({ error: app.uploadError }, 400);
          const uploaded = app.uploads.at(-1), image = uploaded.data.startsWith(PNG.toString('base64').slice(0, 12));
          const suffix = image ? '.png' : '--' + uploaded.filename.replace(/[^A-Za-z0-9_.-]/g, '_').slice(-100);
          return json({ ok: true, attachment: String(app.uploads.length).padStart(32, '0') + suffix, kind: image ? 'image' : 'file' });
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
