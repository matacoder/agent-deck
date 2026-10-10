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
  await expect(page.locator('#session_meta')).toBeHidden();
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
