function svgIcon(name){
  const ns="http://www.w3.org/2000/svg",svg=document.createElementNS(ns,"svg"),use=document.createElementNS(ns,"use");
  svg.setAttribute("class","ui-icon");svg.setAttribute("aria-hidden","true");use.setAttribute("href","#i-"+name);svg.append(use);
  return svg;
}

// Free-text options (Other / Type something) open a text field; the answer is typed into that row.
function renderQuestionCard({box,question,expanded,busyIndex,textIndex,textDraft="",onAnswer,onToggle,onTextOption,onTextInput,onSubmitText,translate}){
  box.replaceChildren();
  box.hidden=!question;
  if(!question)return;
  const busy=busyIndex!==null&&busyIndex!==undefined;
  const head=document.createElement("div");head.className="q-head";
  head.append(translate("Вопрос агента"));
  if(question.progress){const progress=document.createElement("span");progress.className="q-progress";progress.textContent=question.progress;head.append(progress)}
  const title=document.createElement("button");title.type="button";title.className="q-title"+(expanded?" open":"");
  title.textContent=question.title;title.setAttribute("aria-expanded",String(Boolean(expanded)));title.onclick=onToggle;
  const options=document.createElement("div");options.className="q-options";
  question.options.forEach((option,index)=>{
    const button=document.createElement("button");button.type="button";
    button.className="q-opt"+(option.text?" q-free":"")+(index===question.selected?" selected":"")+(index===busyIndex?" sending":"")+(index===textIndex?" active":"");
    const number=document.createElement("span");number.className="q-num";
    if(option.text)number.append(svgIcon("pencil"));else number.textContent=String(index+1);
    const label=document.createElement("span");label.textContent=option.label;
    button.append(number,label);button.disabled=busy;
    button.onclick=()=>option.text?onTextOption&&onTextOption(index):onAnswer(index);
    options.append(button);
    if(option.text&&index===textIndex){
      const form=document.createElement("form");form.className="q-text";
      const field=document.createElement("textarea");field.rows=2;field.maxLength=4000;field.placeholder=translate("Ваш ответ…");field.disabled=busy;field.value=textDraft;
      field.oninput=()=>onTextInput&&onTextInput(field.value);
      const send=document.createElement("button");send.type="submit";send.className="pri";send.textContent=translate("Ответить");send.disabled=busy;
      form.onsubmit=event=>{event.preventDefault();if(field.value.trim())onSubmitText(index,field.value)};
      form.append(field,send);options.append(form);
    }
  });
  box.append(head,title,options);
}

// Typed answers survive reloads, language switches, logout and computer switches, like message drafts.
const ANSWER_DRAFTS="cc.answer-drafts";
function readAnswerDrafts(){try{const all=JSON.parse(sessionStorage.getItem(ANSWER_DRAFTS)||"{}");return all&&typeof all==="object"?all:{}}catch(e){return {}}}
function answerDraft(key){const draft=readAnswerDrafts()[key];return draft&&typeof draft.text==="string"&&Number.isInteger(draft.index)?draft:null}
function saveAnswerDraft(key,draft){
  const all=readAnswerDrafts();
  if(draft&&draft.text)all[key]={index:draft.index,text:draft.text};else delete all[key];
  try{sessionStorage.setItem(ANSWER_DRAFTS,JSON.stringify(all))}catch(e){}
}

// One styled confirm for every destructive action; resolves false on Escape or backdrop close.
function askConfirm(dialog,{title,text="",confirm,danger=false}){
  return new Promise(resolve=>{
    dialog.querySelector("#confirm_title").textContent=title;
    dialog.querySelector("#confirm_text").textContent=text;
    dialog.querySelector("#confirm_text").hidden=!text;
    const ok=dialog.querySelector("#confirm_ok");ok.textContent=confirm;ok.className=danger?"danger-pri":"pri";
    dialog.returnValue="";
    dialog.addEventListener("close",()=>resolve(dialog.returnValue==="ok"),{once:true});
    dialog.showModal();ok.focus();
  });
}

if(typeof module!=="undefined")module.exports={svgIcon,renderQuestionCard,askConfirm,answerDraft,saveAnswerDraft};

// The open session's question: fetched with the screen, drawn as a card, answered by its buttons.
let question={name:null,data:null,expanded:false,busy:null,textIndex:null},loadingQuestion=false,questionCard="";
async function loadQuestion(){
  const s=cur();
  if(!s||agentOf(s)==="shell"||!s.running){if(question.data)setQuestion(s?.name||null,null);return}
  if(loadingQuestion||question.busy!==null||document.hidden)return;
  loadingQuestion=true;const name=s.name;
  try{const data=await api("/api/question?name="+encodeURIComponent(name));if(active===name)setQuestion(name,data.question)}
  catch(e){/* Questions are an optional shortcut; the key row still works. */}
  finally{loadingQuestion=false}
}
function setQuestion(name,data){
  const same=question.name===name&&JSON.stringify(question.data)===JSON.stringify(data);
  if(same)return;
  const keepExpanded=question.name===name&&question.data?.id===data?.id;
  const saved=data?answerDraft(answerKey(name,data.id)):null;
  question={name,data,expanded:keepExpanded&&question.expanded,busy:null,
    textIndex:saved?saved.index:keepExpanded?question.textIndex:null,textDraft:saved?saved.text:keepExpanded?question.textDraft:""};
  renderQuestion();
}
const answerKey=(name,id)=>selectedDeck+"/"+name+"/"+id;
function saveQuestionDraft(){
  if(question.data)saveAnswerDraft(answerKey(question.name,question.data.id),{index:question.textIndex,text:question.textDraft});
}
function renderQuestion(){
  const data=question.name===active?question.data:null;
  // The card's own buttons answer; the 1/2/3 keys would only repeat them on a short screen.
  document.body.classList.toggle("has-question",Boolean(data));
  // Typing an answer must not be wiped by the 2.5 s refresh, so an open text field pauses re-rendering.
  // Only while the card is still this question: its buttons answer the one known now, not the one drawn.
  const card=data?question.name+"\n"+data.id:"";
  if($("question").querySelector(".q-text textarea:focus")&&questionCard===card)return;
  questionCard=card;
  renderQuestionCard({box:$("question"),question:data,expanded:question.expanded,busyIndex:question.busy,textIndex:question.textIndex,textDraft:question.textDraft||"",translate:tr,
    onTextInput:value=>{question.textDraft=value;saveQuestionDraft()},
    onToggle:()=>{question.expanded=!question.expanded;renderQuestion()},onAnswer:answerQuestion,
    // Focus inside the tap itself: iOS opens the keyboard only for a user gesture, and a
    // refocus on every refresh would pop the keyboard back after the user dismissed it.
    onTextOption:index=>{question.textIndex=question.textIndex===index?null:index;renderQuestion();$("question").querySelector(".q-text textarea")?.focus()},
    onSubmitText:(index,text)=>answerQuestion(index,text)});
}
async function answerQuestion(index,text){
  const name=active,data=question.data;
  if(!data||question.busy!==null||panelUpdating)return;
  question.busy=index;$("question").querySelector(".q-text textarea")?.blur();renderQuestion();
  try{
    await api("/api/answer",text===undefined?{name,id:data.id,index}:{name,id:data.id,index,text});
    saveAnswerDraft(answerKey(name,data.id),null);
    sendStates.set(name,{text:tr("Ответ отправлен: {0}",[text===undefined?data.options[index].label:text.slice(0,80)]),phase:"success"});
    question={name,data:null,expanded:false,busy:null,textIndex:null};
  }catch(e){toast(e.message);question.busy=null}
  renderQuestion();renderSendState();await load();loadQuestion();
}
