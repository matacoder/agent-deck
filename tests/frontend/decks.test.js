const {instancePath,instanceStorage,populateDeckSelector}=require('../../frontend/decks');
const ID='a'.repeat(24),OTHER='b'.repeat(24);
beforeEach(()=>{localStorage.clear();sessionStorage.clear();document.body.innerHTML='';});
test('local routes stay local and remote API and tty use the same gateway',()=>{
 expect(instancePath('','/api/sessions')).toBe('/api/sessions');
 expect(instancePath(ID,'/api/send')).toBe('/deck/'+ID+'/api/send');
 expect(instancePath(ID,'/t/?arg=%3Dcc-demo')).toBe('/deck/'+ID+'/t/?arg=%3Dcc-demo');
 expect(()=>instancePath('../','/api/send')).toThrow();
 expect(()=>instancePath(ID,'https://other/')).toThrow();
});
test('same named sessions on different machines cannot exchange drafts or attachments',()=>{
 const local=instanceStorage(sessionStorage,''),mac=instanceStorage(sessionStorage,ID),server=instanceStorage(sessionStorage,OTHER);
 local.setItem('cc.reload-draft','local draft');mac.setItem('cc.reload-draft','mac draft');server.setItem('cc.reload-draft','server draft');
 mac.setItem('cc.reload-images','mac attachment');
 expect(local.getItem('cc.reload-draft')).toBe('local draft');expect(mac.getItem('cc.reload-draft')).toBe('mac draft');expect(server.getItem('cc.reload-draft')).toBe('server draft');
 expect(local.getItem('cc.reload-images')).toBeNull();expect(server.getItem('cc.reload-images')).toBeNull();
 mac.removeItem('cc.reload-draft');expect(local.getItem('cc.reload-draft')).toBe('local draft');expect(server.getItem('cc.reload-draft')).toBe('server draft');
});
test('legacy local session and display settings keep their original keys',()=>{
 localStorage.setItem('cc.active','demo');const local=instanceStorage(localStorage,'');
 expect(local.getItem('cc.active')).toBe('demo');
 const remote=instanceStorage(localStorage,ID);remote.setItem('cc.active','another');expect(local.getItem('cc.active')).toBe('demo');
});
test('selector renders machine names as text and preserves selected identity',()=>{
 document.body.innerHTML='<select></select>';const select=document.querySelector('select');
 populateDeckSelector(select,[{id:ID,name:'<img src=x onerror=alert(1)>'}],ID,'Gateway');
 expect(select.options).toHaveLength(2);expect(select.value).toBe(ID);expect(select.options[1].textContent).toContain('<img');expect(select.querySelector('img')).toBeNull();
});

test('panel login links reuse the public browser origin and its authenticated cookie',()=>{
 const {panelLinkTarget}=require('../../frontend/decks');
 const options={browserOrigin:'https://cli.matakov.com',panelOrigins:['http://100.109.113.79:8790','http://127.0.0.1:8790']};
 expect(panelLinkTarget('http://100.109.113.79:8790/login',options)).toBe('https://cli.matakov.com/');
 expect(panelLinkTarget('http://127.0.0.1:8790/',options)).toBe('https://cli.matakov.com/');
 expect(panelLinkTarget('http://100.109.113.79:3000/login',options)).toBe('http://100.109.113.79:3000/login');
 expect(panelLinkTarget('https://example.com/login',options)).toBe('https://example.com/login');
 expect(panelLinkTarget('http://secret@100.109.113.79:8790/login',options)).toBe('http://secret@100.109.113.79:8790/login');
});

test('remote terminal links keep the selected gateway route',()=>{
 const {panelLinkTarget}=require('../../frontend/decks');
 expect(panelLinkTarget('http://100.68.39.62:8790/t/?arg=cc-demo',{browserOrigin:'https://cli.matakov.com',panelOrigins:['http://100.68.39.62:8790'],identity:ID})).toBe('https://cli.matakov.com/deck/'+ID+'/t/?arg=cc-demo');
});
