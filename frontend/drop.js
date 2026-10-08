// Files dragged onto the window (desktop, iPad Split View) are attached to the open session, the same
// way as the paperclip and paste. The terminal is a frame with its own document, so it is watched too.
// Bundled before app.js; nothing here runs at load time.
let dropHideTimer=null,dragFromPage=false;
// A picture dragged from the page itself (a thumbnail) is not a file from outside.
function dragHasFiles(e){return !dragFromPage&&Array.from(e.dataTransfer?.types||[]).includes("Files")}
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
  // A held-still drag repeats dragover rarely; leaving the window is caught by dragleave.
  clearTimeout(dropHideTimer);dropHideTimer=setTimeout(hideDropZone,1000);
}
function hideDropZone(){clearTimeout(dropHideTimer);$("drop_zone").hidden=true}
function dropBlocked(){return sending||uploading||panelUpdating||Boolean(document.querySelector("dialog[open]:not(.docked)"))}
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
  win.addEventListener("dragleave",e=>{if(!e.relatedTarget)hideDropZone()});
  win.addEventListener("dragstart",()=>{dragFromPage=true});
  win.addEventListener("dragend",()=>{dragFromPage=false;hideDropZone()});
}

if(typeof module!=="undefined")module.exports={dropTarget,dragHasFiles};
