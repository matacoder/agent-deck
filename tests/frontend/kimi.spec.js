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
  await expect(page.locator('#toast')).toHaveClass('success');
  expect(app.kimiSaves[0]).toEqual({key:'sk-private-test-123456789',model:'kimi-for-coding',clear:false});
  await expect(page.locator('#model_cards')).toContainText('Ключ сохранён на сервере');
  await page.locator('#model_cards .hub-card').filter({hasText:'Kimi'}).getByRole('button',{name:'Настроить',exact:true}).click();
  await expect(page.locator('#kimi_key')).toHaveValue('');
  await expect(page.locator('#kimi_state')).toHaveText('Ключ сохранён на сервере');
  expect(await page.evaluate(() => canAutoRefresh())).toBe(false);
  await page.locator('#kimi_dlg').getByRole('button', {name:'Отмена'}).click();
  expect(await page.evaluate(() => JSON.stringify({...localStorage,...sessionStorage}))).not.toContain('sk-private-test');
});

test('both Kimi session modes fit the iPhone dialog and expose correct permission flags', async ({ app, page }) => {
  await app.open();
  await page.evaluate(() => openNew());
  for(const agent of ['claude','kimi']) {
    await page.locator(`#agsel [data-a="${agent}"]`).click();
    await expect(page.locator(`#agsel [data-a="${agent}"]`)).toHaveClass('on');
    await expect(page.locator('#n_skip_lbl')).toContainText(agent==='kimi'?'--auto':'--dangerously-skip-permissions');
  }
  expect(await page.locator('#dlg').evaluate(el => el.scrollWidth<=el.clientWidth)).toBe(true);
});


test('Kimi save errors stay above the modal backdrop and retain the entered key', async ({ app, page }) => {
  await app.open();
  await page.route('**/api/kimi_config', route => route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'Ошибка сохранения ключа'})}));
  await page.evaluate(() => openKimi());
  await page.locator('#kimi_key').fill('sk:test/with+base64==');
  await page.locator('#kimi_save').click();
  await expect(page.locator('#toast')).toContainText('Ошибка сохранения ключа');
  expect(await page.locator('#toast').evaluate(el=>{const r=el.getBoundingClientRect();const top=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return el===top||el.contains(top)})).toBe(true);
  await expect(page.locator('#kimi_key')).toHaveValue('sk:test/with+base64==');
});

test('Kimi compact quota shows overall monthly remainder and a calendar plan', async ({app,page}) => {
  app.kimiConfig={configured:true,model:'k3'};
  app.usage.kimi={windows:[
    {label:'Общий · месяц',percent:32,period:'month',secs:0,resets_at:Date.now()/1000+86400*15},
    {label:'Kimi Code · месяц',percent:15,period:'month',secs:0,resets_at:Date.now()/1000+86400*15},
    {label:'5 часов',percent:1,period:'hours',secs:18000,resets_at:Date.now()/1000+17000}
  ]};
  await app.open();
  const row=page.locator('.quota-strip').filter({has:page.locator('.ag.kimi')});
  await expect(row.locator('.quota-percent')).toHaveText('68%');
  await expect(row.locator('.quota-plan')).toHaveText(/^[0-9]+%$/);
  await expect(row).toHaveAttribute('aria-label',/месяц/);
  await expect(row.locator('.quota-reset')).toContainText('↻');
  await expect(row).not.toContainText('неделя');
});
