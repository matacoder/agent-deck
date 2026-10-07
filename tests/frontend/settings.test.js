const {saveDirectorySetting}=require('../../frontend/settings');
const fs=require('fs');
const path=require('path');

let input,button,notify,request;
beforeEach(()=>{
 document.body.innerHTML='<input id="directory" value="~/dev"><button id="save">Save</button>';
 input=document.querySelector('input');button=document.querySelector('button');
 notify=jest.fn();request=jest.fn();
});
const save=()=>saveDirectorySetting({request,input,button,notify,translate:x=>x});
test('saves and shows the normalized directory immediately',async()=>{
 request.mockResolvedValue({directory:'/Users/denis/dev'});
 await save();
 expect(request).toHaveBeenCalledWith('/api/project_directory',{directory:'~/dev'});
 expect(input.value).toBe('/Users/denis/dev');
 expect(notify).toHaveBeenCalledWith('Папка проектов сохранена','success');
 expect(button.disabled).toBe(false);
});
test('failed saves retain the typed directory and permit retry',async()=>{
 request.mockRejectedValue(new Error('Invalid directory'));
 await save();
 expect(input.value).toBe('~/dev');expect(notify).toHaveBeenCalledWith('Invalid directory');
 expect(button.disabled).toBe(false);
});
test('saving disables the control until the request completes',async()=>{
 let finish;request.mockReturnValue(new Promise(resolve=>finish=resolve));
 const pending=save();expect(button.disabled).toBe(true);
 finish({directory:'/Users/denis/dev'});await pending;expect(button.disabled).toBe(false);
});
test('project settings form is accessible and available in application settings',()=>{
 document.body.innerHTML=fs.readFileSync(path.resolve(__dirname,'../../frontend/index.html'),'utf8');
 const field=document.querySelector('#hub_general #project_directory');
 expect(field.required).toBe(true);
 expect(document.querySelector('label[for="project_directory"]')).not.toBeNull();
 expect(field.closest('form').getAttribute('onsubmit')).toContain('saveProjectDirectory');
});
test('all language catalogs contain project-directory messages',()=>{
 for(const name of fs.readdirSync(path.resolve(__dirname,'../../locales')).filter(x=>x.endsWith('.json'))){
  const catalog=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../locales',name),'utf8')).messages;
  for(const key of ['Папка проектов','Папка проектов сохранена','Используется для новых сессий. Существующие сессии остаются в своих папках.'])expect(catalog[key]).toBeTruthy();
 }
});
test('renaming submits the original ID and refreshes after closing',async()=>{
 const {saveSessionName}=require('../../frontend/settings');
 const dialog={dataset:{session:'stable-id'},close:jest.fn()},refresh=jest.fn();
 input.value='  Новое имя  ';request.mockResolvedValue({ok:true});
 await saveSessionName({request,input,button,dialog,refresh,notify});
 expect(request).toHaveBeenCalledWith('/api/rename',{name:'stable-id',title:'Новое имя'});
 expect(dialog.close).toHaveBeenCalledTimes(1);expect(refresh).toHaveBeenCalledTimes(1);
 expect(button.disabled).toBe(false);
});
test('rename errors preserve the editor and allow retry',async()=>{
 const {saveSessionName}=require('../../frontend/settings');
 const dialog={dataset:{session:'stable-id'},close:jest.fn()},refresh=jest.fn();
 request.mockRejectedValue(new Error('Session gone'));
 await saveSessionName({request,input,button,dialog,refresh,notify});
 expect(dialog.close).not.toHaveBeenCalled();expect(refresh).not.toHaveBeenCalled();
 expect(notify).toHaveBeenCalledWith('Session gone');expect(button.disabled).toBe(false);
});
test('connection name field requests text input to prevent small-font Safari focus zoom',()=>{
 document.body.innerHTML=fs.readFileSync(path.resolve(__dirname,'../../frontend/index.html'),'utf8');
 expect(document.querySelector('#lm_name').type).toBe('text');
 expect(document.querySelector('#rename_dlg #session_title').maxLength).toBe(100);
});

test('refreshes every saved model server before reading the current catalog',async()=>{
 const {refreshModelCatalog}=require('../../frontend/settings');
 const fresh={profiles:[{id:'red',models:[{id:'new-model'}]}]};
 const api=jest.fn().mockResolvedValueOnce({profiles:[{id:'red'},{id:'blue'}]}).mockResolvedValueOnce({}).mockResolvedValueOnce({}).mockResolvedValueOnce(fresh);
 expect(await refreshModelCatalog(api)).toEqual(fresh);
 expect(api.mock.calls).toEqual([['/api/lmstudio'],['/api/lm_probe',{id:'red'}],['/api/lm_probe',{id:'blue'}],['/api/lmstudio']]);
});

test('a failed model server does not prevent refreshing other servers',async()=>{
 const {refreshModelCatalog}=require('../../frontend/settings');
 const fresh={profiles:[{id:'blue',models:[{id:'replacement'}]}]};
 const api=jest.fn().mockResolvedValueOnce({profiles:[{id:'red'},{id:'blue'}]}).mockRejectedValueOnce(new Error('Unavailable')).mockResolvedValueOnce({}).mockResolvedValueOnce(fresh);
 expect(await refreshModelCatalog(api)).toEqual(fresh);
 expect(api).toHaveBeenCalledWith('/api/lm_probe',{id:'blue'});
});

test('terminal mode moves the same session keys into a visible toolbar and restores them in screen mode',()=>{
 const {placeSessionKeys}=require('../../frontend/settings');
 document.body.innerHTML='<div id="screen"><div id="row"><button id="wrap">Wrap</button><button>Tab</button></div></div><div id="terminal" hidden></div>';
 const options={row:document.querySelector('#row'),screen:document.querySelector('#screen'),terminal:document.querySelector('#terminal'),wrap:document.querySelector('#wrap'),active:true};
 const click=jest.fn();options.row.lastChild.onclick=click;
 placeSessionKeys({...options,mode:'term'});
 expect(options.row.parentNode).toBe(options.terminal);expect(options.terminal.hidden).toBe(false);expect(options.wrap.hidden).toBe(true);
 options.row.lastChild.click();expect(click).toHaveBeenCalledTimes(1);
 placeSessionKeys({...options,mode:'screen'});
 expect(options.row.parentNode).toBe(options.screen);expect(options.terminal.hidden).toBe(true);expect(options.wrap.hidden).toBe(false);
 placeSessionKeys({...options,mode:'term',active:false});expect(options.terminal.hidden).toBe(true);
});

test('switching terminal views preserves the composer text, attachment controls and handlers',()=>{
 const {placeSessionKeys}=require('../../frontend/settings');
 document.body.innerHTML='<div id="screen"><div id="composer"><textarea>Unsent draft</textarea><button id="attach">Attach</button><div id="row"><button id="wrap">Wrap</button><button id="reconnect" hidden>Reconnect</button></div><div id="attachments">photo.png</div></div></div><div id="terminal" hidden></div>';
 const options={row:document.querySelector('#row'),composer:document.querySelector('#composer'),screen:document.querySelector('#screen'),terminal:document.querySelector('#terminal'),wrap:document.querySelector('#wrap'),reconnect:document.querySelector('#reconnect'),active:true};
 const attach=jest.fn();document.querySelector('#attach').onclick=attach;
 placeSessionKeys({...options,mode:'term'});
 expect(options.composer.parentNode).toBe(options.terminal);expect(options.reconnect.hidden).toBe(false);
 document.querySelector('#attach').click();expect(attach).toHaveBeenCalledTimes(1);
 placeSessionKeys({...options,mode:'screen'});
 expect(options.composer.parentNode).toBe(options.screen);expect(options.reconnect.hidden).toBe(true);
 expect(document.querySelector('textarea').value).toBe('Unsent draft');expect(document.querySelector('#attachments').textContent).toBe('photo.png');
});

test('closed draft actions copy exact text and delete only the chosen draft',()=>{
 const {renderClosedDraftList}=require('../../frontend/settings');
 const box=document.createElement('div');const drafts=new Map([['one','Text <img>\nnext'],['two','Keep me']]);
 const copy=jest.fn();const remove=jest.fn(name=>{drafts.delete(name);render()});
 const render=()=>renderClosedDraftList({box,drafts,copy,remove,translate:x=>x});
 render();box.querySelector('.pri').click();expect(copy).toHaveBeenCalledWith('Text <img>\nnext');expect(box.querySelector('img')).toBeNull();
 box.querySelector('.danger').click();expect(drafts.get('two')).toBe('Keep me');expect(box.querySelectorAll('.closed-draft')).toHaveLength(1);
 box.querySelector('.danger').click();expect(box.textContent).toBe('Нет сохранённых черновиков');
});

test('HTTP clipboard fallback stays inside the active modal and cleans up its textarea',()=>{
 const {execCopy}=require('../../frontend/settings');
 document.body.innerHTML='<dialog open><button>Copy</button></dialog>';
 document.execCommand=jest.fn(()=>{const field=document.querySelector('dialog textarea');expect(field.value).toBe('Exact\ntext');return true});
 expect(execCopy('Exact\ntext',document)).toBe(true);expect(document.querySelector('textarea')).toBeNull();
 delete document.execCommand;
});

test('automatic update toggle keeps its compact width beside readable text',()=>{
 document.body.innerHTML=fs.readFileSync(path.resolve(__dirname,'../../frontend/index.html'),'utf8');
 const style=document.createElement('style');style.textContent=fs.readFileSync(path.resolve(__dirname,'../../frontend/style.css'),'utf8');document.head.append(style);
 try{
  const checkbox=document.querySelector('#auto_update_enabled');
  expect(checkbox.type).toBe('checkbox');expect(checkbox.closest('label').textContent).toContain('Обновлять автоматически');
  expect(getComputedStyle(checkbox).width).toBe('36px');expect(getComputedStyle(checkbox).height).toBe('21px');
  expect(getComputedStyle(checkbox.closest('label')).display).toBe('flex');
  expect(getComputedStyle(document.querySelector('#project_directory')).width).toBe('100%');
 }finally{style.remove()}
});

test('local model measurements read as words, not jargon, and an empty sample says nothing',()=>{
 global.tr=(text,args=[])=>text.replace(/\{(\d)\}/g,(_,i)=>args[i]);
 const {lmMetrics}=require('../../frontend/hub-models');
 expect(lmMetrics({source:'session',tokens_per_second:52.44,time_to_first_token_seconds:0.381})).toBe('Последний ответ: 52.4 tok/s · первый токен 0.38 с');
 expect(lmMetrics({source:'benchmark',model_load_time_seconds:4.7})).toBe('Тест скорости: загрузка 4.70 с');
 expect(lmMetrics({})).toBe('');
});

test('a found computer is matched to a connected one by address, not by name',()=>{
 const {deckAddress}=require('../../frontend/hub-models');
 expect(deckAddress('http://100.66.158.47:8790')).toBe(deckAddress('http://100.66.158.47:8790/'));
 expect(deckAddress('http://100.66.158.47:8790')).not.toBe(deckAddress('http://100.66.158.47:8791'));
 expect(deckAddress('http://100.64.0.2')).toBe('100.64.0.2:80');
});
