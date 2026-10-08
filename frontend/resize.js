// On a wide screen both sidebars can be dragged wider or narrower (or moved with the arrow keys on their
// edge); a double click restores the default. Widths are kept in this browser; CSS still caps them by the
// window, so a width saved on a big monitor never squeezes the terminal on a laptop.
// edge: which way a drag to the right moves the width (the left sidebar grows, the right one shrinks).
const PANE_SIZES={side:{prop:"--side-w",key:"cc.side-w",min:200,max:480,edge:1},project:{prop:"--project-w",key:"cc.project-w",min:320,max:1100,edge:-1}};
function setPaneWidth(name,width){
  const pane=PANE_SIZES[name];
  width=Math.round(Math.min(pane.max,Math.max(pane.min,width)));
  document.documentElement.style.setProperty(pane.prop,width+"px");
  return width;
}
function savePaneWidth(name,width){try{localStore.setItem(PANE_SIZES[name].key,String(width))}catch(e){}}
function resetPaneWidth(name){
  document.documentElement.style.removeProperty(PANE_SIZES[name].prop);
  try{localStore.removeItem(PANE_SIZES[name].key)}catch(e){}
}
function restorePaneWidths(){
  for(const name of Object.keys(PANE_SIZES)){
    let saved=0;try{saved=+localStore.getItem(PANE_SIZES[name].key)}catch(e){}
    if(saved>0)setPaneWidth(name,saved);
  }
}
function attachResizer(handle,name,target){
  const edge=PANE_SIZES[name].edge;
  handle.addEventListener("pointerdown",e=>{
    if(e.button!==0)return;
    e.preventDefault();handle.setPointerCapture(e.pointerId);
    const startX=e.clientX,start=target().getBoundingClientRect().width;let width=start;
    // The terminal is an iframe: without this it would swallow the drag once the pointer crosses it.
    document.body.classList.add("resizing");
    const move=ev=>{width=setPaneWidth(name,start+(ev.clientX-startX)*edge)};
    const stop=()=>{
      document.body.classList.remove("resizing");savePaneWidth(name,width);
      handle.removeEventListener("pointermove",move);handle.removeEventListener("pointerup",stop);handle.removeEventListener("pointercancel",stop);
    };
    handle.addEventListener("pointermove",move);handle.addEventListener("pointerup",stop);handle.addEventListener("pointercancel",stop);
  });
  handle.addEventListener("dblclick",()=>resetPaneWidth(name));
  handle.addEventListener("keydown",e=>{
    const step=e.key==="ArrowRight"?16:e.key==="ArrowLeft"?-16:0;
    if(!step)return;
    e.preventDefault();savePaneWidth(name,setPaneWidth(name,target().getBoundingClientRect().width+step*edge));
  });
}
