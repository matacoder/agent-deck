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

const pack=['es','pt-BR','de','fr','zh-CN','ja','ko','id','tr','it','pl','uk','hi','zh-TW'];
for(const code of pack){
 test(`${code} works on a narrow phone, preserves agent output and can switch language`,async({app,page})=>{
  app.language=code;
  app.sessions[0].preview='Agent output: сохраняем 原文';
  app.telegramConfig={available:true,configured:true,paired:true,enabled:true,bot:'demo_bot',account:'demo_user'};
  await app.open({width:320});
  await expect(page.locator('html')).toHaveAttribute('lang',code);
  await expect(page.locator('#pre')).toContainText('Agent output: сохраняем 原文');
  await expect(page.locator('#msg')).toHaveAttribute('placeholder',app.catalogs[code]['Сообщение в ']+'Codex…');
  const status=await page.locator('.composer-status').boundingBox();
  const metrics=await page.locator('#server_metrics').boundingBox();
  expect(metrics.x+metrics.width).toBeLessThanOrEqual(320);
  expect(metrics.y+metrics.height).toBeLessThanOrEqual(status.y+status.height+1);
  await page.evaluate(()=>openSettings());
  await expect(page.locator('#settings_dlg h3')).toHaveText(app.catalogs[code]['Настройки']);
  await expect(page.locator('#ui_language option')).toHaveCount(Object.keys(app.catalogs).length);
  await expect(page.locator('#ui_language')).toHaveValue(code);
  await page.evaluate(()=>{$('settings_dlg').close();openIntegrations()});
  await expect(page.locator('#telegram_state')).toContainText('demo_user');
  for(const button of await page.locator('#integrations_dlg .acts button').all()){
   const bounds=await button.boundingBox();
   expect(bounds.x).toBeGreaterThanOrEqual(0);expect(bounds.x+bounds.width).toBeLessThanOrEqual(320);
  }
  const dialogBounds=await page.locator('#integrations_dlg').boundingBox();
  expect(dialogBounds.height).toBeLessThan(800);
  await page.evaluate(()=>$('integrations_dlg').close());
  await page.locator('#msg').fill('Unsent draft 原文');
  await page.evaluate(()=>openSettings());
  await page.locator('#ui_language').selectOption('en');
  await page.locator('#settings_dlg button.pri').tap();
  await expect.poll(async()=> (await page.context().cookies('https://panel.test/')).find(x=>x.name==='cc_lang')?.value).toBe('en');
  await expect(page.locator('html')).toHaveAttribute('lang','en');
  await expect(page.locator('#msg')).toHaveValue('Unsent draft 原文');
  await expect(page.locator('#title b')).toHaveText('tmux');
 });
}
