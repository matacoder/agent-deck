// Changes, commits and files of the open session in one panel: a right sidebar on wide screens that stays
// open while sessions switch (remembered in this browser), a full-screen dialog on phones. Each tab keeps
// its own state and scroll; a tab loads for the open session only when shown.
const PROJECT_TABS=["changes","commits","files"];
const project={tab:"changes",moving:false};
const projectDocked=()=>!isMobile();
function savedProjectTab(){try{const tab=localStore.getItem("cc.project");return PROJECT_TABS.includes(tab)?tab:""}catch(e){return ""}}
function rememberProject(tab){try{localStore.setItem("cc.project",tab)}catch(e){}}

function openFiles(){openProject("files")}
function openHistory(){openProject("changes")}
// The bar buttons hide the sidebar when it already shows their tab.
function toggleProject(tabs){
  const box=$("project_dlg");
  if(box.open&&box.classList.contains("docked")&&tabs.includes(project.tab))return closeProject();
  openProject(tabs[0]);
}
function openProject(tab){
  if(!active)return;
  placeProject(true);
  projectTab(tab);
}
// A tab chosen by hand always shows the current state: the agent keeps working.
function projectTab(tab){
  project.tab=tab;
  if(projectDocked())rememberProject(tab);
  markProjectTab();
  if(tab==="files"){if(files.session!==active&&!filesDirty())startFiles();return}
  if(hist.session!==active)return startHistory(tab);
  historyTab(tab);
}
// Shown for another session (a switch with the sidebar open): load only what is out of date.
function refreshProject(){
  markProjectTab();
  if(project.tab==="files"){if(files.session!==active&&!filesDirty())startFiles();return}
  if(hist.session!==active)startHistory(project.tab);
}
function markProjectTab(){
  for(const b of $("project_tabs").querySelectorAll("[data-tab]")){const on=b.dataset.tab===project.tab;b.classList.toggle("on",on);b.setAttribute("aria-selected",String(on))}
  $("git_body").hidden=project.tab==="files";$("files_body").hidden=project.tab!=="files";
  const box=$("project_dlg"),shown=box.open&&box.classList.contains("docked");
  $("b_files").setAttribute("aria-pressed",String(shown&&project.tab==="files"));
  $("b_history").setAttribute("aria-pressed",String(shown&&project.tab!=="files"));
}
// Opens (or moves) the panel in the form this layout uses: docked beside the session or modal.
function placeProject(open){
  const box=$("project_dlg"),docked=projectDocked();
  if(box.open&&box.classList.contains("docked")!==docked){project.moving=true;box.close();project.moving=false;open=true}
  if(!open||box.open)return;
  applyCodeFont();box.classList.toggle("docked",docked);
  if(docked)box.open=true;  // Not modal: the terminal and the message field stay usable beside it.
  else box.showModal();
}
// Called after every session or layout change: a wide screen restores the remembered sidebar.
function syncProject(){
  const box=$("project_dlg");
  if(!projectDocked()){
    if(box.open&&box.classList.contains("docked")){project.moving=true;box.close();project.moving=false}
    return markProjectTab();
  }
  const tab=savedProjectTab();
  if(!tab||!active||!cur()){if(box.open){project.moving=true;box.close();project.moving=false}return markProjectTab()}
  if(!box.open)project.tab=tab;
  placeProject(true);refreshProject();
}
async function closeProject(){
  if(filesDirty()&&!await leaveFile())return;
  if(projectDocked())rememberProject("");
  $("project_dlg").close();
}
// Closed by hand (not moved between layouts): stop polling and free a previewed file's blob.
function projectClosed(){
  if(project.moving)return;
  clearTimeout(hist.timer);dropPreview();files.file=null;markProjectTab();
}
