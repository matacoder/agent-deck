global.el=(tag,cls,...kids)=>{const e=document.createElement(tag);if(cls)e.className=cls;e.append(...kids);return e};
const {matchPalette,markMatch}=require('../../frontend/search');
global.tr=(text,args=[])=>text.replace(/\{(\d)\}/g,(_,i)=>args[i]);
const {lineComment}=require('../../frontend/git');

test('every word of the query must match the title or the hint',()=>{
  const items=[{label:'api',hint:'Laptop · ~/api'},{label:'web',hint:'Server · ~/web'},{label:'Настройки',hint:'Действие'}];
  expect(matchPalette(items,'').length).toBe(3);
  expect(matchPalette(items,'server WEB').map(i=>i.label)).toEqual(['web']);
  expect(matchPalette(items,'наст').map(i=>i.label)).toEqual(['Настройки']);
  expect(matchPalette(items,'api server')).toEqual([]);
});

test('the found part is marked and the rest stays text',()=>{
  const parts=markMatch('Error: <b>boom</b>','error');
  expect(parts[1].tagName).toBe('MARK');
  expect(parts[1].textContent).toBe('Error');
  expect(parts[2]).toBe(': <b>boom</b>');
});

test('a diff comment names the file and line and quotes the code',()=>{
  expect(lineComment('app.py',{new:42,old:'',text:'  b = `3`'},' rename ')).toBe("app.py:42 `b = '3'` — rename");
  expect(lineComment('app.py',{new:'',old:7,text:''},'why?')).toBe('app.py:7 (удалённая строка) — why?');
});
