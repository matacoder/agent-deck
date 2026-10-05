function shortModel(model){
  const name=String(model||"").split("/").pop();
  const match=name.match(/^([a-z][a-z0-9.]*)[-_].*?([0-9]+(?:\.[0-9]+)?[bm])(?:[-_]|$)/i);
  if(match)return match[1][0].toUpperCase()+match[1].slice(1)+" "+match[2].toUpperCase();
  return name.length>30?name.slice(0,27)+"…":name;
}
function quotaDuration(w){
  if(Number.isFinite(w?.secs)&&w.secs>0)return w.secs;
  if(w?.period!=="month"||!Number.isFinite(w.resets_at))return null;
  const reset=new Date(w.resets_at*1000),start=new Date(reset),day=reset.getUTCDate();
  start.setUTCDate(1);start.setUTCMonth(start.getUTCMonth()-1);
  const lastDay=new Date(Date.UTC(start.getUTCFullYear(),start.getUTCMonth()+1,0)).getUTCDate();
  start.setUTCDate(Math.min(day,lastDay));
  return (reset-start)/1000;
}
function plannedRemaining(w,instant=Date.now()/1000){
  const duration=quotaDuration(w);
  if(!Number.isFinite(w?.resets_at)||!duration)return null;
  const end=new Date(instant*1000);end.setHours(24,0,0,0);
  const cutoff=Math.min(end.getTime()/1000,w.resets_at);
  return Math.round(Math.max(0,Math.min(100,100*(w.resets_at-cutoff)/duration)));
}
function primaryQuota(u){
  const windows=u?.windows||[];
  return windows.find(w=>w.period==="month"&&!/code|код/i.test(w.label||""))||windows.find(w=>w.secs>=86400)||windows[0];
}
function quotaTone(remaining,plan){
  if(!Number.isFinite(remaining)||!Number.isFinite(plan))return "";
  return remaining>=plan?"good":plan-remaining<=3?"over":"crit";
}

function sessionTitle(session){return session?.title||session?.name||""}

if(typeof module!=="undefined")module.exports={sessionTitle,shortModel,quotaDuration,plannedRemaining,primaryQuota,quotaTone};
