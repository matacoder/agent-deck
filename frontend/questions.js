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
