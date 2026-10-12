// What the page showed last time, kept in the browser per computer. The next start draws it at once and the
// fresh answer replaces it in place, so nothing appears late and pushes the rest. Screens of sessions are
// never kept; sign-out forgets everything. Bundled before app.js.
const SHOWN="cc.shown.",SHOWN_SESSIONS=200;
function shown(storage,name){
  try{const value=JSON.parse(storage.getItem(SHOWN+name)||"null");return value&&typeof value==="object"?value:null}catch(e){return null}
}
// Written only when it differs: lists are polled every few seconds and mostly stay the same.
const shownWritten=new Map();
function keepShown(storage,scope,name,value){
  const text=JSON.stringify(value),key=scope+"/"+name;
  if(shownWritten.get(key)===text)return;
  shownWritten.set(key,text);
  try{storage.setItem(SHOWN+name,text)}catch(e){}
}
// A list as it is kept: no screen text, and no clock values that would rewrite it on every poll. Pure for tests.
function sessionsToKeep(list){
  return (Array.isArray(list)?list:[]).slice(0,SHOWN_SESSIONS).map(({preview,preview_ansi,activity,attached,...rest})=>rest);
}
function keptSessions(storage){
  const list=shown(storage,"sessions");
  return Array.isArray(list)?list.filter(s=>s&&typeof s.name==="string"):null;
}
// The computers of a gateway as the list shows them: nothing that signs in. Pure for tests.
function decksToKeep(data,network){
  return {name:network?.name||"",network:{name:network?.name||"",bind_host:network?.bind_host||"",bind_port:network?.bind_port||"",public_url:network?.public_url||"",instance:network?.instance||""},
    decks:(data?.decks||[]).map(({id,name,url,instance})=>({id,name,url,instance}))};
}
function forgetShown(storage){
  try{for(const key of Object.keys(storage))if(key.includes(SHOWN))storage.removeItem(key)}catch(e){}
  shownWritten.clear();
}
// The last answer per computer and session, in memory: a switch back shows it while the fresh one is on its way.
const KNOWN_ANSWERS=60,sessionInfoKnown=new Map(),laterKnown=new Map(),changesKnown=new Map();
function knownAnswer(known,key){return key&&known.has(key)?known.get(key):null}
function keepAnswer(known,key,value){
  if(!key)return;
  known.delete(key);  // Re-inserted last, so the oldest entry is the one that goes.
  if(value)known.set(key,value);
  if(known.size>KNOWN_ANSWERS)known.delete(known.keys().next().value);
}
// Rows that stand in for a list still on its way.
function skeletonRows(count,build){return Array.from({length:count},(_,index)=>build(index))}

function sessionSkeleton(){
  return el("div","tab tab-skeleton",el("span","sk-line sk-dot"),el("span","sk-line sk-icon"),el("div","t",el("span","sk-line"),el("span","sk-line")));
}
function integRow(){return el("div","local-usage compact-local integ-skeleton",el("span","sk-line"),el("span","sk-line"))}
function pendingMetrics(){for(const id of ["metric_cpu","metric_ram"])$(id).replaceChildren(el("span","sk-line sk-metric"))}
// Screens live in memory, and for a reload in this tab's own storage: gone with the tab, never on disk for long.
const SCREENS=12,SCREEN_CHARS=60000;
// The end of a screen as it is kept: the page draws only its last lines anyway. Pure for tests.
function screenToKeep(screen){
  const text=screen?.preview_ansi??screen?.preview??"";
  if(typeof text!=="string")return null;
  const cut=text.length>SCREEN_CHARS?text.indexOf("\n",text.length-SCREEN_CHARS)+1:0;
  return {preview_ansi:text.slice(cut),model:screen.model};
}
function keepScreens(){
  const kept=[...previewCache].slice(-SCREENS).map(([name,screen])=>[name,screenToKeep(screen)]).filter(entry=>entry[1]);
  try{deckSessionStorage.setItem(SHOWN+"screens",JSON.stringify(kept))}catch(e){try{deckSessionStorage.removeItem(SHOWN+"screens")}catch(e){}}
  // Summaries and context sizes go the same way: their keys already name the computer.
  try{sessionStore.setItem(SHOWN+"info",JSON.stringify([...sessionInfoKnown].slice(-SCREENS)))}catch(e){}
}
function restoreScreens(){
  const kept=shown(deckSessionStorage,"screens");
  for(const entry of Array.isArray(kept)?kept:[]){
    if(Array.isArray(entry)&&typeof entry[0]==="string"&&entry[1]&&typeof entry[1]==="object"&&!previewCache.has(entry[0]))previewCache.set(entry[0],entry[1]);
  }
  const info=shown(sessionStore,"info");
  for(const entry of Array.isArray(info)?info:[]){
    if(Array.isArray(entry)&&typeof entry[0]==="string"&&entry[1]&&typeof entry[1]==="object"&&!sessionInfoKnown.has(entry[0]))sessionInfoKnown.set(entry[0],entry[1]);
  }
}
// The screens of sessions not opened yet are asked for quietly, one at a time, most recent first: a switch
// then shows text at once and the fresh screen replaces it.
const WARM_SCREENS=8;let warmingScreens=false;
async function warmScreens(){
  if(warmingScreens||document.hidden)return;
  warmingScreens=true;const epoch=deckEpoch;
  try{
    const rest=sessions.filter(s=>s.name!==active&&!previewCache.has(s.name)).sort((a,b)=>Number(b.activity)-Number(a.activity)).slice(0,WARM_SCREENS);
    for(const s of rest){
      if(epoch!==deckEpoch||document.hidden)return;
      const got=(await api("/api/sessions?preview="+encodeURIComponent(s.name))).sessions?.find(x=>x.name===s.name);
      if(epoch===deckEpoch&&got&&(got.preview!==undefined||got.preview_ansi!==undefined))previewCache.set(s.name,{preview:got.preview,preview_ansi:got.preview_ansi,model:got.model});
    }
  }catch(e){/* The next list tries again. */}
  finally{warmingScreens=false}
}
// A switch made while a list request is on its way would wait for it and then for its own: the new session's
// screen is asked for at once instead.
async function screenNow(name){
  if(!loadingSessions||previewCache.has(name))return;
  const epoch=deckEpoch;
  try{
    const got=(await api("/api/sessions?preview="+encodeURIComponent(name))).sessions?.find(x=>x.name===name);
    if(epoch!==deckEpoch||!got||(got.preview===undefined&&got.preview_ansi===undefined))return;
    previewCache.set(name,{preview:got.preview,preview_ansi:got.preview_ansi,model:got.model});
    const s=cur();
    if(active===name&&s&&s.preview===undefined&&s.preview_ansi===undefined){Object.assign(s,previewCache.get(name));if(curMode()==="screen")updateScreen(s,true)}
  }catch(e){/* The list request brings it. */}
}
// At start and on a computer switch, before the first answer of that computer.
function showRemembered(){
  if(!sessions.length){const kept=keptSessions(deckLocalStorage);if(kept)sessions=kept}
  restoreScreens();
  for(const s of sessions)Object.assign(s,previewCache.get(s.name)||{});
  usageData=shown(deckLocalStorage,"usage")||{};
  const models=shown(deckLocalStorage,"models");
  if(Array.isArray(models)&&!integReady.lm)lmData={profiles:models,discovery:{}};
  ghLogin=shown(deckLocalStorage,"github")?.login||null;
  const version=shown(deckLocalStorage,"version")?.version;
  $("ver").replaceChildren(typeof version==="string"?"v"+version:el("span","sk-line ver-skeleton"));
}
// The switcher and the other computers' lists, so the session list does not move down when they arrive.
function showRememberedDecks(){
  const kept=shown(localStore,"decks");
  if(!kept||!Array.isArray(kept.decks))return;
  deckDirectory={decks:kept.decks,name:kept.name||"",network:kept.network||{}};
  populateDeckSelector($("deck_select"),kept.decks,selectedDeck,kept.name||tr("Этот компьютер"));
  $("deck_switch").hidden=!kept.decks.length&&!selectedDeck;
  otherDecks=[{id:"",name:kept.name||tr("Этот компьютер")},...kept.decks].filter(d=>d.id!==selectedDeck)
    .map(d=>({id:d.id,name:d.name,sessions:keptSessions(instanceStorage(localStore,d.id))})).filter(d=>d.sessions);
  loadOtherDecks();
}

if(typeof module!=="undefined")module.exports={shown,keepShown,sessionsToKeep,keptSessions,decksToKeep,forgetShown,screenToKeep,knownAnswer,keepAnswer};
