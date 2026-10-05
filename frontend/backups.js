let backupStatus=null,backupSources=new Map();

function formatBackupTime(seconds,locale){
  return new Date(seconds*1000).toLocaleString(locale,{dateStyle:"medium",timeStyle:"short"});
}
// One line per machine for the last cycle: what is protected and what needs attention.
function backupReportLines(report,translate,locale){
  if(!report)return [];
  return report.machines.map(m=>({ok:m.ok,text:m.name+" · "+(m.ok?translate("копий на других машинах: {0}",[m.copies||0]):m.error||translate("ошибка"))}))
    .concat(report.finished?[{ok:true,text:translate("Последний цикл: {0}",[formatBackupTime(report.finished,locale)])}]:[]);
}
function backupLabel(meta,locale){
  return meta.name+" · "+formatBackupTime(meta.created,locale)+" · "+Math.max(1,Math.round((meta.size||0)/1024))+" KB";
}

async function loadBackups(){
  try{backupStatus=await api("/api/backups")}catch(e){toast(e.message);return}
  backupSources=new Map([["",backupStatus.stored]]);
  // Copies kept by connected machines are reachable only from the gateway that holds their logins.
  if(!selectedDeck)await Promise.all(deckDirectory.decks.map(async d=>{
    try{backupSources.set(d.id,(await api(instancePath(d.id,"/api/backups"),null,true)).stored||[])}catch(e){}
  }));
  renderBackups();
}
function renderBackups(){
  const s=backupStatus;if(!s)return;
  const box=$("backup_state");
  if(!s.configured){
    box.replaceChildren(el("p","",tr("Бэкапы выключены на этой машине.")),
      el("div","acts",btn(tr("У меня есть код"),"",()=>{$("backup_join_card").hidden=false;$("backup_join_code").focus()}),btn(tr("Включить бэкапы"),"pri",enableBackups)));
  }else{
    const lines=backupReportLines(s.report,tr,DATE_LOCALE).map(l=>el("p","backup-line"+(l.ok?"":" danger"),l.text));
    box.replaceChildren(el("p","",tr("Ключ {0} · последний бэкап: {1}",[s.key_id,s.last?formatBackupTime(s.last,DATE_LOCALE):tr("ещё не было")])),...lines,
      el("div","acts",btn(tr("Скачать бэкап этой машины"),"",downloadBackup),btn(tr("Сделать бэкап сейчас"),"pri",runBackup)));
  }
  const names=new Map([["",tr("Эта машина")],...deckDirectory.decks.map(d=>[d.id,d.name])]);
  const source=$("backup_source").value;
  $("backup_source").replaceChildren(...[...backupSources.keys()].map(id=>{const o=el("option","",names.get(id)||id);o.value=id;return o}));
  if(backupSources.has(source))$("backup_source").value=source;
  renderBackupList();
}
function renderBackupList(){
  const source=$("backup_source").value,list=backupSources.get(source)||[];
  // A copy fetched from another machine can only be restored here; the gateway can push its own copies anywhere.
  const targets=[["",tr("Эта машина")],...(!selectedDeck&&!source?deckDirectory.decks.map(d=>[d.id,d.name]):[])];
  $("backup_target").replaceChildren(...targets.map(([id,name])=>{const o=el("option","",name);o.value=id;return o}));
  $("backup_restore_code_row").hidden=Boolean(backupStatus?.configured);
  $("backup_list").replaceChildren(...(list.length?list.map(meta=>el("div","deck-connection deck-result",
    el("div","deck-info",el("strong","",backupLabel(meta,DATE_LOCALE))),
    el("div","deck-actions",btn(tr("Восстановить"),"",()=>restoreBackup(meta,source)))))
    :[el("p","",tr("Копий пока нет"))]));
}
async function enableBackups(){
  try{const result=await api("/api/backup_setup",{});$("backup_code").textContent=result.code;$("backup_code_card").hidden=false;$("backup_code_card").scrollIntoView({block:"nearest"})}
  catch(e){toast(e.message);return}
  await loadBackups();
}
function copyBackupCode(){copyToClipboard($("backup_code").textContent,window)}
async function finishBackupCode(){
  // The code is shown once; it is not kept in the page after confirmation.
  $("backup_code").textContent="";$("backup_code_card").hidden=true;
  await runBackup();
}
async function joinBackups(){
  try{await api("/api/backup_setup",{code:$("backup_join_code").value});$("backup_join_code").value="";$("backup_join_card").hidden=true;await runBackup()}
  catch(e){toast(e.message)}
}
async function runBackup(){
  toast(tr("Делаю бэкап…"),true);
  try{await api("/api/backup_run",{});toast(tr("Бэкап готов"),"success")}catch(e){toast(e.message)}
  await loadBackups();
}
async function downloadBackup(){
  const last=backupStatus?.stored.find(m=>m.origin===backupStatus.instance);
  if(!last){toast(tr("Сначала сделайте бэкап"));return}
  try{
    const data=await api("/api/backup_blob?origin="+last.origin+"&created="+last.created);
    const bytes=Uint8Array.from(atob(data.blob),c=>c.charCodeAt(0)),link=document.createElement("a");
    link.href=URL.createObjectURL(new Blob([bytes],{type:"application/octet-stream"}));
    link.download="agent-deck-"+last.name.replace(/[^A-Za-z0-9_-]+/g,"-")+"-"+last.created+".adbk";
    link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
  }catch(e){toast(e.message)}
}
async function restoreBackup(meta,source,blob){
  const target=$("backup_target").value,targetName=$("backup_target").selectedOptions[0]?.textContent||"";
  const code=$("backup_restore_code").value.trim();
  if(!backupStatus?.configured&&!target&&!code){toast(tr("Введите код восстановления"));$("backup_restore_code").focus();return}
  const ok=await confirmAction(tr("Восстановить «{0}» от {1}?",[meta.name,formatBackupTime(meta.created,DATE_LOCALE)]),
    {text:tr("Настройки, ключи и логины агентов на «{0}» будут заменены. Текущее состояние сохранится в бэкап, панель перезапустится.",[targetName]),confirm:tr("Восстановить"),danger:true});
  if(!ok)return;
  try{
    if(target)await api("/api/backup_restore_remote",{deck:target,origin:meta.origin,created:meta.created});
    else await api("/api/backup_restore",blob?{blob,code}:{origin:meta.origin,created:meta.created,deck:source||undefined,code:code||undefined});
  }catch(e){toast(e.message);return}
  if(target){toast(tr("Восстановлено на «{0}». Панель там перезапускается.",[targetName]),"success");return}
  toast(tr("Восстановлено. Панель перезапускается…"),true);
  setTimeout(()=>location.reload(),5000);
}
function restoreBackupFile(input){
  const file=input.files[0];input.value="";if(!file)return;
  const reader=new FileReader();
  reader.onload=()=>{
    const blob=String(reader.result).split(",")[1];
    $("backup_target").value="";
    restoreBackup({name:file.name,created:Math.floor(file.lastModified/1000)},"",blob);
  };
  reader.readAsDataURL(file);
}

if(typeof module!=="undefined")module.exports={formatBackupTime,backupReportLines,backupLabel};
