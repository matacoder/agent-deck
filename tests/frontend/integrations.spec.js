const { test, expect } = require('./fixtures');

test('phone integration setup keeps token private and shows the pairing link', async ({ app, page }) => {
  await app.open({ width:390 });
  await page.getByRole('button', { name:'Действия', exact:true }).click();
  await page.getByRole('button', { name:'Интеграции', exact:true }).click();
  const dialog=page.locator('#integrations_dlg');
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('#telegram_token')).toHaveAttribute('type','password');
  await dialog.locator('#telegram_token').fill('1234567890:test_token_only_for_browser_tests');
  await dialog.getByRole('button',{name:'Сохранить',exact:true}).click();
  await expect(dialog.locator('#telegram_token')).toHaveValue('');
  await expect(dialog.getByRole('link',{name:/Привязать мой Telegram/})).toHaveAttribute('href',/https:\/\/t.me\/deck_test_bot\?start=/);
  expect(app.telegramSaves).toHaveLength(1);
  expect(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).not.toContain('test_token_only');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('paired Telegram can be paused and a draft token is cleared on close', async ({ app,page }) => {
  app.telegramConfig={available:true,configured:true,paired:true,enabled:true,bot:'deck_test_bot',account:'tester'};
  await app.open({width:1000});
  await page.locator('#integ').getByRole('button',{name:'Настроить',exact:true}).click();
  const dialog=page.locator('#integrations_dlg');
  await expect(dialog.locator('#telegram_state')).toContainText('tester');
  await expect(dialog.locator('#telegram_token')).not.toBeVisible();
  await dialog.locator('#telegram_enabled').uncheck();
  await page.waitForTimeout(3200);
  await expect(dialog.locator('#telegram_enabled')).not.toBeChecked();
  await dialog.getByRole('button',{name:'Сохранить',exact:true}).click();
  expect(app.telegramSaves.at(-1).enabled).toBe(false);
  await dialog.locator('summary').click();
  await dialog.locator('#telegram_token').fill('unsaved-token');
  await dialog.getByRole('button',{name:'Закрыть',exact:true}).click();
  await expect(dialog.locator('#telegram_token')).toHaveValue('');
});

test('compact integration card fits a 320px phone without a full-height dialog', async ({app,page})=>{
  app.telegramConfig={available:true,configured:true,paired:true,enabled:true,bot:'deck_test_bot',account:'tester'};
  await app.open({width:320});
  await page.getByRole('button',{name:'Действия',exact:true}).click();
  await page.getByRole('button',{name:'Интеграции',exact:true}).click();
  const dialog=page.locator('#integrations_dlg');
  await expect(dialog.locator('#telegram_state')).toContainText('tester');
  const bounds=await dialog.boundingBox();
  expect(bounds.height).toBeLessThan(700);
  for(const name of ['Отключить','Закрыть','Сохранить']){
    const box=await dialog.getByRole('button',{name,exact:true}).boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(320);
  }
});
