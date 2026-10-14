// Dictation: the microphone button records, a computer with whisper.cpp turns each piece into text, and the
// text joins the draft of the session it was spoken to. Pieces wait in IndexedDB until their text is there.
const voice={rec:null,working:false,engine:undefined,engineAt:0,computers:[],retry:null,failures:0,error:"",pending:0,prompts:new Map(),held:false};
const VOICE_ENGINE_MS=300000,VOICE_RETRY=[5,15,30,60];

// The first ready computer answers the question; a sleeping one is not waited for.
function voiceEngine(force=false){
  if(!force&&voice.engine!==undefined&&Date.now()-voice.engineAt<VOICE_ENGINE_MS)return Promise.resolve(voice.engine);
  const ids=["",...deckDirectory.decks.map(d=>d.id)];
  voice.computers=ids.map(id=>({id,checking:true}));
  return new Promise(resolve=>{
    let left=ids.length,found=false;
    const settle=(index,state)=>{
      voice.computers[index]=state;left--;renderVoiceDialog();
      if(state.ready&&!found){found=true;voice.engine=state.id;voice.engineAt=Date.now();resolve(state.id)}
      if(!left&&!found){voice.engine=null;voice.engineAt=Date.now();resolve(null)}
    };
    ids.forEach((id,index)=>gatewayApi(instancePath(id,"/api/voice_status"),{})
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
function renderVoice(){
  const rec=voice.rec,button=$("b_mic"),state=$("voice_state");
  button.classList.toggle("on",Boolean(rec));button.setAttribute("aria-pressed",rec?"true":"false");
  const seconds=rec?Math.floor((Date.now()-rec.started)/1000):0;
  const text=rec?"● "+Math.floor(seconds/60)+":"+String(seconds%60).padStart(2,"0")
    :voice.error&&voice.pending?tr("Запись сохранена, распознать пока не удалось: {0}",[voice.error])
    :voice.pending?tr("Распознаётся: {0}",[voice.pending]):"";
  state.hidden=!text;state.textContent=text;state.classList.toggle("error",Boolean(!rec&&voice.error&&voice.pending));state.classList.toggle("rec",Boolean(rec));
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
  return c.can_install?tr("Не установлено"):tr("Нужен whisper.cpp: установите его, чтобы команда whisper-cli была доступна");
}
function renderVoiceComputers(){
  const box=$("voice_computers");if(!box)return;
  box.replaceChildren(...voice.computers.map(c=>{
    const row=el("div","voice-computer",el("b","",deckName(c.id)),el("span","",voiceComputerState(c)));
    // The copy already installed is named, so nobody installs a second one.
    if(c.uses?.length)row.append(el("small","voice-uses",c.uses.join(" · ")));
    if(!c.ready&&c.can_install&&!["binary","model"].includes(c.phase)){
      const install=el("button","",c.model?tr("Установить whisper.cpp"):tr("Установить (≈{0} МБ)",[Math.round((c.size||0)/1e6)]));
      install.onclick=()=>installVoice(c.id);row.append(install);
    }
    return row;
  }));
}
async function renderVoiceTexts(){
  const box=$("voice_texts");
  let texts=[];try{texts=(await voiceTexts()).sort((a,b)=>b.at-a.at).slice(0,10)}catch(e){}
  box.replaceChildren(...texts.map(t=>{
    const copy=el("button","",tr("Копировать")),put=el("button","",tr("Вставить"));
    copy.onclick=()=>navigator.clipboard.writeText(t.text).then(()=>toast(tr("Скопировано"),true),()=>toast(tr("Не удалось скопировать")));
    put.onclick=()=>{if(!active)return;deliverDictation({session:active,text:t.text});$("voice_dlg").close()};
    return el("div","voice-text",el("small","",new Date(t.at).toLocaleString(DATE_LOCALE)+" · "+t.session),el("p","",t.text),el("div","acts",copy,put));
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
