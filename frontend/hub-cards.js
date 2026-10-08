// Settings cards for agents (with Kimi and GitHub), Telegram and the version. Bundled before app.js.

/* ---------- agents ---------- */
function agentCard(a){
  const st=lastAg[a]||{},title=AGENTS[a].label,icon=agentIcon({agent:a}),update=[tr("Обновить"),()=>agentAction("install",a)];
  if(!st.installed)return hubCard({key:a,icon,title,status:tr("Не установлен"),primary:{label:tr("Установить"),run:()=>agentAction("install",a)}});
  if(!st.logged_in)return hubCard({key:a,icon,title,status:tr("Вход не выполнен"),tone:"warn",meta:st.version,
    primary:{label:tr("Войти"),run:()=>agentAction("login",a)},more:[update]});
  return hubCard({key:a,icon,title,status:tr("Подключён"),tone:"ok",meta:st.version,more:[update]});
}
// One Kimi key serves Claude on Kimi models and Kimi Code, so both live on this card.
function kimiCard(){
  const st=lastAg.kimi||{},config=lastAg.kimi_config||{};
  const install=[st.installed?tr("Обновить Kimi Code"):tr("Установить Kimi Code"),()=>agentAction("install","kimi")];
  return hubCard({key:"kimi",icon:agentIcon({agent:"kimi"}),title:"Kimi",
    status:config.configured?tr("Ключ сохранён · {0}",[config.model||"k3"]):tr("Ключ не указан"),tone:config.configured?"ok":"idle",
    meta:st.installed?"Kimi Code "+(st.version||""):tr("Kimi Code не установлен"),
    primary:config.configured?null:{label:tr("Указать ключ"),run:openKimi,quiet:true},
    more:[config.configured&&[tr("Изменить ключ и модель"),openKimi],install],
    body:[el("p","hint",tr("Ключ используют Claude на моделях Kimi и Kimi Code."))]});
}
function piCard(){
  const st=lastAg.pi||{},icon=agentIcon({agent:"pi"}),hint=el("p","hint",tr("Агент для локальных моделей LM Studio."));
  if(!st.installed)return hubCard({key:"pi",icon,title:"Pi",status:tr("Не установлен"),primary:{label:tr("Установить"),run:()=>agentAction("install","pi"),quiet:true},body:[hint]});
  return hubCard({key:"pi",icon,title:"Pi",status:tr("Установлен"),tone:"ok",meta:st.version,more:[[tr("Обновить"),()=>agentAction("install","pi")]],body:[hint]});
}
function githubCard(){
  const icon=el("span","");icon.innerHTML=GH_ICON;
  const leave=run=>()=>{returnToNew=false;$("settings_dlg").close();run()};
  if(!ghLogin)return hubCard({key:"github",icon,title:"GitHub",status:tr("Не подключён"),primary:{label:tr("Подключить"),run:leave(ghConnect),quiet:true},
    body:[el("p","hint",tr("Чтобы выбирать репозиторий при создании сессии."))]});
  return hubCard({key:"github",icon,title:"GitHub",status:"@"+ghLogin,tone:"ok",more:[[tr("Новая сессия из репозитория"),leave(openNew)]]});
}
function renderAgentCards(){
  if(editorInUse($("kimi_dlg")))return;
  const cards=[agentCard("claude"),agentCard("codex"),kimiCard(),piCard(),githubCard()];
  $("agent_cards").replaceChildren(...placeEditor(cards,"kimi",$("kimi_dlg")));
}
function openKimi(){
  const config=lastAg.kimi_config||{};
  $("kimi_key").value="";$("kimi_model").value=config.model||"k3";
  $("kimi_state").textContent=config.configured?tr("Ключ сохранён на сервере"):tr("Ключ ещё не указан");
  $("kimi_state").className="card-status "+(config.configured?"ok":"idle");
  $("kimi_clear").hidden=!config.configured;
  $("kimi_dlg").hidden=false;snapshotEditor($("kimi_dlg"));openSettings("agents");$("kimi_dlg").scrollIntoView({block:"nearest"});
  // On a phone the keyboard would cover the explanation and the Save button.
  if(!isMobile()&&lastPointer!=="touch")$("kimi_key").focus({preventScroll:true});
}
function closeKimi(){
  const wasOpen=!$("kimi_dlg").hidden;
  $("kimi_key").value="";$("kimi_dlg").hidden=true;
  if($("settings_dlg").open){renderHub();if(wasOpen)focusCard("kimi")}
}
async function saveKimi(clear=false){
  $("kimi_save").disabled=true;
  try{
    await api("/api/kimi_config",{key:$("kimi_key").value.trim(),model:$("kimi_model").value,clear});
    await checkGithubFoot();closeKimi();await loadUsage();renderSources();toast(clear?tr("Ключ Kimi удалён"):tr("Настройки Kimi сохранены"),"success");
  }catch(e){toast(e.message)}finally{$("kimi_save").disabled=false}
}
async function clearKimi(){if(await confirmAction(tr("Удалить ключ Kimi из панели?"),{text:tr("Сессии на моделях Kimi перестанут запускаться, пока ключ не будет указан снова."),confirm:tr("Удалить ключ"),danger:true}))saveKimi(true)}
// Install and sign-in run in a session of their own; Settings steps aside so it is visible.
async function agentAction(kind,agent){
  const name=kind==="install"?"install-"+agent:agent+"-login";
  if(await post("/api/agent_"+kind,{agent})){if($("settings_dlg").open)$("settings_dlg").close();select(name);if(isMobile())setMode("screen")}
}

/* ---------- Telegram ---------- */
function telegramSummary(c){
  if(c.available===false)return [tr("Нужно обновление Agent Deck: Общие → Версия и обновления"),"bad"];
  if(c.error)return [c.error,"bad"];
  if(c.paired)return [`@${c.bot} · ${c.account||tr("аккаунт привязан")} · ${c.enabled?tr("включён"):tr("пауза")}`,c.enabled?"ok":"warn"];
  if(c.configured)return [tr("@{0} · привяжите свой Telegram",[c.bot]),"warn"];
  return [tr("Не настроен"),"idle"];
}
// The same bot polled by another computer delivers every question twice; it can be turned off there from here.
const telegramClearedOn=new Set();  // The server remembers duplicates for a minute; a computer just switched off is not one.
function duplicateWarning(c){
  const decks=(c.duplicates||[]).map(d=>typeof d==="string"?{name:d}:d).filter(d=>!telegramClearedOn.has(d.id));
  if(!decks.length)return null;
  const box=el("div","integration-note danger",el("p","",tr("Этот бот также включён на: {0}. Вопросы будут приходить дважды; отключите Telegram там.",[decks.map(d=>d.name).join(", ")])));
  for(const d of decks)if(d.id)box.append(btn(tr("Отключить на {0}",[d.name]),"danger",()=>disableTelegramOn(d)));
  return box;
}
async function disableTelegramOn(deck){
  if(!await confirmAction(tr("Отключить Telegram на {0}?",[deck.name]),{text:tr("Токен бота там будет удалён; здесь Telegram продолжит работать."),confirm:tr("Отключить"),danger:true}))return;
  try{await api(instancePath(deck.id,"/api/telegram_config"),{clear:true});telegramClearedOn.add(deck.id);toast(tr("Telegram отключён на {0}",[deck.name]),"success")}
  catch(e){if(e.message!==STALE)toast(e.message)}
  renderTelegram(telegramConfig);
}
function renderTelegramCard(){
  if(editorInUse($("integrations_dlg")))return;
  const [status,tone]=telegramSummary(telegramConfig);
  const card=hubCard({key:"telegram",icon:el("span","telegram-glyph",svgIcon("telegram")),title:"Telegram",status,tone,
    primary:{label:tr("Настроить"),run:openIntegrations,quiet:Boolean(telegramConfig.paired)},
    more:[telegramConfig.configured&&[tr("Отключить"),clearTelegram,true]],
    body:[el("p","hint",tr("Вопросы с кнопками ответа в личном чате с вашим ботом.")),duplicateWarning(telegramConfig)]});
  $("telegram_cards").replaceChildren(...placeEditor([card],"telegram",$("integrations_dlg")));
}
function renderTelegram(config){
  const wasConfigured=telegramConfig.configured;
  telegramConfig=config||{};
  const c=telegramConfig,[status,tone]=telegramSummary(c),state=$("telegram_state");
  if(wasConfigured!==c.configured)$("telegram_credentials").open=!c.configured;
  $("telegram_credentials").querySelector("summary").textContent=c.configured?tr("Изменить токен бота"):tr("Токен бота");
  // Polled every few seconds: rewriting the same text would make screen readers repeat it.
  if(state.textContent!==status)state.textContent=status;
  state.className="card-status "+tone;
  const warning=duplicateWarning(c);
  $("telegram_duplicates").hidden=!warning;$("telegram_duplicates").replaceChildren(...(warning?[warning]:[]));
  if(!telegramDirty)$("telegram_enabled").checked=c.enabled!==false;  // A poll must not undo the user's switch.
  $("telegram_clear").hidden=!c.configured;
  $("telegram_pair").hidden=!(c.configured&&!c.pair_url);
  $("telegram_pair").textContent=c.paired?tr("Привязать другой аккаунт"):tr("Получить ссылку привязки");
  $("telegram_pairing").hidden=!c.pair_url;
  if(typeof c.pair_url==="string"&&c.pair_url.startsWith("https://t.me/"))$("telegram_link").href=c.pair_url;else $("telegram_link").removeAttribute("href");
  if($("settings_dlg").open&&$("integrations_dlg").hidden)renderTelegramCard();
  renderInteg();
}
async function loadIntegrations(){
  try{const data=await api("/api/integrations");renderTelegram(data.telegram)}catch(e){if(!$("integrations_dlg").hidden&&e.message!==STALE)$("telegram_state").textContent=e.message}
}
function openIntegrations(){
  telegramDirty=false;$("telegram_token").value="";$("telegram_credentials").open=!telegramConfig.configured;$("integrations_dlg").hidden=false;
  $("telegram_enabled").checked=telegramConfig.enabled!==false;snapshotEditor($("integrations_dlg"));
  openSettings("notifications");loadIntegrations();$("integrations_dlg").scrollIntoView({block:"nearest"});
  clearInterval(integrationTimer);integrationTimer=setInterval(()=>{if(!document.hidden&&!telegramDirty)loadIntegrations()},3000);
}
function closeIntegrations(){
  const wasOpen=!$("integrations_dlg").hidden;
  $("telegram_token").value="";telegramDirty=false;clearInterval(integrationTimer);$("integrations_dlg").hidden=true;
  if($("settings_dlg").open){renderHub();if(wasOpen)focusCard("telegram")}
}
async function saveTelegram(clear=false){
  $("telegram_save").disabled=true;
  try{
    const data=await api("/api/telegram_config",{token:$("telegram_token").value.trim(),enabled:$("telegram_enabled").checked,language:I18N.language,clear});
    telegramDirty=false;$("telegram_token").value="";renderTelegram(data.telegram);
    if(!clear&&!data.telegram.paired)await pairTelegram();
    toast(clear?tr("Telegram отключён"):tr("Настройки Telegram сохранены"),"success");
  }catch(e){toast(e.message)}finally{$("telegram_save").disabled=false}
}
async function pairTelegram(){
  try{const data=await api("/api/telegram_pair",{});renderTelegram(data.telegram)}catch(e){toast(e.message)}
}
async function clearTelegram(){if(await confirmAction(tr("Отключить Telegram и удалить сохранённый токен?"),{confirm:tr("Отключить"),danger:true}))saveTelegram(true)}

/* ---------- version and updates ---------- */
// What the version card says and which single action it offers; also drives the sidebar and the menu.
function versionState(v){
  const job=v.job||{};
  // The button stays, disabled, so the progress is visible where the update was started.
  if(UPDATE_PHASES.has(job.phase))return {status:job.message||tr("Обновляю панель…"),tone:"idle",label:job.message||tr("Обновляю панель…"),run:()=>{}};
  if(job.phase==="done"&&job.version===v.version&&UI_PANEL_VERSION!==null&&job.version!==UI_PANEL_VERSION)
    return {status:tr("Обновлено до v{0}",[v.version]),tone:"ok",label:tr("Перезагрузить страницу"),run:refreshInterface};
  if(job.phase==="error")return {status:tr("Обновление не удалось: {0}",[job.message||tr("ошибка")]),tone:"bad",label:tr("Повторить обновление"),run:startPanelUpdate};
  if(v.update)return v.incomplete?{status:tr("Не хватает компонентов"),tone:"warn",label:tr("Доустановить компоненты"),run:startPanelUpdate}
    :{status:tr("Доступна v{0}",[v.latest]),tone:"warn",label:tr("Обновить до v")+v.latest,run:startPanelUpdate};
  if(v.release_error)return {status:tr("Не удалось проверить обновления"),tone:"idle"};
  return {status:tr("Установлена последняя версия"),tone:"ok"};
}
function renderVersion(v){
  panelVersion=v;const job=v.job||{},state=versionState(v),box=$("ver"),mobile=$("s_update");
  panelUpdating=UPDATE_PHASES.has(job.phase);
  box.replaceChildren("v"+v.version);box.title=v.latest?tr("последний релиз: v{0}",[v.latest]):"";
  const blocked=Boolean(state.run===startPanelUpdate&&!v.can_update);
  const how=v.container?tr("Контейнер: обновите образ и пересоздайте контейнер: {0}",[v.update_command||"docker compose up -d --build"]):tr("Разработка: обновляйте чекаут через git. Кнопка доступна после установки панели.");
  mobile.style.display="none";
  if(blocked)box.title=how;
  if(state.label||panelUpdating){
    box.append(btn(tr("Обновить"),"",()=>openSettings("general")));
    $("s_update_label").textContent=state.label||state.status;mobile.style.display="flex";mobile.disabled=panelUpdating||blocked;
  }
  $("version_status").textContent=state.status;$("version_status").className="card-status "+state.tone;
  const revision=el("span","version-build","UI "+UI_REVISION.slice(0,7));revision.title=UI_REVISION;
  $("version_meta").replaceChildren("v"+v.version+" · ",revision);
  $("version_hint").hidden=!(blocked||!v.can_update);$("version_hint").textContent=v.can_update?"":how;
  const actions=[btn(tr("Проверить обновления"),"",checkPanelUpdates)];actions[0].id="b_check_updates";
  if(state.run!==refreshInterface){const reload=btn(tr("Перезагрузить страницу"),"",refreshInterface);reload.id="b_refresh_interface";actions.push(reload)}
  if(state.label){const main=btn(state.label,"pri",state.run);main.id="b_update";main.disabled=panelUpdating||blocked;actions.push(main)}
  for(const b of actions)if(b.id!=="b_update")b.disabled=panelUpdating;
  $("hub_version").replaceChildren(...actions);
  // Containers and development checkouts update outside the panel: the switch would only mislead.
  $("auto_update_row").hidden=$("auto_update_hint").hidden=!v.can_update||!v.auto_update;
  $("auto_update_enabled").checked=v.auto_update?.enabled!==false;$("auto_update_enabled").disabled=panelUpdating;
  $("auto_update_status").textContent=v.auto_update?.phase==="waiting"?tr("Обновление ждёт завершения локальной генерации"):"";
  if($("settings_dlg").open)updateHubDots();
  renderAttachments();
}
async function checkPanelUpdates(){
  const button=$("b_check_updates");if(button)button.disabled=true;
  try{renderVersion(await api("/api/check_update",{}));toast(tr("Проверка завершена"),"success")}
  catch(e){toast(e.message)}finally{if(button)button.disabled=false}
}
async function saveAutoUpdates(){
  const input=$("auto_update_enabled"),enabled=input.checked;input.disabled=true;
  try{const data=await api("/api/auto_update",{enabled});renderVersion({...panelVersion,auto_update:data.auto_update})}
  catch(e){input.checked=!enabled;toast(e.message)}finally{input.disabled=!panelVersion?.can_update}
}
