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

test('the conversation dialog shows what was said, from the agent\'s file, and again at once the next time',async()=>{
  let hold=false;const never=()=>new Promise(()=>{});
  const routes={...routesFor({local:()=>({sessions:[session('alpha')]})}),
    '/api/conversation':()=>hold?never():({supported:true,turns:[{role:'user',text:'Which option?'},{role:'assistant',text:'## Options\n\n| A | B |\n|---|---|\n| one | two |'}]})};
  const window=boot(routes,null,w=>{w.localStorage.setItem('cc.active','alpha');w.localStorage.setItem('cc.mode.d','screen')});
  try{
    await settle();await settle();
    const doc=window.document,list=doc.getElementById('talk_list');
    window.eval('openConversation()');
    expect(list.querySelector('.list-skeleton')).not.toBeNull();
    await settle();await settle();
    expect([...list.querySelectorAll('.talk-who')].map(n=>n.textContent)).toEqual(['Вы','Агент']);
    expect(list.querySelector('.talk-turn.mine .talk-text').textContent).toBe('Which option?');
    // The agent's Markdown is drawn, not shown as pipes and hashes.
    expect(list.querySelector('.talk-md h2').textContent).toBe('Options');
    expect([...list.querySelectorAll('.talk-md td')].map(n=>n.textContent)).toEqual(['one','two']);
    doc.getElementById('talk_dlg').close();hold=true;
    window.eval('openConversation()');
    expect(list.querySelectorAll('.talk-turn').length).toBe(2);
  }finally{window.close()}
});

test('the session search opens from its button and takes its filter away when closed',async()=>{
  const routes=routesFor({local:()=>({sessions:[session('alpha'),session('beta')]})});
  const window=boot(routes,null,w=>w.localStorage.setItem('cc.active','alpha'));
  try{
    await settle();await settle();
    const document=window.document,row=document.getElementById('side_find'),field=document.getElementById('q'),button=document.getElementById('b_find');
    const shown=()=>['alpha','beta'].filter(name=>document.querySelector('#tabs [data-session="'+name+'"]'));
    expect(row.hidden).toBe(true);
    button.click();
    expect(row.hidden).toBe(false);
    expect(button.getAttribute('aria-expanded')).toBe('true');
    field.value='beta';field.dispatchEvent(new window.Event('input'));
    expect(shown()).toEqual(['beta']);
    // A hidden field must not keep hiding sessions.
    field.dispatchEvent(new window.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    expect(row.hidden).toBe(true);
    expect(field.value).toBe('');
    expect(shown()).toEqual(['alpha','beta']);
  }finally{window.close()}
});

test('a computer that does not answer is marked, so a phone can leave it out of the list',async()=>{
  const window=boot(routesFor({local:()=>({sessions:[session('alpha')]})}));
  try{
    await settle();await settle();
    window.eval('window.heads=[deckHeader({id:"b".repeat(24),name:"RED",error:true},false),deckHeader({id:"c".repeat(24),name:"Mac",count:2},false)]');
    expect(window.heads[0].classList.contains('off')).toBe(true);
    expect(window.heads[1].querySelector('.deck-head').classList.contains('off')).toBe(false);
    // The sidebar no longer has a help button: the one in the session bar is the only one.
    expect(window.document.querySelector('aside .help-side')).toBeNull();
  }finally{window.close()}
});
