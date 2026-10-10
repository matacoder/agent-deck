const { test, expect } = require('./fixtures');

for (const width of [320, 390]) {
  test(`portrait ${width}px keeps header and input inside the viewport`, async ({ app, page }) => {
    await app.open({ width });
    for (const selector of ['main > .bar', '#msg', '#b_send']) {
      const bounds = await page.locator(selector).boundingBox();
      expect(bounds, selector).not.toBeNull();
      expect(bounds.x, selector).toBeGreaterThanOrEqual(-1);
      expect(bounds.x + bounds.width, selector).toBeLessThanOrEqual(width + 1);
      expect(bounds.y, selector).toBeGreaterThanOrEqual(0);
      expect(bounds.y + bounds.height, selector).toBeLessThanOrEqual(845);
    }
    expect(await page.locator('main > .bar').evaluate(el => getComputedStyle(el).backdropFilter)).toBe('none');
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
  });
}

test('keyboard viewport resize keeps composer visible and the hide button removes focus', async ({ app, page }) => {
  await app.open({ width: 390, height: 844 });
  await page.locator('#msg').focus();
  await expect(page.locator('#b_keyboard')).toBeVisible();
  await page.evaluate(() => {
    Object.defineProperty(window, 'visualViewport', { configurable: true, value: { height: 430, offsetTop: 24, scale: 1 } });
    fitViewport();
  });
  await expect(page.locator('body')).toHaveClass(/keyboard-open/);
  const bounds = await page.locator('#b_send').boundingBox();
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(454);
  await page.locator('#b_keyboard').click();
  await expect(page.locator('#msg')).not.toBeFocused();
  await page.evaluate(() => { window.visualViewport.height = 844; window.visualViewport.offsetTop = 0; fitViewport(); });
  await expect(page.locator('body')).not.toHaveClass(/keyboard-open/);
  expect(await page.locator('main').evaluate(el => el.getBoundingClientRect().bottom)).toBe(844);
});

test('message input disables correction, capitalization and spelling suggestions', async ({ app, page }) => {
  await app.open();
  for (const [attribute, value] of Object.entries({ autocomplete: 'off', autocorrect: 'off', autocapitalize: 'none', spellcheck: 'false' })) {
    await expect(page.locator('#msg')).toHaveAttribute(attribute, value);
  }
});

test('compact quotas show remaining and plan without affecting the header', async ({ app, page }) => {
  const now = Date.now() / 1000;
  app.usage = Object.fromEntries(['codex', 'claude'].map(agent => [agent, { windows: [{ label: 'неделя', percent: 60, secs: 604800, resets_at: now + 302400 }] }]));
  await app.open();
  const headerBefore = await page.locator('main > .bar').boundingBox();
  await page.getByRole('button', { name: 'Сессии', exact: true }).click();
  await expect(page.locator('.quota-heading')).toContainText('Остаток');
  await expect(page.locator('.quota-heading')).toContainText('План');
  for(const agent of ['claude','codex']){
    const row=page.locator('.quota-strip').filter({has:page.locator('.ag.'+agent)});
    await expect(row).toHaveAttribute('aria-label',/неделя/);
    await expect(row.locator('.quota-percent')).toHaveText('40%');
    await expect(row.locator('.quota-plan')).toHaveText(/^[0-9]+%$/);
    const bounds=await row.evaluate(e=>({height:e.getBoundingClientRect().height,width:e.getBoundingClientRect().width}));expect(bounds.height).toBeLessThanOrEqual(32);expect(bounds.width).toBeLessThan(390);
  }
  expect((await page.locator('main > .bar').boundingBox()).height).toBe(headerBefore.height);
});

test('desktop layout keeps sidebar visible and Enter sends', async ({ app, page }) => {
  await app.open({ width: 1280, height: 800 });
  await expect(page.locator('aside')).toBeVisible();
  await page.locator('#msg').fill('Desktop message');
  await page.locator('#msg').press('Enter');
  await expect(page.locator('#send_state')).toContainText('Отправлено');
  expect(app.sends).toHaveLength(1);
});

test('mobile drawer stays visible and accepts search after opening',async({app,page})=>{
 await app.open({width:390});
 await page.getByRole('button',{name:'Сессии',exact:true}).click();
 await page.locator('#q').fill('other');
 await expect(page.locator('#tabs .tab')).toHaveCount(1);
 await expect(page.locator('#tabs .n')).toHaveText('other');
});
