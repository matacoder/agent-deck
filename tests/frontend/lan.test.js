const {isLanHost,deckAddresses,lanMeta}=require("../../frontend/lan.js");
const t=(text,args=[])=>text.replace(/\{(\d)\}/g,(_,i)=>args[i]);

test("only private IPv4 addresses count as the local network",()=>{
  for(const host of ["192.168.1.5","10.0.0.7","172.16.0.1","172.31.255.1"])expect(isLanHost(host)).toBe(true);
  for(const host of ["100.68.39.62","172.32.0.1","8.8.8.8","127.0.0.1","example.com",""])expect(isLanHost(host)).toBe(false);
});

test("a computer shows every address once and says when the local one is in use",()=>{
  const tail="http://100.68.39.62:8790",local="http://192.168.1.20:8790";
  expect(deckAddresses({url:tail},t)).toBe("100.68.39.62:8790");  // A gateway before this version sends one address.
  expect(deckAddresses({url:tail,urls:[tail,local],route:tail},t)).toBe("100.68.39.62:8790 · 192.168.1.20:8790");
  expect(deckAddresses({url:tail,urls:[tail,local],route:local},t)).toBe("100.68.39.62:8790 · 192.168.1.20:8790 — сейчас через локальную сеть");
  expect(deckAddresses({url:local,urls:[local],route:local},t)).toBe("192.168.1.20:8790");  // Its only address: nothing to remark.
  // A found computer: the first address apart from the rest.
  expect(deckAddresses({url:tail,urls:[local]},t)).toBe("100.68.39.62:8790 · 192.168.1.20:8790");
});

test("the row tells an open address from a switch that is off and a machine without a local network",()=>{
  expect(lanMeta({state:"offline"},t)).toBe("Не отвечает");
  expect(lanMeta({state:"old"},t)).toBe("Нужна новая версия панели");
  expect(lanMeta({state:"ok",lan:true,lan_address:"192.168.1.5",lan_found:"192.168.1.5",port:8790},t)).toBe("http://192.168.1.5:8790");
  expect(lanMeta({state:"ok",lan:false,lan_address:null,lan_found:"192.168.1.5",port:8790},t)).toBe("Выключено · 192.168.1.5");
  expect(lanMeta({state:"ok",lan:true,lan_address:null,lan_found:"192.168.1.5",port:8790},t)).toBe("Адрес открывается…");
  expect(lanMeta({state:"ok",lan:false,lan_address:null,lan_found:null,port:8790},t)).toBe("Локальная сеть не найдена");
});
