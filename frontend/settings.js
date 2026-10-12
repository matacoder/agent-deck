async function saveDirectorySetting({request,input,button,notify,translate}){
  button.disabled=true;
  try{
    const data=await request("/api/project_directory",{directory:input.value});
    input.value=data.directory;
    notify(translate("Папка проектов сохранена"),"success");
  }catch(e){notify(e.message)}finally{button.disabled=false}
}

async function saveSessionName({request,input,button,dialog,refresh,notify}){
  button.disabled=true;
  try{await request("/api/rename",{name:dialog.dataset.session,title:input.value.trim()});dialog.close();await refresh()}
  catch(e){notify(e.message)}finally{button.disabled=false}
}

async function refreshModelCatalog(request){
  const current=await request("/api/lmstudio");
  await Promise.allSettled((current.profiles||[]).map(profile=>request("/api/lm_probe",{id:profile.id})));
  return request("/api/lmstudio");
}

function placeSessionKeys({row,composer,screen,terminal,wrap,reconnect,mode,active}){
  const live=active&&mode==="term";
  // Moved only when it changes place: putting a node where it already is still takes it out of the page for
  // a moment, and the message field inside it loses the keyboard in the middle of a word. When it does move,
  // the field keeps its focus and caret.
  const target=live?terminal:screen,node=composer||row;
  if(node.parentNode!==target){
    const focused=node.ownerDocument?.activeElement,inside=focused&&node.contains(focused)?focused:null;
    const caret=inside&&typeof inside.selectionStart==="number"?[inside.selectionStart,inside.selectionEnd]:null;
    target.append(node);
    if(inside){inside.focus({preventScroll:true});if(caret)try{inside.setSelectionRange(caret[0],caret[1])}catch(e){}}
  }
  terminal.hidden=!live;
  wrap.hidden=live;
  if(reconnect)reconnect.hidden=!live;
}

function execCopy(text,doc){
  const ta=doc.createElement("textarea");ta.value=text;ta.setAttribute("readonly","");
  ta.style.cssText="position:fixed;top:-1000px;left:0;opacity:0";(doc.querySelector("dialog[open]:not(.docked)")||doc.body).appendChild(ta);ta.select();
  let ok=false;try{ok=doc.execCommand("copy")}catch(e){}
  ta.remove();return ok;
}

function renderClosedDraftList({box,drafts,copy,remove,translate}){
  box.replaceChildren();
  if(!drafts.size){const empty=document.createElement("p");empty.textContent=translate("Нет сохранённых черновиков");box.append(empty);return}
  for(const [name,text] of drafts){
    const item=document.createElement("div");item.className="closed-draft";
    const title=document.createElement("strong");title.textContent=name;
    const preview=document.createElement("pre");preview.textContent=text;
    const actions=document.createElement("div");actions.className="acts";
    const copyButton=document.createElement("button");copyButton.type="button";copyButton.className="pri";copyButton.textContent=translate("Скопировать");copyButton.onclick=()=>copy(text);
    const removeButton=document.createElement("button");removeButton.type="button";removeButton.className="danger";removeButton.textContent=translate("Удалить");removeButton.onclick=()=>remove(name);
    actions.append(copyButton,removeButton);item.append(title,preview,actions);box.append(item);
  }
}

if(typeof module!=="undefined")module.exports={saveDirectorySetting,saveSessionName,refreshModelCatalog,placeSessionKeys,renderClosedDraftList,execCopy};
