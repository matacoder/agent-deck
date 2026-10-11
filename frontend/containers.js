// Containers on another computer: which computers lend their Docker and which one this computer's
// sessions use. Always asked from the gateway: it is the one that reaches the others.
let containers=null,containersTimer=null;

// What a row says under a computer's name. Pure for tests.
function containerMeta(machine,translate){
  if(machine.state==="offline")return translate("Не отвечает");
  if(machine.state==="old")return translate("Нужна новая версия панели");
  const d=machine.docker;
  if(!d)return translate(machine.can_start||machine.host?"Docker не запущен":"Docker не найден");
  return translate("Docker {0} · ядер: {1} · память: {2} ГБ",[d.version,d.cpus,Math.round(d.memory/2**30)]);
}
// Computers a session's containers can go to: marked ones only; a saved choice that is gone means "here". Pure for tests.
function containerChoices(data){
  const hosts=data.machines.filter(m=>m.host);
  return {hosts,selected:hosts.some(m=>m.id===data.use)?data.use:""};
}
function containerRow(name,meta,checked,disabled,save){
  const input=el("input");
  input.type="checkbox";input.setAttribute("role","switch");input.checked=checked;input.disabled=disabled;
  input.setAttribute("aria-label",tr("Запускать контейнеры здесь")+": "+name);
  input.onchange=()=>saveContainerHost(input,save);
  return el("label","integration-toggle container-machine",el("span","",el("strong","",name),el("span","card-meta",meta)),input);
}
function renderContainers(){
  const data=containers,card=$("containers_card");
  // One computer has nobody to lend Docker to.
  card.hidden=!data||!data.machines.length;
  if(card.hidden)return;
  const rows=[containerRow(deckDirectory.name,containerMeta({state:"ok",...data},tr),data.host,!data.docker&&!data.can_start&&!data.host,
    host=>gatewayApi("/api/containers_save",{host}))];
  for(const m of data.machines)rows.push(containerRow(m.name,containerMeta(m,tr),m.host,m.state!=="ok"||(!m.docker&&!m.can_start&&!m.host),
    host=>api(instancePath(m.id,"/api/containers_save"),{host},true)));
  $("container_machines").replaceChildren(...rows);
  const {hosts,selected}=containerChoices(data),select=$("containers_use");
  const option=(value,label)=>{const o=el("option","",label);o.value=value;return o};
  select.replaceChildren(option("",tr("На этом компьютере")),...hosts.map(m=>option(m.id,m.name)));
  select.value=selected;select.disabled=!hosts.length;
}
async function loadContainers(){
  // The other computers are asked again: a switch flipped on one of them shows at once.
  let data=null;
  try{data=await gatewayApi("/api/containers?fresh=1")}catch(e){if(e.message===STALE)return}
  containers=data&&Array.isArray(data.machines)?data:null;
  // A computer just switched on is still opening its Docker: look again until it shows.
  clearTimeout(containersTimer);
  const starting=containers&&[containers,...containers.machines].some(m=>m.host&&!m.docker&&m.state!=="offline");
  if(starting&&$("settings_dlg").open&&!document.hidden)containersTimer=setTimeout(loadContainers,8000);
  renderContainers();
}
async function saveContainerHost(input,save){
  input.disabled=true;
  try{await save(input.checked);toast(tr("Настройки сохранены"),"success")}catch(e){input.checked=!input.checked;if(e.message!==STALE)toast(e.message)}
  await loadContainers();
}
async function saveContainersUse(){
  const select=$("containers_use");select.disabled=true;
  try{containers=(await gatewayApi("/api/containers_save",{use:select.value})).containers;toast(tr("Настройки сохранены"),"success")}
  catch(e){if(e.message!==STALE)toast(e.message)}
  renderContainers();
}

if(typeof module!=="undefined")module.exports={containerMeta,containerChoices};
