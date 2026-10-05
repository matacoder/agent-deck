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

if(typeof module!=="undefined")module.exports={saveDirectorySetting,saveSessionName};
