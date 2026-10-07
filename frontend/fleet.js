// Versions of every connected computer and "update all" from the gateway.
const fleet={versions:new Map(),gateway:null,updating:false,loadedAt:0};
const UPDATING=new Set(["checking","downloading","installing","restarting"]);

// Which computers can be updated now; pure for tests.
function fleetTargets(versions){
  const ids=[];
  for(const [id,v] of versions)if(v&&v.update&&v.can_update!==false&&!UPDATING.has(v.job?.phase))ids.push(id);
  return ids;
}
function versionLabel(v,translate){
  if(!v)return translate("недоступен");
  if(UPDATING.has(v.job?.phase))return "v"+v.version+" · "+(v.job.message||translate("обновляется…"));
  if(v.job?.phase==="error")return "v"+v.version+" · "+translate("обновление не удалось");
  return v.update&&v.latest?"v"+v.version+" → v"+v.latest:"v"+v.version;
}

async function loadFleet(fresh=false){
  fleet.loadedAt=Date.now();
  const decks=deckDirectory.decks;
  // Opening Network asks every computer to check GitHub again, so "Update all" appears right after a release.
  const path="/api/version"+(fresh?"?fresh=1":"");
  const results=await Promise.all(decks.map(async d=>{try{return [d.id,await api(instancePath(d.id,path),null,true)]}catch(e){return [d.id,null]}}));
  fleet.versions=new Map(results);
  try{fleet.gateway=await api("/api/version",null,true)}catch(e){fleet.gateway=null}
  renderFleet();renderTabs();
}
function renderFleet(){
  const bar=document.getElementById("fleet_bar");if(!bar)return;
  for(const node of document.querySelectorAll("[data-deck-version]")){
    const v=fleet.versions.get(node.dataset.deckVersion);
    node.textContent=versionLabel(v,tr);node.classList.toggle("outdated",Boolean(v?.update));
    if(node.classList.contains("card-status"))node.className="card-status "+(!v?"bad":v.update||UPDATING.has(v.job?.phase)?"warn":"ok");
  }
  const targets=fleetTargets(fleet.versions),gatewayOld=Boolean(fleet.gateway?.update&&fleet.gateway?.can_update);
  const count=targets.length+(gatewayOld?1:0);
  bar.replaceChildren();
  if(!deckDirectory.decks.length)return;
  bar.append(el("span","",fleet.updating?tr("Обновляю компьютеры…"):count?tr("Обновления доступны: {0}",[count]):tr("Все компьютеры обновлены")));
  if(count&&!fleet.updating)bar.append(btn(tr("Обновить все"),"pri",updateAllComputers));
  if(typeof updateHubDots==="function"&&$("settings_dlg").open)updateHubDots();
}
async function updateAllComputers(){
  const targets=fleetTargets(fleet.versions),gatewayOld=Boolean(fleet.gateway?.update&&fleet.gateway?.can_update);
  if(!targets.length&&!gatewayOld)return;
  if(!await confirmAction(tr("Обновить все компьютеры?"),{text:tr("Панели перезапустятся по очереди, сессии и агенты продолжат работать. Этот компьютер обновится последним."),confirm:tr("Обновить все")}))return;
  fleet.updating=true;renderFleet();
  await Promise.all(targets.map(id=>api(instancePath(id,"/api/update"),{},true).catch(e=>toast(e.message))));
  // Poll until every started job ends; the gateway goes last because its restart interrupts the proxy.
  const deadline=Date.now()+10*60*1000;
  while(Date.now()<deadline){
    await new Promise(resolve=>setTimeout(resolve,3000));
    await loadFleet();
    if(targets.every(id=>!UPDATING.has(fleet.versions.get(id)?.job?.phase)))break;
  }
  fleet.updating=false;renderFleet();
  if(gatewayOld){
    if(!selectedDeck)startPanelUpdate();
    else api("/api/update",{},true).then(()=>toast(tr("Этот компьютер обновляется"),true)).catch(e=>toast(e.message));
  }else toast(tr("Компьютеры обновлены"),"success");
}

if(typeof module!=="undefined")module.exports={fleetTargets,versionLabel};
