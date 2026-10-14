/* ⌥1..9 — табы, ⌥↑/⌥↓ — пред./след., ⌥T — новая, ⌥K — быстрый переход (работает и внутри терминала) */
function hotkeys(e){
  if(!e.altKey&&!e.ctrlKey&&!e.metaKey&&(answerByDigit(e)||screenKey(e)))return;
  // Ctrl+K is kill-line in a shell (and in Mac text fields), so inside the terminal only Alt+K opens the
  // switcher, and a Mac uses Cmd+K.
  const commandKey=/Mac|iPhone|iPad/.test(navigator.platform||"")?e.metaKey&&!e.ctrlKey:e.ctrlKey&&!e.metaKey;
  if(commandKey&&!e.altKey&&!e.shiftKey&&e.code==="KeyK"&&e.target?.ownerDocument===document){e.preventDefault();e.stopPropagation();openPalette();return}
  if(!e.altKey||e.ctrlKey||e.metaKey)return;
  // An open dialog belongs to the session under it: a shortcut must not put another one there.
  if(document.querySelector("dialog[open]:not(.docked)"))return;
  const vis=[...$("tabs").querySelectorAll(".tab:not(.remote)")].map(t=>t.dataset.session);
  let target=null;
  if(/^Digit[1-9]$/.test(e.code)&&!e.shiftKey){
    // Non-US Mac layouts type [ ] { } | etc. with Option+digit; keep those characters.
    if(/^[!-\/:-@\[-`{-~]$/.test(e.key))return;
    target=vis[+e.code.slice(5)-1];
  }
  else if(e.code==="ArrowUp"||e.code==="ArrowDown"){const i=vis.indexOf(active);target=vis[(i+(e.code==="ArrowUp"?-1:1)+vis.length)%vis.length]}
  else if(e.code==="KeyT"){e.preventDefault();e.stopPropagation();openNew();return}
  else if(e.code==="KeyK"){
    if(/^[^\x00-\x7f]$/.test(e.key))return;  // Option+K types "˚" on a Mac; that keeps working, Cmd+K opens the switcher there.
    e.preventDefault();e.stopPropagation();openPalette();return;
  }
  else return;
  e.preventDefault();e.stopPropagation();if(target)select(target);
}
// The text screen has no terminal to type into, so the keys an agent's menu needs (digits, arrows, Enter,
// Esc, Tab) go to the session, like the on-screen keys, while nothing else has the focus.
const SCREEN_KEYS={Enter:"Enter",Escape:"Escape",Tab:"Tab",ArrowUp:"Up",ArrowDown:"Down",ArrowLeft:"Left",ArrowRight:"Right"};
function screenKey(e){
  if(e.isComposing||!cur()||curMode()!=="screen")return false;
  const focus=document.activeElement;
  if(focus&&focus!==document.body&&!$("pre_wrap").contains(focus))return false;
  if(document.querySelector("dialog[open]:not(.docked)")||$("sheet").classList.contains("on")||!$("search_pop").hidden||!$("viewer").hidden)return false;
  const digit=/^(Digit|Numpad)[1-9]$/.test(e.code)&&!e.shiftKey?e.code.slice(-1):"";
  const name=digit||(e.key==="Tab"&&e.shiftKey?"BTab":e.shiftKey?"":SCREEN_KEYS[e.key]);
  if(!name)return false;
  e.preventDefault();e.stopPropagation();key(name);return true;
}
// The numbers on a question card's options answer it, as they would in the terminal, unless you are typing.
function answerByDigit(e){
  const data=question.name===active?question.data:null,target=e.target;
  if(!data||!/^Digit[1-9]$/.test(e.code)||question.busy!==null||document.querySelector("dialog[open]:not(.docked)"))return false;
  if(target&&(target.closest?.("input,textarea,select,[contenteditable]")||target.tagName==="IFRAME"))return false;
  const index=+e.code.slice(5)-1,option=data.options[index];
  if(!option||option.text)return false;
  e.preventDefault();e.stopPropagation();answerQuestion(index);return true;
}
