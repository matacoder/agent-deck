// The ordinary local network next to Tailscale: which computers also answer there, and by which of its
// addresses a connected computer is reached now. Bundled before app.js.
let lanData=null,lanSeq=0;

function isLanHost(host){
  const p=String(host).split(".").map(Number);
  return p.length===4&&(p[0]===10||(p[0]===192&&p[1]===168)||(p[0]===172&&p[1]>=16&&p[1]<=31));
}
function hostPort(url){try{const u=new URL(url);return u.hostname+":"+(u.port||"80")}catch(e){return String(url)}}
// Every address of a connected or found computer on one line; says so when the local one is in use. Pure for tests.
function deckAddresses(deck,translate){
  // A connected computer lists all its addresses; a found one has the first apart from the rest.
  const urls=[...new Set(deck.route?deck.urls||[deck.url]:[deck.url,...(deck.urls||[])])];
  const text=urls.map(hostPort).join(" · ");
  let host="";try{host=new URL(deck.route||"").hostname}catch(e){}
  return urls.length>1&&isLanHost(host)?text+" — "+translate("сейчас через локальную сеть"):text;
}
// What a row says under a computer's name. Pure for tests.
function lanMeta(machine,translate){
  if(machine.state==="offline")return translate("Не отвечает");
  if(machine.state==="old")return translate("Нужна новая версия панели");
  if(machine.lan_address)return "http://"+machine.lan_address+":"+machine.port;
  // A server with a public address, or a panel that already listens on every address of its container.
  if(!machine.lan_found)return translate("Локальная сеть не найдена");
  return machine.lan?translate("Адрес открывается…"):translate("Выключено · {0}",[machine.lan_found]);
}
async function loadLan(){
  const seq=++lanSeq,decks=deckDirectory.decks;
  const ask=async(path,gateway)=>{
    try{const data=await api(path,null,gateway);return typeof data.lan==="boolean"?{state:"ok",...data}:{state:"old"}}
    catch(e){return {state:e.offline?"offline":"old"}}
  };
  const [own,...others]=await Promise.all([ask("/api/lan",true),...decks.map(d=>ask(instancePath(d.id,"/api/lan"),true))]);
  if(seq!==lanSeq)return;
  lanData={own,machines:decks.map((d,i)=>({id:d.id,name:d.name,...others[i]}))};
  renderLan();
}
function lanRow(name,machine,save){
  const input=el("input");
  input.type="checkbox";input.setAttribute("role","switch");input.checked=machine.lan===true;
  input.disabled=machine.state!=="ok"||machine.fixed===true||(!machine.lan_found&&!machine.lan);
  input.setAttribute("aria-label",tr("Отвечать в локальной сети")+": "+name);
  input.onchange=()=>saveLan(input,name,save);
  return el("label","integration-toggle container-machine",el("span","",el("strong","",name),el("span","card-meta",lanMeta(machine,tr))),input);
}
function renderLan(){
  if(!lanData)return;
  const rows=[lanRow(deckDirectory.name,lanData.own,enabled=>gatewayApi("/api/lan_save",{enabled}))];
  for(const m of lanData.machines)rows.push(lanRow(m.name,m,enabled=>api(instancePath(m.id,"/api/lan_save"),{enabled},true)));
  $("lan_machines").replaceChildren(...rows);
}
async function saveLan(input,name,save){
  const enabled=input.checked;
  // Plain HTTP on a network other people may share: the owner decides for each computer.
  if(enabled&&!await confirmAction(tr("Открыть «{0}» в локальной сети?",[name]),{text:tr("Пароль панели и содержимое сессий пойдут по этой сети без шифрования. Включайте только в сети, которой доверяете."),confirm:tr("Открыть")})){input.checked=false;return}
  input.disabled=true;
  try{await save(enabled)}catch(e){input.checked=!enabled;if(e.message!==STALE)toast(e.message)}
  await loadLan();
}

if(typeof module!=="undefined")module.exports={isLanHost,deckAddresses,lanMeta};
