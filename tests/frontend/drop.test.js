global.agentOf=s=>s.agent||'claude';
global.sessionTitle=s=>s.title||s.name;
const {dropTarget,dragHasFiles,pastedFiles}=require('../../frontend/drop');

test('a pasted picture is a file; text copied with a picture beside it stays text',()=>{
  const shot={name:'image.png'};
  expect(pastedFiles({files:[shot],getData:()=>''})).toEqual([shot]);
  expect(pastedFiles({files:[shot],getData:type=>type==='text/plain'?'cell A1':''})).toEqual([]);
  expect(pastedFiles({files:[],getData:()=>'plain text'})).toEqual([]);
  expect(pastedFiles(null)).toEqual([]);
});

test('a drop names the session it lands in, or says why it cannot',()=>{
  expect(dropTarget({name:'api',agent:'codex'},false)).toEqual({ok:true,text:'Отпустите, чтобы приложить к «{0}»',args:['api']});
  expect(dropTarget({name:'sh',agent:'shell'},false).ok).toBe(false);
  expect(dropTarget(null,false).text).toBe('Сначала откройте сессию');
  expect(dropTarget({name:'api'},true).text).toBe('Дождитесь окончания отправки или загрузки');
});

test('only file drags count, not dragged text or links',()=>{
  expect(dragHasFiles({dataTransfer:{types:['Files']}})).toBe(true);
  expect(dragHasFiles({dataTransfer:{types:['text/plain','text/uri-list']}})).toBe(false);
  expect(dragHasFiles({})).toBe(false);
});

test('rich text copied from a chat yields its pictures once; a copied table yields none',()=>{
  const {pastedPictures,pictureRoom}=require('../../frontend/drop');
  const clip=html=>({getData:type=>type==='text/html'?html:'text'});
  const html='<p>Look <img src="https://cdn.example/a.png"> and <img src="data:image/png;base64,AAAA"><img src="https://cdn.example/a.png"><img src="file:///C:/x.png"><img src="javascript:alert(1)"></p>';
  expect(pastedPictures(clip(html))).toEqual(['https://cdn.example/a.png','data:image/png;base64,AAAA']);
  expect(pastedPictures(clip('<table><tr><td>cell A1</td></tr></table>'))).toEqual([]);
  expect(pastedPictures({files:[]})).toEqual([]);
  expect(pictureRoom(0,6)).toBe(4);expect(pictureRoom(3,2)).toBe(1);expect(pictureRoom(4,1)).toBe(0);
});
