// The real bundled panel (panel/index.html) in jsdom with a fake network, shared by the suites that
// drive whole flows instead of single functions.
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
      if(body&&body.__blob)return {ok:true,status:200,headers:{get:()=>null},blob:async()=>new window.Blob([body.__blob])};
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

module.exports={DECK,boot,session,settle,routesFor};
