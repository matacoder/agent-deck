const {attachDrawerSwipe,EDGE}=require('../../frontend/gestures');

function setup(enabled=true){
  const panel=document.createElement('aside');
  panel.getBoundingClientRect=()=>({width:300});
  let open=false;const setOpen=jest.fn(on=>{open=on});
  attachDrawerSwipe(document,{panel,isOpen:()=>open,setOpen,enabled:()=>enabled});
  const touch=(type,x,y)=>{
    const event=new Event(type,{bubbles:true,cancelable:true});
    const point={clientX:x,clientY:y};
    event.touches=type==='touchend'?[]:[point];event.changedTouches=[point];
    document.dispatchEvent(event);return event;
  };
  return {panel,setOpen,touch,isOpen:()=>open};
}

test('a swipe from the left edge drags the drawer open and it follows the finger',()=>{
  const {panel,setOpen,touch}=setup();
  touch('touchstart',EDGE-10,400);
  const move=touch('touchmove',150,405);
  expect(move.defaultPrevented).toBe(true);
  expect(panel.style.transform).toBe('translateX(-168px)');
  touch('touchend',150,405);
  expect(setOpen).toHaveBeenCalledWith(true);
  expect(panel.style.transform).toBe('');
});

test('a short pull snaps back, and swipes away from the edge or vertical moves are ignored',()=>{
  const {setOpen,touch}=setup();
  touch('touchstart',10,400);touch('touchmove',60,400);touch('touchend',60,400);
  expect(setOpen).toHaveBeenLastCalledWith(false);
  setOpen.mockClear();
  touch('touchstart',200,400);touch('touchmove',350,400);touch('touchend',350,400);
  touch('touchstart',10,400);const scroll=touch('touchmove',14,480);touch('touchend',14,480);
  expect(scroll.defaultPrevented).toBe(false);
  expect(setOpen).not.toHaveBeenCalled();
});

test('an open drawer closes with a swipe left from anywhere',()=>{
  const {setOpen,touch,isOpen}=setup();
  touch('touchstart',10,400);touch('touchmove',200,400);touch('touchend',200,400);
  expect(isOpen()).toBe(true);
  touch('touchstart',250,300);touch('touchmove',100,305);touch('touchend',100,305);
  expect(setOpen).toHaveBeenLastCalledWith(false);
});

test('nothing happens while a dialog or the desktop layout disables it',()=>{
  const {setOpen,touch}=setup(false);
  touch('touchstart',10,400);touch('touchmove',200,400);touch('touchend',200,400);
  expect(setOpen).not.toHaveBeenCalled();
});

test('the right drawer mirrors the left: shown at the start of a pull from the right edge, closed by a swipe right',()=>{
  const panel=document.createElement('dialog');panel.getBoundingClientRect=()=>({width:300});
  let open=false;const setOpen=jest.fn(on=>{open=on}),reveal=jest.fn();
  const doc=document.implementation.createHTMLDocument('');
  Object.defineProperty(doc,'defaultView',{value:{innerWidth:400}});
  attachDrawerSwipe(doc,{panel:()=>panel,right:true,reveal,isOpen:()=>open,setOpen,enabled:()=>true});
  const touch=(type,x)=>{
    const event=new Event(type,{bubbles:true,cancelable:true}),point={clientX:x,clientY:300};
    event.touches=type==='touchend'?[]:[point];event.changedTouches=[point];doc.dispatchEvent(event);
  };
  touch('touchstart',200);touch('touchmove',100);touch('touchend',100);  // Not from the edge.
  expect(reveal).not.toHaveBeenCalled();
  touch('touchstart',390);touch('touchmove',250);
  expect(reveal).toHaveBeenCalledTimes(1);
  expect(panel.style.transform).toBe('translateX(160px)');
  touch('touchend',250);
  expect(setOpen).toHaveBeenLastCalledWith(true);
  touch('touchstart',100);touch('touchmove',80);touch('touchend',80);  // Open: a swipe left does nothing.
  expect(setOpen).toHaveBeenCalledTimes(1);
  touch('touchstart',100);touch('touchmove',300);
  expect(panel.style.transform).toBe('translateX(200px)');
  touch('touchend',300);
  expect(setOpen).toHaveBeenLastCalledWith(false);
});
