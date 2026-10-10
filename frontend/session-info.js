// The open session's conversation at a glance, read by the panel from the agent's own conversation file: a
// quiet summary under the bar (its headline and first sentence; a tap shows all of it) and, at the bottom,
// the two restarts, how long the conversation has run and how full the context is. Shells, other agents and computers without this version show neither.
const sessionInfo={session:null,data:null,timer:null,seq:0};
const SESSION_INFO_POLL=30000;
const CONTEXT_SCALE=200000;  // A full bar for Claude, whose window the conversation file does not state.
// Colours by size, not by the window: quality drops long before it is full. No published number exists;
// Claude Code users most often report the drop around 150k. Both are set in Settings, in this browser.
const CONTEXT_LIMITS={heavy:80000,full:150000};
function contextLimits(){
  let saved={};try{saved=JSON.parse(localStore.getItem("cc.context-limits")||"{}")}catch(e){}
  const heavy=saved.heavy>0?saved.heavy:CONTEXT_LIMITS.heavy,full=saved.full>0?saved.full:CONTEXT_LIMITS.full;
  return full>heavy?{heavy,full}:CONTEXT_LIMITS;
}
function contextLevel(tokens){const limits=contextLimits();return tokens>=limits.full?"full":tokens>=limits.heavy?"heavy":"fine"}
function applyContextLimits(){
  const limits=contextLimits(),heavy=document.getElementById("context_heavy"),full=document.getElementById("context_full");
  if(heavy)heavy.value=String(limits.heavy/1000);
  if(full)full.value=String(limits.full/1000);
}
function saveContextLimits(){
  const heavy=Math.round(+$("context_heavy").value*1000),full=Math.round(+$("context_full").value*1000);
  if(!(heavy>0&&full>heavy)){toast(tr("Красный порог должен быть больше жёлтого"));applyContextLimits();return}
  try{localStore.setItem("cc.context-limits",JSON.stringify({heavy,full}))}catch(e){}
  renderSessionInfo();
}
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
// The summary's first sentence; CJK full stops are followed by no space.
function firstSentence(text){
  const found=/^[\s\S]*?(?:[.!?…]+(?=\s|$)|[。！？])/.exec((text||"").trim());
  return found?found[0]:(text||"").trim();
}
function renderSessionInfo(){
  const data=sessionInfo.data?.supported?sessionInfo.data:null;
  $("session_meta").hidden=!data;
  renderContext(data?.context,data?.started);
  const summary=data?.summary,hint=$("session_hint");
  hint.hidden=!summary||!(summary.line||summary.updating);
  if(hint.hidden)return;
  const open=summaryOpen()&&Boolean(summary.line);
  $("hint_line").textContent=summary.line||tr("Составляю пересказ…");
  // Closed: the headline and the first sentence, two or three lines; open: all of it below.
  const lead=open?"":firstSentence(summary.text);
  $("hint_lead").textContent=lead;$("hint_lead").hidden=!lead;
  $("hint_toggle").setAttribute("aria-expanded",String(open));
  hint.classList.toggle("open",open);
  $("hint_more").hidden=!open;
  $("hint_text").textContent=summary.text||"";
  $("hint_meta").textContent=summary.at?tr("Пересказ: {0} · {1}",[summary.model,relativeTime(summary.at)]):"";
}
function renderContext(context,started){
  const box=$("ctx"),fill=$("ctx_fill");
  const level=context?contextLevel(context.tokens):"";
  box.dataset.level=level;
  fill.style.width=context?Math.min(100,Math.round(context.tokens/(context.window||CONTEXT_SCALE)*100))+"%":"0";
  const text=context?tr("Контекст {0}",[formatTokens(context.tokens)+(context.window?" / "+formatTokens(context.window):"")]):tr("Контекст: нет данных");
  $("ctx_text").textContent=text;
  // Age matters next to size: a long conversation has drifted from its start even when compaction keeps it small.
  const age=started?compactDuration(Math.max(0,Math.floor((Date.now()/1000-started)/60))):"";
  $("ctx_age").textContent=age;$("ctx_age_box").hidden=!age;
  const hint=(context?text+" · "+tr(CONTEXT_LEVELS[level]):text)+(age?" · "+tr("Разговор идёт {0}",[age]):"");
  box.title=hint;box.setAttribute("aria-label",hint);
}
if(typeof document!=="undefined")document.addEventListener("visibilitychange",()=>{if(!document.hidden&&sessionInfo.session)loadSessionInfo()});
