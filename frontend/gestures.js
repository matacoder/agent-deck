// Phone drawers follow the finger: the menu comes from the left edge, the project panel from the right;
// a swipe back towards the edge closes them.
// Attached to the page and to each terminal frame (same origin), whose touches never reach the page.
// reveal: a drawer that is not in the page while closed (a dialog) is shown when the drag starts.
const EDGE=28,DECIDE=10,OPEN_SHARE=0.3;
// Wide content in an open drawer (a table, a diff) scrolls under the finger first; the drawer follows
// once that content is back at its edge.
function scrollsAside(node,panel,dx){
  if(!panel.contains(node))return false;
  for(;node&&node!==panel;node=node.parentElement){
    if(node.scrollWidth<=node.clientWidth)continue;
    const flow=node.ownerDocument.defaultView.getComputedStyle(node).overflowX;
    if((flow==="auto"||flow==="scroll")&&(dx>0?node.scrollLeft>0:node.scrollLeft+node.clientWidth<node.scrollWidth-1))return true;
  }
  return false;
}
function attachDrawerSwipe(doc,{panel:drawer,isOpen,setOpen,enabled,right=false,reveal}){
  let start=null,dragging=false,width=0;
  const panel=typeof drawer==="function"?drawer:()=>drawer;
  const sign=right?-1:1;  // Right drawer: the same moves, mirrored.
  const offset=dx=>sign*Math.min(0,(start.open?sign*dx:sign*dx-width));
  doc.addEventListener("touchstart",e=>{
    // A second finger mid-drag ends the drag where it was, instead of leaving the panel half open.
    if(dragging){reset();setOpen(start?start.open:isOpen())}
    start=null;dragging=false;
    if(e.touches.length!==1||!enabled())return;
    const t=e.touches[0],open=isOpen();
    // Closed: only the edge, so vertical scrolling and taps elsewhere stay untouched.
    const fromEdge=right?(doc.defaultView?.innerWidth||innerWidth)-t.clientX:t.clientX;
    if(!open&&fromEdge>EDGE)return;
    start={x:t.clientX,y:t.clientY,open,target:e.target};width=panel().getBoundingClientRect().width||panel().offsetWidth||300;
  },{passive:true,capture:true});
  doc.addEventListener("touchmove",e=>{
    if(!start||e.touches.length!==1)return;
    const t=e.touches[0],dx=t.clientX-start.x,dy=t.clientY-start.y;
    if(!dragging){
      if(Math.abs(dx)<DECIDE&&Math.abs(dy)<DECIDE)return;
      // A mostly vertical move is a scroll; an open drawer only drags towards closing.
      if(Math.abs(dy)>Math.abs(dx)||(start.open&&(sign*dx>0||scrollsAside(start.target,panel(),dx)))){start=null;return}
      if(!start.open&&reveal){reveal();width=panel().getBoundingClientRect().width||width}
      dragging=true;panel().style.transition="none";panel().style.animation="none";
    }
    e.preventDefault();
    panel().style.transform="translateX("+offset(dx)+"px)";
  },{passive:false,capture:true});
  const finish=e=>{
    if(!start)return;
    const was=start,moved=dragging?(e.changedTouches[0]?.clientX??was.x)-was.x:0;start=null;
    if(!dragging)return;
    dragging=false;reset();
    setOpen(was.open?-sign*moved<width*OPEN_SHARE:sign*moved>width*OPEN_SHARE);
  };
  const reset=()=>{panel().style.transition="";panel().style.transform="";panel().style.animation=""};
  doc.addEventListener("touchend",finish,{capture:true});
  doc.addEventListener("touchcancel",finish,{capture:true});
}

if(typeof module!=="undefined")module.exports={attachDrawerSwipe,EDGE};
