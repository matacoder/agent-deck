/**
 * @jest-environment node
 *
 * Send later and quick messages against the real bundled panel.
 */
const {boot,session,settle,routesFor}=require('./harness');

function laterRoutes(state,posts){
  const waiting=name=>({prompts:state.prompts[name]||[],auto_resume:false,limit:null,error:''});
  return {...routesFor(state),
    '/api/schedule':target=>state.broken?{__status:500,error:'boom'}:waiting(target.searchParams.get('name')),
    '/api/schedule_add':(target,options)=>{const body=JSON.parse(options.body);posts.push(body);
      (state.prompts[body.name]=state.prompts[body.name]||[]).push({id:'n',text:body.text,trigger:body.trigger,at:0,created:2});return waiting(body.name)},
    '/api/quick_prompts':(target,options)=>{
      if(options.method==='POST'){posts.push(JSON.parse(options.body));return {prompts:JSON.parse(options.body).prompts}}
      return state.quickDown?{__status:500,error:'boom'}:{prompts:state.quick};
    }};
}

test('send later lives in the menu, shows by the field only while something waits, and stays with its session',async()=>{
  const state={local:()=>({sessions:[session('alpha'),session('bravo')]}),prompts:{bravo:[{id:'1',text:'x',trigger:'idle',at:0,created:1}]}},posts=[];
  const window=boot(laterRoutes(state,posts));
  try{
  await settle();await settle();
  const doc=window.document,toast=()=>doc.getElementById('toast').textContent;
  window.eval(`select("alpha")`);await settle();await settle();
  expect(doc.getElementById('b_later').hidden).toBe(true);
  expect(doc.getElementById('s_later_label').textContent).toBe('Отправить позже');
  window.eval('openLater()');await settle();
  expect(doc.getElementById('later_title').textContent).toBe('Отправить позже · alpha');
  doc.getElementById('later_text').value='deploy to production';
  // A shortcut does not move another session under an open dialog.
  doc.dispatchEvent(new window.KeyboardEvent('keydown',{code:'Digit2',key:'2',altKey:true,bubbles:true}));await settle();
  expect(window.eval('active')).toBe('alpha');
  // A tapped notification still can: the first press then only says so and names the new session.
  window.eval(`select("bravo")`);await settle();await settle();
  await window.eval('saveLater()');
  expect(posts).toEqual([]);
  expect(toast()).toContain('Открыта другая сессия');
  expect(doc.getElementById('later_title').textContent).toBe('Отправить позже · bravo');
  await window.eval('saveLater()');
  expect(posts).toEqual([{name:'bravo',text:'deploy to production',trigger:'idle'}]);
  // Something waits in bravo: the button is by the field with its count, and the menu says the same.
  expect(doc.getElementById('b_later').hidden).toBe(false);
  expect(doc.getElementById('s_later_label').textContent).toBe('Отправить позже · ждут: 2');
  }finally{window.close()}
});

test('a failed read of held messages is not reported as an old panel',async()=>{
  const state={local:()=>({sessions:[session('alpha')]}),prompts:{},broken:true};
  const window=boot(laterRoutes(state,[]));
  try{
  await settle();await settle();
  window.eval(`select("alpha")`);await settle();await settle();
  window.eval('openLater()');await settle();
  expect(window.document.getElementById('later_dlg').open).toBeFalsy();
  expect(window.document.getElementById('toast').textContent).toContain('Не удалось прочитать отложенные сообщения');
  }finally{window.close()}
});

test('the quick message editor reads the list first and never saves over one it could not read',async()=>{
  const state={local:()=>({sessions:[session('alpha')]}),prompts:{},quick:[{label:'Tests',text:'run the tests'}],quickDown:true},posts=[];
  const window=boot(laterRoutes(state,posts));
  try{
  await settle();await settle();
  const doc=window.document;
  await window.eval('openQuickEditor()');
  expect(doc.getElementById('quick_dlg').open).toBeFalsy();
  expect(doc.getElementById('toast').textContent).toContain('Не удалось прочитать быстрые сообщения');
  state.quickDown=false;state.quick=[{label:'Tests',text:'run the tests'},{label:'Ship',text:'commit and push'}];  // Changed on another device.
  await window.eval('openQuickEditor()');
  expect(doc.getElementById('quick_rows').children.length).toBe(2);
  await window.eval('saveQuickPrompts()');
  expect(posts).toEqual([{prompts:state.quick}]);
  }finally{window.close()}
});
