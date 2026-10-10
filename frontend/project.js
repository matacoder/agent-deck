// Changes, commits, feature groups, files and pictures of the open session in one panel: a right sidebar on wide screens that stays
// open while sessions switch (remembered in this browser), a full-screen dialog on phones. Each tab keeps
// its own state and scroll; a tab loads for the open session only when shown.
const PROJECT_TABS=["changes","commits","groups","files","gallery"];
const project={tab:"changes",moving:false};
const projectDocked=()=>!isMobile();
function savedProjectTab(){try{const tab=localStore.getItem("cc.project");return PROJECT_TABS.includes(tab)?tab:""}catch(e){return ""}}
function rememberProject(tab){try{localStore.setItem("cc.project",tab)}catch(e){}}

function openFiles(){openProject("files")}
function openHistory(){openProject("changes")}
// The bar button hides the panel when it is open and reopens the last tab.
function toggleProject(tabs){
  const box=$("project_dlg");
  if(box.open&&tabs.includes(project.tab))return closeProject();
  openProject(tabs.includes(project.tab)?project.tab:tabs[0]);
}
function openProject(tab){
  if(!active)return;
  const shown=$("project_dlg").open;
  placeProject(true);
  // Reopened on the same tab: what it showed stays while a quiet check runs, instead of a "Loading…"
  // and a full redraw while the drawer slides in.
  if(!shown&&tab===project.tab&&projectCurrent())return quietProject();
  projectTab(tab);
}
function projectCurrent(){
  if(project.tab==="files")return files.session===active;
  if(project.tab==="gallery")return gallery.session===active&&Boolean(gallery.items);
  return hist.session===active&&Boolean(hist.changes);
}
function quietProject(){
  markProjectTab();
  // After the drawer has slid in: a diff redrawn mid-slide is what makes it stutter.
  clearTimeout(project.quiet);
  project.quiet=setTimeout(function check(){
    const box=$("project_dlg");
    if(!box.open)return;
    if(box.style.transform){project.quiet=setTimeout(check,200);return}  // Still under the finger.
    if(project.tab==="gallery")return loadGallery();
    if(project.tab==="changes"||project.tab==="groups")pollChanges();
  },projectDrawer()?400:0);
}
// The phone drawer slides in and out like the menu on the left; elsewhere the panel just appears.
const PROJECT_DRAWER="(max-width:760px),(pointer:coarse) and (max-height:500px)";
function projectDrawer(){return !projectDocked()&&typeof matchMedia==="function"&&matchMedia(PROJECT_DRAWER).matches}
function projectSlides(box){
  return !box.classList.contains("docked")&&projectDrawer()&&!matchMedia("(prefers-reduced-motion:reduce)").matches;
}
// In: closed, the drawer already waits past the edge (style.css), so showing it is the slide.
function slideProject(box){
  box.style.transform="translateX(calc(100% + 48px))";
  return new Promise(done=>{
    const end=()=>{clearTimeout(timer);box.removeEventListener("transitionend",end);done()};
    const timer=setTimeout(end,300);box.addEventListener("transitionend",end);
  });
}
// A tab chosen by hand always shows the current state: the agent keeps working.
function projectTab(tab){
  project.tab=tab;
  if(projectDocked())rememberProject(tab);
  markProjectTab();
  if(tab==="files"){if(files.session!==active&&!filesDirty())startFiles();return}
  if(tab==="gallery")return loadGallery();
  if(hist.session!==active)return startHistory(tab);
  historyTab(tab);
}
// Shown for another session (a switch with the sidebar open): load only what is out of date.
function refreshProject(){
  markProjectTab();
  if(project.tab==="files"){if(files.session!==active&&!filesDirty())startFiles();return}
  if(project.tab==="gallery"){if(gallery.session!==active)loadGallery();return}
  if(hist.session!==active)startHistory(project.tab);
}
function markProjectTab(){
  for(const b of $("project_tabs").querySelectorAll("[data-tab]")){const on=b.dataset.tab===project.tab;b.classList.toggle("on",on);b.setAttribute("aria-selected",String(on))}
  $("git_body").hidden=["files","gallery"].includes(project.tab);$("files_body").hidden=project.tab!=="files";$("gallery_body").hidden=project.tab!=="gallery";
  const box=$("project_dlg");
  $("b_project").setAttribute("aria-pressed",String(box.open));
}
// Opens (or moves) the panel in the form this layout uses: docked beside the session or modal.
function placeProject(open){
  const box=$("project_dlg"),docked=projectDocked();
  if(box.open&&box.classList.contains("docked")!==docked){project.moving=true;box.close();project.moving=false;open=true}
  if(!open||box.open)return;
  applyCodeFont();box.classList.toggle("docked",docked);
  // Not modal: docked, the terminal and the message field stay usable beside it; as the phone drawer, the
  // top layer a modal dialog enters re-lays out the whole diff (most of a second) on every swipe.
  const drawer=!docked&&projectDrawer();
  document.body.classList.toggle("project-drawer",drawer);
  box.removeAttribute("aria-hidden");
  if(docked||drawer)box.open=true;
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
  const box=$("project_dlg");
  if(box.open&&projectSlides(box))await slideProject(box);
  box.close();box.style.transform="";
}
// Closed by hand (not moved between layouts): stop polling and free a previewed file's blob.
function projectClosed(){
  // Closed, the phone drawer stays in the page past the edge: hidden from screen readers and focus. Not
  // inert: that re-styles the whole diff, as slow as the re-layout this avoids.
  const box=$("project_dlg");
  if(document.body.classList.contains("project-drawer")){box.setAttribute("aria-hidden","true");if(box.contains(document.activeElement))document.activeElement.blur()}
  document.body.classList.remove("project-drawer");
  if(project.moving)return;
  clearTimeout(hist.timer);clearTimeout(gallery.timer);dropPreview();files.file=null;markProjectTab();
}
