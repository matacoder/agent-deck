// Is this browser on one of the computers it shows? The page of a gateway may be opened from anywhere; a
// panel on the same machine answers one question on 127.0.0.1 (integrations/here.py), and only to the right
// installation id. A phone is never one of these computers, so it does not ask. Bundled before app.js.
const here={found:undefined,asking:null};  // found: a computer's id, "" for the gateway itself, null for none
// Who could be this machine: an installation id and the port its panel listens on. Pure for tests.
function hereCandidates(network,decks){
  const port=url=>{try{return new URL(url).port||"80"}catch(e){return ""}};
  return [{id:"",instance:network?.instance,port:String(network?.bind_port||"")},...(decks||[]).map(d=>({id:d.id,instance:d.instance,port:port(d.url)}))]
    .filter(c=>/^[0-9a-f]{24}$/.test(c.instance||"")&&/^\d{1,5}$/.test(c.port));
}
// A computer's name as lists show it. Pure for tests.
function hereName(name,id,found,translate){return found===id?name+" · "+translate("этот компьютер"):name}
async function askHere(candidate){
  const stop=new AbortController(),timer=setTimeout(()=>stop.abort(),1500);
  try{
    const answer=await fetch(`http://127.0.0.1:${candidate.port}/api/here?id=${candidate.instance}`,
      {mode:"cors",credentials:"omit",referrerPolicy:"no-referrer",cache:"no-store",signal:stop.signal});
    return answer.ok&&(await answer.json()).same===true;
  }catch(e){return false}  // No panel here, or the browser does not let a public page ask this machine.
  finally{clearTimeout(timer)}
}
// Asked once per page: the answer does not change while it is open. With one computer there is nothing to
// tell apart, and no reason for the browser's "local network" question.
function findHere(network,decks){
  if(here.found!==undefined||!decks?.length||isMobile()||isTouch())return Promise.resolve(here.found??null);
  here.asking=here.asking||(async()=>{
    const candidates=hereCandidates(network,decks),answers=await Promise.all(candidates.map(askHere));
    const index=answers.indexOf(true);
    here.found=index<0?null:candidates[index].id;
    return here.found;
  })();
  return here.asking;
}

if(typeof module!=="undefined")module.exports={hereCandidates,hereName};
