const { test, expect, PNG } = require('./fixtures');

test('automatically reloads an idle screen when the server revision changes', async ({ app, page }) => {
  await app.open();
  app.revision = 'next-version';
  await page.evaluate(() => checkInterfaceVersion());
  await expect.poll(() => app.navigations).toBe(2);
  await expect(page.locator('#title b')).toHaveText('tmux');
  await expect(page.locator('#pre')).toContainText('Output from tmux');
});

for (const guard of ['current draft', 'other session draft', 'focus', 'file picker', 'dialog', 'drawer', 'terminal', 'selection', 'attachment']) {
  test(`auto update waits while there is a ${guard}`, async ({ app, page }) => {
    await app.open();
    switch (guard) {
      case 'current draft': await page.locator('#msg').fill('Unsent'); await page.locator('#msg').blur(); break;
      case 'other session draft': await page.locator('#msg').fill('Unsent'); await page.evaluate(() => select('other')); await page.locator('#msg').blur(); break;
      case 'focus': await page.locator('#msg').focus(); break;
      case 'file picker': await page.evaluate(() => { choosingImages = true; }); break;
      case 'dialog': await page.evaluate(() => $('dlg').showModal()); break;
      case 'drawer': await page.evaluate(() => drawer(true)); break;
      case 'terminal': await page.evaluate(() => setMode('term')); break;
      case 'selection': await page.locator('#pre').evaluate(el => { const range = document.createRange(); range.selectNodeContents(el); window.getSelection().addRange(range); }); break;
      case 'attachment':
        await page.locator('#image_files').setInputFiles({ name: 'image.png', mimeType: 'image/png', buffer: PNG });
        await expect(page.locator('#attachments')).toContainText('image.png');
        break;
    }
    app.revision = 'next-version';
    await page.evaluate(() => checkInterfaceVersion());
    expect(app.navigations).toBe(1);
    await expect(page.locator('#title b')).toHaveText(guard === 'other session draft' ? 'other' : 'tmux');
  });
}

test('reading older output blocks auto update and polling preserves reading position', async ({ app, page }) => {
  app.sessions[0].preview = Array.from({ length: 200 }, (_, i) => `Line ${i}`).join('\n');
  await app.open();
  await page.locator('#pre').evaluate(el => { el.scrollTop = 100; });
  app.revision = 'next-version';
  await page.evaluate(() => checkInterfaceVersion());
  expect(app.navigations).toBe(1);
  app.sessions[0].preview += '\nNew output';
  await page.evaluate(() => load());
  expect(await page.locator('#pre').evaluate(el => el.scrollTop)).toBeCloseTo(100, 0);
});
