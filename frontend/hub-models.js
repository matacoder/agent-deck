// Settings cards for LM Studio servers and for other computers running Agent Deck. Bundled before app.js.

/* ---------- local models (LM Studio) ---------- */
const LM_STATUS={online:["Подключён","ok"],needs_key:["Нужен API-ключ","warn"],offline:["Не отвечает","bad"]};
function lmMetrics(m){
  const label=m.source==="session"?tr("Последний ответ"):m.source==="benchmark"?tr("Тест скорости"):tr("Замер");
  const parts=[];
  if(Number.isFinite(m.tokens_per_second))parts.push(m.tokens_per_second.toFixed(1)+" tok/s");
  if(Number.isFinite(m.time_to_first_token_seconds))parts.push(tr("первый токен {0} с",[m.time_to_first_token_seconds.toFixed(2)]));
  if(Number.isFinite(m.model_load_time_seconds))parts.push(tr("загрузка {0} с",[m.model_load_time_seconds.toFixed(2)]));
  return parts.length?label+": "+parts.join(" · "):"";
}
function lmModelPicker(p,selection){
  const select=el("select","");select.dataset.profile=p.id;select.setAttribute("aria-label",tr("Модель на {0}",[p.name]));
  for(const m of p.models){const o=el("option","",m.name+(m.loaded?" · "+tr("загружена"):"")+(m.tool_tested?" · ✓ "+tr("инструменты"):""));o.value=m.id;select.append(o)}
  if(selection)select.value=selection;if(!select.value&&select.options.length)select.selectedIndex=0;
  const detail=el("p","card-meta");
  const describe=()=>{const m=p.models.find(x=>x.id===select.value)||{};detail.textContent=[m.context_length||m.max_context_length?tr("Контекст: {0}",[m.context_length||m.max_context_length]):"",m.quantization||"",m.tool_tested?tr("Инструменты: ✓"):tr("Инструменты: не проверены")].filter(Boolean).join(" · ")};
  select.onchange=describe;describe();
  const actions=el("div","acts",btn(tr("Проверить инструменты"),"",()=>lmAction("test",{id:p.id,model:select.value})),btn(tr("Измерить скорость"),"",()=>lmAction("benchmark",{id:p.id,model:select.value})));
  return [select,detail,actions];
}
function lmCard(p,selection){
  const [status,tone]=LM_STATUS[p.status]||["Не проверен","idle"];
  const primary=p.status==="needs_key"?{label:tr("Указать ключ"),run:()=>editLM(p)}:p.status==="offline"?{label:tr("Проверить снова"),run:()=>lmAction("probe",{id:p.id}),quiet:true}:null;
  const samples=p.measurements?Object.values(p.measurements).flatMap(group=>Object.values(group)):[p.performance||{}];
  const body=samples.map(lmMetrics).filter(Boolean).map(text=>el("p","card-metrics",text));
  if(p.status==="offline")body.unshift(el("p","hint",tr("{0} не отвечает. Запустите LM Studio, включите Developer → Start server и проверьте порт.",[p.url])));
  if(p.models?.length)body.push(...lmModelPicker(p,selection));
  return hubCard({key:"lm:"+p.id,icon:"cpu",title:p.name,status:tr(status),tone,meta:p.url,primary,
    more:[[tr("Обновить список моделей"),()=>lmAction("probe",{id:p.id})],[tr("Изменить"),()=>editLM(p)],[tr("Удалить"),()=>removeLM(p),true]],body});
}
function renderModelCards(){
  const selections=new Map([...$("model_cards").querySelectorAll("select")].map(x=>[x.dataset.profile,x.value]));
  const cards=(lmData.profiles||[]).map(p=>lmCard(p,selections.get(p.id)));
  if(!cards.length&&$("lm_editor").hidden)cards.push(el("p","hub-empty",tr("Серверов пока нет. Добавьте адрес LM Studio или найдите его в Tailscale ниже.")));
  $("model_cards").replaceChildren(...placeEditor(cards,"lm:"+$("lm_id").value,$("lm_editor")));
}
async function refreshLMModels(){
  if(document.hidden)return;
  if(lmRefreshPending)return lmRefreshPending;
  lmModelsChecked=Date.now();
  lmRefreshPending=(async()=>{try{lmData=await refreshModelCatalog(api);if($("settings_dlg").open)renderHub();renderDiscovery();renderSources()}catch(e){if(!e.offline)toast(e.message)}finally{lmRefreshPending=null}})();
  return lmRefreshPending;
}
async function loadLM(refresh=true){try{lmData=await api("/api/lmstudio");if($("settings_dlg").open&&refresh)renderHub();renderDiscovery()}catch(e){if(e.message!==STALE)$("lm_progress").textContent=e.message}}
function editLM(p={}){
  $("lm_id").value=p.id||"";$("lm_name").value=p.name||"";$("lm_url").value=p.url||"";$("lm_key").value="";$("lm_clear_key").checked=false;
  $("lm_clear_row").hidden=!p.id;
  $("lm_editor_title").textContent=p.id?tr("Изменить · {0}",[p.name]):tr("Новый сервер LM Studio");
  $("lm_editor").hidden=false;if(hubSection!=="models")settingsSection("models");
  renderModelCards();$("lm_editor").scrollIntoView({block:"nearest"});
  if(!isMobile()&&lastPointer!=="touch")$(p.id&&p.status==="needs_key"?"lm_key":"lm_name").focus({preventScroll:true});
}
function resetLM(){
  const key=$("lm_id").value,wasOpen=!$("lm_editor").hidden;
  $("lm_editor").hidden=true;$("lm_id").value="";$("lm_name").value="";$("lm_url").value="";$("lm_key").value="";
  if($("settings_dlg").open&&wasOpen){renderModelCards();if(key)focusCard("lm:"+key)}
}
async function saveLM(){
  const button=$("lm_save");button.disabled=true;
  try{
    const saved=await api("/api/lm_save",{id:$("lm_id").value||undefined,name:$("lm_name").value.trim(),url:$("lm_url").value.trim(),key:$("lm_key").value,clear_key:$("lm_clear_key").checked});
    $("lm_key").value="";await api("/api/lm_probe",{id:saved.profile.id});resetLM();await loadLM();renderSources();focusCard("lm:"+saved.profile.id);
  }catch(e){toast(e.message)}finally{button.disabled=false}
}
const LM_WORKING={probe:"Проверяю модели…",test:"Проверяю инструменты…",benchmark:"Измеряю скорость…",remove:"Удаляю…"};
async function lmAction(action,data){
  if($("model_cards").getAttribute("aria-busy")==="true")return;
  const buttons=[...$("model_cards").querySelectorAll("button")];buttons.forEach(b=>b.disabled=true);$("model_cards").setAttribute("aria-busy","true");toast(tr(LM_WORKING[action]),true);
  let r=null;
  try{r=await api("/api/lm_"+action,data);if(r.result)toast(r.result.ok?tr("Проверка завершена"):r.result.error,r.result.ok?"success":"error");else if(action!=="remove")hideToast()}catch(e){toast(e.message)}
  finally{buttons.forEach(b=>b.disabled=false);$("model_cards").removeAttribute("aria-busy")}
  // Reload after clearing aria-busy, otherwise renderHub would skip the refreshed model cards.
  if(r){if(action==="remove")toast(tr("Сервер удалён"),"success");await loadLM();renderSources()}
}
async function removeLM(p){
  if(await confirmAction(tr("Удалить сервер LM Studio «{0}»?",[p.name]),{text:tr("Сессии на его моделях перестанут отвечать."),confirm:tr("Удалить"),danger:true}))lmAction("remove",{id:p.id});
}
function lmPorts(){return $("lm_ports").value.split(/[\s,;]+/).filter(Boolean).map(Number)}
async function discoverLM(cancel=false){try{await api("/api/lm_discover",cancel?{cancel:true}:{ports:lmPorts()});await loadLM()}catch(e){toast(e.message)}}
function renderDiscovery(){
  const d=lmData.discovery||{},running=d.phase==="running";
  $("lm_progress").textContent=d.error||[tr(running?"Поиск…":d.phase==="done"?"Поиск завершён":d.phase==="cancelled"?"Остановлено":""),d.total?d.checked+" / "+d.total:""].filter(Boolean).join(" · ");
  $("lm_cancel").hidden=!running;$("lm_find").disabled=running;
  $("lm_results").replaceChildren(...(d.results||[]).map(p=>hubRow({title:p.name,meta:p.url,status:p.status==="needs_key"?tr("Нужен API-ключ"):"",tone:"warn",
    actions:[labelledButton(tr("Добавить"),"",()=>editLM({name:p.name,url:p.url}),p.name)]})));
}
function configureSource(){returnToNew=true;$("dlg").close();openSettings("models")}

/* ---------- computers ---------- */
function renderComputers(data,network){
  $("network_name").value=network.name;$("network_public_url").value=network.public_url;$("network_isolate").checked=network.isolate_terminals===true;
  $("network_bind").textContent="http://"+network.bind_host+":"+network.bind_port;
  $("network_browser").textContent=location.origin;
  const count=data.decks.length;
  $("deck_summary").textContent=count?tr("Подключено: {0}",[count]):tr("Пока не подключены");
  $("deck_summary").className="card-status "+(count?"ok":"idle");
  $("network_isolate_row").hidden=$("network_isolate_hint").hidden=!count;
  const rows=data.decks.map(deck=>{
    const row=hubRow({title:deck.name,meta:deck.url,status:"…",
      actions:[deck.id===selectedDeck?el("span","card-meta",tr("открыт")):labelledButton(tr("Открыть"),"",()=>switchDeck(deck.id),deck.name),
        moreMenu([[tr("Изменить"),()=>editDeck(deck)],[tr("Отключить"),()=>removeDeck(deck),true]],deck.name)]});
    row.querySelector(".card-status").dataset.deckVersion=deck.id;row.dataset.card="deck:"+deck.id;return row;
  });
  $("deck_connections").replaceChildren(...placeEditor(rows,"deck:"+$("deck_id").value,$("deck_editor")));
  renderDeckDiscovery(data.discovery);
}
function editDeck(deck={}){
  $("deck_id").value=deck.id||"";$("deck_name").value=deck.name||"";$("deck_url").value=deck.url||"";$("deck_username").value=deck.username||"";$("deck_password").value="";
  $("deck_editor_title").textContent=deck.id?tr("Изменить · {0}",[deck.name]):tr("Подключить другой Agent Deck");
  $("deck_save").textContent=deck.id?tr("Сохранить"):tr("Подключить");
  $("deck_editor").hidden=false;
  const row=deck.id&&$("deck_connections").querySelector(`[data-card="deck:${deck.id}"]`);
  if(row){row.hidden=true;row.after($("deck_editor"))}else $("deck_connections").prepend($("deck_editor"));
  $("deck_editor").scrollIntoView({block:"nearest"});
  if(!isMobile()&&lastPointer!=="touch")$(deck.url?"deck_username":"deck_name").focus({preventScroll:true});
}
function closeDeckEditor(){
  const key=$("deck_id").value;
  $("deck_editor").hidden=true;$("deck_password").value="";$("deck_id").value="";$("deck_url").value="";
  for(const row of $("deck_connections").querySelectorAll(".hub-row[hidden]"))row.hidden=false;
  // The editor lives in the section, not inside a row that the next render replaces.
  $("hub_computers").append($("deck_editor"));
  if(key)focusCard("deck:"+key);
}
async function saveDeck(){
  const button=$("deck_save");button.disabled=true;
  try{await gatewayApi("/api/decks_save",{id:$("deck_id").value||undefined,name:$("deck_name").value.trim(),url:$("deck_url").value.trim(),username:$("deck_username").value.trim(),password:$("deck_password").value});closeDeckEditor();await loadDeckSettings();toast(tr("Agent Deck подключён"),"success")}
  catch(e){$("deck_password").value="";toast(e.message)}finally{button.disabled=false}
}
async function removeDeck(deck){
  if(!await confirmAction(tr("Отключить «{0}»?",[deck.name]),{text:tr("Сессии на нём продолжат работать; сохранённый пароль будет удалён с этого сервера."),confirm:tr("Отключить"),danger:true}))return;
  try{await gatewayApi("/api/decks_remove",{id:deck.id});if(deck.id===selectedDeck)switchDeck("");else await loadDeckSettings()}catch(e){toast(e.message)}
}
function renderDeckDiscovery(discovery){
  $("deck_discover").disabled=discovery.phase==="running";
  $("deck_discovery_status").textContent=discovery.error||tr(discovery.phase==="running"?"Поиск…":discovery.phase==="done"?"Поиск завершён":"");
  $("deck_discovery_results").replaceChildren(...(discovery.results||[]).map(deck=>hubRow({title:deck.name,meta:deck.url,actions:[labelledButton(tr("Подключить"),"",()=>editDeck(deck),deck.name)]})));
  clearInterval(deckTimer);
  if(discovery.phase==="running")deckTimer=setInterval(async()=>{if(document.hidden||!$("settings_dlg").open)return;try{const data=await gatewayApi("/api/decks");renderDeckDiscovery(data.discovery)}catch(e){toast(e.message);clearInterval(deckTimer)}},2000);
}
async function discoverDecks(){
  try{const result=await gatewayApi("/api/decks_discover",{port:Number($("deck_port").value)});renderDeckDiscovery(result.discovery)}catch(e){toast(e.message)}
}
// fields: the name and public address to save; the isolation switch saves alone with the stored ones.
async function saveNetworkSettings(isolate,fields){
  const changed=isolate!==(deckDirectory.network?.isolate_terminals===true);
  await gatewayApi("/api/network_save",{...fields,isolate_terminals:isolate});
  // Open terminal frames were loaded under the previous mode; reopen them under the new one.
  if(changed&&selectedDeck)for(const frame of frames.values())frame.src=frame.src;
  await loadDeckSettings();
}
async function saveNetwork(){
  const button=$("network_save");button.disabled=true;
  try{await saveNetworkSettings($("network_isolate").checked,{name:$("network_name").value.trim(),public_url:$("network_public_url").value.trim()});toast(tr("Настройки сохранены"),"success")}catch(e){toast(e.message)}finally{button.disabled=false}
}
async function saveIsolation(){
  const input=$("network_isolate");input.disabled=true;
  const stored=deckDirectory.network||{};
  try{await saveNetworkSettings(input.checked,{name:stored.name||deckDirectory.name,public_url:stored.public_url||""});toast(tr("Настройки сохранены"),"success")}catch(e){input.checked=!input.checked;toast(e.message)}finally{input.disabled=false}
}

if(typeof module!=="undefined")module.exports={lmMetrics};
