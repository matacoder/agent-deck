// Project files of the open session: browse folders, open a text file, copy or paste into it and save.
// The server keeps everything inside the home folder and refuses to overwrite a file changed meanwhile.
const files={session:null,listing:null,file:null,loading:false};

function formatSize(bytes){
  return bytes<1024?bytes+" B":bytes<1048576?(bytes/1024).toFixed(1)+" KB":(bytes/1048576).toFixed(1)+" MB";
}
function homeRelative(path,home){return path===home?"~":path.startsWith(home+"/")?"~/"+path.slice(home.length+1):path}
function filesDirty(){return Boolean(files.file&&files.file.content!==files.file.saved)}

async function openFiles(){
  if(!active)return;
  files.session=active;files.file=null;files.listing=null;
  if(!$("files_dlg").open)$("files_dlg").showModal();
  await loadFolder("");
}
async function loadFolder(path){
  if(files.loading)return;
  files.loading=true;
  try{files.listing=await api("/api/files?name="+encodeURIComponent(files.session)+"&path="+encodeURIComponent(path));files.file=null}
  catch(e){if(e.message!==STALE)toast(e.message)}
  finally{files.loading=false;renderFiles()}
}
async function openFile(path){
  try{const data=await api("/api/file?path="+encodeURIComponent(path));files.file={...data,saved:data.content,isNew:false}}
  catch(e){if(e.message!==STALE)toast(e.message);return}
  renderFiles();
}
async function leaveFile(){
  if(filesDirty()&&!await confirmAction(tr("Изменения не сохранены. Закрыть без сохранения?"),{confirm:tr("Закрыть без сохранения"),danger:true}))return false;
  files.file=null;renderFiles();return true;
}
async function saveFile(){
  const file=files.file;if(!file)return;
  try{
    const result=await api("/api/file_save",{path:file.path,content:file.content,hash:file.isNew?null:file.hash});
    Object.assign(file,{hash:result.hash,saved:file.content,isNew:false});
    toast(tr("Файл сохранён"),"success");
  }catch(e){if(e.message!==STALE)toast(e.message)}
  // Only the button changes: re-rendering would move the cursor and scroll of the open text.
  if(files.file===file&&files.saveButton)files.saveButton.disabled=!filesDirty();
}
function newFile(name){
  name=name.trim();
  if(!name||name.includes("/")||name==="."||name===".."){toast(tr("Введите имя файла без папок"));return}
  const folder=files.listing.path;
  files.file={path:folder+"/"+name,content:"",saved:"",hash:null,isNew:true};renderFiles();
}
async function closeFiles(){if(!files.file||await leaveFile())$("files_dlg").close()}
function fileButton(label,cls,run,icon){
  const b=el("button",cls,...(icon?[svgIcon(icon)]:[]),el("span","",label));b.type="button";b.onclick=run;return b;
}

function renderFiles(){
  const box=$("files_body"),listing=files.listing;box.replaceChildren();
  if(!listing){box.append(el("p","files-empty",tr("Загрузка…")));return}
  if(files.file)return renderEditor(box,listing);
  const crumbs=el("div","files-path",el("code","",homeRelative(listing.path,listing.home)));
  if(listing.parent)crumbs.prepend(fileButton(tr("Вверх"),"files-up",()=>loadFolder(listing.parent),"arrow-up"));
  const create=el("form","files-new");
  const input=el("input","");input.type="text";input.placeholder=tr("Имя нового файла, например .env");
  input.setAttribute("autocapitalize","none");input.setAttribute("autocorrect","off");input.spellcheck=false;
  create.append(input,fileButton(tr("Создать"),"",()=>newFile(input.value),"plus"));
  create.onsubmit=e=>{e.preventDefault();newFile(input.value)};
  const list=el("div","files-list");
  for(const entry of listing.entries){
    const path=listing.path+"/"+entry.name;
    const row=fileButton(entry.name,"files-row"+(entry.dir?" dir":""),()=>entry.dir?loadFolder(path):openFile(path),entry.dir?"folder":"file");
    if(!entry.dir)row.append(el("span","files-size",formatSize(entry.size)));
    list.append(row);
  }
  if(!listing.entries.length)list.append(el("p","files-empty",tr("Папка пуста")));
  if(listing.truncated)list.append(el("p","files-empty",tr("Показаны первые 2000 элементов")));
  box.append(crumbs,create,list);
}
// Files open for reading: wrapped lines with numbers, selectable without the keyboard popping up and the
// layout jumping. Editing is a separate step, and a new file starts in it.
function renderEditor(box,listing){
  const file=files.file,name=file.path.split("/").pop();
  const head=el("div","files-path",fileButton(tr("К папке"),"files-up",leaveFile,"arrow-up"),el("code","",homeRelative(file.path,listing.home)),
    el("span","git-font",fileButton("A−","",()=>codeFont(-1)),fileButton("A+","",()=>codeFont(1))));
  applyCodeFont();
  if(!file.isNew&&!file.editing)return renderReader(box,head,file);
  const area=el("textarea","files-text");area.value=file.content;area.spellcheck=false;
  area.setAttribute("autocapitalize","none");area.setAttribute("autocorrect","off");area.setAttribute("aria-label",name);
  const save=fileButton(tr("Сохранить"),"pri",saveFile);save.disabled=!filesDirty()&&!file.isNew;files.saveButton=save;
  area.oninput=()=>{file.content=area.value;save.disabled=!filesDirty()&&!file.isNew};
  const copy=fileButton(tr("Копировать"),"",()=>{
    const text=area.selectionStart!==area.selectionEnd?area.value.slice(area.selectionStart,area.selectionEnd):area.value;
    copyText(text);
  });
  box.append(head,area,el("div","acts",copy,save));
}
function renderReader(box,head,file){
  const view=el("div","files-view");
  file.content.split("\n").forEach((line,i,lines)=>{
    if(i===lines.length-1&&!line&&lines.length>1)return;  // The newline that ends the file is not a line.
    view.append(el("div","fl",el("span","ln",String(i+1)),el("span","code",line||" ")));
  });
  const copy=fileButton(tr("Копировать"),"",()=>{
    const selected=String(getSelection()||"");
    copyText(selected&&view.contains(getSelection().anchorNode)?selected:file.content);
  });
  const change=fileButton(tr("Изменить"),"pri",()=>{file.editing=true;renderFiles()});
  box.append(head,view,el("div","acts",copy,change));
}
async function copyText(text){
  try{if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(text);toast(tr("Скопировано: {0} симв.",[text.length]),"success");return}}catch(e){}
  if(execCopy(text,document))toast(tr("Скопировано: {0} симв.",[text.length]),"success");else toast(tr("Браузер запретил копирование"));
}

if(typeof module!=="undefined")module.exports={formatSize,homeRelative};
