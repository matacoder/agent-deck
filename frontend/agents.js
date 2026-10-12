// Every agent the panel can start, once: how it is called, drawn and stopped from asking, and which of its own
// commands sit behind "more". Agents marked `cli` are only a program in a terminal (integrations/agents.py
// describes the same ones for the server); the others have their own cards and model sources.
// Bundled before app.js; nothing here runs at load time.
const FORGETS="Агент забудет весь разговор этой сессии.";
const AGENT_LIST=[
  {id:"claude",label:"Claude",glyph:"✻",skip:"--dangerously-skip-permissions",compact:"/compact",fresh:"/clear"},
  {id:"codex",label:"Codex",glyph:"◎",skip:"--dangerously-bypass-approvals-and-sandbox",compact:"/compact",fresh:"/new"},
  {id:"claude-kimi",label:"Claude · Kimi",glyph:"✻",skip:"--dangerously-skip-permissions",compact:"/compact",fresh:"/clear",hidden:true},
  {id:"claude-provider",label:"Claude",glyph:"✻",skip:"--dangerously-skip-permissions",compact:"/compact",fresh:"/clear",hidden:true},
  {id:"kimi",label:"Kimi Code",glyph:"◈",skip:"--auto"},
  {id:"cursor",label:"Cursor",glyph:"❖",skip:"--force",compact:"/summarize",fresh:"/clear",cli:true,
    hint:"Нужна подписка Cursor: «Войти» открывает вход в браузере."},
  {id:"gemini",label:"Gemini CLI",glyph:"✦",skip:"--yolo",compact:"/compress",fresh:"/clear",cli:true,
    hint:"Вход — в самом Gemini CLI: аккаунт Google или ключ API."},
  {id:"copilot",label:"GitHub Copilot",glyph:"◉",skip:"--allow-all",compact:"/compact",fresh:"/new",cli:true,
    hint:"Использует вход GitHub CLI, если он есть; иначе — «Войти»."},
  {id:"opencode",label:"OpenCode",glyph:"▣",skip:"--auto",compact:"/compact",fresh:"/new",cli:true,
    hint:"Работает без аккаунта на бесплатной модели; «Войти» подключает ваших провайдеров. После перезапуска продолжает последний разговор в папке."},
  {id:"qwen",label:"Qwen Code",glyph:"⬢",skip:"--yolo",compact:"/compress",fresh:"/clear",cli:true,
    hint:"Ключ и модель выбираются в самом Qwen Code: команды /auth и /model."},
  {id:"pi",label:"Pi",glyph:"π",skip:""},
  {id:"shell",label:"Терминал",glyph:"$",translate:true}];
// The agent's own commands behind "more"; the one that drops the conversation asks first. Pure for tests.
function agentCommands(agent){
  const spec=AGENT_LIST.find(a=>a.id===agent);
  if(!spec||!spec.compact)return [];
  return [{label:spec.compact,text:spec.compact,compact:true},{label:spec.fresh,text:spec.fresh,confirm:FORGETS}];
}
// What the new session dialog offers: the built-in agents always, a terminal-only one once it is installed.
// Pure for tests.
function pickableAgents(status){
  return AGENT_LIST.filter(a=>!a.hidden&&(!a.cli||status?.[a.id]?.installed));
}
function renderAgentPicker(){
  const buttons=pickableAgents(lastAg).map(a=>{
    const button=el("button","",agentIcon({agent:a.id}),el("span","",AGENTS[a.id].label));
    button.type="button";button.dataset.a=a.id;button.onclick=()=>pickAgent(a.id);button.classList.toggle("on",a.id===newAgent);
    return button;
  });
  if(buttons.map(b=>b.dataset.a).join()!==[...$("agsel").children].map(b=>b.dataset.a).join())$("agsel").replaceChildren(...buttons);
}
// A terminal-only agent in Settings: install, sign in, update, and one line on where its key lives.
function cliAgentCard(spec){
  const card=agentCard(spec.id);
  if(spec.hint)card.append(el("p","hint",tr(spec.hint)));
  return card;
}

if(typeof module!=="undefined")module.exports={AGENT_LIST,agentCommands,pickableAgents};
