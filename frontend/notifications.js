let pushState=null;

// Why notifications cannot be enabled here, as a translatable message; null when they can.
function pushBlocker({secure,ios,standalone,pushManager,origin}){
  if(!secure)return ["Уведомлениям нужен HTTPS-адрес панели. Сейчас она открыта по {0}.",[origin]];
  if(ios&&!standalone)return ["На iPhone и iPad добавьте панель на экран «Домой» и откройте её оттуда.",[]];
  if(!pushManager)return ["Этот браузер не поддерживает уведомления.",[]];
  return null;
}
function deviceLabel(ua){
  const device=/iPhone/.test(ua)?"iPhone":/iPad/.test(ua)?"iPad":/Android/.test(ua)?"Android":/Macintosh/.test(ua)?"Mac":/Windows/.test(ua)?"Windows":/Linux/.test(ua)?"Linux":"Browser";
  const browser=/Edg\//.test(ua)?"Edge":/Firefox\//.test(ua)?"Firefox":/(Chrome|CriOS)\//.test(ua)?"Chrome":/Safari\//.test(ua)?"Safari":"";
  return browser?device+" · "+browser:device;
}
function base64UrlBytes(text){
  const raw=atob(text.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-text.length%4)%4));
  return Uint8Array.from(raw,c=>c.charCodeAt(0));
}

function pushEnvironment(){
  const ua=navigator.userAgent,ios=/iPhone|iPad/.test(ua)||(/Macintosh/.test(ua)&&navigator.maxTouchPoints>1);
  return {secure:window.isSecureContext,ios,standalone:navigator.standalone===true||matchMedia("(display-mode: standalone)").matches,
    pushManager:"serviceWorker" in navigator&&"PushManager" in window,origin:location.origin};
}
async function loadPush(){
  try{pushState=await gatewayApi("/api/push")}catch(e){if(e.message!==STALE)toast(e.message);return}
  renderPush();
}
// Encryption parts download in the background; if that never finishes, say so instead of waiting forever.
let pushUnavailableSince=0;
function pushStatus(s,blocker,subscribed){
  if(blocker)return [tr(blocker[0],blocker[1]),"warn"];
  if(!s.available){
    pushUnavailableSince=pushUnavailableSince||Date.now();
    if(s.error)return [s.error,"bad"];
    return Date.now()-pushUnavailableSince>60000?[tr("Не удалось загрузить компоненты шифрования — обновите Agent Deck"),"bad"]:[tr("Панель скачивает компоненты шифрования…"),"idle"];
  }
  pushUnavailableSince=0;
  return subscribed?[tr("Включены на этом устройстве"),"ok"]:[tr("Выключены на этом устройстве"),"idle"];
}
function renderPush(){
  const s=pushState;if(!s)return;
  const blocker=pushBlocker(pushEnvironment()),mine=localStore.getItem("cc.push-id"),subscribed=s.devices.some(d=>d.id===mine);
  const [status,tone]=pushStatus(s,blocker,subscribed);
  $("push_state").textContent=status;$("push_state").className="card-status "+tone;
  // Without HTTPS the fix lives in another section: point there instead of leaving a dead end.
  $("push_fix").replaceChildren(...(blocker&&!pushEnvironment().secure?[el("p","hint",tr("Откройте панель по HTTPS-адресу или укажите его в разделе «Компьютеры» → «Публичный адрес».")),
    el("div","acts",btn(tr("Указать публичный адрес"),"",()=>{settingsSection("computers");$("network_public_url").focus()}))]:[]));
  const actions=[];
  if(!blocker&&s.available)actions.push(...(subscribed?[btn(tr("Выключить"),"",disablePush),btn(tr("Отправить тест"),"pri",()=>testPush(mine))]:[btn(tr("Включить уведомления"),"pri",enablePush)]));
  $("push_actions").replaceChildren(...(actions.length?[el("div","acts",...actions)]:[]));
  $("push_questions").checked=s.events.questions;$("push_finished").checked=s.events.finished;
  $("push_questions").disabled=$("push_finished").disabled=Boolean(blocker)||!s.available;
  $("push_devices_title").hidden=!s.devices.length;
  $("push_devices").replaceChildren(...s.devices.map(d=>{
    const name=d.label+(d.id===mine?" · "+tr("это устройство"):"");
    return hubRow({title:name,meta:formatBackupTime(d.created,DATE_LOCALE),actions:[labelledButton(tr("Удалить"),"danger",()=>removePushDevice(d),name)]});
  }));
  if($("settings_dlg").open){updateHubDots();renderSetupCard()}
}
async function enablePush(){
  // iOS only allows the permission prompt from a tap, which is why this runs from the button.
  try{
    if(await Notification.requestPermission()!=="granted"){toast(tr("Уведомления запрещены в настройках браузера или системы"));return}
    const registration=await navigator.serviceWorker.register("/sw.js");await navigator.serviceWorker.ready;
    const subscription=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:base64UrlBytes(pushState.public_key)});
    const result=await gatewayApi("/api/push_subscribe",{subscription:subscription.toJSON(),label:deviceLabel(navigator.userAgent),language:I18N.language});
    localStore.setItem("cc.push-id",result.id);
    await loadPush();await testPush(result.id);
  }catch(e){if(e.message!==STALE)toast(e.message||String(e))}
}
async function testPush(id){
  try{await gatewayApi("/api/push_test",{id});toast(tr("Тестовое уведомление отправлено"),"success")}catch(e){if(e.message!==STALE)toast(e.message)}
}
async function disablePush(){
  const id=localStore.getItem("cc.push-id");
  try{
    const registration=await navigator.serviceWorker.getRegistration("/");
    const subscription=registration&&await registration.pushManager.getSubscription();
    if(subscription)await subscription.unsubscribe();
    if(id)await gatewayApi("/api/push_unsubscribe",{id});
  }catch(e){if(e.message!==STALE)toast(e.message)}
  localStore.removeItem("cc.push-id");await loadPush();
}
async function removePushDevice(device){
  const id=device.id;
  if(id===localStore.getItem("cc.push-id"))return disablePush();
  if(!await confirmAction(tr("Удалить устройство «{0}»?",[device.label]),{text:tr("Уведомления туда перестанут приходить, пока их не включат на нём снова."),confirm:tr("Удалить"),danger:true}))return;
  try{await gatewayApi("/api/push_unsubscribe",{id});await loadPush()}catch(e){if(e.message!==STALE)toast(e.message)}
}
async function savePushEvents(){
  try{pushState.events=(await gatewayApi("/api/push_events",{questions:$("push_questions").checked,finished:$("push_finished").checked})).events}
  catch(e){if(e.message!==STALE)toast(e.message)}
  renderPush();
}
// A tap on a notification stores {deck, session}; the page opens it on start, resume or a worker message.
const OPEN_CACHE="agent-deck-open",OPEN_KEY="/__agent-deck-open";
async function takeNotificationTarget(storage){
  if(!storage)return null;
  try{
    const cache=await storage.open(OPEN_CACHE),hit=await cache.match(OPEN_KEY);
    if(!hit)return null;
    const target=await hit.json();
    await cache.delete(OPEN_KEY);
    return Date.now()-target.at<120000?target:null;  // An old tap must not jump sessions later.
  }catch(e){return null}
}
function openNotificationTarget(target){
  const deck=target.deck||"",session=target.session;
  if(!session&&deck===selectedDeck)return;
  if(deck!==selectedDeck){openDeckSession(deck,session);return}
  drawer(false);
  if(load.done)select(session);
  else activate(session);  // Before the first list: the load keeps this session when it exists.
}
// The page can become visible before the worker has stored the tapped target: look a few times.
let notificationWatch=null;
function watchNotificationTarget(){
  clearTimeout(notificationWatch);
  let attempt=0;
  const delays=[0,250,600,1200,2000,3000];
  const step=async()=>{if(await consumeNotificationTarget())return;if(++attempt<delays.length)notificationWatch=setTimeout(step,delays[attempt]-delays[attempt-1])};
  step();
}
async function consumeNotificationTarget(){
  const target=await takeNotificationTarget(window.caches);
  if(target)openNotificationTarget(target);
  return Boolean(target);
}
if("serviceWorker" in navigator&&window.isSecureContext){
  navigator.serviceWorker.addEventListener("message",event=>{if((event.data||{}).type==="agent-deck-open")consumeNotificationTarget()});
  navigator.serviceWorker.startMessages?.();
  navigator.serviceWorker.register("/sw.js").catch(()=>{});
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)watchNotificationTarget()});
  addEventListener("focus",watchNotificationTarget);
  addEventListener("pageshow",watchNotificationTarget);
  setTimeout(watchNotificationTarget,0);  // After app.js has restored this computer's state.
}

if(typeof module!=="undefined")module.exports={pushBlocker,deviceLabel,base64UrlBytes,takeNotificationTarget};
