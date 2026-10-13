/**
 * @jest-environment node
 *
 * What the page showed last time is on screen before the first answer, and sign-out forgets it.
 */
const {DECK,boot,session,settle,routesFor}=require('./harness');
const {sessionsToKeep,decksToKeep,keepShown,shown,forgetShown,screenToKeep,knownAnswer,keepAnswer,terminalsToWarm}=require('../../frontend/remember');

function storage(){
  const data={};
  Object.defineProperties(data,{getItem:{value:k=>k in data?data[k]:null},setItem:{value:(k,v)=>{data[k]=String(v)}},removeItem:{value:k=>{delete data[k]}}});
  return data;
}

test('a kept list has no screen text and no clock values; kept computers have nothing that signs in',()=>{
  const kept=sessionsToKeep([{name:'a',agent:'codex',preview:'secret output',preview_ansi:'x',activity:5,attached:1}]);
  expect(kept).toEqual([{name:'a',agent:'codex'}]);
  expect(sessionsToKeep(null)).toEqual([]);
  const decks=decksToKeep({decks:[{id:DECK,name:'Mac',url:'http://100.64.0.2:8790',instance:'b'.repeat(24),username:'demo',password:'no',pair:{key:'no'}}]},{name:'gw',bind_port:8790});
  expect(decks.decks).toEqual([{id:DECK,name:'Mac',url:'http://100.64.0.2:8790',instance:'b'.repeat(24)}]);
  expect(JSON.stringify(decks)).not.toMatch(/demo|"no"/);
});

test('an unchanged value is written once; sign-out removes every kept view and nothing else',()=>{
  const store=storage();let writes=0;
  const counted={getItem:store.getItem,setItem:(k,v)=>{writes++;store.setItem(k,v)},removeItem:store.removeItem};
  keepShown(counted,'x','usage',{a:1});keepShown(counted,'x','usage',{a:1});keepShown(counted,'x','usage',{a:2});
  expect(writes).toBe(2);
  expect(shown(store,'usage')).toEqual({a:2});
  store.setItem('deck.'+DECK+'.cc.shown.sessions','[]');store.setItem('cc.active','alpha');
  forgetShown(store);
  expect(Object.keys(store)).toEqual(['cc.active']);
  store.setItem('cc.shown.usage','{broken');
  expect(shown(store,'usage')).toBeNull();
});

test('the remembered list, computers and limits are drawn before the first answer; a cold start shows placeholders',async()=>{
  const never=()=>new Promise(()=>{});
  const routes={...routesFor({local:never}),'/api/sessions':never,'/api/decks':never,'/api/network':never,'/api/usage':never,'/api/version':never,
    ['/deck/'+DECK+'/api/sessions']:never};
  const cold=boot(routes);
  try{
    await settle();
    expect(cold.document.querySelectorAll('#tabs .tab-skeleton').length).toBe(4);
    expect(cold.document.querySelector('.side-foot #server_metrics')).not.toBeNull();
    expect(cold.document.getElementById('deck_switch').hidden).toBe(true);
  }finally{cold.close()}
  const warm=boot(routes,null,window=>{
    const at=Date.now()/1000+3600;
    window.localStorage.setItem('cc.shown.sessions',JSON.stringify(sessionsToKeep([session('alpha'),session('bravo')])));
    window.localStorage.setItem('cc.shown.decks',JSON.stringify(decksToKeep({decks:[{id:DECK,name:'Mac Studio',url:'http://100.64.0.2:8790'}]},{name:'gateway',bind_port:8790})));
    window.localStorage.setItem('deck.'+DECK+'.cc.shown.sessions',JSON.stringify(sessionsToKeep([session('beta')])));
    window.localStorage.setItem('cc.shown.usage',JSON.stringify({codex:{windows:[{label:'Week',percent:40,resets_at:at,window_seconds:604800}]}}));
    window.localStorage.setItem('cc.shown.version',JSON.stringify({version:'1.2.3'}));
    window.localStorage.setItem('cc.active','bravo');
  });
  try{
    await settle();
    const doc=warm.document,names=[...doc.querySelectorAll('#tabs .tab .n')].map(n=>n.textContent);
    expect(names).toEqual(['alpha','bravo','beta']);
    expect(doc.querySelector('#tabs .tab.on .n').textContent).toBe('bravo');
    expect(doc.getElementById('deck_switch').hidden).toBe(false);
    expect([...doc.getElementById('deck_select').options].map(o=>o.textContent)).toEqual(['gateway','Mac Studio']);
    expect(doc.querySelector('#send_state .quota-percent').textContent).toBe('60%');
    expect(doc.getElementById('ver').textContent).toBe('v1.2.3');
    expect(doc.getElementById('empty').style.display).toBe('none');
    await settle();await settle();
  }finally{warm.close()}
});

test('a kept screen is the end of its text; known answers are per key and the oldest goes first',()=>{
  const long=Array.from({length:5000},(_,i)=>'line '+i+' '+'x'.repeat(40)).join('\n');
  const kept=screenToKeep({preview:'plain',preview_ansi:long,model:'m'});
  expect(kept.preview_ansi.length).toBeLessThanOrEqual(60000);
  expect(kept.preview_ansi.startsWith('line ')).toBe(true);
  expect(kept.preview_ansi.endsWith(long.slice(-50))).toBe(true);
  expect(kept).not.toHaveProperty('preview');
  expect(screenToKeep({preview:'short'})).toEqual({preview_ansi:'short',model:undefined});
  const known=new Map();
  for(let i=0;i<70;i++)keepAnswer(known,'d/s'+i,{i});
  expect(known.size).toBe(60);
  expect(knownAnswer(known,'d/s0')).toBeNull();
  expect(knownAnswer(known,'d/s69')).toEqual({i:69});
  keepAnswer(known,'d/s69',null);
  expect(knownAnswer(known,'d/s69')).toBeNull();
  expect(knownAnswer(known,null)).toBeNull();
});

test('a session opened before shows its summary and screen at once on a switch back',async()=>{
  let hold=false,holdInfo=false;const never=()=>new Promise(()=>{});
  const list=target=>{const name=target.searchParams.get('preview');
    return {sessions:[session('alpha'),session('bravo')].map(s=>s.name===name?{...s,preview:'screen of '+name,preview_ansi:'screen of '+name}:s)}};
  const routes={...routesFor({local:()=>({sessions:[]})}),'/api/sessions':target=>hold?never():list(target),
    '/api/session_info':target=>holdInfo?never():({supported:true,context:{tokens:1000,limit:200000},summary:{line:'about '+target.searchParams.get('name')}})};
  const window=boot(routes,null,w=>{w.localStorage.setItem('cc.active','alpha');w.localStorage.setItem('cc.mode.d','screen')});
  try{
    await settle();await settle();await settle();
    const doc=window.document;
    // The other session's screen was fetched quietly, before it was ever opened.
    hold=true;
    window.eval('select("bravo")');
    expect(doc.getElementById('pre').textContent).toContain('screen of bravo');
    expect(doc.querySelector('#pre .screen-skeleton')).toBeNull();
    hold=false;await settle();await settle();
    expect(doc.getElementById('session_hint').hidden).toBe(false);
    expect(doc.getElementById('session_hint').textContent).toContain('about bravo');
    hold=holdInfo=true;
    window.eval('select("alpha")');
    expect(doc.getElementById('pre').textContent).toContain('screen of alpha');
    expect(doc.getElementById('session_hint').hidden).toBe(false);
    expect(doc.getElementById('session_hint').textContent).toContain('about alpha');
    await settle();await settle();
  }catch(e){await settle();await settle();throw e}finally{window.close()}
});

test('terminals opened ahead: the most recent running agents, never the open one, a shell or more than the limit',()=>{
  const list=[{name:'open',running:true,activity:9},{name:'old',running:true,activity:1},{name:'new',running:true,activity:8},
    {name:'stopped',running:false,activity:7},{name:'sh',running:true,agent:'shell',activity:6},{name:'seen',running:true,activity:5}];
  expect(terminalsToWarm(list,'open',['open','seen'],5)).toEqual(['new','old']);
  expect(terminalsToWarm(list,'open',['open','seen'],2)).toEqual(['new']);
  expect(terminalsToWarm(list,'open',['open','a','b','c','d','e'],5)).toEqual([]);
});
