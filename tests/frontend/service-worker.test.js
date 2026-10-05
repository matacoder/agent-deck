/** @jest-environment node */
// Runs the real service worker source (served at /sw.js) with fake browser globals.
const fs=require('fs');
const path=require('path');
const vm=require('vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../integrations/webpush.py'),'utf8').match(/SERVICE_WORKER = r"""([\s\S]*?)"""/)[1];

function worker({consumes}){
  const handlers={},store=new Map(),calls=[];
  const cache={put:async(k,r)=>store.set(k,await r.text()),match:async k=>store.has(k)?{}:undefined,delete:async k=>store.delete(k)};
  const client={url:'https://deck.test/#old',postMessage:m=>{calls.push(['message',m]);if(consumes)store.clear()},focus:async()=>calls.push(['focus']),navigate:async u=>calls.push(['navigate',u])};
  const self={addEventListener:(type,fn)=>{handlers[type]=fn},location:{origin:'https://deck.test'},registration:{},
    clients:{matchAll:async()=>[client],openWindow:async u=>calls.push(['open',u]),claim:async()=>{}},skipWaiting(){}};
  vm.runInNewContext(source,{self,caches:{open:async()=>cache},Response:class{constructor(b){this.b=b}text(){return Promise.resolve(this.b)}},URL,setTimeout,JSON,Promise,Date});
  return {handlers,store,calls};
}
async function tap(w){
  let done;w.handlers.notificationclick({notification:{close(){},data:{url:'/?deck=abc#api',deck:'abc',session:'api'}},waitUntil:p=>{done=p}});
  await done;
}

test('a page that takes the target is only focused',async()=>{
  const w=worker({consumes:true});
  await tap(w);
  expect(w.calls.map(c=>c[0])).toEqual(['message','focus']);
},10000);

test('a resumed page that missed the target is navigated to the session',async()=>{
  const w=worker({consumes:false});
  await tap(w);
  expect(w.calls).toEqual([['message',{type:'agent-deck-open'}],['focus'],['navigate','/?deck=abc#api']]);
  expect(w.store.size).toBe(0);
},10000);
