// Public documentation captures use entirely synthetic sessions, accounts and output.
const {test,expect,session}=require('../tests/frontend/fixtures');
const path=require('node:path');
const fs=require('node:fs');
const version=fs.readFileSync(path.resolve(__dirname,'../panel/VERSION'),'utf8').trim();
const target=name=>path.resolve(__dirname,'../docs/screenshots',name+'.png');
async function demo(app,page){
 app.language='en';app.version={version,latest:version,update:false,can_update:true,job:{phase:'idle'}};
 app.telegramConfig={available:true,configured:true,paired:true,enabled:true,bot:'agent_deck_demo_bot',account:'demo_user'};
 app.sessions=[
  session('agent-deck',{group:'agent-deck',preview:`Agent Deck · v${version}\n\n✓ Telegram answer delivered to Codex\n✓ English and Russian interface\n✓ Linux and macOS installation\n\n• Settings → Interface language\n• Private Telegram pairing\n• Persistent sessions and drafts\n\nReady for the next task.`,path:'/home/demo/projects/agent-deck'}),
  session('api-tests',{agent:'claude',group:'agent-deck',activity:Date.now()/1000,path:'/home/demo/projects/agent-deck'}),
  session('terminal',{agent:'shell',group:'agent-deck',command:'bash',path:'/home/demo/projects/agent-deck'}),
  session('landing',{agent:'claude',group:'website',path:'/home/demo/projects/website'}),
  session('mobile-ui',{group:'website',activity:Date.now()/1000,path:'/home/demo/projects/website'})
 ];
 const now=Date.now()/1000;
 app.usage={codex:{plan:'Plus',windows:[{label:'5 часов',percent:34,secs:18000,resets_at:now+5400},{label:'неделя',percent:28,secs:604800,resets_at:now+345600}]},claude:{plan:'Max',windows:[{label:'неделя',percent:41,secs:604800,resets_at:now+345600}]}};
 await page.route('**/api/agents',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({codex:{installed:true,logged_in:true,version:'0.160.0'},claude:{installed:true,logged_in:true},kimi:{installed:true,logged_in:false},kimi_config:{configured:false}})}));
 await app.open({active:'agent-deck',mode:'screen'});
 await expect(page.locator('#ver')).toContainText(version);
 await page.evaluate(()=>document.activeElement?.blur());
}
test('desktop',async({app,page},info)=>{
 test.skip(info.project.name!=='desktop');await demo(app,page);await page.screenshot({path:target('desktop')});
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
 await page.evaluate(()=>{$('integrations_dlg').close();openSettings()});
 await expect(page.locator('#ui_language')).toHaveValue('en');
 await page.evaluate(()=>document.activeElement?.blur());
 await page.screenshot({path:target('mobile-settings')});
});
