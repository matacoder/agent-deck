const {test,expect}=require('./fixtures');

test('English covers dynamic controls and dialogs without translating agent output',async({app,page})=>{
  app.language='en';app.sessions[0].preview='Ответ агента остаётся на русском';
  await app.open();
  await expect(page.locator('html')).toHaveAttribute('lang','en');
  await expect(page.locator('#send_state')).toContainText('send');
  await expect(page.locator('#pre')).toContainText('Ответ агента остаётся на русском');
  await page.evaluate(()=>openIntegrations());
  await expect(page.locator('#integrations_dlg')).toContainText('Questions and answers in your bot chat');
  await expect(page.locator('#telegram_state')).toHaveText('No bot connected yet');
  await page.locator('#integrations_dlg').getByRole('button',{name:'Close',exact:true}).click();
  await page.evaluate(()=>openNew());
  await expect(page.locator('#dlg')).toContainText('Session name');
  await expect(page.locator('#gh_state')).toHaveText('GitHub is not connected');
});

test('changing language preserves draft, active session and mode',async({app,page})=>{
  await app.open();await page.locator('#msg').fill('Несохранённый draft');
  await page.evaluate(()=>openSettings());
  await page.locator('#ui_language').selectOption('en');
  await page.locator('#settings_dlg').getByRole('button',{name:'Применить'}).click();
  await expect(page.locator('html')).toHaveAttribute('lang','en');
  await expect(page.locator('#msg')).toHaveValue('Несохранённый draft');
  await expect(page.locator('#title b')).toHaveText('tmux');
  await expect(page.locator('#screen')).toBeVisible();
  await page.evaluate(()=>openSettings());
  await page.locator('#ui_language').selectOption('ru');
  await page.locator('#settings_dlg').getByRole('button',{name:'Apply'}).click();
  await expect(page.locator('html')).toHaveAttribute('lang','ru');
  await expect(page.locator('#msg')).toHaveValue('Несохранённый draft');
});
