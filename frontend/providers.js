// Claude Code on the models of another service that speaks Anthropic's API: GLM, or any address the owner
// adds. The key is typed here once and never comes back from the server. Bundled before app.js.
const PROVIDER_PRESETS={glm:{name:"GLM",url:"https://api.z.ai/api/anthropic",model:"glm-5.3"}};
let providerEditing=null;
function savedProviders(){return lastAg.providers||[]}
// What the new session dialog offers for Claude Code. Pure for tests.
function providerSources(providers){
  return providers.filter(p=>p.configured).map(p=>[{kind:"provider",provider:p.id,model:p.model},p.name+" · "+p.model]);
}
function providerRow(provider){
  const edit=labelledButton(tr("Изменить"),"",()=>openProvider(provider),provider.name);edit.type="button";
  return el("div","provider-row",el("span","provider-name",provider.name),el("span","card-meta",provider.model),edit);
}
function providersCard(){
  const list=savedProviders(),hasGlm=list.some(p=>p.url===PROVIDER_PRESETS.glm.url);
  const other=btn(tr("Добавить другой сервис"),"quick-add",()=>openProvider(null,{name:"",url:"",model:""}));other.type="button";
  return hubCard({key:"providers",icon:agentIcon({agent:"claude"}),title:tr("Claude на других моделях"),
    status:list.length?tr("Сервисов: {0}",[list.length]):tr("Не настроено"),tone:list.length?"ok":"idle",
    primary:hasGlm?null:{label:tr("Добавить GLM"),run:()=>openProvider(null,PROVIDER_PRESETS.glm),quiet:true},
    body:[el("p","hint",tr("Claude Code работает на моделях другого сервиса с Anthropic-совместимым адресом. Сервис выбирается в новой сессии Claude, в поле «Источник модели».")),...list.map(providerRow),other]});
}
function openProvider(provider,preset){
  const from=provider||preset;providerEditing=provider?provider.id:null;
  $("provider_name").value=from.name;$("provider_url").value=from.url;$("provider_model").value=from.model;$("provider_key").value="";
  $("provider_key_hint").hidden=!provider;$("provider_remove").hidden=!provider;
  $("provider_dlg").hidden=false;snapshotEditor($("provider_dlg"));openSettings("agents");$("provider_dlg").scrollIntoView({block:"nearest"});
  if(!isMobile()&&lastPointer!=="touch")$(provider||from.name?"provider_key":"provider_name").focus({preventScroll:true});
}
function closeProvider(){
  const wasOpen=!$("provider_dlg").hidden;
  $("provider_key").value="";$("provider_dlg").hidden=true;
  if($("settings_dlg").open){renderHub();if(wasOpen)focusCard("providers")}
}
async function saveProvider(){
  $("provider_save").disabled=true;
  try{
    const result=await api("/api/provider_save",{id:providerEditing??undefined,name:$("provider_name").value,url:$("provider_url").value.trim(),
      model:$("provider_model").value.trim(),key:$("provider_key").value.trim()});
    lastAg.providers=result.providers;closeProvider();renderSources();toast(tr("Сервис сохранён"),"success");
  }catch(e){toast(e.message)}finally{$("provider_save").disabled=false}
}
async function removeProvider(){
  if(!await confirmAction(tr("Удалить этот сервис из панели?"),{text:tr("Сессии на его моделях перестанут запускаться."),confirm:tr("Удалить"),danger:true}))return;
  try{const result=await api("/api/provider_remove",{id:providerEditing});lastAg.providers=result.providers;closeProvider();renderSources()}catch(e){toast(e.message)}
}

if(typeof module!=="undefined")module.exports={providerSources,PROVIDER_PRESETS};
