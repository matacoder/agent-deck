let backupStatus=null,backupSources=new Map();

function formatBackupTime(seconds,locale){
  return new Date(seconds*1000).toLocaleString(locale,{dateStyle:"medium",timeStyle:"short"});
}
// One line per machine for the last cycle: what is protected and what needs attention.
function backupReportLines(report,translate,locale){
  if(!report)return [];
  // Errors often start with the machine's name, which the row already shows.
  const own=m=>String(m.error||"").startsWith(m.name+": ")?m.error.slice(m.name.length+2):m.error;
  return report.machines.map(m=>({ok:m.ok,name:m.name,text:m.ok?translate("копий на других компьютерах: {0}",[m.copies||0]):own(m)||translate("ошибка")}))
    .concat(report.finished?[{ok:true,name:"",text:translate("Последняя проверка всех копий: {0}",[formatBackupTime(report.finished,locale)])}]:[]);
}
function backupLabel(meta,locale){
  return meta.name+" · "+formatBackupTime(meta.created,locale)+" · "+Math.max(1,Math.round((meta.size||0)/1024))+" KB";
}

async function loadBackups(){
  // A computer whose backups cannot be read shows nothing of the previous one; the error is only worth a
  // toast where backups are being looked at.
  try{backupStatus=await api("/api/backups")}catch(e){backupStatus=null;backupSources=new Map();if(hubSection==="backups"&&e.message!==STALE)toast(e.message);return}
  backupSources=new Map([["",backupStatus.stored]]);
  // Copies kept by connected machines are reachable only from the gateway that holds their logins.
  if(!selectedDeck)await Promise.all(deckDirectory.decks.map(async d=>{
    try{backupSources.set(d.id,(await api(instancePath(d.id,"/api/backups"),null,true)).stored||[])}catch(e){}
  }));
  renderBackups();
}
let backupRestoreOpen=false;
function renderBackupState(s){
  const status=$("backup_status"),busy=!$("backup_code_card").hidden||!$("backup_join_card").hidden;
  if(!s.configured){
    status.textContent=tr("Выключены");status.className="card-status warn";$("backup_meta").textContent="";
    // While a recovery-code step is open, its own buttons are the only ones.
    $("backup_state").replaceChildren(el("p","hint",tr("Без бэкапа ключи и логины агентов пропадут при переустановке.")),
      ...(busy?[]:[el("div","acts",btn(tr("Уже включены на другом компьютере"),"",openBackupJoin),btn(tr("Включить бэкапы"),"pri",enableBackups))]));
    return;
  }
  status.textContent=tr("Включены");status.className="card-status ok";
  $("backup_meta").textContent=tr("Код восстановления …{0} · последний бэкап: {1}",[String(s.key_id||"").slice(-4),s.last?formatBackupTime(s.last,DATE_LOCALE):tr("ещё не было")]);
  const rows=backupReportLines(s.report,tr,DATE_LOCALE).map(l=>l.name?hubRow({title:l.name,status:l.text,tone:l.ok?"ok":"bad"}):el("p","card-meta",l.text));
  $("backup_state").replaceChildren(...rows,el("div","acts",btn(tr("Скачать файл"),"",downloadBackup),btn(tr("Сделать бэкап сейчас"),"pri",runBackup)));
}
function renderBackups(){
  const s=backupStatus;if(!s)return;
  renderBackupState(s);
  const names=new Map([["",tr("Этот компьютер")],...deckDirectory.decks.map(d=>[d.id,d.name])]);
  const source=$("backup_source").value;
  $("backup_source").replaceChildren(...[...backupSources.keys()].map(id=>{const o=el("option","",names.get(id)||id);o.value=id;return o}));
  if(backupSources.has(source))$("backup_source").value=source;
  // Nothing to restore from yet: one link instead of empty pickers.
  const any=[...backupSources.values()].some(list=>list.length);
  const collapsed=!s.configured&&!any&&!backupRestoreOpen;
  $("backup_restore_open").hidden=!collapsed;$("backup_restore_body").hidden=collapsed;
  renderBackupList();
  if($("settings_dlg").open){updateHubDots();renderSetupCard()}
}
function openBackupRestore(){backupRestoreOpen=true;renderBackups()}
function openBackupJoin(){
  $("backup_join_card").hidden=false;$("backup_state").after($("backup_join_card"));snapshotEditor($("backup_join_card"));renderBackups();
  if(!isMobile())$("backup_join_code").focus();
}
function closeBackupJoin(){$("backup_join_card").hidden=true;$("backup_join_code").value="";renderBackups()}
function renderBackupList(){
  const source=$("backup_source").value,list=backupSources.get(source)||[];
  // A copy fetched from another machine can only be restored here; the gateway can push its own copies anywhere.
  const targets=[["",tr("Этот компьютер")],...(!selectedDeck&&!source?deckDirectory.decks.map(d=>[d.id,d.name]):[])];
  $("backup_target").replaceChildren(...targets.map(([id,name])=>{const o=el("option","",name);o.value=id;return o}));
  $("backup_restore_code_row").hidden=Boolean(backupStatus?.configured);
  $("backup_list").replaceChildren(...(list.length?list.map(meta=>hubRow({title:backupLabel(meta,DATE_LOCALE),
    actions:[labelledButton(tr("Восстановить"),"",()=>restoreBackup(meta,source),backupLabel(meta,DATE_LOCALE))]}))
    :[el("p","hint",tr("Копий пока нет"))]));
}
async function enableBackups(){
  try{const result=await api("/api/backup_setup",{});$("backup_code").textContent=result.code;$("backup_code_card").hidden=false;$("backup_state").after($("backup_code_card"));$("backup_code_card").scrollIntoView({block:"nearest"})}
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
  try{await api("/api/backup_setup",{code:$("backup_join_code").value});closeBackupJoin();await runBackup()}
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
  let warned=false;
  const ok=await confirmAction(tr("Восстановить «{0}» от {1}?",[meta.name,formatBackupTime(meta.created,DATE_LOCALE)]),
    {text:tr("Настройки, ключи и логины агентов на «{0}» будут заменены. Текущее состояние сохранится в бэкап, панель перезапустится.",[targetName]),confirm:tr("Восстановить"),danger:true});
  if(!ok)return;
  try{
    if(target)await api("/api/backup_restore_remote",{deck:target,origin:meta.origin,created:meta.created});
    else{
      const result=await api("/api/backup_restore",blob?{blob,code}:{origin:meta.origin,created:meta.created,deck:source||undefined,code:code||undefined});
      warned=(result.restored?.warnings||[]).length>0;
      // One toast: each call replaces the previous one, so separate toasts would hide all but the last.
      const warnings=(result.restored?.warnings||[]).map(w=>tr(w));if(warnings.length)toast(warnings.join(" "));
    }
  }catch(e){toast(e.message);return}
  if(target){toast(tr("Восстановлено на «{0}». Панель там перезапускается.",[targetName]),"success");return}
  if(!warned)toast(tr("Восстановлено. Панель перезапускается…"),true);
  setTimeout(()=>location.reload(),warned?12000:5000);  // Leave time to read a warning.
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
