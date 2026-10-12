/**
 * @jest-environment node
 *
 * A page that cannot reload itself says that it is old; the bottom line survives one odd answer; sent
 * pictures leave with the text.
 */
const {boot,session,settle,routesFor}=require('./harness');

test('an outdated page in use offers a reload instead of staying old silently',async()=>{
  const routes={...routesFor({local:()=>({sessions:[session('alpha')]})}),'/api/ui-version':()=>({revision:'newer'})};
  const window=boot(routes,null,w=>{w.localStorage.setItem('cc.mode.d','term');w.localStorage.setItem('cc.active','alpha')});
  try{
    await settle();await settle();
    const button=window.document.getElementById('b_stale');
    // A terminal is open: the page is never reloaded under it.
    window.eval('checkInterfaceVersion()');await settle();await settle();
    expect(button.hidden).toBe(false);
    expect(button.textContent).toBe('Обновить страницу');
  }finally{window.close()}
});

test('the line under the field stays through one answer without a conversation and goes after two',async()=>{
  let supported=true;
  const routes={...routesFor({local:()=>({sessions:[session('alpha')]})}),
    '/api/session_info':()=>supported?{supported:true,context:{tokens:1000},summary:null}:{supported:false}};
  const window=boot(routes,null,w=>{w.localStorage.setItem('cc.active','alpha');w.localStorage.setItem('cc.mode.d','screen')});
  try{
    await settle();await settle();await settle();
    const meta=window.document.getElementById('session_meta');
    expect(meta.hidden).toBe(false);
    supported=false;
    window.eval('loadSessionInfo()');await settle();await settle();
    expect(meta.hidden).toBe(false);
    window.eval('loadSessionInfo()');await settle();await settle();
    expect(meta.hidden).toBe(true);
    window.eval('clearTimeout(sessionInfo.timer)');
  }finally{window.close()}
});

test('a sent picture leaves the field at once, before the session list comes back',async()=>{
  let hold=false;const never=()=>new Promise(()=>{});
  const routes={...routesFor({local:()=>({sessions:[session('alpha')]})}),'/api/sessions':()=>hold?never():({sessions:[session('alpha')]}),'/api/send':()=>({ok:true})};
  const window=boot(routes,null,w=>{w.localStorage.setItem('cc.active','alpha');w.localStorage.setItem('cc.mode.d','screen')});
  try{
    await settle();await settle();
    const doc=window.document;
    window.eval('imageAttachments.set("alpha",[{attachment:"a1.png",label:"shot.png",kind:"image"}]);renderAttachments()');
    expect(doc.getElementById('attachments').textContent).toContain('shot.png');
    doc.getElementById('msg').value='look';
    hold=true;
    window.eval('send()');await settle();await settle();
    expect(doc.getElementById('msg').value).toBe('');
    expect(doc.getElementById('attachments').textContent).not.toContain('shot.png');
  }finally{window.close()}
});
