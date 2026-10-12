const {hereCandidates,hereName}=require('../../frontend/here');

test('the gateway and every connected computer with a known id may be this machine',()=>{
  const id=n=>String(n).repeat(24);
  expect(hereCandidates({instance:id(1),bind_port:8790},[{id:'a',instance:id(2),url:'http://100.64.0.2:8791'},{id:'b',instance:'',url:'http://100.64.0.3:8790'},{id:'c',instance:id(3),url:'not a url'}]))
    .toEqual([{id:'',instance:id(1),port:'8790'},{id:'a',instance:id(2),port:'8791'}]);
  expect(hereCandidates(undefined,undefined)).toEqual([]);
  // An id from a list is never trusted as part of an address.
  expect(hereCandidates({instance:'x/../y',bind_port:8790},[])).toEqual([]);
});

test('only the computer the browser runs on is named so',()=>{
  const tr=text=>text;
  expect(hereName('Mac Studio','a','a',tr)).toBe('Mac Studio · этот компьютер');
  expect(hereName('gateway','','',tr)).toBe('gateway · этот компьютер');
  expect(hereName('Mac Studio','a','',tr)).toBe('Mac Studio');
  expect(hereName('gateway','',null,tr)).toBe('gateway');
  expect(hereName('gateway','',undefined,tr)).toBe('gateway');
});
