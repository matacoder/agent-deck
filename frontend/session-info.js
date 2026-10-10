// The open session's conversation at a glance, read by the panel from the agent's own conversation file: a
// quiet one-line summary under the bar (a tap shows all of it) and, at the bottom, how full the context is
// next to the two restarts. Shells, other agents and computers without this version show neither.
const sessionInfo={session:null,data:null,timer:null,seq:0};
const SESSION_INFO_POLL=30000;
const CONTEXT_SCALE=200000;  // A full bar for Claude, whose window the conversation file does not state.
const CONTEXT_LEVELS={fine:"Разговор свежий",heavy:"Разговор разросся: агент начинает хуже держать детали",full:"Пора начать новый разговор: контекст переполнен"};

function summaryOpen(){try{return localStore.getItem("cc.summary-open")==="1"}catch(e){return false}}
function toggleSummary(){
  try{localStore.setItem("cc.summary-open",summaryOpen()?"0":"1")}catch(e){}
  renderSessionInfo();
}
// Per computer and session: the same name on another computer is another conversation.
function sessionInfoKey(){return active?(selectedDeck||"")+"/"+active:null}
function watchSessionInfo(){if(sessionInfo.session!==sessionInfoKey())loadSessionInfo()}
async function loadSessionInfo(){
  clearTimeout(sessionInfo.timer);
  const key=sessionInfoKey(),seq=++sessionInfo.seq;
  if(sessionInfo.session!==key){sessionInfo.session=key;sessionInfo.data=null;renderSessionInfo()}
  if(!key)return;
  let data=null;
  try{data=await api("/api/session_info?name="+encodeURIComponent(active))}
  catch(e){if(e.message===STALE)return}  // A computer without this version, or a shell: nothing to show.
  if(seq!==sessionInfo.seq)return;
  sessionInfo.data=data;renderSessionInfo();
  // A summary being written is asked for again soon; otherwise the conversation changes slowly.
  if(!document.hidden)sessionInfo.timer=setTimeout(loadSessionInfo,data?.summary?.updating?8000:SESSION_INFO_POLL);
}
function formatTokens(n){return n>=1000?Math.round(n/1000)+"k":String(n)}
function renderSessionInfo(){
  const data=sessionInfo.data?.supported?sessionInfo.data:null;
  $("session_meta").hidden=!data;
  renderContext(data?.context);
  const summary=data?.summary,hint=$("session_hint");
  hint.hidden=!summary||!(summary.line||summary.updating);
  if(hint.hidden)return;
  const open=summaryOpen()&&Boolean(summary.line);
  $("hint_line").textContent=summary.line||tr("Составляю пересказ…");
  $("hint_toggle").setAttribute("aria-expanded",String(open));
  hint.classList.toggle("open",open);
  $("hint_more").hidden=!open;
  $("hint_text").textContent=summary.text||"";
  $("hint_meta").textContent=summary.at?tr("Пересказ: {0} · {1}",[summary.model,relativeTime(summary.at)]):"";
}
function renderContext(context){
  const box=$("ctx"),fill=$("ctx_fill");
  box.dataset.level=context?.level||"";
  fill.style.width=context?Math.min(100,Math.round(context.tokens/(context.window||CONTEXT_SCALE)*100))+"%":"0";
  const text=context?tr("Контекст {0}",[formatTokens(context.tokens)+(context.window?" / "+formatTokens(context.window):"")]):tr("Контекст: нет данных");
  $("ctx_text").textContent=text;
  const hint=context?text+" · "+tr(CONTEXT_LEVELS[context.level]||CONTEXT_LEVELS.fine):text;
  box.title=hint;box.setAttribute("aria-label",hint);
}
if(typeof document!=="undefined")document.addEventListener("visibilitychange",()=>{if(!document.hidden&&sessionInfo.session)loadSessionInfo()});
