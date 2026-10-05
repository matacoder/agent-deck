// Screenshots and previews that agents mention by path: clickable, with thumbnails and a viewer.
const IMAGE_PATH_RE=/(?<![\w/.~@+-])(?:~?\/)?(?:[\w.@+-]+\/)*[\w.@+-]+\.(?:png|jpe?g|webp|gif)(?![\w-]|\.\w)/gi;
const IMAGE_HEAD_RE=/^[\w./@+-]+\.(?:png|jpe?g|webp|gif)(?![\w-]|\.\w)/i;
let screenImages=[],viewerIndex=0;

function imageMatches(text,taken=[]){
  // taken: [start,end) ranges already used by URLs, so https://x/a.png stays a web link.
  const result=[];
  for(const m of text.matchAll(IMAGE_PATH_RE)){
    const start=m.index,end=start+m[0].length;
    if(!taken.some(([a,b])=>start<b&&end>a))result.push({index:start,path:m[0]});
  }
  return result;
}
// Agents hard-wrap long paths ("…/padel-w1-cashier-" + "preview/shot.png"); glue such lines back.
function joinImageLines(lines){
  const text=runs=>runs.map(r=>r.text).join(""),out=[];
  for(let i=0;i<lines.length;i++){
    const runs=lines[i].slice();
    while(i+1<lines.length){
      const tail=text(runs).trimEnd().match(/[\w.~@+-]*\/[\w./@+-]*$/);
      if(!tail||/\.(?:png|jpe?g|webp|gif)$/i.test(tail[0])||!IMAGE_HEAD_RE.test(text(lines[i+1])))break;
      for(let j=runs.length-1;j>=0&&/\s$/.test(runs[j].text);j--)runs[j]={...runs[j],text:runs[j].text.trimEnd()};
      runs.push(...lines[++i]);
    }
    out.push(runs);
  }
  return out;
}

function imageUrl(session,path,thumb){return activePath("/api/image?name="+encodeURIComponent(session)+"&path="+encodeURIComponent(path)+(thumb?"&thumb=1":""))}
function imageLink(session,path,runs,from,to){
  const link=el("a","img-link");link.href=imageUrl(session,path);
  appendStyledRange(link,runs,from,to);
  link.onclick=event=>{event.preventDefault();openViewer(path)};
  return link;
}
function imageStrip(session,paths){
  const strip=el("div","img-strip");
  for(const path of new Set(paths)){
    const thumb=el("button","img-thumb"),img=document.createElement("img");
    thumb.type="button";thumb.title=path;thumb.setAttribute("aria-label",tr("Открыть картинку {0}",[path.split("/").pop()]));
    img.loading="lazy";img.decoding="async";img.alt="";img.src=imageUrl(session,path,true);
    // Missing files, or paths no longer on screen, simply leave the text without a preview.
    img.onerror=()=>thumb.remove();
    thumb.append(img);thumb.onclick=()=>openViewer(path);strip.append(thumb);
  }
  return strip;
}

function openViewer(path){
  viewerIndex=Math.max(0,screenImages.indexOf(path));
  if(!screenImages.includes(path))screenImages=[path];
  renderViewer();$("viewer").hidden=false;$("viewer_close").focus();
}
function renderViewer(){
  const path=screenImages[viewerIndex],url=imageUrl(active,path);
  $("viewer_img").src=url;$("viewer_open").href=url;
  $("viewer_caption").textContent=(screenImages.length>1?(viewerIndex+1)+" / "+screenImages.length+"  ·  ":"")+path.split("/").pop();
  $("viewer_caption").title=path;
  $("viewer_prev").hidden=$("viewer_next").hidden=screenImages.length<2;
}
function stepViewer(delta){viewerIndex=(viewerIndex+delta+screenImages.length)%screenImages.length;renderViewer()}
function closeViewer(){$("viewer").hidden=true;$("viewer_img").removeAttribute("src")}
if(typeof document!=="undefined"&&document.getElementById("viewer")){
  addEventListener("keydown",e=>{
    if($("viewer").hidden)return;
    if(e.key==="Escape")closeViewer();else if(e.key==="ArrowRight")stepViewer(1);else if(e.key==="ArrowLeft")stepViewer(-1);else return;
    e.preventDefault();e.stopPropagation();
  },true);
  // Horizontal swipe flips between screenshots on a phone.
  // Runs before app.js defines $, so the element is looked up directly.
  const viewer=document.getElementById("viewer");let touchX=null;
  viewer.addEventListener("touchstart",e=>{touchX=e.touches.length===1?e.touches[0].clientX:null},{passive:true});
  viewer.addEventListener("touchend",e=>{
    if(touchX===null||screenImages.length<2)return;
    const dx=e.changedTouches[0].clientX-touchX;touchX=null;
    if(Math.abs(dx)>60)stepViewer(dx<0?1:-1);
  },{passive:true});
}

if(typeof module!=="undefined")module.exports={imageMatches,joinImageLines,IMAGE_PATH_RE};
