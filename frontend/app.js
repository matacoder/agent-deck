const I18N=__PANEL_I18N__;
const DATE_LOCALE=(()=>{try{return Intl.getCanonicalLocales(I18N.language)[0]}catch(e){return "en"}})();
const $=id=>document.getElementById(id);
function tr(message,params=[]){return (I18N.messages[message]??message).replace(/\{(\d+)\}/g,(_,n)=>String(params[n]??""))}

// Blocked storage throws SecurityError on access; an in-memory fallback keeps the app usable.
function browserStorage(name){
  try{const storage=window[name];if(storage)return storage}catch(e){}
  const memory=new Map();
  return {getItem:k=>memory.has(k)?memory.get(k):null,setItem:(k,v)=>{memory.set(k,String(v))},removeItem:k=>{memory.delete(k)}};
}
const localStore=browserStorage("localStorage"),sessionStore=browserStorage("sessionStorage");
let selectedDeck="";
// Notification links carry ?deck=<id> so a cold start opens the right computer.
try{
  const params=new URLSearchParams(location.search);
  if(params.has("deck")){const deck=params.get("deck");if(deck===""||/^[0-9a-f]{24}$/.test(deck))localStore.setItem("cc.deck",deck);history.replaceState(null,"",location.pathname+location.hash)}
}catch(e){}
try{selectedDeck=localStore.getItem("cc.deck")||""}catch(e){}
if(!/^[0-9a-f]{24}$/.test(selectedDeck))selectedDeck="";
let deckLocalStorage=instanceStorage(localStore,selectedDeck);
let deckSessionStorage=instanceStorage(sessionStore,selectedDeck);
// Bumped on every computer switch; responses started for the previous computer are dropped.
let deckEpoch=0;
const STALE="stale Agent Deck response";
function activePath(path){return instancePath(selectedDeck,path)}
async function gatewayApi(path,body){return api(path,body,true)}

const BUSY_SEC=6;
const UI_REVISION="__PANEL_REVISION__";
// Phone landscape (932×430 on a Pro Max) keeps the phone layout; keep in sync with the mobile block in style.css.
const MOBILE_QUERY="(max-width:760px),(pointer:coarse) and (max-height:500px)";
const isMobile=()=>matchMedia(MOBILE_QUERY).matches;
// Layout follows the width; touch handling follows the pointer, so an iPad or an unfolded iPhone in the
// wide layout still gets finger-sized controls, keyboard handling and the Screen view by default.
const isTouch=()=>matchMedia("(pointer:coarse)").matches;
const modKey=()=>/Mac|iPhone|iPad/.test(navigator.platform||navigator.userAgent)?"⌥":"Alt+";
let lastPointer="mouse";
addEventListener("pointerdown",e=>{lastPointer=e.pointerType},true);
let sessions=[],active=null,mode=null,clockSkew=0;
const frames=new Map(),wasBusy=new Map(),attention=new Set();

/* keep layout glued to the visible area when the iOS keyboard opens */
function fitViewport(){
  const vv=window.visualViewport;if(!vv)return;
  if(Math.abs(vv.scale-1)>0.01)return; // Pinch zoom must not resize the document layout.
  const root=document.documentElement;
  const keyboard=(isMobile()||isTouch())&&Math.abs(vv.scale-1)<0.01&&root.clientHeight-vv.height>150;
  // Keep controls inside the web view: the OS-owned strip below an installed
  // app is outside its drawable viewport, even when screen.height is larger.
  root.style.setProperty("--app-h",vv.height+"px");
  root.style.setProperty("--app-top",keyboard?vv.offsetTop+"px":"0px");
  document.body.classList.toggle("keyboard-open",keyboard);
}
if(window.visualViewport){visualViewport.addEventListener("resize",fitViewport);visualViewport.addEventListener("scroll",fitViewport);fitViewport()}
addEventListener("pageshow",fitViewport);
addEventListener("orientationchange",()=>requestAnimationFrame(fitViewport));

// Network failures and proxy/restart answers are "offline", not bugs: they go to the connection pill.
class OfflineError extends Error{constructor(message){super(message);this.offline=true}}
const API_READ_TIMEOUT=25000;
async function api(path,body,gateway=false,options={}){
  const epoch=deckEpoch;
  let r;
  // iOS can park a request while the app is in the background and never settle it; every poll
  // guarded by "one request at a time" would then wait forever. Reads give up; mutations are not
  // retried blindly, so they keep waiting for a definite answer.
  // Another computer is reached through the gateway, which itself waits up to 30 s for it.
  const limit=options.timeout||(selectedDeck&&!gateway?API_READ_TIMEOUT*2:API_READ_TIMEOUT);
  const controller=body?null:new AbortController(),timer=controller&&setTimeout(()=>controller.abort(),limit);
  try{r=await fetch(gateway?path:activePath(path),body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{cache:"no-store",signal:controller.signal})}
  catch(e){
    clearTimeout(timer);if(!gateway&&epoch!==deckEpoch)throw new Error(STALE);
    throw new OfflineError(controller?.signal.aborted?tr("Панель не ответила за {0} с",[Math.round(limit/1000)]):tr("Нет связи с панелью"));
  }
  if(r.status===401){
    try{stashDrafts();location.href="/login"}catch(e){toast(tr("Войдите в новой вкладке: здесь сохранён несохранённый текст."),true,{label:tr("Войти"),run:()=>window.open("/login","_blank","noopener")})}
    // Already handled above; a caller's toast(e.message) must not replace the login prompt.
    throw new Error(STALE);
  }
  const d=r.headers.get("Date");if(d)clockSkew=Date.now()/1000-Date.parse(d)/1000;
  let j=null;try{j=await r.json()}catch(e){}  // An aborted body read lands here and reads as offline below.
  clearTimeout(timer);
  // Gateway answers (other computers, inbox, update-all) do not depend on the selected computer.
  if(!gateway&&epoch!==deckEpoch)throw new Error(STALE);
  if([502,503,504].includes(r.status))throw new OfflineError(j?.error||tr("Нет связи с панелью"));
  // A proxy or captive page can answer 200 with HTML; never hand that to code expecting JSON.
  if(!j||typeof j!=="object")throw new OfflineError(controller?.signal.aborted?tr("Панель не ответила за {0} с",[Math.round(limit/1000)]):tr("Панель вернула неожиданный ответ"));
  // A route this computer's Agent Deck does not have yet: say what to do instead of "Not Found".
  if(r.status===404&&(!j.error||/^(not found|Agent Deck route not found)$/i.test(j.error)))throw new Error(tr("Эта функция недоступна: обновите Agent Deck на этом компьютере"));
  if(!r.ok)throw new Error(j.error||r.statusText);return j;
}
// Shown only when connecting takes noticeable time, so a quick resume does not flicker.
let connection="online",connectionTimer=null;
function setConnection(next){
  const pill=$("conn");clearTimeout(connectionTimer);
  if(next==="online"){
    if(connection!=="online"&&!pill.hidden){pill.className="conn ok";pill.textContent=tr("Связь восстановлена");connectionTimer=setTimeout(()=>{pill.hidden=true},1500)}
    else pill.hidden=true;
  }else if(next==="connecting"){
    connectionTimer=setTimeout(()=>{pill.className="conn";pill.textContent=tr("Подключаюсь…");pill.hidden=false},400);
  }else{pill.className="conn bad";pill.textContent=tr("Нет связи с панелью · повторяю");pill.hidden=false}
  connection=next;
}
function toast(m,info,action){
  if(m===STALE)return;
  const t=$("toast"),dialogs=Array.from(document.querySelectorAll("dialog[open]"));
  (dialogs[dialogs.length-1]||document.body).append(t);t.className=info==="success"?"success":info?"info":"";t.replaceChildren(el("span","",m));
  if(action){const b=document.createElement("button");b.textContent=action.label;b.onclick=e=>{e.stopPropagation();action.run();hideToast()};t.append(b)}
  t.setAttribute("role",info?"status":"alert");t.setAttribute("aria-live",info?"polite":"assertive");
  t.classList.add("on");clearTimeout(t._h);t._h=setTimeout(hideToast,action?12000:(info?2200:8000));
}
function hideToast(){$("toast").classList.remove("on")}
$("toast").addEventListener("click",hideToast);

/* tmux (set-clipboard on) sends selections as OSC 52 -> put them on the browser clipboard.
   Over plain HTTP there is no Clipboard API, so copy via execCommand right after the mouse-up
   (still inside the user activation window); if the browser refuses, offer a button. */
async function copyToClipboard(text,w){
  const done=()=>toast(tr("Скопировано: {0} симв.",[text.length]),"success");
  try{if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(text);return done()}}catch(e){}
  const ok=execCopy(text,w.document);
  try{w.term.focus()}catch(e){}
  if(ok)return done();
  toast(tr("Выделение из терминала готово"),true,{label:tr("Копировать"),run:()=>{execCopy(text,document)?done():toast(tr("Браузер запретил копирование"))}});
}
function hookClipboard(w,tries=0){
  const t=w.term;
  if(!t||!t.parser){if(tries<100)setTimeout(()=>hookClipboard(w,tries+1),100);return}
  if(t._ccClip)return;t._ccClip=true;
  t.parser.registerOscHandler(52,data=>{
    const b64=data.slice(data.indexOf(";")+1);
    if(!b64||b64==="?")return true;
    try{copyToClipboard(new TextDecoder().decode(Uint8Array.from(atob(b64),c=>c.charCodeAt(0))),w)}catch(e){}
    return true;
  });
}
const now=()=>Date.now()/1000-clockSkew;
const AGENTS={claude:{label:"Claude",glyph:"✻",skip:"--dangerously-skip-permissions"},
  codex:{label:"Codex",glyph:"◎",skip:"--dangerously-bypass-approvals-and-sandbox"},
  "claude-kimi":{label:"Claude · Kimi",glyph:"✻",skip:"--dangerously-skip-permissions"},
  kimi:{label:"Kimi Code",glyph:"◈",skip:"--auto"},
  pi:{label:"Pi",glyph:"π",skip:""},
  shell:{label:tr("Терминал"),glyph:"$"}};
const agentOf=s=>AGENTS[s&&s.agent]?s.agent:"claude";
const isLocal=s=>s?.source?.kind==="lmstudio";
const localComputer=s=>lmData.profiles.find(p=>p.id===s.source.profile)?.name||s.source.label?.split(" · ")[1]||"LM Studio";
const agentLabel=s=>isLocal(s)?shortModel(s.source.model||tr("локальная модель"))+" · "+localComputer(s):AGENTS[agentOf(s)].label;
function agentIcon(s){
  const icon=el("span","ag "+(isLocal(s)?"local":agentOf(s)));
  icon.setAttribute("aria-hidden","true");
  if(isLocal(s))icon.innerHTML='<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>';
  else icon.textContent=AGENTS[agentOf(s)].glyph;
  return icon;
}
const state=s=>{
  const recent=now()-s.activity<BUSY_SEC;
  if(agentOf(s)==="shell")return recent?"busy":"sh";
  return !s.running?"off":(recent?"busy":"idle");
};
function stateText(s){
  const a=agentLabel(s),st=state(s);
  if(agentOf(s)==="shell")return st==="busy"?tr("терминал · вывод…"):(s.running?tr("терминал · ")+s.command:tr("терминал"));
  return {off:a+tr(" не запущен"),busy:a+tr(" работает…"),idle:a+tr(" ждёт")}[st];
}
function el(tag,cls,...kids){const e=document.createElement(tag);if(cls)e.className=cls;e.append(...kids);return e}
const shortPath=p=>p.replace(/^.*\/(?:projects|dev)\//,"~/").replace(/\.worktrees\//,"⎇ ");
const curMode=()=>mode||(isMobile()||isTouch()?"screen":"term");

function drawer(on){document.body.classList.toggle("drawer",on);if(on)$("q").blur()}
const drawerSwipe={panel:document.querySelector("aside"),isOpen:()=>document.body.classList.contains("drawer"),setOpen:on=>drawer(on),
  enabled:()=>isMobile()&&!document.querySelector("dialog[open]")&&$("viewer").hidden&&!$("sheet").classList.contains("on")};
attachDrawerSwipe(document,drawerSwipe);
function sheet(on){
  if(on){
    const s=cur(),groups=$("sheet").querySelectorAll(".sheet-group");
    $("sheetCap").textContent=s?sessionTitle(s):"Agent Deck";
    groups[0].hidden=groups[1].hidden=groups[3].hidden=!s;
    $("s_mode_label").textContent=curMode()==="term"?tr("Показать экран"):tr("Показать терминал");
    $("s_mode").querySelector("use").setAttribute("href",curMode()==="term"?"#i-file":"#i-terminal");
    $("s_link").style.display=lastUrl(s)?"":"none";
  }
  const wasOpen=$("sheet").classList.contains("on");
  $("sheet").classList.toggle("on",on);
  $("b_actions").setAttribute("aria-expanded",String(on));
  // Keyboard users land in the menu and return to its button; taps keep focus where it was.
  if(on&&!wasOpen&&lastPointer!=="touch"&&!isMobile())[...$("sheet").querySelectorAll(".panel button")].find(b=>b.offsetParent)?.focus();
  if(!on&&wasOpen&&$("sheet").contains(document.activeElement))$("b_actions").focus();
}
for(const item of $("sheet").querySelectorAll(".panel button"))item.setAttribute("role","menuitem");
// Escape on an edited file asks first instead of dropping the changes.
$("files_dlg").addEventListener("cancel",e=>{if(filesDirty()){e.preventDefault();leaveFile()}});
addEventListener("keydown",e=>{if(e.key==="Escape"&&$("sheet").classList.contains("on"))sheet(false)});
async function confirmAction(title,{text="",confirm=tr("Продолжить"),danger=false}={}){
  return askConfirm($("confirm_dlg"),{title,text,confirm,danger});
}
const cur=()=>sessions.find(x=>x.name===active);
const messageDrafts=new Map();
const closedDrafts=new Map();
let quickSignature=null,quickActive=null;
const quickRemote=new Map();
const quickButtons=new Map();
function renderQuickTabs(){
  const others=otherDecks.filter(d=>d.id!==selectedDeck),waiting=inboxCount();
  const box=$("quick_tabs"),signature=JSON.stringify([sessions.map(s=>[s.name,s.title,agentOf(s)]),others.map(d=>[d.id,d.sessions.map(s=>[s.name,s.title,agentOf(s)])]),waiting>0]);
  if(signature!==quickSignature){
    const left=box.scrollLeft;box.replaceChildren();quickButtons.clear();quickRemote.clear();
    // What waits for you comes first, under the thumb.
    if(waiting){
      const pill=el("button","quick-tab quick-inbox",svgIcon("inbox"),el("span","label",tr("Ждут ответа")),el("b","quick-count",String(waiting)));
      pill.type="button";pill.onclick=openInbox;box.append(pill);
    }
    for(const s of sessions){
      const button=el("button","quick-tab",el("span","dot"),agentIcon(s),el("span","label",sessionTitle(s)),el("span","bell"));
      button.type="button";button.setAttribute("aria-label",tr("Открыть сессию ")+sessionTitle(s));
      onLongPress(button,()=>{select(s.name);sheet(true)});
      button.addEventListener("click",e=>{if(button.dataset.longPress){delete button.dataset.longPress;e.preventDefault();return}select(s.name)});
      box.append(button);quickButtons.set(s.name,button);
    }
    for(const deck of others)for(const s of deck.sessions){
      const button=el("button","quick-tab quick-remote",el("span","dot "+state(s)),agentIcon(s),el("span","label",sessionTitle(s)),el("span","quick-machine",deck.name),el("span","bell"));
      button.type="button";button.title=deck.name+" · "+sessionTitle(s);
      button.onclick=()=>openDeckSession(deck.id,s.name);box.append(button);quickRemote.set(deck.id+"/"+s.name,{button,deck,s});
    }
    if(sessions.length){
      const add=el("button","quick-tab quick-new",svgIcon("plus"));add.type="button";
      add.setAttribute("aria-label",tr("Новая сессия"));add.onclick=openNew;box.append(add);
    }
    box.scrollLeft=left;quickSignature=signature;
  }
  box.classList.toggle("more-right",box.scrollLeft+box.clientWidth<box.scrollWidth-4);
  document.body.classList.toggle("has-quick-tabs",sessions.length>0);
  for(const s of sessions){
    const button=quickButtons.get(s.name);button.classList.toggle("on",s.name===active);
    button.setAttribute("aria-pressed",String(s.name===active));button.title=sessionTitle(s)+" · "+stateText(s);
    button.children[0].className="dot "+state(s);button.children[3].style.display=attention.has(s.name)?"":"none";
  }
  for(const [key,{button,deck,s:known}] of quickRemote){
    // The tab keeps the session from its last rebuild; states change without a rebuild.
    const s=others.find(d=>d.id===deck.id)?.sessions.find(x=>x.name===known.name)||known;
    button.children[0].className="dot "+state(s);button.children[4].style.display=otherAttention.has(key)?"":"none"}
  const count=box.querySelector(".quick-count");if(count)count.textContent=waiting;
  if(active!==quickActive&&isMobile()){
    const safelySelected=active,button=quickButtons.get(active);
    if(button)requestAnimationFrame(()=>{
      if(active!==safelySelected||!button.isConnected)return;
      const left=button.offsetLeft,right=left+button.offsetWidth;
      if(left<box.scrollLeft)box.scrollTo({left:Math.max(0,left-8),behavior:"smooth"});
      else if(right>box.scrollLeft+box.clientWidth)box.scrollTo({left:right-box.clientWidth+8,behavior:"smooth"});
    });
  }
  quickActive=active;
}
$("quick_tabs").addEventListener("scroll",e=>{const box=e.target;box.classList.toggle("more-right",box.scrollLeft+box.clientWidth<box.scrollWidth-4)},{passive:true});
// Session actions are under the thumb: long-press a quick tab instead of reaching for "⋯" at the top.
function onLongPress(node,run){
  let timer=null,start=null;
  const cancel=()=>{clearTimeout(timer);timer=null};
  node.addEventListener("pointerdown",e=>{
    if(e.pointerType==="mouse")return;
    start=[e.clientX,e.clientY];cancel();
    timer=setTimeout(()=>{timer=null;node.dataset.longPress="1";navigator.vibrate?.(10);run()},500);
  });
  node.addEventListener("pointermove",e=>{if(timer&&start&&Math.hypot(e.clientX-start[0],e.clientY-start[1])>10)cancel()});
  for(const type of ["pointerup","pointercancel","pointerleave"])node.addEventListener(type,cancel);
  node.addEventListener("contextmenu",e=>e.preventDefault());
}

// A pending question is the state that needs you most, so the list says so, not only the inbox count.
function waitingFor(deck,name){
  if((deck||"")===selectedDeck&&name===active&&question.data)return true;
  return inbox.questions.some(q=>(q.deck||"")===(deck||"")&&q.session===name);
}
function renderTabs(){
  renderQuickTabs();
  const q=$("q").value.trim().toLowerCase(),view=$("tabs"),box=document.createElement("div");
  // Built on every poll but swapped in only when it differs, so focus, hover tooltips and the
  // screen-reader position survive; on a swap, keyboard focus stays on the same session row.
  const was=view.contains(document.activeElement)?document.activeElement:null;
  const focused=was?.dataset.session?'[data-session="'+CSS.escape(was.dataset.session)+'"]':was?.dataset.deck?'[data-deck="'+CSS.escape(was.dataset.deck)+'"]':null;
  const list=sessions.filter(s=>matchesSessionQuery(s,q)),others=otherDecks.filter(d=>d.id!==selectedDeck);
  // Computers keep one order whichever is selected: switching only moves the highlight, never the rows.
  const order=deckOrder();
  if(order.length<2&&!others.length){renderCurrentSessions(box,list);finishTabs(view,box,focused);return}
  for(const id of order){
    if(id===selectedDeck){box.append(deckHeader({id,name:currentDeckName(),count:list.length},true));renderCurrentSessions(box,list);continue}
    const deck=others.find(d=>d.id===id);
    if(deck)renderDeckSection(box,deck,q);
    else if(!q)box.append(deckHeader({id,name:deckName(id),count:"…"},false));  // Its list has not arrived yet.
  }
  finishTabs(view,box,focused);
}
// This computer first, then connected ones in the order they were added; any list we know but the
// directory does not (yet) goes last.
function deckOrder(){
  const ids=["",...deckDirectory.decks.map(d=>d.id)];
  for(const d of otherDecks)if(!ids.includes(d.id))ids.push(d.id);
  if(!ids.includes(selectedDeck))ids.push(selectedDeck);
  return ids;
}
function deckName(id){return id?deckDirectory.decks.find(d=>d.id===id)?.name||"Agent Deck":deckDirectory.name||tr("Этот компьютер")}
function renderCurrentSessions(box,list){
  let grp=null,i=0;
  for(const s of list){
    if(s.group!==grp){grp=s.group;box.append(el("div","grp",grp))}
    i++;const st=state(s);
    const t=el("div","tab"+(s.name===active?" on":""));
    const dot=el("span","dot "+st);dot.title=stateText(s);
    // State is spelled out next to the path so it does not depend on the dot colour alone.
    const word=waitingFor(selectedDeck,s.name)?["ask",tr("ждёт ответа")]:attention.has(s.name)?["ready",tr("готово")]:st==="busy"?["busy",tr("работает")]:st==="off"?["off",tr("остановлен")]:null;
    const sub=el("div","s",...(word?[el("span","state "+word[0],word[1])," · "]:[]),shortPath(s.path));
    t.append(dot,agentIcon(s),el("div","t",el("div","n",sessionTitle(s)),...(isLocal(s)?[el("div","s session-source",agentLabel(s))]:[]),sub));
    t.title=isLocal(s)?s.source.model+" · "+localComputer(s):s.name;
    if(attention.has(s.name))t.append(el("span","bell"));
    else if(i<10)t.append(el("span","k",modKey()+i));
    t.dataset.session=s.name;t.onclick=()=>select(s.name);
    t.tabIndex=0;t.setAttribute("role","button");if(s.name===active)t.setAttribute("aria-current","true");
    t.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();select(s.name)}};
    box.append(t);
  }
  if(!sessions.length){
    const start=el("button","empty-new",svgIcon("plus"),el("span","",tr("Новая сессия")));start.type="button";start.onclick=openNew;
    box.append(el("div","empty-list",el("span","",tr("Сессий пока нет")),start));
  }
}
function finishTabs(view,box,focused){
  if(box.innerHTML!==view.innerHTML){
    view.replaceChildren(...box.childNodes);
    if(focused)view.querySelector(focused)?.focus({preventScroll:true});
  }
  const busy=sessions.filter(s=>state(s)==="busy").length;
  $("foot").textContent=tr("{0} сессий · {1} работают",[sessions.length,busy])+(attention.size?tr(" · {0} готово",[attention.size]):"");
  const ready=renderInboxBadge();
  $("menuBadge").textContent=ready;$("menuBadge").classList.toggle("on",ready>0);
  document.title=(ready?`(${ready}) `:"")+"Agent Deck";
  // Home-screen icon badge (iOS 16.4+ with notifications allowed, desktop PWAs); ignored elsewhere.
  try{if(navigator.setAppBadge)ready?navigator.setAppBadge(ready).catch(()=>{}):navigator.clearAppBadge().catch(()=>{})}catch(e){}
}
function renderTitle(){
  const s=cur(),t=$("title");t.replaceChildren();
  document.body.classList.toggle("is-shell",!!s&&agentOf(s)==="shell");
  document.body.classList.toggle("is-codex",!!s&&agentOf(s)==="codex");
  $("msg").placeholder=s?tr("Сообщение в ")+agentLabel(s)+"…":tr("Сообщение агенту…");
  $("bar_tools").hidden=!s;
  if(!s){t.textContent=isMobile()?"Agent Deck":"";return}
  const st=state(s);
  t.append(el("b","",sessionTitle(s)),el("span","path"," — "+s.path.replace(/^\/(?:home|Users)\/[^/]+/,"~")),el("span","st",stateText(s)+" · "+shortPath(s.path)+(s.source?.label?" · "+s.source.label:"")));
}

function frameFor(name){
  let f=frames.get(name);
  if(!f){
    f=document.createElement("iframe");f.src=activePath("/t/?arg="+encodeURIComponent("=cc-"+name));
    // Only the overlay reacts: a full show() would scroll the Screen view or move focus into the terminal.
    f.dataset.loading="1";f.addEventListener("load",()=>{delete f.dataset.loading;if(frames.get(active)===f&&curMode()==="term")$("term_loading").hidden=true},{once:true});
    f.onload=()=>{try{f.contentWindow.addEventListener("keydown",hotkeys,true);watchFileDrops(f.contentWindow);hookClipboard(f.contentWindow);attachDrawerSwipe(f.contentDocument,drawerSwipe)}catch(e){}};
    $("stage").append(f);frames.set(name,f);
  }
  return f;
}
function show(){
  const s=cur(),m=curMode();
  $("empty").style.display=s?"none":"grid";
  if(!s){$("empty_text").textContent=load.done?tr("Сессий пока нет"):tr("Загружаю сессии…");$("empty_new").hidden=!load.done}
  renderTitle();renderSendState();renderAttachments();renderQuestion();
  for(const[n,f]of frames){
    f.classList.toggle("on",!!s&&m==="term"&&n===active);
    const session=sessions.find(x=>x.name===n);f.inert=isLocal(session)&&!session.running;
  }
  placeSessionKeys({row:$("session_keys"),composer:$("session_composer"),screen:$("screen"),terminal:$("terminal_keys"),wrap:$("b_wrap"),reconnect:$("b_reconnect"),mode:m,active:!!s});
  $("screen").classList.toggle("on",!!s&&m==="screen");
  $("term_loading").hidden=!(s&&m==="term"&&frameFor(active).dataset.loading);
  if(s&&m==="term"){const f=frameFor(active);f.classList.add("on");f.inert=isLocal(s)&&!s.running;if(!isMobile()&&!isTouch()&&!f.inert&&document.activeElement!==$("msg"))setTimeout(()=>{try{f.contentWindow.focus();f.contentWindow.term&&f.contentWindow.term.focus()}catch(e){}},30)}
  if(s&&m==="screen")updateScreen(s,true);
  updateLink();fitKeys();
}
function reconnectTerminal(){
  if(!active)return;
  const frame=frames.get(active);
  if(frame)frame.remove();
  frames.delete(active);show();
}
// The view switch lives in the ⋯ menu; the bar keeps Files and History, which are used more often.
function toggleMode(){setMode(curMode()==="term"?"screen":"term")}
function setMode(m){mode=m;try{deckLocalStorage.setItem("cc.mode."+(isMobile()?"m":"d"),m)}catch(e){}show()}

let wrapPreview=true;
function applyWrap(){
  $("pre").classList.toggle("no-wrap",!wrapPreview);
  $("b_wrap").setAttribute("aria-pressed",String(wrapPreview));
}
function toggleWrap(){
  wrapPreview=!wrapPreview;
  try{deckLocalStorage.setItem("cc.wrap",wrapPreview?"1":"0")}catch(e){}
  applyWrap();
}

$("pre").addEventListener("scroll",()=>updateJump(false),{passive:true});
function activate(name){
  if(name===active)return;
  if(active)messageDrafts.set(active,$("msg").value);
  active=name;attention.delete(name);
  $("msg").value=messageDrafts.get(name)||"";$("msg").style.height="";
  $("msg").dispatchEvent(new Event("input"));
  try{if(name)deckLocalStorage.setItem("cc.active",name);else deckLocalStorage.removeItem("cc.active")}catch(e){}
  history.replaceState(null,"","#"+(name?encodeURIComponent(name):""));
  // Never leave the previous session's screen up while the new one loads: a known screen shows at
  // once, otherwise a skeleton until the first answer. The marker differs from any real screen.
  const p=$("pre");p.dataset.raw="\u0000";
  if(!previewCache.has(name))p.replaceChildren(screenSkeleton());
}
function select(name){
  if(!sessions.some(s=>s.name===name))return;
  if(name===active){drawer(false);return}
  activate(name);drawer(false);renderTabs();show();load();
}
function showClosedDrafts(){
  drawer(false);sheet(false);
  renderClosedDraftList({box:$("closed_drafts"),drafts:closedDrafts,copy:text=>copyToClipboard(text,window),remove:name=>{closedDrafts.delete(name);saveClosedDrafts();showClosedDrafts()},translate:tr});
  if(!$("draft_dlg").open)$("draft_dlg").showModal();
}
function saveClosedDrafts(){
  try{deckSessionStorage.setItem("cc.closed-drafts",JSON.stringify([...closedDrafts]))}catch(e){}
  $("s_drafts").style.display=closedDrafts.size?"flex":"none";
  $("b_drafts").style.display=closedDrafts.size?"block":"none";
}

let loadingSessions=null,sessionsQueued=false,queuedSessions=null;
const previewCache=new Map();
function load(){
  if(document.hidden)return Promise.resolve();
  // A caller arriving mid-request (e.g. right after a mutation) must wait for a list fetched after it.
  if(loadingSessions)return queuedSessions||(queuedSessions=loadingSessions.then(()=>{queuedSessions=null;return loadingSessions||load()}));
  const pending=loadSessions().finally(()=>{
    // A computer switch may have started a newer request; only the owner clears the guard.
    if(loadingSessions!==pending)return;
    loadingSessions=null;if(sessionsQueued){sessionsQueued=false;if(!queuedSessions)load()}
  });return loadingSessions=pending;
}
async function loadSessions(){
  const requested=active;
  try{
    const{sessions:list}=await api("/api/sessions"+(requested?"?preview="+encodeURIComponent(requested):""));
    if(!Array.isArray(list))throw new OfflineError(tr("Панель вернула неожиданный ответ"));
    setConnection("online");
    for(const s of list){
      if(s.preview!==undefined||s.preview_ansi!==undefined)previewCache.set(s.name,{preview:s.preview,preview_ansi:s.preview_ansi});
      else Object.assign(s,previewCache.get(s.name)||{});
    }
    for(const s of list){
      const busy=state(s)==="busy";
      if(wasBusy.get(s.name)&&!busy&&s.name!==active)attention.add(s.name);
      wasBusy.set(s.name,busy);
    }
    const names=new Set(list.map(s=>s.name));
    for(const[n,f]of frames)if(!names.has(n)){f.remove();frames.delete(n);attention.delete(n)}
    const first=!load.done,previousActive=active;load.done=true;
    sessions=list;
    for(const[n,f]of frames){const session=sessions.find(x=>x.name===n);f.inert=isLocal(session)&&!session.running}
    if(!active||!names.has(active)){
      activate(sessions.length?sessions.reduce((latest,s)=>Number(s.activity)>Number(latest.activity)?s:latest).name:null);
    }
    for(const[name,text]of messageDrafts)if(!names.has(name)){
      if(text)closedDrafts.set(name,text);messageDrafts.delete(name);previewCache.delete(name);
    }
    for(const[name,images]of imageAttachments)if(!names.has(name)){
      for(const image of images)if(image.preview)URL.revokeObjectURL(image.preview);imageAttachments.delete(name);sendStates.delete(name);
    }
    saveClosedDrafts();
    if(active!==requested)sessionsQueued=true;
    if(first&&!active&&isMobile())drawer(true);
    renderTabs();renderTitle();updateLink();
    const s=cur(),m=curMode();
    if(first||active!==previousActive||!s||(m==="term"&&!frames.has(active)))show();
    else if(m==="screen")updateScreen(s);
    loadQuestion();
  }catch(e){if(e.offline)setConnection("offline");else toast(e.message)}
}
let question={name:null,data:null,expanded:false,busy:null,textIndex:null},loadingQuestion=false;
async function loadQuestion(){
  const s=cur();
  if(!s||agentOf(s)==="shell"||!s.running){if(question.data)setQuestion(s?.name||null,null);return}
  if(loadingQuestion||question.busy!==null||document.hidden)return;
  loadingQuestion=true;const name=s.name;
  try{const data=await api("/api/question?name="+encodeURIComponent(name));if(active===name)setQuestion(name,data.question)}
  catch(e){/* Questions are an optional shortcut; the key row still works. */}
  finally{loadingQuestion=false}
}
function setQuestion(name,data){
  const same=question.name===name&&JSON.stringify(question.data)===JSON.stringify(data);
  if(same)return;
  const keepExpanded=question.name===name&&question.data?.id===data?.id;
  const saved=data?answerDraft(answerKey(name,data.id)):null;
  question={name,data,expanded:keepExpanded&&question.expanded,busy:null,
    textIndex:saved?saved.index:keepExpanded?question.textIndex:null,textDraft:saved?saved.text:keepExpanded?question.textDraft:""};
  renderQuestion();
}
const answerKey=(name,id)=>selectedDeck+"/"+name+"/"+id;
function saveQuestionDraft(){
  if(question.data)saveAnswerDraft(answerKey(question.name,question.data.id),{index:question.textIndex,text:question.textDraft});
}
function renderQuestion(){
  const data=question.name===active?question.data:null;
  // The card's own buttons answer; the 1/2/3 keys would only repeat them on a short screen.
  document.body.classList.toggle("has-question",Boolean(data));
  // Typing an answer must not be wiped by the 2.5 s refresh, so an open text field pauses re-rendering.
  if($("question").querySelector(".q-text textarea:focus"))return;
  renderQuestionCard({box:$("question"),question:data,expanded:question.expanded,busyIndex:question.busy,textIndex:question.textIndex,textDraft:question.textDraft||"",translate:tr,
    onTextInput:value=>{question.textDraft=value;saveQuestionDraft()},
    onToggle:()=>{question.expanded=!question.expanded;renderQuestion()},onAnswer:answerQuestion,
    // Focus inside the tap itself: iOS opens the keyboard only for a user gesture, and a
    // refocus on every refresh would pop the keyboard back after the user dismissed it.
    onTextOption:index=>{question.textIndex=question.textIndex===index?null:index;renderQuestion();$("question").querySelector(".q-text textarea")?.focus()},
    onSubmitText:(index,text)=>answerQuestion(index,text)});
}
async function answerQuestion(index,text){
  const name=active,data=question.data;
  if(!data||question.busy!==null||panelUpdating)return;
  question.busy=index;$("question").querySelector(".q-text textarea")?.blur();renderQuestion();
  try{
    await api("/api/answer",text===undefined?{name,id:data.id,index}:{name,id:data.id,index,text});
    saveAnswerDraft(answerKey(name,data.id),null);
    sendStates.set(name,{text:tr("Ответ отправлен: {0}",[text===undefined?data.options[index].label:text.slice(0,80)]),phase:"success"});
    question={name,data:null,expanded:false,busy:null,textIndex:null};
  }catch(e){toast(e.message);question.busy=null}
  renderQuestion();renderSendState();await load();loadQuestion();
}
async function post(path,body,ask){
  if(panelUpdating){toast(tr("Панель обновляется. Дождитесь завершения."));return false}
  if(ask&&!await confirmAction(ask.title,ask))return false;
  try{const result=await api(path,body);await load();return result}catch(e){toast(e.message);return false}
}
function openRename(){
  const s=cur();if(!s)return;
  $("session_title").value=sessionTitle(s);$("rename_dlg").dataset.session=s.name;
  $("rename_dlg").showModal();$("session_title").focus({preventScroll:true});
}
async function saveSessionTitle(){
  await saveSessionName({request:api,input:$("session_title"),button:$("rename_save"),dialog:$("rename_dlg"),refresh:load,notify:toast});
}
function restart(m){
  const s=cur();if(!s)return;const a=agentLabel(s);
  const title=m==="new"?tr("Перезапустить {0} в «{1}» с НОВЫМ разговором?",[a,sessionTitle(s)]):tr("Перезапустить {0} в «{1}», продолжив разговор?",[a,sessionTitle(s)]);
  post("/api/restart",{name:active,mode:m},{title,confirm:tr("Перезапустить")});
}
async function termHere(){
  const s=cur();if(!s)return;
  const names=new Set(sessions.map(x=>x.name));
  let base=s.name.replace(/-sh\d*$/,"").slice(0,27)+"-sh",n=base,i=2;
  while(names.has(n))n=base+(i++);
  const created=await post("/api/new",{name:n,agent:"shell",path:s.path});if(created)select(created.name||n);
}
async function kill(){
  const s=cur();if(!s)return;
  await post("/api/kill",{name:s.name},{title:tr("Закрыть сессию «{0}»? Агент будет остановлен.",[sessionTitle(s)]),confirm:tr("Закрыть сессию"),danger:true});
}
function popout(){if(active)window.open(activePath("/t/?arg="+encodeURIComponent("=cc-"+active)),"_blank")}
let uploading=false,choosingImages=false;
const imageAttachments=new Map();
const attachmentsFor=name=>imageAttachments.get(name)||[];
function renderAttachments(){
  const list=$("attachments");list.replaceChildren();
  for(const entry of attachmentsFor(active)){
    const chip=el("div","attachment");
    if(entry.preview){const img=document.createElement("img");img.src=entry.preview;img.alt="";chip.append(img)}
    chip.append(el("span","",entry.label));
    const remove=el("button","","×");remove.type="button";
    remove.setAttribute("aria-label",tr("Убрать ")+entry.label);remove.disabled=sending||uploading;
    remove.onclick=()=>{
      api("/api/discard_upload",{name:active,attachments:[entry.attachment]}).catch(e=>toast(e.message));
      imageAttachments.set(active,attachmentsFor(active).filter(x=>x!==entry));
      if(entry.preview)URL.revokeObjectURL(entry.preview);renderAttachments();
    };
    chip.append(remove);list.append(chip);
  }
  $("b_attach").disabled=!active||sending||uploading||panelUpdating;
  $("b_send").disabled=sending||uploading||panelUpdating;
}
// XHR instead of fetch: large phone videos take minutes and need visible progress.
// The file goes as a raw body: a phone never holds a base64 copy of a large video in memory.
function uploadRequest(path,contentType,payload,progress){
  return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest();xhr.open("POST",activePath(path));xhr.setRequestHeader("Content-Type",contentType);
    xhr.upload.onprogress=e=>{if(e.lengthComputable)progress(Math.round(e.loaded/e.total*100))};
    xhr.onerror=()=>reject(new Error(tr("Не удалось загрузить файл: нет соединения")));
    xhr.onload=()=>{
      if(xhr.status===401){try{stashDrafts()}catch(e){}location.href="/login";return reject(new Error("login required"))}
      let data={};try{data=JSON.parse(xhr.responseText)}catch(e){data={error:xhr.statusText}}
      if(xhr.status>=200&&xhr.status<300)resolve(data);
      else{const error=new Error(data.error||xhr.statusText);error.status=xhr.status;reject(error)}
    };
    xhr.send(payload);
  });
}
async function uploadFile(name,file,image,progress){
  const query="?name="+encodeURIComponent(name)+"&filename="+encodeURIComponent(file.name||"file");
  try{return await uploadRequest("/api/upload_raw"+query,"application/octet-stream",image,progress)}
  catch(error){
    if(error.status!==404)throw error;
    // A connected Agent Deck older than 1.9 only knows the JSON upload.
    return uploadRequest("/api/upload","application/json",JSON.stringify({name,data:await readImageData(image),filename:file.name||"file"}),progress);
  }
}
function chooseImages(){
  if(!active||sending||uploading||panelUpdating)return;
  choosingImages=true;
  $("image_files").click();
}
function readImageData(file){
  return new Promise((resolve,reject)=>{
    const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(",")[1]);
    reader.onerror=()=>reject(new Error(tr("Не удалось прочитать файл")));reader.readAsDataURL(file);
  });
}
async function prepareImage(file){
  if(["image/png","image/jpeg","image/webp","image/gif"].includes(file.type))return file;
  // Safari can decode some photo formats that the terminal agents do not accept.
  const url=URL.createObjectURL(file),img=new Image();
  try{
    await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(new Error(tr("Выберите PNG или JPEG: этот формат не удалось открыть")));img.src=url});
    const scale=Math.min(1,4096/Math.max(img.naturalWidth,img.naturalHeight));
    const canvas=document.createElement("canvas");canvas.width=Math.max(1,Math.round(img.naturalWidth*scale));canvas.height=Math.max(1,Math.round(img.naturalHeight*scale));
    const ctx=canvas.getContext("2d");ctx.fillStyle="#fff";ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(img,0,0,canvas.width,canvas.height);
    return await new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error(tr("Не удалось подготовить изображение"))),"image/jpeg",0.9));
  }finally{URL.revokeObjectURL(url)}
}
async function uploadImages(files){
  if(!active||sending||uploading||panelUpdating||!files.length)return;
  const name=active;
  if(agentOf(cur())==="shell"){toast(tr("Выберите сессию Claude или Codex"));return}
  if(attachmentsFor(name).length+files.length>4){toast(tr("Можно приложить до 4 файлов"));return}
  uploading=true;renderAttachments();
  sendStates.set(name,{text:tr("Загружаю файлы…"),phase:"pending"});renderSendState();
  let failed=false;
  for(const file of files){
    try{
      const isImage=file.type.startsWith("image/");
      const limit=200*1024*1024;
      if(file.size>limit)throw new Error(tr("Файл слишком большой: максимум 200 МБ"));
      let image=file;
      if(["image/heic","image/heif"].includes(file.type)){try{image=await prepareImage(file)}catch(e){image=file}}
      const result=await uploadFile(name,file,image,percent=>{
        sendStates.set(name,{text:tr("Загружаю файлы…")+" "+percent+"%",phase:"pending"});if(active===name)renderSendState();
      });
      imageAttachments.set(name,[...attachmentsFor(name),{attachment:result.attachment,label:file.name||tr("Файл"),preview:result.kind==="image"||(result.kind===undefined&&isImage)?URL.createObjectURL(image):null}]);
    }catch(e){failed=true;toast(e.message);sendStates.set(name,{text:tr("Не удалось приложить: ")+e.message,error:true})}
  }
  uploading=false;
  if(!failed)sendStates.set(name,{text:tr("Файлы приложены · нажмите ↑ для отправки"),phase:"success"});
  renderAttachments();renderSendState();
}
$("image_files").addEventListener("cancel",()=>{choosingImages=false});
// Browsers without the cancel event only report that the picker closed via focus/visibility.
function settleImageChoice(){if(choosingImages)setTimeout(()=>{choosingImages=false},1000)}
addEventListener("focus",settleImageChoice);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)settleImageChoice()});
$("image_files").addEventListener("change",e=>{choosingImages=false;const files=Array.from(e.target.files||[]);e.target.value="";uploadImages(files)});
watchFileDrops(window);
$("msg").addEventListener("paste",e=>{
  const files=Array.from(e.clipboardData&&e.clipboardData.files||[]);
  if(files.length){e.preventDefault();uploadImages(files)}
});

let sending=false;
const sendStates=new Map();
function renderSendState(){
  const status=sendStates.get(active),d=$("send_state");
  const session=cur();
  if(isLocal(session)&&!session.running){d.textContent=agentLabel(session)+tr(" не запущен")}
  else if(isLocal(session)&&(!status||status.phase==="success")){
    const profile=lmData.profiles.find(p=>p.id===session.source.profile);
    if(profile){
      const metrics=localUsage({...profile,activity:(profile.activity||[]).filter(a=>!a.binding||a.binding===session.source.binding),performance:profile.measurements?.session?.[session.source.model]||profile.performance});
      d.replaceChildren(el("span","composer-model",shortModel(session.source.model)),metrics.querySelector(".local-live-line"));
    }else d.textContent=shortModel(session.source.model);
  }else{
    const line=session&&(!status||status.phase==="success")?sessionStatus(session):null;
    // The status is live for screen readers; re-rendering identical text every second would be re-announced.
    if(line){if(d.textContent!==line.textContent||d.firstElementChild?.title!==line.title)d.replaceChildren(line)}
    else d.textContent=status?status.text:(isMobile()?tr("Enter ↵ · ↑ отправить"):tr("Enter отправить · ⇧Enter ↵"));
  }
  d.classList.toggle("error",Boolean(status&&status.error));
  d.classList.toggle("pending",Boolean(status&&status.phase==="pending"));
  d.classList.toggle("success",Boolean(status&&status.phase==="success"));
}
async function send(){
  const t=$("msg");if(sending||uploading||panelUpdating||!active||(!t.value.trim()&&!attachmentsFor(active).length))return;
  if(isLocal(cur())&&!cur().running){sendStates.set(active,{text:agentLabel(cur())+tr(" не запущен"),error:true});renderSendState();return}
  const name=active,text=t.value,images=attachmentsFor(active).slice();
  sending=true;renderAttachments();
  sendStates.set(name,{text:tr("Отправляю…"),phase:"pending"});renderSendState();
  try{
    await api("/api/send",{name,text,attachments:images.map(x=>x.attachment)});
    imageAttachments.set(name,attachmentsFor(name).filter(x=>!images.includes(x)));
    for(const image of images)if(image.preview)URL.revokeObjectURL(image.preview);
    if(messageDrafts.get(name)===text)messageDrafts.delete(name);
    if(active===name&&t.value===text){t.value="";t.style.height=""}
    sendStates.set(name,{text:tr("Отправлено в ")+agentLabel(sessions.find(s=>s.name===name))+" · "+new Date().toLocaleTimeString(DATE_LOCALE,{hour:"2-digit",minute:"2-digit"}),phase:"success"});
    await load();
    if(active===name)$("pre").scrollTop=$("pre").scrollHeight;
  }catch(e){
    sendStates.set(name,{text:tr("Не отправлено: ")+e.message,error:true});
  }finally{
    sending=false;renderAttachments();renderSendState();
  }
}
$("session_keys").addEventListener("pointerdown",e=>{if(e.target.closest("button"))e.preventDefault()});
function key(k){if(active&&!sending&&!uploading&&!panelUpdating)post("/api/send",{name:active,key:k})}
async function logout(){
  try{stashDrafts()}catch(e){}
  try{await fetch("/logout",{method:"POST"})}catch(e){toast(tr("Нет связи с панелью"));return}
  location.href="/login";
}
function toggleKeys(){const expanded=$("keys").classList.toggle("expanded");$("b_keymore").setAttribute("aria-expanded",String(expanded));fitKeys()}
function fitKeys(){
  const box=$("keys"),more=$("b_keymore"),keys=[...box.children].filter(k=>k!==more);
  for(const k of keys)k.classList.remove("key-overflow");
  more.classList.remove("all-fit");
  if(!(isMobile()||isTouch())||box.classList.contains("expanded")||!box.clientWidth)return;
  if(box.scrollWidth<=box.clientWidth){more.classList.add("all-fit");return}
  // Hide from the end so the answer keys (↑ ↓ ⏎) stay reachable on the narrowest screens.
  for(const k of keys.reverse()){if(box.scrollWidth<=box.clientWidth)break;if(k.offsetParent)k.classList.add("key-overflow")}
}
if(window.ResizeObserver)new ResizeObserver(()=>fitKeys()).observe($("keys"));
function hideKeyboard(){
  const focused=document.activeElement;
  if(focused&&typeof focused.blur==="function")focused.blur();
  document.body.classList.remove("message-focused");
  requestAnimationFrame(fitViewport);
}
$("msg").addEventListener("focus",()=>document.body.classList.add("message-focused"));
$("msg").addEventListener("blur",()=>document.body.classList.remove("message-focused"));

$("msg").addEventListener("input",e=>{if(active)messageDrafts.set(active,e.target.value);e.target.style.height="";e.target.style.height=Math.min(e.target.scrollHeight,160)+"px"});
$("msg").addEventListener("keydown",e=>{
  if(e.key==="Enter"&&!e.shiftKey&&(isMobile()?false:true)&&!e.isComposing){e.preventDefault();send()}
  else if(e.key==="Enter"&&(e.metaKey||e.ctrlKey)){e.preventDefault();send()}
});
$("q").addEventListener("input",renderTabs);
$("search_form").addEventListener("submit",e=>{e.preventDefault();runOutputSearch()});
$("palette_q").addEventListener("input",filterPalette);
$("palette_q").addEventListener("keydown",paletteKey);
// A click on the backdrop (outside the box) closes the switcher, as Escape does.
$("palette_dlg").addEventListener("click",e=>{if(e.target===$("palette_dlg"))$("palette_dlg").close()});

/* ---------- GitHub ---------- */
const GH_ICON='<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>';
let repos=[],ghLogin=null;
async function ghStatus(){try{const st=await api("/api/github/status");ghLogin=st.connected?st.login:null}catch(e){ghLogin=null}return ghLogin}
async function ghConnect(){if(await post("/api/github_login",{})){if($("dlg").open)$("dlg").close();select("github-login");setMode("screen")}}
function btn(label,cls,fn,title){const b=el("button",cls||"",label);b.onclick=fn;if(title)b.title=title;return b}
let lastGh=0,lastAg={},usageData={};
async function checkGithubFoot(force){
  if(document.hidden)return;
  try{lastAg=await api("/api/agents")}catch(e){}
  if(force===true||Date.now()-lastGh>30000||sessions.some(s=>s.name==="github-login")){await ghStatus();lastGh=Date.now()}
  renderInteg();
}
async function loadUsage(){if(document.hidden)return;try{usageData=await api("/api/usage")}catch(e){}renderInteg()}

function fmtReset(ts){
  if(!ts)return"";
  const ms=ts*1000-Date.now();if(ms<=0)return tr("сбрасывается…");
  const m=Math.round(ms/60000),d=new Date(ts*1000);
  const rel=m<60?tr("{0} мин",[m]):m<1440?tr("{0} ч {1} мин",[Math.floor(m/60),m%60]):tr("{0} д {1} ч",[Math.floor(m/1440),Math.floor(m%1440/60)]);
  const hm=d.toLocaleTimeString(DATE_LOCALE,{hour:"2-digit",minute:"2-digit"});
  const abs=m<1440&&d.getDate()===new Date().getDate()?hm:d.toLocaleDateString(DATE_LOCALE,{weekday:"short",day:"numeric",month:"short"})+" "+hm;
  return tr("сброс через {0} · {1}",[rel,abs]);
}
function compactReset(ts){
  if(!ts)return "↻ —";
  const minutes=Math.max(0,Math.round((ts*1000-Date.now())/60000)),days=Math.floor(minutes/1440),hours=Math.floor(minutes%1440/60);
  const duration=days?tr("{0}д {1}ч",[days,hours]):hours?tr("{0}ч {1}м",[hours,minutes%60]):tr("{0}м",[minutes]);
  return "↻ "+duration;
}
// labelled: outside the sidebar (which has "Left / Plan" headings) the plan value says what it is.
function quotaValues(w,labelled=false){
  const percent=Number.isFinite(w?.percent)?Math.round(Math.max(0,Math.min(100,100-w.percent))):null,plan=plannedRemaining(w,now());
  const remaining=el("span","quota-percent "+quotaTone(percent,plan),percent===null?"—":percent+"%");remaining.title=tr("Остаток");
  const target=el("span","quota-plan",plan===null?"—":labelled?tr("план {0}%",[plan]):plan+"%");target.title=tr("По плану к концу дня");
  target.setAttribute("aria-label",target.title+": "+target.textContent);
  return el("span","quota-values",remaining,target);
}
const QUOTA_OF={claude:"claude",codex:"codex","claude-kimi":"kimi",kimi:"kimi"};
// Mobile hides the sidebar quotas, so the composer shows what runs here and how much quota is left.
function sessionStatus(session){
  const agent=agentOf(session),quota=QUOTA_OF[agent];
  if(!quota||!session.running)return null;
  const model=session.source?.model||session.model,w=primaryQuota(usageData[quota]);
  const line=el("span","session-status",el("span","composer-model",AGENTS[agent].label+(model?" · "+shortModel(model):"")));
  line.title=AGENTS[agent].label+(model?" · "+model:"")+(w?" · "+tr("Остаток")+" / "+tr("По плану к концу дня")+" · "+fmtReset(w.resets_at):"");
  if(w)line.append(quotaValues(w,true),el("span","quota-reset",compactReset(w.resets_at)));
  return line;
}
let quotaHelpOpen=false,hubSignature="";
function renderInteg(){
  const summary=el("summary","",el("span","",tr("Остаток")),el("span","quota-heading-plan",tr("План")));
  const gh=el("span","quota-github");gh.innerHTML=GH_ICON;gh.title=ghLogin?"GitHub · "+ghLogin:tr("GitHub не подключён");gh.append(el("span",ghLogin?"good":"dim",ghLogin?"✓":"—"));summary.append(gh);
  summary.setAttribute("aria-label",tr("Что означают лимиты"));
  // Phones have no hover, so the explanation and exact reset times open on tap instead of living in title.
  const help=el("div","quota-help",el("div","",tr("Остаток — сколько лимита осталось. План — сколько должно остаться к концу дня при равномерном расходе.")));
  const head=el("details","quota-heading",summary,help);head.open=quotaHelpOpen;
  head.addEventListener("toggle",()=>{quotaHelpOpen=head.open});
  const rows=[head];
  for(const a of ["claude","codex","kimi"]){
    const u=usageData[a],w=primaryQuota(u),row=el("div","quota-strip",agentIcon({agent:a}));
    row.title=AGENTS[a].label+" · "+(w?tr(w.label||"")+" · "+fmtReset(w.resets_at):u?.error||tr("Нет данных"))+(u?.stale?" · "+tr("⚠ данные устарели"):"");
    row.setAttribute("aria-label",row.title);
    row.append(quotaValues(w),el("span","quota-reset",w?compactReset(w.resets_at):"—"));
    // A row of dashes says nothing; why there is no data stays in the explanation below.
    if(w)rows.push(row);
    if(w||u?.error)help.append(el("div","",row.title));
  }
  for(const p of lmData.profiles||[])rows.push(localUsage(p));
  // Rebuilding identical nodes every second drops hover, focus and screen-reader position.
  const next=el("div","",...rows);
  if(next.innerHTML!==$("integ").innerHTML)$("integ").replaceChildren(...next.childNodes);
  renderSendState();
  const signature=JSON.stringify([lastAg,ghLogin,telegramConfig,lmData.profiles,panelVersion]);
  if($("settings_dlg").open&&signature!==hubSignature&&!$("settings_dlg").contains(document.activeElement)){hubSignature=signature;renderHub()}
}
const openLocalModels=new Set(); // renderInteg rebuilds every second; keep user-opened rows open.
function localUsage(profile){
  const activity=profile.activity||[],live=activity[0],sample=profile.performance||{};
  const model=live?.model||sample.model||profile.models?.find(m=>m.loaded)?.id||profile.name;
  const box=el("div","local-usage compact-local");
  const labels={waiting:"Ожидание первого токена",thinking:"Модель рассуждает",tool:"Готовит вызов инструмента",generating:"Генерирует ответ"};
  const details=el("details","local-model"),summary=el("summary","",agentIcon({source:{kind:"lmstudio"}}),el("span","local-name",shortModel(model)));
  summary.title=model+" · "+profile.name;summary.setAttribute("aria-label",summary.title);
  details.open=openLocalModels.has(profile.id);
  details.addEventListener("toggle",()=>{if(details.open)openLocalModels.add(profile.id);else openLocalModels.delete(profile.id)});
  const full=el("div","",model);details.append(summary,full,el("p","",profile.name+" · "+(lmMetrics(sample)||tr("Нет замеров"))));box.append(details);
  const line=el("div","local-live-line");
  const seconds=Math.floor(live?.request_time_seconds||0),elapsed=Math.floor(seconds/60)+":"+String(seconds%60).padStart(2,"0");
  const state=el("span","local-state",live?(live.phase==="waiting"?"◌ TTFT "+elapsed:(live.phase==="tool"?"⚙ ":"✦ ")+elapsed+(live.chunks?" · "+live.chunks+" Δ":"")):"✓ "+(Number.isFinite(sample.output_tokens)?sample.output_tokens+" tok":"—"));
  state.title=live?tr(labels[live.phase]||labels.waiting):(lmMetrics(sample)||tr("Нет замеров"));
  if(live){box.setAttribute("aria-busy","true");state.classList.add("local-active")}
  line.append(state);
  const m=Number.isFinite(live?.tokens_per_second)?live:sample;
  const exact=Number.isFinite(m.tokens_per_second),average=!exact&&m.output_tokens>0&&m.request_time_seconds>0;
  const rate=exact?m.tokens_per_second:average?m.output_tokens/m.request_time_seconds:null;
  const speed=el("span","local-rate",rate===null?"— tok/s":(average?"≈":"")+rate.toFixed(1)+" tok/s"+(average?tr(" сред."):""));
  speed.title=(m===sample?tr("Последний ответ")+" · ":"")+(average?tr("Средняя скорость с учётом ожидания"):"tok/s");
  line.append(speed);box.append(line);
  return box;
}
hubInit();
async function saveProjectDirectory(){
  await saveDirectorySetting({request:api,input:$("project_directory"),button:$("project_directory_save"),notify:toast,translate:tr});
}
async function loadDeckSettings(){
  const [data,network]=await Promise.all([gatewayApi("/api/decks"),gatewayApi("/api/network")]);
  const current=data.decks.find(deck=>deck.id===selectedDeck);
  panelOrigins=current?[current.url,location.origin]:[location.origin,"http://"+network.bind_host+":"+network.bind_port,"http://127.0.0.1:"+network.bind_port,"http://localhost:"+network.bind_port];
  if(!current&&network.public_url)panelOrigins.push(network.public_url);
  populateDeckSelector($("deck_select"),data.decks,selectedDeck,network.name);
  // Most installs have a single machine; the switcher appears once another Agent Deck is connected.
  $("deck_switch").hidden=!data.decks.length&&!selectedDeck;
  deckDirectory={decks:data.decks,name:network.name,network};loadOtherDecks();
  if(Date.now()-fleet.loadedAt>10*60*1000||$("settings_dlg").open)loadFleet();else renderFleet();
  renderComputers(data,network);
  if(selectedDeck&&!data.decks.some(d=>d.id===selectedDeck))switchDeck("");
}
// Sessions of every connected machine, so switching environments is one tap from the sidebar.
let deckDirectory={decks:[],name:"",network:{}},otherDecks=[],loadingOthers=false,deckOpen={};
const otherBusy=new Map(),otherAttention=new Set();
try{deckOpen=JSON.parse(localStore.getItem("cc.deck-open")||"{}")||{}}catch(e){}
const currentDeckName=()=>selectedDeck?deckDirectory.decks.find(d=>d.id===selectedDeck)?.name||"Agent Deck":deckDirectory.name||tr("Этот компьютер");
async function loadOtherDecks(){
  if(document.hidden||loadingOthers||!deckDirectory.decks.length){if(!deckDirectory.decks.length&&otherDecks.length){otherDecks=[];renderTabs()}return}
  loadingOthers=true;const epoch=deckEpoch;
  const targets=[{id:"",name:deckDirectory.name||tr("Этот компьютер")},...deckDirectory.decks.map(d=>({id:d.id,name:d.name}))].filter(d=>d.id!==selectedDeck);
  try{
    const loaded=await Promise.all(targets.map(async d=>{
      // Lists come without previews: only names and states travel through the gateway.
      try{return {...d,sessions:(await api(instancePath(d.id,"/api/sessions"),null,true)).sessions}}
      catch(e){return {...d,sessions:[],error:true}}
    }));
    // Built for the computer we just left; switchDeck already placed it in the sidebar.
    if(epoch!==deckEpoch)return;
    otherDecks=loaded;
  }finally{loadingOthers=false}
  // Same "done" signal as local tabs: a session that stopped working since the last poll.
  for(const deck of otherDecks)for(const s of deck.sessions){
    const key=deck.id+"/"+s.name,busy=state(s)==="busy";
    if(otherBusy.get(key)&&!busy)otherAttention.add(key);
    otherBusy.set(key,busy);
  }
  renderTabs();
}
function deckHeader(deck,current){
  const key=deck.id||"local",open=current||deckOpen[key]!==false;
  const head=el(current?"div":"button","deck-head"+(current?" current":""),svgIcon("monitor"),el("span","deck-name",deck.name),
    el("span","deck-count",deck.error?tr("недоступен"):String(deck.count)));
  // A connected computer behind the latest release shows an arrow; Settings → Network updates it.
  if(!current&&fleet.versions.get(deck.id)?.update){const mark=el("span","deck-update","↑");mark.title=tr("Доступно обновление");head.append(mark)}
  if(!current){
    head.type="button";head.dataset.deck=key;head.setAttribute("aria-expanded",String(open));head.append(svgIcon(open?"chevron-down":"chevron-right"));
    head.onclick=()=>{deckOpen[key]=!open;try{localStore.setItem("cc.deck-open",JSON.stringify(deckOpen))}catch(e){}renderTabs()};
  }
  return head;
}
function renderDeckSection(box,deck,q){
  const list=deck.sessions.filter(s=>matchesSessionQuery(s,q));
  if(q&&!list.length)return;
  box.append(deckHeader({...deck,count:list.length},false));
  if(deckOpen[deck.id||"local"]===false)return;
  let grp=null;
  for(const s of list){
    // Project headings as on this computer, so a session reads the same wherever you look from.
    if(s.group&&s.group!==grp){grp=s.group;box.append(el("div","grp",grp))}
    const st=state(s),word=waitingFor(deck.id,s.name)?["ask",tr("ждёт ответа")]:st==="busy"?["busy",tr("работает")]:st==="off"?["off",tr("остановлен")]:null;
    const t=el("div","tab remote",el("span","dot "+st),agentIcon(s),el("div","t",el("div","n",sessionTitle(s)),
      el("div","s",...(word?[el("span","state "+word[0],word[1])," · "]:[]),shortPath(s.path))));
    if(otherAttention.has(deck.id+"/"+s.name))t.append(el("span","bell"));
    t.title=deck.name+" · "+s.name;t.tabIndex=0;t.setAttribute("role","button");
    t.onclick=()=>openDeckSession(deck.id,s.name);
    t.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();openDeckSession(deck.id,s.name)}};
    box.append(t);
  }
}
function openDeckSession(identity,name){
  otherAttention.delete(identity+"/"+name);
  try{instanceStorage(localStore,identity).setItem("cc.active",name)}catch(e){}
  switchDeck(identity);
}
setInterval(loadOtherDecks,10000);
function switchDeck(identity){
  if(identity===selectedDeck)return;
  if(sending||uploading||choosingImages||question.busy!==null){$("deck_select").value=selectedDeck;toast(tr("Дождитесь окончания отправки или загрузки"));return}
  try{stashDrafts();localStore.setItem("cc.deck",identity)}catch(e){$("deck_select").value=selectedDeck;toast(tr("Не удалось сохранить черновик. Очистите поле перед обновлением."));return}
  for(const dialog of document.querySelectorAll("dialog[open]"))dialog.close();
  drawer(false);sheet(false);hideToast();closeViewer();
  // The computer we leave stays in the sidebar right away; the one we enter shows its known list.
  const target=otherDecks.find(d=>d.id===identity&&!d.error);
  otherDecks=[...otherDecks.filter(d=>d.id!==identity),{id:selectedDeck,name:currentDeckName(),sessions:sessions.map(({preview,preview_ansi,...rest})=>rest)}];
  deckEpoch++;selectedDeck=identity;
  deckLocalStorage=instanceStorage(localStore,identity);deckSessionStorage=instanceStorage(sessionStore,identity);
  history.replaceState(null,"","#");
  const previousMode=curMode();
  resetInstanceState(target?target.sessions:[]);
  restoreInstance();
  if(mode===null)mode=previousMode;  // A computer without its own choice keeps the current view.
  renderTabs();show();
  load();checkGithubFoot(true);loadUsage();loadLM().then(renderInteg);showCachedServer();loadServer();loadVersion();loadMetrics();loadIntegrations();
  loadDeckSettings().catch(e=>{if(!e.offline)toast(e.message)});
}
// Everything below belongs to one computer; a switch must not carry any of it to the next.
function resetInstanceState(known){
  for(const key of [...otherAttention,...otherBusy.keys()])if(key.startsWith(selectedDeck+"/")){otherAttention.delete(key);otherBusy.delete(key)}
  for(const frame of frames.values())frame.remove();
  frames.clear();wasBusy.clear();attention.clear();previewCache.clear();sendStates.clear();
  sessions=known;quickSignature=null;quickActive=null;
  question={name:null,data:null,expanded:false,busy:null,textIndex:null};loadingQuestion=false;
  loadingSessions=null;queuedSessions=null;sessionsQueued=false;load.done=false;
  lastAg={};usageData={};ghLogin=null;lastGh=0;repos=[];
  lmData={profiles:[],discovery:{}};lmRefreshPending=null;openLocalModels.clear();
  telegramConfig={};panelVersion=null;UI_PANEL_VERSION=null;panelUpdating=false;hubSignature="";
  $("pre").dataset.raw="";$("pre").replaceChildren();$("ver").replaceChildren();
  $("metric_cpu").textContent=$("metric_ram").textContent="—";
}
function renderSources(){
  const old=$("n_source").value;$("source_row").hidden=!["claude","kimi","pi"].includes(newAgent);
  const values=[];if(newAgent==="claude")values.push([{kind:"default"},"Claude"]);
  if(lastAg.kimi_config?.configured&&["claude","kimi"].includes(newAgent))for(const m of ["k3","kimi-for-coding","kimi-for-coding-highspeed"])values.push([{kind:"kimi",model:m},"Kimi · "+m]);
  if(["claude","pi"].includes(newAgent))for(const p of lmData.profiles||[])for(const m of p.models||[])values.push([{kind:"lmstudio",profile:p.id,model:m.id},p.name+" · "+m.name]);
  $("n_source").replaceChildren(...values.map(([v,label])=>{const o=el("option","",label);o.value=JSON.stringify(v);return o}));if([...$("n_source").options].some(o=>o.value===old))$("n_source").value=old;else if(newAgent==="kimi"&&lastAg.kimi_config?.model)$("n_source").value=JSON.stringify({kind:"kimi",model:lastAg.kimi_config.model});
}
function saveLanguage(){
  if(sending||uploading||choosingImages){toast(tr("Дождитесь окончания отправки или загрузки"));return}
  try{stashDrafts()}catch(e){toast(tr("Не удалось сохранить черновик. Очистите поле перед обновлением."));return}
  document.cookie="cc_lang="+encodeURIComponent($("ui_language").value)+"; Path=/; Max-Age=31536000; SameSite=Lax"+(location.protocol==="https:"?"; Secure":"");
  location.reload();
}
// Off by default: iOS smart punctuation turns -- into an em dash and straightens nothing back.
function applyAutocorrect(){
  let on=false;try{on=localStore.getItem("cc.autocorrect")==="1"}catch(e){}
  const msg=$("msg");msg.setAttribute("autocorrect",on?"on":"off");msg.setAttribute("autocapitalize",on?"sentences":"none");msg.spellcheck=on;
  $("autocorrect_enabled").checked=on;
}
function saveAutocorrect(){try{localStore.setItem("cc.autocorrect",$("autocorrect_enabled").checked?"1":"0")}catch(e){}applyAutocorrect()}
applyAutocorrect();
let UI_PANEL_VERSION=null;
async function loadVersion(){
  if(versionLoading===deckEpoch)return;clearTimeout(versionTimer);
  if(document.hidden){versionTimer=setTimeout(loadVersion,60000);return}
  const epoch=versionLoading=deckEpoch;
  try{
    const v=await api("/api/version");if(UI_PANEL_VERSION===null)UI_PANEL_VERSION=v.version;
    renderVersion(v);
  }catch(e){/* The panel is briefly unreachable while its service restarts. */}
  finally{if(versionLoading===epoch)versionLoading=null;versionTimer=setTimeout(loadVersion,panelUpdating?2000:60000)}
}
async function startPanelUpdate(){
  if(panelUpdating||!panelVersion||!panelVersion.can_update)return;
  if(sending||uploading||choosingImages){toast(tr("Дождитесь окончания отправки или загрузки"));return}
  sheet(false);
  renderVersion({...panelVersion,job:{phase:"checking",message:tr("Запускаю обновление…")}});
  try{
    const result=await api("/api/update",{});renderVersion({...panelVersion,job:result.job});
  }catch(e){renderVersion({...panelVersion,job:{phase:"error",message:e.message}});toast(e.message)}
  clearTimeout(versionTimer);versionTimer=setTimeout(loadVersion,1000);
}
function updatePanel(){
  if(panelVersion&&panelVersion.job&&panelVersion.job.phase==="done"&&panelVersion.job.version===panelVersion.version&&UI_PANEL_VERSION!==null&&panelVersion.job.version!==UI_PANEL_VERSION)refreshInterface();
  else startPanelUpdate();
}
// The address line never empties: the last known one for this computer shows at once (cached in this
// browser), a skeleton only the very first time, and the fresh answer replaces it in place.
function renderServer(s){
  const box=$("srv"),cc=(s.country||"").toUpperCase();box.replaceChildren();
  if(/^[A-Z]{2}$/.test(cc))box.append(el("span","fl",String.fromCodePoint(...[...cc].map(c=>0x1F1A5+c.charCodeAt(0)))));
  box.append(el("span","ip",s.ip||s.tailscale_ip||"—"),...(s.hostname?[el("span","hn","· "+s.hostname)]:[]));
  box.title=[s.city&&`${s.city}, ${cc}`,s.org,s.tailscale_ip&&`Tailscale: ${s.tailscale_ip}`].filter(Boolean).join("\n");
}
function showCachedServer(){
  let cached=null;try{cached=JSON.parse(deckLocalStorage.getItem("cc.server")||"null")}catch(e){}
  if(cached&&typeof cached==="object")renderServer(cached);
  else $("srv").replaceChildren(el("span","sk-line srv-skeleton"));
}
async function loadServer(){
  const epoch=deckEpoch;
  try{
    const s=await api("/api/server");if(epoch!==deckEpoch)return;
    const keep={country:s.country,ip:s.ip,tailscale_ip:s.tailscale_ip,hostname:s.hostname,city:s.city,org:s.org};
    renderServer(keep);try{deckLocalStorage.setItem("cc.server",JSON.stringify(keep))}catch(e){}
  }catch(e){if(e.message!==STALE&&$("srv").querySelector(".srv-skeleton"))renderServer({})}
}
async function loadGithub(){
  const body=$("gh_body");body.replaceChildren();$("gh_refresh").style.display="none";$("gh_state").textContent=tr("GitHub: проверяю…");
  await ghStatus();
  if(!ghLogin){
    $("gh_state").textContent=tr("GitHub не подключён");
    const b=el("button","ghbtn",tr("Подключить GitHub"));b.type="button";b.onclick=ghConnect;body.append(b);return;
  }
  $("gh_state").textContent="GitHub: "+ghLogin;$("gh_refresh").style.display="";
  const q=document.createElement("input");q.type="text";q.id="gh_q";q.className="search";q.placeholder=tr("Поиск репозитория…");q.autocomplete="off";q.setAttribute("autocapitalize","off");
  q.oninput=renderRepos;const list=el("div","");list.id="gh_list";body.append(q,list);
  loadRepos(false);
}
async function loadRepos(refresh){
  const list=$("gh_list");if(!list)return;list.textContent=tr("Загружаю…");
  try{repos=(await api("/api/github/repos"+(refresh?"?refresh=1":""),null,false,{timeout:90000})).repos;renderRepos()}catch(e){if(e.message!==STALE)list.textContent=e.message}
}
function renderRepos(){
  const list=$("gh_list"),q=($("gh_q").value||"").toLowerCase();list.replaceChildren();
  const sel=$("n_git").value;
  for(const r of repos.filter(r=>!q||(r.full_name+" "+r.description).toLowerCase().includes(q)).slice(0,100)){
    const url="https://github.com/"+r.full_name+".git";
    const row=el("button","repo"+(sel===url?" sel":""),el("span","rn",r.full_name));row.type="button";
    if(r.private){const lock=el("span","lock",svgIcon("lock"));lock.title=tr("Приватный");row.append(lock)}
    row.append(el("span","rm",(r.pushed_at||"").slice(0,10)));
    row.title=r.description||"";row.onclick=()=>pickRepo(r);list.append(row);
  }
  if(!list.children.length)list.textContent=tr("Ничего не найдено");
}
function pickRepo(r){
  const repo=r.full_name.split("/")[1];
  $("n_git").value="https://github.com/"+r.full_name+".git";$("n_proj").value=repo;renderAdvanced();
  if(!$("n_name").value||$("n_name").dataset.auto){$("n_name").value=repo.replace(/[^A-Za-z0-9_-]/g,"-").slice(0,32);$("n_name").dataset.auto="1"}
  renderRepos();
}
$("n_name").addEventListener("input",e=>delete e.target.dataset.auto);

let newAgent="claude";
function pickAgent(a){
  newAgent=a;for(const b of $("agsel").children)b.classList.toggle("on",b.dataset.a===a);
  $("n_skip_row").style.display=["shell","pi"].includes(a)?"none":"";
  if(!["shell","pi"].includes(a))$("n_skip_flag").textContent=AGENTS[a].skip;renderSources();
}
async function openNew(){
  returnToNew=false;if($("settings_dlg").open)$("settings_dlg").close();drawer(false);
  try{const{projects}=await api("/api/projects");$("projlist").replaceChildren(...projects.map(p=>{const o=document.createElement("option");o.value=p;return o}))}catch(e){}
  $("dlg").showModal();loadGithub();await refreshLMModels();renderSources();
}
async function createSession(){
  const name=$("n_name").value.trim();$("n_go").disabled=true;$("n_go").textContent=tr("Создаю…");
  const ok=await post("/api/new",{name,project:$("n_proj").value.trim()||name,git:$("n_git").value.trim(),
    worktree:$("n_wt").checked,branch:$("n_branch").value.trim(),skip:$("n_skip").checked,agent:newAgent,source:["claude","kimi","pi"].includes(newAgent)&&$("n_source").value?JSON.parse($("n_source").value):undefined});
  $("n_go").disabled=false;$("n_go").textContent=tr("Создать");
  if(ok){$("dlg").close();for(const i of["n_name","n_proj","n_git","n_branch"])$(i).value="";$("n_wt").checked=false;$("n_adv").open=false;renderAdvanced();select(ok.name||name)}
}
function renderAdvanced(){
  $("n_branch_row").hidden=!$("n_wt").checked;
  const git=$("n_git").value.trim().replace(/^https:\/\/github\.com\//,"").replace(/\.git$/,"");
  $("n_adv_hint").textContent=[git,$("n_wt").checked?"worktree":""].filter(Boolean).join(" · ");
}
$("n_git").addEventListener("input",renderAdvanced);

/* ⌥1..9 — табы, ⌥↑/⌥↓ — пред./след., ⌥T — новая, ⌥K — быстрый переход (работает и внутри терминала) */
function hotkeys(e){
  if(!e.altKey&&!e.ctrlKey&&!e.metaKey&&answerByDigit(e))return;
  // Ctrl+K is kill-line in a shell (and in Mac text fields), so inside the terminal only Alt+K opens the
  // switcher, and a Mac uses Cmd+K.
  const commandKey=/Mac|iPhone|iPad/.test(navigator.platform||"")?e.metaKey&&!e.ctrlKey:e.ctrlKey&&!e.metaKey;
  if(commandKey&&!e.altKey&&!e.shiftKey&&e.code==="KeyK"&&e.target?.ownerDocument===document){e.preventDefault();e.stopPropagation();openPalette();return}
  if(!e.altKey||e.ctrlKey||e.metaKey)return;
  const vis=[...$("tabs").querySelectorAll(".tab:not(.remote)")].map(t=>t.dataset.session);
  let target=null;
  if(/^Digit[1-9]$/.test(e.code)&&!e.shiftKey){
    // Non-US Mac layouts type [ ] { } | etc. with Option+digit; keep those characters.
    if(/^[!-\/:-@\[-`{-~]$/.test(e.key))return;
    target=vis[+e.code.slice(5)-1];
  }
  else if(e.code==="ArrowUp"||e.code==="ArrowDown"){const i=vis.indexOf(active);target=vis[(i+(e.code==="ArrowUp"?-1:1)+vis.length)%vis.length]}
  else if(e.code==="KeyT"){e.preventDefault();e.stopPropagation();openNew();return}
  else if(e.code==="KeyK"){e.preventDefault();e.stopPropagation();openPalette();return}
  else return;
  e.preventDefault();e.stopPropagation();if(target)select(target);
}
// The numbers on a question card's options answer it, as they would in the terminal, unless you are typing.
function answerByDigit(e){
  const data=question.name===active?question.data:null,target=e.target;
  if(!data||!/^Digit[1-9]$/.test(e.code)||question.busy!==null||document.querySelector("dialog[open]"))return false;
  if(target&&(target.closest?.("input,textarea,select,[contenteditable]")||target.tagName==="IFRAME"))return false;
  const index=+e.code.slice(5)-1,option=data.options[index];
  if(!option||option.text)return false;
  e.preventDefault();e.stopPropagation();answerQuestion(index);return true;
}
addEventListener("keydown",hotkeys,true);
// Wide layouts can fold the sidebar away for more room; remembered in this browser.
function toggleSidebar(){
  const on=!document.body.classList.contains("side-collapsed");
  document.body.classList.toggle("side-collapsed",on);
  try{localStore.setItem("cc.side-collapsed",on?"1":"")}catch(e){}
}
try{if(localStore.getItem("cc.side-collapsed"))document.body.classList.add("side-collapsed")}catch(e){}
// A notification fallback (or a pasted link) can change only the #session part of the address.
addEventListener("hashchange",()=>{
  let name="";try{name=decodeURIComponent(location.hash.slice(1))}catch(e){}
  if(name&&name!==active)select(name);
});
let lastMobile=isMobile();
addEventListener("resize",()=>{
  if(isMobile()!==lastMobile){
    lastMobile=isMobile();
    // Folding, unfolding or rotating switches layouts: an open drawer or menu would be left behind.
    drawer(false);sheet(false);
    try{mode=deckLocalStorage.getItem("cc.mode."+(lastMobile?"m":"d"))}catch(e){mode=null}
    show();
  }
  fitViewport();fitKeys();
});

/* Update installed home-screen pages too, without interrupting input. */
let checkingVersion=false;
function stashDrafts(){
  if(active)messageDrafts.set(active,$("msg").value);
  deckSessionStorage.setItem("cc.closed-drafts",JSON.stringify([...closedDrafts]));
  deckSessionStorage.setItem("cc.session-drafts",JSON.stringify([...messageDrafts]));deckSessionStorage.setItem("cc.reload-images",JSON.stringify([...imageAttachments].map(([name,images])=>[name,images.map(x=>({attachment:x.attachment,label:x.label}))])));deckSessionStorage.setItem("cc.reload-draft",JSON.stringify({name:active,text:$("msg").value}));
}
function refreshInterface(){
  if(sending||uploading||choosingImages){toast(tr("Дождитесь окончания отправки или загрузки"));return}
  try{stashDrafts()}catch(e){
    if($("msg").value||attachmentsFor(active).length){toast(tr("Не удалось сохранить черновик. Очистите поле перед обновлением."));return}
  }
  location.reload();
}
function canAutoRefresh(){
  return !document.hidden&&!panelUpdating&&!sending&&!uploading&&!choosingImages&&!Array.from(imageAttachments.values()).some(images=>images.length)&&!Array.from(messageDrafts.values()).some(Boolean)&&!$("msg").value&&!$("dlg").open&&!$("draft_dlg").open&&!$("settings_dlg").open&&!$("rename_dlg").open&&
    !$("sheet").classList.contains("on")&&!document.body.classList.contains("drawer")&&
    (!cur()||(curMode()==="screen"&&$("pre").scrollTop+$("pre").clientHeight>=$("pre").scrollHeight-40))&&
    !String(window.getSelection())&&
    !["INPUT","TEXTAREA"].includes(document.activeElement&&document.activeElement.tagName);
}
async function checkInterfaceVersion(){
  if(checkingVersion||document.hidden)return;
  checkingVersion=true;
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
  try{
    const response=await fetch("/api/ui-version",{cache:"no-store",signal:controller.signal});
    if(!response.ok)return;
    const data=await response.json();
    if(typeof data.revision==="string"&&data.revision!==UI_REVISION&&canAutoRefresh())refreshInterface();
  }catch(e){/* A temporary disconnect should leave the current interface usable. */}
  finally{clearTimeout(timeout);checkingVersion=false}
}
// Manual reloads and iOS page eviction skip the explicit stash paths.
addEventListener("pagehide",()=>{try{stashDrafts()}catch(e){}});
setInterval(checkInterfaceVersion,30000);
checkInterfaceVersion();

let loadingMetrics=false;
async function loadMetrics(){
  if(document.hidden||loadingMetrics)return;
  loadingMetrics=true;
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);
  const node=$("server_metrics");
  function render(cpu,ram,detail=""){
    $("metric_cpu").textContent=cpu;$("metric_ram").textContent=ram;
    node.title="CPU: "+cpu+" · RAM: "+ram+detail;
    node.setAttribute("aria-label",node.title);
  }
  try{
    const epoch=deckEpoch,response=await fetch(activePath("/api/server-metrics"),{cache:"no-store",signal:controller.signal});
    if(!response.ok)throw new Error("metrics unavailable");
    const data=await response.json();
    if(epoch!==deckEpoch)return;
    const cpu=Number.isFinite(data.cpu_percent)?Math.round(data.cpu_percent)+"%":"—";
    const hasMemory=Number.isFinite(data.memory_used)&&Number.isFinite(data.memory_total)&&data.memory_total>0;
    const ram=hasMemory?Math.round(data.memory_used/data.memory_total*100)+"%":"—";
    const detail=hasMemory?" ("+(data.memory_used/1073741824).toFixed(1)+" / "+(data.memory_total/1073741824).toFixed(1)+tr(" ГиБ)"):"";
    render(cpu,ram,detail);
  }catch(e){render("—","—")}
  finally{clearTimeout(timeout);loadingMetrics=false}
}
/* Per-computer browser state: the same code runs on page load and on a computer switch. */
function restoreInstance(){
  active=null;mode=null;$("msg").value="";
  try{active=deckLocalStorage.getItem("cc.active");mode=deckLocalStorage.getItem("cc.mode."+(isMobile()?"m":"d"))}catch(e){}
  if(location.hash.length>1)try{active=decodeURIComponent(location.hash.slice(1))}catch(e){}
  try{
    const draft=JSON.parse(deckSessionStorage.getItem("cc.reload-draft")||"null");
    if(draft&&draft.name===active){$("msg").value=draft.text;deckSessionStorage.removeItem("cc.reload-draft")}
  }catch(e){}
  closedDrafts.clear();messageDrafts.clear();
  try{for(const[name,text]of JSON.parse(deckSessionStorage.getItem("cc.closed-drafts")||"[]"))if(typeof name==="string"&&typeof text==="string")closedDrafts.set(name,text)}catch(e){}
  try{
    for(const [name,text] of JSON.parse(deckSessionStorage.getItem("cc.session-drafts")||"[]"))
      if(typeof name==="string"&&typeof text==="string")messageDrafts.set(name,text);
    deckSessionStorage.removeItem("cc.session-drafts");
    if(active&&!$("msg").value)$("msg").value=messageDrafts.get(active)||"";
  }catch(e){}
  if(active&&$("msg").value)messageDrafts.set(active,$("msg").value);
  for(const images of imageAttachments.values())for(const image of images)if(image.preview)URL.revokeObjectURL(image.preview);
  imageAttachments.clear();
  try{
    const draft=JSON.parse(deckSessionStorage.getItem("cc.reload-images")||"null");
    if(Array.isArray(draft)){
      for(const [name,images] of draft)if(typeof name==="string"&&Array.isArray(images))imageAttachments.set(name,images.slice(0,4));
    }else if(draft&&draft.name===active&&Array.isArray(draft.images))imageAttachments.set(active,draft.images.slice(0,4));
    deckSessionStorage.removeItem("cc.reload-images");
  }catch(e){}
  wrapPreview=true;try{wrapPreview=deckLocalStorage.getItem("cc.wrap")!=="0"}catch(e){}
  applyWrap();saveClosedDrafts();
  $("msg").style.height="";$("msg").dispatchEvent(new Event("input"));
}
restoreInstance();
loadMetrics();setInterval(loadMetrics,5000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)loadMetrics()});

checkGithubFoot(true);setInterval(checkGithubFoot,5000);
loadUsage();setInterval(()=>{loadUsage();if(!document.hidden&&!lmData.profiles?.length)loadLM(false).then(renderInteg)},60000);loadLM().then(renderInteg);let lmPolling=false;
// Generation timing needs a fast tick, but only with a configured profile and one request at a time.
setInterval(()=>{if(document.hidden||$("settings_dlg").open||lmPolling||!lmData.profiles?.length)return;lmPolling=true;loadLM(false).then(renderInteg).finally(()=>{lmPolling=false})},1000);
showCachedServer();loadServer();setInterval(loadServer,3600000);
loadVersion();
loadIntegrations();
let hiddenAt=0;
document.addEventListener("visibilitychange",()=>{if(document.hidden){hiddenAt=Date.now();return}if(Date.now()-hiddenAt>5000)setConnection("connecting")});
document.addEventListener("visibilitychange",()=>{if(!document.hidden){checkGithubFoot(true);loadUsage();load();checkInterfaceVersion();loadVersion();loadOtherDecks();if(!$("integrations_dlg").hidden&&!telegramDirty)loadIntegrations()}});
load();setInterval(load,2500);

loadDeckSettings().catch(e=>{if(!e.offline)toast(e.message)});
loadInbox();setInterval(loadInbox,5000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)loadInbox()});
