// Settings: six sections, one card pattern (icon, title, coloured status, meta, one primary action, a
// "more" menu), editors that open in place of the card they edit, a getting-started card and dots on
// sections that need attention. Bundled before app.js; nothing here touches the page at load time.
const HUB_SECTIONS=["agents","notifications","models","computers","backups","general"];
// Old names still arrive from links and older code paths.
const HUB_ALIASES={connections:"notifications",network:"computers",app:"general"};
let hubSection="agents",lmData={profiles:[],discovery:{}},lmTimer=null,returnToNew=false,lmRefreshPending=null,lmModelsChecked=0;
let deckTimer=null,telegramConfig={},integrationTimer=null,telegramDirty=false,editorReturn=null;
let panelUpdating=false,panelVersion=null,versionTimer=null,versionLoading=null;
const UPDATE_PHASES=new Set(["checking","downloading","installing","restarting"]);

/* ---------- card pattern ---------- */
function cardIcon(icon){
  const box=el("span","card-icon");box.setAttribute("aria-hidden","true");
  box.append(icon instanceof Node?icon:svgIcon(icon));return box;
}
// tone: ok (works), warn (needs a step), bad (broken or unreachable), idle (off or not installed).
function hubCard({key,icon,title,status,tone="idle",meta,primary,more=[],body=[]}){
  const main=el("div","card-main",el("h4","",title));
  if(status)main.append(el("p","card-status "+tone,status));
  if(meta)main.append(el("p","card-meta",meta));
  const top=el("div","card-top",...(icon?[cardIcon(icon)]:[]),main),tools=el("div","card-tools");
  if(primary)tools.append(btn(primary.label,primary.quiet?"pri quiet":"pri",primary.run));
  if(more.length)tools.append(moreMenu(more,title));
  if(tools.childElementCount)top.append(tools);
  const card=el("div","hub-card",top,...body.filter(Boolean));card.dataset.card=key;
  return card;
}
function moreMenu(items,title){
  const menu=el("details","card-more"),summary=el("summary","",svgIcon("more"));
  summary.setAttribute("aria-label",tr("Другие действия: {0}",[title]));summary.title=tr("Другие действия");
  const list=el("div","card-menu");
  for(const [label,run,danger] of items.filter(Boolean))list.append(btn(label,danger?"danger":"",()=>{menu.open=false;run()}));
  menu.append(summary,list);return menu;
}
// A row inside a card (a computer, a device, a found server): name, status, then its own actions.
function hubRow({title,status,tone="idle",meta,actions=[]}){
  const info=el("div","hub-row-info",el("strong","",title));
  if(status)info.append(el("span","card-status "+tone,status));
  if(meta)info.append(el("span","card-meta",meta));
  return el("div","hub-row",info,el("div","hub-row-actions",...actions.filter(Boolean)));
}
function labelledButton(label,cls,run,name){const b=btn(label,cls,run);b.setAttribute("aria-label",label+": "+name);return b}
// An open editor replaces its card; a new item's editor goes first. A closed one stays in the list
// (hidden): rebuilding the cards must never drop it from the page.
function placeEditor(cards,key,editor){
  if(editor.hidden)return [...cards,editor];
  const index=cards.findIndex(card=>card.dataset.card===key);
  if(index<0)return [editor,...cards];
  cards[index].hidden=true;cards.splice(index+1,0,editor);return cards;
}
// After an editor closes, focus returns to the card it came from instead of the page body.
function focusCard(key){
  if(!key)return;
  requestAnimationFrame(()=>document.querySelector(`#settings_dlg [data-card="${key}"] .card-tools button, #settings_dlg [data-card="${key}"] .card-tools summary`)?.focus({preventScroll:true}));
}

/* ---------- sections ---------- */
function settingsSection(section){
  section=HUB_ALIASES[section]||section;
  if(!HUB_SECTIONS.includes(section))section="agents";
  const changed=section!==hubSection;hubSection=section;
  for(const name of HUB_SECTIONS)$("hub_"+name).hidden=name!==section;
  if(changed)document.querySelector(".hub-content").scrollTop=0;
  const open=$("settings_dlg").open;
  if(section==="backups"&&open)loadBackups();
  if(section==="notifications"&&open)loadPush();
  if(section==="computers"&&open)loadFleet(true);
  if(section==="models"&&open)refreshLMModels();
  for(const b of document.querySelectorAll(".hub-nav button")){
    const on=b.dataset.section===section;
    b.classList.toggle("on",on);b.setAttribute("aria-selected",String(on));b.tabIndex=on?0:-1;
    if(on&&isMobile())requestAnimationFrame(()=>{b.scrollIntoView({inline:"center",block:"nearest"});requestAnimationFrame(updateHubNavFade)});
  }
  updateHubNavFade();
}
function updateHubNavFade(){
  const nav=document.querySelector(".hub-nav");
  nav.classList.toggle("more-right",nav.scrollLeft+nav.clientWidth<nav.scrollWidth-4);
  nav.classList.toggle("more-left",nav.scrollLeft>4);
}
// Arrow keys move between sections, as in any tab list.
function hubNavKey(e){
  if(!["ArrowDown","ArrowUp","ArrowLeft","ArrowRight","Home","End"].includes(e.key))return;
  e.preventDefault();
  const i=HUB_SECTIONS.indexOf(hubSection),n=HUB_SECTIONS.length;
  const next=e.key==="Home"?0:e.key==="End"?n-1:(i+(["ArrowDown","ArrowRight"].includes(e.key)?1:-1)+n)%n;
  settingsSection(HUB_SECTIONS[next]);$("tab_"+HUB_SECTIONS[next]).focus();
}
async function openSettings(section="agents"){
  drawer(false);sheet(false);settingsSection(section);
  $("hub_title").textContent=deckDirectory.decks.length?tr("Настройки · {0}",[currentDeckName()]):tr("Настройки");
  if(!$("settings_dlg").open)$("settings_dlg").showModal();updateHubNavFade();
  renderHub();
  // Push and backup state feed the getting-started card and the section dots.
  await Promise.allSettled([loadDeckSettings(),loadPush(),loadBackups(),(async()=>{const data=await api("/api/project_directory");$("project_directory").value=data.directory})(),refreshLMModels(),loadIntegrations(),checkGithubFoot(),(async()=>{const data=await api("/api/locales");$("ui_language").replaceChildren(...data.languages.map(x=>{const o=el("option","",x.name);o.value=x.code;return o}));$("ui_language").value=I18N.language})()]);
  renderHub();
  clearInterval(lmTimer);lmTimer=setInterval(()=>{if(!document.hidden&&$("settings_dlg").open){if(lmData.discovery?.phase==="running")loadLM(false);if(hubSection==="models"&&Date.now()-lmModelsChecked>30000)refreshLMModels()}},2000);
}
function openHubEditor(){return ["kimi_dlg","integrations_dlg","lm_editor","deck_editor","backup_join_card"].map($).find(e=>!e.hidden)}
function hubEditorDirty(){
  return Boolean($("kimi_key").value||telegramDirty||$("lm_key").value||$("deck_password").value||$("backup_join_code").value||
    (!$("lm_editor").hidden&&!$("lm_id").value&&$("lm_url").value)||(!$("deck_editor").hidden&&!$("deck_id").value&&$("deck_url").value));
}
function closeHubEditor(editor){
  ({kimi_dlg:closeKimi,integrations_dlg:closeIntegrations,lm_editor:resetLM,deck_editor:closeDeckEditor,backup_join_card:closeBackupJoin})[editor.id]();
}
// Escape first closes an open editor; typed keys and passwords are never dropped without asking.
async function settingsCancel(e){
  const editor=openHubEditor();if(!editor)return;
  e.preventDefault();
  if(hubEditorDirty()&&!await confirmAction(tr("Изменения не сохранены. Закрыть без сохранения?"),{confirm:tr("Закрыть без сохранения"),danger:true}))return;
  closeHubEditor(editor);
}
async function closeSettings(){
  if(openHubEditor()&&hubEditorDirty()&&!await confirmAction(tr("Изменения не сохранены. Закрыть без сохранения?"),{confirm:tr("Закрыть без сохранения"),danger:true}))return;
  $("settings_dlg").close();
}
function settingsClosed(){
  if($("settings_dlg").open)return;
  clearInterval(lmTimer);clearInterval(deckTimer);closeKimi();closeIntegrations();resetLM();closeDeckEditor();
  if(returnToNew){returnToNew=false;$("dlg").showModal();renderSources()}
}
function hubInit(){
  const nav=document.querySelector(".hub-nav");
  nav.addEventListener("scroll",updateHubNavFade,{passive:true});nav.addEventListener("keydown",hubNavKey);
  $("settings_dlg").addEventListener("cancel",settingsCancel);
  $("settings_dlg").addEventListener("close",settingsClosed);
  for(const id of ["telegram_token","telegram_enabled"])$(id).addEventListener("input",()=>{telegramDirty=true});
  // A "more" menu closes when the tap lands anywhere else.
  document.addEventListener("click",e=>{for(const menu of document.querySelectorAll(".card-more[open]"))if(!menu.contains(e.target))menu.open=false});
}

/* ---------- attention: getting started and section dots ---------- */
function pushReadyHere(){
  if(!Array.isArray(pushState?.devices))return null;
  return pushState.devices.some(d=>d.id===localStore.getItem("cc.push-id"));
}
function setupSteps(){
  return [[tr("Войдите в Claude или Codex"),["claude","codex"].some(a=>lastAg[a]?.logged_in),"agents"],
    [tr("Включите уведомления на этом устройстве"),pushReadyHere(),"notifications"],
    [tr("Включите бэкапы"),backupStatus?Boolean(backupStatus.configured):null,"backups"]];
}
function renderSetupCard(){
  let hidden=false;try{hidden=localStore.getItem("cc.setup-hidden")==="1"}catch(e){}
  const steps=setupSteps(),box=$("setup_card");
  if(hidden||steps.every(([,done])=>done!==false)){box.replaceChildren();return}
  const list=el("div","setup-steps");
  for(const [label,done,section] of steps){
    const row=btn("","setup-step"+(done?" done":""),()=>settingsSection(section));
    row.append(el("span","setup-mark",done?"✓":"○"),el("span","",label));if(done)row.disabled=true;list.append(row);
  }
  const hide=btn(tr("Скрыть"),"setup-hide",()=>{try{localStore.setItem("cc.setup-hidden","1")}catch(e){}renderSetupCard()});
  box.replaceChildren(el("div","hub-card setup",el("div","card-top",el("div","card-main",el("h4","",tr("Начало работы")),
    el("p","card-meta",tr("Три шага, чтобы агенты работали и звали вас, когда нужны."))),hide),list));
}
function hubAttention(){
  const need=new Set(),version=panelVersion||{};
  if(lastAg.claude&&!["claude","codex"].some(a=>lastAg[a]?.logged_in))need.add("agents");
  if(pushState&&pushState.available&&!pushBlocker(pushEnvironment())&&pushReadyHere()===false)need.add("notifications");
  if((lmData.profiles||[]).some(p=>["offline","needs_key"].includes(p.status)))need.add("models");
  if(fleetTargets(fleet.versions).length||deckDirectory.decks.some(d=>fleet.versions.has(d.id)&&!fleet.versions.get(d.id)))need.add("computers");
  if(backupStatus&&!backupStatus.configured)need.add("backups");
  if((version.update&&version.can_update)||version.job?.phase==="error")need.add("general");
  return need;
}
function updateHubDots(){
  const need=hubAttention();
  for(const b of document.querySelectorAll(".hub-nav button")){
    const on=need.has(b.dataset.section);b.classList.toggle("attn",on);
    b.setAttribute("aria-description",on?tr("требует внимания"):"");
  }
}
function renderHub(){
  renderSetupCard();renderAgentCards();renderTelegramCard();
  // Rebuilding during a running test/benchmark would re-enable its buttons and allow a duplicate run.
  if($("model_cards").getAttribute("aria-busy")!=="true")renderModelCards();
  if(panelVersion)renderVersion(panelVersion);
  updateHubDots();
}
