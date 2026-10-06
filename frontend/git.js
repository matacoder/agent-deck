// Git history of the open session's repository: commits with their diffs, and feature groups that a
// cheap model (Claude Haiku) proposes from commit subjects and file names, each with a combined diff.
// Agent and repository text is rendered with textContent only.
const hist={session:null,tab:"commits",log:null,commits:[],back:null,view:null,groups:null,timer:null};

function relativeTime(seconds){
  const diff=seconds-Date.now()/1000,units=[["year",31536000],["month",2592000],["day",86400],["hour",3600],["minute",60]];
  const format=new Intl.RelativeTimeFormat(DATE_LOCALE,{numeric:"auto"});
  for(const [unit,size] of units)if(Math.abs(diff)>=size)return format.format(Math.round(diff/size),unit);
  return format.format(0,"minute");
}
// Unified diff text -> rows with old/new line numbers; headers before the first hunk are dropped.
function diffRows(patch){
  const rows=[];let oldLine=0,newLine=0,inHunk=false;
  for(const line of patch.split("\n")){
    const hunk=line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/);
    if(hunk){oldLine=+hunk[1];newLine=+hunk[2];inHunk=true;rows.push({kind:"hunk",text:line});continue}
    if(!inHunk||line.startsWith("\\"))continue;
    if(line.startsWith("+"))rows.push({kind:"add",old:"",new:newLine++,text:line.slice(1)});
    else if(line.startsWith("-"))rows.push({kind:"del",old:oldLine++,new:"",text:line.slice(1)});
    else if(line.length||rows.length)rows.push({kind:"ctx",old:oldLine++,new:newLine++,text:line.slice(1)});
  }
  while(rows.length&&rows[rows.length-1].kind==="ctx"&&!rows[rows.length-1].text)rows.pop();
  return rows;
}
function renderDiff(patch,file){
  const box=el("div","diff");
  if(file.binary){box.append(el("p","diff-note",tr("Двоичный файл")));return box}
  if(!patch){box.append(el("p","diff-note",tr("Дифф слишком большой для просмотра; откройте его в терминале")));return box}
  for(const row of diffRows(patch)){
    if(row.kind==="hunk"){box.append(el("div","dl hunk",row.text));continue}
    box.append(el("div","dl "+row.kind,el("span","ln",String(row.old)),el("span","ln",String(row.new)),el("span","code",row.text||" ")));
  }
  if(file.truncated)box.append(el("p","diff-note",tr("Показана только часть изменений")));
  return box;
}
const STATUS_MARK={added:"A",deleted:"D",renamed:"R",modified:"M"};
// Collapsed files render their diff only when opened, so large commits stay fast on a phone.
function fileBlock(title,file,open,content){
  const details=el("details","diff-file"),summary=el("summary","",el("span","diff-status "+(file.status||"modified"),STATUS_MARK[file.status]||"M"),
    el("span","diff-path",title),el("span","diff-count",el("b","plus","+"+file.added),el("b","minus","−"+file.removed)));
  details.append(summary);
  details.addEventListener("toggle",()=>{if(details.open&&details.childElementCount===1)details.append(content())});
  details.open=open;return details;
}

async function openHistory(){
  if(!active)return;
  hist.session=active;hist.tab="commits";hist.view=null;hist.back=null;hist.log=null;hist.commits=[];hist.groups=null;
  if(!$("git_dlg").open)$("git_dlg").showModal();
  renderHistory();await loadHistoryPage();
}
function gitPath(route,params={}){return "/api/git/"+route+"?"+new URLSearchParams({name:hist.session,...params})}
async function loadHistoryPage(){
  try{const page=await api(gitPath("log",{skip:hist.commits.length}));hist.log=page;hist.commits.push(...page.commits)}
  catch(e){if(e.message!==STALE)hist.error=e.message}
  renderHistory();
}
async function showCommit(sha,back){
  hist.view={kind:"loading"};hist.back=back||null;renderHistory();
  try{hist.view={kind:"commit",data:await api(gitPath("commit",{sha}))}}
  catch(e){hist.view=null;if(e.message!==STALE)toast(e.message)}
  renderHistory();$("git_body").scrollTop=0;
}
async function showGroup(group){
  hist.view={kind:"group",group,diff:null};renderHistory();$("git_body").scrollTop=0;
  try{hist.view.diff=await api(gitPath("group_diff",{shas:group.commits.join(",")}))}
  catch(e){if(e.message!==STALE)toast(e.message)}
  if(hist.view?.group===group)renderHistory();
}
async function loadGroups(){
  clearTimeout(hist.timer);
  try{hist.groups=await api(gitPath("groups"))}catch(e){if(e.message!==STALE)hist.groups={phase:"error",error:e.message}}
  if(hist.groups?.phase==="running"&&$("git_dlg").open)hist.timer=setTimeout(loadGroups,3000);
  if(hist.tab==="groups"&&!hist.view)renderHistory();
}
async function startGrouping(){
  try{hist.groups=await api("/api/git_group",{name:hist.session})}catch(e){if(e.message!==STALE)toast(e.message);return}
  renderHistory();hist.timer=setTimeout(loadGroups,3000);
}
function historyTab(tab){hist.tab=tab;hist.view=null;if(tab==="groups"&&!hist.groups)loadGroups();renderHistory()}

function commitRow(c,back){
  const row=el("button","git-row",el("span","git-subject",c.subject),
    el("span","git-meta",[c.short,c.author,relativeTime(c.time)].join(" · "),el("span","diff-count",el("b","plus","+"+c.added),el("b","minus","−"+c.removed))));
  row.type="button";row.onclick=()=>showCommit(c.sha,back);return row;
}
function renderHistory(){
  const box=$("git_body");box.replaceChildren();
  for(const b of $("git_tabs").children)b.classList.toggle("on",b.dataset.tab===hist.tab);
  if(hist.view)return renderHistoryView(box);
  if(hist.tab==="groups")return renderGroups(box);
  if(hist.error&&!hist.commits.length){box.append(el("p","files-empty",hist.error));return}
  if(!hist.log){box.append(el("p","files-empty",tr("Загрузка…")));return}
  box.append(el("p","git-repo",el("code","",hist.log.name+" · "+hist.log.branch)));
  const list=el("div","git-list");for(const c of hist.commits)list.append(commitRow(c));box.append(list);
  if(!hist.commits.length)box.append(el("p","files-empty",tr("В репозитории ещё нет коммитов")));
  if(hist.log.more){const more=el("button","git-more",tr("Показать ещё"));more.type="button";more.onclick=loadHistoryPage;box.append(more)}
}
function backButton(label,run){const b=fileButton(label,"files-up",run,"arrow-up");return el("div","files-path",b)}
function renderHistoryView(box){
  const view=hist.view;
  if(view.kind==="loading"){box.append(el("p","files-empty",tr("Загрузка…")));return}
  if(view.kind==="commit"){
    const c=view.data,[subject,...rest]=c.message.split("\n");
    const back=hist.back;
    box.append(backButton(back?tr("К группе"):tr("К коммитам"),()=>{hist.view=back?{kind:"group",group:back,diff:null}:null;if(back)showGroup(back);else renderHistory()}),
      el("h4","git-title",subject),el("p","git-meta",[c.short,c.author,new Date(c.time*1000).toLocaleString(DATE_LOCALE)].join(" · ")));
    const body=rest.join("\n").trim();if(body)box.append(el("pre","git-message",body));
    c.files.forEach((f,i)=>box.append(fileBlock(f.path,f,i<3&&c.files.length<=12,()=>renderDiff(f.patch,f))));
    return;
  }
  const group=view.group;
  box.append(backButton(tr("К группам"),()=>{hist.view=null;renderHistory()}),el("h4","git-title",group.ungrouped?tr("Без группы"):group.title));
  if(group.summary)box.append(el("p","git-summary",group.summary));
  const list=el("div","git-list");
  for(const sha of group.commits){const c=hist.groups?.commits?.[sha];if(c)list.append(commitRow(c,group))}
  box.append(list,el("h5","git-section",tr("Общий дифф")));
  if(!view.diff){box.append(el("p","files-empty",tr("Загрузка…")));return}
  for(const file of view.diff.files){
    box.append(fileBlock(file.path,file,false,()=>{
      const wrap=el("div","");
      for(const change of file.changes)wrap.append(el("div","diff-commit",change.short+" · "+change.subject),renderDiff(change.patch,change));
      return wrap;
    }));
  }
}
function renderGroups(box){
  const state=hist.groups;
  if(!state){box.append(el("p","files-empty",tr("Загрузка…")));return}
  if(state.phase==="done"){
    for(const group of state.groups){
      const card=el("button","git-group",el("span","git-subject",group.ungrouped?tr("Без группы"):group.title),
        ...(group.summary?[el("span","git-summary",group.summary)]:[]),el("span","git-meta",tr("Коммитов: {0}",[group.commits.length])));
      card.type="button";card.onclick=()=>showGroup(group);box.append(card);
    }
    const again=el("button","git-more",tr("Сгруппировать заново"));again.type="button";again.onclick=startGrouping;box.append(again);
    return;
  }
  if(state.phase==="running"){box.append(el("p","files-empty",tr("Claude Haiku группирует коммиты по фичам. Это занимает до пары минут.")));return}
  box.append(el("p","git-summary",tr("Claude Haiku прочитает заголовки последних 80 коммитов и имена изменённых файлов (без кода) и объединит их в группы по фичам. Результат сохраняется до следующего коммита.")));
  if(state.phase==="error")box.append(el("p","diff-note",state.error));
  const start=fileButton(tr("Сгруппировать коммиты"),"pri",startGrouping);box.append(el("div","acts",start));
}

if(typeof module!=="undefined")module.exports={diffRows};
