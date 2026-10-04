const {test,expect}=require('./fixtures');

test('Pi selects a pinned local model and hides skip permission controls',async({app,page})=>{
 const profile={id:'abcdef012345abcdef012345',name:'Workstation',models:[{id:'qwen-coder',name:'Qwen Coder',loaded:true}]};
 app.lmstudio.profiles=[profile];
 await app.open();await page.evaluate(()=>openNew());
 await page.locator('#agsel [data-a="pi"]').click();
 await expect(page.locator('#n_skip_row')).toBeHidden();
 await expect(page.locator('#source_row')).toBeVisible();
 const source={kind:'lmstudio',profile:profile.id,model:'qwen-coder'};
 await expect(page.locator('#n_source')).toHaveValue(JSON.stringify(source));
 await expect(page.locator('#n_source option')).toHaveCount(1);
 await page.locator('#n_name').fill('pi-local');await page.locator('#n_go').click();
 await expect.poll(()=>app.newSessions.length).toBe(1);
 expect(app.newSessions[0]).toMatchObject({agent:'pi',source});
});

test('Pi has an installer in settings without cloud login',async({app,page})=>{
 await app.open();await page.evaluate(()=>openSettings('agents'));
 await expect(page.locator('#hub_agents')).toContainText('Pi');
 await expect(page.locator('#hub_agents')).toContainText('Установить');
});


test('settings gear stays readable with a full height click target',async({app,page})=>{
 await app.open({width:1280,height:900});
 const button=page.locator('.settingsbtn'),icon=button.locator('svg');
 await expect(icon).toBeVisible();
 const mark=await icon.boundingBox(),target=await button.boundingBox();
 expect(mark.width).toBe(22);expect(mark.height).toBe(22);expect(target.height).toBeGreaterThanOrEqual(44);
 await button.click();await expect(page.locator('#settings_dlg')).toBeVisible();
});
