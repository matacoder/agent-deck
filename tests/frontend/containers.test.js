const {containerMeta,containerChoices}=require("../../frontend/containers.js");

const translate=(text,args=[])=>text.replace(/\{(\d+)\}/g,(_,n)=>args[n]);

test("a computer's row says what its Docker is or why it cannot be used",()=>{
  expect(containerMeta({state:"ok",docker:{version:"28.3.3",cpus:16,memory:64*2**30}},translate)).toBe("Docker 28.3.3 · ядер: 16 · память: 64 ГБ");
  expect(containerMeta({state:"ok",docker:null,can_start:true},translate)).toBe("Docker не запущен");
  expect(containerMeta({state:"ok",docker:null,host:true},translate)).toBe("Docker не запущен");
  expect(containerMeta({state:"ok",docker:null},translate)).toBe("Docker не найден");
  expect(containerMeta({state:"offline",docker:{version:"1",cpus:1,memory:1}},translate)).toBe("Не отвечает");
  expect(containerMeta({state:"old"},translate)).toBe("Нужна новая версия панели");
});

test("only marked computers can be chosen, and a choice that is gone means this computer",()=>{
  const machines=[{id:"a",name:"Red",host:true},{id:"b",name:"Air",host:false}];
  expect(containerChoices({machines,use:"a"})).toEqual({hosts:[machines[0]],selected:"a"});
  expect(containerChoices({machines,use:"b"}).selected).toBe("");
  expect(containerChoices({machines:[],use:"a"})).toEqual({hosts:[],selected:""});
});
