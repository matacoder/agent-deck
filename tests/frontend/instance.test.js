/**
 * @jest-environment node
 *
 * Runs the real bundled panel (panel/index.html) in jsdom with a fake network to cover switching
 * between connected Agent Decks without a page reload.
 */
const fs=require('fs');
const path=require('path');
const {JSDOM,VirtualConsole}=require('jsdom');

const DECK='a'.repeat(24);
const page=fs.readFileSync(path.resolve(__dirname,'../../panel/index.html'),'utf8')
  .replace('__PANEL_I18N__',JSON.stringify({language:'en',messages:{}})).replace(/__PANEL_REVISION__/g,'test');
const session=(name,extra={})=>({name,title:name,agent:'codex',group:'demo',path:'/home/demo/projects/'+name,running:true,activity:1,created:1,...extra});

function boot(routes,opened,setup){
  // jsdom cannot replace location.reload; a reload shows up as a "navigation" not-implemented error.
  const console=new VirtualConsole(),problems=[];
  console.on('jsdomError',error=>problems.push(String(error.message)));
  const dom=new JSDOM(page,{url:'https://panel.test/',runScripts:'dangerously',pretendToBeVisual:true,virtualConsole:console,beforeParse(window){
    window.focus=()=>{};
    // The 25 s read timeout fires at once here, so a parked request can be tested quickly.
    const nativeTimeout=window.setTimeout.bind(window);
    window.setTimeout=(fn,ms,...args)=>nativeTimeout(fn,ms===25000?0:ms,...args);
    // A tapped notification as the service worker leaves it in Cache Storage.
    const store=new Map(opened?[['/__agent-deck-open',JSON.stringify({...opened,at:Date.now()})]]:[]);
    window.notificationTargets=store;
    window.caches={open:async()=>({match:async key=>store.has(key)?{json:async()=>JSON.parse(store.get(key))}:undefined,delete:async key=>store.delete(key)})};
    Object.defineProperty(window.navigator,'serviceWorker',{value:{addEventListener(){},startMessages(){},register:()=>Promise.resolve()}});
    Object.defineProperty(window,'isSecureContext',{value:true});
    window.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}});
    window.ResizeObserver=class{observe(){}};
    window.HTMLDialogElement.prototype.showModal=function(){this.open=true};
    window.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new window.Event('close'))};
    window.HTMLElement.prototype.scrollIntoView=()=>{};
    if(setup)setup(window);
    window.fetch=async(url,options={})=>{
      const target=new URL(url,'https://panel.test/');
      if(routes.__parked&&target.pathname===routes.__parked)return new Promise((_,reject)=>options.signal?.addEventListener('abort',()=>reject(new Error('aborted'))));
      const handler=routes[target.pathname];
      const body=handler?await handler(target,options):{};
      if(body&&body.__network)throw new TypeError('Load failed');
      if(body&&body.__html)return {ok:true,status:200,headers:{get:()=>null},json:async()=>{throw new SyntaxError('Unexpected token <')}};
      if(body&&body.__status)return {ok:false,status:body.__status,headers:{get:()=>null},json:async()=>({error:body.error})};
      return {ok:true,status:200,headers:{get:()=>null},json:async()=>body};
    };
  }});
  dom.window.problems=problems;
  return dom.window;
}
const settle=()=>new Promise(resolve=>setTimeout(resolve,30));

function routesFor(state){
  return {
    '/api/sessions':()=>state.local(),
    ['/deck/'+DECK+'/api/sessions']:()=>({sessions:[session('beta')]}),
    '/api/decks':()=>({decks:[{id:DECK,name:'Mac Studio',url:'http://100.64.0.2:8790',username:'demo'}],discovery:{phase:'idle',results:[]}}),
    '/api/network':()=>({name:'gateway',public_url:'',bind_host:'100.64.0.1',bind_port:8790}),
  };
}

test('switching computers keeps each draft on its own machine without reloading',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const window=boot(routesFor(state));
  try{
  await settle();await settle();
  expect(window.document.querySelector('#title b').textContent).toBe('alpha');
  const message=window.document.getElementById('msg');
  message.value='draft for alpha';message.dispatchEvent(new window.Event('input'));

  window.openDeckSession(DECK,'beta');
  await settle();await settle();
  expect(window.problems.filter(p=>p.includes('navigation'))).toEqual([]);
  expect(window.document.querySelector('#title b').textContent).toBe('beta');
  expect(message.value).toBe('');
  expect(window.document.querySelector('.tab.remote .n').textContent).toBe('alpha');

  window.openDeckSession('','alpha');
  await settle();await settle();
  expect(window.document.querySelector('#title b').textContent).toBe('alpha');
  expect(message.value).toBe('draft for alpha');
  expect(window.problems.filter(p=>!p.includes('window.focus'))).toEqual([]);
  }finally{window.close()}
});

test('a response from the previous computer that arrives after the switch is rejected',async()=>{
  let release;
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state);
  routes['/api/usage']=()=>new Promise(resolve=>{release=()=>resolve({claude:{windows:[]}})});
  const window=boot(routes);
  try{
  await settle();await settle();
  // A request issued for the gateway, still in flight while the user switches computers.
  const inFlight=window.eval('api("/api/usage")');
  await settle();
  window.openDeckSession(DECK,'beta');
  await settle();
  release();
  await expect(inFlight).rejects.toThrow('stale Agent Deck response');
  expect(window.document.querySelector('#title b').textContent).toBe('beta');
  }finally{window.close()}
});

test('an unchanged sidebar keeps its nodes, so focus and screen-reader position survive polls',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const window=boot(routesFor(state));
  try{
  await settle();await settle();
  const row=window.document.querySelector('#tabs [data-session="alpha"]');
  window.eval('renderTabs()');
  expect(window.document.querySelector('#tabs [data-session="alpha"]')).toBe(row);
  state.local=()=>({sessions:[session('alpha',{title:'Renamed'})]});
  await window.eval('load()');await settle();
  expect(window.document.querySelector('#tabs [data-session="alpha"] .n').textContent).toBe('Renamed');
  }finally{window.close()}
});

test('gateway answers survive a switch: the sidebar keeps other computers reachable',async()=>{
  let release;
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state);
  routes['/api/inbox']=()=>new Promise(resolve=>{release=()=>resolve({questions:[]})});
  const window=boot(routes);
  try{
  await settle();await settle();
  // Inbox, update-all and other computers' lists go to the gateway whatever computer is selected.
  const inFlight=window.eval('api("/api/inbox",null,true)');
  await settle();
  window.openDeckSession(DECK,'beta');
  await settle();
  release();
  await expect(inFlight).resolves.toEqual({questions:[]});
  await window.eval('loadOtherDecks()');await settle();
  expect(window.document.querySelector('.tab.remote .n').textContent).toBe('alpha');
  expect([...window.document.querySelectorAll('.deck-count')].map(n=>n.textContent)).not.toContain('unavailable');
  }finally{window.close()}
});

test('a read that iOS parked in the background gives up instead of blocking every later poll',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state);
  const window=boot(routes);
  try{
  await settle();await settle();
  routes.__parked='/api/usage';
  await expect(window.eval('api("/api/usage")')).rejects.toMatchObject({offline:true});
  }finally{window.close()}
});

test('project files: browse, open .env, paste a secret and save it with the version that was opened',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state),saved=[];
  routes['/api/files']=url=>url.searchParams.get('path')?{path:'/home/demo/projects/alpha/config',home:'/home/demo',parent:'/home/demo/projects/alpha',entries:[{name:'.env',dir:false,size:9,mtime:1}]}
    :{path:'/home/demo/projects/alpha',home:'/home/demo',parent:'/home/demo/projects',entries:[{name:'config',dir:true,size:0,mtime:1}]};
  routes['/api/file']=()=>({path:'/home/demo/projects/alpha/config/.env',content:'TOKEN=\n',hash:'h1',size:7});
  routes['/api/file_save']=(url,options)=>{saved.push(JSON.parse(options.body));return {ok:true,hash:'h2'}};
  const window=boot(routes);
  try{
  await settle();await settle();
  const doc=window.document;
  await window.eval('openFiles()');await settle();
  expect(doc.querySelector('.files-crumbs').textContent).toBe('~/projects/alpha');
  expect(doc.querySelector('.files-crumbs .here').textContent).toBe('alpha');
  doc.querySelector('.files-row.dir').click();await settle();
  doc.querySelector('.files-row').click();await settle();
  // Reading first: wrapped numbered lines and no editable field, so the keyboard stays down.
  expect(doc.querySelector('.files-text')).toBeNull();
  expect([...doc.querySelectorAll('.files-view .code')].map(n=>n.textContent)).toEqual(['TOKEN=']);
  [...doc.querySelectorAll('#files_body button')].find(b=>b.textContent==='Изменить'||b.textContent==='Edit').click();await settle();
  const area=doc.querySelector('.files-text');
  expect(area.value).toBe('TOKEN=\n');
  area.value='TOKEN=pasted-secret\n';area.dispatchEvent(new window.Event('input'));
  [...doc.querySelectorAll('#files_body button')].find(b=>b.textContent==='Сохранить'||b.textContent==='Save').click();await settle();
  expect(saved).toEqual([{path:'/home/demo/projects/alpha/config/.env',content:'TOKEN=pasted-secret\n',hash:'h1'}]);
  // A saved file closes without asking; an edited one asks first.
  area.value='TOKEN=changed\n';area.dispatchEvent(new window.Event('input'));
  const leaving=window.eval('leaveFile()');await settle();
  expect(doc.getElementById('confirm_dlg').open).toBe(true);
  doc.getElementById('confirm_dlg').close();await settle();
  await expect(leaving).resolves.toBe(false);
  expect(doc.querySelector('.files-text').value).toBe('TOKEN=changed\n');
  }finally{window.close()}
});

test('the code font size changes in steps, stays within limits and is remembered',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const window=boot(routesFor(state));
  try{
  await settle();
  window.eval('codeFont(1);codeFont(1)');
  expect(window.localStorage.getItem('cc.code-font')).toBe('14');
  expect(window.document.documentElement.style.getPropertyValue('--code-font')).toBe('14px');
  window.eval('for(let i=0;i<30;i++)codeFont(-1)');
  expect(window.localStorage.getItem('cc.code-font')).toBe('9');
  }finally{window.close()}
});

test('switching sessions never shows the previous screen: a skeleton waits for the new one',async()=>{
  let release;
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state);
  routes['/api/sessions']=url=>{
    const wanted=url.searchParams.get('preview');
    const list=()=>({sessions:[session('alpha',{preview:wanted==='alpha'?'ALPHA SCREEN':undefined}),session('beta',{preview:wanted==='beta'?'BETA SCREEN':undefined})]});
    return wanted==='beta'?new Promise(resolve=>{release=()=>resolve(list())}):list();
  };
  const window=boot(routes);
  try{
  const pre=window.document.getElementById('pre');
  await settle();window.eval('setMode("screen")');
  for(let i=0;i<20&&!pre.textContent.includes('ALPHA SCREEN');i++)await settle();
  expect(pre.textContent).toContain('ALPHA SCREEN');
  window.eval('select("beta")');await settle();
  expect(pre.textContent).not.toContain('ALPHA SCREEN');
  expect(pre.querySelector('.screen-skeleton')).not.toBeNull();
  release();
  for(let i=0;i<20&&!pre.textContent.includes('BETA SCREEN');i++)await settle();
  expect(pre.textContent).toContain('BETA SCREEN');
  expect(pre.querySelector('.screen-skeleton')).toBeNull();
  }finally{window.close()}
});

test('history drops an answer for a branch that is no longer selected and never loads a page twice',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state),pending={},calls=[];
  const page=(ref,subject,more)=>({repo:'/r',name:'r',branch:ref||'feature',ref:ref||'HEAD',branches:['feature','origin/main'],remote:'origin/main',ahead:0,behind:0,
    commits:[{sha:subject.padEnd(40,'0'),short:subject,author:'a',time:1,subject,files:1,added:1,removed:0}],more});
  routes['/api/git/log']=url=>{calls.push(url.searchParams.get('ref')+':'+url.searchParams.get('skip'));
    if(url.searchParams.get('ref')==='')return new Promise(resolve=>{pending.feature=()=>resolve(page('','old-branch',true))});
    return url.searchParams.get('skip')==='0'?page('origin/main','prod',true):new Promise(resolve=>{pending.more=()=>resolve(page('origin/main','prod-older',false))})};
  routes['/api/git/changes']=()=>({repo:'/r',name:'r',branch:'feature',files:[],skipped:0});
  const window=boot(routes);
  try{
  await settle();await settle();
  window.eval('openHistory()');await settle();
  window.eval('historyTab("commits")');
  window.eval('chooseBranch("origin/main")');await settle();
  pending.feature();await settle();
  const subjects=()=>[...window.document.querySelectorAll('.git-subject')].map(n=>n.textContent);
  expect(subjects()).toEqual(['prod']);  // The feature branch answered late and was dropped.
  window.eval('loadHistoryPage();loadHistoryPage()');await settle();
  pending.more();await settle();await settle();
  expect(subjects()).toEqual(['prod','prod-older']);
  expect(calls.filter(c=>c==='origin/main:1')).toHaveLength(1);
  }finally{window.close()}
});

test('a tapped line of an uncommitted change becomes a comment in the session draft',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state);
  routes['/api/git/log']=()=>({repo:'/r',name:'r',branch:'main',ref:'HEAD',branches:['main'],remote:'',ahead:0,behind:0,commits:[],more:false});
  routes['/api/git/changes']=()=>({repo:'/r',name:'r',branch:'main',skipped:0,files:[{path:'app.py',old_path:'app.py',status:'modified',added:1,removed:1,binary:false,truncated:false,
    patch:'diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1,2 +1,2 @@\n a = 1\n-b = 2\n+b = 3\n'}]});
  const window=boot(routes);
  try{
  await settle();await settle();
  const doc=window.document,message=doc.getElementById('msg');
  message.value='Please check:';message.dispatchEvent(new window.Event('input'));
  window.eval('openHistory()');await settle();await settle();
  const added=doc.querySelector('#git_body .dl.add');
  added.click();
  doc.querySelector('.diff-comment textarea').value='use a constant';
  doc.querySelector('.diff-comment').requestSubmit();
  expect(message.value).toBe('Please check:\napp.py:2 `b = 3` — use a constant');
  expect(doc.querySelector('.diff-comment')).toBeNull();
  // The commits page answered meanwhile; the open Changes tab was not redrawn under the user.
  expect(doc.querySelector('#project_tabs .on').dataset.tab).toBe('changes');
  }finally{window.close()}
});

test('on a wide screen the project panel docks on the right, follows the session and is remembered',async()=>{
  const state={local:()=>({sessions:[session('alpha'),session('beta')]})};
  const routes=routesFor(state),asked=[];
  routes['/api/git/log']=()=>({repo:'/r',name:'r',branch:'main',ref:'HEAD',branches:['main'],remote:'',ahead:0,behind:0,commits:[],more:false});
  routes['/api/files']=()=>({path:'/home/demo/p',home:'/home/demo',parent:'/home/demo',entries:[]});
  routes['/api/git/changes']=url=>{asked.push(url.searchParams.get('name'));return {repo:'/r',name:url.searchParams.get('name'),branch:'main',head:'',skipped:0,files:[]}};
  const window=boot(routes);
  try{
  await settle();await settle();
  const doc=window.document,panel=doc.getElementById('project_dlg');
  doc.getElementById('b_history').click();await settle();
  expect(panel.open).toBe(true);
  expect(panel.classList.contains('docked')).toBe(true);
  expect(doc.getElementById('b_history').getAttribute('aria-pressed')).toBe('true');
  expect(window.localStorage.getItem('cc.project')).toBe('changes');
  // The terminal stays usable: a docked panel does not count as an open dialog.
  expect(doc.querySelector('dialog[open]:not(.docked)')).toBeNull();
  window.eval('select("beta")');await settle();await settle();
  expect(asked.slice(-1)).toEqual(['beta']);
  expect(doc.querySelector('#git_body .git-head code').textContent).toBe('beta');
  doc.querySelector('#project_tabs [data-tab="files"]').click();
  expect(doc.getElementById('git_body').hidden).toBe(true);
  expect(doc.getElementById('files_body').hidden).toBe(false);
  expect(window.localStorage.getItem('cc.project')).toBe('files');
  doc.getElementById('b_files').click();await settle();
  expect(panel.open).toBe(false);
  expect(window.localStorage.getItem('cc.project')).toBe('');
  // The sidebar button reopens the last tab and hides the panel again.
  doc.getElementById('b_project').click();await settle();
  expect(panel.open).toBe(true);
  expect(doc.querySelector('#project_tabs .on').dataset.tab).toBe('files');
  expect(doc.getElementById('b_project').getAttribute('aria-pressed')).toBe('true');
  doc.getElementById('b_project').click();await settle();
  expect(panel.open).toBe(false);
  }finally{window.close()}
});

test('sidebar widths change from their edge, are remembered and reset with a double click',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const window=boot(routesFor(state));
  try{
  await settle();
  const doc=window.document,root=doc.documentElement.style,handle=doc.getElementById('side_resizer');
  doc.querySelector('aside').getBoundingClientRect=()=>({width:300});
  handle.dispatchEvent(new window.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
  expect(root.getPropertyValue('--side-w')).toBe('316px');
  expect(window.localStorage.getItem('cc.side-w')).toBe('316');
  // The right sidebar grows when its edge moves left, and never below its minimum.
  doc.getElementById('project_dlg').getBoundingClientRect=()=>({width:330});
  doc.getElementById('project_resizer').dispatchEvent(new window.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
  expect(root.getPropertyValue('--project-w')).toBe('320px');
  handle.dispatchEvent(new window.MouseEvent('dblclick',{bubbles:true}));
  expect(root.getPropertyValue('--side-w')).toBe('');
  expect(window.localStorage.getItem('cc.side-w')).toBeNull();
  }finally{window.close()}
});

test('Changes follows the worktree the agent works in and a picked tree wins',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state),asked=[];
  const trees=[{path:'/r',name:'r',branch:'HEAD'},{path:'/r/.claude/worktrees/w2',name:'w2',branch:'worktree-w2'},{path:'/r/.claude/worktrees/w3',name:'w3',branch:'worktree-w3'}];
  const pick=url=>url.searchParams.get('tree')||'/r/.claude/worktrees/w2';
  routes['/api/git/log']=url=>{asked.push('log:'+url.searchParams.get('tree'));return {repo:pick(url),name:'w',branch:'b',ref:'HEAD',branches:['b'],remote:'',ahead:0,behind:0,commits:[],more:false,trees,tree:pick(url),auto:!url.searchParams.get('tree')}};
  routes['/api/git/changes']=url=>{asked.push('changes:'+url.searchParams.get('tree'));return {repo:pick(url),name:'w',branch:'b',head:'',skipped:0,files:[],trees,tree:pick(url),auto:!url.searchParams.get('tree')}};
  const window=boot(routes);
  try{
  await settle();await settle();
  const doc=window.document;
  window.eval('openHistory()');await settle();await settle();
  const select=()=>doc.querySelector('#git_body .git-tree');
  expect(doc.querySelector('#git_body .git-head code').textContent).toBe('r');
  expect(select().value).toBe('');
  expect(select().options[0].textContent).toMatch(/^w2 · worktree-w2 · /);
  // The agent moves on to w3: a quiet check picks it up without a tap.
  routes['/api/git/changes']=url=>({repo:'/r/.claude/worktrees/w3',name:'w3',branch:'worktree-w3',head:'',skipped:0,files:[],trees,tree:url.searchParams.get('tree')||'/r/.claude/worktrees/w3',auto:!url.searchParams.get('tree')});
  await window.eval('pollChanges()');await settle();
  expect(select().options[0].textContent).toMatch(/^w3 · worktree-w3 · /);
  select().value='/r/.claude/worktrees/w3';select().dispatchEvent(new window.Event('change'));await settle();await settle();
  expect(asked.slice(-1)).toEqual(['log:/r/.claude/worktrees/w3']);
  expect(select().value).toBe('/r/.claude/worktrees/w3');
  }finally{window.close()}
});

test('the actions menu keeps restarts, duplicate, rename and close; duplicate keeps agent, folder and model',async()=>{
  const state={local:()=>({sessions:[session('alpha',{agent:'claude-kimi',skip:true,source:{kind:'kimi',model:'k2',label:'Kimi · k2'}})]})};
  const routes=routesFor(state),created=[];
  routes['/api/new']=(url,options)=>{created.push(JSON.parse(options.body));return {name:'alpha-2'}};
  const window=boot(routes);
  try{
  await settle();await settle();
  const doc=window.document;
  window.eval('sheet(true)');
  const labels=[...doc.querySelectorAll('#sheet .panel button')].filter(b=>b.style.display!=='none'&&!b.closest('[hidden]')&&!b.classList.contains('sheet-cancel')).map(b=>b.textContent);
  expect(labels).toEqual(['Перезапустить — новый разговор','Перезапустить — продолжить разговор','Дублировать сессию — новый разговор','Переименовать сессию','Закрыть сессию']);
  expect(doc.getElementById('b_link')).toBeNull();
  window.eval('duplicateSession()');await settle();
  expect(created).toEqual([{name:'alpha',path:'/home/demo/projects/alpha',agent:'claude',skip:true,source:{kind:'kimi',model:'k2'}}]);
  }finally{window.close()}
});

test('output search runs from the bar field and shows results under it without a dialog',async()=>{
  const state={local:()=>({sessions:[session('alpha'),session('beta')]})};
  const routes=routesFor(state),asked=[];
  routes['/api/scrollback']=url=>{asked.push(url.searchParams.get('name')+':'+url.searchParams.get('q'));return {query:'boom',total:1,lines:10,matches:[{line:4,text:'boom here',before:[],after:[]}]}};
  const window=boot(routes);
  try{
  await settle();await settle();
  const doc=window.document,pop=doc.getElementById('search_pop');
  doc.getElementById('search_q').value='boom';
  doc.getElementById('search_form').requestSubmit();await settle();
  expect(asked).toEqual(['alpha:boom']);
  expect(pop.hidden).toBe(false);
  expect(doc.querySelector('#search_body mark').textContent).toBe('boom');
  expect(doc.querySelector('dialog[open]')).toBeNull();
  doc.getElementById('search_q').dispatchEvent(new window.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  expect(pop.hidden).toBe(true);
  // Another session starts with an empty field.
  window.eval('select("beta")');await settle();
  expect(doc.getElementById('search_q').value).toBe('');
  }finally{window.close()}
});

test('the sidebar keeps the place of local models until they load',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state);let release;
  routes['/api/lmstudio']=()=>new Promise(resolve=>{release=()=>resolve({profiles:[],discovery:{}})});
  const window=boot(routes,null,w=>{w.localStorage.setItem('cc.integ-models','1');w.localStorage.setItem('cc.integ-height','90')});
  try{
  await settle();await settle();
  const doc=window.document;
  expect(doc.querySelectorAll('#integ .integ-skeleton')).toHaveLength(1);
  expect(doc.getElementById('integ').style.minHeight).toBe('90px');
  release();await settle();await settle();
  expect(doc.querySelectorAll('#integ .integ-skeleton')).toHaveLength(0);
  }finally{window.close()}
});

test('the same Telegram bot on another computer can be turned off there from here',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state),cleared=[];
  routes['/api/integrations']=()=>({telegram:{available:true,configured:true,paired:true,enabled:true,bot:'deck_bot',duplicates:[{id:DECK,name:'Mac Studio'}]}});
  routes['/deck/'+DECK+'/api/telegram_config']=(url,options)=>{cleared.push(JSON.parse(options.body).clear);return {telegram:{}}};
  const window=boot(routes);
  try{
  await settle();await settle();
  const doc=window.document,box=doc.getElementById('telegram_duplicates');
  expect(box.hidden).toBe(false);
  [...box.querySelectorAll('button')].find(b=>/Mac Studio/.test(b.textContent)).click();await settle();
  const confirm=doc.getElementById('confirm_dlg');confirm.returnValue='ok';confirm.close();await settle();
  expect(cleared).toEqual([true]);
  expect(box.hidden).toBe(true);  // Gone at once, without waiting for the server's one-minute memory.
  }finally{window.close()}
});

test('the + of a project heading opens the new session form for that folder',async()=>{
  const state={local:()=>({sessions:[session('alpha',{group:'alpha',path:'/home/demo/projects/alpha/.claude/worktrees/w1'})]})};
  const routes=routesFor(state),created=[];
  routes['/api/projects']=()=>({projects:['alpha']});
  routes['/api/new']=(url,options)=>{created.push(JSON.parse(options.body));return {name:'alpha-2'}};
  const window=boot(routes);
  try{
  await settle();await settle();
  const doc=window.document;
  doc.querySelector('#tabs .grp-row .row-add').click();await settle();
  expect(doc.getElementById('dlg').open).toBe(true);
  expect(doc.getElementById('n_proj').value).toBe('alpha');
  window.eval('createSession()');await settle();
  expect(created[0]).toMatchObject({name:'alpha',project:'alpha',path:'/home/demo/projects/alpha'});
  // Every computer heading offers one too.
  expect(doc.querySelector('#tabs .head-row .deck-head + .row-add')).not.toBeNull();
  }finally{window.close()}
});

test('the ? next to search explains how the panel works',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const window=boot(routesFor(state));
  try{
  await settle();await settle();
  const doc=window.document;
  doc.getElementById('b_help').click();
  expect(doc.getElementById('help_dlg').open).toBe(true);
  expect(doc.querySelectorAll('#help_dlg .arch-zone').length).toBe(3);
  }finally{window.close()}
});

test('a clean working tree shows the last commit in Changes',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state),head='c'.repeat(40);
  routes['/api/git/log']=()=>({repo:'/r',name:'r',branch:'main',ref:'HEAD',branches:['main'],remote:'',ahead:0,behind:0,commits:[],more:false});
  routes['/api/git/changes']=()=>({repo:'/r',name:'r',branch:'main',head,skipped:0,files:[]});
  routes['/api/git/commit']=url=>({sha:url.searchParams.get('sha'),short:'ccccccc',author:'a',email:'',time:1,parents:[],message:'Ship it',
    files:[{path:'app.py',old_path:'app.py',status:'modified',added:1,removed:0,binary:false,truncated:false,patch:'@@ -1 +1,2 @@\n a\n+b\n'}]});
  const window=boot(routes);
  try{
  await settle();await settle();
  const doc=window.document;
  window.eval('openHistory()');await settle();await settle();
  expect(doc.querySelector('#git_body .git-title').textContent).toBe('Ship it');
  expect(doc.querySelector('#git_body .diff-path').textContent).toBe('app.py');
  // Lines of a committed change are not comments for the agent.
  expect(doc.querySelector('#git_body .dl.commentable')).toBeNull();
  }finally{window.close()}
});

test('Alt+K opens the switcher, words filter it and Enter opens the session',async()=>{
  const state={local:()=>({sessions:[session('alpha'),session('beta')]})};
  const window=boot(routesFor(state));
  try{
  await settle();await settle();
  const doc=window.document;
  doc.body.dispatchEvent(new window.KeyboardEvent('keydown',{code:'KeyK',key:'k',altKey:true,bubbles:true}));
  expect(doc.getElementById('palette_dlg').open).toBe(true);
  const input=doc.getElementById('palette_q');
  input.value='bet';input.dispatchEvent(new window.Event('input'));
  // This computer's session first, then the same name on the connected Mac.
  expect([...doc.querySelectorAll('.palette-row .palette-label')].map(n=>n.textContent)).toEqual(['beta','beta']);
  expect(doc.querySelectorAll('.palette-row .palette-hint')[1].textContent).toMatch(/^Mac Studio/);
  input.dispatchEvent(new window.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));await settle();
  expect(doc.getElementById('palette_dlg').open).toBe(false);
  expect(doc.querySelector('#title b').textContent).toBe('beta');
  }finally{window.close()}
});

test('Markdown opens rendered with a switch to text, and images preview from checked content',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state),previews=[];
  routes['/api/files']=()=>({path:'/home/demo/p',home:'/home/demo',parent:'/home/demo',entries:[{name:'README.md',dir:false,size:9},{name:'shot.png',dir:false,size:4}]});
  routes['/api/file']=()=>({path:'/home/demo/p/README.md',content:'# Title\n',hash:'h',size:9});
  routes['/api/file_preview']=url=>{previews.push(url.searchParams.get('path'));return {path:'/home/demo/p/shot.png',type:'image/png',size:4,data:'iVBORw=='}};
  const window=boot(routes);
  window.URL.createObjectURL=()=>'blob:https://panel.test/1';window.URL.revokeObjectURL=()=>{};
  try{
  await settle();await settle();
  const doc=window.document,rows=()=>[...doc.querySelectorAll('.files-row')];
  await window.eval('openFiles()');await settle();
  rows()[0].click();await settle();
  expect(doc.querySelector('#files_body .md h1').textContent).toBe('Title');
  [...doc.querySelectorAll('#files_body button')].find(b=>/Текст|Text/.test(b.textContent)).click();
  expect(doc.querySelector('#files_body .md')).toBeNull();
  expect(doc.querySelector('#files_body .files-view .code').textContent).toBe('# Title');
  [...doc.querySelectorAll('#files_body button')].find(b=>/К папке|folder/i.test(b.textContent)).click();await settle();
  rows()[1].click();await settle();
  expect(previews).toEqual(['/home/demo/p/shot.png']);
  expect(doc.querySelector('#files_body img.files-image').getAttribute('src')).toBe('blob:https://panel.test/1');
  }finally{window.close()}
});

function settingsRoutes(state,agents){
  const routes=routesFor(state);
  routes['/api/agents']=()=>agents;
  routes['/api/push']=()=>({available:true,error:'',public_key:'x',devices:[],events:{questions:true,finished:true}});
  routes['/api/backups']=()=>({configured:false,stored:[],report:null});
  routes['/api/lmstudio']=()=>({profiles:[{id:'p1',name:'Studio',url:'http://100.64.0.2:1234',status:'offline',models:[]}],discovery:{}});
  routes['/api/agent_login']=()=>({ok:true});
  return routes;
}

test('settings open on new sections, accept old names and mark what needs attention',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const window=boot(settingsRoutes(state,{claude:{installed:true,logged_in:false,version:'2.1'},codex:{installed:false}}));
  try{
  await settle();await settle();
  const doc=window.document;
  await window.eval('openSettings("connections")');await settle();
  expect(doc.getElementById('hub_notifications').hidden).toBe(false);
  expect(doc.getElementById('tab_notifications').getAttribute('aria-selected')).toBe('true');
  await window.eval('openSettings("agents")');await settle();
  const claude=doc.querySelector('#agent_cards [data-card="claude"]');
  expect(claude.querySelector('.card-status').textContent).toBe('Вход не выполнен');
  expect(claude.querySelector('.card-status').classList.contains('warn')).toBe(true);
  expect([...doc.querySelectorAll('.hub-nav .attn')].map(b=>b.dataset.section).sort()).toEqual(['agents','backups','models']);  // No push support here, so notifications cannot be asked for.
  expect(doc.querySelector('#setup_card').textContent).toContain('Войдите в Claude или Codex');
  // Signing in runs in its own session: Settings closes so that session is visible.
  claude.querySelector('.card-tools .pri').click();await settle();await settle();
  expect(doc.getElementById('settings_dlg').open).toBe(false);
  }finally{window.close()}
});

test('Escape closes an open settings editor first and asks before dropping a typed key',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const window=boot(settingsRoutes(state,{claude:{installed:true,logged_in:true},kimi:{installed:true},kimi_config:{configured:false}}));
  try{
  await settle();await settle();
  const doc=window.document,dialog=doc.getElementById('settings_dlg');
  await window.eval('openSettings("agents")');await settle();
  window.eval('openKimi()');
  expect(doc.getElementById('kimi_dlg').hidden).toBe(false);
  expect(doc.querySelector('#agent_cards [data-card="kimi"]').hidden).toBe(true);  // The editor takes the card's place.
  dialog.dispatchEvent(new window.Event('cancel',{cancelable:true}));await settle();
  expect(dialog.open).toBe(true);
  expect(doc.getElementById('kimi_dlg').hidden).toBe(true);
  window.eval('openKimi()');doc.getElementById('kimi_key').value='sk-typed';
  dialog.dispatchEvent(new window.Event('cancel',{cancelable:true}));await settle();
  expect(doc.getElementById('confirm_dlg').open).toBe(true);
  expect(doc.getElementById('kimi_dlg').hidden).toBe(false);
  }finally{window.close()}
});

test('files dropped on the window are uploaded to the open session',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const window=boot(routesFor(state)),uploads=[];
  try{
  await settle();await settle();
  // The upload itself (XHR with progress) is covered by the paperclip; here the drop must reach it.
  window.uploadImages=files=>uploads.push(...files.map(f=>f.name));
  const drag=type=>{const e=new window.Event(type,{bubbles:true,cancelable:true});
    Object.defineProperty(e,'dataTransfer',{value:{types:['Files'],files:[new window.File(['png'],'shot.png',{type:'image/png'})],dropEffect:''}});return e};
  window.document.body.dispatchEvent(drag('dragover'));
  expect(window.document.getElementById('drop_zone').hidden).toBe(false);
  expect(window.document.getElementById('drop_title').textContent).toBe('Отпустите, чтобы приложить к «alpha»');
  const drop=drag('drop');window.document.body.dispatchEvent(drop);
  expect(drop.defaultPrevented).toBe(true);
  expect(window.document.getElementById('drop_zone').hidden).toBe(true);
  await settle();await settle();
  expect(uploads).toEqual(['shot.png']);
  }finally{window.close()}
});

test('switching computers keeps the computers in one order in the sidebar',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const window=boot(routesFor(state));
  try{
  await settle();await settle();
  const heads=()=>[...window.document.querySelectorAll('#tabs .deck-head .deck-name')].map(n=>n.textContent);
  const before=heads();
  expect(before.length).toBe(2);
  const inbox=window.document.getElementById('inbox_btn'),srv=window.document.getElementById('srv');
  window.localStorage.setItem('deck.'+DECK+'.cc.server',JSON.stringify({ip:'203.0.113.7',hostname:'mac'}));
  window.openDeckSession(DECK,'beta');
  // Right after the switch, before the new computer answers, its last known address is already there.
  expect(inbox.hidden).toBe(false);
  expect(srv.querySelector('.ip').textContent).toBe('203.0.113.7');
  await settle();await settle();
  expect(heads()).toEqual(before);
  // The computer we left keeps its project headings in its section.
  expect([...window.document.querySelectorAll('#tabs .grp')].map(n=>n.textContent)).toEqual(['demo','demo']);
  window.openDeckSession('','alpha');await settle();await settle();
  expect(heads()).toEqual(before);
  }finally{window.close()}
});

test('returning to the app with a stale keyboard height and nothing focused fills the screen again',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const viewport={height:400,scale:1,offsetTop:0,listeners:{},addEventListener(type,fn){this.listeners[type]=fn}};
  const window=boot(routesFor(state),null,w=>{
    w.matchMedia=query=>({matches:/pointer:coarse|max-width/.test(query),addEventListener(){},removeEventListener(){}});
    Object.defineProperty(w,'visualViewport',{value:viewport});
    Object.defineProperty(w.HTMLHtmlElement.prototype,'clientHeight',{get:()=>844});
  });
  try{
  await settle();await settle();
  const doc=window.document,height=()=>doc.documentElement.style.getPropertyValue('--app-h');
  doc.getElementById('msg').focus();viewport.listeners.resize();
  expect(height()).toBe('400px');  // A real keyboard: the field is focused.
  Object.defineProperty(doc,'hidden',{configurable:true,get:()=>true});doc.dispatchEvent(new window.Event('visibilitychange'));
  expect(doc.activeElement).not.toBe(doc.getElementById('msg'));
  Object.defineProperty(doc,'hidden',{configurable:true,get:()=>false});doc.dispatchEvent(new window.Event('visibilitychange'));
  await new Promise(resolve=>setTimeout(resolve,750));
  expect(height()).toBe('844px');  // iOS still reports 400 px, but no keyboard can be up.
  }finally{window.close()}
});

test('a connected computer with no sessions offers to start one there',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state);routes['/deck/'+DECK+'/api/sessions']=()=>({sessions:[]});
  const window=boot(routes);
  try{
  await settle();await settle();
  const start=window.document.querySelector('#tabs .deck-new');
  expect(start.getAttribute('aria-label')).toBe('Новая сессия на «Mac Studio»');
  start.click();await settle();
  expect(window.eval('selectedDeck')).toBe(DECK);
  expect(window.document.getElementById('dlg').open).toBe(true);
  }finally{window.close()}
});

test('a found computer that is already connected says so instead of offering to connect',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=settingsRoutes(state,{claude:{installed:true,logged_in:true}});
  routes['/api/decks']=()=>({decks:[{id:DECK,name:'Mac Studio',url:'http://100.64.0.2:8790',username:'demo'}],
    discovery:{phase:'done',results:[{name:'MacBook Pro',url:'http://100.64.0.2:8790'},{name:'RED',url:'http://100.64.0.9:8790'}]}});
  const window=boot(routes);
  try{
  await settle();await settle();
  await window.eval('openSettings("computers")');await settle();
  const rows=[...window.document.querySelectorAll('#deck_discovery_results .hub-row')];
  expect(rows[0].querySelector('.card-status').textContent).toBe('Подключено как «Mac Studio»');
  expect(rows[0].querySelector('button').getAttribute('aria-label')).toBe('Открыть: Mac Studio');
  expect(rows[1].querySelector('button').getAttribute('aria-label')).toBe('Подключить: RED');
  }finally{window.close()}
});

test('background refreshes never move an editor being typed in or overwrite unsaved fields',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=settingsRoutes(state,{claude:{installed:true,logged_in:true},kimi:{installed:true},kimi_config:{configured:false}});
  routes['/api/project_directory']=()=>({directory:'/home/demo/projects'});
  const window=boot(routes);
  try{
  await settle();await settle();
  const doc=window.document;
  await window.eval('openSettings("general")');await settle();
  const folder=doc.getElementById('project_directory');
  expect(folder.value).toBe('/home/demo/projects');
  folder.value='/home/demo/typed-but-not-saved';
  window.eval('openKimi()');await settle();
  expect(folder.value).toBe('/home/demo/typed-but-not-saved');  // Opening the Kimi editor did not reload the form.
  const key=doc.getElementById('kimi_key');key.focus();key.value='sk-half';
  window.eval('renderHub()');
  expect(doc.activeElement).toBe(key);
  expect(key.value).toBe('sk-half');
  }finally{window.close()}
});

test('a computer switch does not carry backups or a recovery code to the next computer',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=settingsRoutes(state,{claude:{installed:true,logged_in:true}});
  routes['/api/backups']=()=>({configured:true,key_id:'abcd1234',last:1,stored:[],report:null});
  routes['/deck/'+DECK+'/api/backups']=()=>({__status:404,error:'not found'});
  const window=boot(routes);
  try{
  await settle();await settle();
  const doc=window.document;
  await window.eval('openSettings("backups")');await settle();
  expect(doc.getElementById('backup_status').textContent).toBe('Включены');
  doc.getElementById('backup_code').textContent='AD1-SECRET';doc.getElementById('backup_code_card').hidden=false;
  window.openDeckSession(DECK,'beta');await settle();
  expect(window.eval('backupStatus')).toBeNull();
  expect(doc.getElementById('backup_status').textContent).toBe('');
  expect(doc.getElementById('backup_code').textContent).toBe('');
  expect(doc.getElementById('backup_code_card').hidden).toBe(true);
  }finally{window.close()}
});

test('desktop keeps the typing focus across a tab switch, and Option+K on a Mac still types',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const window=boot(routesFor(state),null,w=>Object.defineProperty(w.navigator,'platform',{value:'MacIntel'}));
  try{
  await settle();await settle();
  const doc=window.document,msg=doc.getElementById('msg');
  msg.focus();
  Object.defineProperty(doc,'hidden',{configurable:true,get:()=>true});doc.dispatchEvent(new window.Event('visibilitychange'));
  expect(doc.activeElement).toBe(msg);
  Object.defineProperty(doc,'hidden',{configurable:true,get:()=>false});
  const option=new window.KeyboardEvent('keydown',{code:'KeyK',key:'˚',altKey:true,bubbles:true,cancelable:true});
  msg.dispatchEvent(option);
  expect(option.defaultPrevented).toBe(false);
  expect(doc.getElementById('palette_dlg').open).toBe(false);
  }finally{window.close()}
});

test('a diff comment goes to the session whose history is open, and New session never lands on the wrong computer',async()=>{
  const state={local:()=>({sessions:[session('alpha'),session('beta')]})};
  const routes=routesFor(state);routes['/deck/'+DECK+'/api/sessions']=()=>({sessions:[]});
  const window=boot(routes);
  try{
  await settle();await settle();
  window.eval('hist.session="alpha";select("beta")');
  window.eval('appendToMessage("app.py:1 — fix")');
  expect(window.eval('messageDrafts.get("alpha")')).toBe('app.py:1 — fix');
  expect(window.document.getElementById('msg').value).toBe('');
  window.eval('sending=true');
  window.document.querySelector('#tabs .deck-new').click();await settle();
  expect(window.eval('selectedDeck')).toBe('');
  expect(window.document.getElementById('dlg').open).toBe(false);
  }finally{window.close()}
});

test('a folder that cannot be listed offers a retry instead of loading forever',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state);let fail=true;
  routes['/api/files']=url=>fail?{__status:400,error:'Папка не найдена'}:{path:url.searchParams.get('path')||'/home/demo/p',home:'/home/demo',parent:null,entries:[]};
  const window=boot(routes);
  try{
  await settle();await settle();
  await window.eval('openFiles()');await settle();
  const doc=window.document;
  expect(doc.querySelector('#files_body .diff-note').textContent).toBe('Папка не найдена');
  fail=false;[...doc.querySelectorAll('#files_body button')].find(b=>/Повторить|Retry/.test(b.textContent)).click();await settle();
  expect(doc.querySelector('.files-crumbs').textContent).toBe('~/p');
  // A crumb jumps straight to that folder.
  doc.querySelector('.files-crumbs button').click();await settle();
  expect(doc.querySelector('.files-crumbs .here').textContent).toBe('~');
  }finally{window.close()}
});

test('a pending question marks its session in the list and the digits answer it',async()=>{
  const state={local:()=>({sessions:[session('alpha'),session('beta')]})};
  const routes=routesFor(state),answers=[];
  routes['/api/question']=url=>url.searchParams.get('name')==='alpha'?{question:{id:'q1',title:'Deploy?',progress:'',selected:0,options:[{label:'Yes',text:false},{label:'No',text:false},{label:'Type something',text:true}]}}:{question:null};
  routes['/api/answer']=(url,options)=>{answers.push(JSON.parse(options.body));return {ok:true}};
  const window=boot(routes);
  try{
  await settle();await settle();
  window.eval('select("alpha");loadQuestion()');
  for(let i=0;i<20&&!window.document.querySelector('#question .q-opt');i++)await settle();
  window.eval('renderTabs()');
  const state=name=>window.document.querySelector(`#tabs [data-session="${name}"] .state`)?.className||'';
  expect(state('alpha')).toContain('ask');
  expect(state('beta')).not.toContain('ask');
  const press=code=>window.dispatchEvent(new window.KeyboardEvent('keydown',{code,key:code.slice(-1),bubbles:true}));
  press('Digit3');await settle();  // A free-text option is never answered blindly.
  expect(answers).toEqual([]);
  press('Digit2');await settle();
  expect(answers).toEqual([{name:'alpha',id:'q1',index:1}]);
  }finally{window.close()}
});

test('tapping a notification opens its session on cold start and when the app resumes',async()=>{
  const state={local:()=>({sessions:[session('alpha',{activity:9}),session('api')]})};
  const window=boot(routesFor(state),{deck:'',session:'api'});
  try{
  await settle();await settle();
  expect(window.document.querySelector('#title b').textContent).toBe('api');
  expect(window.notificationTargets.size).toBe(0);
  // Back from the background: a tap on another notification while the app was suspended.
  window.notificationTargets.set('/__agent-deck-open',JSON.stringify({deck:'',session:'alpha',at:Date.now()}));
  window.document.dispatchEvent(new window.Event('visibilitychange'));
  await settle();await settle();
  expect(window.document.querySelector('#title b').textContent).toBe('alpha');
  // A notification from another computer switches to it and opens that session.
  window.notificationTargets.set('/__agent-deck-open',JSON.stringify({deck:DECK,session:'beta',at:Date.now()}));
  window.dispatchEvent(new window.Event('focus'));
  await settle();await settle();
  expect(window.document.querySelector('#title b').textContent).toBe('beta');
  }finally{window.close()}
});

test('a notification that lands after the app became visible is still opened',async()=>{
  const state={local:()=>({sessions:[session('alpha',{activity:9}),session('api')]})};
  const window=boot(routesFor(state));
  try{
  await settle();await settle();
  expect(window.document.querySelector('#title b').textContent).toBe('alpha');
  window.document.dispatchEvent(new window.Event('visibilitychange'));
  await new Promise(resolve=>setTimeout(resolve,400));
  // The service worker stores the target only now, after the page has already checked once.
  window.notificationTargets.set('/__agent-deck-open',JSON.stringify({deck:'',session:'api',at:Date.now()}));
  await new Promise(resolve=>setTimeout(resolve,1000));
  expect(window.document.querySelector('#title b').textContent).toBe('api');
  // The worker's last resort navigates to /#session; the page follows the hash.
  window.location.hash='#alpha';
  await settle();await settle();
  expect(window.document.querySelector('#title b').textContent).toBe('alpha');
  }finally{window.close()}
});

test('a lost connection shows the status pill instead of errors and recovers on its own',async()=>{
  const state={local:()=>({__network:true})};
  const window=boot(routesFor(state));
  try{
  await settle();await settle();
  const pill=window.document.getElementById('conn');
  expect(pill.hidden).toBe(false);
  expect(pill.classList.contains('bad')).toBe(true);
  expect(window.document.getElementById('toast').classList.contains('on')).toBe(false);
  state.local=()=>({__html:true});   // A proxy page answering 200 with HTML must not crash the list.
  await window.load();await settle();
  expect(window.problems.filter(p=>!p.includes('window.focus'))).toEqual([]);
  expect(pill.classList.contains('bad')).toBe(true);
  state.local=()=>({sessions:[session('alpha')]});
  await window.load();await settle();
  expect(pill.textContent).toBe('Связь восстановлена');
  expect(window.document.querySelector('#title b').textContent).toBe('alpha');
  await new Promise(resolve=>setTimeout(resolve,1700));
  expect(pill.hidden).toBe(true);
  }finally{window.close()}
});
