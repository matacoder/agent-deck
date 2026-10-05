function svgIcon(name){
  const ns="http://www.w3.org/2000/svg",svg=document.createElementNS(ns,"svg"),use=document.createElementNS(ns,"use");
  svg.setAttribute("class","ui-icon");svg.setAttribute("aria-hidden","true");use.setAttribute("href","#i-"+name);svg.append(use);
  return svg;
}

// Free-text options (Other / Type something) need typing in the terminal, so they stay keyboard-only.
function renderQuestionCard({box,question,expanded,busyIndex,onAnswer,onToggle,translate}){
  box.replaceChildren();
  box.hidden=!question;
  if(!question)return;
  const head=document.createElement("div");head.className="q-head";
  head.append(translate("Вопрос агента"));
  if(question.progress){const progress=document.createElement("span");progress.className="q-progress";progress.textContent=question.progress;head.append(progress)}
  const title=document.createElement("button");title.type="button";title.className="q-title"+(expanded?" open":"");
  title.textContent=question.title;title.setAttribute("aria-expanded",String(Boolean(expanded)));title.onclick=onToggle;
  const options=document.createElement("div");options.className="q-options";
  let freeText=false;
  question.options.forEach((option,index)=>{
    if(option.text){freeText=true;return}
    const button=document.createElement("button");button.type="button";
    button.className="q-opt"+(index===question.selected?" selected":"")+(index===busyIndex?" sending":"");
    const number=document.createElement("span");number.className="q-num";number.textContent=String(index+1);
    const label=document.createElement("span");label.textContent=option.label;
    button.append(number,label);button.disabled=busyIndex!==null&&busyIndex!==undefined;
    button.onclick=()=>onAnswer(index);
    options.append(button);
  });
  box.append(head,title,options);
  if(freeText){const note=document.createElement("p");note.className="q-note";note.textContent=translate("Свой ответ — клавишами ↑ ↓ ⏎ ниже");box.append(note)}
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

if(typeof module!=="undefined")module.exports={svgIcon,renderQuestionCard,askConfirm};
