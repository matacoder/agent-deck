async function saveDirectorySetting({request,input,button,notify,translate}){
  button.disabled=true;
  try{
    const data=await request("/api/project_directory",{directory:input.value});
    input.value=data.directory;
    notify(translate("Папка проектов сохранена"),"success");
  }catch(e){notify(e.message)}finally{button.disabled=false}
}

async function saveSessionName({request,input,button,dialog,refresh,notify}){
  button.disabled=true;
  try{await request("/api/rename",{name:dialog.dataset.session,title:input.value.trim()});dialog.close();await refresh()}
  catch(e){notify(e.message)}finally{button.disabled=false}
}

async function refreshModelCatalog(request){
  const current=await request("/api/lmstudio");
  await Promise.allSettled((current.profiles||[]).map(profile=>request("/api/lm_probe",{id:profile.id})));
  return request("/api/lmstudio");
}

if(typeof module!=="undefined")module.exports={saveDirectorySetting,saveSessionName,refreshModelCatalog};
