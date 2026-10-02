const { test, expect, session } = require('./fixtures');

test('restores the saved session and shows its output immediately after reload', async ({ app, page }) => {
  await app.open({ active: 'tmux' });
  await expect(page.locator('#screen')).toBeVisible();
  await expect(page.locator('#pre')).toContainText('Output from tmux');
  await page.reload();
  await expect(page.locator('#screen')).toBeVisible();
  await expect(page.locator('#title b')).toHaveText('tmux');
  await expect(page.locator('#pre')).toContainText('Output from tmux');
});

test('opens the most recently active session when there is no saved session', async ({ app, page }) => {
  await app.open({ active: null });
  await expect(page.locator('#title b')).toHaveText('other');
  await expect(page.locator('#screen')).toBeVisible();
});

test('falls back when the saved session was deleted and handles an empty list', async ({ app, page }) => {
  await app.open({ active: 'deleted' });
  await expect(page.locator('#title b')).toHaveText('other');
  app.sessions = [];
  await page.evaluate(() => load());
  await expect(page.locator('#empty')).toBeVisible();
  await expect(page.locator('#empty')).toContainText('Нет сессий');
  await expect(page.locator('#quick_tabs')).toBeHidden();
});

test('quick tabs preserve drafts and highlight the selected session', async ({ app, page }) => {
  await app.open();
  await page.locator('#msg').fill('Draft for tmux');
  await page.getByRole('button', { name: 'Открыть сессию other', exact: true }).click();
  await expect(page.locator('#msg')).toHaveValue('');
  await page.locator('#msg').fill('Draft for other');
  await page.getByRole('button', { name: 'Открыть сессию tmux', exact: true }).click();
  await expect(page.locator('#msg')).toHaveValue('Draft for tmux');
  await expect(page.getByRole('button', { name: 'Открыть сессию tmux', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Открыть сессию other', exact: true }).click();
  await expect(page.locator('#msg')).toHaveValue('Draft for other');
});

test('many tabs scroll horizontally and polling preserves scroll and button nodes', async ({ app, page }) => {
  app.sessions = Array.from({ length: 15 }, (_, i) => session(`project-${i}`));
  await app.open({ active: 'project-0' });
  await page.locator('#quick_tabs').evaluate(el => { el.scrollLeft = 200; window.originalTab = el.firstElementChild; });
  app.sessions[0].activity = Math.floor(Date.now() / 1000);
  await page.evaluate(() => load());
  expect(await page.locator('#quick_tabs').evaluate(el => el.firstElementChild === window.originalTab)).toBe(true);
  expect(await page.locator('#quick_tabs').evaluate(el => el.scrollLeft)).toBeCloseTo(200, 0);
  await page.evaluate(() => select('project-14'));
  await expect(page.locator('#title b')).toHaveText('project-14');
  await expect.poll(() => page.locator('#quick_tabs').evaluate(el => {
    const r = el.querySelector('.on').getBoundingClientRect(), parent = el.getBoundingClientRect();
    return r.left >= parent.left - 1 && r.right <= parent.right + 1;
  })).toBe(true);
});

test('manual refresh preserves drafts from more than one session', async ({ app, page }) => {
  await app.open();
  await page.locator('#msg').fill('Draft A');
  await page.evaluate(() => select('other'));
  await page.locator('#msg').fill('Draft B');
  await page.evaluate(() => refreshInterface());
  await expect(page.locator('#title b')).toHaveText('other');
  await expect(page.locator('#msg')).toHaveValue('Draft B');
  await page.evaluate(() => select('tmux'));
  await expect(page.locator('#msg')).toHaveValue('Draft A');
});
