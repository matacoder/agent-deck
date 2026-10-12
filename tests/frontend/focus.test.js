/**
 * @jest-environment node
 *
 * A terminal that finishes connecting must not take the keyboard from a field of the page.
 */
const {boot,session,settle,routesFor}=require('./harness');

test('the terminal takes focus only while nothing is typed on the page',async()=>{
  const window=boot(routesFor({local:()=>({sessions:[session('alpha')]})}));
  try{
  await settle();await settle();
  const doc=window.document,calls=[],frame={};
  window.frame=frame;window.calls=calls;
  window.eval('keepPageFocus(frame)');
  // ttyd creates its terminal after the frame has loaded and focuses it when the connection opens.
  frame.term={focus(){calls.push('term')}};
  doc.getElementById('msg').focus();
  frame.term.focus();
  expect(calls).toEqual([]);
  expect(doc.activeElement.id).toBe('msg');
  doc.getElementById('msg').blur();
  frame.term.focus();
  expect(calls).toEqual(['term']);
  // A terminal that already exists is wrapped once, however often the frame reloads.
  const ready={term:{focus(){calls.push('ready')}}};
  window.ready=ready;window.eval('keepPageFocus(ready);keepPageFocus(ready)');
  doc.getElementById('q').focus();ready.term.focus();
  expect(calls).toEqual(['term']);
  doc.getElementById('q').blur();ready.term.focus();
  expect(calls).toEqual(['term','ready']);
  }finally{window.close()}
});
