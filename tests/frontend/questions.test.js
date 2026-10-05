const fs=require('fs');
const path=require('path');
const {renderQuestionCard,askConfirm}=require('../../frontend/questions');

const question={id:'q1',title:'Run <img src=x> now?',progress:'Question 1/2',selected:1,
 options:[{label:'Yes',text:false},{label:'Always <b>',text:false},{label:'Type something',text:true}]};
const render=(extra={})=>{
 const box=document.createElement('div'),onAnswer=jest.fn(),onToggle=jest.fn();
 renderQuestionCard({box,question,expanded:false,busyIndex:null,onAnswer,onToggle,translate:x=>x,...extra});
 return {box,onAnswer,onToggle};
};

test('question options become one-tap buttons with their original index',()=>{
 const {box,onAnswer}=render();
 const buttons=box.querySelectorAll('.q-opt');
 expect([...buttons].map(b=>b.textContent)).toEqual(['1Yes','2Always <b>']);
 buttons[1].click();expect(onAnswer).toHaveBeenCalledWith(1);
 expect(buttons[1].classList.contains('selected')).toBe(true);
 expect(box.querySelector('.q-progress').textContent).toBe('Question 1/2');
});

test('free-text options stay keyboard-only and agent text is never parsed as HTML',()=>{
 const {box}=render();
 expect(box.textContent).not.toContain('Type something');
 expect(box.querySelector('.q-note')).not.toBeNull();
 expect(box.querySelector('img')).toBeNull();expect(box.querySelector('b')).toBeNull();
 expect(box.querySelector('.q-title').textContent).toBe('Run <img src=x> now?');
});

test('a pending answer disables every option so a second tap cannot double-send',()=>{
 const {box,onAnswer}=render({busyIndex:0});
 const buttons=[...box.querySelectorAll('.q-opt')];
 expect(buttons.every(b=>b.disabled)).toBe(true);expect(buttons[0].classList.contains('sending')).toBe(true);
 buttons[1].click();expect(onAnswer).not.toHaveBeenCalled();
});

test('no question hides the card',()=>{
 const box=document.createElement('div');
 renderQuestionCard({box,question:null,translate:x=>x});
 expect(box.hidden).toBe(true);expect(box.children).toHaveLength(0);
});

test('confirm dialog resolves only for the confirm button and styles destructive actions',async()=>{
 document.body.innerHTML='<dialog id="confirm_dlg"><h3 id="confirm_title"></h3><p id="confirm_text"></p><button id="confirm_ok"></button></dialog>';
 const dialog=document.querySelector('dialog');
 dialog.showModal=jest.fn();dialog.close=jest.fn(value=>{dialog.returnValue=value||'';dialog.dispatchEvent(new Event('close'))});
 const pending=askConfirm(dialog,{title:'Close <b>?',confirm:'Close',danger:true});
 expect(dialog.querySelector('#confirm_title').textContent).toBe('Close <b>?');
 expect(dialog.querySelector('#confirm_ok').className).toBe('danger-pri');
 expect(dialog.querySelector('#confirm_text').hidden).toBe(true);
 dialog.close('ok');await expect(pending).resolves.toBe(true);
 const cancelled=askConfirm(dialog,{title:'Again?',confirm:'Yes'});
 dialog.close();await expect(cancelled).resolves.toBe(false);
});

test('phone layout query is identical in script and stylesheet',()=>{
 const script=fs.readFileSync(path.resolve(__dirname,'../../frontend/app.js'),'utf8');
 const css=fs.readFileSync(path.resolve(__dirname,'../../frontend/style.css'),'utf8');
 const query=script.match(/const MOBILE_QUERY="([^"]+)"/)[1];
 expect(css).toContain('@media '+query+'{');
});
