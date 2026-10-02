const { test, expect, PNG } = require('./fixtures');

function newRelease(app) {
  app.version.latest = '0.2.0';
  app.version.update = true;
}

test('latest installed version has no update action', async ({ app, page }) => {
  await app.open();
  await expect(page.locator('#ver')).toContainText('v0.1.0');
  await expect(page.locator('#b_update')).toHaveCount(0);
  await page.evaluate(() => sheet(true));
  await expect(page.locator('#s_update')).toBeHidden();
});

test('mobile release update runs once, shows progress and preserves drafts on reload', async ({ app, page }) => {
  newRelease(app);
  await app.open();
  await page.locator('#msg').fill('Unsent draft');
  await page.locator('#image_files').setInputFiles({ name: 'saved.png', mimeType: 'image/png', buffer: PNG });
  await expect(page.locator('#attachments')).toContainText('saved.png');
  await page.evaluate(() => sheet(true));
  await page.locator('#sheet').getByRole('button', { name: 'Обновить до v0.2.0', exact: true }).click();
  await expect.poll(() => app.updates.length).toBe(1);
  await expect(page.locator('#b_send')).toBeDisabled();
  await page.evaluate(() => startPanelUpdate());
  expect(app.updates).toEqual([{}]);
  app.version.job = { phase: 'downloading', message: 'Скачиваю v0.2.0…' };
  await page.evaluate(() => loadVersion());
  await page.evaluate(() => sheet(true));
  await expect(page.locator('#s_update')).toHaveText('Скачиваю v0.2.0…');
  await expect(page.locator('#s_update')).toBeDisabled();
  app.version.version = '0.2.0';
  app.version.update = false;
  app.version.job = { phase: 'done', version: '0.2.0', message: 'Панель обновлена' };
  app.revision = 'updated-interface';
  await page.evaluate(() => loadVersion());
  await expect(page.locator('#s_update')).toContainText('перезагрузить интерфейс');
  await page.locator('#s_update').click();
  await expect.poll(() => app.navigations).toBe(2);
  await expect(page.locator('#msg')).toHaveValue('Unsent draft');
  await expect(page.locator('#attachments')).toContainText('saved.png');
  await expect(page.locator('#b_send')).toBeEnabled();
});

test('failed update permits retry and leaves unsent text intact', async ({ app, page }) => {
  newRelease(app);
  await app.open({ width: 1280, height: 800 });
  await page.locator('#msg').fill('Keep this');
  app.updateError = 'GitHub is unavailable';
  await page.locator('#b_update').click();
  await expect(page.locator('#b_update')).toHaveText('Обновление не удалось · повторить');
  await expect(page.locator('#toast')).toContainText('GitHub is unavailable');
  await expect(page.locator('#msg')).toHaveValue('Keep this');
  await expect(page.locator('#b_send')).toBeEnabled();
  app.updateError = null;
  await page.locator('#b_update').click();
  await expect.poll(() => app.updates.length).toBe(2);
  await expect(page.locator('#b_update')).toBeDisabled();
});

test('development checkout disables automatic installation', async ({ app, page }) => {
  newRelease(app);
  app.version.can_update = false;
  await app.open({ width: 1280, height: 800 });
  await expect(page.locator('#b_update')).toBeDisabled();
  await expect(page.locator('#ver')).toHaveAttribute('title', /через git/);
  expect(app.updates).toEqual([]);
});

test('update waits for a pending message instead of interrupting its send', async ({ app, page }) => {
  newRelease(app);
  await app.open({ width: 1280, height: 800 });
  await page.locator('#msg').fill('In flight');
  const gate = app.holdSend();
  await page.locator('#b_send').click();
  await expect.poll(() => app.sends.length).toBe(1);
  await page.locator('#b_update').click();
  await expect(page.locator('#toast')).toContainText('Дождитесь окончания отправки');
  expect(app.updates).toEqual([]);
  gate.release();
  await expect(page.locator('#send_state')).toContainText('Отправлено');
  await page.locator('#b_update').click();
  await expect.poll(() => app.updates.length).toBe(1);
});

test('a previous completed update does not turn the next release button into reload', async ({ app, page }) => {
  newRelease(app);
  app.version.job = { phase: 'done', version: '0.1.0' };
  await app.open();
  await page.evaluate(() => sheet(true));
  await page.locator('#s_update').click();
  await expect.poll(() => app.updates.length).toBe(1);
  expect(app.navigations).toBe(1);
});
