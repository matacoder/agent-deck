/**
 * @jest-environment node
 *
 * Defects found by review: each test is the scenario that went wrong.
 */
const {DECK,boot,session,settle,routesFor}=require('./harness');

const open=async(extra={},setup)=>{
  const window=boot({...routesFor({local:()=>({sessions:[session('alpha'),session('bravo')]})}),...extra},null,setup);
  await settle();await settle();
  return window;
};

test('an unsaved file keeps the computer it was opened on',async()=>{
  const window=await open();
  try{
    window.eval('files.file={path:"/home/demo/a.md",content:"edited",saved:"as read"}');
    window.eval(`switchDeck("${DECK}")`);await settle();
    expect(window.eval('selectedDeck')).toBe('');
    expect(window.document.getElementById('deck_select').value).toBe('');
    window.eval('files.file.saved="edited"');
    window.eval(`switchDeck("${DECK}")`);await settle();
    expect(window.eval('selectedDeck')).toBe(DECK);
  }finally{window.close()}
});

test('signing out leaves nothing of what was shown, also when the page is left',async()=>{
  const window=await open({'/logout':()=>({})});
  try{
    window.eval('previewCache.set("alpha",{preview:"secret screen",preview_ansi:"secret screen"})');
    window.localStorage.setItem('cc.server',JSON.stringify({hostname:'box',ip:'203.0.113.7'}));
    await window.eval('logout()');
    window.dispatchEvent(new window.Event('pagehide'));
    const kept=[...Object.keys(window.localStorage),...Object.keys(window.sessionStorage)];
    expect(kept.filter(key=>key.includes('cc.shown.')||key.endsWith('cc.server'))).toEqual([]);
  }finally{window.close()}
});

test('a card with a typed answer is redrawn when it is no longer the question it shows',async()=>{
  const ask=(id,text)=>({question:{id,title:text,question:text,options:[{label:'Yes'},{label:'Other',text:true}]}});
  const window=await open({'/api/question':target=>target.searchParams.get('name')==='alpha'?ask('one','Alpha asks'):ask('two','Bravo asks')});
  try{
    window.eval('select("alpha")');await settle();await settle();
    const box=window.document.getElementById('question');
    expect(box.textContent).toContain('Alpha asks');
    window.eval('question.textIndex=1;renderQuestion()');
    const field=box.querySelector('.q-text textarea');
    field.focus();field.value='typed';
    // The same question refreshed: the field and what is typed in it stay.
    window.eval('renderQuestion()');
    expect(box.querySelector('.q-text textarea')).toBe(field);
    window.eval('select("bravo")');await settle();await settle();
    expect(box.textContent).toContain('Bravo asks');
    expect(box.textContent).not.toContain('Alpha asks');
  }finally{window.close()}
});

test('a file that failed to attach is reported after the others are done',async()=>{
  const window=await open();
  try{
    window.eval('select("alpha")');await settle();
    window.uploadFile=async(name,file,image,progress)=>{progress(100);return {attachment:{id:'1'},kind:'file'}};
    const big={name:'big.bin',type:'application/octet-stream',size:300*1024*1024},small={name:'a.txt',type:'text/plain',size:3};
    await window.eval('uploadImages')([big,small]);
    const state=window.document.getElementById('send_state');
    expect(state.classList.contains('error')).toBe(true);
    expect(state.classList.contains('pending')).toBe(false);
    // Typing again is the next attempt: the failure does not stand over it.
    const field=window.document.getElementById('msg');
    field.value='next';field.dispatchEvent(new window.Event('input'));
    expect(state.classList.contains('error')).toBe(false);
  }finally{window.close()}
});
