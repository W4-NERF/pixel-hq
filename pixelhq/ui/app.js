/* Every string coming from cards, sessions or the ledger goes through esc() before it touches innerHTML. */
let DATA = /*PIXELHQ_DATA*/null;
let LIVE = null, LIVE_ERR = null;
const CFG = () => (DATA && DATA.cfg) || {locale:'en-GB', timezone:'UTC', xp:{pass:10,revise:3,fail:-5}, staleDays:14, rooms:[], operator:'operator', orchestrator:'default'};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeColor = c => /^#[0-9a-fA-F]{6}$/.test(c) ? c : '#93A1AF';
const safeId = s => String(s || '').replace(/[^a-zA-Z0-9_-]/g, '');
function submitToHost(message,unavailable){if(window.parent===window){unavailable({ok:false,message:'standalone page: no host, nothing was sent'});return}
 window.parent.postMessage(message,'*')}
function liveOf(id){const v = LIVE && LIVE.bots && LIVE.bots[id]; return v || null}
function shortStep(st){if(!st)return '';let m;
 if((m=st.match(/terminal command running \((\d+)s/)))return 'terminal · '+m[1]+' s';
 if((m=st.match(/sequential tool running \((\d+)s\): (\w+)/)))return m[2]+' · '+m[1]+' s';
 if((m=st.match(/delegate_task: subagent running (\w+) \(iteration (\d+)\/(\d+)\)/)))return 'subagent '+m[2]+'/'+m[3];
 if((m=st.match(/tool running: (\w+)/)))return m[1];
 if(/receiving stream response/.test(st))return 'thinking …';
 if(/starting new turn/.test(st))return 'new turn';
 return st.length>22?st.slice(0,21)+'…':st}
function liveStatus(b){const v=liveOf(b.id);if(!v)return {status:b.status,label:null};
 if(v.active){const s=v.sessions[0];if(s)return {status:'running',label:shortStep(s.step)||'active'};const t=v.tasks[0];return {status:'running',label:t?'kanban · '+(t.heartbeatAge==null?'no heartbeat':'hb '+t.heartbeatAge+' s'):'active'}}
 return {status:b.status==='running'?'idle':b.status,label:null}}
/* 8×9 pixel sprite drawn with box-shadow; leader gets a crown, quarantine zone gets amber eyes */
const SPR=["..a..a..","..XXXX..",".XXXXXX.",".XeXXeX.",".XXXXXX.","..XmmX..",".XXXXXX.","X.XXXX.X","..X..X.."];
const CROWN=["c.c..c.c","cccccccc"];
const quarantineZones=()=>new Set(CFG().rooms.flatMap(r=>(r.zones||[]).filter(z=>z.quarantine).map(z=>z.id)));
function sprite(b,px){px=px||4;let rows=SPR.slice();if(b.leader)rows=CROWN.concat(SPR.slice(1));
 if(quarantineZones().has(b.zone))rows=rows.map(r=>r.replace(/e/g,'q'));
 const col=safeColor(b.color),sh=[];rows.forEach((row,y)=>[...row].forEach((c,x)=>{const m={X:col,e:'#0B0F14',q:'#C9A23F',a:'#DCE4EC',m:'rgba(11,15,20,.5)',c:'#C9A23F'}[c];
  if(m)sh.push((x*px)+'px '+(y*px)+'px 0 '+m)}));
 return '<div class="spr" style="width:'+(8*px)+'px;height:'+(rows.length*px)+'px"><i style="width:'+px+'px;height:'+px+'px;box-shadow:'+sh.join(',')+'"></i></div>'}
const ST={running:'working',blocked:'blocked',idle:'idle',offline:'offline'};
function bubble(b){const lv=liveStatus(b);if(lv.status==='running')return '<span class="bub'+(lv.label?' live':'')+'" title="'+esc(lv.label||'')+'">'+(lv.label?esc(lv.label):'...')+'</span>';
 if(lv.status==='blocked')return '<span class="bub blocked">! '+Number(b.blocked)+'</span>';
 if(lv.status==='offline')return '<span class="bub offline">x</span>';return '<span class="bub idle">z</span>'}
const ATTR=['Precision','Stamina','Discipline','Wisdom'],ATTR_T=['correctness','completeness','format','safety'];
const fmtN=n=>Number(n||0).toLocaleString(CFG().locale);
const fmt1=(v,d)=>v==null?'–':Number(v).toLocaleString(CFG().locale,{maximumFractionDigits:d||0});
function ago(ts){if(!ts)return '–';const s=(LIVE?LIVE.generated:DATA.generated)-ts;if(s<90)return 'just now';if(s<3600)return Math.round(s/60)+' min ago';if(s<86400)return Math.round(s/3600)+' h ago';return Math.round(s/86400)+' d ago'}
function clock(ts){try{return new Date(ts*1000).toLocaleString(CFG().locale,{timeZone:CFG().timezone,day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})}catch(e){return new Date(ts*1000).toISOString().slice(5,16)}}
function hm(){try{return new Date().toLocaleTimeString(CFG().locale,{timeZone:CFG().timezone,hour:'2-digit',minute:'2-digit'})}catch(e){return new Date().toISOString().slice(11,16)}}
const hpTxt=b=>b.hp==null?'–':Number(b.hp)+'%';
function bars(b){return '<div class="mut" style="font-size:10px">LVL '+Number(b.lvl)+' · '+fmtN(b.xp)+' XP</div>'+(b.xpSummon?'<div class="mut" style="font-size:10px">own '+fmtN(b.xpOwn)+' · summons '+fmtN(b.xpSummon)+'</div>':'')+'<div class="bar xp"><b style="width:'+Number(b.xpPct)+'%"></b></div>'+
 '<div class="mut" style="font-size:10px;margin-top:4px">HP '+hpTxt(b)+(b.n?' · '+Number(b.n)+' reviews':' · no reviews yet')+'</div><div class="bar hp'+(b.hp!=null&&b.hp<75?' low':'')+'"><b style="width:'+Number(b.hp??0)+'%"></b></div>'}
function evk(kind){const x=CFG().xp,sg=n=>(n>0?'+':'')+n;
 return {'qc-pass':[sg(x.pass)+' XP · QC pass','ok'],'qc-revise':[sg(x.revise)+' XP · revision','warn'],'qc-fail':[sg(x.fail)+' XP · QC fail','bad'],completed:['quest completed','ok'],blocked:['quest blocked','bad'],
 changes_requested:['changes requested','warn'],gave_up:['gave up','bad'],timed_out:['timed out','bad'],protocol_violation:['protocol violation','warn'],suspected_hallucinated_references:['mirage: hallucinated reference','bad'],created:['new quest','']}[kind]||[kind,'']}
function logHtml(){return DATA.events.map(e=>{const k=e.selfReview?['self-review · no XP','']:evk(e.kind);return '<div class="ev '+k[1]+'"><span class="t">'+clock(e.ts)+'</span> <b>'+esc(e.bot)+'</b>'+(e.summon?' <span class="mut">(summon)</span>':'')+' · '+esc(k[0])+'<div class="mut2">'+esc(e.text)+'</div></div>'}).join('')||'<div class="ev">no events</div>'}
let sel=null,ofilter='all',bzone='all',bsort='lvl';
/* ---- UI reviews: drafts survive polling; only Confirm sends a host message ---- */
const reviewDrafts=new Map(),reviewPending=new Set(),reviewResults=new Map();
const reviewKey=(agent,sessionId)=>JSON.stringify([agent,sessionId||null]);
function reviewBody(key){const d=reviewDrafts.get(key),pending=reviewPending.has(key),r=reviewResults.get(key);
 let h='<div class="acts"><span class="mut">Rate:</span>'+['pass','revise','fail'].map(v=>'<button type="button" data-rate="'+v+'"'+(d&&d.verdict===v?' class="on"':'')+(pending?' disabled':'')+'>'+v+'</button>').join('')+'</div>';
 if(d)h+='<form data-review-form><fieldset'+(pending?' disabled':'')+'><div class="review-dims">'+ATTR_T.map(name=>'<label>'+esc(name)+'<select data-review-dim="'+name+'">'+[1,2,3,4,5].map(v=>'<option value="'+v+'"'+(v===d.dims[name]?' selected':'')+'>'+v+'</option>').join('')+'</select></label>').join('')+'</div>'+
  '<label class="review-ref">Ref<input data-review-ref type="text" maxlength="200" value="'+esc(d.ref)+'"></label><div class="acts"><button type="submit">Confirm</button><button type="button" data-review-cancel>Cancel</button></div></fieldset></form>';
 if(pending)h+='<div class="res" role="status">Saving review …</div>';
 if(r)h+='<div class="res '+(r.ok?'ok':'bad')+'" role="status">'+esc(r.message||r.error||'No review result received.')+'</div>';
 return h}
function reviewHtml(agent,sessionId,ref){if(!EMBED)return '';
 const key=reviewKey(agent,sessionId);
 return '<div class="review" data-review="'+esc(key)+'" data-agent="'+esc(agent)+'" data-session="'+esc(sessionId||'')+'" data-ref="'+esc(String(ref||'').slice(0,80))+'">'+reviewBody(key)+'</div>'}
function refreshReview(el){el.innerHTML=reviewBody(el.dataset.review);bindReview(el)}
function bindReview(el){const key=el.dataset.review;
 el.querySelectorAll('[data-rate]').forEach(btn=>btn.onclick=()=>{if(reviewPending.has(key))return;
  const previous=reviewDrafts.get(key);
  reviewDrafts.set(key,{agent:el.dataset.agent,sessionId:el.dataset.session||null,verdict:btn.dataset.rate,
   dims:previous?previous.dims:Object.fromEntries(ATTR_T.map(name=>[name,4])),ref:previous?previous.ref:el.dataset.ref});
  reviewResults.delete(key);refreshReview(el)});
 const d=reviewDrafts.get(key),form=el.querySelector('[data-review-form]');if(!d||!form)return;
 el.querySelectorAll('[data-review-dim]').forEach(input=>input.onchange=()=>{d.dims[input.dataset.reviewDim]=Number(input.value)});
 const ref=el.querySelector('[data-review-ref]');ref.oninput=()=>{d.ref=ref.value.slice(0,200)};
 el.querySelector('[data-review-cancel]').onclick=()=>{if(reviewPending.has(key))return;reviewDrafts.delete(key);reviewResults.delete(key);refreshReview(el)};
 form.onsubmit=e=>{e.preventDefault();if(reviewPending.has(key))return;
  const body={agent:d.agent,verdict:d.verdict,dims:{...d.dims},ref:d.ref,sessionId:d.sessionId};
  reviewPending.add(key);reviewResults.delete(key);refreshReview(el);
  submitToHost({pixelhqReview:body},r=>onReviewResult({...r,agent:body.agent,sessionId:body.sessionId}))}}
function bindReviews(root){root.querySelectorAll('[data-review]').forEach(bindReview)}
function onReviewResult(r){const key=reviewKey(r.agent,r.sessionId);if(!reviewPending.has(key))return;
 reviewPending.delete(key);reviewResults.set(key,r);if(r.ok)reviewDrafts.delete(key);
 document.querySelectorAll('[data-review]').forEach(el=>{if(el.dataset.review===key)refreshReview(el)})}
function detail(b){const a=b.attrs.map((v,i)=>'<div class="attr" title="'+ATTR_T[i]+'"><span>'+ATTR[i]+'</span><div class="bar at"><b style="width:'+(v==null?0:Number(v)*20)+'%"></b></div><span>'+(v==null?'–':Number(v))+'</span></div>').join('');
 const qs=b.quests.map(q=>'<div class="ql"><span class="s s-'+esc(q.status)+'">'+esc(q.status)+'</span><span><span class="mut">'+esc(q.board)+'</span> '+esc(q.title)+'</span></div>').join('')||'<div class="mut" style="font-size:11px">no open quests</div>';
 const more=b.openQuests-b.quests.length;
 const ach=b.achievements.map(x=>'<span class="ach '+esc(x[2])+'" title="'+esc(x[1])+'"><i></i>'+esc(x[0])+'</span>').join('')||'<span class="mut" style="font-size:11px">none yet</span>';
 document.getElementById('detail').innerHTML='<div class="card st-'+esc(b.status)+'"><span class="lv">'+Number(b.lvl)+'</span><div class="top"><div class="holder">'+sprite(b,7)+bubble(b)+'</div><div style="flex:1;min-width:0"><h2>'+esc(b.id)+'</h2><div class="mut" style="font-size:11px">'+esc(b.title)+' · '+esc(b.cls)+'</div><div style="margin-top:8px">'+bars(b)+'</div></div></div>'+
 '<div class="sec">STATUS</div><div class="kv"><span class="mut">Status</span><span>'+esc(ST[b.status])+'</span><span class="mut">Current</span><span>'+(esc(b.quest)||'–')+'</span><span class="mut">Gear</span><span>'+esc(b.model)+'</span><span class="mut">Location</span><span>'+(esc(b.loc)||'–')+(b.gateway?' · gateway '+esc(b.gateway):'')+'</span><span class="mut">Last activity</span><span>'+ago(b.lastActivity)+'</span><span class="mut">Sessions 7 d</span><span>'+(b.sessions7d==null?'–':Number(b.sessions7d))+'</span></div>'+
 reviewHtml(b.id,null,b.quest)+'<div class="sec">RECORD (PASS/REVISE/FAIL)</div><div class="kv"><span class="mut">Own</span><span>'+b.own.map(Number).join(' / ')+'</span><span class="mut">Summons</span><span>'+b.summ.map(Number).join(' / ')+(b.subSessions?' <span class="mut">· '+Number(b.subSessions)+' sub-agent sessions</span>':'')+'</span></div>'+
 '<div class="sec">ATTRIBUTES'+(b.attrsSource==='kanban'?' <span class="mut">(from Kanban)</span>':b.attrsSource==='reviews'?' <span class="mut">(from reviews)</span>':'')+'</div>'+a+'<div class="sec">QUESTS ('+Number(b.openQuests)+' open, '+Number(b.blocked)+' blocked)</div>'+qs+(more>0?'<div class="mut" style="font-size:10px">+'+more+' more</div>':'')+'<div class="sec">ACHIEVEMENTS</div>'+ach+'</div>';bindReviews(document.getElementById('detail'))}
function select(id){sel=id;document.querySelectorAll('.desk').forEach(d=>d.classList.toggle('sel',d.dataset.id===id));const b=DATA.bots.find(x=>x.id===id);if(b)detail(b)}
function roomsHtml(){const rooms=CFG().rooms||[];const main=rooms.find(r=>r.main)||rooms[0];
 const zoneHtml=z=>'<div class="zone'+(z.quarantine?' q':'')+'"><h4>'+esc(z.label||z.id)+'</h4><div class="desks" data-zone="'+safeId(z.id)+'"></div></div>';
 const roomHtml=(r,isMain)=>'<div class="room'+(isMain?' main':'')+'"><h3>'+esc(r.label||r.id)+'</h3>'+(r.zones||[]).map(zoneHtml).join('')+(r.note?'<div class="mut" style="font-size:10px;margin-top:8px">'+esc(r.note)+'</div>':'')+'</div>';
 return rooms.map(r=>roomHtml(r,r===main)).join('')+'<div class="room"><h3>REACTOR</h3><div id="rack"></div></div>'}
function office(){const floor=document.getElementById('floor');floor.innerHTML=roomsHtml();floor.style.setProperty('--side',Math.max(1,(CFG().rooms||[]).length));
 const zones={};floor.querySelectorAll('[data-zone]').forEach(el=>{zones[el.dataset.zone]=el});
 const fallback=Object.keys(zones)[0];
 DATA.bots.forEach(b=>{const el=zones[safeId(b.zone)]||zones[fallback];if(!el)return;const lst=liveStatus(b).status;el.insertAdjacentHTML('beforeend','<div class="desk st-'+esc(lst)+(ofilter!=='all'&&lst!==ofilter?' dim':'')+'" tabindex="0" data-id="'+esc(b.id)+'" title="'+esc(b.id)+' – '+esc(ST[lst])+(b.quest?': '+esc(b.quest):'')+'"><div class="holder">'+sprite(b,4)+bubble(b)+'</div><div class="tbl"></div><div class="nm">'+esc(b.id)+'</div><div class="mut" style="font-size:9px">LVL '+Number(b.lvl)+' · HP '+hpTxt(b)+'</div></div>')});
 document.querySelectorAll('.desk').forEach(d=>{d.onclick=()=>select(d.dataset.id);d.onkeydown=e=>{if(e.key==='Enter')select(d.dataset.id)}});
 document.getElementById('rack').innerHTML=reactorHtml(DATA.reactor);
 if(!sel||!DATA.bots.find(b=>b.id===sel))sel=(DATA.bots.find(b=>b.leader)||DATA.bots[0]||{}).id;
 select(sel);document.getElementById('log1').innerHTML=logHtml()}
function tps(v){if(v==null)return '–';return v>=1000?fmt1(v/1000,1)+'k':fmt1(v)}
function reactorHtml(g){if(!g)return '<div class="mut" style="font-size:11px">No GPU/LLM metrics configured (gpu.prometheus_url in config.json).</div>';
 let h=(g.nodes.length?g.nodes.map(n=>'<div class="srv"><div class="px" style="font-size:11px">'+esc(n.id)+'</div><div style="margin:4px 0">'+'<span class="led"></span>'.repeat(6)+'</div><div class="mut" style="font-size:10px">GPU '+(n.util==null?'–':Number(n.util))+' % · '+(n.power==null?'–':Number(n.power))+' W</div><div class="bar xp"><b style="width:'+Number(n.util||0)+'%"></b></div></div>').join(''):'<div class="mut">no DCGM data</div>')+
 '<div class="mut" style="font-size:10px">Model: '+(esc(g.model)||'not reachable')+'</div>';
 const t=g.srv;if(!t)return h+'<div class="mut" style="font-size:10px;margin-top:6px">no serving metrics ('+esc(g.engine)+':*)</div>';
 const kv=t.kv==null?null:Math.round(t.kv*100);
 const pair=t.pairBroken==null&&t.pairStalled==null?'':(t.pairBroken>0?' · <span style="color:var(--rust)">node pair broken</span>':t.pairStalled>0?' · <span style="color:var(--amber)">node pair stalled</span>':' · <span style="color:var(--olive)">node pair ok</span>');
 return h+'<div class="srv" style="margin-top:8px"><div class="px" style="font-size:11px">'+esc(g.engine.toUpperCase())+pair+'</div>'+
 '<div class="kv" style="grid-template-columns:112px 1fr;margin-top:4px"><span class="mut">Decode</span><span>'+tps(t.decodeTps)+' tok/s</span><span class="mut">Prefill</span><span>'+tps(t.prefillTps)+' tok/s</span>'+
 '<span class="mut">Requests</span><span>'+fmt1(t.running)+' running · '+fmt1(t.waiting)+' waiting</span>'+(t.specAccept!=null?'<span class="mut">Spec. accept</span><span>'+Math.round(t.specAccept*100)+' %</span>':'')+
 (t.ttftP50!=null?'<span class="mut">TTFT p50</span><span>'+fmt1(t.ttftP50,1)+' s</span>':'')+'</div>'+
 '<div class="mut" style="font-size:10px;margin-top:4px">KV cache '+(kv==null?'–':kv+' %')+'</div><div class="bar xp"><b style="width:'+(kv||0)+'%"></b></div>'+
 '<div class="mut" style="font-size:9px;margin-top:4px">throughput 5 min · accept/TTFT 15 min</div></div>'}
function zoneFilters(){const zones=CFG().rooms.flatMap(r=>r.zones||[]);
 document.getElementById('bfilter').innerHTML=['<button class="'+(bzone==='all'?'on':'')+'" data-z="all">All</button>'].concat(zones.map(z=>'<button class="'+(bzone===z.id?'on':'')+'" data-z="'+safeId(z.id)+'">'+esc(z.label||z.id)+'</button>')).join('');
 document.querySelectorAll('[data-z]').forEach(b=>b.onclick=()=>{bzone=b.dataset.z;board()})}
function board(){zoneFilters();const rows=DATA.bots.filter(b=>bzone==='all'||b.zone===bzone).sort((x,y)=>bsort==='id'?x.id.localeCompare(y.id):((y[bsort]??-1)-(x[bsort]??-1))||(y.xp-x.xp));
 document.getElementById('tb').innerHTML=rows.map((b,i)=>'<tr data-id="'+esc(b.id)+'"><td class="rk">'+(i+1)+'</td><td><span style="position:relative;display:inline-block">'+sprite(b,3)+'</span></td><td><b>'+esc(b.id)+'</b><div class="mut" style="font-size:10px">'+esc(b.title)+'</div></td><td class="px">'+Number(b.lvl)+'</td><td><span class="mini"><span class="bar xp" style="display:block"><b style="width:'+Number(b.xpPct)+'%"></b></span></span>'+fmtN(b.xp)+'</td><td><span class="mini"><span class="bar hp'+(b.hp!=null&&b.hp<75?' low':'')+'" style="display:block"><b style="width:'+Number(b.hp??0)+'%"></b></span></span>'+hpTxt(b)+'</td><td>'+Number(b.p)+'/'+Number(b.r)+'/'+Number(b.f)+'</td><td>'+(b.blocked?Number(b.blocked):'<span class="mut">0</span>')+'</td><td style="white-space:nowrap"><span class="dot d-'+esc(liveStatus(b).status)+'"></span>'+esc(ST[liveStatus(b).status])+'</td><td class="qcell" title="'+esc(b.quest)+'">'+(esc(b.quest)||'<span class="mut">–</span>')+'</td><td class="mut">'+esc(b.model)+'</td></tr>').join('');
 document.querySelectorAll('#tb tr').forEach(tr=>tr.onclick=()=>{sel=tr.dataset.id;tab('office')});
 document.getElementById('log2').innerHTML=logHtml()}
function hud(){const bs=DATA.bots,sum=k=>bs.reduce((a,b)=>a+Number(b[k]||0),0);const party=sum('n')?Math.round(100*sum('p')/sum('n')):0;
 const g=DATA.reactor,gpu=g?g.nodes.map(n=>n.id+' '+(n.util==null?'–':Number(n.util))+'%').join(' · ')||'–':'–';
 const reactor=g&&g.srv&&g.srv.decodeTps!=null?tps(g.srv.decodeTps)+' tok/s':gpu;
 document.getElementById('brand').textContent=CFG().label||'PIXEL HQ';
 document.getElementById('hud').innerHTML=[['PARTY HP',party+'%','pass rate across all reviews'],['ACTIVE BOTS',bs.filter(b=>liveStatus(b).status==='running').length+'/'+bs.length,LIVE?'live as of '+clock(LIVE.generated):'snapshot'],['BLOCKED QUESTS',sum('blocked'),'Kanban, all boards'],['TOTAL XP',fmtN(sum('xp')),''],['REACTOR',reactor,g?'decode throughput (5 min) · GPU '+gpu:'not configured']].map(x=>'<div title="'+esc(x[2])+'"><div class="k">'+esc(x[0])+'</div><div class="v">'+esc(x[1])+'</div></div>').join('');
 document.getElementById('stand').textContent=(DATA.demo?'DEMO DATA · ':'')+'as of '+clock(DATA.generated);
 const sourceXp=source=>bs.reduce((total,b)=>total+Number((b.xpBySource||{})[source]||0),0),signed=n=>(n>0?'+':'')+fmtN(n);
 const x=CFG().xp,warnings=[...new Set([...(DATA.warnings||[]),...((LIVE&&LIVE.warnings)||[])])];document.getElementById('foot').textContent='XP: pass '+(x.pass>0?'+':'')+x.pass+' · revise '+(x.revise>0?'+':'')+x.revise+' · fail '+x.fail+' · XP sources (raw): Kanban '+signed(sourceXp('kanban'))+' · reviews '+signed(sourceXp('reviews'))+' · raw source totals may differ from floored XP · level = 1 + floor(sqrt(XP/25)) · HP = pass rate · sub-agents count for the bot that spawned them · collector '+DATA.collectMs+' ms · sources read-only; actions and reviews require confirmation'+(CFG().configError?' · '+CFG().configError:'')+(warnings.length?' · Warnings: '+warnings.join(' · '):'');}
function tab(t){document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('on',x.dataset.tab===t));document.querySelectorAll('.view').forEach(v=>v.classList.toggle('on',v.id===t));if(t==='office')select(sel)}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>tab(b.dataset.tab));
document.querySelectorAll('[data-f]').forEach(b=>b.onclick=()=>{ofilter=b.dataset.f;document.querySelectorAll('[data-f]').forEach(x=>x.classList.toggle('on',x===b));office()});
document.querySelectorAll('th[data-k]').forEach(th=>th.onclick=()=>{bsort=th.dataset.k;document.querySelectorAll('th[data-k]').forEach(x=>x.classList.toggle('on',x===th));board()});
/* ---- blocked cards ---- */
const CAT={you:['Waiting for you','needs your decision, answer, approval or sign-off'],technical:['Technically stuck','worker gave up, timed out or lacks a capability'],stale:['Stale','older than the stale threshold, no clear reason'],unknown:['No reason','blocked without a recorded reason'],upstream:['Waiting upstream','resolves once its parent cards are done']};
let bcat='all',bboard='all',bstale=false,bopen=new Set();
const ALAB={answer:'Answer & unblock',retry:'Retry',comment:'Comment',archive:'Archive'};
const CONFIRM=new Set(['answer','retry','archive']);
const drafts={},pend={},results={},lastRes=[];
let triageSel=[],triagePending=false;
function scopeLabel(){return (bcat==='all'?'all categories':CAT[bcat][0])+' · '+(bboard==='all'?'all boards':bboard)+(bstale?' · older than '+CFG().staleDays+' d':'')}
function pushRes(ok,text){lastRes.unshift({ok,text,t:hm()});lastRes.length=Math.min(lastRes.length,5)}
function actionsHtml(b,key){if(!EMBED)return '<div class="lab">ACTIONS</div><div class="mut">available inside the Hermes desktop app only</div>';
 const acts=b.actions||[];let h='<div class="lab">ACTIONS</div>';
 if(acts.includes('answer')||acts.includes('comment'))h+='<textarea class="ta" data-ta="'+esc(key)+'" rows="3" placeholder="'+(acts.includes('answer')?'answer / decision for the bot …':'comment …')+'"></textarea>';
 h+='<div class="acts">'+acts.map(x=>'<button data-act="'+x+'" data-key="'+esc(key)+'"'+(pend[key]?' disabled':'')+'>'+ALAB[x]+'</button>').join('')+'</div>';
 if(b.remote&&(acts.includes('answer')||acts.includes('retry')))h+='<div class="mut" style="font-size:10px">This bot runs on a remote host – the local dispatcher will not start it after unblocking.</div>';
 if(pend[key])h+='<div class="res">running …</div>';const r=results[key];if(r)h+='<div class="res '+(r.ok?'ok':'bad')+'">'+esc(r.message||r.error)+'</div>';
 return h}
function bindActions(){document.querySelectorAll('[data-ta]').forEach(t=>{t.value=drafts[t.dataset.ta]||'';t.oninput=()=>{drafts[t.dataset.ta]=t.value}});
 document.querySelectorAll('[data-act]').forEach(btn=>btn.onclick=()=>{const key=btn.dataset.key,act=btn.dataset.act,i=key.indexOf('/'),board=key.slice(0,i),id=key.slice(i+1),text=(drafts[key]||'').trim();
  if((act==='answer'||act==='comment')&&text.length<3){results[key]={ok:false,error:'Please enter some text first (at least 3 characters).'};blk();return}
  if(CONFIRM.has(act)&&btn.dataset.armed!=='1'){btn.dataset.armed='1';btn.classList.add('armed');btn.textContent='Confirm: '+ALAB[act]+'?';
   setTimeout(()=>{if(btn.isConnected){btn.dataset.armed='';btn.classList.remove('armed');btn.textContent=ALAB[act]}},6000);return}
  pend[key]=true;delete results[key];blk();submitToHost({pixelhqAction:{board,id,action:act,text}},r=>onActionResult({...r,board,id}))})}
function onActionResult(r){const key=(r.board||'')+'/'+(r.id||'');delete pend[key];results[key]=r;if(r.ok)delete drafts[key];pushRes(!!r.ok,r.message||r.error||'?');blk()}
function blk(){const all=DATA.blockers||[];document.getElementById('blktab').textContent='Blocked ('+all.length+')';
 const cnt=k=>all.filter(b=>k==='all'||b.cat===k).length;
 document.getElementById('bcats').innerHTML=['all',...Object.keys(CAT)].map(k=>'<button class="chip'+(bcat===k?' on':'')+'" data-bc="'+k+'" title="'+(k==='all'?'':esc(CAT[k][1]))+'">'+(k==='all'?'All':esc(CAT[k][0]))+'<span class="n">'+cnt(k)+'</span></button>').join('');
 const boards=[...new Set(all.map(b=>b.board))].sort();
 document.getElementById('bboards').innerHTML=['all',...boards].map(k=>'<button class="'+(bboard===k?'on':'')+'" data-bb="'+esc(k)+'">'+(k==='all'?'all':esc(k))+' <span class="mut">'+all.filter(b=>k==='all'||b.board===k).length+'</span></button>').join('');
 const sb=document.getElementById('bstale');sb.classList.toggle('on',bstale);sb.textContent='older than '+CFG().staleDays+' d only';
 const rows=all.filter(b=>(bcat==='all'||b.cat===bcat)&&(bboard==='all'||b.board===bboard)&&(!bstale||b.stale));
 triageSel=rows.filter(b=>b.cat!=='upstream').map(b=>b.board+'/'+b.id);
 const tb=document.getElementById('btriage');tb.style.display=EMBED?'':'none';tb.disabled=!triageSel.length||triagePending;
 if(tb.dataset.armed!=='1')tb.textContent=triagePending?'Starting triage …':'Triage run → '+CFG().orchestrator+' ('+triageSel.length+' cards)';
 tb.title='Opens a new chat with '+CFG().orchestrator+' that reviews the cards in the current selection (without "waiting upstream") and proposes one decision package. Nothing is changed without your go.';
 document.getElementById('blist').innerHTML=rows.map(b=>{const bot=DATA.bots.find(x=>x.id===b.assignee)||{id:b.assignee,color:'#93A1AF',zone:''};const key=b.board+'/'+b.id;
  const par=b.openParents.length?'<div class="lab">OPEN UPSTREAM CARDS</div>'+b.openParents.map(p=>'<div>'+esc(p.status)+' · '+esc(p.id)+' '+esc(p.title)+'</div>').join(''):'';
  const cm=b.comment?'<div class="lab">LAST COMMENT ('+esc(b.comment.author)+', '+clock(b.comment.ts)+')</div><pre>'+esc(b.comment.text)+'</pre>':'';
  return '<div class="bi c-'+esc(b.cat)+(bopen.has(key)?' open':'')+'" data-k="'+esc(key)+'"><div class="bh"><span><span class="ctag">'+esc(CAT[b.cat][0])+'</span></span><span class="t" title="'+esc(b.title)+'">'+esc(b.title)+'</span>'+
  '<span class="who"><span style="position:relative;display:inline-block">'+sprite(bot,2)+'</span>'+esc(b.assignee)+'</span><span class="'+(b.stale?'old':'mut')+'" style="font-size:11px;text-align:right">'+Number(b.ageDays)+' d</span></div>'+
  '<div class="br"><span class="mut">'+esc(b.board)+' · '+esc(b.id)+(b.kind?' · '+esc(b.kind):'')+' —</span> '+(esc(b.reason)||'<span class="mut">no reason recorded</span>')+'</div>'+
  '<div class="bx">'+par+cm+(b.body?'<div class="lab">TASK (EXCERPT)</div><pre>'+esc(b.body)+'</pre>':'')+actionsHtml(b,key)+'</div></div>'}).join('')||'<div class="mut">no cards in this selection</div>';
 document.querySelectorAll('[data-bc]').forEach(x=>x.onclick=()=>{bcat=x.dataset.bc;blk()});
 document.querySelectorAll('[data-bb]').forEach(x=>x.onclick=()=>{bboard=x.dataset.bb;blk()});
 document.querySelectorAll('.bi .bh').forEach(h=>h.onclick=()=>{const k=h.parentNode.dataset.k;bopen.has(k)?bopen.delete(k):bopen.add(k);h.parentNode.classList.toggle('open')});
 bindActions();
 document.getElementById('bres').innerHTML=lastRes.map(x=>'<div class="res '+(x.ok?'ok':'bad')+'"><span class="mut">'+x.t+'</span> '+esc(x.text)+'</div>').join('');
 if(DATA.boardErrors&&DATA.boardErrors.length)document.getElementById('blist').insertAdjacentHTML('afterbegin','<div class="note" style="color:var(--amber)">Not readable: '+DATA.boardErrors.map(esc).join(', ')+'</div>')}
document.getElementById('bstale').onclick=()=>{bstale=!bstale;blk()};
document.getElementById('btriage').onclick=()=>{const tb=document.getElementById('btriage');if(!triageSel.length||triagePending)return;
 if(tb.dataset.armed!=='1'){tb.dataset.armed='1';tb.classList.add('armed');tb.textContent='Confirm: start triage for '+triageSel.length+' cards?';
  setTimeout(()=>{tb.dataset.armed='';tb.classList.remove('armed');blk()},6000);return}
 tb.dataset.armed='';tb.classList.remove('armed');triagePending=true;blk();
 submitToHost({pixelhqTriage:{keys:triageSel.slice(0,80),scope:scopeLabel()}},r=>{triagePending=false;pushRes(!!r.ok,r.message);blk()})};
/* ---- live ---- */
const SRC={desktop:'desktop',kanban:'kanban',cron:'cron',subagent:'sub',cli:'cli',oneshot:'oneshot',matrix:'matrix',discord:'discord',email:'mail',tool:'tool'};
const dur=s=>s<90?Math.round(s)+' s':s<5400?Math.round(s/60)+' min':Math.round(s/360)/10+' h';
const kt=n=>n>=1e6?(n/1e6).toFixed(1)+'M':n>=1000?Math.round(n/1000)+'k':String(n);
function sessHtml(s,now,sub,agent){const st=s.step?'<div class="st'+(s.stale?' stale':' run')+'" title="'+esc(s.step)+'">'+esc(s.step)+(s.stale?' — no progress for '+dur(now-s.lastAt):'')+'</div>':'<div class="st" style="color:var(--mut)">waiting for the next step</div>';
 const tl=s.tool?'<div class="tl" title="'+esc(s.tool.name+' '+(s.tool.arg||''))+'"><b>'+esc(s.tool.name)+'</b>'+(s.tool.arg?' › '+esc(s.tool.arg):'')+' <span class="mut">('+ago(s.tool.ts)+')</span></div>':'';
 const meta=['for '+dur(now-s.startedAt),s.msgs+' msgs',s.toolCalls+' tools',kt(s.inTok+s.outTok)+' tok',s.cost!=null?s.cost.toLocaleString(CFG().locale,{minimumFractionDigits:2,maximumFractionDigits:2})+' $':null,s.model||null].filter(Boolean).join(' · ');
 return '<div class="ls'+(sub?' sub':'')+'"><div class="t"><span class="src '+(sub?'sub':esc(SRC[s.source]||''))+'">'+(sub?'subagent':esc(SRC[s.source]||s.source))+'</span>'+esc(s.title)+'</div>'+st+tl+'<div class="mt">'+esc(meta)+'</div>'+(!sub&&s.source!=='subagent'?reviewHtml(agent,s.id,s.title):'')+(s.children||[]).map(c=>sessHtml(c,now,true,agent)).join('')+'</div>'}
function taskHtml(t,now){const hb=t.heartbeatAge==null?'no heartbeat':'heartbeat '+dur(t.heartbeatAge)+' ago';const bad=t.heartbeatAge==null||t.heartbeatAge>600;
 return '<div class="ls"><div class="t"><span class="src kanban">kanban</span>'+esc(t.board)+' · '+esc(t.title)+'</div><div class="st'+(bad?' stale':' run')+'">'+esc(hb)+(t.startedAt?' · running for '+dur(now-t.startedAt):'')+'</div><div class="mt">'+esc(t.id)+(t.pid?' · PID '+esc(t.pid):'')+'</div></div>'}
function liveTab(){const tabEl=document.getElementById('livetab');const note=document.getElementById('livenote');
 if(!LIVE){tabEl.textContent='Live';note.style.display='';note.textContent=LIVE_ERR?('Live data unavailable: '+LIVE_ERR):'Loading live data …';document.getElementById('lactive').innerHTML='';document.getElementById('lidle').innerHTML='';return}
 note.style.display=LIVE_ERR?'':'none';if(LIVE_ERR)note.textContent='Last live poll failed: '+LIVE_ERR+' (as of '+clock(LIVE.generated)+')';
 const now=LIVE.generated;const act=[],idle=[];
 DATA.bots.forEach(b=>{const v=liveOf(b.id);if(v&&v.active)act.push([b,v]);else idle.push([b,v])});
 tabEl.textContent='Live ('+act.length+')';
 document.getElementById('lactive').innerHTML=act.map(([b,v])=>'<div class="lc" style="border-left-color:'+safeColor(b.color)+'"><div class="h"><div class="holder">'+sprite(b,4)+'</div><div><div class="nm">'+esc(b.id)+'</div><div class="cl">'+esc(b.title)+' · '+v.sessions.length+' session'+(v.sessions.length===1?'':'s')+(v.tasks.length?' · '+v.tasks.length+' card'+(v.tasks.length===1?'':'s'):'')+'</div></div></div>'+
  v.sessions.map(s=>sessHtml(s,now,false,b.id)).join('')+v.tasks.map(t=>taskHtml(t,now)).join('')+'</div>').join('')||'<div class="mut">no bot is working right now</div>';bindReviews(document.getElementById('lactive'));
 document.getElementById('lidle').innerHTML=idle.map(([b,v])=>{const l=v&&v.last;const z=v&&v.remote?'remote host – Kanban status only':l?'last seen '+ago(l.at)+' · '+(l.title||l.step||l.source):(v&&v.error?'state.db: '+v.error:'no session found');
  return '<div><span class="n">'+esc(b.id)+'</span><span class="z" title="'+esc(z)+'">'+esc(z)+'</span></div>'}).join('')}
function liveRender(){try{hud();office();liveTab()}catch(e){setStand('live render error: '+e)}}
function renderAll(){hud();office();board();blk();liveTab()}
/* Embedded (desktop plugin, sandboxed iframe): data arrives via postMessage from the host, "Reload" asks
   the host. Standalone (dist/pixel-hq.html): the snapshot is embedded at render time. */
const EMBED=window.parent!==window||/[?&]actions=1\b/.test(location.search); /* ?actions=1: show action buttons on the standalone page (demo video) */
function setStand(t){document.getElementById('stand').textContent=t}
window.addEventListener('message',e=>{if(e.source!==window.parent)return;const m=e.data||{};
 if(m.pixelhqActionResult){onActionResult(m.pixelhqActionResult);return}
 if(m.pixelhqReviewResult){onReviewResult(m.pixelhqReviewResult);return}
 if(m.pixelhqLive){LIVE=m.pixelhqLive;LIVE_ERR=null;liveRender();return}
 if(m.pixelhqLiveError){LIVE_ERR=String(m.pixelhqLiveError).slice(0,160);liveTab();return}
 if(m.pixelhqTriageResult){triagePending=false;const r=m.pixelhqTriageResult;pushRes(!!r.ok,r.message||r.error||'?');blk();return}
 if(m.pixelhq&&Array.isArray(m.pixelhq.bots)){DATA=m.pixelhq;try{renderAll();window.parent.postMessage({pixelhqRendered:DATA.bots.length},'*')}catch(err){setStand('render error: '+err);window.parent.postMessage({pixelhqRenderError:String(err)},'*')}}else if(m.pixelhqError){setStand('error: '+String(m.pixelhqError).slice(0,120))}else if(m.pixelhqLoading){setStand('loading …')}});
document.getElementById('reload').onclick=()=>{if(EMBED){setStand('loading …');window.parent.postMessage({pixelhqReload:true},'*')}else location.reload()};
if(DATA&&DATA.live)LIVE=DATA.live;
if(DATA)renderAll();else{setStand(EMBED?'loading …':'no data – run render.py');if(EMBED)window.parent.postMessage({pixelhqReady:true},'*')}
