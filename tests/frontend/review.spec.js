const { test, expect, PNG } = require('./fixtures');

test('disappearing active session never transfers its draft into the fallback session', async ({ app, page }) => {
  await app.open();
  await page.evaluate(() => select('other'));
  await page.locator('#msg').fill('Other draft');
  await page.evaluate(() => select('tmux'));
  await page.locator('#msg').fill('Deleted session draft');
  await page.locator('#image_files').setInputFiles({ name: 'old.png', mimeType: 'image/png', buffer: PNG });
  await expect(page.locator('#attachments')).toContainText('old.png');
  app.sessions = app.sessions.filter(s => s.name !== 'tmux');
  await page.evaluate(() => load());
  await expect(page.locator('#title b')).toHaveText('other');
  await expect(page.locator('#msg')).toHaveValue('Other draft');
  await expect(page.locator('#attachments')).toBeEmpty();
  await page.evaluate(() => sheet(true));
  await page.locator('#s_drafts').click();
  await expect(page.locator('#closed_drafts')).toContainText('Deleted session draft');
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click();
  await page.locator('#msg').fill('');
  await page.locator('#msg').blur();
  expect(await page.evaluate(() => canAutoRefresh())).toBe(true);
});

test('closing a session immediately keeps another session visible', async ({ app, page }) => {
  await app.open();
  page.once('dialog', dialog => dialog.accept());
  await page.evaluate(() => kill());
  await expect(page.locator('#title b')).toHaveText('other');
  await expect(page.locator('#screen')).toBeVisible();
  await expect(page.locator('#empty')).toBeHidden();
});

test('terminal iframe and popout use exact tmux targets', async ({ app, page }) => {
  await app.open({ mode: 'term' });
  await expect(page.locator('#stage iframe')).toHaveAttribute('src', '/t/?arg=%3Dcc-tmux');
  await page.evaluate(() => { window.open = url => { window.openedTerminal = url; };popout(); });
  expect(await page.evaluate(() => window.openedTerminal)).toBe('/t/?arg=%3Dcc-tmux');
});

test('401 redirects to login and restores text, attachments and active session afterwards', async ({ app, page }) => {
  await app.open();
  await page.locator('#msg').fill('Preserve after login');
  await page.locator('#image_files').setInputFiles({ name: 'login.png', mimeType: 'image/png', buffer: PNG });
  await expect(page.locator('#attachments')).toContainText('login.png');
  app.authExpired = true;
  await page.evaluate(() => { load(); });
  await expect(page).toHaveURL('https://panel.test/login');
  await page.locator('#p').fill('test-password-only');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.locator('#title b')).toHaveText('tmux');
  await expect(page.locator('#msg')).toHaveValue('Preserve after login');
  await expect(page.locator('#attachments')).toContainText('login.png');
});

test('session polls never overlap and a queued poll observes fresh session data', async ({ app, page }) => {
  await app.open();
  const before = app.sessionRequests.length;
  const gate = app.holdSessions();
  await page.evaluate(() => { load(); });
  await expect.poll(() => app.sessionCaptured).toBe(true);
  await page.evaluate(() => { load();load(); });
  expect(app.sessionRequests.length).toBe(before + 1);
  app.sessions = app.sessions.filter(s => s.name !== 'tmux');
  gate.release();
  await expect(page.locator('#title b')).toHaveText('other');
  await expect(page.locator('#pre')).toContainText('Output from other');
});

test('hidden page does not poll previews and visible selections only request their own preview', async ({ app, page }) => {
  await app.open();
  expect(app.sessionRequests[0]).toBe('tmux');
  await page.evaluate(() => select('other'));
  await expect(page.locator('#pre')).toContainText('Output from other');
  expect(app.sessionRequests.at(-1)).toBe('other');
  const before = app.sessionRequests.length;
  await page.evaluate(async () => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    await load();
  });
  expect(app.sessionRequests.length).toBe(before);
});

test('colored hard-wrapped URLs become one complete link', async ({ app, page }) => {
  const start = 'https://example.com/auth?token=' + 'a'.repeat(50), end = 'b'.repeat(40);
  app.sessions[0].preview_ansi = '\x1b[1m' + start + '\x1b[0m\n\x1b[32m' + end + '\x1b[0m\nFinished now';
  await app.open();
  await expect(page.locator('#pre a')).toHaveAttribute('href', start + end);
  await expect(page.locator('#pre a span').first()).toHaveCSS('font-weight', '700');
  await expect(page.locator('#pre a span').last()).toHaveCSS('color', 'rgb(78, 154, 6)');
});

test('desktop Enter hint matches sending and pinch zoom does not shrink the layout', async ({ app, page }) => {
  await app.open({ width: 1280, height: 800 });
  await expect(page.locator('#send_state')).toHaveText('Enter — отправить · Shift+Enter — новая строка');
  const before = await page.locator('#app').boundingBox();
  await page.evaluate(() => {
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: { height: 400, offsetTop: 0, scale: 2 } });
    fitViewport();
  });
  expect((await page.locator('#app').boundingBox()).height).toBe(before.height);
});
