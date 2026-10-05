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
try{selectedDeck=localStore.getItem("cc.deck")||""}catch(e){}
if(!/^[0-9a-f]{24}$/.test(selectedDeck))selectedDeck="";
const deckLocalStorage=instanceStorage(localStore,selectedDeck);
const deckSessionStorage=instanceStorage(sessionStore,selectedDeck);
function activePath(path){return instancePath(selectedDeck,path)}
async function gatewayApi(path,body){return api(path,body,true)}

const BUSY_SEC=6;
const UI_REVISION="__PANEL_REVISION__";
const isMobile=()=>matchMedia("(max-width:760px)").matches;
let sessions=[],active=null,mode=null,clockSkew=0;
const frames=new Map(),wasBusy=new Map(),attention=new Set();
try{active=deckLocalStorage.getItem("cc.active");mode=deckLocalStorage.getItem("cc.mode."+(isMobile()?"m":"d"))}catch(e){}
if(location.hash.length>1)try{active=decodeURIComponent(location.hash.slice(1))}catch(e){}
try{
  const draft=JSON.parse(deckSessionStorage.getItem("cc.reload-draft")||"null");
  if(draft&&draft.name===active){$("msg").value=draft.text;deckSessionStorage.removeItem("cc.reload-draft")}
}catch(e){}

/* keep layout glued to the visible area when the iOS keyboard opens */
function fitViewport(){
  const vv=window.visualViewport;if(!vv)return;
  if(Math.abs(vv.scale-1)>0.01)return; // Pinch zoom must not resize the document layout.
  const root=document.documentElement;
  const keyboard=isMobile()&&Math.abs(vv.scale-1)<0.01&&root.clientHeight-vv.height>150;
  // Keep controls inside the web view: the OS-owned strip below an installed
  // app is outside its drawable viewport, even when screen.height is larger.
  root.style.setProperty("--app-h",vv.height+"px");
  root.style.setProperty("--app-top",keyboard?vv.offsetTop+"px":"0px");
  document.body.classList.toggle("keyboard-open",keyboard);
}
if(window.visualViewport){visualViewport.addEventListener("resize",fitViewport);visualViewport.addEventListener("scroll",fitViewport);fitViewport()}
addEventListener("pageshow",fitViewport);
addEventListener("orientationchange",()=>requestAnimationFrame(fitViewport));

async function api(path,body,gateway=false){
  const r=await fetch(gateway?path:activePath(path),body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{cache:"no-store"});
  if(r.status===401){
    try{stashDrafts();location.href="/login"}catch(e){toast(tr("Войдите в новой вкладке: здесь сохранён несохранённый текст."),true,{label:tr("Войти"),run:()=>window.open("/login","_blank","noopener")})}
    throw new Error("login required");
  }
  const d=r.headers.get("Date");if(d)clockSkew=Date.now()/1000-Date.parse(d)/1000;
  const j=await r.json().catch(()=>({error:r.statusText}));
  if(!r.ok)throw new Error(j.error||r.statusText);return j;
}
function toast(m,info,action){
  const t=$("toast"),dialogs=Array.from(document.querySelectorAll("dialog[open]"));
  (dialogs[dialogs.length-1]||document.body).append(t);t.className=info==="success"?"success":info?"info":"";t.replaceChildren(m);
  if(action){const b=document.createElement("button");b.textContent=action.label;b.onclick=()=>{action.run();t.style.display="none"};t.append(b)}
  t.style.display="block";clearTimeout(t._h);t._h=setTimeout(()=>t.style.display="none",action?12000:(info?1800:5000));
}

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
const curMode=()=>mode||(isMobile()?"screen":"term");

function drawer(on){document.body.classList.toggle("drawer",on);if(on)$("q").blur()}
function sheet(on){
  if(on){if(!active)return;$("sheetCap").textContent=active;$("s_link").style.display=lastUrl(cur())?"":"none"}
  $("sheet").classList.toggle("on",on);
}
const cur=()=>sessions.find(x=>x.name===active);
const messageDrafts=new Map();
const closedDrafts=new Map();
try{for(const[name,text]of JSON.parse(deckSessionStorage.getItem("cc.closed-drafts")||"[]"))if(typeof name==="string"&&typeof text==="string")closedDrafts.set(name,text)}catch(e){}
try{
  for(const [name,text] of JSON.parse(deckSessionStorage.getItem("cc.session-drafts")||"[]"))
    if(typeof name==="string"&&typeof text==="string")messageDrafts.set(name,text);
  deckSessionStorage.removeItem("cc.session-drafts");
  if(active&&!$("msg").value)$("msg").value=messageDrafts.get(active)||"";
}catch(e){}
if(active&&$("msg").value)messageDrafts.set(active,$("msg").value);
let quickSignature=null,quickActive=null;
const quickButtons=new Map();
function renderQuickTabs(){
  const box=$("quick_tabs"),signature=JSON.stringify(sessions.map(s=>[s.name,s.title,agentOf(s)]));
  if(signature!==quickSignature){
    const left=box.scrollLeft;box.replaceChildren();quickButtons.clear();
    for(const s of sessions){
      const button=el("button","quick-tab",el("span","dot"),agentIcon(s),el("span","label",sessionTitle(s)),el("span","bell"));
      button.type="button";button.setAttribute("aria-label",tr("Открыть сессию ")+sessionTitle(s));
      button.onclick=()=>select(s.name);box.append(button);quickButtons.set(s.name,button);
    }
    box.scrollLeft=left;quickSignature=signature;
  }
  document.body.classList.toggle("has-quick-tabs",sessions.length>0);
  for(const s of sessions){
    const button=quickButtons.get(s.name);button.classList.toggle("on",s.name===active);
    button.setAttribute("aria-pressed",String(s.name===active));button.title=sessionTitle(s)+" · "+stateText(s);
    button.children[0].className="dot "+state(s);button.children[3].style.display=attention.has(s.name)?"":"none";
  }
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

function renderTabs(){
  renderQuickTabs();
  const q=$("q").value.trim().toLowerCase(),box=$("tabs");
  const list=sessions.filter(s=>!q||(s.name+" "+sessionTitle(s)+" "+s.group+" "+s.path).toLowerCase().includes(q));
  box.replaceChildren();let grp=null,i=0;
  for(const s of list){
    if(s.group!==grp){grp=s.group;box.append(el("div","grp",grp))}
    i++;const st=state(s);
    const t=el("div","tab"+(s.name===active?" on":""));
    const dot=el("span","dot "+st);dot.title=stateText(s);
    const ag=agentOf(s);
    t.append(dot,agentIcon(s),el("div","t",el("div","n",sessionTitle(s)),...(isLocal(s)?[el("div","s session-source",agentLabel(s))]:[]),el("div","s",shortPath(s.path))));
    t.title=isLocal(s)?s.source.model+" · "+localComputer(s):s.name;
    if(attention.has(s.name))t.append(el("span","bell"));
    else if(i<10)t.append(el("span","k","⌥"+i));
    t.dataset.session=s.name;t.onclick=()=>select(s.name);
    box.append(t);
  }
  if(!sessions.length)box.append(el("div","grp",tr("сессий пока нет")));
  const busy=sessions.filter(s=>state(s)==="busy").length;
  $("foot").textContent=tr("{0} сессий · {1} работают",[sessions.length,busy])+(attention.size?tr(" · {0} готово",[attention.size]):"");
  $("menuBadge").textContent=attention.size;$("menuBadge").classList.toggle("on",attention.size>0);
  document.title=(attention.size?`(${attention.size}) `:"")+"Agent Deck";
}
function renderTitle(){
  const s=cur(),t=$("title");t.replaceChildren();
  document.body.classList.toggle("is-shell",!!s&&agentOf(s)==="shell");
  document.body.classList.toggle("is-codex",!!s&&agentOf(s)==="codex");
  $("msg").placeholder=s?tr("Сообщение в ")+agentLabel(s)+"…":tr("Сообщение агенту…");
  if(!s){t.textContent=isMobile()?"Agent Deck":"—";return}
  const st=state(s);
  t.append(el("b","",sessionTitle(s)),el("span","path"," — "+s.path.replace(/^\/(?:home|Users)\/[^/]+/,"~")),el("span","st",stateText(s)+" · "+shortPath(s.path)+(s.source?.label?" · "+s.source.label:"")));
}

function frameFor(name){
  let f=frames.get(name);
  if(!f){
    f=document.createElement("iframe");f.src=activePath("/t/?arg="+encodeURIComponent("=cc-"+name));
    f.onload=()=>{try{f.contentWindow.addEventListener("keydown",hotkeys,true);hookClipboard(f.contentWindow)}catch(e){}};
    $("stage").append(f);frames.set(name,f);
  }
  return f;
}
function show(){
  const s=cur(),m=curMode();
  $("empty").style.display=s?"none":"grid";
  if(!s)$("empty").textContent=load.done?tr("Нет сессий. Создайте новую через меню ☰ → ＋."):tr("Загружаю сессии…");
  renderTitle();renderSendState();renderAttachments();
  $("b_mode").textContent=m==="term"?tr("⌨ Экран"):tr("▣ Живой терминал");
  for(const b of $("seg").children)b.classList.toggle("on",b.dataset.m===m);
  for(const[n,f]of frames){
    f.classList.toggle("on",!!s&&m==="term"&&n===active);
    const session=sessions.find(x=>x.name===n);f.inert=isLocal(session)&&!session.running;
  }
  placeSessionKeys({row:$("session_keys"),composer:$("session_composer"),screen:$("screen"),terminal:$("terminal_keys"),wrap:$("b_wrap"),reconnect:$("b_reconnect"),mode:m,active:!!s});
  $("screen").classList.toggle("on",!!s&&m==="screen");
  if(s&&m==="term"){const f=frameFor(active);f.classList.add("on");f.inert=isLocal(s)&&!s.running;if(!isMobile()&&!f.inert)setTimeout(()=>{try{f.contentWindow.focus();f.contentWindow.term&&f.contentWindow.term.focus()}catch(e){}},30)}
  if(s&&m==="screen")updateScreen(s,true);
  updateLink();
}
function reconnectTerminal(){
  if(!active)return;
  const frame=frames.get(active);
  if(frame)frame.remove();
  frames.delete(active);show();
}
function setMode(m){mode=m;try{deckLocalStorage.setItem("cc.mode."+(isMobile()?"m":"d"),m)}catch(e){}show()}

let wrapPreview=true;
try{wrapPreview=deckLocalStorage.getItem("cc.wrap")!=="0"}catch(e){}
function applyWrap(){
  $("pre").classList.toggle("no-wrap",!wrapPreview);
  $("b_wrap").setAttribute("aria-pressed",String(wrapPreview));
}
function toggleWrap(){
  wrapPreview=!wrapPreview;
  try{deckLocalStorage.setItem("cc.wrap",wrapPreview?"1":"0")}catch(e){}
  applyWrap();
}
applyWrap();

const URL_RE=/https?:\/\/[^\s"'<>│]+/g;
/* Claude hard-wraps long URLs: glue a URL at line end with following space-free lines */
function unwrapUrls(text){
  const L=text.split("\n"),out=[];
  for(let i=0;i<L.length;i++){
    let line=L[i];
    if(/https?:\/\/\S+$/.test(line.trimEnd()))
      while(i+1<L.length&&/^\S{2,}$/.test(L[i+1])&&!/^https?:/.test(L[i+1])){line=line.trimEnd()+L[++i]}
    out.push(line);
  }
  return out.join("\n");
}
let panelOrigins=[location.origin];
const resolvePanelLink=u=>panelLinkTarget(u,{browserOrigin:location.origin,panelOrigins,identity:selectedDeck});
const cleanUrl=u=>u.replace(/[.,;)\]]+$/,"");
function lastUrl(s){const m=unwrapUrls(s&&s.preview||"").match(URL_RE);return m?cleanUrl(m[m.length-1]):null}
function updateLink(){$("b_link").style.display=lastUrl(cur())?"":"none"}
function openLink(){const u=lastUrl(cur());if(u)window.open(resolvePanelLink(u),"_blank","noopener")}
const ANSI_PALETTE=["#2e3436","#cc0000","#4e9a06","#c4a000","#3465a4","#75507b","#06989a","#d3d7cf","#555753","#ef2929","#8ae234","#fce94f","#729fcf","#ad7fa8","#34e2e2","#eeeeec"];
function ansiColor(n){
  if(!Number.isInteger(n)||n<0||n>255)return null;
  if(n<16)return ANSI_PALETTE[n];
  if(n>=232){const v=8+(n-232)*10;return `rgb(${v},${v},${v})`}
  n-=16;const level=v=>v===0?0:55+40*v;
  return `rgb(${level(Math.floor(n/36))},${level(Math.floor(n/6)%6)},${level(n%6)})`;
}
function ansiLines(text){
  let style={},line=[],lines=[];
  const write=t=>{
    const parts=t.replace(/\r/g,"").split("\n");
    parts.forEach((part,i)=>{if(i){lines.push(line);line=[]}if(part)line.push({text:part,style:{...style}})});
  };
  const sgr=params=>{
    const codes=params.split(";").flatMap(p=>{
      const c=p.split(":");
      if(c[0]==="4"&&c.length>1)return [c[1]==="0"?24:4];
      if(c.length>=5&&(c[0]==="38"||c[0]==="48")&&c[1]==="2")return [c[0],c[1],...c.slice(-3)].map(Number);
      return c.filter((v,i)=>v!==""||i===0).map(Number);
    });
    for(let i=0;i<codes.length;i++){
      const c=codes[i];
      if(c===0)style={};
      else if(c===1)style.bold=true;
      else if(c===2)style.dim=true;
      else if(c===3)style.italic=true;
      else if(c===4||c===21)style.underline=true;
      else if(c===7)style.inverse=true;
      else if(c===8)style.hidden=true;
      else if(c===9)style.strike=true;
      else if(c===22){delete style.bold;delete style.dim}
      else if(c===23)delete style.italic;
      else if(c===24)delete style.underline;
      else if(c===27)delete style.inverse;
      else if(c===28)delete style.hidden;
      else if(c===29)delete style.strike;
      else if(c===39)delete style.fg;
      else if(c===49)delete style.bg;
      else if(c>=30&&c<=37)style.fg=ansiColor(c-30);
      else if(c>=90&&c<=97)style.fg=ansiColor(c-90+8);
      else if(c>=40&&c<=47)style.bg=ansiColor(c-40);
      else if(c>=100&&c<=107)style.bg=ansiColor(c-100+8);
      else if(c===38||c===48){
        const key=c===38?"fg":"bg",mode=codes[++i];let color=null;
        if(mode===5)color=ansiColor(codes[++i]);
        else if(mode===2){const rgb=codes.slice(i+1,i+4);i+=3;if(rgb.length===3&&rgb.every(v=>Number.isInteger(v)&&v>=0&&v<=255))color=`rgb(${rgb.join(",")})`}
        if(color)style[key]=color;
      }
    }
  };
  const escapes=/\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g;
  let start=0;
  for(const m of text.matchAll(escapes)){
    write(text.slice(start,m.index));
    if(m[0].startsWith("\x1b[")&&m[0].endsWith("m"))sgr(m[0].slice(2,-1));
    start=m.index+m[0].length;
  }
  write(text.slice(start));lines.push(line);
  // Parse before trimming so styles spanning lines remain intact.
  while(lines.length&&!lines[lines.length-1].some(r=>r.text.trim()))lines.pop();
  return lines.slice(-200);
}
function styledText(text,s){
  const span=el("span","",text);
  if(s.inverse){span.style.color=s.bg||"var(--bg)";span.style.backgroundColor=s.fg||"var(--fg)"}
  else{if(s.fg)span.style.color=s.fg;if(s.bg)span.style.backgroundColor=s.bg}
  if(s.bold)span.style.fontWeight="700";
  if(s.dim)span.style.opacity="0.65";
  if(s.italic)span.style.fontStyle="italic";
  const decorations=[];if(s.underline)decorations.push("underline");if(s.strike)decorations.push("line-through");
  if(decorations.length)span.style.textDecoration=decorations.join(" ");
  if(s.hidden)span.style.visibility="hidden";
  return span;
}
function appendStyledRange(node,runs,from,to){
  let offset=0;
  for(const run of runs){
    const end=offset+run.text.length;
    if(end>from&&offset<to)node.append(styledText(run.text.slice(Math.max(0,from-offset),Math.min(run.text.length,to-offset)),run.style));
    offset=end;if(offset>=to)break;
  }
}
const BOX_CHARS=/[─━═╌┄┈╍▔▁]/g;
const BOX_LINE=/^[\s─━═╌┄┈╍▔▁-]*$/;
function joinUrlLines(lines){
  const out=[];
  for(let i=0;i<lines.length;i++){
    const runs=lines[i].slice(),plain=runs.map(r=>r.text).join("");
    if(/https?:\/\/\S+$/.test(plain.trimEnd())){
      while(i+1<lines.length){
        const next=lines[i+1].map(r=>r.text).join("");
        if(!/^\S{2,}$/.test(next)||/^https?:/.test(next))break;
        for(let j=runs.length-1;j>=0&&/\s$/.test(runs[j].text);j--)runs[j]={...runs[j],text:runs[j].text.trimEnd()};
        runs.push(...lines[++i]);
      }
    }
    out.push(runs);
  }
  return out;
}
function updateScreen(s,force){
  const p=$("pre"),stick=force||p.scrollTop+p.clientHeight>=p.scrollHeight-40;
  const raw=s.preview_ansi??unwrapUrls(s.preview||"");
  if(p.dataset.raw!==raw){
    p.dataset.raw=raw;p.replaceChildren();
    const lines=joinUrlLines(ansiLines(raw));
    if(!lines.length)p.append(el("div","preview-empty",tr("В tmux пока нет текста. Можно переключиться в «Терм» и проверить сессию.")));
    for(const runs of lines){
      const line=runs.map(r=>r.text).join("").trimEnd();
      // TUI rules (Claude's input box etc.) would wrap into a stack of lines on a phone: draw them as one rule
      const boxN=(line.match(BOX_CHARS)||[]).length;
      if(line.length>=8&&boxN&&BOX_LINE.test(line)){if(!(p.lastChild&&p.lastChild.className==="hr"))p.append(el("div","hr"));continue}
      if(line.length>=20&&boxN/line.length>=0.8){p.append(el("div","hrl",line.replace(BOX_CHARS,"").trim()));continue}
      const d=el("div","ln");let i=0;
      for(const m of line.matchAll(URL_RE)){
        const u=cleanUrl(m[0]);appendStyledRange(d,runs,i,m.index);
        const a=document.createElement("a");a.href=resolvePanelLink(u);a.target="_blank";a.rel="noopener";
        appendStyledRange(a,runs,m.index,m.index+u.length);d.append(a);i=m.index+u.length;
      }
      appendStyledRange(d,runs,i,line.length);p.append(d);
    }
  }
  if(stick)p.scrollTop=p.scrollHeight;
}
function activate(name){
  if(name===active)return;
  if(active)messageDrafts.set(active,$("msg").value);
  active=name;attention.delete(name);
  $("msg").value=messageDrafts.get(name)||"";$("msg").style.height="";
  $("msg").dispatchEvent(new Event("input"));
  try{if(name)deckLocalStorage.setItem("cc.active",name);else deckLocalStorage.removeItem("cc.active")}catch(e){}
  history.replaceState(null,"","#"+(name?encodeURIComponent(name):""));
  $("pre").dataset.raw="";
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
  loadingSessions=loadSessions().finally(()=>{
    loadingSessions=null;if(sessionsQueued){sessionsQueued=false;if(!queuedSessions)load()}
  });return loadingSessions;
}
async function loadSessions(){
  const requested=active;
  try{
    const{sessions:list}=await api("/api/sessions"+(requested?"?preview="+encodeURIComponent(requested):""));
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
  }catch(e){toast(e.message)}
}
async function post(path,body,confirmText){
  if(panelUpdating){toast(tr("Панель обновляется. Дождитесь завершения."));return false}
  if(confirmText&&!confirm(confirmText))return false;
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
  post("/api/restart",{name:active,mode:m},m==="new"?tr("Перезапустить {0} в «{1}» с НОВЫМ разговором?",[a,active]):tr("Перезапустить {0} в «{1}», продолжив разговор?",[a,active]));
}
async function termHere(){
  const s=cur();if(!s)return;
  const names=new Set(sessions.map(x=>x.name));
  let base=s.name.replace(/-sh\d*$/,"").slice(0,27)+"-sh",n=base,i=2;
  while(names.has(n))n=base+(i++);
  const created=await post("/api/new",{name:n,agent:"shell",path:s.path});if(created)select(created.name||n);
}
async function kill(){
  if(!active)return;const n=active;
  await post("/api/kill",{name:n},tr("Закрыть сессию «{0}»? Агент будет остановлен.",[n]));
}
function popout(){if(active)window.open(activePath("/t/?arg="+encodeURIComponent("=cc-"+active)),"_blank")}
let uploading=false,choosingImages=false;
const imageAttachments=new Map();
const attachmentsFor=name=>imageAttachments.get(name)||[];
try{
  const draft=JSON.parse(deckSessionStorage.getItem("cc.reload-images")||"null");
  if(Array.isArray(draft)){
    for(const [name,images] of draft)if(typeof name==="string"&&Array.isArray(images))imageAttachments.set(name,images.slice(0,4));
  }else if(draft&&draft.name===active&&Array.isArray(draft.images))imageAttachments.set(active,draft.images.slice(0,4));
  deckSessionStorage.removeItem("cc.reload-images");
}catch(e){}
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
      const data=await readImageData(image);
      const result=await api("/api/upload",{name,data,filename:file.name||"file"});
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
  }else d.textContent=status?status.text:(isMobile()?tr("Enter ↵ · ↑ отправить"):tr("Enter отправить · ⇧Enter ↵"));
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
async function logout(){try{stashDrafts()}catch(e){}await fetch("/logout",{method:"POST"});location.href="/login"}
function toggleKeys(){const expanded=$("keys").classList.toggle("expanded");$("b_keymore").setAttribute("aria-expanded",String(expanded))}
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

/* ---------- GitHub ---------- */
const GH_ICON='<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>';
let repos=[],ghLogin=null;
async function ghStatus(){try{const st=await api("/api/github/status");ghLogin=st.connected?st.login:null}catch(e){ghLogin=null}return ghLogin}
async function ghConnect(){if(await post("/api/github_login",{})){if($("dlg").open)$("dlg").close();select("github-login");setMode("screen")}}
async function agentAction(kind,agent){
  const name=kind==="install"?"install-"+agent:agent+"-login";
  if(await post("/api/agent_"+kind,{agent})){select(name);if(isMobile())setMode("screen")}
}
function irow(glyphHtml,name,ver,right){
  const r=el("div","irow");const g=el("span","");g.innerHTML=glyphHtml;
  const nm=el("span","nm",name);if(ver)nm.append(el("small","",ver));
  r.append(g,nm,...right);return r;
}
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
/* pace: compare used % with the share of the window that has already elapsed */
function pace(w){
  if(!w.resets_at||!w.secs)return null;
  const now=Date.now()/1000,left=w.resets_at-now,elapsed=Math.min(Math.max(1-left/w.secs,0),1);
  if(elapsed<0.03||left<=0)return {elapsed};             // too early to judge
  const used=w.percent||0,norm=elapsed*100,diff=Math.round(used-norm);
  const res={elapsed,norm:Math.round(norm),diff};
  if(used>0){
    const rate=used/(w.secs*elapsed);                       // % per second so far
    const hitAt=now+(100-used)/rate;                        // when 100% is reached at this pace
    res.forecast=Math.round(used/elapsed);                  // projected % at reset
    if(hitAt<w.resets_at&&elapsed>=0.1)res.hitAt=hitAt;   // early in the window the forecast is noise
  }
  return res;
}
function fmtWhen(ts){
  const d=new Date(ts*1000),hm=d.toLocaleTimeString(DATE_LOCALE,{hour:"2-digit",minute:"2-digit"});
  return d.toDateString()===new Date().toDateString()?tr("сегодня ")+hm:d.toLocaleDateString(DATE_LOCALE,{weekday:"short"})+" "+hm;
}
function compactReset(ts){
  if(!ts)return "↻ —";
  const minutes=Math.max(0,Math.round((ts*1000-Date.now())/60000)),days=Math.floor(minutes/1440),hours=Math.floor(minutes%1440/60);
  const duration=days?tr("{0}д {1}ч",[days,hours]):hours?tr("{0}ч {1}м",[hours,minutes%60]):tr("{0}м",[minutes]);
  return "↻ "+duration;
}
function usageBlock(u){
  const box=el("div","usage");if(!u)return null;
  if(u.error&&!(u.windows||[]).length){box.append(el("div","err",u.error));return box}
  for(const w of u.windows||[]){
    const p=Math.round(w.percent||0),fill=el("i",p>=90?"bad":p>=70?"warn":"");fill.style.width=Math.min(p,100)+"%";
    const labels={"Общий · месяц":tr("месяц · всё"),"Kimi Code · месяц":tr("месяц · код"),"5 часов":tr("5 ч")};
    const pc=pace(w),bar=el("span","usage-meter",fill),row=el("div","uw",el("span","",labels[w.label]||tr(w.label)),el("span","pc",p+"%"),bar);
    bar.setAttribute("role","progressbar");bar.setAttribute("aria-label",tr("Использование лимита: ")+tr(w.label));
    bar.setAttribute("aria-valuemin","0");bar.setAttribute("aria-valuemax","100");bar.setAttribute("aria-valuenow",String(Math.max(0,Math.min(p,100))));
    const details=el("details","quota-details"),summary=el("summary","",el("span","rs",compactReset(w.resets_at))),body=el("div","quota-explanation");
    summary.title=fmtReset(w.resets_at)||tr("Данные о лимите");summary.setAttribute("aria-label",tr("Подробности лимита: ")+tr(w.label));
    if(pc&&pc.norm!==undefined){
      const tick=el("b","");tick.style.left=(pc.elapsed*100)+"%";tick.title=tr("норма к этому моменту: {0}%",[pc.norm]);bar.append(tick);
      const cls=pc.diff<=3?"good":pc.hitAt?"crit":"over";
      summary.append(el("span","pace "+cls,pc.diff<=3?"✓":"▲ +"+pc.diff+tr(" п.п.")));
      body.append(el("div","",tr("Норма сейчас: {0}%. ",[pc.norm])+(pc.diff<=3?tr("В пределах нормы."):tr("Быстрее нормы на {0} п.п.",[pc.diff]))));
      if(pc.hitAt)body.append(el("div","forecast",tr("При таком темпе лимит закончится ≈ ")+fmtWhen(pc.hitAt)));
      else if(pc.forecast!==undefined)body.append(el("div","forecast",tr("Прогноз к сбросу: ≈ ")+pc.forecast+"%"));
    }
    body.append(el("div","",fmtReset(w.resets_at)));details.append(summary,body);row.append(details);box.append(row);
  }
  if(u.stale)box.append(el("div","err",tr("⚠ данные устарели")));return box;
}

let integOpen=(()=>{try{const v=deckLocalStorage.getItem("cc.integ."+(isMobile()?"m":"d"));return v===null?!isMobile():v==="1"}catch(e){return !isMobile()}})();
function toggleInteg(){integOpen=!integOpen;try{deckLocalStorage.setItem("cc.integ."+(isMobile()?"m":"d"),integOpen?"1":"0")}catch(e){}renderInteg()}
function integSummary(){
  const head=el("button","ihead"+(integOpen?" open":""));head.type="button";head.onclick=toggleInteg;
  head.title=integOpen?tr("Свернуть"):tr("Лимиты и аккаунты");
  for(const a of["claude","codex","kimi"]){
    const st=lastAg[a]||{},u=usageData[a],sum=el("span","sum");
    const g=agentIcon({agent:a});sum.append(g);
    if(!st.installed||!st.logged_in){sum.append(el("span","dim",st.installed?tr("войти"):tr("нет")))}
    else{
      const w=u&&(u.windows||[]).find(x=>x.period==="month")||u&&(u.windows||[]).find(x=>x.secs>=86400)||(u&&(u.windows||[])[0]);
      if(w){
        const pc=pace(w),p=Math.round(w.percent||0);
        const cls=!pc||pc.diff===undefined?"":pc.diff<=3?"good":pc.hitAt?"crit":"over";
        sum.append(el("span","",p+"%"));
        if(cls)sum.append(el("span",cls,cls==="good"?"✓":"▲"));
      }else sum.append(el("span","dim","—"));
    }
    head.append(sum);
  }
  const gh=el("span","sum");gh.innerHTML=GH_ICON;gh.append(el("span",ghLogin?"good":"dim",ghLogin?"✓":"—"));
  head.append(gh,el("span","chev",integOpen?"▾":"▸"));
  return head;
}
function renderInteg(){
  const head=el("div","quota-heading",el("span","",tr("Остаток")),el("span","quota-heading-plan",tr("План")));
  const gh=el("span","quota-github");gh.innerHTML=GH_ICON;gh.title=ghLogin?"GitHub · "+ghLogin:tr("GitHub не подключён");gh.append(el("span",ghLogin?"good":"dim",ghLogin?"✓":"—"));head.append(gh);
  const rows=[head];
  for(const a of ["claude","codex","kimi"]){
    const u=usageData[a],w=primaryQuota(u),row=el("div","quota-strip",agentIcon({agent:a}));
    const percent=Number.isFinite(w?.percent)?Math.round(Math.max(0,Math.min(100,100-w.percent))):null,plan=plannedRemaining(w,now());
    row.title=AGENTS[a].label+" · "+(w?tr(w.label||"")+" · "+fmtReset(w.resets_at):u?.error||tr("Нет данных"))+(u?.stale?" · "+tr("⚠ данные устарели"):"");
    row.setAttribute("aria-label",row.title);
    const remaining=el("span","quota-percent "+quotaTone(percent,plan),percent===null?"—":percent+"%");remaining.title=tr("Остаток");
    const target=el("span","quota-plan",plan===null?"—":plan+"%");target.title=tr("По плану к концу дня");
    target.setAttribute("aria-label",target.title+": "+target.textContent);
    row.append(el("span","quota-values",remaining,target),el("span","quota-reset",w?compactReset(w.resets_at):"—"));
    rows.push(row);
  }
  for(const p of lmData.profiles||[])rows.push(localUsage(p));
  $("integ").replaceChildren(...rows);
  renderSendState();
  if($("settings_dlg").open&&!$("settings_dlg").contains(document.activeElement))renderHub();
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
  const full=el("div","",model);details.append(summary,full,el("p","",profile.name+" · "+performanceText(sample,false)));box.append(details);
  const line=el("div","local-live-line");
  const seconds=Math.floor(live?.request_time_seconds||0),elapsed=Math.floor(seconds/60)+":"+String(seconds%60).padStart(2,"0");
  const state=el("span","local-state",live?(live.phase==="waiting"?"◌ TTFT "+elapsed:(live.phase==="tool"?"⚙ ":"✦ ")+elapsed+(live.chunks?" · "+live.chunks+" Δ":"")):"✓ "+(Number.isFinite(sample.output_tokens)?sample.output_tokens+" tok":"—"));
  state.title=live?tr(labels[live.phase]||labels.waiting):performanceText(sample,false);
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
let hubSection="agents",lmData={profiles:[],discovery:{}},lmTimer=null,returnToNew=false,lmRefreshPending=null,lmModelsChecked=0;
function settingsSection(section){
  hubSection=section;for(const name of ["agents","models","connections","app"])$("hub_"+name).hidden=name!==section;
  for(const b of document.querySelectorAll(".hub-nav button"))b.classList.toggle("on",b.dataset.section===section);
  if(section==="models"&&$("settings_dlg").open)refreshLMModels();
}
async function openSettings(section="agents"){
  drawer(false);sheet(false);settingsSection(section);
  if(!$("settings_dlg").open)$("settings_dlg").showModal();
  renderHub();
  await Promise.allSettled([loadDeckSettings(),(async()=>{const data=await api("/api/project_directory");$("project_directory").value=data.directory})(),refreshLMModels(),loadIntegrations(),checkGithubFoot(),(async()=>{const data=await api("/api/locales");$("ui_language").replaceChildren(...data.languages.map(x=>{const o=el("option","",x.name);o.value=x.code;return o}));$("ui_language").value=I18N.language})()]);
  clearInterval(lmTimer);lmTimer=setInterval(()=>{if(!document.hidden&&$("settings_dlg").open){if(lmData.discovery?.phase==="running")loadLM(false);if(hubSection==="models"&&Date.now()-lmModelsChecked>30000)refreshLMModels()}},2000);
}
$("settings_dlg").addEventListener("close",()=>{if($("settings_dlg").open)return;clearInterval(lmTimer);clearInterval(deckTimer);closeKimi();closeIntegrations();$("lm_key").value="";if(returnToNew){returnToNew=false;$("dlg").showModal();renderSources()}});
async function saveProjectDirectory(){
  await saveDirectorySetting({request:api,input:$("project_directory"),button:$("project_directory_save"),notify:toast,translate:tr});
}
let deckTimer=null;
async function loadDeckSettings(){
  const [data,network]=await Promise.all([gatewayApi("/api/decks"),gatewayApi("/api/network")]);
  const current=data.decks.find(deck=>deck.id===selectedDeck);
  panelOrigins=current?[current.url,location.origin]:[location.origin,"http://"+network.bind_host+":"+network.bind_port,"http://127.0.0.1:"+network.bind_port,"http://localhost:"+network.bind_port];
  if(!current&&network.public_url)panelOrigins.push(network.public_url);
  populateDeckSelector($("deck_select"),data.decks,selectedDeck,network.name);
  $("network_name").value=network.name;$("network_public_url").value=network.public_url;
  $("network_bind").textContent="http://"+network.bind_host+":"+network.bind_port;
  $("network_browser").textContent=location.origin;
  const box=$("deck_connections");box.replaceChildren();
  for(const deck of data.decks){
    const card=el("div","deck-connection",el("strong","",deck.name),el("p","",deck.url));
    card.append(el("div","deck-actions",btn(tr("Переключиться"),"pri",()=>switchDeck(deck.id)),btn(tr("Изменить"),"",()=>editDeck(deck)),btn(tr("Удалить"),"danger",()=>removeDeck(deck.id))));box.append(card);
  }
  renderDeckDiscovery(data.discovery);
  if(selectedDeck&&!data.decks.some(d=>d.id===selectedDeck))switchDeck("");
}
function switchDeck(identity){
  if(identity===selectedDeck)return;
  if(sending||uploading||choosingImages){$("deck_select").value=selectedDeck;toast(tr("Дождитесь окончания отправки или загрузки"));return}
  try{stashDrafts();localStore.setItem("cc.deck",identity)}catch(e){$("deck_select").value=selectedDeck;toast(tr("Не удалось сохранить черновик. Очистите поле перед обновлением."));return}
  location.hash="";location.reload();
}
function editDeck(deck={}){
  $("deck_id").value=deck.id||"";$("deck_name").value=deck.name||"";$("deck_url").value=deck.url||"";$("deck_username").value=deck.username||"";$("deck_password").value="";
  $("deck_editor").open=true;$("deck_editor").scrollIntoView({block:"nearest"});
}
async function saveDeck(){
  const button=$("deck_save");button.disabled=true;
  try{await gatewayApi("/api/decks_save",{id:$("deck_id").value||undefined,name:$("deck_name").value.trim(),url:$("deck_url").value.trim(),username:$("deck_username").value.trim(),password:$("deck_password").value});$("deck_password").value="";$("deck_editor").open=false;await loadDeckSettings();toast(tr("Agent Deck подключён"),"success")}
  catch(e){$("deck_password").value="";toast(e.message)}finally{button.disabled=false}
}
async function removeDeck(identity){
  if(!confirm(tr("Отключить этот Agent Deck?")))return;
  try{await gatewayApi("/api/decks_remove",{id:identity});if(identity===selectedDeck)switchDeck("");else await loadDeckSettings()}catch(e){toast(e.message)}
}
function renderDeckDiscovery(discovery){
  $("deck_discover").disabled=discovery.phase==="running";
  $("deck_discovery_status").textContent=discovery.error||tr(discovery.phase==="running"?"Поиск…":discovery.phase==="done"?"Поиск завершён":"");
  $("deck_discovery_results").replaceChildren(...(discovery.results||[]).map(deck=>el("div","deck-connection deck-result",el("div","deck-info",el("strong","",deck.name),el("p","",deck.url)),el("div","deck-actions",btn(tr("Подключить"),"",()=>editDeck(deck))))));
  clearInterval(deckTimer);
  if(discovery.phase==="running")deckTimer=setInterval(async()=>{if(document.hidden||!$("settings_dlg").open)return;try{const data=await gatewayApi("/api/decks");renderDeckDiscovery(data.discovery)}catch(e){toast(e.message);clearInterval(deckTimer)}},2000);
}
async function discoverDecks(){
  try{const result=await gatewayApi("/api/decks_discover",{port:Number($("deck_port").value)});renderDeckDiscovery(result.discovery)}catch(e){toast(e.message)}
}
async function saveNetwork(){
  const button=$("network_save");button.disabled=true;
  try{await gatewayApi("/api/network_save",{name:$("network_name").value.trim(),public_url:$("network_public_url").value.trim()});await loadDeckSettings();toast(tr("Настройки сохранены"),"success")}
  catch(e){toast(e.message)}finally{button.disabled=false}
}
function card(name,status,label,action,secondary=[]){const c=el("div","hub-card",el("div","card-top",el("div","card-main",el("h4","",name),el("p","",status)),btn(label,"pri",action)));if(secondary.length){const d=el("details","",el("summary","",tr("Другие действия")));for(const [text,fn] of secondary)d.append(btn(text,"",fn));c.append(d)}return c}
function openCardDetails(box){return new Set([...box.querySelectorAll(".hub-card")].filter(c=>c.querySelector("details[open]")).map(c=>c.querySelector("h4").textContent))}
function restoreCardDetails(box,open){for(const c of box.querySelectorAll(".hub-card")){const d=c.querySelector("details");if(d&&open.has(c.querySelector("h4").textContent))d.open=true}}
function renderHub(){
  const openAgents=openCardDetails($("hub_agents")),openModels=openCardDetails($("model_cards"));
  const selections=new Map([...$("model_cards").querySelectorAll("select")].map(x=>[x.dataset.profile,x.value]));
  $("hub_agents").replaceChildren(...["claude","codex","kimi","pi"].map(a=>{const st=lastAg[a]||{};if(a==="pi")return card("Pi",st.version||tr("Не установлен"),st.installed?tr("Обновить"):tr("Установить"),()=>agentAction("install",a));if(a==="kimi")return card(AGENTS[a].label,st.version||tr("Не установлен"),st.installed?(lastAg.kimi_config?.configured?tr("Обновить"):tr("Настроить ключ Kimi")):tr("Установить"),()=>st.installed&&!lastAg.kimi_config?.configured?openKimi():agentAction("install",a));return card(AGENTS[a].label,[st.version,st.installed?(st.logged_in?tr("подключён"):tr("Войти")):tr("Не установлен")].filter(Boolean).join(" · "),st.installed?(st.logged_in?tr("Обновить"):tr("Войти")):tr("Установить"),()=>agentAction(st.installed&&!st.logged_in?"login":"install",a),st.installed?[[tr("Обновить"),()=>agentAction("install",a)]]:[])}));
  restoreCardDetails($("hub_agents"),openAgents);
  // Rebuilding during a running test/benchmark would re-enable its buttons and allow a duplicate run.
  if($("model_cards").getAttribute("aria-busy")!=="true")renderModelCards(selections,openModels);
  $("connection_cards").replaceChildren(card("GitHub",ghLogin||tr("Не подключён"),ghLogin?tr("Репозитории"):tr("Подключить"),()=>{returnToNew=false;$("settings_dlg").close();ghLogin?openNew():ghConnect()}),card("Telegram",telegramConfig.paired?tr("подключён"):tr("Не подключён"),tr("Настроить"),()=>openEditor("telegram")));
  if(panelVersion)renderVersion(panelVersion);
}
function renderModelCards(selections,open){
  const cards=[card("Kimi",lastAg.kimi_config?.configured?tr("Ключ сохранён на сервере"):tr("Ключ ещё не настроен"),tr("Настроить"),()=>openEditor("kimi"))];
  for(const p of lmData.profiles||[]){
    const c=card(p.name+" · LM Studio",p.url+" · "+tr(p.status==="online"?"подключён":p.status==="needs_key"?"Нужен ключ":p.status==="offline"?"Недоступен":"Не проверен"),tr("Обновить модели"),()=>lmAction("probe",{id:p.id}),[[tr("Изменить"),()=>editLM(p)],[tr("Удалить"),()=>lmAction("remove",{id:p.id})]]);
    const samples=p.measurements?Object.values(p.measurements).flatMap(group=>Object.values(group)):[p.performance||{}];for(const sample of samples)c.append(el("p","",performanceText(sample,false)));
    if(p.models?.length){const select=el("select","");select.dataset.profile=p.id;select.setAttribute("aria-label",tr("Модель"));for(const m of p.models){const o=el("option","",m.name+(m.loaded?" · "+tr("Загружена"):"")+(m.tool_tested?" · ✓ tools":""));o.value=m.id;select.append(o)}if(selections.has(p.id))select.value=selections.get(p.id);if(!select.value&&select.options.length)select.selectedIndex=0;c.append(select);const detail=el("p","");const describe=()=>{const m=p.models.find(x=>x.id===select.value);detail.textContent=[m.context_length||m.max_context_length?tr("Контекст: {0}",[m.context_length||m.max_context_length]):"",m.quantization||"",m.tool_tested?tr("Инструменты: ✓"):tr("Инструменты: ?")].filter(Boolean).join(" · ")};select.onchange=describe;describe();c.append(detail);const actions=el("div","acts",btn(tr("Проверить инструменты"),"",()=>lmAction("test",{id:p.id,model:select.value})),btn(tr("Измерить скорость"),"",()=>lmAction("benchmark",{id:p.id,model:select.value})));c.append(actions)}cards.push(c);
  }
  $("model_cards").replaceChildren(...cards);restoreCardDetails($("model_cards"),open);
}
function performanceText(m,includeModel=true){
  const parts=[m.source==="session"?tr("Последний ответ"):m.source==="benchmark"?tr("Тест скорости"):tr("Без лимитов")];
  if(Number.isFinite(m.tokens_per_second))parts.push(m.tokens_per_second.toFixed(1)+" tok/s");
  if(Number.isFinite(m.time_to_first_token_seconds))parts.push("TTFT "+m.time_to_first_token_seconds.toFixed(2)+" s");
  if(Number.isFinite(m.model_load_time_seconds))parts.push(tr("Загрузка")+" "+m.model_load_time_seconds.toFixed(2)+" s");
  if(includeModel&&m.model)parts.push(m.model);return parts.join(" · ");
}
async function refreshLMModels(){
  if(document.hidden)return;
  if(lmRefreshPending)return lmRefreshPending;
  lmModelsChecked=Date.now();
  lmRefreshPending=(async()=>{try{lmData=await refreshModelCatalog(api);if($("settings_dlg").open)renderHub();renderDiscovery();renderSources()}catch(e){toast(e.message)}finally{lmRefreshPending=null}})();
  return lmRefreshPending;
}
async function loadLM(refresh=true){try{lmData=await api("/api/lmstudio");if($("settings_dlg").open&&refresh)renderHub();renderDiscovery()}catch(e){$("lm_progress").textContent=e.message}}
function editLM(p){$("lm_editor").open=true;$("lm_id").value=p.id||"";$("lm_name").value=p.name||"";$("lm_url").value=p.url||"";$("lm_key").value="";$("lm_clear_key").checked=false;$("lm_editor").scrollIntoView({block:"nearest"})}
function resetLM(){editLM({});$("lm_editor").open=false}
async function saveLM(){try{const saved=await api("/api/lm_save",{id:$("lm_id").value||undefined,name:$("lm_name").value.trim(),url:$("lm_url").value.trim(),key:$("lm_key").value,clear_key:$("lm_clear_key").checked});$("lm_key").value="";await api("/api/lm_probe",{id:saved.profile.id});resetLM();await loadLM();renderSources()}catch(e){toast(e.message)}}
async function lmAction(action,data){
  if($("model_cards").getAttribute("aria-busy")==="true")return;
  const buttons=[...$("model_cards").querySelectorAll("button")];buttons.forEach(b=>b.disabled=true);$("model_cards").setAttribute("aria-busy","true");toast(tr("Загружаю…"));
  let r=null;
  try{r=await api("/api/lm_"+action,data);if(r.result)toast(r.result.ok?tr("Проверка завершена"):r.result.error,r.result.ok?"success":"error")}catch(e){toast(e.message)}
  finally{buttons.forEach(b=>b.disabled=false);$("model_cards").removeAttribute("aria-busy")}
  // Reload after clearing aria-busy, otherwise renderHub would skip the refreshed model cards.
  if(r){await loadLM();renderSources()}
}
async function discoverLM(cancel=false){try{const ports=$("lm_ports").value.split(",").map(x=>Number(x.trim()));await api("/api/lm_discover",cancel?{cancel:true}:{ports});await loadLM()}catch(e){toast(e.message)}}
function renderDiscovery(){const d=lmData.discovery||{};$("lm_progress").textContent=d.error||[tr(d.phase==="running"?"Поиск…":d.phase==="done"?"Поиск завершён":d.phase==="cancelled"?"Остановлено":""),d.total?d.checked+" / "+d.total:""].filter(Boolean).join(" · ");$("lm_cancel").hidden=d.phase!=="running";$("lm_results").replaceChildren(...(d.results||[]).map(p=>card(p.name,p.url+(p.status==="needs_key"?" · "+tr("Нужен ключ"):""),tr("Добавить"),()=>editLM(p))))}
function openEditor(kind){kind==="kimi"?openKimi():openIntegrations()}
function configureSource(){returnToNew=true;$("dlg").close();openSettings("models")}
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
function closeKimi(){$("kimi_key").value="";$("kimi_dlg").hidden=true}
function openKimi(){
  const config=lastAg.kimi_config||{};
  $("kimi_key").value="";$("kimi_model").value=config.model||"k3";
  $("kimi_state").textContent=config.configured?tr("Ключ сохранён на сервере"):tr("Ключ ещё не настроен");
  openSettings("models");$("kimi_dlg").hidden=false;$("kimi_dlg").scrollIntoView({block:"nearest"});
}

async function saveKimi(clear=false){
  $("kimi_save").disabled=true;
  try{
    await api("/api/kimi_config",{key:$("kimi_key").value.trim(),model:$("kimi_model").value,clear});
    closeKimi();await checkGithubFoot();await loadUsage();renderHub();renderSources();toast(clear?tr("Ключ Kimi удалён"):tr("Настройки Kimi сохранены"),"success");
  }catch(e){toast(e.message)}finally{$("kimi_save").disabled=false}
}
function clearKimi(){if(confirm(tr("Удалить ключ Kimi из панели?")))saveKimi(true)}
let telegramConfig={},integrationTimer=null,telegramDirty=false;
for(const id of ["telegram_token","telegram_enabled"])$(id).addEventListener("input",()=>{telegramDirty=true});
function renderTelegram(config){
  const wasConfigured=telegramConfig.configured;
  telegramConfig=config||{};
  const c=telegramConfig;
  if(wasConfigured!==c.configured)$("telegram_credentials").open=!c.configured;
  $("telegram_credentials").querySelector("summary").textContent=c.configured?tr("Изменить токен бота"):tr("Токен бота");
  $("telegram_state").classList.toggle("connected",!!c.paired&&!!c.enabled&&!c.error);
  $("telegram_state").classList.toggle("error",!!c.error);
  $("telegram_state").textContent=c.available===false?tr("Обновите панель: установите интеграции из меню обновлений"):c.error||
    (c.paired?`@${c.bot} · ${c.account||tr("аккаунт привязан")} · ${c.enabled?tr("включён"):tr("пауза")}`:c.configured?tr("@{0} · привяжите свой Telegram",[c.bot]):tr("Бот ещё не подключён"));
  $("telegram_enabled").checked=c.enabled!==false;
  $("telegram_pair").style.display=c.configured&&!c.pair_url?"flex":"none";
  $("telegram_pair").textContent=c.paired?tr("Привязать другой аккаунт"):tr("Получить ссылку привязки");
  $("telegram_pairing").style.display=c.pair_url?"block":"none";
  if(typeof c.pair_url==="string"&&c.pair_url.startsWith("https://t.me/"))$("telegram_link").href=c.pair_url;else $("telegram_link").removeAttribute("href");
  renderInteg();
}
async function loadIntegrations(){
  try{const data=await api("/api/integrations");renderTelegram(data.telegram)}catch(e){if(!$("integrations_dlg").hidden)$("telegram_state").textContent=e.message}
}
function openIntegrations(){
  telegramDirty=false;$("telegram_token").value="";$("telegram_credentials").open=!telegramConfig.configured;openSettings("connections");$("integrations_dlg").hidden=false;loadIntegrations();
  clearInterval(integrationTimer);integrationTimer=setInterval(()=>{if(!document.hidden&&!telegramDirty)loadIntegrations()},3000);
}
function closeIntegrations(){$("telegram_token").value="";clearInterval(integrationTimer);$("integrations_dlg").hidden=true}
async function saveTelegram(clear=false){
  $("telegram_save").disabled=true;
  try{
    const data=await api("/api/telegram_config",{token:$("telegram_token").value.trim(),enabled:$("telegram_enabled").checked,language:I18N.language,clear});
    telegramDirty=false;$("telegram_token").value="";renderTelegram(data.telegram);renderHub();
    if(!clear&&!data.telegram.paired)await pairTelegram();
    toast(clear?tr("Telegram отключён"):tr("Настройки Telegram сохранены"),"success");
  }catch(e){toast(e.message)}finally{$("telegram_save").disabled=false}
}
async function pairTelegram(){
  try{const data=await api("/api/telegram_pair",{});renderTelegram(data.telegram)}catch(e){toast(e.message)}
}
function clearTelegram(){if(confirm(tr("Отключить Telegram и удалить сохранённый токен?")))saveTelegram(true)}
let panelUpdating=false,panelVersion=null,versionTimer=null,versionLoading=false;
const UPDATE_PHASES=new Set(["checking","downloading","installing","restarting"]);
function versionInfo(v){
  const revision=el("span","version-build","UI "+UI_REVISION.slice(0,7));revision.title=UI_REVISION;
  return el("div","version-info",el("span","version-number","v"+v.version),revision);
}
function renderVersion(v){
  panelVersion=v;const job=v.job||{},box=$("ver"),mobile=$("s_update");
  panelUpdating=UPDATE_PHASES.has(job.phase);
  box.replaceChildren("v"+v.version);box.title=v.latest?tr("последний релиз: v{0}",[v.latest]):"";
  mobile.style.display="none";
  let label,action;
  if(panelUpdating){label=job.message||tr("Обновляю панель…");action=()=>{}}
  else if(job.phase==="done"&&job.version===v.version&&UI_PANEL_VERSION!==null&&job.version!==UI_PANEL_VERSION){label=tr("Обновлено · перезагрузить интерфейс");action=refreshInterface}
  else if(job.phase==="error"){label=tr("Обновление не удалось · повторить");action=startPanelUpdate;box.title=job.message||label}
  else if(v.update){label=v.incomplete?tr("Доустановить компоненты"):tr("Обновить до v")+v.latest;action=startPanelUpdate}
  if(label){
    const b=btn(label,"",action);b.id="b_update";b.disabled=panelUpdating;
    if(!v.can_update&&!panelUpdating&&job.phase!=="done"){
      b.disabled=true;box.title=tr("Разработка: обновляйте чекаут через git. Кнопка доступна после установки панели.");
    }
    $("hub_version").replaceChildren(versionInfo(v),b);box.append(btn(tr("Обновить"),"",()=>openSettings("app")));mobile.textContent=label;mobile.style.display="flex";mobile.disabled=b.disabled;
  }
  if(!label)$("hub_version").replaceChildren(versionInfo(v));
  if(action!==refreshInterface){const refresh=btn(tr("Обновить интерфейс"),"pri",refreshInterface);refresh.id="b_refresh_interface";refresh.disabled=panelUpdating;$("hub_version").append(refresh)}
  renderAttachments();
}
let UI_PANEL_VERSION=null;
async function loadVersion(){
  if(versionLoading)return;clearTimeout(versionTimer);
  if(document.hidden){versionTimer=setTimeout(loadVersion,60000);return}
  versionLoading=true;
  try{
    const v=await api("/api/version");if(UI_PANEL_VERSION===null)UI_PANEL_VERSION=v.version;
    renderVersion(v);
  }catch(e){/* The panel is briefly unreachable while its service restarts. */}
  finally{versionLoading=false;versionTimer=setTimeout(loadVersion,panelUpdating?2000:60000)}
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
async function loadServer(){
  try{
    const s=await api("/api/server"),box=$("srv");box.replaceChildren();
    const cc=(s.country||"").toUpperCase();
    if(/^[A-Z]{2}$/.test(cc))box.append(el("span","fl",String.fromCodePoint(...[...cc].map(c=>0x1F1A5+c.charCodeAt(0)))));
    box.append(el("span","ip",s.ip||s.tailscale_ip||"?"),el("span","hn","· "+s.hostname));
    box.title=[s.city&&`${s.city}, ${cc}`,s.org,`Tailscale: ${s.tailscale_ip}`].filter(Boolean).join("\n");
  }catch(e){}
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
  try{repos=(await api("/api/github/repos"+(refresh?"?refresh=1":""))).repos;renderRepos()}catch(e){list.textContent=e.message}
}
function renderRepos(){
  const list=$("gh_list"),q=($("gh_q").value||"").toLowerCase();list.replaceChildren();
  const sel=$("n_git").value;
  for(const r of repos.filter(r=>!q||(r.full_name+" "+r.description).toLowerCase().includes(q)).slice(0,100)){
    const url="https://github.com/"+r.full_name+".git";
    const row=el("div","repo"+(sel===url?" sel":""),el("span","rn",r.full_name));
    if(r.private)row.append(el("span","lock","🔒"));
    row.append(el("span","rm",(r.pushed_at||"").slice(0,10)));
    row.title=r.description||"";row.onclick=()=>pickRepo(r);list.append(row);
  }
  if(!list.children.length)list.textContent=tr("Ничего не найдено");
}
function pickRepo(r){
  const repo=r.full_name.split("/")[1];
  $("n_git").value="https://github.com/"+r.full_name+".git";$("n_proj").value=repo;
  if(!$("n_name").value||$("n_name").dataset.auto){$("n_name").value=repo.replace(/[^A-Za-z0-9_-]/g,"-").slice(0,32);$("n_name").dataset.auto="1"}
  renderRepos();
}
$("n_name").addEventListener("input",e=>delete e.target.dataset.auto);

let newAgent="claude";
function pickAgent(a){
  newAgent=a;for(const b of $("agsel").children)b.classList.toggle("on",b.dataset.a===a);
  $("n_skip_row").style.display=["shell","pi"].includes(a)?"none":"";
  if(!["shell","pi"].includes(a))$("n_skip_lbl").textContent=tr("Без подтверждений (")+AGENTS[a].skip+")";renderSources();
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
  if(ok){$("dlg").close();for(const i of["n_name","n_proj","n_git","n_branch"])$(i).value="";select(ok.name||name)}
}

/* ⌥1..9 — табы, ⌥↑/⌥↓ — пред./след., ⌥T — новая (работает и внутри терминала) */
function hotkeys(e){
  if(!e.altKey||e.ctrlKey||e.metaKey)return;
  const vis=[...$("tabs").querySelectorAll(".tab")].map(t=>t.dataset.session);
  let target=null;
  if(/^Digit[1-9]$/.test(e.code)){
    // Non-US Mac layouts type [ ] { } | etc. with Option+digit; keep those characters.
    if(/^[!-\/:-@\[-`{-~]$/.test(e.key))return;
    target=vis[+e.code.slice(5)-1];
  }
  else if(e.code==="ArrowUp"||e.code==="ArrowDown"){const i=vis.indexOf(active);target=vis[(i+(e.code==="ArrowUp"?-1:1)+vis.length)%vis.length]}
  else if(e.code==="KeyT"){e.preventDefault();e.stopPropagation();openNew();return}
  else return;
  e.preventDefault();e.stopPropagation();if(target)select(target);
}
addEventListener("keydown",hotkeys,true);
let lastMobile=isMobile();
addEventListener("resize",()=>{if(isMobile()!==lastMobile){lastMobile=isMobile();try{mode=deckLocalStorage.getItem("cc.mode."+(lastMobile?"m":"d"))}catch(e){mode=null}show()}});

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
    const response=await fetch(activePath("/api/server-metrics"),{cache:"no-store",signal:controller.signal});
    if(!response.ok)throw new Error("metrics unavailable");
    const data=await response.json();
    const cpu=Number.isFinite(data.cpu_percent)?Math.round(data.cpu_percent)+"%":"—";
    const hasMemory=Number.isFinite(data.memory_used)&&Number.isFinite(data.memory_total)&&data.memory_total>0;
    const ram=hasMemory?Math.round(data.memory_used/data.memory_total*100)+"%":"—";
    const detail=hasMemory?" ("+(data.memory_used/1073741824).toFixed(1)+" / "+(data.memory_total/1073741824).toFixed(1)+tr(" ГиБ)"):"";
    render(cpu,ram,detail);
  }catch(e){render("—","—")}
  finally{clearTimeout(timeout);loadingMetrics=false}
}
loadMetrics();setInterval(loadMetrics,5000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)loadMetrics()});

checkGithubFoot(true);setInterval(checkGithubFoot,5000);
loadUsage();setInterval(loadUsage,60000);loadLM().then(renderInteg);setInterval(()=>{if(!document.hidden&&!$("settings_dlg").open)loadLM(false).then(renderInteg)},1000);
loadServer();setInterval(loadServer,3600000);
loadVersion();
loadIntegrations();
document.addEventListener("visibilitychange",()=>{if(!document.hidden){checkGithubFoot(true);loadUsage();load();checkInterfaceVersion();loadVersion();if(!$("integrations_dlg").hidden&&!telegramDirty)loadIntegrations()}});
load();setInterval(load,2500);

loadDeckSettings().catch(e=>toast(e.message));
