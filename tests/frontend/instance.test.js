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

function boot(routes,opened){
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
  expect(doc.querySelector('.files-path code').textContent).toBe('~/projects/alpha');
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
  const window=boot(routes);
  try{
  await settle();await settle();
  window.eval('openHistory()');await settle();
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

test('a folder that cannot be listed offers a retry instead of loading forever',async()=>{
  const state={local:()=>({sessions:[session('alpha')]})};
  const routes=routesFor(state);let fail=true;
  routes['/api/files']=()=>fail?{__status:400,error:'Папка не найдена'}:{path:'/home/demo/p',home:'/home/demo',parent:null,entries:[]};
  const window=boot(routes);
  try{
  await settle();await settle();
  await window.eval('openFiles()');await settle();
  const doc=window.document;
  expect(doc.querySelector('#files_body .diff-note').textContent).toBe('Папка не найдена');
  fail=false;[...doc.querySelectorAll('#files_body button')].find(b=>/Повторить|Retry/.test(b.textContent)).click();await settle();
  expect(doc.querySelector('.files-path code').textContent).toBe('~/p');
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
