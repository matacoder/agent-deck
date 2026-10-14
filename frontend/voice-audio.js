// Speech is recorded as plain 16 kHz samples and cut into pieces at pauses, so a piece never splits a word,
// fits one request to the computer that recognises it, and a long dictation is never one fragile upload.
const VOICE_RATE=16000,VOICE_PIECE_MIN=10,VOICE_PIECE_MAX=18,VOICE_WINDOW=VOICE_RATE/10;

function downsample(samples,from,to=VOICE_RATE){
  if(from===to)return Float32Array.from(samples);
  const ratio=from/to,out=new Float32Array(Math.floor(samples.length/ratio));
  for(let i=0;i<out.length;i++){
    // Averaging the samples a target sample stands for keeps high frequencies from folding back as noise.
    const start=Math.floor(i*ratio),end=Math.min(samples.length,Math.floor((i+1)*ratio));
    let sum=0;for(let j=start;j<end;j++)sum+=samples[j];
    out[i]=end>start?sum/(end-start):0;
  }
  return out;
}
function windowLevel(samples,start){
  let sum=0;const end=Math.min(samples.length,start+VOICE_WINDOW);
  for(let i=start;i<end;i++)sum+=samples[i]*samples[i];
  return end>start?Math.sqrt(sum/(end-start)):0;
}
// The quietest tenth of a second between the shortest and the longest piece: most likely a pause.
function cutPoint(samples,min=VOICE_PIECE_MIN*VOICE_RATE,max=VOICE_PIECE_MAX*VOICE_RATE){
  let best=Math.min(max,samples.length),level=Infinity;
  for(let start=min;start+VOICE_WINDOW<=Math.min(max,samples.length);start+=VOICE_WINDOW/2){
    const here=windowLevel(samples,start);
    if(here<level){level=here;best=start+VOICE_WINDOW/2}
  }
  return best;
}
// Whisper invents sentences for silence, so a piece nobody spoke in is never sent.
function hasSpeech(samples,threshold=0.01){
  for(let start=0;start<samples.length;start+=VOICE_WINDOW)if(windowLevel(samples,start)>threshold)return true;
  return false;
}
function encodeWav(samples){
  const bytes=new Uint8Array(44+samples.length*2),view=new DataView(bytes.buffer);
  const text=(at,value)=>{for(let i=0;i<value.length;i++)bytes[at+i]=value.charCodeAt(i)};
  text(0,"RIFF");view.setUint32(4,36+samples.length*2,true);text(8,"WAVEfmt ");
  view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);
  view.setUint32(24,VOICE_RATE,true);view.setUint32(28,VOICE_RATE*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);
  text(36,"data");view.setUint32(40,samples.length*2,true);
  for(let i=0;i<samples.length;i++){const s=Math.max(-1,Math.min(1,samples[i]));view.setInt16(44+i*2,s<0?s*0x8000:s*0x7fff,true)}
  return bytes;
}
function joinDictation(current,text){
  if(!text)return current;
  return current&&!/\s$/.test(current)?current+" "+text:current+text;
}
// Pieces wait here until their text is in the message field: a closed tab, a reload or a lost
// connection loses at most the last few seconds, never the dictation.
const VOICE_DB="deckaway-voice",VOICE_PIECES="pieces",VOICE_TEXTS="texts";
function voiceDb(){
  return new Promise((resolve,reject)=>{
    const request=indexedDB.open(VOICE_DB,1);
    request.onupgradeneeded=()=>{const db=request.result;db.createObjectStore(VOICE_PIECES,{keyPath:"key"});db.createObjectStore(VOICE_TEXTS,{keyPath:"rec"})};
    request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
  });
}
async function voiceStore(store,mode,work){
  const db=await voiceDb();
  return new Promise((resolve,reject)=>{
    const tx=db.transaction(store,mode),request=work(tx.objectStore(store));
    tx.oncomplete=()=>{db.close();resolve(request?.result)};tx.onerror=tx.onabort=()=>{db.close();reject(tx.error)};
  });
}
const voicePieces=()=>voiceStore(VOICE_PIECES,"readonly",s=>s.getAll());
const voicePut=piece=>voiceStore(VOICE_PIECES,"readwrite",s=>s.put(piece));
const voiceRemove=key=>voiceStore(VOICE_PIECES,"readwrite",s=>s.delete(key));
const voiceTexts=()=>voiceStore(VOICE_TEXTS,"readonly",s=>s.getAll());
const voicePieceKey=(rec,seq)=>rec+"-"+String(seq).padStart(5,"0");
// Every dictation's text is kept for a week, so a draft lost with a closed tab can be put back.
const VOICE_KEEP_MS=7*86400000;
const voiceKeep=(entry,text)=>voiceStore(VOICE_TEXTS,"readwrite",s=>{
  const read=s.get(entry.rec);
  read.onsuccess=()=>s.put({...entry,text:joinDictation(read.result?.text||"",text),at:Date.now()});
  return read;
});
const voicePrune=()=>voiceStore(VOICE_TEXTS,"readwrite",s=>{
  const read=s.getAll();
  read.onsuccess=()=>{for(const t of read.result)if(Date.now()-t.at>VOICE_KEEP_MS)s.delete(t.rec)};
  return read;
});
function bytesToBase64(bytes){
  let text="";
  for(let i=0;i<bytes.length;i+=0x8000)text+=String.fromCharCode.apply(null,bytes.subarray(i,i+0x8000));
  return btoa(text);
}

if(typeof module!=="undefined")module.exports={downsample,cutPoint,hasSpeech,encodeWav,joinDictation,voicePieceKey,bytesToBase64,VOICE_RATE};
