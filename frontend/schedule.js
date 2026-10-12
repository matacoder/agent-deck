// Sending without typing or waiting: quick prompts (one tap), prompts held for later (a time, a free
// session, a limit reset) and continuing by itself after a subscription limit. Bundled before app.js.
const later={session:null,data:null,seq:0,timer:null,failed:false,opened:null};
const quick={saved:[],loaded:false,more:false};
const LATER_POLL=30000;
// The user's own prompts, then the agent's commands behind "more": they are rare and one of them drops the
// conversation. With `shared` the "more" of the keys row opens them, so no second one is drawn. A terminal
// gets none. Pure for tests.
function quickChips(agent,saved,more,shared){
  if(agent==="shell")return [];
  const commands=agentCommands(agent);
  return [...saved.map(p=>({label:p.label,text:p.text})),...(commands.length&&!shared?[{more:true}]:[]),...(more?commands:[])];
}
// Rows of the editor -> what is saved; empty rows are dropped, not reported. Pure for tests.
function quickRows(rows){
  return rows.map(r=>({label:r.label.trim(),text:r.text})).filter(r=>r.text.trim());
}
function laterWhen(prompt,translate,formatTime){
  if(prompt.trigger==="time")return formatTime(prompt.at);
  return translate(prompt.trigger==="limit"?"Когда сбросится лимит":"Когда агент освободится");
}
// The next round five minutes, an hour ahead, as a datetime-local value in the browser's own time zone.
function defaultLaterTime(now){
  const at=new Date(Math.ceil((now+3600000)/300000)*300000),two=n=>String(n).padStart(2,"0");
  return `${at.getFullYear()}-${two(at.getMonth()+1)}-${two(at.getDate())}T${two(at.getHours())}:${two(at.getMinutes())}`;
}
function laterCount(data){return data?data.prompts.length+(data.auto_resume?1:0):0}

function laterKey(){return active?(selectedDeck||"")+"/"+active:null}
function watchLater(){
  renderQuickPrompts();
  if(!quick.loaded){quick.loaded=true;loadQuickPrompts()}
  if(later.session!==laterKey())loadLater();
}
async function loadLater(){
  clearTimeout(later.timer);
  const key=laterKey(),seq=++later.seq;
  if(later.session!==key){later.session=key;later.data=null;renderLater()}
  if(!key)return;
  let data;
  // A computer without this version has no schedule: the button then explains it instead of failing silently.
  try{data=await api("/api/schedule?name="+encodeURIComponent(active));later.failed=false}
  catch(e){if(e.message===STALE)return;data=later.data;later.failed=true}
  if(seq!==later.seq)return;
  later.data=data&&Array.isArray(data.prompts)?data:null;renderLater();
  if(!document.hidden)later.timer=setTimeout(loadLater,LATER_POLL);
}
function formatLaterTime(seconds){
  return new Date(seconds*1000).toLocaleString(DATE_LOCALE,{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"});
}
function renderLater(){
  const count=laterCount(later.data),button=$("b_later");
  $("later_count").textContent=count||"";button.classList.toggle("on",count>0);
  const label=count?tr("Отправить позже · ждут: {0}",[count]):tr("Отправить позже");
  // The button by the field appears only while something waits; otherwise the action lives in the menu.
  button.hidden=!count;button.setAttribute("aria-label",label);$("s_later_label").textContent=label;
  if(!$("later_dlg").open)return;
  const data=later.data,shell=agentOf(cur())==="shell";
  $("later_title").textContent=cur()?tr("Отправить позже · {0}",[sessionTitle(cur())]):tr("Отправить позже");
  $("later_limit_option").hidden=shell;$("later_auto_row").hidden=shell;
  if(document.activeElement!==$("later_auto"))$("later_auto").checked=Boolean(data?.auto_resume);
  const limit=data?.limit;
  $("later_limit").hidden=!limit;
  $("later_limit").textContent=limit?(limit.at?tr("Лимит исчерпан · сброс {0}",[formatLaterTime(limit.at)]):tr("Лимит исчерпан · время сброса на экране не распознано")):"";
  $("later_error").hidden=!data?.error;
  $("later_error").textContent=data?.error?tr("Не отправлено: ")+tr(data.error):"";
  const rows=(data?.prompts||[]).map(p=>{
    const row=el("div","later-item",el("div","later-body",el("b","",laterWhen(p,tr,formatLaterTime)),el("p","",p.text)));
    const remove=btn("","later-remove",()=>removeLater(p.id),tr("Удалить"));
    remove.type="button";remove.setAttribute("aria-label",tr("Удалить"));remove.append(svgIcon("x"));
    row.append(remove);return row;
  });
  $("later_list").replaceChildren(...rows);
  $("later_waiting").hidden=!rows.length;
}
function openLater(){
  if(!active)return;
  if(!later.data){
    // A read that failed is not an old panel: saying so would send the owner to update for nothing.
    toast(later.failed?tr("Не удалось прочитать отложенные сообщения. Проверьте связь и повторите"):tr("На этом компьютере нужна новая версия панели, чтобы отправлять позже"));
    loadLater();return;
  }
  later.opened=laterKey();
  $("later_text").value=$("msg").value;
  $("later_at").value=defaultLaterTime(Date.now());
  $("later_dlg").querySelector("input[name=later_trigger][value=idle]").checked=true;
  syncLaterTime();
  $("later_dlg").showModal();renderLater();loadLater();
}
function syncLaterTime(){
  $("later_at").hidden=$("later_dlg").querySelector("input[name=later_trigger]:checked").value!=="time";
}
// The dialog belongs to the session it was opened for. If another one is on screen by now (a notification
// tap, a closed session), nothing is sent: the heading already names the new one, the next press goes there.
function laterMoved(){
  if(later.opened===laterKey())return false;
  later.opened=laterKey();renderLater();
  toast(tr("Открыта другая сессия. Проверьте, куда уйдёт сообщение, и повторите"));
  return true;
}
async function saveLater(){
  if(laterMoved())return;
  const name=active,text=$("later_text").value,trigger=$("later_dlg").querySelector("input[name=later_trigger]:checked").value;
  if(!text.trim()){toast(tr("Введите сообщение"));$("later_text").focus();return}
  const at=trigger==="time"?Math.floor(new Date($("later_at").value).getTime()/1000):undefined;
  if(trigger==="time"&&!at){toast(tr("Укажите время отправки"));return}
  $("later_save").disabled=true;
  try{
    const data=await api("/api/schedule_add",{name,text,trigger,at});
    if(active!==name)return;
    later.data=data;
    // The message now waits on the server; keeping it in the field would send it twice.
    if($("msg").value===text){$("msg").value="";$("msg").dispatchEvent(new Event("input"))}
    $("later_text").value="";$("later_dlg").close();renderLater();
    toast(tr("Сообщение ждёт отправки"),"success");
  }catch(e){if(e.message!==STALE)toast(e.message)}finally{$("later_save").disabled=false}
}
async function removeLater(id){
  try{await api("/api/schedule_remove",{id});await loadLater()}catch(e){if(e.message!==STALE)toast(e.message)}
}
async function saveAutoResume(){
  const box=$("later_auto"),enabled=box.checked;
  if(laterMoved()){box.checked=!enabled;return}
  try{later.data=await api("/api/auto_resume",{name:active,enabled});renderLater()}
  catch(e){box.checked=!enabled;if(e.message!==STALE)toast(e.message)}
}

/* ---------- Quick prompts ---------- */
async function loadQuickPrompts(){
  // One list for every computer, so it is read from the gateway.
  try{quick.saved=(await api("/api/quick_prompts",null,true)).prompts||[]}catch(e){quick.loaded=false}
  renderQuickPrompts();
}
function renderQuickPrompts(){
  // One "more" on a phone: when the keys row shows its own, it opens the agent's commands too.
  const shared=$("b_keymore").offsetParent!==null,open=shared?$("keys").classList.contains("expanded"):quick.more;
  const box=$("quick_prompts"),session=cur(),prompts=session?quickChips(agentOf(session),quick.saved,open,shared):[];
  box.hidden=!session||agentOf(session)==="shell"||!prompts.length&&shared;
  $("b_compact").hidden=!session||!compactCommand(agentOf(session));
  const signature=JSON.stringify(prompts);
  if(box.dataset.signature===signature)return;  // Rebuilt on every refresh otherwise: a tap in progress would be lost.
  box.dataset.signature=signature;
  const chips=prompts.map(p=>{
    if(!p.more){const chip=btn(p.label,"quick-chip",()=>sendQuick(p),p.text);chip.type="button";return chip}
    const more=btn("","quick-chip quick-edit",()=>{quick.more=!quick.more;renderQuickPrompts()},tr("Команды агента"));
    more.type="button";more.setAttribute("aria-label",tr("Команды агента"));more.setAttribute("aria-expanded",String(quick.more));more.append(svgIcon("more"));
    return more;
  });
  const edit=btn("","quick-chip quick-edit",openQuickEditor,tr("Настроить быстрые сообщения"));
  edit.type="button";edit.setAttribute("aria-label",tr("Настроить быстрые сообщения"));edit.append(svgIcon("pencil"));
  box.replaceChildren(...chips,edit);
}
async function sendQuick(prompt){
  if(sending||uploading||panelUpdating||!active)return;
  if(prompt.confirm&&!await confirmAction(tr("Отправить {0}?",[prompt.text]),{text:tr(prompt.confirm),confirm:tr("Отправить"),danger:true}))return;
  // Bound to the computer and session it was tapped on, like a typed message.
  const deck=selectedDeck,epoch=deckEpoch,name=active;
  sending=true;renderAttachments();
  sendStates.set(name,{text:tr("Отправляю…"),phase:"pending"});renderSendState();
  try{
    await api(instancePath(deck,"/api/send"),{name,text:prompt.text},true);
    sendStates.set(name,{text:tr("Отправлено в ")+agentLabel(sessions.find(s=>s.name===name))+" · "+new Date().toLocaleTimeString(DATE_LOCALE,{hour:"2-digit",minute:"2-digit"}),phase:"success"});
    await load();
  }catch(e){
    if(epoch===deckEpoch)sendStates.set(name,{text:tr("Не отправлено: ")+e.message,error:true});
    else toast(tr("Не отправлено: ")+e.message);
  }finally{sending=false;quick.more=false;renderAttachments();renderSendState();renderQuickPrompts()}
}
// The agent's own command for a shorter conversation, or nothing for an agent without one. Pure for tests.
function compactCommand(agent){return agentCommands(agent).find(c=>c.compact)||null}
function compactConversation(){const command=cur()&&compactCommand(agentOf(cur()));if(command)sendQuick(command)}
function quickEditorRow(prompt){
  const label=el("input"),text=el("textarea"),remove=btn("","later-remove",()=>row.remove(),tr("Удалить"));
  label.type="text";label.maxLength=30;label.value=prompt.label||"";label.placeholder=tr("Подпись кнопки");label.setAttribute("aria-label",tr("Подпись кнопки"));
  text.rows=2;text.maxLength=4000;text.value=prompt.text||"";text.placeholder=tr("Текст сообщения");text.setAttribute("aria-label",tr("Текст сообщения"));
  remove.type="button";remove.setAttribute("aria-label",tr("Удалить"));remove.append(svgIcon("x"));
  const row=el("div","quick-row",el("div","quick-fields",label,text),remove);
  return row;
}
async function openQuickEditor(){
  // Saving writes the whole list: it is read first, so a list that did not load, or was changed on another
  // device, is never replaced by an empty or old one.
  try{quick.saved=(await api("/api/quick_prompts",null,true)).prompts||[]}
  catch(e){if(e.message!==STALE)toast(tr("Не удалось прочитать быстрые сообщения. Проверьте связь и повторите"));return}
  renderQuickPrompts();
  $("quick_rows").replaceChildren(...quick.saved.map(quickEditorRow));
  if(!quick.saved.length)addQuickRow();
  $("quick_dlg").showModal();
}
function addQuickRow(){
  if($("quick_rows").children.length>=24){toast(tr("Быстрых сообщений может быть не больше 24"));return}
  const row=quickEditorRow({});$("quick_rows").append(row);row.querySelector("input").focus();
}
async function saveQuickPrompts(){
  const rows=[...$("quick_rows").children].map(r=>({label:r.querySelector("input").value,text:r.querySelector("textarea").value}));
  $("quick_save").disabled=true;
  try{
    quick.saved=(await api("/api/quick_prompts",{prompts:quickRows(rows)},true)).prompts;
    $("quick_dlg").close();renderQuickPrompts();
  }catch(e){if(e.message!==STALE)toast(e.message)}finally{$("quick_save").disabled=false}
}
if(typeof document!=="undefined")document.addEventListener("visibilitychange",()=>{if(!document.hidden&&later.session)loadLater()});

if(typeof module!=="undefined")module.exports={quickChips,quickRows,laterWhen,defaultLaterTime,laterCount,compactCommand};
