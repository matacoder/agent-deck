const {inboxItems}=require('../../frontend/inbox');
const {fleetTargets,versionLabel}=require('../../frontend/fleet');
const t=(text,params=[])=>text.replace(/\{(\d+)\}/g,(_,n)=>String(params[n]));

test('a session with a question is listed once, as the question',()=>{
 const items=inboxItems([{deck:'',session:'api'},{deck:'m',session:'ml'}],[{deck:'',session:'api',machine:'gw'},{deck:'',session:'web',machine:'gw'}]);
 expect(items.map(i=>[i.kind,i.key])).toEqual([['question','/api'],['question','m/ml'],['finished','/web']]);
});

test('only computers that can update now are targeted',()=>{
 const versions=new Map([
  ['old',{version:'1.8.0',latest:'1.9.0',update:true,can_update:true,job:{phase:'idle'}}],
  ['dev',{version:'1.8.0',latest:'1.9.0',update:true,can_update:false}],
  ['busy',{version:'1.8.0',latest:'1.9.0',update:true,can_update:true,job:{phase:'installing'}}],
  ['new',{version:'1.9.0',latest:'1.9.0',update:false,can_update:true}],
  ['gone',null]]);
 expect(fleetTargets(versions)).toEqual(['old']);
 expect(versionLabel(versions.get('old'),t)).toBe('v1.8.0 → v1.9.0');
 expect(versionLabel(versions.get('new'),t)).toBe('v1.9.0');
 expect(versionLabel(versions.get('busy'),t)).toBe('v1.8.0 · обновляется…');
 expect(versionLabel(null,t)).toBe('недоступен');
});
