const { test, expect } = require('./fixtures');

test('Kimi settings save a key without displaying or retaining it in the dialog', async ({ app, page }) => {
  await app.open();
  await page.evaluate(() => openKimi());
  await expect(page.locator('#kimi_state')).toHaveText('Ключ ещё не настроен');
  await expect(page.locator('#kimi_key')).toHaveAttribute('type', 'password');
  await page.locator('#kimi_key').fill('sk-private-test-123456789');
  await page.locator('#kimi_model').selectOption('kimi-for-coding');
  await page.locator('#kimi_save').click();
  await expect(page.locator('#kimi_dlg')).not.toBeVisible();
  expect(app.kimiSaves[0]).toEqual({key:'sk-private-test-123456789',model:'kimi-for-coding',clear:false});
  await page.evaluate(() => openKimi());
  await expect(page.locator('#kimi_key')).toHaveValue('');
  await expect(page.locator('#kimi_state')).toHaveText('Ключ сохранён на сервере');
  expect(await page.evaluate(() => canAutoRefresh())).toBe(false);
  await page.locator('#kimi_dlg').getByRole('button', {name:'Отмена'}).click();
  expect(await page.evaluate(() => JSON.stringify({...localStorage,...sessionStorage}))).not.toContain('sk-private-test');
});

test('both Kimi session modes fit the iPhone dialog and expose correct permission flags', async ({ app, page }) => {
  await app.open();
  await page.evaluate(() => openNew());
  for(const agent of ['claude-kimi','kimi']) {
    await page.locator(`#agsel [data-a="${agent}"]`).click();
    await expect(page.locator(`#agsel [data-a="${agent}"]`)).toHaveClass('on');
    await expect(page.locator('#n_skip_lbl')).toContainText(agent==='kimi'?'--auto':'--dangerously-skip-permissions');
  }
  expect(await page.locator('#dlg').evaluate(el => el.scrollWidth<=el.clientWidth)).toBe(true);
});
