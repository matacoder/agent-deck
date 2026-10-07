// Files dragged onto the window (desktop, iPad Split View) are attached to the open session, the same
// way as the paperclip and paste. The terminal is a frame with its own document, so it is watched too.
// Bundled before app.js; nothing here runs at load time.
let dropHideTimer=null;
function dragHasFiles(e){return Array.from(e.dataTransfer?.types||[]).includes("Files")}
// Where a drop would land, or why it cannot; pure for tests.
function dropTarget(session,blocked){
  if(blocked)return {ok:false,text:"Дождитесь окончания отправки или загрузки"};
  if(!session)return {ok:false,text:"Сначала откройте сессию"};
  if(agentOf(session)==="shell")return {ok:false,text:"Выберите сессию Claude или Codex"};
  return {ok:true,text:"Отпустите, чтобы приложить к «{0}»",args:[sessionTitle(session)]};
}
function showDropZone(target){
  const zone=$("drop_zone");
  $("drop_title").textContent=tr(target.text,target.args||[]);
  zone.classList.toggle("blocked",!target.ok);zone.hidden=false;
  // dragover repeats while the pointer is over the window; when it stops, the drag has left.
  clearTimeout(dropHideTimer);dropHideTimer=setTimeout(hideDropZone,250);
}
function hideDropZone(){clearTimeout(dropHideTimer);$("drop_zone").hidden=true}
function dropBlocked(){return sending||uploading||panelUpdating||Boolean(document.querySelector("dialog[open]"))}
function onFileDrag(e){
  if(!dragHasFiles(e))return;
  e.preventDefault();
  const target=dropTarget(cur(),dropBlocked());
  e.dataTransfer.dropEffect=target.ok?"copy":"none";
  showDropZone(target);
}
function onFileDrop(e){
  if(!dragHasFiles(e))return;
  e.preventDefault();hideDropZone();
  const target=dropTarget(cur(),dropBlocked()),files=Array.from(e.dataTransfer.files||[]);
  if(!target.ok){toast(tr(target.text));return}
  uploadImages(files);
}
function watchFileDrops(win){
  win.addEventListener("dragenter",onFileDrag);win.addEventListener("dragover",onFileDrag);
  win.addEventListener("drop",onFileDrop);
}

if(typeof module!=="undefined")module.exports={dropTarget,dragHasFiles};
