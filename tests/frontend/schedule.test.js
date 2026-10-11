const {quickChips,quickRows,laterWhen,defaultLaterTime,laterCount}=require('../../frontend/schedule');
const t=text=>'['+text+']';

test('saved prompts come first; the agent commands wait behind "more"; a terminal gets none',()=>{
 const saved=[{label:'Tests',text:'run the tests'}];
 const labels=(agent,list,more,shared)=>quickChips(agent,list,more,shared).map(p=>p.more?'…':p.label);
 expect(labels('claude',saved,false)).toEqual(['Tests','…']);
 expect(labels('claude',saved,true)).toEqual(['Tests','…','/compact','/clear']);
 expect(labels('claude-kimi',[],true)).toEqual(['…','/compact','/clear']);
 expect(labels('codex',[],true)).toEqual(['…','/compact','/new']);
 expect(labels('pi',saved,true)).toEqual(['Tests']);
 expect(quickChips('shell',saved,true)).toEqual([]);
 // The keys row already has a "more": the commands follow it and no second one is drawn.
 expect(labels('claude',saved,false,true)).toEqual(['Tests']);
 expect(quickChips('claude',[],false,true)).toEqual([]);
 expect(quickChips('claude',[],true,true).map(p=>p.label)).toEqual(['/compact','/clear']);
});

test('only commands that drop the conversation ask before sending',()=>{
 const commands=agent=>quickChips(agent,[],true).filter(p=>!p.more);
 const byText=Object.fromEntries(commands('claude').concat(commands('codex')).map(p=>[p.text,Boolean(p.confirm)]));
 expect(byText).toEqual({'/compact':false,'/clear':true,'/new':true});
 expect(quickChips('claude',[{label:'x',text:'/clear',confirm:'injected'}],false)[0].confirm).toBeUndefined();
});

test('empty editor rows are dropped and labels are trimmed',()=>{
 expect(quickRows([{label:' Tests ',text:'run the tests'},{label:'empty',text:'   '},{label:'',text:'commit'}]))
  .toEqual([{label:'Tests',text:'run the tests'},{label:'',text:'commit'}]);
});

test('a waiting prompt says when it goes',()=>{
 const time=seconds=>'at '+seconds;
 expect(laterWhen({trigger:'time',at:1700000000},t,time)).toBe('at 1700000000');
 expect(laterWhen({trigger:'idle',at:0},t,time)).toBe('[Когда агент освободится]');
 expect(laterWhen({trigger:'limit',at:0},t,time)).toBe('[Когда сбросится лимит]');
});

test('the time field starts an hour ahead on a round five minutes, in local time',()=>{
 const value=defaultLaterTime(new Date(2026,9,10,23,12,30).getTime());
 expect(value).toBe('2026-10-11T00:15');
 expect(defaultLaterTime(new Date(2026,0,5,8,0,0).getTime())).toBe('2026-01-05T09:00');
});

test('the badge counts waiting prompts and auto-continue',()=>{
 expect(laterCount(null)).toBe(0);
 expect(laterCount({prompts:[],auto_resume:false})).toBe(0);
 expect(laterCount({prompts:[{},{}],auto_resume:true})).toBe(3);
});
