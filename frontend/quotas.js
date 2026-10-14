/* The limits line under the message field: what is left of every subscription, the one this session spends
standing out, and a local model's speed for a session that runs on one. Functions and plain state only: the
listener that refits the line is in app.js, which defines $. */
function fmtReset(ts){
  if(!ts)return"";
  const ms=ts*1000-Date.now();if(ms<=0)return tr("сбрасывается…");
  const m=Math.round(ms/60000),d=new Date(ts*1000);
  const rel=m<60?tr("{0} мин",[m]):m<1440?tr("{0} ч {1} мин",[Math.floor(m/60),m%60]):tr("{0} д {1} ч",[Math.floor(m/1440),Math.floor(m%1440/60)]);
  const hm=d.toLocaleTimeString(DATE_LOCALE,{hour:"2-digit",minute:"2-digit"});
  const abs=m<1440&&d.getDate()===new Date().getDate()?hm:d.toLocaleDateString(DATE_LOCALE,{weekday:"short",day:"numeric",month:"short"})+" "+hm;
  return tr("сброс через {0} · {1}",[rel,abs]);
}
function compactDuration(minutes){
  const days=Math.floor(minutes/1440),hours=Math.floor(minutes%1440/60);
  return days?tr("{0}д {1}ч",[days,hours]):hours?tr("{0}ч {1}м",[hours,minutes%60]):tr("{0}м",[minutes]);
}
const QUOTA_OF={claude:"claude",codex:"codex","claude-kimi":"kimi",kimi:"kimi"};
// Days while days are left, then hours: the line holds every subscription, so each gets a few characters.
function shortReset(ts){
  const minutes=Math.max(0,Math.round((ts*1000-Date.now())/60000));
  return "↻ "+(minutes>=1440?tr("{0}д",[Math.round(minutes/1440)]):minutes>=60?tr("{0}ч",[Math.round(minutes/60)]):tr("{0}м",[minutes]));
}
function quotaItem(name,w,used){
  const percent=Number.isFinite(w.percent)?Math.round(Math.max(0,Math.min(100,100-w.percent))):null,plan=plannedRemaining(w,now());
  const item=el("span","quota-item"+(used?" on":""),agentIcon({agent:name}),
    el("span","quota-percent "+quotaTone(percent,plan),percent===null?"—":percent+"%"),el("span","quota-plan",plan===null?"—":plan+"%"),
    el("span","quota-reset",w.resets_at?shortReset(w.resets_at):"↻ —"));
  item.title=AGENTS[name].label+" · "+tr(w.label||"")+" · "+tr("Остаток")+" / "+tr("По плану к концу текущих суток лимита")+" · "+fmtReset(w.resets_at)+(usageData[name].stale?" · "+tr("⚠ данные устарели"):"");
  item.setAttribute("role","img");item.setAttribute("aria-label",item.title+": "+item.textContent);
  return item;
}
// Under the message field: what is left of every subscription, the one this session spends standing out.
function sessionStatus(session){
  const used=QUOTA_OF[agentOf(session)];
  const items=["claude","codex","kimi"].map(name=>[name,primaryQuota(usageData[name])]).filter(([,w])=>w).map(([name,w])=>quotaItem(name,w,name===used));
  if(!items.length)return null;
  const more=el("button","quota-more","…");more.type="button";more.hidden=true;more.title=tr("Все лимиты");more.setAttribute("aria-label",more.title);
  more.onclick=()=>{quotaOpen=!quotaOpen;fitQuotas()};
  return el("span","session-status",...items,more);
}
// A narrow screen keeps the limits that fit in one line and a button for the rest.
let quotaOpen=false;
function fitQuotas(){
  const line=$("send_state").querySelector(".session-status"),more=line?.querySelector(".quota-more");
  if(!more||!line.getClientRects().length)return;  // A hidden line has no widths to go by.
  const items=[...line.querySelectorAll(".quota-item")];
  for(const item of items)item.hidden=false;
  more.hidden=false;line.classList.toggle("open",quotaOpen);more.setAttribute("aria-expanded",String(quotaOpen));
  const gap=parseFloat(getComputedStyle(line).columnGap)||0,widths=items.map(item=>item.offsetWidth);
  const kept=quotaFit(widths,gap,$("send_state").parentElement.clientWidth,more.offsetWidth,items.findIndex(item=>item.classList.contains("on")));
  more.hidden=kept.length===items.length;
  if(more.hidden)quotaOpen=false;
  if(!quotaOpen)items.forEach((item,index)=>{item.hidden=!kept.includes(index)});
}
// The speed of a local model, shown under the message field of a session that runs on it.
function localUsage(profile){
  const activity=profile.activity||[],live=activity[0],sample=profile.performance||{};
  const labels={waiting:"Ожидание первого токена",thinking:"Модель рассуждает",tool:"Готовит вызов инструмента",generating:"Генерирует ответ"};
  const line=el("div","local-live-line");
  const seconds=Math.floor(live?.request_time_seconds||0),elapsed=Math.floor(seconds/60)+":"+String(seconds%60).padStart(2,"0");
  const state=el("span","local-state",live?(live.phase==="waiting"?"◌ TTFT "+elapsed:(live.phase==="tool"?"⚙ ":"✦ ")+elapsed+(live.chunks?" · "+live.chunks+" Δ":"")):"✓ "+(Number.isFinite(sample.output_tokens)?sample.output_tokens+" tok":"—"));
  state.title=live?tr(labels[live.phase]||labels.waiting):(lmMetrics(sample)||tr("Нет замеров"));
  if(live)state.classList.add("local-active");
  line.append(state);
  const m=Number.isFinite(live?.tokens_per_second)?live:sample;
  const exact=Number.isFinite(m.tokens_per_second),average=!exact&&m.output_tokens>0&&m.request_time_seconds>0;
  const rate=exact?m.tokens_per_second:average?m.output_tokens/m.request_time_seconds:null;
  const speed=el("span","local-rate",rate===null?"— tok/s":(average?"≈":"")+rate.toFixed(1)+" tok/s"+(average?tr(" сред."):""));
  speed.title=(m===sample?tr("Последний ответ")+" · ":"")+(average?tr("Средняя скорость с учётом ожидания"):"tok/s");
  line.append(speed);
  return line;
}
