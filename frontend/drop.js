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
// Files in a paste: a screenshot or a copied picture. Text with a picture beside it (a copied table, a
// document fragment) stays text. Pure for tests.
function pastedFiles(data){
  const files=Array.from(data?.files||[]);
  return files.length&&!(data.getData&&data.getData("text/plain"))?files:[];
}
// Pictures inside copied rich text (a chat message, a page fragment): the sources of its <img> tags, each
// once. A copied table has none, so its rendering stays out. Pure for tests.
function pastedPictures(data){
  const html=data?.getData?data.getData("text/html"):"";
  if(!html||!/<img/i.test(html))return [];
  const page=new DOMParser().parseFromString(html,"text/html");  // Inert: nothing is loaded while parsing.
  const sources=Array.from(page.querySelectorAll("img[src]"),img=>img.getAttribute("src"));
  return [...new Set(sources.filter(src=>/^(data:image\/|https?:\/\/|blob:)/i.test(src)))];
}
// How many of the pictures fit, given what is already attached. Pure for tests.
function pictureRoom(attached,wanted){return Math.max(0,Math.min(wanted,4-attached))}
const SMALL_PICTURE=48;
// Chats draw emoji and avatars as pictures too; those are not what was copied.
async function isSmallPicture(blob){
  try{const bitmap=await createImageBitmap(blob),small=Math.max(bitmap.width,bitmap.height)<SMALL_PICTURE;bitmap.close();return small}
  catch(e){return false}
}
// A site that lets other pages read its pictures, the clipboard's own data, or this page's blob. The
// address of this panel stays out of the request.
async function fetchPicture(src,index){
  const response=await fetch(src,{credentials:"omit",referrerPolicy:"no-referrer"});
  if(!response.ok)throw new Error("HTTP "+response.status);
  const blob=await response.blob();
  if(!blob.type.startsWith("image/"))throw new Error("not a picture");
  if(await isSmallPicture(blob))return null;
  return new File([blob],"pasted-"+index+"."+blob.type.slice(6).split(/[+;]/)[0],{type:blob.type});
}
async function attachPastedPictures(sources,ready){
  const name=active,deck=selectedDeck,files=ready.slice();
  let wanted=ready.length;
  for(const [index,src] of sources.entries()){
    try{const file=await fetchPicture(src,index+1);if(file){files.push(file);wanted++}}
    catch(e){wanted++}
  }
  if(name!==active||deck!==selectedDeck||!wanted)return;
  const fit=files.slice(0,pictureRoom(attachmentsFor(name).length,files.length));
  if(fit.length<wanted)toast(tr("Картинок приложено: {0} из {1}. Остальные сохраните и приложите файлами",[fit.length,wanted]));
  if(fit.length)await uploadImages(fit);
}
// A paste anywhere on the page or in the live terminal attaches the picture, not only in the message field.
function onFilePaste(e){
  const data=e.clipboardData,files=pastedFiles(data),sources=files.length?[]:pastedPictures(data);
  if(!files.length&&!sources.length)return;
  const target=dropTarget(cur(),dropBlocked());
  if(sources.length){
    // The text goes where a paste always goes; its pictures are attached beside it.
    const ready=Array.from(data.files||[]).filter(file=>file.type.startsWith("image/"));
    if(target.ok)attachPastedPictures(ready.length?[]:sources,ready);
    return;
  }
  // Otherwise the terminal would receive an empty paste, and a field of an open dialog the file's name.
  e.preventDefault();e.stopPropagation();
  if(!target.ok){toast(tr(target.text));return}
  uploadImages(files);
}
function watchFileDrops(win){
  win.addEventListener("paste",onFilePaste,true);
  win.addEventListener("dragenter",onFileDrag);win.addEventListener("dragover",onFileDrag);
  win.addEventListener("drop",onFileDrop);
  win.addEventListener("dragleave",e=>{if(!e.relatedTarget)hideDropZone()});
  win.addEventListener("dragstart",()=>{dragFromPage=true});
  win.addEventListener("dragend",()=>{dragFromPage=false;hideDropZone()});
}

if(typeof module!=="undefined")module.exports={dropTarget,dragHasFiles,pastedFiles,pastedPictures,pictureRoom};
