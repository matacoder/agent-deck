// Search in the open session's whole output (tmux scrollback) and the quick switcher (Alt+K, Ctrl/Cmd+K).
// Output is shown with textContent only; the server matches plain text, newest first.
// Bundled before app.js; nothing here runs at load time.
const outputSearch={session:null,query:"",seq:0,result:null,error:"",busy:false};

function openOutputSearch(){
  if(!active)return;
  if(outputSearch.session!==active)Object.assign(outputSearch,{session:active,query:"",result:null,error:""});
  if(!$("search_dlg").open)$("search_dlg").showModal();
  const input=$("search_q");input.value=outputSearch.query;renderOutputSearch();
  setTimeout(()=>{input.focus();input.select()},0);
}
async function runOutputSearch(){
  const query=$("search_q").value.trim();
  if(!query)return;
  const seq=++outputSearch.seq;Object.assign(outputSearch,{query,busy:true,error:""});renderOutputSearch();
  try{
    const result=await api("/api/scrollback?"+new URLSearchParams({name:outputSearch.session,q:query}),null,false,{timeout:60000});
    if(seq===outputSearch.seq)outputSearch.result=result;
  }catch(e){if(seq===outputSearch.seq&&e.message!==STALE)outputSearch.error=e.message}
  if(seq===outputSearch.seq){outputSearch.busy=false;renderOutputSearch()}
}
// The matched part in a <mark>; when case folding changes the length, the line stays plain.
function markMatch(text,query){
  const lower=text.toLowerCase(),needle=query.toLowerCase(),at=lower.indexOf(needle);
  if(!needle||at<0||lower.length!==text.length)return [text||" "];
  return [text.slice(0,at),el("mark","",text.slice(at,at+needle.length)),text.slice(at+needle.length)];
}
function renderOutputSearch(){
  const box=$("search_body"),state=outputSearch,result=state.result;box.replaceChildren();
  if(state.busy){box.append(el("p","files-empty",tr("Ищу…")));return}
  if(state.error){box.append(errorWithRetry(state.error,runOutputSearch));return}
  if(!result){box.append(el("p","files-empty",tr("Ищет по всему выводу сессии, включая прокрутку, начиная с последних строк")));return}
  if(!result.total){box.append(el("p","files-empty",tr("Ничего не найдено")));return}
  box.append(el("p","git-meta",result.total>result.matches.length?tr("Найдено: {0}, показаны последние {1}",[result.total,result.matches.length]):tr("Найдено: {0}",[result.total])));
  for(const hit of result.matches){
    const lines=el("div","search-lines",...hit.before.map(t=>el("div","ctx",t||" ")),el("div","hit",...markMatch(hit.text,result.query)),...hit.after.map(t=>el("div","ctx",t||" ")));
    const copy=fileButton(tr("Копировать"),"search-copy",()=>copyText(hit.text));
    box.append(el("div","search-result",el("div","git-meta",tr("Строка {0} из {1}",[hit.line,result.lines]),copy),lines));
  }
}

// Every word must appear in the title or the hint, in any order.
function matchPalette(items,query){
  const words=query.toLowerCase().split(/\s+/).filter(Boolean);
  return items.filter(item=>{const text=(item.label+" "+(item.hint||"")).toLowerCase();return words.every(w=>text.includes(w))});
}
const palette={items:[],shown:[],index:0};
function paletteItems(){
  const items=[];
  for(const s of sessions)items.push({label:sessionTitle(s),hint:currentDeckName()+" · "+shortPath(s.path||""),icon:"terminal",run:()=>select(s.name)});
  for(const deck of otherDecks)if(!deck.error)for(const s of deck.sessions)
    items.push({label:sessionTitle(s),hint:deck.name+" · "+shortPath(s.path||""),icon:"monitor",run:()=>openDeckSession(deck.id,s.name)});
  const actions=[[tr("Новая сессия"),"plus",openNew,true],[tr("Файлы проекта"),"folder",openFiles,active],[tr("История изменений"),"history",openHistory,active],
    [tr("Поиск в выводе"),"search",openOutputSearch,active],[tr("Настройки"),"gear",()=>openSettings(),true]];
  for(const [label,icon,run,on] of actions)if(on)items.push({label,hint:tr("Действие"),icon,run});
  return items;
}
function openPalette(){
  if($("palette_dlg").open){$("palette_dlg").close();return}
  if(document.querySelector("dialog[open]"))return;  // A switch from inside another dialog would leave it behind.
  palette.items=paletteItems();
  const input=$("palette_q");input.value="";filterPalette();
  $("palette_dlg").showModal();setTimeout(()=>input.focus(),0);
}
function filterPalette(){palette.shown=matchPalette(palette.items,$("palette_q").value).slice(0,50);palette.index=0;renderPalette()}
function renderPalette(){
  const list=$("palette_list");list.replaceChildren();
  palette.shown.forEach((item,i)=>{
    const row=el("button","palette-row"+(i===palette.index?" on":""),svgIcon(item.icon),el("span","palette-label",item.label),el("span","palette-hint",item.hint));
    row.type="button";row.setAttribute("role","option");row.setAttribute("aria-selected",String(i===palette.index));
    row.onclick=()=>runPalette(i);list.append(row);
  });
  if(!palette.shown.length)list.append(el("p","files-empty",tr("Ничего не найдено")));
  list.querySelector(".on")?.scrollIntoView?.({block:"nearest"});
}
function runPalette(i){const item=palette.shown[i];if(!item)return;$("palette_dlg").close();item.run()}
function paletteKey(e){
  if(e.key==="ArrowDown"||e.key==="ArrowUp"){
    e.preventDefault();const n=palette.shown.length;if(!n)return;
    palette.index=(palette.index+(e.key==="ArrowDown"?1:-1)+n)%n;renderPalette();
  }else if(e.key==="Enter"&&!e.isComposing){e.preventDefault();runPalette(palette.index)}
}

if(typeof module!=="undefined")module.exports={matchPalette,markMatch};
