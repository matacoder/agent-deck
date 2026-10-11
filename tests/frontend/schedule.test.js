const {quickPromptsFor,quickRows,laterWhen,defaultLaterTime,laterCount}=require('../../frontend/schedule');
const t=text=>'['+text+']';

test('saved prompts come first, then the commands of that agent; a terminal gets none',()=>{
 const saved=[{label:'Tests',text:'run the tests'}];
 expect(quickPromptsFor('claude',saved).map(p=>p.label)).toEqual(['Tests','/compact','/clear']);
 expect(quickPromptsFor('claude-kimi',[]).map(p=>p.label)).toEqual(['/compact','/clear']);
 expect(quickPromptsFor('codex',[]).map(p=>p.label)).toEqual(['/compact','/new']);
 expect(quickPromptsFor('pi',saved).map(p=>p.label)).toEqual(['Tests']);
 expect(quickPromptsFor('shell',saved)).toEqual([]);
});

test('only commands that drop the conversation ask before sending',()=>{
 const byText=Object.fromEntries(quickPromptsFor('claude',[]).concat(quickPromptsFor('codex',[])).map(p=>[p.text,Boolean(p.confirm)]));
 expect(byText).toEqual({'/compact':false,'/clear':true,'/new':true});
 expect(quickPromptsFor('claude',[{label:'x',text:'/clear',confirm:'injected'}])[0].confirm).toBeUndefined();
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
