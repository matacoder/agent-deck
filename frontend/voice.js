// Dictation: the microphone button records, a computer with whisper.cpp turns each piece into text, and the
// text joins the draft of the session it was spoken to. Pieces wait in IndexedDB until their text is there.
const voice={doneAt:0,rec:null,working:false,engine:undefined,engineAt:0,computers:[],retry:null,failures:0,error:"",pending:0,prompts:new Map(),held:false};
const VOICE_ENGINE_MS=300000,VOICE_ASK_MS=8000,VOICE_RETRY=[5,15,30,60],VOICE_DONE_MS=4000;

// The first ready computer answers the question; a sleeping one is not waited for.
function voiceEngine(force=false){
  // Only a found computer is remembered: "none" is asked again, since it changes with an install.
  if(!force&&voice.engine!=null&&Date.now()-voice.engineAt<VOICE_ENGINE_MS)return Promise.resolve(voice.engine);
  const ids=["",...deckDirectory.decks.map(d=>d.id)];
  voice.computers=ids.map(id=>({id,checking:true}));
  return new Promise(resolve=>{
    let left=ids.length,found=false;
    const settle=(index,state)=>{
      voice.computers[index]=state;left--;renderVoiceDialog();
      if(state.ready&&!found){found=true;voice.engine=state.id;voice.engineAt=Date.now();resolve(state.id)}
      if(!left&&!found){voice.engine=null;voice.engineAt=Date.now();resolve(null)}
    };
    // A sleeping computer would hold the answer for as long as the gateway waits for it.
    const late=new Promise((_,reject)=>setTimeout(()=>reject(new Error(tr("Не отвечает"))),VOICE_ASK_MS));
    ids.forEach((id,index)=>Promise.race([gatewayApi(instancePath(id,"/api/voice_status"),{}),late])
      .then(j=>settle(index,{id,...j.voice}),e=>settle(index,{id,unreachable:e.message})));
  });
}
async function toggleVoice(){
  if(voice.held){voice.held=false;return}  // A long press opened the dialog instead.
  if(voice.rec)return stopVoice();
  if(!active)return;
  if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){toast(tr("Микрофон работает только по https: откройте панель по её https-адресу"));return}
  // Created inside the tap: Safari keeps an audio context made later silent.
  const context=new (window.AudioContext||window.webkitAudioContext)();
  const engine=await voiceEngine();
  if(engine===null){context.close();openVoice();return}
  let stream;
  try{stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}})}
  catch(e){context.close();toast(tr("Нет доступа к микрофону: разрешите его для этого сайта в настройках браузера"));return}
  // Not awaited: WebKit settles it only once audio runs, which the recording itself starts.
  context.resume().catch(()=>{});
  startRecording(context,stream);
}
function startRecording(context,stream){
  const source=context.createMediaStreamSource(stream),node=context.createScriptProcessor(4096,1,1);
  const rec={id:String(Date.now()),seq:0,deck:selectedDeck,session:active,context,stream,source,node,
    chunks:[],length:0,rate:context.sampleRate,started:Date.now(),ticks:0,saving:Promise.resolve(),lock:null};
  node.onaudioprocess=e=>{const data=e.inputBuffer.getChannelData(0);rec.chunks.push(new Float32Array(data));rec.length+=data.length};
  source.connect(node);node.connect(context.destination);
  rec.tick=setInterval(()=>voiceTick(rec),1000);
  for(const track of stream.getAudioTracks())track.onended=()=>{if(voice.rec===rec)stopVoice(tr("Запись прервалась; всё, что успело записаться, сохранено"))};
  // A phone that locks its screen stops the microphone.
  navigator.wakeLock?.request("screen").then(lock=>{if(voice.rec===rec)rec.lock=lock;else lock.release()},()=>{});
  voice.rec=rec;renderVoice();
}
function voiceSamples(rec){
  const all=new Float32Array(rec.length);let at=0;
  for(const chunk of rec.chunks){all.set(chunk,at);at+=chunk.length}
  return all;
}
function voiceTick(rec){
  rec.ticks++;renderVoice();
  if(rec.length>=VOICE_PIECE_MAX*rec.rate)return cutPiece(rec,false);
  // The piece being spoken is saved every few seconds, so a killed tab loses only those seconds.
  if(rec.ticks%3===0){const samples=downsample(voiceSamples(rec),rec.rate);queueSave(rec,rec.seq,samples,true)}
}
function cutPiece(rec,last){
  const all=voiceSamples(rec),samples=downsample(all,rec.rate),cut=last?samples.length:cutPoint(samples);
  const keep=Math.round(cut*rec.rate/VOICE_RATE);
  rec.chunks=[all.slice(keep)];rec.length=rec.chunks[0].length;
  queueSave(rec,rec.seq,samples.slice(0,cut),false);rec.seq++;
  return rec.saving.then(runVoice);
}
// Saves of one recording run in order: a late save of the open piece must never replace the finished one.
function queueSave(rec,seq,samples,open){
  rec.saving=rec.saving.then(async()=>{
    const key=voicePieceKey(rec.id,seq);
    if(!hasSpeech(samples)){if(!open)await voiceRemove(key);return}
    await voicePut({key,rec:rec.id,seq,deck:rec.deck,session:rec.session,open,wav:encodeWav(samples).buffer});
  }).catch(()=>{voice.error=tr("Не удалось сохранить запись в браузере");renderVoice()});
}
function stopVoice(message){
  const rec=voice.rec;if(!rec)return;
  voice.rec=null;clearInterval(rec.tick);
  rec.node.onaudioprocess=null;rec.source.disconnect();rec.node.disconnect();
  for(const track of rec.stream.getTracks())track.stop();
  rec.context.close().catch(()=>{});rec.lock?.release().catch(()=>{});
  if(rec.length)cutPiece(rec,true);else rec.saving.then(runVoice);
  if(message)toast(message,true);
  renderVoice();
}
async function transcribePiece(piece,engine){
  const answer=await gatewayApi(instancePath(engine,"/api/transcribe"),
    {audio:bytesToBase64(new Uint8Array(piece.wav)),language:"auto",prompt:voice.prompts.get(piece.rec)||""});
  const text=(answer.text||"").trim();
  if(text)voice.prompts.set(piece.rec,text);
  await voicePut({...piece,text});
  return {...piece,text};
}
// The text goes to the end of the draft; the cursor and a selection in the field stay where they are.
function deliverDictation(piece){
  if(!piece.text)return;
  if(piece.session!==active){messageDrafts.set(piece.session,joinDictation(messageDrafts.get(piece.session)||"",piece.text));return}
  const box=$("msg"),end=box.value.length;
  box.setRangeText(joinDictation(box.value,piece.text).slice(end),end,end,"preserve");
  box.dispatchEvent(new Event("input"));
}
async function voiceStep(){
  const live=voice.rec?.id;
  const pieces=(await voicePieces()).filter(p=>!(p.open&&p.rec===live)).sort((a,b)=>a.key<b.key?-1:1);
  voice.pending=pieces.length;renderVoice();
  // A piece is put in the draft only after every earlier piece of its recording, and only on its own computer.
  const first=new Map();for(const p of pieces)if(!first.has(p.rec))first.set(p.rec,p);
  const ready=[...first.values()].find(p=>typeof p.text==="string"&&p.deck===selectedDeck);
  if(ready){
    deliverDictation(ready);
    if(ready.text&&ready.session===active){voice.doneAt=Date.now();setTimeout(renderVoice,VOICE_DONE_MS+50)}
    if(ready.text)await voiceKeep({rec:ready.rec,deck:ready.deck,session:ready.session},ready.text);
    await voiceRemove(ready.key);return true;
  }
  const next=pieces.find(p=>typeof p.text!=="string");
  if(!next)return false;
  const engine=await voiceEngine();
  if(engine===null)throw new Error(tr("Ни один компьютер не распознаёт речь"));
  try{await transcribePiece(next,engine)}catch(e){voice.engine=undefined;throw e}
  return true;
}
async function runVoice(){
  if(voice.working||document.hidden)return;
  voice.working=true;clearTimeout(voice.retry);
  try{
    while(await voiceStep()){voice.failures=0;voice.error=""}
    // Text for another computer's session waits until that computer is chosen again.
    if(voice.pending)voice.retry=setTimeout(runVoice,30000);
  }catch(e){
    voice.error=e.message;
    voice.retry=setTimeout(runVoice,VOICE_RETRY[Math.min(voice.failures++,VOICE_RETRY.length-1)]*1000);
  }finally{voice.working=false;renderVoice()}
}
// Under the field, visible with the keyboard open too: what happens to the speech, and where its text goes.
function voiceStatus(){
  const rec=voice.rec;
  if(rec){
    const seconds=Math.floor((Date.now()-rec.started)/1000);
    return ["rec",Math.floor(seconds/60)+":"+String(seconds%60).padStart(2,"0")+" · "+tr("текст появляется в конце поля по ходу записи")];
  }
  if(voice.pending&&voice.error)return ["error",tr("Запись сохранена, распознать пока не удалось: {0}",[voice.error])];
  if(voice.pending)return ["busy",tr("Распознаётся… текст встанет в конец поля")];
  if(Date.now()-voice.doneAt<VOICE_DONE_MS)return ["done",tr("Текст добавлен в конец поля")];
  return ["",""];
}
function renderVoice(){
  const button=$("b_mic"),state=$("voice_state"),[kind,text]=voiceStatus();
  button.classList.toggle("on",Boolean(voice.rec));button.classList.toggle("busy",kind==="busy");
  button.setAttribute("aria-pressed",voice.rec?"true":"false");
  state.hidden=!text;state.className="voice-state "+kind;state.querySelector("span").textContent=text;
}
function watchVoice(){
  const button=$("b_mic");let timer=null;
  // A long press opens the computers that recognise speech and the last dictations.
  button.addEventListener("pointerdown",()=>{timer=setTimeout(()=>{voice.held=true;openVoice()},600)});
  for(const name of ["pointerup","pointercancel","pointerleave"])button.addEventListener(name,()=>clearTimeout(timer));
  button.addEventListener("contextmenu",e=>{e.preventDefault();clearTimeout(timer);if(!voice.held)openVoice()});
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)runVoice()});
  addEventListener("online",runVoice);
  voicePrune().catch(()=>{});runVoice();
}
function voiceComputerState(c){
  if(c.checking)return tr("Проверяется…");
  if(c.unreachable)return c.unreachable;
  if(c.ready)return tr("Готово");
  if(c.phase==="binary")return tr("Устанавливается whisper.cpp…");
  if(c.phase==="model")return tr("Загружается модель: {0}%",[Math.floor(100*(c.done||0)/(c.total||c.size||1))]);
  if(c.phase==="error")return c.error;
  if(c.model&&!c.binary)return tr("Модель есть, нет программы whisper-cli");
  return tr("Нет whisper.cpp");
}
// The model's file name says which one recognises ("whisper-large-v2"), the folder only clutters.
const voiceModelName=c=>(c.uses?.[1]||"").split("/").pop().replace(/\.bin$/,"").replace(/^ggml-/,"");
function voiceComputerRow(c){
  const row=el("div","voice-computer",el("b","",deckName(c.id)),el("span","",voiceComputerState(c)));
  if(c.uses?.length)row.title=c.uses.join("\n");  // The full paths, for whoever needs to know.
  if(!c.ready&&c.can_install&&!["binary","model"].includes(c.phase)){
    const install=el("button","",c.model?tr("Установить whisper.cpp"):tr("Установить (≈{0} МБ)",[Math.round((c.size||0)/1e6)]));
    install.onclick=()=>installVoice(c.id);row.append(install);
  }
  return row;
}
// One line says who recognises; the other computers matter only to install it somewhere.
function renderVoiceComputers(){
  const summary=$("voice_summary"),more=$("voice_more"),engine=voice.computers.find(c=>c.ready);
  const checking=voice.computers.some(c=>c.checking);
  summary.classList.toggle("ready",Boolean(engine));
  summary.replaceChildren(engine?el("b","",tr("Распознаёт: {0}",[deckName(engine.id)])):el("b","",checking?tr("Ищу компьютер с whisper.cpp…"):tr("Ни на одном компьютере нет whisper.cpp")),
    ...(engine&&voiceModelName(engine)?[el("small","",voiceModelName(engine))]:[]));
  const others=voice.computers.filter(c=>c!==engine);
  more.hidden=!others.length;
  if(!engine&&!checking)more.open=true;
  $("voice_more_count").textContent=others.length;
  $("voice_computers").replaceChildren(...others.map(voiceComputerRow));
}
function voiceWhen(at){
  const date=new Date(at),today=new Date().toDateString()===date.toDateString();
  return date.toLocaleString(DATE_LOCALE,today?{hour:"2-digit",minute:"2-digit"}:{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"});
}
async function renderVoiceTexts(){
  const box=$("voice_texts");
  let texts=[];try{texts=(await voiceTexts()).sort((a,b)=>b.at-a.at).slice(0,10)}catch(e){}
  box.replaceChildren(...texts.map(t=>{
    const copy=el("button","voice-link",tr("Копировать")),put=el("button","voice-link",tr("В поле"));
    copy.onclick=()=>navigator.clipboard.writeText(t.text).then(()=>toast(tr("Скопировано"),true),()=>toast(tr("Не удалось скопировать")));
    put.onclick=()=>{if(!active)return;deliverDictation({session:active,text:t.text});$("voice_dlg").close()};
    const text=el("p","",t.text);text.onclick=()=>text.classList.toggle("open");
    return el("div","voice-text",text,el("div","voice-text-foot",el("small","",voiceWhen(t.at)+" · "+t.session),copy,put));
  }));
  $("voice_texts_title").hidden=!texts.length;
}
function renderVoiceDialog(){if($("voice_dlg").open)renderVoiceComputers()}
function openVoice(){
  const dialog=$("voice_dlg");
  if(!dialog.open)dialog.showModal();
  renderVoiceComputers();renderVoiceTexts();
  if(!voice.computers.length||Date.now()-voice.engineAt>5000)voiceEngine(true).then(watchVoiceInstall);
}
async function installVoice(id){
  try{const j=await gatewayApi(instancePath(id,"/api/voice_install"),{});updateVoiceComputer(id,j.voice)}
  catch(e){toast(e.message)}
  watchVoiceInstall();
}
function updateVoiceComputer(id,state){
  const index=voice.computers.findIndex(c=>c.id===id);
  if(index>=0)voice.computers[index]={id,...state};
  if(state.ready){voice.engine=undefined;runVoice()}
  renderVoiceDialog();
}
// Progress is read only while the dialog is open.
function watchVoiceInstall(){
  clearTimeout(voice.installTimer);
  const busy=voice.computers.filter(c=>["binary","model"].includes(c.phase));
  if(!busy.length||!$("voice_dlg").open)return;
  voice.installTimer=setTimeout(async()=>{
    await Promise.all(busy.map(c=>gatewayApi(instancePath(c.id,"/api/voice_status"),{}).then(j=>updateVoiceComputer(c.id,j.voice),()=>{})));
    watchVoiceInstall();
  },2000);
}
