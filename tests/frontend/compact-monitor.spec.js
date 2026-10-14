const {test,expect}=require('./fixtures');

test('limits line under the message field shows each subscription remainder, plan and reset',async({app,page})=>{
 const resets_at=Date.now()/1000+90000;
 app.usage={claude:{windows:[{label:'5 часов',percent:7,secs:18000,resets_at},{label:'неделя',percent:73,secs:604800,resets_at}]},codex:{windows:[{label:'неделя',percent:30,secs:604800,resets_at}]},kimi:{windows:[{label:'Kimi Code · месяц',period:'month',percent:0,secs:2592000,resets_at},{label:'Общий · месяц',period:'month',percent:18,secs:2592000,resets_at}]}};
 await app.open({width:1280,height:900});
 const items=page.locator('#send_state .session-status .quota-item');await expect(items).toHaveCount(3);
 await expect(items.nth(0).locator('.quota-percent')).toHaveText('27%');await expect(items.nth(1).locator('.quota-percent')).toHaveText('70%');await expect(items.nth(2).locator('.quota-percent')).toHaveText('82%');
 // The open session runs Codex: only its limit is marked as the one being spent.
 await expect(page.locator('#send_state .quota-item.on')).toHaveCount(1);await expect(items.nth(1)).toHaveClass(/\bon\b/);
 await expect(items.nth(1).locator('.ag.codex')).toHaveCount(1);
 await expect(items.nth(0)).toHaveAttribute('aria-label',/неделя/);await expect(items.nth(0)).toHaveAttribute('aria-label',/Остаток/);
 await expect(page.locator('#send_state .quota-more')).toBeHidden();
 await expect(page.locator('aside .quota-item')).toHaveCount(0);
 for(const item of await items.all()){
  await expect(item.locator('.quota-plan')).toHaveText(/^[0-9]+%$/);await expect(item.locator('.quota-reset')).toContainText('↻');
  expect(await item.evaluate(e=>e.getBoundingClientRect().height)).toBeLessThanOrEqual(32);
 }
});

test('limits that do not fit a 320px phone fold behind a button and keep the session own one',async({app,page})=>{
 const resets_at=Date.now()/1000+90000;
 app.usage={claude:{windows:[{label:'неделя',percent:73,secs:604800,resets_at}]},codex:{windows:[{label:'неделя',percent:30,secs:604800,resets_at}]},kimi:{windows:[{label:'Общий · месяц',period:'month',percent:18,secs:2592000,resets_at}]}};
 await app.open({width:320});
 const line=page.locator('#send_state .session-status'),more=line.locator('.quota-more');
 await expect(line.locator('.quota-item')).toHaveCount(3);
 await expect(line.locator('.quota-item.on')).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await expect(more).toBeVisible();
 await expect(more).toHaveAttribute('aria-expanded','false');
 expect(await line.locator('.quota-item:visible').count()).toBeLessThan(3);
 await more.click();
 await expect(more).toHaveAttribute('aria-expanded','true');
 await expect(line.locator('.quota-item:visible')).toHaveCount(3);
});

test('local composer displays shortened model and explicitly labelled average speed',async({app,page})=>{
 const model='qwen3.8-27b-turbo-fable-cold-fusion-735-882-heretic-uncensored-neo-coder-max-mtp';
 app.sessions[0].agent='claude';app.sessions[0].source={kind:'lmstudio',profile:'local',model,binding:'session'};
 app.lmstudio.profiles=[{id:'local',name:'RED',performance:{source:'session',model,output_tokens:180,request_time_seconds:273.5},activity:[{binding:'session',model,phase:'waiting',request_time_seconds:228,chunks:0}]}];
 await app.open({width:390});
 await expect(page.locator('#msg')).toHaveAttribute('placeholder','Сообщение в Qwen3.8 27B · RED…');
 const state=page.locator('#send_state');await expect(state).toContainText('Qwen3.8 27B');await expect(state).toContainText('TTFT 3:48');await expect(state).toContainText('≈0.7 tok/s сред.');
 await expect(state.locator('.local-rate')).toHaveAttribute('title',/учётом ожидания/);
 // The model and its speed share the status line under the message field and never widen the page.
 expect(await state.evaluate(e=>e.getBoundingClientRect().height)).toBeLessThan(40);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('stopped local agent keeps draft and never sends it to the shell',async({app,page})=>{
 app.sessions[0].agent='claude';app.sessions[0].source={kind:'lmstudio',profile:'local',model:'qwen-coder'};app.sessions[0].running=false;app.sessions[0].command='bash';
 await app.open();await page.locator('#msg').fill('Do not execute this in bash');await page.locator('#b_send').click();
 expect(app.sends).toEqual([]);await expect(page.locator('#msg')).toHaveValue('Do not execute this in bash');await expect(page.locator('#send_state')).toContainText('не запущен');
 await page.evaluate(()=>setMode('term'));await expect(page.locator('#stage iframe')).toHaveAttribute('inert','');
});

test.describe('planned remaining uses the end of the local calendar day',()=>{
 test.use({timezoneId:'America/New_York'});
 test('handles daylight savings, a reset today and missing period information',async({app,page})=>{
  await app.open();
  const values=await page.evaluate(()=>{
   const instant=Date.parse('2026-11-01T00:00:00-04:00')/1000;
   return [plannedRemaining({secs:604800,resets_at:Date.parse('2026-11-08T00:00:00-05:00')/1000},instant),plannedRemaining({secs:18000,resets_at:instant+3600},instant),plannedRemaining({resets_at:instant+3600},instant)];
  });
  expect(values).toEqual([86,0,null]);
 });
});

test('monthly Kimi plan uses the calendar month when API duration is zero',async({app,page})=>{
 await app.open();
 const values=await page.evaluate(()=>{
  const epoch=date=>Date.parse(date)/1000;
  return [quotaDuration({period:'month',secs:0,resets_at:epoch('2026-11-01T00:00:00Z')})/86400,quotaDuration({period:'month',secs:0,resets_at:epoch('2024-03-31T00:00:00Z')})/86400,plannedRemaining({period:'month',secs:0,resets_at:epoch('2026-11-01T00:00:00Z')},epoch('2026-10-04T12:00:00Z'))];
 });
 expect(values).toEqual([31,31,87]);
});

test('remaining quota colors compare with the daily plan rather than absolute usage',async({app,page})=>{
 await app.open();
 const colors=await page.evaluate(()=>[quotaTone(26,20),quotaTone(70,77),quotaTone(75,77),quotaTone(74,77),quotaTone(10,10),quotaTone(25,null)]);
 expect(colors).toEqual(['good','crit','over','over','good','']);
});
