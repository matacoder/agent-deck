// Every picture the open session showed, kept by the panel after it left the screen: a grid of square
// thumbnails, newest first, opening in the full-screen viewer. Reloaded while the tab is open and visible.
const gallery={session:null,items:null,raw:"",error:"",timer:null};
const GALLERY_POLL=15000;

function galleryUrl(session,id,thumb){
  return activePath("/api/gallery_image?name="+encodeURIComponent(session)+"&id="+encodeURIComponent(id)+(thumb?"&thumb=1":""));
}
function galleryShown(){
  const box=$("project_dlg");
  return box.open&&project.tab==="gallery"&&!document.hidden;
}
async function loadGallery(){
  const session=active;clearTimeout(gallery.timer);
  if(gallery.session!==session){Object.assign(gallery,{session,items:null,raw:"",error:""});renderGallery()}
  try{
    const data=await api("/api/gallery?name="+encodeURIComponent(session));
    if(gallery.session!==session)return;
    const raw=JSON.stringify(data.items||[]);
    // The same answer leaves the grid alone: no thumbnail reloads, no lost scroll.
    if(raw!==gallery.raw||gallery.error){Object.assign(gallery,{raw,items:data.items||[],error:""});renderGallery()}
  }catch(e){
    if(gallery.session!==session||e.message===STALE)return;
    gallery.error=e.message;if(!gallery.items)renderGallery();
  }
  if(galleryShown())gallery.timer=setTimeout(()=>{if(galleryShown())loadGallery()},GALLERY_POLL);
}
function renderGallery(){
  const box=$("gallery_body");box.replaceChildren();
  if(gallery.error&&!gallery.items){box.append(errorWithRetry(gallery.error,loadGallery));return}
  if(!gallery.items){box.append(el("p","files-empty",tr("Загрузка…")));return}
  const items=gallery.items,session=gallery.session;
  if(!items.length){box.append(el("p","files-empty",tr("Здесь появятся картинки, которые агенты этой сессии покажут на экране: скриншоты, превью, графики. Они остаются, даже когда уходят с экрана.")));return}
  box.append(el("p","gallery-count",tr("Картинок: {0}",[items.length])));
  const grid=el("div","gallery-grid");
  const viewer=()=>items.map(item=>({url:galleryUrl(session,item.id),name:item.name,title:item.path+" · "+formatTime(item.at)}));
  items.forEach((item,i)=>{
    const cell=el("button","gallery-cell"),img=document.createElement("img");
    cell.type="button";cell.title=item.name;cell.setAttribute("aria-label",tr("Открыть картинку {0}",[item.name]));
    img.loading="lazy";img.decoding="async";img.alt="";img.src=galleryUrl(session,item.id,true);
    cell.append(img);cell.onclick=()=>showViewer(viewer(),i);grid.append(cell);
  });
  box.append(grid);
}
function formatTime(at){
  return new Intl.DateTimeFormat(DATE_LOCALE,{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"}).format(new Date(at*1000));
}
if(typeof document!=="undefined")document.addEventListener("visibilitychange",()=>{if(!document.hidden&&gallery.session&&galleryShown())loadGallery()});
