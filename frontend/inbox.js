// Everything waiting for you on every computer: agent questions (answerable here) and finished work.
const inbox={questions:[],cards:new Map(),loading:false};

// Questions plus finished sessions, without listing a session twice; pure for tests.
function inboxItems(questions,finished){
  const asked=new Set(questions.map(q=>(q.deck||"")+"/"+q.session));
  return [...questions.map(q=>({kind:"question",key:(q.deck||"")+"/"+q.session,question:q})),
    ...finished.filter(f=>!asked.has(f.deck+"/"+f.session)).map(f=>({kind:"finished",key:f.deck+"/"+f.session,...f}))];
}
function finishedSessions(){
  const local=[...attention].map(name=>({deck:selectedDeck,session:name,machine:currentDeckName()}));
  const remote=[...otherAttention].map(key=>{const [deck,session]=key.split("/");return {deck,session,machine:(otherDecks.find(d=>d.id===deck)||{}).name||""}});
  return [...local,...remote];
}
async function loadInbox(){
  if(document.hidden||inbox.loading)return;
  inbox.loading=true;
  try{inbox.questions=(await api("/api/inbox",null,true)).questions||[]}catch(e){/* Older gateways have no inbox; the list stays empty. */}
  finally{inbox.loading=false}
  renderInbox();
}
function inboxCount(){return inboxItems(inbox.questions,finishedSessions()).length}
function renderInboxBadge(){
  const count=inboxCount();
  $("inbox_btn").hidden=!count;$("inbox_count").textContent=count;
  return count;
}
function openInboxSession(deck,session){
  $("inbox_dlg").close();
  if((deck||"")!==selectedDeck)openDeckSession(deck||"",session);else select(session);
}
function renderInbox(){
  renderInboxBadge();renderQuickTabs();
  if(!$("inbox_dlg").open)return;
  const list=$("inbox_list"),items=inboxItems(inbox.questions,finishedSessions());
  if(list.querySelector(".q-text textarea:focus"))return;  // Do not wipe a half-typed answer.
  const live=new Set(items.filter(i=>i.kind==="question").map(i=>i.key+"/"+i.question.id));
  for(const key of inbox.cards.keys())if(!live.has(key))inbox.cards.delete(key);
  list.replaceChildren(...(items.length?items.map(renderInboxItem):[el("p","inbox-empty",tr("Сейчас никто не ждёт ответа"))]));
}
// The name the user gave the session, not its technical tmux name.
function inboxLabel(item,deck,session){
  if(item.kind==="question"&&item.question.label)return item.question.label;
  const list=deck===selectedDeck?sessions:(otherDecks.find(d=>d.id===deck)||{}).sessions||[];
  const found=list.find(s=>s.name===session);
  return found?sessionTitle(found):session;
}
function renderInboxItem(item){
  const machine=item.kind==="question"?(item.question.origin||(item.question.deck?"":deckDirectory.name)):item.machine;
  const deck=item.kind==="question"?item.question.deck||"":item.deck,session=item.kind==="question"?item.question.session:item.session;
  const head=el("button","inbox-head",agentIcon({agent:item.kind==="question"?item.question.agent:"claude"}),el("span","inbox-session",inboxLabel(item,deck,session)),
    el("span","inbox-machine",machine||""));
  head.type="button";head.onclick=()=>openInboxSession(deck,session);
  const box=el("div","inbox-item",head);
  if(item.kind==="finished"){box.append(el("p","inbox-status",tr("Агент закончил работу")));return box}
  // Per question, not per session: a new question in the same session starts with a clean card.
  const draftKey=item.key+"/"+item.question.id,saved=answerDraft(draftKey);
  const card=el("div","inbox-question"),state=inbox.cards.get(draftKey)||{expanded:false,busy:null,textIndex:saved?.index??null,draft:saved?.text||""};
  inbox.cards.set(draftKey,state);
  const answer=async(index,text)=>{
    state.busy=index;draw();
    const q=item.question,body={name:q.session,id:q.id,index};if(text!==undefined)body.text=text;
    try{await api(instancePath(deck,"/api/answer"),body,true);toast(tr("Ответ отправлен: {0}",[text===undefined?q.options[index].label:text.slice(0,80)]),"success");
      saveAnswerDraft(draftKey,null);inbox.questions=inbox.questions.filter(x=>x!==q);inbox.cards.delete(draftKey);renderInbox();if(deck===selectedDeck)load()}
    catch(e){state.busy=null;draw();toast(e.message)}
  };
  const draw=()=>renderQuestionCard({box:card,question:item.question,expanded:state.expanded,busyIndex:state.busy,textIndex:state.textIndex,textDraft:state.draft,translate:tr,
    onToggle:()=>{state.expanded=!state.expanded;draw()},onAnswer:index=>answer(index),
    onTextOption:index=>{state.textIndex=state.textIndex===index?null:index;draw();card.querySelector(".q-text textarea")?.focus()},onTextInput:value=>{state.draft=value;saveAnswerDraft(draftKey,{index:state.textIndex,text:value})},onSubmitText:answer});
  draw();box.append(card);return box;
}
function openInbox(){
  drawer(false);sheet(false);
  if(!$("inbox_dlg").open)$("inbox_dlg").showModal();
  renderInbox();loadInbox();
}

if(typeof module!=="undefined")module.exports={inboxItems};
