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

function boot(routes){
  // jsdom cannot replace location.reload; a reload shows up as a "navigation" not-implemented error.
  const console=new VirtualConsole(),problems=[];
  console.on('jsdomError',error=>problems.push(String(error.message)));
  const dom=new JSDOM(page,{url:'https://panel.test/',runScripts:'dangerously',pretendToBeVisual:true,virtualConsole:console,beforeParse(window){
    window.focus=()=>{};
    window.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}});
    window.ResizeObserver=class{observe(){}};
    window.HTMLDialogElement.prototype.showModal=function(){this.open=true};
    window.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new window.Event('close'))};
    window.HTMLElement.prototype.scrollIntoView=()=>{};
    window.fetch=async(url)=>{
      const target=new URL(url,'https://panel.test/');
      const handler=routes[target.pathname];
      const body=handler?await handler(target):{};
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
