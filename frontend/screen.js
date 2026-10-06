// Screen view: tmux output with ANSI colours, joined wrapped URLs, image paths and TUI rules.
// Bundled before app.js; nothing here runs at load time except constants.
function screenSkeleton(){
  const box=el("div","screen-skeleton");box.setAttribute("role","status");
  for(const width of [72,48,86,64,38,80,56]){const line=el("span","sk-line");line.style.width=width+"%";box.append(line)}
  box.append(el("span","sk-label",tr("Загружаю экран сессии…")));
  return box;
}
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
const atBottom=p=>p.scrollTop+p.clientHeight>=p.scrollHeight-40;
function updateJump(fresh){
  const p=$("pre"),j=$("jump"),away=!atBottom(p);
  j.classList.toggle("on",away);
  if(!away)j.classList.remove("fresh");else if(fresh)j.classList.add("fresh");
}
function jumpToLatest(){const p=$("pre");p.scrollTo({top:p.scrollHeight,behavior:"smooth"});$("jump").classList.remove("on","fresh")}
function updateScreen(s,force){
  const p=$("pre"),stick=force||atBottom(p);
  // Nothing known about this session's screen yet: keep the skeleton instead of a blank or stale view.
  if(s.preview===undefined&&s.preview_ansi===undefined){
    if(!p.querySelector(".screen-skeleton")){p.dataset.raw="\u0000";p.replaceChildren(screenSkeleton())}
    return;
  }
  const raw=s.preview_ansi??unwrapUrls(s.preview||"");
  // Rebuilding would drop a selection the user is making to copy text; catch up once it is released.
  const selection=getSelection(),selecting=selection&&!selection.isCollapsed&&p.contains(selection.anchorNode);
  const changed=p.dataset.raw!==raw&&!selecting;
  if(changed){
    p.dataset.raw=raw;p.replaceChildren();
    const lines=joinImageLines(joinUrlLines(ansiLines(raw)));screenImages=[];
    // A session known only from another computer's list has no preview yet: show nothing, not "empty".
    if(!lines.length&&(s.preview!==undefined||s.preview_ansi!==undefined))p.append(el("div","preview-empty",tr("В tmux пока нет текста. Терминал открывается в меню ⋯.")));
    for(const runs of lines){
      const line=runs.map(r=>r.text).join("").trimEnd();
      // TUI rules (Claude's input box etc.) would wrap into a stack of lines on a phone: draw them as one rule
      const boxN=(line.match(BOX_CHARS)||[]).length;
      if(line.length>=8&&boxN&&BOX_LINE.test(line)){if(!(p.lastChild&&p.lastChild.className==="hr"))p.append(el("div","hr"));continue}
      if(line.length>=20&&boxN/line.length>=0.8){p.append(el("div","hrl",line.replace(BOX_CHARS,"").trim()));continue}
      const d=el("div","ln");let i=0;
      const urls=[...line.matchAll(URL_RE)].map(m=>({index:m.index,url:cleanUrl(m[0])}));
      const images=imageMatches(line,urls.map(u=>[u.index,u.index+u.url.length]));
      for(const m of [...urls,...images].sort((x,y)=>x.index-y.index)){
        appendStyledRange(d,runs,i,m.index);
        if(m.url){
          const a=document.createElement("a");a.href=resolvePanelLink(m.url);a.target="_blank";a.rel="noopener";
          appendStyledRange(a,runs,m.index,m.index+m.url.length);d.append(a);i=m.index+m.url.length;
        }else{d.append(imageLink(s.name,m.path,runs,m.index,m.index+m.path.length));i=m.index+m.path.length}
      }
      appendStyledRange(d,runs,i,line.length);p.append(d);
      if(images.length){
        for(const m of images)if(!screenImages.includes(m.path))screenImages.push(m.path);
        p.append(imageStrip(s.name,images.map(m=>m.path)));
      }
    }
  }
  if(stick)p.scrollTop=p.scrollHeight;
  updateJump(changed&&!stick);
}
