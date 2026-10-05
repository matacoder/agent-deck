const {backupReportLines,backupLabel,formatBackupTime}=require('../../frontend/backups');
const translate=(text,params=[])=>text.replace(/\{(\d+)\}/g,(_,n)=>String(params[n]));

test('cycle report names each machine, its copies or its error, then the finish time',()=>{
 const report={finished:1700000000,machines:[{name:'Mac Studio',ok:true,copies:2},{name:'uk',ok:false,error:'Remote Agent Deck did not respond'},{name:'old',ok:false}]};
 const lines=backupReportLines(report,translate,'en');
 expect(lines.map(l=>[l.ok,l.text])).toEqual([[true,'Mac Studio · копий на других машинах: 2'],[false,'uk · Remote Agent Deck did not respond'],[false,'old · ошибка'],[true,'Последний цикл: '+formatBackupTime(1700000000,'en')]]);
 expect(backupReportLines(null,translate,'en')).toEqual([]);
});

test('backup labels show machine, local time and a size of at least 1 KB',()=>{
 expect(backupLabel({name:'gw',created:1700000000,size:300},'en')).toBe('gw · '+formatBackupTime(1700000000,'en')+' · 1 KB');
 expect(backupLabel({name:'gw',created:1700000000,size:4096},'en')).toMatch(/· 4 KB$/);
});
