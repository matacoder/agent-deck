const {test,expect}=require('./fixtures');

test('quota monitor shows only overall period, percent and reset in compact rows',async({app,page})=>{
 const resets_at=Date.now()/1000+90000;
 app.usage={claude:{windows:[{label:'5 часов',percent:7,secs:18000,resets_at},{label:'неделя',percent:73,secs:604800,resets_at}]},codex:{windows:[{label:'неделя',percent:30,secs:604800,resets_at}]},kimi:{windows:[{label:'Kimi Code · месяц',period:'month',percent:0,secs:2592000,resets_at},{label:'Общий · месяц',period:'month',percent:18,secs:2592000,resets_at}]}};
 await app.open({width:1280,height:900});
 const rows=page.locator('.quota-strip');await expect(rows).toHaveCount(3);
 await expect(page.locator('.quota-heading')).toContainText('Остаток');await expect(page.locator('.quota-heading-plan')).toHaveText('План');
 const alignment=await page.evaluate(()=>{const heading=document.querySelector('.quota-heading-plan').getBoundingClientRect(),planned=document.querySelector('.quota-strip .quota-plan').getBoundingClientRect();return Math.abs(heading.right-planned.right)});
 expect(alignment).toBeLessThan(1);
 await expect(rows.nth(0)).toContainText('27%');await expect(rows.nth(1)).toContainText('70%');await expect(rows.nth(2)).toContainText('82%');
 for(const row of await rows.all()){expect(await row.evaluate(e=>e.getBoundingClientRect().height)).toBeLessThanOrEqual(32);await expect(row).toContainText('↻');}
});

test('local composer displays shortened model and explicitly labelled average speed',async({app,page})=>{
 const model='qwen3.8-27b-turbo-fable-cold-fusion-735-882-heretic-uncensored-neo-coder-max-mtp';
 app.sessions[0].agent='claude';app.sessions[0].source={kind:'lmstudio',profile:'local',model,binding:'session'};
 app.lmstudio.profiles=[{id:'local',name:'RED',performance:{source:'session',model,output_tokens:180,request_time_seconds:273.5},activity:[{binding:'session',model,phase:'waiting',request_time_seconds:228,chunks:0}]}];
 await app.open({width:390});
 await expect(page.locator('#msg')).toHaveAttribute('placeholder','Сообщение в Qwen3.8 27B · RED…');
 const state=page.locator('#send_state');await expect(state).toContainText('Qwen3.8 27B');await expect(state).toContainText('TTFT 3:48');await expect(state).toContainText('≈0.7 tok/s avg');
 await expect(state.locator('.local-rate')).toHaveAttribute('title',/учётом ожидания/);
 await page.evaluate(()=>drawer(true));expect(await page.locator('.compact-local').evaluate(e=>e.getBoundingClientRect().height)).toBeLessThan(80);
 expect(await page.locator('aside').evaluate(e=>e.scrollWidth<=e.clientWidth)).toBe(true);
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
