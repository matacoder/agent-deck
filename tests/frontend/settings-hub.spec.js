const {test,expect}=require('./fixtures');

function localProfile(){return {id:'abcdef012345abcdef012345',name:'Workstation',url:'http://100.64.1.2:1234',status:'online',key_saved:true,models:[{id:'qwen-coder',name:'Qwen Coder',loaded:true,context_length:32768,tool_tested:true}],performance:{model:'qwen-coder',source:'session',tokens_per_second:39.5,time_to_first_token_seconds:0.24}}}

test('desktop settings has one labelled entry and separates runtime, sources and connections',async({app,page})=>{
  app.lmstudio.profiles=[localProfile()];await app.open({width:1280,height:900});
  await page.locator('.settingsbtn').click();
  await expect(page.locator('#hub_agents')).toBeVisible();
  await expect(page.locator('#hub_agents')).toContainText('Codex');
  await page.locator('.hub-nav').getByRole('button',{name:'Модели',exact:true}).click();
  await expect(page.locator('#model_cards')).toContainText('Workstation');
  await expect(page.locator('#model_cards')).toContainText('39.5 tok/s');
  await expect(page.locator('#model_cards')).toContainText('Context: 32768');
  await expect(page.locator('#model_cards')).not.toContainText('%');
  await page.locator('#model_cards').getByRole('button',{name:'Проверить инструменты'}).click();
  await expect.poll(()=>app.lmActions.length).toBe(1);
  expect(app.lmActions[0].data).toEqual({id:localProfile().id,model:'qwen-coder'});
  await page.locator('.hub-nav').getByRole('button',{name:'Приложение',exact:true}).click();
  await expect(page.getByRole('button',{name:'Выйти',exact:true})).toBeVisible();
  await expect(page.locator('#ui_language')).toBeVisible();
});

test('source selection pins local model and survives a trip to settings',async({app,page})=>{
  app.lmstudio.profiles=[localProfile()];app.kimiConfig.configured=true;
  await app.open();await page.evaluate(()=>openNew());
  await page.locator('#n_name').fill('local-test');
  const source={kind:'lmstudio',profile:localProfile().id,model:'qwen-coder'};
  await page.locator('#n_source').selectOption(JSON.stringify(source));
  await page.getByRole('button',{name:'Настроить модели',exact:true}).click();
  await expect(page.locator('#settings_dlg')).toBeVisible();
  await page.locator('.hub-heading').getByRole('button',{name:'Закрыть',exact:true}).click();
  await expect(page.locator('#n_name')).toHaveValue('local-test');
  await expect(page.locator('#n_source')).toHaveValue(JSON.stringify(source));
  await page.locator('#n_go').click();
  await expect.poll(()=>app.newSessions.length).toBe(1);
  expect(app.newSessions[0]).toMatchObject({agent:'claude',source});
  expect(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).not.toContain('test-secret');
});

test('discovery adds an explicit editable profile and cancels without changing saved profiles',async({app,page})=>{
  app.lmstudio.discovery={phase:'running',checked:1,total:3,results:[{name:'Found Mac',url:'http://100.64.2.3:1234',status:'needs_key',models:[]}]};
  await app.open({width:320});await page.evaluate(()=>openSettings('models'));
  await expect(page.locator('#lm_progress')).toContainText('1 / 3');
  await page.locator('#lm_results').getByRole('button',{name:'Добавить',exact:true}).click();
  await expect(page.locator('#lm_url')).toHaveValue('http://100.64.2.3:1234');
  await page.locator('#lm_key').fill('draft-only-secret');
  await page.locator('#lm_cancel').click();
  await expect.poll(()=>app.lmActions.length).toBe(1);
  expect(app.lmActions[0]).toMatchObject({path:'/api/lm_discover',data:{cancel:true}});
  expect(await page.locator('#settings_dlg').evaluate(e=>e.scrollWidth<=e.clientWidth)).toBe(true);
  await page.locator('.hub-heading').getByRole('button',{name:'Закрыть',exact:true}).click();
  await expect(page.locator('#lm_key')).toHaveValue('');
});

test('refresh preserves the chosen local model for tool tests and benchmarks',async({app,page})=>{
 const p=localProfile();p.models.push({...p.models[0],id:'second-model',name:'Second Model'});app.lmstudio.profiles=[p];
 await app.open();await page.evaluate(()=>openSettings('models'));
 await page.locator('#model_cards select').selectOption('second-model');
 await page.evaluate(()=>loadLM());
 await expect(page.locator('#model_cards select')).toHaveValue('second-model');
 await page.locator('#model_cards').getByRole('button',{name:'Измерить скорость',exact:true}).click();
 await expect.poll(()=>app.lmActions.length).toBe(1);
 expect(app.lmActions[0]).toMatchObject({path:'/api/lm_benchmark',data:{model:'second-model'}});
});

test('native Kimi source defaults to the saved model instead of always K3',async({app,page})=>{
 app.kimiConfig={configured:true,model:'kimi-for-coding-highspeed'};await app.open();await page.evaluate(()=>openNew());
 await page.locator('#agsel [data-a="kimi"]').click();
 await expect(page.locator('#n_source')).toHaveValue(JSON.stringify({kind:'kimi',model:'kimi-for-coding-highspeed'}));
 await expect(page.locator('#agsel [data-a="claude-kimi"]')).toHaveCount(0);
});

test('drawer keeps a long local model compact and lets the user reveal its full name',async({app,page})=>{
 const p=localProfile();p.name='RED';p.performance={...p.performance,source:'benchmark',model:'qwen-coder-'+ 'long-model-name-'.repeat(12)};app.lmstudio.profiles=[p];
 await app.open({width:320});await page.evaluate(()=>{drawer(true);integOpen=true;renderInteg()});
 const block=page.locator('.local-usage');await expect(block).toContainText('39.5');
 const bounds=await block.boundingBox();expect(bounds.height).toBeLessThan(160);
 const summary=block.locator('summary');await expect(summary).toHaveAttribute("title",p.performance.model+" · "+p.name);await expect(summary).toContainText("…");
 await summary.click();await expect(block.locator('.local-model div')).toHaveText(p.performance.model);
 expect(await page.locator('aside').evaluate(e=>e.scrollWidth<=e.clientWidth)).toBe(true);
});

test('phone settings scroll content inside a fixed header and short navigation bar',async({app,page})=>{
 app.lmstudio.profiles=[localProfile()];await app.open({width:320});await page.evaluate(()=>openSettings('models'));
 const nav=await page.locator('.hub-nav').boundingBox();expect(nav.height).toBeLessThan(90);
 const heading=await page.locator('.hub-heading').boundingBox();
 await page.locator('.hub-content').evaluate(e=>e.scrollTop=e.scrollHeight);
 await expect(page.locator('#lm_ports')).toBeInViewport();
 expect((await page.locator('.hub-heading').boundingBox()).y).toBe(heading.y);
 expect(await page.locator('.hub-content').evaluate(e=>e.scrollWidth<=e.clientWidth)).toBe(true);
});

test('local Claude sessions identify the model source in the drawer and header',async({app,page})=>{
 app.sessions[0].agent='claude';app.sessions[0].source={kind:'lmstudio',profile:localProfile().id,model:'qwen-coder',label:'LM Studio · Workstation · qwen-coder'};
 await app.open({width:390});await page.evaluate(()=>drawer(true));
 await expect(page.locator('.tab').filter({hasText:'tmux'}).locator('.session-source')).toHaveText('qwen-coder · Workstation');
 await expect(page.locator('.tab').filter({hasText:'tmux'}).locator('.ag.local svg')).toBeVisible();
 await page.evaluate(()=>drawer(false));
 await expect(page.locator('#title')).toContainText('qwen-coder · Workstation');
 await expect(page.locator('#msg')).toHaveAttribute('placeholder','Сообщение в qwen-coder · Workstation…');
});
