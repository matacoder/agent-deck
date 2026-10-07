function shortModel(model){
  const name=String(model||"").split("/").pop();
  const claude=name.match(/^claude-([a-z]+)-(\d+)(?:-(\d))?(?:-\d{8})?(?:\[1m\])?$/i);
  if(claude)return claude[1][0].toUpperCase()+claude[1].slice(1)+" "+claude[2]+(claude[3]?"."+claude[3]:"");
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
// The window is split into equal days counted from its start (a week into 7), not calendar days: the
// plan is what should be left when the current one of those days ends, so it moves in steps of 1/7.
function plannedRemaining(w,instant=Date.now()/1000){
  const duration=quotaDuration(w);
  if(!Number.isFinite(w?.resets_at)||!duration)return null;
  const days=Math.max(1,Math.round(duration/86400)),elapsed=instant-(w.resets_at-duration);
  const day=Math.min(days,Math.max(1,Math.floor(elapsed/(duration/days))+1));
  return Math.round(100*(days-day)/days);
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
function matchesSessionQuery(session,query){
  return !query||[session.name,sessionTitle(session),session.group,session.path].join(" ").toLowerCase().includes(query);
}

if(typeof module!=="undefined")module.exports={sessionTitle,matchesSessionQuery,shortModel,quotaDuration,plannedRemaining,primaryQuota,quotaTone};
