// Public documentation captures use entirely synthetic sessions, accounts and output.
const {test,expect,session}=require('../tests/frontend/fixtures');
const path=require('node:path');
const fs=require('node:fs');
const version=fs.readFileSync(path.resolve(__dirname,'../panel/VERSION'),'utf8').trim();
const target=name=>path.resolve(__dirname,'../docs/screenshots',name+'.png');
async function demo(app,page,before){
 app.language='en';app.version={version,latest:version,update:false,can_update:true,job:{phase:'idle'}};
 app.lmstudio.profiles=[{id:'abcdef012345abcdef012345',name:'Mac Studio',url:'http://100.64.0.2:1234',status:'online',key_saved:false,models:[{id:'qwen-coder',name:'Qwen Coder',loaded:true,context_length:32768,tool_tested:true}],performance:{model:'qwen-coder',source:'session',tokens_per_second:45.2,time_to_first_token_seconds:0.31}}];
 app.telegramConfig={available:true,configured:true,paired:true,enabled:true,bot:'agent_deck_demo_bot',account:'demo_user'};
 app.sessions=[
  session('agent-deck',{group:'agent-deck',preview:`Agent Deck · v${version}\n\n✓ Telegram answer delivered to Codex\n✓ Interface in 16 languages\n✓ Linux and macOS installation\n\n• Settings → Interface language\n• Private Telegram pairing\n• Persistent sessions and drafts\n\nReady for the next task.`,path:'/home/demo/projects/agent-deck'}),
  session('api-tests',{agent:'claude',group:'agent-deck',activity:Date.now()/1000,path:'/home/demo/projects/agent-deck'}),
  session('terminal',{agent:'shell',group:'agent-deck',command:'bash',path:'/home/demo/projects/agent-deck'}),
  session('landing',{agent:'claude',group:'website',path:'/home/demo/projects/website'}),
  session('mobile-ui',{group:'website',activity:Date.now()/1000,path:'/home/demo/projects/website'})
 ];
 const now=Date.now()/1000;
 app.usage={codex:{plan:'Plus',windows:[{label:'5 часов',percent:34,secs:18000,resets_at:now+5400},{label:'неделя',percent:28,secs:604800,resets_at:now+345600}]},claude:{plan:'Max',windows:[{label:'неделя',percent:41,secs:604800,resets_at:now+345600}]}};
 await page.route('**/api/decks',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({decks:[],discovery:{phase:'idle',results:[]}})}));
 await page.route('**/api/network',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({name:'demo-server',public_url:'',bind_host:'100.64.0.1',bind_port:8790})}));
 await page.route('**/api/agents',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({codex:{installed:true,logged_in:true,version:'0.160.0'},claude:{installed:true,logged_in:true},kimi:{installed:true,logged_in:false},kimi_config:{configured:false}})}));
 if(before)await before();
 await app.open({active:'agent-deck',mode:'screen'});
 await expect(page.locator('#ver')).toContainText(version);
 await page.evaluate(()=>document.activeElement?.blur());
}
test('desktop',async({app,page},info)=>{
 test.skip(info.project.name!=='desktop');await demo(app,page);await page.screenshot({path:target('desktop')});await page.evaluate(()=>openSettings('models'));await expect(page.locator('#model_cards')).toContainText('Mac Studio');await page.screenshot({path:target('desktop-models')});
});
test('phone screens',async({app,page},info)=>{
 test.skip(info.project.name!=='phone');await demo(app,page);
 await page.screenshot({path:target('mobile-screen')});
 await page.evaluate(()=>drawer(true));await expect(page.locator('aside')).toHaveCSS('transform','matrix(1, 0, 0, 1, 0, 0)');
 await page.screenshot({path:target('mobile-sessions')});
 await page.evaluate(()=>{drawer(false);openNew();pickAgent('codex')});
 await page.locator('#n_name').fill('telegram-bot');await page.locator('#n_proj').fill('agent-deck');
 await page.evaluate(()=>document.activeElement?.blur());
 await page.screenshot({path:target('mobile-new')});
 await page.evaluate(()=>{$('dlg').close();openIntegrations()});
 await expect(page.locator('#telegram_state')).toContainText('demo_user');
 await page.evaluate(()=>document.activeElement?.blur());
 await page.screenshot({path:target('mobile-integrations')});
 await page.evaluate(()=>{closeIntegrations();openSettings('app')});
 await expect(page.locator('#ui_language')).toHaveValue('en');
 await page.evaluate(()=>document.activeElement?.blur());
 await page.screenshot({path:target('mobile-settings')});await page.evaluate(()=>openSettings('models'));await page.screenshot({path:target('mobile-models')});
});

const json=body=>route=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
const DECK='b'.repeat(24);
// A synthetic "screenshot an agent made", rendered on the fly so no real product appears in docs.
async function agentScreenshot(page,title,accent){
 const shot=await page.context().newPage();
 await shot.setViewportSize({width:360,height:220});
 await shot.setContent(`<body style="margin:0;font:15px Inter,sans-serif;background:#f4f5f7;color:#1d1d1f"><div style="padding:22px"><div style="font-weight:700;font-size:20px">${title}</div><div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:18px">${['Open','Paid','Refunds','Issues'].map((t,i)=>`<div style="background:#fff;border-radius:14px;padding:16px;box-shadow:0 1px 3px #0001"><div style="color:#86868b;font-size:13px">${t}</div><div style="font-size:26px;font-weight:700;color:${i===3?accent:'#1d1d1f'}">${[12,48,3,2][i]}</div></div>`).join('')}</div></div></body>`);
 const png=await shot.screenshot({type:'png'});await shot.close();return png;
}
test('phone features',async({app,page},info)=>{
 test.skip(info.project.name!=='phone');
 const cashier=await agentScreenshot(page,'Cashier','#e5484d'),issues=await agentScreenshot(page,'Cashier · issues','#0a84ff');
 await demo(app,page,async()=>{
  app.sessions[0].preview='• Done. The cashier shows a compact counter\nand an "Open review" button.\n\n  Checks passed. Commit 88df2f9.\n\n  Cashier (/tmp/demo-preview/cashier_viewport.png) · Issues\n(/tmp/demo-preview/cashier_issues_viewport.png)\n\n  Worked for 12m 4s';
  await page.route('**/api/image?*',route=>route.fulfill({contentType:'image/png',body:route.request().url().includes('issues')?issues:cashier}));
  await page.route('**/api/question?*',json({question:null}));
 });
 await page.waitForTimeout(600);
 await page.screenshot({path:target('mobile-images')});
 await page.unroute('**/api/question?*');
 await page.route('**/api/question?*',json({question:{id:'q1',title:'Codex wants to run: npm run deploy -- --prod\nAllow this command?',progress:'',selected:0,
  options:[{label:'Yes',text:false},{label:'Yes, and do not ask again for npm',text:false},{label:'No, tell Codex what to do instead',text:true}]}}));
 await page.evaluate(()=>{const p=$('pre');load()});await page.waitForTimeout(800);
 await page.screenshot({path:target('mobile-question')});
});
test('phone notifications',async({app,page},info)=>{
 test.skip(info.project.name!=='phone');
 await demo(app,page,async()=>{
  await page.addInitScript(()=>{Object.defineProperty(navigator,'standalone',{get:()=>true});localStorage.setItem('cc.push-id','phone')});
  const now=Math.floor(Date.now()/1000);
  await page.route('**/api/push',json({available:true,error:'',public_key:'BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8',
   devices:[{id:'phone',label:'iPhone · Safari',created:now-86400},{id:'mac',label:'Mac · Chrome',created:now-7200}],events:{questions:true,finished:true}}));
 });
 await page.evaluate(()=>openSettings('connections'));await page.waitForTimeout(700);
 await page.evaluate(()=>document.activeElement?.blur());
 await page.screenshot({path:target('mobile-notifications')});
});
test('desktop computers and backups',async({app,page},info)=>{
 test.skip(info.project.name!=='desktop');
 const now=Math.floor(Date.now()/1000);
 await demo(app,page,async()=>{
  await page.route('**/deck/'+DECK+'/api/**',json({}));
  await page.route('**/deck/'+DECK+'/api/sessions*',json({sessions:[session('ml-train',{agent:'claude',group:'ml',path:'/Users/demo/dev/ml',activity:Date.now()/1000}),session('notebook',{agent:'codex',group:'ml',path:'/Users/demo/dev/ml'})]}));
  await page.route('**/api/decks',json({decks:[{id:DECK,name:'Mac Studio',url:'http://100.64.0.2:8790',username:'demo'}],discovery:{phase:'idle',results:[]}}));
  await page.route('**/api/backups',json({configured:true,key_id:'3f9a1c02b7de',instance:'c'.repeat(24),name:'demo-server',last:now-3600,
   stored:[{origin:'c'.repeat(24),name:'demo-server',created:now-3600,size:8200},{origin:DECK,name:'Mac Studio',created:now-3500,size:12400}],
   report:{started:now-3600,finished:now-3590,machines:[{name:'Mac Studio',ok:true,copies:1}]}}));
 });
 await page.evaluate(()=>loadDeckSettings());await page.waitForTimeout(900);
 await page.screenshot({path:target('desktop-computers')});
 await page.evaluate(()=>openSettings('backups'));await page.waitForTimeout(700);
 await page.evaluate(()=>document.activeElement?.blur());
 await page.screenshot({path:target('desktop-backups')});
});
