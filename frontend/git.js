// Git history of the open session's repository: uncommitted changes (a tapped line becomes a comment in the
// message draft; a clean tree shows the last commit), commits with their diffs, and feature groups that a model proposes from commit subjects
// and file names, each with a combined diff.
// Agent and repository text is rendered with textContent only.
// tree: the working tree picked by hand, "" while the server follows the one the agent's output names.
const hist={session:null,ref:"",tree:"",tab:"changes",authors:null,changes:null,changesError:"",changesSeq:0,log:null,commits:[],back:null,view:null,groups:null,timer:null,fetching:false,
  seq:0,loadingPage:false,error:""};
// Every list (session, branch) gets a new number; an answer for an older one is dropped instead of being
// mixed into the list that is on screen now.
function freshList(){hist.seq++;hist.log=null;hist.commits=[];hist.groups=null;hist.view=null;hist.error="";hist.loadingPage=false}

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
// onLine: given for uncommitted changes, where a tapped line opens a comment for the agent.
function renderDiff(patch,file,onLine){
  const box=el("div","diff");
  if(file.binary){box.append(el("p","diff-note",tr("Двоичный файл")));return box}
  if(!patch){box.append(el("p","diff-note",tr("Дифф слишком большой для просмотра; откройте его в терминале")));return box}
  for(const row of diffRows(patch)){
    if(row.kind==="hunk"){box.append(el("div","dl hunk",row.text));continue}
    const line=el("div","dl "+row.kind,el("span","ln",String(row.old)),el("span","ln",String(row.new)),el("span","code",row.text||" "));
    if(onLine){
      line.classList.add("commentable");line.tabIndex=0;line.setAttribute("role","button");
      // Selecting text to copy is not a request to comment.
      line.onclick=()=>{if(!String(getSelection()||""))onLine(row,line)};
      line.onkeydown=e=>{if(e.key==="Enter"){e.preventDefault();onLine(row,line)}};
    }
    box.append(line);
  }
  if(file.truncated)box.append(el("p","diff-note",tr("Показана только часть изменений")));
  return box;
}
const STATUS_MARK={added:"A",deleted:"D",renamed:"R",modified:"M"};
// One code size for diffs and commit messages, kept in this browser.
const CODE_FONT={min:9,max:20,fallback:12};
function codeFontSize(){const saved=+localStore.getItem("cc.code-font");return saved>=CODE_FONT.min&&saved<=CODE_FONT.max?saved:CODE_FONT.fallback}
function applyCodeFont(){document.documentElement.style.setProperty("--code-font",codeFontSize()+"px")}
function codeFont(step){
  const size=Math.min(CODE_FONT.max,Math.max(CODE_FONT.min,codeFontSize()+step));
  try{localStore.setItem("cc.code-font",String(size))}catch(e){}
  applyCodeFont();
}
// Collapsed files render their diff only when opened, so large commits stay fast on a phone.
function fileBlock(title,file,open,content){
  const binary=file.binary||file.changes?.every(change=>change.binary);
  const details=el("details","diff-file"),summary=el("summary","",el("span","diff-status "+(file.status||"modified"),STATUS_MARK[file.status]||"M"),
    el("span","diff-path",title),binary?el("span","diff-binary",tr("двоичный")):el("span","diff-count",el("b","plus","+"+file.added),el("b","minus","−"+file.removed)));
  details.append(summary);
  details.addEventListener("toggle",()=>{if(details.open&&details.childElementCount===1)details.append(content())});
  details.open=open&&!binary;return details;
}

function startHistory(tab){
  hist.session=active;hist.ref="";hist.tree="";hist.tab=tab;hist.back=null;hist.models=null;hist.authors=savedAuthorColors();freshList();
  renderHistory();loadChanges();loadHistoryPage();
}
async function loadChanges(){
  const seq=++hist.changesSeq;hist.changes=null;hist.changesError="";
  if(hist.tab==="changes"&&!hist.view)renderHistory();
  try{
    const data=await api(gitPath("changes",{tree:hist.tree}),null,false,{timeout:60000});
    // A clean tree shows the last commit instead, so the tab is never empty right after a commit.
    if(!data.files.length&&data.head&&seq===hist.changesSeq)data.last=await lastCommit(data.head);
    if(seq!==hist.changesSeq)return;hist.changes=data;
    // The agent moved to another worktree: the commit list follows it.
    if(data.tree&&hist.log?.tree&&hist.log.tree!==data.tree){freshList();loadHistoryPage()}
  }catch(e){if(seq!==hist.changesSeq)return;hist.changesError=e.message===STALE?"":e.message||tr("Не удалось загрузить")}
  if(hist.tab==="changes"&&!hist.view)renderHistory();
}
async function lastCommit(sha){
  try{return await api(gitPath("commit",{sha}),null,false,{timeout:60000})}
  catch(e){return {error:e.message===STALE?"":e.message||tr("Не удалось загрузить")}}
}
// Later pages, commits and groups stay on the tree the list was made for.
const shownTree=()=>hist.tree||hist.log?.tree||hist.changes?.tree||"";
function gitPath(route,params={}){return "/api/git/"+route+"?"+new URLSearchParams({name:hist.session,ref:hist.ref,tree:shownTree(),...params})}
function chooseTree(tree){hist.tree=tree;freshList();renderHistory();loadChanges();loadHistoryPage()}
function treeLabel(tree){return tree.name+" · "+tree.branch}
// Several worktrees: a quiet picker whose first entry follows the agent; one tree: just where we are.
function treePicker(data){
  if(!(data.trees?.length>1))return [el("code","",data.name),el("span","sep","·"),el("span","",data.branch)];
  const current=data.trees.find(t=>t.path===data.tree)||data.trees[0];
  const select=el("select","git-tree");select.setAttribute("aria-label",tr("Рабочее дерево"));
  const auto=el("option","",data.auto?tr("{0} · авто",[treeLabel(current)]):tr("Авто"));auto.value="";select.append(auto);
  for(const tree of data.trees){const option=el("option","",treeLabel(tree));option.value=tree.path;select.append(option)}
  select.value=hist.tree;select.onchange=()=>chooseTree(select.value);
  return [el("code","",data.trees[0].name),el("span","sep","·"),select];
}
// Another branch (a worktree's own, the local main, or GitHub's after a fetch) starts the list over.
function chooseBranch(ref){hist.ref=ref;freshList();renderHistory();loadHistoryPage();if(hist.tab==="groups")loadGroups()}
async function fetchRemote(){
  if(hist.fetching)return;
  hist.fetching=true;renderHistory();
  try{await api("/api/git_fetch",{name:hist.session});toast(tr("Ветки обновлены с GitHub"),"success");hist.fetching=false;chooseBranch(hist.ref);return}
  catch(e){if(e.message!==STALE)toast(e.message)}
  hist.fetching=false;renderHistory();
}
function branchBar(){
  const log=hist.log,select=el("select","git-branch");select.setAttribute("aria-label",tr("Ветка"));
  for(const name of log.branches){const option=el("option","",name);option.value=name===log.branches[0]?"":name;select.append(option)}
  select.value=hist.ref;select.onchange=()=>chooseBranch(select.value);
  const fetch=fileButton(hist.fetching?tr("Получаю…"):tr("Получить с GitHub"),"git-fetch",fetchRemote,"refresh");fetch.disabled=hist.fetching;
  const groups=fileButton(tr("Группы фич"),"git-fetch",()=>historyTab("groups"));
  const bar=el("div","git-bar",el("code","",log.name),select,fetch,groups);
  const notes=[];
  if(log.behind&&log.remote)notes.push(el("div","git-behind",el("span","",tr("Эта ветка отстаёт от {0} на {1} коммитов",[log.remote,log.behind])),
    fileButton(tr("Показать {0}",[log.remote]),"",()=>chooseBranch(log.remote))));
  return [bar,...notes];
}
async function loadHistoryPage(){
  if(hist.loadingPage)return;  // A double tap on "Show more" would ask for the same page twice.
  // Commits load in the background while Changes is open; redrawing it would close a comment being typed.
  const seq=hist.seq;hist.loadingPage=true;hist.error="";if(hist.tab!=="changes")renderHistory();
  try{
    const page=await api(gitPath("log",{skip:hist.commits.length}),null,false,{timeout:60000});
    if(seq!==hist.seq)return;
    hist.log=page;hist.commits.push(...page.commits);
  }catch(e){if(seq===hist.seq&&e.message!==STALE)hist.error=e.message}
  finally{if(seq===hist.seq){hist.loadingPage=false;if(hist.tab!=="changes")renderHistory()}}
}
async function showCommit(sha,back){
  const view={kind:"loading",back:back||null};hist.view=view;hist.back=back||null;renderHistory();
  try{const data=await api(gitPath("commit",{sha}),null,false,{timeout:60000});if(hist.view!==view)return;hist.view={kind:"commit",data}}
  catch(e){if(hist.view!==view)return;hist.view={kind:"error",error:e.message===STALE?"":e.message,retry:()=>showCommit(sha,back),back:back||null}}
  renderHistory();$("git_body").scrollTop=0;
}
async function showGroup(group){
  const view={kind:"group",group,diff:null};hist.view=view;renderHistory();$("git_body").scrollTop=0;
  try{view.diff=await api(gitPath("group_diff",{shas:group.commits.join(",")}),null,false,{timeout:120000})}
  catch(e){view.error=e.message===STALE?"":e.message}
  if(hist.view===view)renderHistory();
}
async function loadGroups(){
  clearTimeout(hist.timer);
  const seq=hist.seq;
  let state;
  try{state=await api(gitPath("groups"))}catch(e){state=e.message===STALE?null:{phase:"error",error:e.message}}
  if(seq!==hist.seq||!state)return;
  hist.groups=state;
  if(state.phase==="running"&&$("project_dlg").open)hist.timer=setTimeout(loadGroups,3000);
  if(hist.tab==="groups"&&!hist.view)renderHistory();
}
// Any model this computer can reach groups commits; local ones come first because they cost nothing.
async function loadGroupModels(){
  try{hist.models=(await api(gitPath("models"))).models||[]}catch(e){hist.models=[]}
  if(hist.tab==="groups"&&!hist.view)renderHistory();
}
function groupModel(){
  let saved="";try{saved=deckLocalStorage.getItem("cc.group-model")||""}catch(e){}
  const models=hist.models||[];
  return models.some(m=>m.id===saved)?saved:(models[0]?.id||"claude");
}
function modelPicker(){
  const models=hist.models||[];
  if(!models.length)return null;
  const select=el("select","git-branch");select.setAttribute("aria-label",tr("Модель для группировки"));
  for(const m of models){const option=el("option","",m.local?tr("{0} — локально, бесплатно",[m.label]):m.label);option.value=m.id;select.append(option)}
  select.value=groupModel();
  select.onchange=()=>{try{deckLocalStorage.setItem("cc.group-model",select.value)}catch(e){}};
  return el("label","git-model",el("span","",tr("Модель")),select);
}
async function startGrouping(){
  try{hist.groups=await api("/api/git_group",{name:hist.session,ref:hist.ref,tree:shownTree(),model:groupModel()})}catch(e){if(e.message!==STALE)toast(e.message);return}
  renderHistory();hist.timer=setTimeout(loadGroups,3000);
}
function historyTab(tab){
  hist.tab=tab;hist.view=null;
  if(tab==="groups"){if(!hist.groups)loadGroups();if(!hist.models)loadGroupModels()}
  if(tab==="changes")return loadChanges();  // The agent keeps working: always the current state.
  renderHistory();
}

// Authors get colours in this order, chosen so the first few are as far apart as possible; green and
// red are left out because they already mean added and removed lines. An author keeps the colour
// first given (remembered in this browser), so the same person looks the same everywhere.
const AUTHOR_COLORS=["#64d2ff","#ff9f0a","#bf5af2","#ffd60a","#f472b6","#66d4cf","#7d7aff","#c69c6d"];
function authorColor(name,taken){
  if(!taken.has(name)){
    const used=new Set(taken.values());
    const free=AUTHOR_COLORS.findIndex((_,index)=>!used.has(index));
    taken.set(name,free>=0?free:taken.size%AUTHOR_COLORS.length);
    // Only the most recent authors are remembered; the list must not grow forever.
    try{localStore.setItem("cc.author-colors",JSON.stringify([...taken].slice(-200)))}catch(e){}
  }
  return AUTHOR_COLORS[taken.get(name)];
}
function savedAuthorColors(){
  try{return new Map(JSON.parse(localStore.getItem("cc.author-colors")||"[]").filter(([name,index])=>typeof name==="string"&&Number.isInteger(index)&&index>=0&&index<AUTHOR_COLORS.length))}
  catch(e){return new Map()}
}
function authorLabel(name){const label=el("span","git-author",name);label.style.setProperty("--author",authorColor(name||"?",hist.authors));return label}
function commitRow(c,back){
  const color=authorColor(c.author||"?",hist.authors);
  const row=el("button","git-row",el("span","git-subject",c.subject),
    el("span","git-meta",c.short,el("span","sep","·"),el("span","git-author",c.author),el("span","sep","·"),relativeTime(c.time),el("span","diff-count",el("b","plus","+"+c.added),el("b","minus","−"+c.removed))));
  row.style.setProperty("--author",color);
  row.type="button";row.onclick=()=>showCommit(c.sha,back);return row;
}
function renderHistory(){
  const box=$("git_body");box.replaceChildren();
  if(hist.view)return renderHistoryView(box);
  if(hist.tab==="groups")return renderGroups(box);
  if(hist.tab==="changes")return renderChanges(box);
  if(hist.error&&!hist.log){box.append(errorWithRetry(hist.error,loadHistoryPage));return}
  if(!hist.log){box.append(el("p","files-empty",tr("Загрузка…")));return}
  box.append(...branchBar());
  const list=el("div","git-list");for(const c of hist.commits)list.append(commitRow(c));box.append(list);
  if(!hist.commits.length)box.append(el("p","files-empty",tr("В репозитории ещё нет коммитов")));
  if(hist.error)box.append(errorWithRetry(hist.error,loadHistoryPage));
  else if(hist.log.more){const more=el("button","git-more",hist.loadingPage?tr("Загрузка…"):tr("Показать ещё"));more.type="button";more.disabled=hist.loadingPage;more.onclick=loadHistoryPage;box.append(more)}
}
// A failed load says what went wrong and offers to try again instead of "Loading…" forever.
function errorWithRetry(message,retry){
  const again=fileButton(tr("Повторить"),"",retry,"refresh");
  return el("div","git-error",el("p","diff-note",message||tr("Не удалось загрузить")),again);
}
// Back to the previous view points left; "Up" (a parent folder) keeps its up arrow.
function backButton(label,run){const b=fileButton(label,"files-up",run,"arrow-left");return el("div","files-path",b)}
function renderHistoryView(box){
  const view=hist.view;
  const leave=()=>{if(view.back)showGroup(view.back);else{hist.view=null;renderHistory()}};
  if(view.kind==="loading"||view.kind==="error"){
    box.append(backButton(view.back?tr("К группе"):tr("К коммитам"),leave),
      view.kind==="error"?errorWithRetry(view.error,view.retry):el("p","files-empty",tr("Загрузка…")));
    return;
  }
  if(view.kind==="commit"){
    const back=hist.back;
    box.append(backButton(back?tr("К группе"):tr("К коммитам"),()=>{hist.view=back?{kind:"group",group:back,diff:null}:null;if(back)showGroup(back);else renderHistory()}));
    return commitDetails(box,view.data);
  }
  const group=view.group;
  box.append(backButton(tr("К группам"),()=>{hist.view=null;renderHistory()}),el("h4","git-title",group.ungrouped?tr("Без группы"):group.title));
  if(group.summary)box.append(el("p","git-summary",group.summary));
  const list=el("div","git-list");
  for(const sha of group.commits){const c=hist.groups?.commits?.[sha];if(c)list.append(commitRow(c,group))}
  box.append(list,el("h5","git-section",tr("Общий дифф")));
  if(view.error!==undefined){box.append(errorWithRetry(view.error,()=>showGroup(group)));return}
  if(!view.diff){box.append(el("p","files-empty",tr("Загрузка…")));return}
  for(const file of view.diff.files){
    box.append(fileBlock(file.path,file,true,()=>{
      const wrap=el("div","");
      for(const change of file.changes)wrap.append(el("div","diff-commit",change.short+" · "+change.subject),renderDiff(change.patch,change));
      return wrap;
    }));
  }
}
// compact: the last commit under Changes shows only its subject and who/when; the full message is in Commits.
function commitDetails(box,c,compact){
  const [subject,...rest]=c.message.split("\n");
  const when=compact?relativeTime(c.time):new Date(c.time*1000).toLocaleString(DATE_LOCALE);
  box.append(el("h4","git-title"+(compact?" compact":""),subject),el("p","git-meta",c.short,el("span","sep","·"),authorLabel(c.author),el("span","sep","·"),when));
  const body=rest.join("\n").trim();if(body&&!compact)box.append(el("pre","git-message",body));
  for(const f of c.files)box.append(fileBlock(f.path,f,true,()=>renderDiff(f.patch,f)));
}
// A comment names the file, the line and quotes it, so the agent finds the place without the diff.
function lineComment(path,row,text){
  const where=row.new!==""?path+":"+row.new:path+":"+row.old+" ("+tr("удалённая строка")+")";
  // Repository text can hide control characters (escape sequences) that would act as keys in the agent.
  const code=row.text.replace(/[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/g,"").trim();
  return where+(code?" `"+(code.length>120?code.slice(0,120)+"…":code).replace(/`/g,"'")+"`":"")+" — "+text.trim();
}
function appendToMessage(text){
  const join=current=>{current=current.replace(/\s+$/,"");return (current?current+"\n":"")+text};
  // The comment belongs to the session whose history is open, even if another one became active meanwhile.
  if(active!==hist.session){messageDrafts.set(hist.session,join(messageDrafts.get(hist.session)||""));return}
  const box=$("msg");box.value=join(box.value);
  box.dispatchEvent(new Event("input"));  // Saves the draft for this session and resizes the field.
}
function commentForm(path,row,line){
  const open=line.nextElementSibling;
  if(open?.classList.contains("diff-comment")){open.querySelector("textarea").focus();return}
  const area=el("textarea","");area.rows=2;area.placeholder=tr("Комментарий для агента");area.setAttribute("aria-label",tr("Комментарий для агента"));
  const form=el("form","diff-comment",area);
  const cancel=fileButton(tr("Отмена"),"",()=>form.remove()),add=fileButton(tr("Добавить в сообщение"),"pri",null);
  add.type="submit";form.append(el("div","acts",cancel,add));
  form.onsubmit=e=>{
    e.preventDefault();
    if(!area.value.trim()){area.focus();return}
    appendToMessage(lineComment(path,row,area.value));form.remove();
    toast(tr("Комментарий добавлен в сообщение"),"success",{label:tr("К сообщению"),run:()=>{if(!projectDocked())closeProject();$("msg").focus()}});
  };
  area.onkeydown=e=>{if(e.key==="Enter"&&(e.metaKey||e.ctrlKey)){e.preventDefault();form.requestSubmit()}};
  line.after(form);area.focus();
}
function renderChanges(box){
  const data=hist.changes;
  if(hist.changesError){box.append(errorWithRetry(hist.changesError,loadChanges));return}
  if(!data){box.append(el("p","files-empty",tr("Загрузка…")));return}
  // One line for where we are; the refresh button is an icon to keep the first change high on the screen.
  const refresh=el("button","git-refresh",svgIcon("refresh"));refresh.type="button";refresh.onclick=loadChanges;
  refresh.setAttribute("aria-label",tr("Обновить"));refresh.title=tr("Обновить");
  box.append(el("div","git-head",...treePicker(data),refresh));
  if(!data.files.length)return renderLastCommit(box,data.last);
  box.append(el("p","git-meta",tr("Нажмите на строку, чтобы добавить комментарий в сообщение агенту")));
  // Many files stay folded: each diff renders only when opened, which keeps a phone responsive.
  const open=data.files.length<=5;
  for(const f of data.files)box.append(fileBlock(f.path,f,open,()=>renderDiff(f.patch,f,(row,line)=>commentForm(f.path,row,line))));
  if(data.skipped)box.append(el("p","diff-note",tr("Ещё новых файлов: {0}; они не показаны",[data.skipped])));
}
function renderLastCommit(box,last){
  if(!last){box.append(el("p","files-empty",tr("Незакоммиченных изменений нет")));return}
  box.append(el("p","git-meta",tr("Всё закоммичено · последний коммит")));
  if(last.error!==undefined)box.append(el("p","diff-note",last.error||tr("Не удалось загрузить")));
  else commitDetails(box,last,true);
}
function renderGroups(box){
  const state=hist.groups;
  box.append(backButton(tr("К коммитам"),()=>historyTab("commits")));
  if(!state){box.append(el("p","files-empty",tr("Загрузка…")));return}
  if(state.phase==="done"){
    for(const group of state.groups){
      const card=el("button","git-group",el("span","git-subject",group.ungrouped?tr("Без группы"):group.title),
        ...(group.summary?[el("span","git-summary",group.summary)]:[]),el("span","git-meta",tr("Коммитов: {0}",[group.commits.length])));
      card.type="button";card.onclick=()=>showGroup(group);box.append(card);
    }
    if(state.model)box.append(el("p","git-meta",tr("Сгруппировано: {0}",[state.model])));
    const again=el("button","git-more",tr("Сгруппировать заново"));again.type="button";again.onclick=startGrouping;
    box.append(...[modelPicker(),again].filter(Boolean));
    return;
  }
  if(state.phase==="running"){box.append(el("p","files-empty",tr("Модель группирует коммиты по фичам. Локальной модели может понадобиться несколько минут.")));return}
  box.append(el("p","git-summary",tr("Модель прочитает заголовки последних 80 коммитов и имена изменённых файлов (без кода) и объединит их в группы по фичам. Результат сохраняется до следующего коммита.")));
  if(state.phase==="error")box.append(el("p","diff-note",state.error));
  const start=fileButton(tr("Сгруппировать коммиты"),"pri",startGrouping);box.append(...[modelPicker(),el("div","acts",start)].filter(Boolean));
}

if(typeof module!=="undefined")module.exports={diffRows,lineComment,authorColor,AUTHOR_COLORS};
