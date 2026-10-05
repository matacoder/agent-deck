const {shortModel,quotaDuration,plannedRemaining,primaryQuota,quotaTone}=require('../../frontend/logic');

const epoch=value=>Date.parse(value)/1000;
test.each([
 ['models/qwen3.8-27b-turbo-fable','Qwen3.8 27B'],
 ['llama-3.1-8b-instruct','Llama 8B'],
 ['short-model','short-model'],
 ['claude-opus-5-5','Opus 5.5'],
 ['claude-sonnet-4-5-20250929','Sonnet 4.5'],
 ['claude-fable-5-1[1m]','Fable 5.1'],
 ['gpt-6.1-sol','gpt-6.1-sol'],
 ['', ''],
 ['abcdefghijklmnopqrstuvwxyz0123456789','abcdefghijklmnopqrstuvwxyz0…'],
])('shortens model %s', (raw,expected)=>expect(shortModel(raw)).toBe(expected));
test.each([[31,'2026-11-01T00:00:00Z'],[31,'2024-03-31T00:00:00Z'],[29,'2024-03-01T00:00:00Z']])('calendar quota duration %s days', (days,reset)=>{
 expect(quotaDuration({period:'month',secs:0,resets_at:epoch(reset)})).toBe(days*86400);
});
test('known quota duration takes precedence over the calendar',()=>expect(quotaDuration({secs:18000,period:'month'})).toBe(18000));
test.each([{},null,{secs:0},{period:'month',resets_at:NaN}])('missing quota duration yields null %#',value=>expect(quotaDuration(value)).toBeNull());
test('daily plan stops at a reset today and tolerates missing duration',()=>{
 const now=epoch('2026-10-04T12:00:00Z');
 expect(plannedRemaining({secs:18000,resets_at:now+3600},now)).toBe(0);
 expect(plannedRemaining({resets_at:now+3600},now)).toBeNull();
 expect(plannedRemaining({period:'month',secs:0,resets_at:epoch('2026-11-01T00:00:00Z')},now)).toBe(87);
});
test.each([[26,20,'good'],[70,77,'crit'],[75,77,'over'],[74,77,'over'],[10,10,'good'],[25,null,'']])('quota tone %s vs %s', (remaining,plan,tone)=>expect(quotaTone(remaining,plan)).toBe(tone));
test('overall monthly quota wins over coding and short quotas',()=>{
 const code={period:'month',label:'Kimi Code'},overall={period:'month',label:'Overall'},short={secs:18000};
 expect(primaryQuota({windows:[code,short,overall]})).toBe(overall);
 expect(primaryQuota({windows:[short,{secs:604800}]}).secs).toBe(604800);
 expect(primaryQuota({})).toBeUndefined();
});
test('session label uses a rename while preserving the internal identifier',()=>{
 const {sessionTitle}=require('../../frontend/logic');
 const session={name:'stable-id',title:'Моя работа'};
 expect(sessionTitle(session)).toBe('Моя работа');expect(session.name).toBe('stable-id');
 expect(sessionTitle({name:'legacy'})).toBe('legacy');expect(sessionTitle(null)).toBe('');
});
