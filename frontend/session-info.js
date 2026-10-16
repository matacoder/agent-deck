// The open session's conversation at a glance, read by the panel from the agent's own conversation file: a
// summary under the bar (its whole headline; a tap shows the rest) and, at the bottom,
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
  // Nothing is saved until the pair fits, and the fields keep what was typed: the other one is changed next.
  if(!(heavy>0&&full>heavy)){toast(tr("Красный порог должен быть больше жёлтого"));return}
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
  // A session seen before shows what was known about it at once; the answer below replaces it.
  if(sessionInfo.session!==key){sessionInfo.session=key;sessionInfo.data=knownAnswer(sessionInfoKnown,key);renderSessionInfo()}
  if(!key)return;
  let data;
  try{data=await api("/api/session_info?name="+encodeURIComponent(active))}
  // A failed poll keeps what is shown. A computer without this version has had nothing to show since the key changed.
  catch(e){if(e.message===STALE)return;data=sessionInfo.data}
  if(seq!==sessionInfo.seq)return;
  // One answer without a conversation after ones with it is a hiccup far more often than a change (the id is
  // read from tmux at that moment): the line under the field stays until a second answer says the same.
  if(data&&!data.supported&&sessionInfo.data?.supported&&!sessionInfo.doubt){
    sessionInfo.doubt=true;if(!document.hidden)sessionInfo.timer=setTimeout(loadSessionInfo,5000);return;
  }
  sessionInfo.doubt=false;
  sessionInfo.data=data;keepAnswer(sessionInfoKnown,key,data);renderSessionInfo();
  // A summary being written is asked for again soon; otherwise the conversation changes slowly.
  if(!document.hidden)sessionInfo.timer=setTimeout(loadSessionInfo,data?.summary?.updating?8000:SESSION_INFO_POLL);
}
// The terminal of a restarted or shortened conversation holds only its last screens; the agent's own file
// still has what was said before. Kept per computer and session and shown while it is read again.
const conversationKnown=new Map();
// The agent writes Markdown (tables, headings, lists); the owner's own messages stay as typed.
function talkText(turn){
  if(turn.role==="user")return el("div","talk-text",turn.text);
  const md=renderMarkdown(turn.text||"");md.className="talk-text md talk-md";return md;
}
function renderConversation(data,failed){
  const box=$("talk_list"),stick=!box.querySelector(".talk-turn")||atBottom(box);
  if(!data){box.replaceChildren(failed?el("p","hint",failed):listSkeleton());return}
  const turns=data.supported?data.turns||[]:[];
  if(!turns.length){box.replaceChildren(el("p","hint",tr(data.supported?"В этом разговоре пока нет сообщений.":"У этой сессии нет разговора, который можно прочитать.")));return}
  box.replaceChildren(...turns.map(turn=>el("div","talk-turn"+(turn.role==="user"?" mine":""),el("div","talk-who",tr(turn.role==="user"?"Вы":"Агент")),talkText(turn))));
  if(stick)box.scrollTop=box.scrollHeight;
}
async function openConversation(){
  if(!active)return;
  const key=sessionInfoKey(),known=knownAnswer(conversationKnown,key);
  $("talk_list").replaceChildren();
  if(!$("talk_dlg").open)$("talk_dlg").showModal();
  renderConversation(known);
  try{
    const data=await api("/api/conversation?name="+encodeURIComponent(active));
    if(key!==sessionInfoKey()||!$("talk_dlg").open)return;
    keepAnswer(conversationKnown,key,data,8);renderConversation(data);
  }catch(e){if(e.message!==STALE&&!known)renderConversation(null,e.message)}
}
function formatTokens(n){return n>=1000?Math.round(n/1000)+"k":String(n)}
function renderSessionInfo(){
  const data=sessionInfo.data?.supported?sessionInfo.data:null;
  $("session_meta").hidden=!data;
  renderContext(data?.context,data?.started);
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
