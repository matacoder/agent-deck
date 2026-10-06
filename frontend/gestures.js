// Phone drawer follows the finger: a swipe from the left edge opens it, a swipe left closes it.
// Attached to the page and to each terminal frame (same origin), whose touches never reach the page.
const EDGE=28,DECIDE=10,OPEN_SHARE=0.3;
function attachDrawerSwipe(doc,{panel,isOpen,setOpen,enabled}){
  let start=null,dragging=false,width=0;
  const offset=dx=>isOpen()?Math.min(0,dx):Math.min(0,dx-width);
  doc.addEventListener("touchstart",e=>{
    // A second finger mid-drag ends the drag where it was, instead of leaving the panel half open.
    if(dragging){panel.style.transition="";panel.style.transform="";setOpen(start?start.open:isOpen())}
    start=null;dragging=false;
    if(e.touches.length!==1||!enabled())return;
    const t=e.touches[0],open=isOpen();
    // Closed: only the left edge, so vertical scrolling and taps elsewhere stay untouched.
    if(!open&&t.clientX>EDGE)return;
    start={x:t.clientX,y:t.clientY,open};width=panel.getBoundingClientRect().width||panel.offsetWidth||300;
  },{passive:true,capture:true});
  doc.addEventListener("touchmove",e=>{
    if(!start||e.touches.length!==1)return;
    const t=e.touches[0],dx=t.clientX-start.x,dy=t.clientY-start.y;
    if(!dragging){
      if(Math.abs(dx)<DECIDE&&Math.abs(dy)<DECIDE)return;
      // A mostly vertical move is a scroll; an open drawer only drags towards closing.
      if(Math.abs(dy)>Math.abs(dx)||(start.open&&dx>0)){start=null;return}
      dragging=true;panel.style.transition="none";
    }
    e.preventDefault();
    panel.style.transform="translateX("+offset(dx)+"px)";
  },{passive:false,capture:true});
  const finish=e=>{
    if(!start)return;
    const was=start,moved=dragging?(e.changedTouches[0]?.clientX??was.x)-was.x:0;start=null;
    if(!dragging)return;
    dragging=false;panel.style.transition="";panel.style.transform="";
    setOpen(was.open?-moved<width*OPEN_SHARE:moved>width*OPEN_SHARE);
  };
  doc.addEventListener("touchend",finish,{capture:true});
  doc.addEventListener("touchcancel",finish,{capture:true});
}

if(typeof module!=="undefined")module.exports={attachDrawerSwipe,EDGE};
