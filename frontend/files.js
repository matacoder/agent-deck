// Project files of the open session: browse folders, open a text file, copy or paste into it and save.
// The server keeps everything inside the home folder and refuses to overwrite a file changed meanwhile.
// seq: each opening and folder load gets a number; an answer for an older one (another session, a
// folder left meanwhile) is dropped so it can never fill the dialog or decide where a new file goes.
const files={session:null,listing:null,file:null,seq:0,error:"",path:""};

function formatSize(bytes){
  return bytes<1024?bytes+" B":bytes<1048576?(bytes/1024).toFixed(1)+" KB":(bytes/1048576).toFixed(1)+" MB";
}
// Each folder on the way from home is one tap away instead of several "Up" taps.
function breadcrumbs(listing){
  const nav=el("nav","files-crumbs");nav.setAttribute("aria-label",tr("Путь"));
  const rest=listing.path===listing.home?[]:listing.path.slice(listing.home.length+1).split("/");
  const parts=[["~",listing.home],...rest.map((name,i)=>[name,listing.home+"/"+rest.slice(0,i+1).join("/")])];
  parts.forEach(([name,path],i)=>{
    if(i)nav.append(el("span","sep","/"));
    if(i===parts.length-1){nav.append(el("span","here",name));return}
    const link=el("button","",name);link.type="button";link.onclick=()=>loadFolder(path);nav.append(link);
  });
  return nav;
}
function homeRelative(path,home){return path===home?"~":path.startsWith(home+"/")?"~/"+path.slice(home.length+1):path}
function filesDirty(){return Boolean(files.file&&files.file.content!==files.file.saved)}

async function startFiles(){
  dropPreview();files.session=active;files.file=null;files.listing=null;files.creating=false;
  await loadFolder("");
}
async function loadFolder(path){
  const seq=++files.seq;files.error="";files.path=path;
  if(!files.listing)renderFiles();
  try{
    const listing=await api("/api/files?name="+encodeURIComponent(files.session)+"&path="+encodeURIComponent(path),null,false,{timeout:60000});
    if(seq!==files.seq)return;
    files.listing=listing;files.file=null;
  }catch(e){if(seq!==files.seq)return;if(e.message!==STALE){files.error=e.message;if(files.listing)toast(e.message)}}
  renderFiles();
}
const PREVIEW_FILE=/\.(png|jpe?g|gif|webp|pdf)$/i;
async function openFile(path){
  const seq=++files.seq,preview=PREVIEW_FILE.test(path);
  try{
    const data=await api((preview?"/api/file_preview?path=":"/api/file?path=")+encodeURIComponent(path),null,false,{timeout:60000});
    if(seq!==files.seq)return;
    files.file=preview?{path:data.path,preview:previewBlob(data)}:{...data,saved:data.content,isNew:false,rendered:isMarkdown(data.path)};
  }catch(e){
    if(seq!==files.seq||e.message===STALE)return;
    // Not text and not a picture or PDF (an archive, a spreadsheet): it can still be downloaded.
    if(!preview&&!(e instanceof OfflineError)){files.file={path,download:true,error:e.message};renderFiles()}else toast(e.message);
    return;
  }
  renderFiles();
}
// The server checked the content; the Blob gets that type and nothing else (never HTML or SVG).
function previewBlob(data){
  const type=["application/pdf","image/png","image/jpeg","image/gif","image/webp"].includes(data.type)?data.type:"application/octet-stream";
  // A plain loop: a callback per byte freezes a phone for seconds on a 10 MB file.
  const raw=atob(data.data),bytes=new Uint8Array(raw.length);
  for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);
  return {type,size:data.size,url:URL.createObjectURL(new Blob([bytes],{type}))};
}
function dropPreview(){if(files.file?.preview)URL.revokeObjectURL(files.file.preview.url)}
async function leaveFile(){
  if(filesDirty()&&!await confirmAction(tr("Изменения не сохранены. Закрыть без сохранения?"),{confirm:tr("Закрыть без сохранения"),danger:true}))return false;
  dropPreview();files.file=null;
  // The folder may have changed (a new file was just saved): show it as it is now.
  if(files.listing){loadFolder(files.listing.path);return true}
  renderFiles();return true;
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
  files.creating=false;files.file={path:folder+"/"+name,content:"",saved:"",hash:null,isNew:true};renderFiles();
}
function fileButton(label,cls,run,icon){
  const b=el("button",cls,...(icon?[svgIcon(icon)]:[]),el("span","",label));b.type="button";b.onclick=run;return b;
}

function renderFiles(){
  const box=$("files_body"),listing=files.listing;box.replaceChildren();
  if(!listing&&files.error){box.append(errorWithRetry(files.error,()=>loadFolder(files.path)));return}
  if(!listing){box.append(el("p","files-empty",tr("Загрузка…")));return}
  if(files.file)return renderEditor(box,listing);
  const crumbs=el("div","files-path",breadcrumbs(listing));
  if(listing.parent)crumbs.prepend(fileButton(tr("Вверх"),"files-up",()=>loadFolder(listing.parent),"arrow-up"));
  // Creating a file is occasional: a small button in the path row, the name field only once asked for.
  let create;
  if(files.creating){
    create=el("form","files-new");
    const input=el("input","");input.type="text";input.placeholder=tr("Новый файл");
    input.setAttribute("autocapitalize","none");input.setAttribute("autocorrect","off");input.spellcheck=false;input.setAttribute("aria-label",tr("Новый файл"));
    create.append(input,fileButton(tr("Создать"),"",()=>newFile(input.value),"plus"));
    create.onsubmit=e=>{e.preventDefault();newFile(input.value)};
    setTimeout(()=>input.focus(),0);
  }else crumbs.append(fileButton(tr("Файл"),"files-up files-add",()=>{files.creating=true;renderFiles()},"plus"));
  const list=el("div","files-list");
  for(const entry of listing.entries){
    const path=listing.path+"/"+entry.name;
    const row=fileButton(entry.name,"files-row"+(entry.dir?" dir":""),()=>entry.dir?loadFolder(path):openFile(path),entry.dir?"folder":"file");
    if(entry.dir){list.append(row);continue}
    row.append(el("span","files-size",formatSize(entry.size)));
    // Any file straight from the list, without opening it first (a video, an archive, a huge log).
    const save=el("button","files-download",svgIcon("download"));save.type="button";
    save.setAttribute("aria-label",tr("Скачать файл {0}",[entry.name]));save.title=tr("Скачать");
    save.onclick=()=>downloadFile(null,path);
    list.append(el("div","files-item",row,save));
  }
  if(!listing.entries.length)list.append(el("p","files-empty",tr("Папка пуста")));
  if(listing.truncated)list.append(el("p","files-empty",tr("Показаны первые 2000 элементов")));
  box.append(...[crumbs,create,list].filter(Boolean));
}
// Files open for reading: wrapped lines with numbers, selectable without the keyboard popping up and the
// layout jumping. Editing is a separate step, and a new file starts in it.
function renderEditor(box,listing){
  const file=files.file,name=file.path.split("/").pop();
  const head=el("div","files-path",fileButton(tr("К папке"),"files-up",leaveFile,"arrow-up"),el("code","",homeRelative(file.path,listing.home)));
  applyCodeFont();
  if(file.preview)return renderPreview(box,head,file);
  if(file.download){box.append(head,el("p","files-empty",file.error),el("div","acts",fileButton(tr("Скачать"),"pri",()=>downloadFile(null,file.path))));return}
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
  let view=el("div","files-view");
  if(file.rendered)view=renderMarkdown(file.content);
  else view.style.setProperty("--ln",Math.max(2,String(file.content.split("\n").length).length));
  if(!file.rendered)file.content.split("\n").forEach((line,i,lines)=>{
    if(i===lines.length-1&&!line&&lines.length>1)return;  // The newline that ends the file is not a line.
    view.append(el("div","fl",el("span","ln",String(i+1)),el("span","code",line||" ")));
  });
  if(isMarkdown(file.path))head.append(fileButton(file.rendered?tr("Текст"):tr("Просмотр"),"files-up",()=>{file.rendered=!file.rendered;renderFiles()}));
  const copy=fileButton(tr("Копировать"),"",()=>{
    const selected=String(getSelection()||"");
    copyText(selected&&view.contains(getSelection().anchorNode)?selected:file.content);
  });
  const change=fileButton(tr("Изменить"),"pri",()=>{file.editing=true;renderFiles()});
  const download=fileButton(tr("Скачать"),"",()=>downloadFile(null,file.path));
  box.append(head,view,el("div","acts",copy,download,change));
}
// Images show here; a PDF opens from a link, a direct tap, so no popup blocker stands in the way.
function renderPreview(box,head,file){
  const name=file.path.split("/").pop(),{type,url,size}=file.preview;
  box.append(head);
  if(type.startsWith("image/")){const img=el("img","files-image");img.src=url;img.alt=name;box.append(el("div","files-view files-picture",img))}
  else box.append(el("p","files-empty",tr("PDF-документ · {0}",[formatSize(size)])));
  const open=el("a","btn pri",tr("Открыть"));open.href=url;open.target="_blank";open.rel="noopener";
  box.append(el("div","acts",fileButton(tr("Скачать"),"",()=>downloadFile(null,file.path)),...(type==="application/pdf"?[open]:[])));
}
// Paths to any file that agents print ("/home/me/plan.pdf", "docs/notes.md"): a tap downloads it.
// A folder in the path keeps ordinary words ("v1.2", "e.g.") from turning into links.
const FILE_PATH_RE=/(?<![\w/.~@+-])(?:~\/|\/|\.\.?\/)?(?:[\w.@+-]+\/)+[\w.@+-]*\w\.[A-Za-z0-9]{1,10}(?![\w-]|\.\w)/g;
function fileMatches(text,taken=[]){
  return [...text.matchAll(FILE_PATH_RE)].map(m=>({index:m.index,file:m[0]}))
    .filter(({index,file})=>!taken.some(([a,b])=>index<b&&index+file.length>a));
}
function fileLink(session,path,runs,from,to){
  const link=el("a","file-link");link.href="#";link.title=tr("Скачать файл {0}",[path.split("/").pop()]);
  appendStyledRange(link,runs,from,to);
  link.onclick=event=>{event.preventDefault();downloadFile(session,path)};
  return link;
}
// Fetched first, so a missing or too large file is a message here, not an error page in its place.
// A large file takes a while with nothing to see: a note says it started, and more taps do not start it again.
const downloading=new Set();
async function downloadFile(session,path){
  const url=activePath("/api/download?"+(session?"name="+encodeURIComponent(session)+"&":"")+"path="+encodeURIComponent(path));
  if(downloading.has(url))return;
  const name=path.split("/").pop();
  downloading.add(url);toast(tr("Скачиваю файл {0}…",[name]),"info");
  try{
    const r=await fetch(url,{cache:"no-store"});
    if(!r.ok){let message="";try{message=(await r.json()).error}catch(e){}toast(message||tr("Не удалось скачать файл"));return}
    const blob=await r.blob();
    if(await shareDownload(blob,name))return;
    const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=name;
    document.body.append(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(a.href),60000);
  }catch(e){toast(tr("Не удалось скачать файл"))}
  finally{downloading.delete(url)}
}
// An iOS Home Screen app has no downloads: a blob link opens a blank in-app page that only "back" leaves.
// The share sheet saves to Files instead. It needs a fresh tap, which a slow download has outlived.
async function shareDownload(blob,name){
  if(!navigator.canShare)return false;
  const environment=pushEnvironment(),file=new File([blob],name,{type:blob.type||"application/octet-stream"});
  if(!environment.ios||!environment.standalone||!navigator.canShare({files:[file]}))return false;
  const share=()=>navigator.share({files:[file]});
  try{await share()}
  catch(e){if(e.name==="NotAllowedError")toast(tr("Файл {0} загружен",[name]),"info",{label:tr("Сохранить"),run:()=>share().catch(()=>{})})}
  return true;
}
async function copyText(text){
  try{if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(text);toast(tr("Скопировано: {0} симв.",[text.length]),"success");return}}catch(e){}
  if(execCopy(text,document))toast(tr("Скопировано: {0} симв.",[text.length]),"success");else toast(tr("Браузер запретил копирование"));
}

if(typeof module!=="undefined")module.exports={formatSize,homeRelative,fileMatches};
