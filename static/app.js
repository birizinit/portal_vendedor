/* ============================================================
   CORTEX · PAINEL DE VENDAS  — protótipo de front
   Lista e painel consomem a API /api/... (Ploomes + Neppo no backend).
   ============================================================ */

/* ------------------------------------------------------------
   1) DADOS — API backend (Ploomes + Neppo)
   ------------------------------------------------------------ */
let DATA = [];
let state = { activeId: null, mode: "smart", query: "", panelTab: "pedidos", threadView: "conversa", filter: null,
  listOffset: 0, listHasMore: false, listTotal: 0, globalHits: null, goalTarget: null, agentInfo: null,
  hideBot: (()=>{try{return !!localStorage.getItem("cortex-hidebot")}catch(e){return false}})(),
  density: (()=>{try{return localStorage.getItem("cortex-density")||"comfortable"}catch(e){return "comfortable"}})() };
const clientCache = {};
const unread = {};            // {convId: nº de mensagens novas não vistas}
let sseOn = false;

/* ---------- não-lidas (marca/limpa por conversa) ---------- */
function lastSig(c){ const m=(c.messages||[]); return m.length? (m[m.length-1].f+"|"+m[m.length-1].t+"|"+m[m.length-1].h):""; }
async function markSeen(c){
  const sig=lastSig(c);
  try{ localStorage.setItem("cortex-seen-"+c.id, sig); }catch(e){}
  try{
    await fetch(`/api/conversations/${encodeURIComponent(c.id)}/seen`,{
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({sig}),
    });
  }catch(e){}
  if(unread[c.id]){ delete unread[c.id]; updateRailUnread(); renderList(); }
}
function bumpUnread(convId){
  if(convId===state.activeId && state.threadView==="conversa") return;
  unread[convId]=(unread[convId]||0)+1; updateRailUnread(); renderList();
  const c=DATA.find(x=>x.id===convId); if(c) toast(`Nova mensagem · ${c.name}`);
}

/* helpers de exibição */
const esc = s => String(s==null?"":s).replace(/[&<>"]/g, ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[ch]));
const fmtQty = q => { const n=Number(q); return Number.isFinite(n)?(n%1?n.toFixed(2):n):q; };
function fmtDate(d){
  if(!d) return "";
  const s=String(d);
  if(/^\d{2}\/\d{2}/.test(s)) return s;                 // já dd/mm
  const m=s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if(m) return `${m[3]}/${m[2]}/${m[1].slice(2)}`;
  return s.slice(0,16).replace("T"," ");
}
function avatarColor(name){
  let h=0; const s=String(name||"");
  for(let i=0;i<s.length;i++) h=(h*31+s.charCodeAt(i))%360;
  const light=document.documentElement.dataset.theme==="light";
  return `hsl(${h} 42% ${light?"52%":"40%"})`;
}
function countUp(el, to, ms=950){
  if(!el) return; to=Number(to)||0; let start=null;
  function step(t){ if(start==null) start=t; const k=Math.min(1,(t-start)/ms);
    el.textContent=Math.round(to*(1-Math.pow(1-k,3))); if(k<1) requestAnimationFrame(step); }
  requestAnimationFrame(step);
}

/* ícones SVG (substituem emojis — visual profissional) */
const _svg=(p,sz=14)=>`<svg class="ic" width="${sz}" height="${sz}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
const IC={
  user:_svg('<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'),
  tag:_svg('<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><circle cx="7.5" cy="7.5" r="1.2"/>'),
  search:_svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3-3"/>'),
  bot:_svg('<rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V5M9 14h.01M15 14h.01M2 13v2M22 13v2"/>'),
  alert:_svg('<path d="M10.3 3.3 1.8 18a2 2 0 0 0 1.7 3h16.9a2 2 0 0 0 1.7-3L13.7 3.3a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>'),
  rows:_svg('<path d="M3 6h18M3 12h18M3 18h18"/>'),
  star:_svg('<path d="M12 3l2.5 6.5L21 10l-5 4.5L17.5 21 12 17.3 6.5 21 8 14.5 3 10l6.5-.5z"/>'),
  clip:_svg('<path d="M21 8l-9.5 9.5a3.5 3.5 0 0 1-5-5L15 3a2.5 2.5 0 0 1 3.5 3.5L9 16"/>'),
  check:_svg('<path d="M20 6 9 17l-5-5"/>'),
  x:_svg('<path d="M18 6 6 18M6 6l12 12"/>'),
  card:_svg('<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>'),
  chevron:_svg('<path d="m6 9 6 6 6-6"/>',12),
  note:_svg('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M9 13h6M9 17h4"/>'),
  chat:_svg('<path d="M21 11.5a8.5 8.5 0 0 1-12.3 7.6L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5z"/>'),
  mail:_svg('<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m2 6 10 7 10-7"/>'),
  snail:_svg('<circle cx="9" cy="14" r="5"/><path d="M14 14a5 5 0 0 1 5-5V5M9 14h.01M17 5l2-2"/>'),
  spark:_svg('<path d="M12 3l1.9 5.8L20 9l-4.6 3.5L17 18l-5-3.2L7 18l1.6-5.5L4 9l6.1-.2L12 3z"/>'),
  target:_svg('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>'),
};

const URL_DAY = new URLSearchParams(location.search).get("day") || "";
let PILOT_IDS = new Set();
async function loadConversations(append=false){
  if(!append) state.listOffset = 0;
  const q = encodeURIComponent(state.query || "");
  const day = state.day ? `&day=${encodeURIComponent(state.day)}` : "";
  const off = state.listOffset;
  const r = await fetch(`/api/conversations?mode=${state.mode}&q=${q}${day}&offset=${off}&limit=80`);
  if(!r.ok){
    let msg = "Erro ao carregar conversas (" + r.status + ")";
    try{ const j = await r.json(); if(j.detail) msg = j.detail; }catch(_){}
    throw new Error(msg);
  }
  const j = await r.json();
  const items = Array.isArray(j) ? j : (j.items || []);
  DATA = append ? DATA.concat(items) : items;
  state.listHasMore = j.has_more || false;
  state.listTotal = j.total ?? DATA.length;
  state.listOffset = off + items.length;
  DATA.forEach(c=>{
    const ib=c.inbox||{};
    if(ib.unread>0) unread[c.id]=ib.unread;
  });
  if(DATA.length && !DATA.some(c => c.id === state.activeId))
    state.activeId = DATA[0].id;
  updateRailUnread();
  const needle = (state.query || "").trim();
  if(needle.length >= 2){
    try{ state.globalHits = await (await fetch("/api/search?q="+encodeURIComponent(needle))).json(); }
    catch(_){ state.globalHits = null; }
  } else state.globalHits = null;
}

async function loadGoal(){
  try{
    const g = await (await fetch("/api/goals")).json();
    state.goalTarget = g.target;
  }catch(_){ state.goalTarget = null; }
}

function renderGoalBar(){
  const bar = document.getElementById("kpibar");
  if(!bar) return;
  const t = state.goalTarget;
  const lbl = t != null ? Number(t).toLocaleString("pt-BR") : "—";
  bar.innerHTML = `<div class="kstat click" id="goal-edit" tabindex="0" role="button" aria-label="Meta de vendas do mês"><div class="n">${lbl}</div><div class="k">Meta mês (R$)</div></div>`;
  const el = document.getElementById("goal-edit");
  if(!el) return;
  const edit = async ()=>{
    const v = prompt("Meta de vendas (R$) neste mês:", t != null ? String(t) : "");
    if(v === null) return;
    const target = parseFloat(String(v).replace(/\./g,"").replace(",","."));
    if(!Number.isFinite(target) || target < 0){ toast("Valor inválido"); return; }
    const r = await fetch("/api/goals",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({target})});
    if(r.ok){ state.goalTarget = target; renderGoalBar(); toast("Meta salva"); }
    else toast("Falha ao salvar meta");
  };
  el.onclick = edit;
  el.onkeydown = e=>{ if(e.key==="Enter" || e.key===" ") { e.preventDefault(); edit(); } };
}

function announceLive(msg){
  const el = document.getElementById("live-announcer");
  if(el) el.textContent = msg;
}

function notifyDesktop(title, body){
  if(typeof Notification === "undefined" || Notification.permission !== "granted") return;
  try{ new Notification(title, {body: body || "", icon: "/logo.png"}); }catch(_){}
}

const norm = s => s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"");

/* ------------------------------------------------------------
   2) SCORE
   ------------------------------------------------------------ */
const scoreOf = c => Math.max(0, Math.min(100, c.score.reduce((a,b)=>a+b.p,0)));
const scoreClass = v => v>=60 ? "s-hi" : v>=30 ? "s-mid" : "s-lo";
const scoreColor = v => v>=60 ? "var(--accent)" : v>=30 ? "var(--amber)" : "var(--slate)";
const scoreLevel = v => v>=60 ? "Prioridade alta" : v>=30 ? "Prioridade média" : "Prioridade baixa";
const lastSnippet = c => {
  const ib=c.inbox||{};
  const prev=(ib.preview||"").trim();
  if(prev && prev!=="—") return prev;
  const m=c.messages?.[c.messages.length-1];
  if(m && m.t) return (m.f==="out"?"Você: ":"")+m.t;
  if(c.stage) return c.stage;
  if(c.deal_value) return `Negócio · R$ ${c.deal_value}`;
  return "";
};
const lastIntentTag = () => "—";
function fmtDayLabel(iso){
  if(!iso) return "";
  const today=new Date().toISOString().slice(0,10);
  const d=new Date(iso+"T12:00:00");
  const yest=new Date(); yest.setDate(yest.getDate()-1);
  const ys=yest.toISOString().slice(0,10);
  if(iso===today) return "Hoje";
  if(iso===ys) return "Ontem";
  return d.toLocaleDateString("pt-BR",{day:"2-digit",month:"short"});
}
function updateRailUnread(){
  const n=Object.values(unread).reduce((a,b)=>a+(Number(b)||0),0);
  const btn=document.getElementById("rail-inbox");
  if(!btn) return;
  let b=btn.querySelector(".rail-badge");
  if(n>0){
    if(!b){ b=document.createElement("span"); b.className="rail-badge"; btn.appendChild(b); }
    b.textContent=n>9?"9+":n;
  } else if(b) b.remove();
}
/* tags de reserva quando o backend não mandou (mock antigo / sem dados) */
function fallbackTags(c){
  const out=[]; const v=scoreOf(c);
  out.push({l:v>=60?"Prioridade alta":v>=30?"Prioridade média":"Prioridade baixa", k:v>=60?"ok":v>=30?"warn":"info"});
  const it=lastIntentTag(c); if(it && it!=="—") out.push({l:it,k:"stage"});
  return out;
}

/* ------------------------------------------------------------
   5) ESTADO + RENDER
   ------------------------------------------------------------ */

function filtered(){
  let arr = DATA.filter(c=>{
    if(!state.query) return true;
    const q = norm(state.query);
    return norm(c.name).includes(q)||norm(c.contact).includes(q)||c.phone.includes(state.query)||c.cnpj.includes(state.query);
  });
  if(state.filter){
    const f=state.filter;
    arr = arr.filter(c=>{
      if(f.type==="owner") return (c.owner||"")===f.value;
      if(f.type==="tag") return (c.tags||[]).some(t=>t.l===f.value);
      if(f.type==="pred") return f.value==="inativo"?isInativo(c):f.value==="negoc"?inNegoc(c):true;
      return true;
    });
  }
  return arr;
}
function setFilter(type,value){
  state.filter = (state.filter && state.filter.type===type && state.filter.value===value)
    ? null : {type,value};
  renderList();
}
function renderFilterBar(){
  const bar=document.getElementById("filter-bar"); if(!bar) return;
  if(!state.filter){ bar.innerHTML=""; return; }
  const f=state.filter;
  const predLabel={inativo:"Inativos",negoc:"Em negociação"};
  const label = f.type==="pred" ? (predLabel[f.value]||f.value) : f.value;
  const ico = f.type==="owner"?IC.user:f.type==="pred"?IC.search:IC.tag;
  bar.innerHTML=`<span class="fchip">${ico} <b>${esc(label)}</b><button id="fsave" title="Salvar filtro">${IC.star}</button><button id="fx" aria-label="limpar">×</button></span>`;
  document.getElementById("fx").onclick=()=>{ state.filter=null; renderList(); };
  document.getElementById("fsave").onclick=saveCurrentFilter;
}

function renderSearchExtras(){
  const box = document.getElementById("search-extras");
  if(!box) return;
  const msgs = state.globalHits?.messages || [];
  if(!msgs.length){ box.innerHTML = ""; return; }
  box.innerHTML = `<div style="color:var(--faint);margin-bottom:6px;font-size:11px">Mensagens WhatsApp</div>` +
    msgs.slice(0,8).map(m=>`<div class="search-hit" data-phone="${esc(m.phone||"")}"><b>${esc(m.name||m.phone||"—")}</b><br><span style="color:var(--dim)">${esc((m.text||"").slice(0,120))}</span></div>`).join("");
  box.querySelectorAll(".search-hit").forEach(n=>n.onclick=()=>{
    const ph = n.dataset.phone;
    const c = DATA.find(x=>(x.phone||"").replace(/\D/g,"").includes((ph||"").replace(/\D/g,"").slice(-8)));
    if(c){ state.activeId=c.id; renderAll(); }
    else toast("Abra a conversa pelo nome na lista");
  });
}

function renderList(){
  const arr = filtered();
  const dayTxt = URL_DAY ? ` · criados em ${URL_DAY.split("-").reverse().slice(0,2).join("/")}` : "";
  const tot = state.listTotal || arr.length;
  document.getElementById("count").textContent = arr.length + " de " + tot + (tot===1?" conversa":" conversas") + dayTxt;
  renderSearchExtras();
  const moreBtn = document.getElementById("list-more");
  if(moreBtn){
    moreBtn.style.display = state.listHasMore ? "" : "none";
    moreBtn.onclick = async ()=>{ try{ await loadConversations(true); renderList(); }catch(e){ toast("Erro ao carregar"); } };
  }
  const el = document.getElementById("list");
  el.className = "list" + (state.density==="compact"?" compact":"");
  const ownerIco = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>`;
  el.innerHTML = arr.map(c=>{
    const v = scoreOf(c);
    const tags = (c.tags && c.tags.length) ? c.tags : fallbackTags(c);
    const chips = tags.map(t=>`<span class="chip ${t.k||""} flt" data-ft="tag" data-fv="${esc(t.l)}">${esc(t.l)}</span>`).join("");
    const ib=c.inbox||{};
    const sub = lastSnippet(c) || c.stage || "";
    const unN = unread[c.id] || ib.unread || 0;
    const un = unN ? `<span class="unread">${unN}</span>` : "";
    const wait = ib.awaiting ? `<span class="chip wait">Aguardando</span>` : "";
    const pilot = PILOT_IDS.has(c.id) ? `<span class="chip pilot">Piloto</span>` : "";
    return `<div class="conv ${c.id===state.activeId?"on":""} ${ib.awaiting?"awaiting":""}" data-id="${c.id}">
      <div class="row1">
        <span class="name"><span class="cava" style="background:${avatarColor(c.name)}">${esc(c.initials||"?")}</span>${esc(c.name)}</span>
        ${un}<span class="score ${scoreClass(v)}">${v}</span>
      </div>
      ${(chips||wait||pilot)?`<div class="chips">${chips}${wait}${pilot}</div>`:""}
      ${sub?`<div class="snippet">${esc(sub)}</div>`:""}
      <div class="row3">
        ${c.owner?`<span class="owner flt" data-ft="owner" data-fv="${esc(c.owner)}">${ownerIco}<span>${esc(c.owner)}</span></span>`:`<span class="owner"></span>`}
        ${c.deal_value?`<span class="dealval">R$ ${esc(c.deal_value)}</span>`:`<span class="time">${c.messages?.length ? c.messages[c.messages.length-1].h : ""}</span>`}
      </div>
    </div>`;
  }).join("");
  el.querySelectorAll(".conv").forEach(n=>n.onclick=()=>{ state.activeId=n.dataset.id; if(window.innerWidth<=820) document.body.classList.add("show-thread"); renderAll(); });
  el.querySelectorAll(".flt").forEach(n=>n.onclick=e=>{ e.stopPropagation(); setFilter(n.dataset.ft, n.dataset.fv); });
  renderFilterBar();
  updateRailUnread();
}

async function loadAgentInfo(convId){
  if(!convId){ state.agentInfo=null; return; }
  try{
    state.agentInfo = await (await fetch(`/api/conversations/${encodeURIComponent(convId)}/agent`)).json();
  }catch(_){ state.agentInfo=null; }
}

function renderAgentBanner(){
  const box = document.getElementById("agent-banner");
  if(!box) return;
  const c = DATA.find(x=>x.id===state.activeId);
  const info = state.agentInfo;
  if(!c || !info){ box.hidden=true; box.innerHTML=""; return; }
  const p = info.pilot || {};
  const sent = (info.log||[]).filter(x=>x.action==="sent").length;
  const lines = [];
  if(p.human_owned) lines.push("Vendedor assumiu — assistente pausado.");
  else if(p.enabled) lines.push(`Piloto noturno ativo${info.night_active?" agora":" (fora do horário 18:10–07:00)"}.`);
  if(sent) lines.push(`Respostas automáticas nesta conversa: ${sent}.`);
  const admin = ME && ME.role==="admin";
  box.hidden = !lines.length && !admin && !p.enabled;
  if(box.hidden) return;
  box.innerHTML = `
    <div>${lines.map(esc).join(" ")}</div>
    <div class="row">
      ${admin?`<label class="pilot-switch"><input type="checkbox" id="pilot-toggle" ${p.enabled&&!p.human_owned?"checked":""} ${p.human_owned?"disabled":""}> Assistente noturno (piloto)</label>`:""}
      <button type="button" class="btn ghost" id="assume-btn">Assumir conversa</button>
      ${sent?`<button type="button" class="btn ghost" id="agent-log-btn">Ver log IA</button>`:""}
    </div>`;
  document.getElementById("pilot-toggle")?.addEventListener("change", async e=>{
    const on = e.target.checked;
    const r = await fetch(`/api/admin/agent/pilot/${encodeURIComponent(c.id)}`,{
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({enabled: on}),
    });
    if(r.ok){ toast(on?"Piloto ligado":"Piloto desligado"); await loadPilotIds(); await loadAgentInfo(c.id); renderAgentBanner(); renderList(); }
    else toast((await r.json().catch(()=>({}))).detail||"Falha");
  });
  const assumeBtn = document.getElementById("assume-btn");
  if(assumeBtn) assumeBtn.onclick = async ()=>{
    const r = await fetch(`/api/conversations/${encodeURIComponent(c.id)}/assume`,{method:"POST"});
    if(r.ok){ toast("Conversa assumida"); await loadAgentInfo(c.id); renderAgentBanner(); }
    else toast("Falha ao assumir");
  };
  const agentLogBtn = document.getElementById("agent-log-btn");
  if(agentLogBtn) agentLogBtn.onclick = ()=>{
    const txt = (info.log||[]).slice(0,10).map(x=>`${x.at}: [${x.action}] ${x.reply_text||x.detail||""}`).join("\n");
    alert(txt || "Sem registros");
  };
}

function renderThread(){
  stopThreadPoll();
  const c = DATA.find(x=>x.id===state.activeId);
  if(!c){
    document.getElementById("thread-head").innerHTML="";
    document.getElementById("msgs").innerHTML="";
    document.getElementById("sugg-slot").innerHTML="";
    const ab=document.getElementById("agent-banner"); if(ab){ ab.hidden=true; ab.innerHTML=""; }
    return;
  }
  document.getElementById("thread-head").innerHTML = `
    <button class="th-back" id="th-back" aria-label="Voltar">‹</button>
    <div class="ava" style="background:${avatarColor(c.name)};color:#fff">${esc(c.initials)}</div>
    <div>
      <div class="th-name">${esc(c.name)}</div>
      <div class="th-sub">${esc(c.contact)} · ${esc(c.phone||"—")}${c.owner?` · ${IC.user} ${esc(c.owner)}`:""}</div>
      ${(c.inbox&&c.inbox.no_phone)?`<div class="th-warn">${IC.alert} Sem telefone no CRM — WhatsApp pode não funcionar</div>`:""}
    </div>
    <div class="th-actions" style="align-items:center">
      ${state.threadView!=="historico"?`<button class="th-botbtn ${state.hideBot?"on":""}" id="botfilter" title="${state.hideBot?"Mostrar":"Ocultar"} mensagens automáticas">${IC.bot} auto</button>`:""}
      <div class="th-toggle">
        <button data-view="conversa" class="${state.threadView==="historico"?"":"on"}">Conversa</button>
        <button data-view="historico" class="${state.threadView==="historico"?"on":""}">Histórico</button>
      </div>
    </div>`;
  document.querySelectorAll(".th-toggle button").forEach(b=>b.onclick=()=>{
    state.threadView=b.dataset.view; renderThread();
  });
  const back=document.getElementById("th-back");
  if(back) back.onclick=()=>document.body.classList.remove("show-thread");
  const bf=document.getElementById("botfilter");
  if(bf) bf.onclick=()=>{ state.hideBot=!state.hideBot; try{localStorage.setItem("cortex-hidebot",state.hideBot?"1":"")}catch(e){} renderThread(); };
  renderAgentBanner();
  if(state.threadView==="historico"){ renderTimeline(c); document.getElementById("sugg-slot").innerHTML=""; document.getElementById("ai-slot").innerHTML=""; }
  else { loadThreadMessages(c); renderAssist(c); }
}

let threadPollTimer=null;
function stopThreadPoll(){ if(threadPollTimer){ clearInterval(threadPollTimer); threadPollTimer=null; } }

/* mantém mensagens enviadas localmente que o histórico do Neppo ainda não trouxe */
function mergeMessages(server, c){
  const locals=(c.messages||[]).filter(m=>m._local && !server.some(x=>x.t===m.t && x.f===m.f));
  return [...server, ...locals];
}

function warmAiContext(convId){
  if(!AI.available) return;
  fetch(`/api/conversations/${encodeURIComponent(convId)}/ai/warm`,{method:"POST"}).catch(()=>{});
}

async function loadThreadMessages(c){
  const msgs = document.getElementById("msgs");
  if(!(c.messages||[]).length) msgs.innerHTML = skelBubbles();
  else paintMessages(c, true);
  warmAiContext(c.id);
  await refreshMessages(c, false);
  warmAiContext(c.id);
  markSeen(c);
  stopThreadPoll();
  threadPollTimer=setInterval(()=>refreshMessages(c, true), sseOn?30000:15000);  // SSE reduz polling
}

async function refreshMessages(c, silent){
  let real=null;
  try{
    const r = await fetch(`/api/conversations/${encodeURIComponent(c.id)}/messages`);
    if(r.ok) real = await r.json();
  }catch(e){}
  if(real===null) return;
  if(c.id!==state.activeId || state.threadView!=="conversa") return;  // mudou de tela
  const merged = mergeMessages(real, c);
  const changed = JSON.stringify(merged)!==JSON.stringify(c.messages||[]);
  c.messages = merged;
  if(!silent || changed){ paintMessages(c, !silent); markSeen(c); if(silent && changed) renderList(); }
}

function renderBubbles(list){
  const arr = state.hideBot ? list.filter(m=>!(m.bot && m.f==="out")) : list;
  if(!arr.length) return "";
  let lastD="";
  let out="";
  for(const m of arr){
    if(m.d && m.d!==lastD){ lastD=m.d; out+=`<div class="day">${esc(fmtDayLabel(m.d))}</div>`; }
    let inner;
    if(m.media){
      const ct=(m.ct||"").toUpperCase();
      if(ct==="IMAGE") inner=`<img class="media-img" src="${esc(m.media)}" loading="lazy" onclick="window.open(this.src,'_blank')">`;
      else if(ct==="AUDIO") inner=`<audio class="media-audio" controls src="${esc(m.media)}"></audio>`;
      else inner=`<a class="media-doc" href="${esc(m.media)}" target="_blank">${IC.clip} Abrir arquivo</a>`;
      if(m.t && m.t!==m.media) inner+=`<div class="cap">${esc(m.t)}</div>`;
    } else inner=esc(m.t);
    const bot = m.bot && m.f==="out";
    const botTag = bot?`<span class="botmark">${IC.bot} auto</span>`:"";
    const stat = m._local ? `<span class="mstat ${m._status||'sending'}">${m._status==='failed'?IC.x:m._status==='sent'?IC.check:'<span class="sdot"></span>'}</span>` : "";
    out+=`<div class="msg ${m.f==="in"?"in":"out"} ${bot?"botmsg":""}">${inner}<div class="t">${botTag}${m.h||""}${stat}</div></div>`;
  }
  return out;
}
function paintMessages(c, forceScroll){
  const msgs=document.getElementById("msgs"); if(!msgs) return;
  const nearBottom = msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 100;
  const list=c.messages||[];
  const html = renderBubbles(list);
  msgs.innerHTML = html || `<div class="loading">Sem mensagens recentes. Envie a primeira mensagem abaixo.</div>`;
  if(forceScroll || nearBottom) msgs.scrollTop = msgs.scrollHeight;
}

async function renderTimeline(c){
  const msgs = document.getElementById("msgs");
  msgs.innerHTML = noteComposer() + `<div class="loading">Carregando histórico (CRM + WhatsApp)…</div>`;
  wireNoteComposer(c);
  let items=[];
  try{ const r=await fetch(`/api/conversations/${encodeURIComponent(c.id)}/timeline`); if(r.ok) items=await r.json(); }catch(e){}
  const body = items.length ? `<div class="tl">` + items.map(it=>{
    const cls = it.kind==="whatsapp"?"wa":it.kind==="email"?"email":"";
    return `<div class="tlx ${cls}">
      <div class="h"><span class="ti">${esc(it.title||it.kind)}</span><span class="dt">${fmtDate(it.date)}</span></div>
      ${it.content?`<div class="c">${esc(it.content)}</div>`:""}
    </div>`;
  }).join("") + `</div>` : `<div class="loading">Nenhuma interação registrada ainda.</div>`;
  msgs.innerHTML = noteComposer() + body;
  wireNoteComposer(c);
}

function noteComposer(){
  return `<div class="note-add">
    <div class="note-types" id="note-types">
      <button data-tid="1" class="on" title="Anotação">${IC.note}</button>
      <button data-tid="7" title="WhatsApp">${IC.chat}</button>
      <button data-tid="4" title="E-mail">${IC.mail}</button>
    </div>
    <input id="note-text" placeholder="Registrar contato no CRM (ex.: 'cliente vai fechar semana que vem')…" autocomplete="off">
    <button class="btn primary" id="note-save">Registrar</button>
  </div>`;
}
function wireNoteComposer(c){
  const inp=document.getElementById("note-text"), btn=document.getElementById("note-save");
  if(!inp||!btn) return;
  document.querySelectorAll("#note-types button").forEach(b=>b.onclick=()=>{
    document.querySelectorAll("#note-types button").forEach(x=>x.classList.remove("on")); b.classList.add("on");
  });
  const save=async()=>{
    const content=inp.value.trim(); if(!content){ inp.focus(); return; }
    const tid=+(document.querySelector("#note-types button.on")||{dataset:{tid:1}}).dataset.tid;
    btn.disabled=true; btn.textContent="…";
    try{
      const r=await fetch("/api/interactions",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({conversation_id:c.id, type_id:tid, content})});
      const res=await r.json();
      if(r.ok && res.ok){ toast("Interação registrada no CRM"); inp.value=""; renderTimeline(c); }
      else { toast(res.error||res.detail||"Falha ao registrar"); }
    }catch(e){ toast("Erro de rede"); }
    finally{ btn.disabled=false; btn.textContent="Registrar"; }
  };
  btn.onclick=save;
  inp.onkeydown=e=>{ if(e.key==="Enter"){ e.preventDefault(); save(); } };
}

async function renderAssist(c){
  renderAiBar(c);
  const slot = document.getElementById("sugg-slot");
  if(!slot) return;
  slot.innerHTML = `<div class="no-sugg">Carregando sugestão…</div>`;
  let s = null;
  try {
    const r = await fetch(`/api/conversations/${encodeURIComponent(c.id)}/suggestion`);
    const raw = await r.text();
    if(raw && raw !== "null") s = JSON.parse(raw);
  } catch(e) { /* só API */ }
  if(!s){
    slot.innerHTML = `<div class="no-sugg"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/></svg> Intenção não identificada com confiança — sem sugestão automática.</div>`;
    return;
  }
  slot.innerHTML = `
    <div class="sugg">
      <div class="sugg-head">
        <span class="ico"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.8L20 9l-4.6 3.5L17 18l-5-3.2L7 18l1.6-5.5L4 9l6.1-.2L12 3z"/></svg></span>
        <span class="lab">Motor de regras · intenção: <b>${s.intent.label}</b></span>
        <span class="conf">${s.intent.confidence}<span class="bar"><i style="width:${s.intent.conf}%"></i></span></span>
      </div>
      <div class="sugg-body">
        ${s.text}
        <div class="src"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7V4h16v3M9 20h6M12 4v16"/></svg> campos preenchidos com dados do Ploomes + ERP</div>
      </div>
      <div class="sugg-foot">
        <button class="btn primary" id="use"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg> Usar rascunho</button>
        <button class="btn" id="edit">Editar</button>
        <button class="btn ghost" id="ignore">Ignorar</button>
      </div>
    </div>`;
  // >>> API  — aqui, no produto real, você registra o evento de feedback (Camada 4)
  document.getElementById("use").onclick = ()=>{ document.getElementById("input").value=s.text; logFeedback("used",s.intent.id); toast("Rascunho aplicado — revise e envie"); document.getElementById("input").focus(); };
  document.getElementById("edit").onclick = ()=>{ document.getElementById("input").value=s.text; logFeedback("edited",s.intent.id); toast("Rascunho aberto para edição"); document.getElementById("input").focus(); };
  document.getElementById("ignore").onclick = ()=>{ slot.querySelector(".sugg").style.display="none"; logFeedback("ignored",s.intent.id); toast("Sugestão ignorada — sinal registrado"); };
}

function renderPanel(){
  const c = DATA.find(x=>x.id===state.activeId);
  if(!c){ document.getElementById("panel").innerHTML=""; return; }
  const v = scoreOf(c);
  const col = scoreColor(v);
  // cabeçalho com score + esqueleto; os dados ricos chegam em loadClientData
  document.getElementById("panel").innerHTML = `
    <div class="p-title">Cliente 360° · via Ploomes + Sankhya</div>
    <div class="ring-wrap">
      <div class="ring" style="--ring-col:${col};--target:${v*3.6}deg">
        <div class="inner"><span class="num" style="color:${col}">0</span><span class="cap">score</span></div>
      </div>
      <div class="ring-info">
        <div class="lvl">${scoreLevel(v)}</div>
        ${c.owner?`<div class="desc">Vendedor: <b style="color:var(--text)">${esc(c.owner)}</b></div>`:""}
        <div id="p-status"></div>
      </div>
    </div>
    <div class="breakdown">
      <div class="bd-title">Por que esse score</div>
      ${c.score.map(s=>`<div class="bd"><span class="l">${esc(s.l)}</span><span class="v ${s.p<0?"neg":""}">${s.p>=0?"+":"−"}${Math.abs(s.p)}</span></div>`).join("")}
    </div>
    <div class="panel-cta">
      <button class="btn primary" id="cta-quote"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg> Cotação</button>
      <button class="btn" id="cta-order"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg> Pedido</button>
    </div>
    <div class="panel-cta">
      <a class="btn ghost" id="cta-ploomes" href="https://app.ploomes.com/Deals/${encodeURIComponent(c.id)}" target="_blank" rel="noopener">Abrir no CRM</a>
      <button class="btn ghost" id="cta-snooze" type="button">Adiar 2h</button>
    </div>
    ${(c.deals && c.deals.length>1) ? `<div class="deal-ctl deal-pick">
      <select id="deal-sel" title="Este número tem ${c.deals.length} negócios — escolha em qual agir">
        ${c.deals.map(d=>`<option value="${esc(String(d.id))}">${esc(d.title||('#'+d.id))} · ${esc(d.stage||'—')}${d.value?` · R$ ${esc(d.value)}`:''}</option>`).join("")}
      </select>
    </div>` : ""}
    <div class="deal-ctl">
      <select id="stage-sel" title="Mover de estágio"><option>estágio…</option></select>
      <button class="btn ghost" id="assign-btn" title="Trocar vendedor">${IC.user} trocar</button>
    </div>
    <div id="p-kpis"></div>
    <div id="p-commercial"><div class="loading" style="font-size:11px;padding:4px 0 12px">Carregando operação…</div></div>
    <div id="p-insights"></div>
    <div id="p-facts"></div>
    <div class="ptabs" id="p-tabs">
      <button data-tab="pedidos" class="${state.panelTab==="cotacoes"?"":"on"}">Pedidos</button>
      <button data-tab="cotacoes" class="${state.panelTab==="cotacoes"?"on":""}">Cotações</button>
    </div>
    <div id="p-tabcontent">${skelCards(3)}</div>
  `;
  countUp(document.querySelector("#panel .ring .num"), v);
  document.getElementById("cta-quote").onclick = ()=>openDoc("quote", c);
  document.getElementById("cta-order").onclick = ()=>openDoc("order", c);
  const snz=document.getElementById("cta-snooze");
  if(snz) snz.onclick=async()=>{
    try{
      const r=await fetch(`/api/conversations/${encodeURIComponent(c.id)}/snooze`,{
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({hours:2}),
      });
      if(r.ok){ toast("Conversa adiada por 2h"); await loadConversations(); renderList(); }
      else toast("Não foi possível adiar");
    }catch(e){ toast("Erro de rede"); }
  };
  renderDealControls(c);
  const dealSel=document.getElementById("deal-sel");
  if(dealSel){
    dealSel.value = String(curDeal(c).id);
    dealSel.onchange = ()=>{
      DEAL_SEL[c.id]=dealSel.value;
      renderDealControls(c);
      const crm=document.getElementById("cta-ploomes");
      if(crm) crm.href=`https://app.ploomes.com/Deals/${encodeURIComponent(curDeal(c).id)}`;
    };
  }
  document.getElementById("assign-btn").onclick = ()=>openAssign(c);
  document.querySelectorAll("#p-tabs button").forEach(b=>b.onclick=()=>{
    state.panelTab=b.dataset.tab; renderPanel();
  });
  loadClientData(c);
}

async function loadClientData(c){
  // perfil
  fetch(`/api/conversations/${encodeURIComponent(c.id)}/profile`).then(r=>r.ok?r.json():null).then(p=>{
    if(!p || c.id!==state.activeId) return;
    clientCache[c.id]={...(clientCache[c.id]||{}), profile:p};
    renderProfile(p);
  }).catch(()=>{});
  fetch(`/api/conversations/${encodeURIComponent(c.id)}/commercial-stats`).then(r=>r.ok?r.json():null).then(st=>{
    if(!st || c.id!==state.activeId) return;
    clientCache[c.id]={...(clientCache[c.id]||{}), commercial:st};
    renderCommercialStats(st);
  }).catch(()=>{});
  // insights RFM + top produtos (atualiza freq. se o CRM não tiver o campo)
  fetch(`/api/conversations/${encodeURIComponent(c.id)}/insights`).then(r=>r.ok?r.json():null).then(ins=>{
    if(!ins || c.id!==state.activeId) return;
    const prof=clientCache[c.id]?.profile;
    if(prof && prof.buy_frequency_days == null && ins.avg_gap_days > 0){
      prof.buy_frequency_days = ins.avg_gap_days;
      renderProfile(prof);
    }
    renderInsights(ins);
  }).catch(()=>{});
  // aba ativa
  const tab = state.panelTab==="cotacoes" ? "quotes" : "orders";
  const el = document.getElementById("p-tabcontent");
  try{
    const r = await fetch(`/api/conversations/${encodeURIComponent(c.id)}/${tab}`);
    if(c.id!==state.activeId) return;
    const data = r.ok ? await r.json() : [];
    if(tab==="orders") renderOrders(data); else renderQuotes(data);
  }catch(e){ if(el) el.innerHTML=`<div class="loading">Falha ao carregar.</div>`; }
}

function renderCommercialStats(s){
  const el=document.getElementById("p-commercial");
  if(!el) return;
  const n=v=> (v==null?0:v);
  el.innerHTML=`
    <div class="p-title">Operação comercial</div>
    <div class="kpis commercial-kpis">
      <div class="kpi kpi-go"><div class="n">${n(s.orders_open)}</div><div class="k">pedidos em andamento</div></div>
      <div class="kpi kpi-info"><div class="n">${n(s.quotes_open)}</div><div class="k">orçamentos</div></div>
      <div class="kpi kpi-ok"><div class="n">${n(s.orders_done)}</div><div class="k">pedidos concluídos</div></div>
    </div>`;
}

function renderProfile(p){
  const status = p.status || "—";
  const sk = /inativ|bloque|suspens/i.test(status)?"bad":/atend|verific|pend/i.test(status)?"warn":"ok";
  const st = document.getElementById("p-status");
  if(st) st.innerHTML = `<span class="badge ${sk}">${esc(status)}</span>` +
    (p.partner_code?` <span class="badge">Cód. ${esc(p.partner_code)}</span>`:``);
  const freqLbl = p.buy_frequency_days != null ? String(p.buy_frequency_days)
    : (p.buy_frequency_label ? esc(p.buy_frequency_label) : "—");
  const kpis = document.getElementById("p-kpis");
  if(kpis) kpis.innerHTML = `<div class="kpis" style="grid-template-columns:1fr 1fr 1fr">
    <div class="kpi"><div class="n">${p.days_without_purchase??"—"}</div><div class="k">dias sem compra</div></div>
    <div class="kpi"><div class="n">${freqLbl}</div><div class="k">freq. compra (dias)</div></div>
    <div class="kpi"><div class="n" style="font-size:12px">${esc((p.segment||"—").split(" - ").pop())}</div><div class="k">segmento</div></div>
  </div>`;
  const facts=[
    ["CNPJ", p.cnpj], ["Razão social", p.legal_name], ["Cidade", p.city],
    ["E-mail NFe", p.nfe_email], ["Insc. estadual", p.state_registration],
    ["Últ. orçamento", fmtDate(p.last_quote_date)], ["Classif. ICMS", p.icms_class],
    ...(p.fields||[]).map(f=>[f.label,f.value])
  ].filter(x=>x[1]);
  const fe=document.getElementById("p-facts");
  if(fe) fe.innerHTML = `<div class="p-title">Dados do cliente</div><div class="facts">`+
    facts.map(f=>`<div class="fact"><span class="l">${esc(f[0])}</span><span class="v" style="text-align:right;max-width:140px;overflow:hidden;text-overflow:ellipsis">${esc(String(f[1]))}</span></div>`).join("")+`</div>`;
}

function renderInsights(ins){
  const el=document.getElementById("p-insights"); if(!el) return;
  if(!ins || !ins.orders_count){ el.innerHTML=""; return; }
  const rec = ins.recency_days!=null ? (ins.recency_days===0?"hoje":ins.recency_days+"d atrás") : "—";
  const freq = ins.avg_gap_days!=null && ins.avg_gap_days>0 ? `a cada ~${ins.avg_gap_days}d` : "—";
  el.innerHTML = `
    <div class="p-title">Inteligência de compra</div>
    <div class="kpis" style="grid-template-columns:1fr 1fr 1fr">
      <div class="kpi"><div class="n">${esc(ins.ticket_fmt||"—")}</div><div class="k">ticket médio</div></div>
      <div class="kpi"><div class="n" style="font-size:13px">${esc(ins.total_fmt||"—")}</div><div class="k">total (${ins.orders_count}p)</div></div>
      <div class="kpi"><div class="n" style="font-size:13px">${esc(rec)}</div><div class="k">última compra</div></div>
    </div>
    ${ins.top_products && ins.top_products.length ? `
    <div class="toppro">
      <div class="tp-h">Mais comprados · compra ${esc(freq)}</div>
      ${ins.top_products.map(p=>`<div class="tp"><span class="nm">${esc(p.name)}</span><span class="q">${p.qty}× · ${esc(p.total_fmt)}</span></div>`).join("")}
    </div>`:""}
  `;
}

function renderOrders(orders){
  const el=document.getElementById("p-tabcontent"); if(!el) return;
  const open=orders.filter(o=>o.is_open), done=orders.filter(o=>!o.is_open);
  const card=o=>{
    const sk=o.late?"late":o.is_open?"open":"done";
    const sc=o.late?"st-bad":o.is_open?"st-go":"st-ok";
    return `<div class="ocard ${sk}">
      <div class="top"><span class="code">#${esc(o.number||o.id)}</span>
        <span style="display:flex;gap:6px;align-items:center">
          ${o.late?`<span class="stat st-bad">${IC.alert} atrasado ${o.days_late}d</span>`:""}
          <span class="stat ${sc}">${esc(o.status||"—")}</span></span></div>
      <div class="meta">
        ${o.nf?`<span>NF <b>${esc(o.nf)}</b></span>`:""}
        ${o.eta?`<span>entrega <b${o.late?' style="color:var(--bad)"':''}>${esc(o.eta)}</b></span>`:""}
        ${o.date?`<span>data <b>${esc(o.date)}</b></span>`:""}
        ${o.volumes?`<span>vol <b>${o.volumes}</b></span>`:""}
        ${o.freight?`<span>${esc(o.freight)}</span>`:""}
        <span class="val" style="margin-left:auto">R$ ${esc(o.amount_fmt||"0,00")}</span>
      </div>
      ${o.payment?`<div class="paytag">${IC.card} ${esc(o.payment)}</div>`:""}
      ${o.items&&o.items.length?`<div class="toggle" onclick="this.nextElementSibling.classList.toggle('show')">${IC.chevron}${o.items.length} itens</div>
        <div class="items">${o.items.map(i=>`<div class="li"><span class="nm">${esc(i.name||i.code||"")}</span><span>${fmtQty(i.qty)}× · R$ ${esc(i.total||"")}</span></div>`).join("")}</div>`:""}
      ${o.history?`<div class="toggle" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='block'?'none':'block'">${IC.chevron}histórico</div><div class="hist" style="display:none">${esc(o.history)}</div>`:""}
    </div>`;
  };
  el.innerHTML =
    (open.length?`<div class="p-title">Em aberto (${open.length})</div>`+open.map(card).join(""):`<div class="loading">Nenhum pedido em aberto.</div>`)+
    (done.length?`<div class="p-title" style="margin-top:14px">Concluídos (${done.length})</div>`+done.slice(0,6).map(card).join(""):"");
}

function renderQuotes(quotes){
  const el=document.getElementById("p-tabcontent"); if(!el) return;
  if(!quotes.length){ el.innerHTML=`<div class="loading">Nenhuma cotação.</div>`; return; }
  el.innerHTML = `<div class="p-title">Cotações (${quotes.length})</div>` + quotes.map((q,qi)=>{
    const appr=/sim/i.test(q.needs_approval||"");
    return `<div class="ocard ${appr?"open":"done"}">
      <div class="top"><span class="code">#${esc(q.number||q.id)}</span>
        <span class="val">R$ ${esc(q.amount_fmt||"0,00")}</span></div>
      <div class="meta">
        ${q.date?`<span>data <b>${esc(q.date)}</b></span>`:""}
        ${q.eta?`<span>entrega <b>${esc(q.eta)}</b></span>`:""}
        ${q.needs_approval?`<span>aprovação <b>${esc(q.needs_approval)}</b></span>`:""}
        ${q.discount_validator?`<span>${esc(q.discount_validator)}</span>`:""}
      </div>
      ${q.items&&q.items.length?`<div class="toggle" onclick="this.nextElementSibling.classList.toggle('show')">${IC.chevron}${q.items.length} itens</div>
        <div class="items">${q.items.map(i=>`<div class="li"><span class="nm">${esc(i.name||i.code||"")}</span><span>${fmtQty(i.qty)}× · R$ ${esc(i.total||"")}</span></div>`).join("")}</div>`:""}
      ${q.items&&q.items.length?`<button class="btn genorder" data-qi="${qi}" style="height:28px;margin-top:9px;font-size:11.5px">→ Gerar pedido desta cotação</button>`:""}
    </div>`;
  }).join("");
  el.querySelectorAll(".genorder").forEach(b=>b.onclick=()=>openDocFromQuote(quotes[+b.dataset.qi]));
}

function openDocFromQuote(q){
  const c = DATA.find(x=>x.id===state.activeId); if(!c||!q) return;
  openDoc("order", c);
  docState.originQuoteId = q.id;
  docState.lines = (q.items||[]).map(i=>({
    product_id:i.product_id, code:i.code, name:i.name,
    quantity:Number(i.qty)||1, unit_price:Number(i.unit_price)||0
  }));
  document.getElementById("doc-title").textContent = `Pedido da cotação #${q.number||q.id}`;
  renderLines();
}

async function renderAll(){
  renderGoalBar(); renderKpis(); renderList();
  await loadAgentInfo(state.activeId);
  renderThread(); renderPanel();
}

/* ------------------------------------------------------------
   KPIs + dashboards (Funil / Métricas) — calculados de DATA
   ------------------------------------------------------------ */
const parseBRL = s => { if(!s) return 0; const n=parseFloat(String(s).replace(/\./g,"").replace(",",".")); return Number.isFinite(n)?n:0; };
function moneyShort(v){
  if(v>=1e6) return "R$ "+(v/1e6).toFixed(v>=1e7?0:1).replace(".",",")+"M";
  if(v>=1e3) return "R$ "+Math.round(v/1e3)+"k";
  return "R$ "+Math.round(v);
}
const isInativo = c => (c.tags||[]).some(t=>/inativ|sem comprar/i.test(t.l));
const isLead = c => (c.tags||[]).some(t=>/lead/i.test(t.l));
const inNegoc = c => /negocia/i.test(c.stage||"");

function renderKpis(){
  const el=document.getElementById("kpibar"); if(!el) return;
  if(!DATA.length){ el.innerHTML=""; return; }
  const pipeline=DATA.reduce((a,c)=>a+parseBRL(c.deal_value),0);
  const inativos=DATA.filter(isInativo).length;
  const negoc=DATA.filter(inNegoc).length;
  el.innerHTML=`
    <div class="kstat"><div class="n">${moneyShort(pipeline)}</div><div class="k">pipeline</div></div>
    <div class="kstat"><div class="n">${DATA.length}</div><div class="k">em aberto</div></div>
    <div class="kstat click" data-f="inativo"><div class="n" style="color:var(--bad)">${inativos}</div><div class="k">inativos</div></div>
    <div class="kstat click" data-f="negoc"><div class="n" style="color:var(--amber)">${negoc}</div><div class="k">negociação</div></div>`;
  el.querySelector('[data-f="inativo"]').onclick=()=>quickFilter("inativo");
  el.querySelector('[data-f="negoc"]').onclick=()=>quickFilter("negoc");
}
function quickFilter(kind){
  // filtro especial por predicado: usa state.filter com type 'pred'
  state.filter = (state.filter && state.filter.value===kind) ? null : {type:"pred", value:kind};
  renderList();
}

function groupSum(arr, keyfn){
  const m={};
  for(const c of arr){ const k=keyfn(c)||"—"; (m[k]=m[k]||{n:0,val:0}); m[k].n++; m[k].val+=parseBRL(c.deal_value); }
  return Object.entries(m).map(([label,v])=>({label,...v})).sort((a,b)=>b.val-a.val);
}
function barRows(rows, colorClass){
  const max=Math.max(...rows.map(r=>r.val),1);
  setTimeout(()=>document.querySelectorAll(".dbar-fill[data-w]").forEach(e=>{ e.style.width=e.dataset.w; e.removeAttribute("data-w"); }),30);
  return rows.map(r=>`
    <div class="dbar-row">
      <span class="dbar-label">${esc(r.label)}</span>
      <span class="dbar-track"><span class="dbar-fill ${colorClass||''}" style="width:0" data-w="${Math.max(6,r.val/max*100)}%">${r.n} <span class="dbar-n" style="margin-left:5px">cli</span></span></span>
      <span class="dbar-val">${moneyShort(r.val)}</span>
    </div>`).join("");
}
function openDashboard(kind){
  const body=document.getElementById("dash-body");
  const title=document.getElementById("dash-title");
  const pipeline=DATA.reduce((a,c)=>a+parseBRL(c.deal_value),0);
  if(kind==="funil"){
    title.textContent="Funil de vendas";
    const rows=groupSum(DATA, c=>c.stage);
    body.innerHTML=`
      <div class="dash-kpis">
        <div class="kpi"><div class="n">${DATA.length}</div><div class="k">negócios</div></div>
        <div class="kpi"><div class="n" style="font-size:16px">${moneyShort(pipeline)}</div><div class="k">pipeline</div></div>
        <div class="kpi"><div class="n">${rows.length}</div><div class="k">estágios</div></div>
        <div class="kpi"><div class="n" style="font-size:16px">${moneyShort(pipeline/(DATA.length||1))}</div><div class="k">ticket médio</div></div>
      </div>
      <div class="dash-sec">Pipeline por estágio</div>
      ${barRows(rows)}`;
  } else if(kind==="sla"){
    title.textContent="Fila de ação";
    const parado=DATA.filter(c=>(c.tags||[]).some(t=>/parado/i.test(t.l)));
    const inativos=DATA.filter(isInativo);
    const semVend=DATA.filter(c=>!c.owner);
    const grupo=(titulo,arr,cor)=>arr.length?`<div class="dash-sec">${titulo} (${arr.length})</div>`+
      arr.slice(0,15).map(c=>`<div class="sla-row" data-id="${esc(c.id)}"><span class="dbar-label">${esc(c.name)}</span><span class="sla-meta">${esc((c.tags||[]).map(t=>t.l).join(" · "))}</span><span class="dbar-val">${c.deal_value?"R$ "+esc(c.deal_value):""}</span></div>`).join(""):"";
    body.innerHTML=`
      <div class="dash-kpis">
        <div class="kpi"><div class="n" style="color:var(--amber)">${parado.length}</div><div class="k">parados</div></div>
        <div class="kpi"><div class="n" style="color:var(--bad)">${inativos.length}</div><div class="k">inativos</div></div>
        <div class="kpi"><div class="n">${semVend.length}</div><div class="k">sem vendedor</div></div>
        <div class="kpi"><div class="n">${DATA.length}</div><div class="k">total</div></div>
      </div>
      ${grupo(IC.snail+" Parados no estágio",parado)}
      ${grupo(IC.alert+" Inativos / sem comprar",inativos)}
      ${grupo(IC.user+" Sem vendedor",semVend)}
      ${(!parado.length&&!inativos.length&&!semVend.length)?`<div class="loading">${IC.check} Nada na fila de ação.</div>`:""}`;
    body.querySelectorAll(".sla-row").forEach(n=>n.onclick=()=>{ state.activeId=n.dataset.id; closeDash(); renderAll(); });
    document.getElementById("dash-overlay").classList.add("show");
    return;
  } else {
    title.textContent="Métricas por vendedor";
    const rows=groupSum(DATA, c=>c.owner||"Sem vendedor");
    const inativos=DATA.filter(isInativo).length, leads=DATA.filter(isLead).length, negoc=DATA.filter(inNegoc).length;
    body.innerHTML=`
      <div class="dash-kpis">
        <div class="kpi"><div class="n">${rows.length}</div><div class="k">vendedores</div></div>
        <div class="kpi"><div class="n" style="color:var(--info)">${leads}</div><div class="k">leads</div></div>
        <div class="kpi"><div class="n" style="color:var(--amber)">${negoc}</div><div class="k">em negociação</div></div>
        <div class="kpi"><div class="n" style="color:var(--bad)">${inativos}</div><div class="k">inativos</div></div>
      </div>
      <div class="dash-sec">Carteira por vendedor</div>
      ${barRows(rows,"slate")}`;
  }
  document.getElementById("dash-overlay").classList.add("show");
}
function closeDash(){
  document.getElementById("dash-overlay").classList.remove("show");
  document.querySelectorAll(".rail-btn").forEach(x=>x.classList.remove("on"));
  const conv=[...document.querySelectorAll(".rail-btn[title]")].find(b=>b.getAttribute("title")==="Conversas");
  if(conv) conv.classList.add("on");
}
document.getElementById("dash-close").onclick=closeDash;
document.getElementById("dash-overlay").addEventListener("click",e=>{ if(e.target.id==="dash-overlay") closeDash(); });

/* ------------------------------------------------------------
   Mover estágio / atribuir vendedor (write no Ploomes)
   ------------------------------------------------------------ */
let STAGES=null, USERS=null;
const DEAL_SEL={};   // conv.id -> negócio selecionado (quando o número tem vários)
async function getStages(){ if(!STAGES){ try{STAGES=await (await fetch("/api/stages")).json()}catch(e){STAGES=[]} } return STAGES; }
async function getUsers(){ if(!USERS){ try{USERS=await (await fetch("/api/users")).json()}catch(e){USERS=[]} } return USERS; }

/* negócio "ativo" do card. Um número pode ter vários negócios (c.deals);
   se nenhum estiver selecionado, usa o primário (deals[0] == o próprio card). */
function curDeal(c){
  const deals=c.deals||[];
  if(!deals.length) return {id:c.id, title:c.name, stage:c.stage,
                            stage_id:c.stage_id, pipeline_id:c.pipeline_id,
                            value:c.deal_value, owner:c.owner};
  const sel=DEAL_SEL[c.id];
  return deals.find(d=>String(d.id)===String(sel)) || deals[0];
}

async function renderDealControls(c){
  const sel=document.getElementById("stage-sel"); if(!sel) return;
  const all=await getStages();
  if(c.id!==state.activeId) return;
  const d=curDeal(c);
  const stages=all.filter(s=>!d.pipeline_id || s.pipeline===d.pipeline_id);
  sel.innerHTML = stages.length
    ? stages.map(s=>`<option value="${s.id}" ${s.id===d.stage_id?"selected":""}>${esc(s.name)}</option>`).join("")
    : `<option>${esc(d.stage||"—")}</option>`;
  async function moveStage(sid, withUndo){
    const prev=d.stage_id, prevName=d.stage;
    try{
      const r=await fetch(`/api/deals/${encodeURIComponent(d.id)}/stage`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({stage_id:sid})});
      if(r.ok){ const st=stages.find(x=>x.id===sid); d.stage_id=sid; if(st) d.stage=st.name;
        if(String(d.id)===String(c.id)){ c.stage_id=sid; if(st) c.stage=st.name; }
        renderList();
        if(withUndo && prev) toastAction("Estágio atualizado","Desfazer",()=>{ d.stage=prevName; moveStage(prev,false); renderDealControls(c); });
        else toast("Estágio atualizado");
      } else { const e=await r.json().catch(()=>({})); toast(e.detail||"Falha ao mover"); sel.value=d.stage_id; }
    }catch(e){ toast("Erro de rede"); }
  }
  sel.onchange=()=>moveStage(+sel.value, true);
}

let assignConv=null;
async function openAssign(c){
  assignConv=c;
  document.getElementById("assign-overlay").classList.add("show");
  document.getElementById("assign-search").value="";
  const list=document.getElementById("assign-list");
  list.innerHTML=`<div class="pr">Carregando vendedores…</div>`;
  const users=await getUsers();
  paintAssign(users.slice(0,40));
  document.getElementById("assign-search").oninput=e=>{
    const q=norm(e.target.value);
    paintAssign(q?users.filter(u=>norm(u.name).includes(q)).slice(0,40):users.slice(0,40));
  };
}
function paintAssign(users){
  const list=document.getElementById("assign-list");
  list.innerHTML = users.length ? users.map(u=>`<div class="pr" data-id="${u.id}"><span>${esc(u.name)}</span></div>`).join("") : `<div class="pr">Nada encontrado</div>`;
  list.querySelectorAll(".pr[data-id]").forEach(n=>n.onclick=async()=>{
    const oid=+n.dataset.id, c=assignConv, d=curDeal(c);
    try{
      const r=await fetch(`/api/deals/${encodeURIComponent(d.id)}/owner`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({owner_id:oid})});
      if(r.ok){ d.owner=n.textContent.trim(); if(String(d.id)===String(c.id)) c.owner=d.owner; toast("Vendedor atribuído"); document.getElementById("assign-overlay").classList.remove("show"); renderAll(); }
      else toast("Falha ao atribuir");
    }catch(e){ toast("Erro de rede"); }
  });
}

/* ------------------------------------------------------------
   Tela de Templates editáveis
   ------------------------------------------------------------ */
async function openTemplates(){
  const body=document.getElementById("tpl-body");
  body.innerHTML=`<div class="loading">Carregando templates…</div>`;
  document.getElementById("tpl-overlay").classList.add("show");
  let data={templates:[],placeholders:[]};
  try{ const r=await fetch("/api/templates"); if(r.ok) data=await r.json(); }catch(e){}
  body.innerHTML = `
    <div class="tpl-help">Use marcadores entre chaves — eles são preenchidos com os dados do cliente:
      ${data.placeholders.map(p=>`<code>{${p}}</code>`).join(" ")}</div>` +
    data.templates.map(t=>`
      <div class="tpl-item" data-id="${t.id}">
        <div class="tpl-h"><b>${esc(t.label)}</b>${t.customized?`<span class="chip ok">personalizado</span>`:""}</div>
        <textarea class="tpl-ta" rows="3">${esc(t.text)}</textarea>
        <div class="tpl-actions">
          <button class="btn ghost tpl-reset" data-id="${t.id}">Restaurar padrão</button>
          <button class="btn primary tpl-save" data-id="${t.id}">Salvar</button>
        </div>
      </div>`).join("");
  body.querySelectorAll(".tpl-save").forEach(b=>b.onclick=()=>saveTemplate(b.dataset.id, false));
  body.querySelectorAll(".tpl-reset").forEach(b=>b.onclick=()=>saveTemplate(b.dataset.id, true));
}
async function saveTemplate(id, reset){
  const item=document.querySelector(`.tpl-item[data-id="${id}"]`);
  const ta=item.querySelector(".tpl-ta");
  const text = reset ? "" : ta.value;
  try{
    const r=await fetch("/api/templates",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({intent_id:id, text})});
    if(r.ok){ toast(reset?"Template restaurado ao padrão":"Template salvo"); openTemplates(); }
    else toast("Falha ao salvar");
  }catch(e){ toast("Erro de rede"); }
}
document.getElementById("tpl-close").onclick=()=>document.getElementById("tpl-overlay").classList.remove("show");
document.getElementById("tpl-overlay").addEventListener("click",e=>{ if(e.target.id==="tpl-overlay") e.currentTarget.classList.remove("show"); });

/* ------------------------------------------------------------
   6) EVENTOS
   ------------------------------------------------------------ */
async function send(){
  const inp = document.getElementById("input");
  const txt = inp.value.trim();
  if(!txt || !state.activeId) return;
  const c = DATA.find(x=>x.id===state.activeId);
  const h = new Date().toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"});
  const msg={f:"out", t:txt, h, _local:true, _status:"sending"};
  if(c){ c.messages=(c.messages||[]); c.messages.push(msg); paintMessages(c, true); }
  inp.value=""; inp.style.height="auto";
  try {
    const r = await fetch("/api/send", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({conversation_id: state.activeId, text: txt})
    });
    if(!r.ok){ const e = await r.json().catch(()=>({})); msg._status="failed"; toast(e.detail || "Falha ao enviar"); }
    else { msg._status="sent"; renderList(); }
  } catch(e) {
    msg._status="failed"; toast("Erro de rede ao enviar");
  }
  if(c && state.activeId===c.id && state.threadView==="conversa") paintMessages(c, false);
}
document.getElementById("send").onclick = send;
document.getElementById("input").addEventListener("keydown", e=>{
  if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); send(); }
});
document.getElementById("input").addEventListener("input", e=>{
  e.target.style.height="auto"; e.target.style.height=Math.min(120,e.target.scrollHeight)+"px";
});
let searchTimer;
document.getElementById("q").addEventListener("input", e=>{
  state.query=e.target.value;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async ()=>{ try{ await loadConversations(false); renderList(); }catch(err){ toast("Erro na busca"); } }, 300);
});
document.getElementById("seg-smart").onclick = ()=>setMode("smart");
document.getElementById("seg-chrono").onclick = ()=>setMode("chrono");
async function setMode(m){
  state.mode=m;
  document.getElementById("seg-smart").classList.toggle("on", m==="smart");
  document.getElementById("seg-chrono").classList.toggle("on", m==="chrono");
  const ab=document.getElementById("action-btn");
  if(ab) ab.classList.toggle("on", m==="action");
  try{ await loadConversations(); renderAll(); }catch(e){ toast("Erro ao carregar"); }
}

function skelLines(n){ return Array.from({length:n},(_,i)=>`<div class="skel skel-row" style="width:${[80,65,90,55,72,60][i%6]}%"></div>`).join(""); }
function skelCards(n){ return Array.from({length:n},()=>`<div class="skel skel-card"></div>`).join(""); }
function skelBubbles(){ return `<div class="skel skel-bubble"></div><div class="skel skel-bubble out"></div><div class="skel skel-bubble" style="width:52%"></div><div class="skel skel-bubble out" style="width:40%"></div>`; }
let toastActTimer;
function toastAction(msg,label,fn){
  const t=document.getElementById("toast"); clearTimeout(toastTimer);
  t.innerHTML=`${esc(msg)} <button class="tact">${esc(label)}</button>`;
  const b=t.querySelector(".tact"); b.onclick=()=>{ fn(); t.classList.remove("show"); };
  t.classList.add("show"); clearTimeout(toastActTimer);
  toastActTimer=setTimeout(()=>t.classList.remove("show"),6000);
}
let toastTimer;
function toast(msg){
  const t=document.getElementById("toast");
  t.innerHTML=`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg> ${msg}`;
  t.classList.add("show"); clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>t.classList.remove("show"),2200);
}
const feedback=[];
function logFeedback(action,intentId){
  feedback.push({action,intentId,at:new Date().toISOString()});
  fetch("/api/feedback", {
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({action, intent_id: intentId, conversation_id: state.activeId})
  }).catch(()=>{});
}

/* ------------------------------------------------------------
   7) MODAL — nova cotação / pedido (preview dry-run -> confirma)
   ------------------------------------------------------------ */
let docState = { kind:"quote", conv:null, lines:[] };

function openDoc(kind, conv){
  docState = { kind, conv, lines:[], originQuoteId:null };
  document.getElementById("doc-title").textContent = kind==="order"?"Novo pedido":"Nova cotação";
  document.querySelectorAll("#doc-kind button").forEach(b=>b.classList.toggle("on", b.dataset.kind===kind));
  document.getElementById("doc-client").value = `${conv.name} · ${conv.contact||""}`;
  document.getElementById("doc-prod").value="";
  document.getElementById("doc-prodres").classList.remove("show");
  document.getElementById("doc-notes").value="";
  document.getElementById("doc-preview").style.display="none";
  document.getElementById("doc-confirm").style.display="none";
  document.getElementById("doc-preview-btn").style.display="";
  renderLines();
  document.getElementById("overlay").classList.add("show");
}
function closeDoc(){ document.getElementById("overlay").classList.remove("show"); }

function renderLines(){
  const el=document.getElementById("doc-lines");
  el.innerHTML = docState.lines.length ? docState.lines.map((l,i)=>`
    <div class="line">
      <span class="nm">${esc(l.name||"")}<small>${esc(l.code||"")}</small></span>
      <input type="number" min="1" value="${l.quantity}" data-i="${i}" data-f="quantity">
      <input type="number" step="0.01" value="${l.unit_price}" data-i="${i}" data-f="unit_price">
      <span class="lt">R$ ${money(l.quantity*l.unit_price)}</span>
      <button class="rm" data-i="${i}" title="Remover">×</button>
    </div>`).join("") : `<div class="loading">Adicione produtos pela busca acima.</div>`;
  el.querySelectorAll("input").forEach(inp=>inp.oninput=()=>{
    const l=docState.lines[+inp.dataset.i]; l[inp.dataset.f]=parseFloat(inp.value)||0; updateTotal();
    inp.closest(".line").querySelector(".lt").textContent="R$ "+money(l.quantity*l.unit_price);
  });
  el.querySelectorAll(".rm").forEach(b=>b.onclick=()=>{ docState.lines.splice(+b.dataset.i,1); renderLines(); });
  updateTotal();
}
const money = n => (Number(n)||0).toLocaleString("pt-BR",{minimumFractionDigits:2,maximumFractionDigits:2});
function updateTotal(){
  const t=docState.lines.reduce((a,l)=>a+(l.quantity*l.unit_price),0);
  document.getElementById("doc-total").textContent="R$ "+money(t);
}

let prodTimer;
document.getElementById("doc-prod").addEventListener("input", e=>{
  const q=e.target.value.trim();
  clearTimeout(prodTimer);
  const box=document.getElementById("doc-prodres");
  if(q.length<2){ box.classList.remove("show"); return; }
  prodTimer=setTimeout(async ()=>{
    try{
      const r=await fetch(`/api/products?q=${encodeURIComponent(q)}`);
      const rows=r.ok?await r.json():[];
      if(!rows.length){ box.innerHTML=`<div class="pr">Nada encontrado</div>`; box.classList.add("show"); return; }
      box.innerHTML=rows.map(p=>`<div class="pr" data-p='${esc(JSON.stringify(p))}'>
        <span>${esc(p.name||"")}<span class="c"> ${esc(p.code||"")}</span></span>
        <span class="c">${p.stock!=null?p.stock+" un":""}</span></div>`).join("");
      box.classList.add("show");
      box.querySelectorAll(".pr[data-p]").forEach(n=>n.onclick=()=>{
        const p=JSON.parse(n.dataset.p);
        docState.lines.push({product_id:p.id, code:p.code, name:p.name, quantity:1, unit_price:p.price||0});
        box.classList.remove("show"); document.getElementById("doc-prod").value=""; renderLines();
      });
    }catch(err){}
  }, 280);
});

document.getElementById("doc-kind").addEventListener("click", e=>{
  const b=e.target.closest("button[data-kind]"); if(!b) return;
  docState.kind=b.dataset.kind;
  document.querySelectorAll("#doc-kind button").forEach(x=>x.classList.toggle("on",x===b));
  document.getElementById("doc-title").textContent=docState.kind==="order"?"Novo pedido":"Nova cotação";
});

function docPayload(dry){
  return { conversation_id:docState.conv.id, kind:docState.kind, dry_run:dry,
    notes:document.getElementById("doc-notes").value,
    origin_quote_id:docState.originQuoteId||null,
    items:docState.lines.map(l=>({product_id:l.product_id,code:l.code,name:l.name,quantity:l.quantity,unit_price:l.unit_price})) };
}

document.getElementById("doc-preview-btn").onclick = async ()=>{
  if(!docState.lines.length){ toast("Adicione ao menos um item"); return; }
  try{
    const r=await fetch("/api/documents",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(docPayload(true))});
    const p=await r.json();
    if(!r.ok){ toast(p.detail||"Falha no preview"); return; }
    const box=document.getElementById("doc-preview");
    box.style.display="block";
    box.innerHTML=`<div class="warn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 9v4M12 17h.01M10.3 3.3 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.3a2 2 0 0 0-3.4 0z"/></svg>${esc(p.warning)}</div>
      <div><b>${docState.kind==="order"?"Pedido":"Cotação"}</b> para <b>${esc(p.contact.name)}</b> · ${p.items.length} itens · total <b>R$ ${esc(p.total_fmt)}</b></div>`;
    document.getElementById("doc-confirm").style.display="";
    toast("Pré-visualização gerada — nada foi gravado ainda");
  }catch(e){ toast("Erro de rede no preview"); }
};

document.getElementById("doc-confirm").onclick = async ()=>{
  const btn=document.getElementById("doc-confirm"); btn.disabled=true; btn.textContent="Criando…";
  try{
    const r=await fetch("/api/documents",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(docPayload(false))});
    const res=await r.json();
    if(r.ok && res.ok){ toast(`${docState.kind==="order"?"Pedido":"Cotação"} criado no Ploomes (#${res.id||"?"})`); closeDoc(); renderPanel(); }
    else { toast(res.error||res.detail||"Falha ao criar"); }
  }catch(e){ toast("Erro de rede ao criar"); }
  finally{ btn.disabled=false; btn.textContent="Confirmar e criar"; }
};
document.getElementById("doc-close").onclick=closeDoc;
document.getElementById("doc-cancel").onclick=closeDoc;
document.getElementById("overlay").addEventListener("click", e=>{ if(e.target.id==="overlay") closeDoc(); });

/* ------------------------------------------------------------
   8) RAIL — navegação lateral (botões antes inertes)
   ------------------------------------------------------------ */
document.querySelectorAll(".rail-btn[title]:not(#theme-toggle)").forEach(b=>{
  b.onclick=()=>{
    document.querySelectorAll(".rail-btn").forEach(x=>x.classList.remove("on"));
    b.classList.add("on");
    const t=b.getAttribute("title");
    if(t==="Funil") openDashboard("funil");
    else if(t==="Métricas") openDashboard("metricas");
    else if(t==="Templates") openTemplates();
    else if(t==="Alertas") openAlerts();
    else if(t!=="Conversas") toast(`${t} — em breve`);
  };
});

/* ---------- tema claro / escuro ---------- */
const SUN=`<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`;
const MOON=`<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>`;
function applyTheme(t){
  document.documentElement.dataset.theme=t;
  try{ localStorage.setItem("cortex-theme", t); }catch(e){}
  const btn=document.getElementById("theme-toggle");
  if(btn) btn.innerHTML = t==="light" ? MOON : SUN;   // mostra o que vai ativar
}
(function(){
  const cur=document.documentElement.dataset.theme || "dark";
  applyTheme(cur);
  document.getElementById("theme-toggle").onclick=()=>{
    applyTheme((document.documentElement.dataset.theme==="light")?"dark":"light");
  };
})();

/* ---------- barra de ferramentas: data, densidade, ação, filtros salvos ---------- */
state.day = URL_DAY;
function initTools(){
  const dp=document.getElementById("day-picker");
  if(dp){ dp.value=state.day||""; dp.onchange=async()=>{ state.day=dp.value; try{ await loadConversations(); renderAll(); }catch(e){ toast("Erro ao filtrar"); } }; }
  const db=document.getElementById("density-btn");
  if(db) db.onclick=()=>{ state.density=state.density==="compact"?"comfortable":"compact"; try{localStorage.setItem("cortex-density",state.density)}catch(e){} renderList(); };
  const ab=document.getElementById("action-btn");
  if(ab){
    ab.classList.toggle("on", state.mode==="action");
    ab.onclick=async()=>{ await setMode(state.mode==="action"?"smart":"action"); };
  }
  renderSavedFilters();
}
/* filtros salvos (localStorage) */
function loadSaved(){ try{ return JSON.parse(localStorage.getItem("cortex-saved-filters")||"[]"); }catch(e){ return []; } }
function saveCurrentFilter(){
  if(!state.filter) return;
  const f={...state.filter}; const all=loadSaved();
  if(!all.some(x=>x.type===f.type&&x.value===f.value)){ all.push(f); try{localStorage.setItem("cortex-saved-filters",JSON.stringify(all))}catch(e){} renderSavedFilters(); toast("Filtro salvo"); }
}
function renderSavedFilters(){
  const el=document.getElementById("saved-filters"); if(!el) return;
  const all=loadSaved();
  const predLabel={inativo:"Inativos",negoc:"Em negociação"};
  el.innerHTML = all.map((f,i)=>{
    const lbl=f.type==="pred"?(predLabel[f.value]||f.value):f.value;
    return `<span class="savedf" data-i="${i}">${f.type==="owner"?IC.user:f.type==="pred"?IC.search:IC.tag} ${esc(lbl)}<b data-del="${i}">×</b></span>`;
  }).join("");
  el.querySelectorAll(".savedf").forEach(n=>n.onclick=e=>{
    if(e.target.dataset.del!=null){ const all=loadSaved(); all.splice(+e.target.dataset.del,1); try{localStorage.setItem("cortex-saved-filters",JSON.stringify(all))}catch(_){} renderSavedFilters(); return; }
    state.filter=all[+n.dataset.i]; renderList();
  });
}

/* ---------- atalhos de teclado ---------- */
document.addEventListener("keydown", e=>{
  const tag=(e.target.tagName||"").toLowerCase();
  const typing = tag==="input"||tag==="textarea"||tag==="select";
  if(e.key==="Escape"){ document.querySelectorAll(".overlay.show").forEach(o=>o.classList.remove("show")); return; }
  if(e.key==="/" && !typing){ e.preventDefault(); document.getElementById("q").focus(); return; }
  if(typing) return;
  if(e.key==="ArrowDown"||e.key==="ArrowUp"){
    e.preventDefault();
    const arr=filtered(); if(!arr.length) return;
    let idx=arr.findIndex(c=>c.id===state.activeId);
    idx = e.key==="ArrowDown" ? Math.min(arr.length-1,idx+1) : Math.max(0,idx-1);
    state.activeId=arr[idx].id; renderAll();
    const node=document.querySelector(`.conv[data-id="${CSS.escape(arr[idx].id)}"]`); if(node) node.scrollIntoView({block:"nearest"});
  }
});

/* ---------- tempo real (SSE) ---------- */
function findConvByContact(phone, name){
  const np=(phone||"").replace(/\D/g,""), nn=norm(name||"");
  return DATA.find(c=> (np && (c.phone||"").replace(/\D/g,"").includes(np.slice(-8)))
    || (nn.length>2 && (norm(c.contact||"").includes(nn)||norm(c.name||"").includes(nn))) );
}
let listRefreshTimer = null;
function scheduleListRefresh(){
  if(listRefreshTimer) clearTimeout(listRefreshTimer);
  listRefreshTimer = setTimeout(async ()=>{
    listRefreshTimer = null;
    const keepId = state.activeId;
    try{
      await loadConversations(false);
      if(keepId && DATA.some(c=>c.id===keepId)) state.activeId = keepId;
      renderList();
    }catch(_){}
  }, 600);
}
function initSSE(){
  if(!window.EventSource) return;
  try{
    const es=new EventSource("/api/stream");
    es.onopen=()=>{ sseOn=true; };
    es.onerror=()=>{ sseOn=false; };
    es.onmessage=(e)=>{
      let ev; try{ ev=JSON.parse(e.data); }catch(_){ return; }
      if(!ev) return;
      if(ev.type==="agent"){
        if(document.getElementById("night-overlay")?.classList.contains("show")) renderNightTower();
        if(ev.conv_id===state.activeId){
          loadAgentInfo(state.activeId).then(()=>renderAgentBanner());
          if(ev.action==="sent" && state.threadView==="conversa"){
            const c=DATA.find(x=>x.id===state.activeId);
            if(c) refreshMessages(c, true);
          }
        }
        announceLive(`IA: ${ev.action||""} ${ev.name||""}`.trim());
        return;
      }
      if(ev.type!=="message") return;
      const m=findConvByContact(ev.phone, ev.name);
      if(m){
        if(m.id===state.activeId && state.threadView==="conversa") refreshMessages(m, true);
        else bumpUnread(m.id);
      }
      scheduleListRefresh();
      refreshAlertsBadgeThrottled();
      const title = ev.name || (m && m.name) || "Cliente";
      const body = (ev.text || "").slice(0, 140);
      announceLive("Nova mensagem de " + title);
      if(document.hidden) notifyDesktop(title, body);
    };
  }catch(e){}
}

document.getElementById("assign-close").onclick=()=>document.getElementById("assign-overlay").classList.remove("show");
document.getElementById("assign-overlay").addEventListener("click",e=>{ if(e.target.id==="assign-overlay") e.currentTarget.classList.remove("show"); });

/* ------------------------------------------------------------
   Copiloto de IA (OpenRouter)
   ------------------------------------------------------------ */
let AI={available:false};
function renderAiBar(c){
  const slot=document.getElementById("ai-slot"); if(!slot) return;
  if(!AI.available){ slot.innerHTML=""; return; }
  slot.innerHTML=`<div class="ai-bar">
    <button class="ai-btn" data-ai="summary">${IC.spark} Resumir</button>
    <button class="ai-btn" data-ai="reply">${IC.chat} Rascunhar</button>
    <button class="ai-btn" data-ai="next-action">${IC.target} Próxima ação</button>
    <button class="ai-btn" data-ai="sentiment">${IC.spark} Análise</button>
  </div><div id="ai-result"></div>`;
  slot.querySelectorAll(".ai-btn").forEach(b=>b.onclick=()=>aiAction(c, b.dataset.ai, b));
}
function sentiBadges(s){
  const cls=(v,good,bad)=> v===good?"ok":v===bad?"bad":"warn";
  return `<span class="senti chip ${cls(s.sentiment,'positivo','negativo')}">${esc(s.sentiment)}</span>
    <span class="senti chip ${cls(s.buying_signal,'alto','baixo')}">compra: ${esc(s.buying_signal)}</span>
    <span class="senti chip ${cls(s.churn_risk,'baixo','alto')}">churn: ${esc(s.churn_risk)}</span>`;
}
async function aiAction(c, kind, btn){
  const res=document.getElementById("ai-result");
  const orig=btn.innerHTML; btn.disabled=true; btn.innerHTML=`${IC.spark} …`;
  if(res) res.innerHTML=`<div class="ai-card"><div class="loading" style="padding:10px 0">Consultando CRM e IA…</div></div>`;
  try{
    const isGet = kind==="sentiment";
    const url=`/api/conversations/${encodeURIComponent(c.id)}/ai/${kind}`;
    const r=await fetch(url, isGet?{}:{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({instruction:""})});
    const j=await r.json().catch(()=>({}));
    if(!r.ok){ toast(j.detail||"IA indisponível"); return; }
    if(kind==="reply"){
      const inp=document.getElementById("input"); inp.value=j.text||""; inp.style.height="auto"; inp.style.height=Math.min(120,inp.scrollHeight)+"px"; inp.focus();
      toast("Rascunho da IA aplicado — revise e envie"); if(res) res.innerHTML="";
    } else if(kind==="sentiment"){
      if(!j){ toast("Sem análise"); return; }
      res.innerHTML=`<div class="ai-card"><div class="ai-h">${IC.spark} Análise da conversa · IA<button class="ai-x">×</button></div><div style="margin-bottom:7px">${sentiBadges(j)}</div>${esc(j.note||"")}</div>`;
      res.querySelector(".ai-x").onclick=()=>res.innerHTML="";
    } else {
      const title = kind==="summary"?"Resumo da conversa":"Próxima melhor ação";
      res.innerHTML=`<div class="ai-card"><div class="ai-h">${IC.spark} ${esc(title)} · IA<button class="ai-x">×</button></div>${esc(j.text||"")}<div class="ai-acts"><button class="btn" id="ai-toreply">${IC.chat} Rascunhar resposta</button></div></div>`;
      res.querySelector(".ai-x").onclick=()=>res.innerHTML="";
      document.getElementById("ai-toreply").onclick=()=>aiAction(c,"reply",btn);
    }
  }catch(e){ toast("Erro de rede na IA"); }
  finally{ btn.disabled=false; btn.innerHTML=orig; }
}

/* ------------------------------------------------------------
   Conta do usuário + módulo Admin
   ------------------------------------------------------------ */
let ME=null;
function initials2(name){ const p=String(name||"").trim().split(/\s+/); return ((p[0]||"?")[0]+(p.length>1?p[p.length-1][0]:"")).toUpperCase(); }

async function loadPilotIds(){
  if(!ME || ME.role!=="admin"){ PILOT_IDS=new Set(); return; }
  try{
    const j = await (await fetch("/api/admin/agent/pilot")).json();
    PILOT_IDS = new Set((j.pilots||[]).filter(p=>p.enabled).map(p=>p.conv_id));
  }catch(_){ PILOT_IDS=new Set(); }
}

async function loadMe(){
  try{ ME=await (await fetch("/api/me")).json(); }catch(e){ ME=null; }
  const me=document.getElementById("me-btn");
  if(me) me.textContent=initials2(ME&&ME.name);
  const ab=document.getElementById("rail-admin");
  if(ab) ab.style.display = (ME&&ME.role==="admin")?"grid":"none";
  const rn=document.getElementById("rail-night");
  if(rn) rn.style.display = (ME&&ME.role==="admin")?"grid":"none";
  await loadPilotIds();
}
document.getElementById("me-btn").onclick=(e)=>{
  e.stopPropagation();
  const m=document.getElementById("usermenu");
  document.getElementById("um-name").textContent=ME&&ME.name||"—";
  document.getElementById("um-role").textContent=ME&&ME.role==="admin"?"Administrador":"Vendedor";
  m.classList.toggle("show");
};
document.addEventListener("click",()=>document.getElementById("usermenu").classList.remove("show"));
document.getElementById("um-logout").onclick=async()=>{ await fetch("/api/logout",{method:"POST"}); location.href="/login"; };
document.getElementById("um-pwd").onclick=async()=>{
  const p=prompt("Nova senha:"); if(!p) return;
  const r=await fetch("/api/password",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({password:p})});
  toast(r.ok?"Senha alterada":"Falha ao alterar");
};
document.getElementById("rail-admin").onclick=()=>{ if(ME&&ME.role==="admin") openAdmin(); };

async function renderNightTower(){
  const body=document.getElementById("night-body");
  if(!body) return;
  try{
    const j=await (await fetch("/api/admin/agent/tower")).json();
    const st=j.night_active?'<span class="pill" style="color:var(--accent)">Noite ativa</span>':'<span class="pill">Fora do horário</span>';
    const logs=(j.logs||[]).slice(0,40).map(x=>`
      <div class="tower-row">
        <b>${esc(x.conv_id)} · ${esc(x.action)}</b>
        <div>${esc(x.reply_text||x.detail||"")}</div>
        <div class="meta">${esc(x.at||"")}</div>
      </div>`).join("")||'<div class="alert-empty">Nenhum evento ainda.</div>';
    body.innerHTML=`<div style="margin-bottom:12px">${st} · ${(j.pilots||[]).length} conversa(s) no piloto</div>${logs}`;
  }catch(e){ body.innerHTML='<div class="alert-empty">Erro ao carregar</div>'; }
}
async function openNightTower(){
  document.getElementById("night-overlay")?.classList.add("show");
  document.querySelectorAll(".rail-btn").forEach(x=>x.classList.remove("on"));
  document.getElementById("rail-night")?.classList.add("on");
  await renderNightTower();
}
document.getElementById("rail-night")?.addEventListener("click", openNightTower);
const nightClose = document.getElementById("night-close");
if(nightClose) nightClose.onclick = ()=>{
  document.getElementById("night-overlay")?.classList.remove("show");
  railReset();
};
document.getElementById("night-overlay")?.addEventListener("click",e=>{
  if(e.target.id==="night-overlay"){ e.currentTarget.classList.remove("show"); railReset(); }
});

let adminTab="visao";
function openAdmin(){ document.getElementById("admin-overlay").classList.add("show"); adminTab="visao"; document.querySelectorAll("#admin-tabs button").forEach(b=>b.classList.toggle("on",b.dataset.at==="visao")); renderAdmin(); }
document.getElementById("admin-close").onclick=()=>document.getElementById("admin-overlay").classList.remove("show");
document.getElementById("admin-overlay").addEventListener("click",e=>{ if(e.target.id==="admin-overlay") e.currentTarget.classList.remove("show"); });
document.querySelectorAll("#admin-tabs button").forEach(b=>b.onclick=()=>{ adminTab=b.dataset.at; document.querySelectorAll("#admin-tabs button").forEach(x=>x.classList.toggle("on",x===b)); renderAdmin(); });

async function renderAdmin(){
  const body=document.getElementById("admin-body");
  body.innerHTML=`<div class="loading">Carregando…</div>`;
  if(adminTab==="visao" || adminTab==="vendedores"){
    let m={}; try{ m=await (await fetch("/api/admin/metrics")).json(); }catch(e){}
    if(adminTab==="visao"){
      const maxS=Math.max(...(m.by_stage||[]).map(r=>r.value),1);
      body.innerHTML=`
        <div class="dash-kpis">
          <div class="kpi"><div class="n">${m.deals||0}</div><div class="k">negócios (amostra)</div></div>
          <div class="kpi"><div class="n" style="font-size:16px">${moneyShort(m.pipeline||0)}</div><div class="k">pipeline</div></div>
          <div class="kpi"><div class="n">${m.sellers||0}</div><div class="k">vendedores ativos</div></div>
          <div class="kpi"><div class="n" style="color:var(--bad)">${m.inativos||0}</div><div class="k">inativos</div></div>
        </div>
        <div class="dash-sec">Pipeline por estágio</div>
        ${(m.by_stage||[]).map(r=>`<div class="dbar-row"><span class="dbar-label">${esc(r.label)}</span><span class="dbar-track"><span class="dbar-fill" style="width:${Math.max(6,r.value/maxS*100)}%">${r.n}</span></span><span class="dbar-val">${moneyShort(r.value)}</span></div>`).join("")}`;
    } else {
      body.innerHTML=`<div class="dash-sec">Carteira por vendedor</div>
        <div class="sla-row" style="font-weight:700;color:var(--faint);font-size:11px;text-transform:uppercase"><span>Vendedor</span><span>Negócios</span><span>Leads</span><span>Inativos</span><span class="dbar-val">Pipeline</span></div>
        ${(m.by_seller||[]).map(r=>`<div class="sla-row adm5"><span class="dbar-label">${esc(r.label)}</span><span>${r.n}</span><span>${r.leads||0}</span><span style="color:${r.inativos?'var(--bad)':'inherit'}">${r.inativos||0}</span><span class="dbar-val">${moneyShort(r.value)}</span></div>`).join("")}`;
    }
  } else if(adminTab==="usuarios"){
    let users=[]; try{ users=await (await fetch("/api/admin/users")).json(); }catch(e){}
    body.innerHTML=`
      <div class="dash-sec">Novo acesso</div>
      <div class="newuser">
        <input id="nu-name" placeholder="Nome"><input id="nu-email" placeholder="E-mail" type="email">
        <input id="nu-pwd" placeholder="Senha" type="text">
        <select id="nu-role"><option value="seller">Vendedor</option><option value="admin">Admin</option></select>
        <input id="nu-owner" placeholder="ID Ploomes (vendedor)" style="display:none">
        <button class="btn primary" id="nu-add">Criar</button>
      </div>
      <div class="nu-hint" id="nu-ownerwrap" style="display:none">Vincule ao vendedor do Ploomes para a carteira: <a href="#" id="nu-pick">escolher da lista</a></div>
      <div class="dash-sec" style="margin-top:18px">Usuários (${users.length})</div>
      ${users.map(u=>`<div class="urow ${u.active===0?"off":""}">
        <span class="un">${esc(u.name||"")} <i>${esc(u.email)}</i></span>
        <span class="chip ${u.role==="admin"?"value":"stage"}">${u.role}</span>
        <span class="uid">${u.owner_id?"#"+u.owner_id:""}</span>
        <button class="btn ghost ua-toggle" data-id="${u.id}" data-active="${u.active}">${u.active===0?"Ativar":"Desativar"}</button>
      </div>`).join("")}`;
    body.querySelectorAll(".ua-toggle").forEach(b=>b.onclick=async()=>{
      const r=await fetch(`/api/admin/users/${b.dataset.id}/active`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({active:b.dataset.active==="0"})});
      if(r.ok){ toast("Acesso atualizado"); renderAdmin(); } else { const e=await r.json().catch(()=>({})); toast(e.detail||"Falha"); }
    });
    const roleSel=document.getElementById("nu-role"), ownerInp=document.getElementById("nu-owner"), ownerWrap=document.getElementById("nu-ownerwrap");
    roleSel.onchange=()=>{ const s=roleSel.value==="seller"; ownerInp.style.display=s?"":"none"; ownerWrap.style.display=s?"":"none"; };
    ownerInp.style.display=""; ownerWrap.style.display="";
    document.getElementById("nu-pick").onclick=async(e)=>{ e.preventDefault(); openAssignPicker(id=>{ ownerInp.value=id; }); };
    document.getElementById("nu-add").onclick=async()=>{
      const gv=id=>document.getElementById(id).value;
      const body={name:gv("nu-name").trim(),email:gv("nu-email").trim(),password:gv("nu-pwd"),role:roleSel.value,owner_id:ownerInp.value?+ownerInp.value:null};
      if(!body.name||!body.email||!body.password){ toast("Preencha nome, e-mail e senha"); return; }
      const r=await fetch("/api/admin/users",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
      if(r.ok){ toast("Acesso criado"); renderAdmin(); } else { const e=await r.json().catch(()=>({})); toast(e.detail||"Falha"); }
    };
  } else if(adminTab==="whatsapp"){
    let st={}; try{ st=await (await fetch("/api/admin/backfill/status")).json(); }catch(e){}
    body.innerHTML=`
      <div class="dash-sec">Histórico de WhatsApp no banco</div>
      <div class="dash-kpis" style="grid-template-columns:1fr 1fr"><div class="kpi"><div class="n">${(st.total_in_db||0).toLocaleString("pt-BR")}</div><div class="k">mensagens salvas</div></div><div class="kpi"><div class="n" style="font-size:12px">${esc(st.last||"—")}</div><div class="k">último backfill</div></div></div>
      <p style="font-size:12.5px;color:var(--dim);line-height:1.6;margin-bottom:14px">O backfill varre o histórico da Neppo e grava no banco — depois as conversas abrem na hora e ficam pesquisáveis. Rode aos poucos (cada página ≈ 100 msgs). A captura em tempo real via webhook já grava as novas automaticamente.</p>
      <div style="display:flex;gap:8px;align-items:center">
        <input id="bf-pages" type="number" value="200" style="width:120px;height:36px;background:var(--surface-2);border:1px solid var(--border);border-radius:8px;color:var(--text);padding:0 10px">
        <span style="font-size:12px;color:var(--faint)">páginas</span>
        <button class="btn primary" id="bf-run">Rodar backfill</button>
        <button class="btn" id="bf-refresh">Atualizar status</button>
      </div>`;
    document.getElementById("bf-run").onclick=async()=>{
      const p=+document.getElementById("bf-pages").value||200;
      const r=await fetch("/api/admin/backfill?pages="+p,{method:"POST"});
      if(!r.ok){ toast("Falha ao iniciar"); return; }
      toast("Backfill rodando…");
      // progresso ao vivo: atualiza o contador por ~40s
      let ticks=0; const iv=setInterval(async()=>{
        if(adminTab!=="whatsapp" || !document.getElementById("admin-overlay").classList.contains("show")){ clearInterval(iv); return; }
        try{ const st=await (await fetch("/api/admin/backfill/status")).json();
          const el=document.querySelector("#admin-body .kpi .n"); if(el) el.textContent=(st.total_in_db||0).toLocaleString("pt-BR"); }catch(e){}
        if(++ticks>20) clearInterval(iv);
      },2000);
    };
    document.getElementById("bf-refresh").onclick=renderAdmin;
  }
}
/* seletor de vendedor reutilizável p/ vincular owner_id */
function openAssignPicker(cb){
  assignConv=null;
  document.getElementById("assign-overlay").classList.add("show");
  document.getElementById("assign-search").value="";
  getUsers().then(users=>{
    const paint=(list)=>{ const el=document.getElementById("assign-list"); el.innerHTML=list.map(u=>`<div class="pr" data-id="${u.id}"><span>${esc(u.name)} <span style="color:var(--faint)">#${u.id}</span></span></div>`).join(""); el.querySelectorAll(".pr[data-id]").forEach(n=>n.onclick=()=>{ cb(+n.dataset.id); document.getElementById("assign-overlay").classList.remove("show"); }); };
    paint(users.slice(0,40));
    document.getElementById("assign-search").oninput=e=>{ const q=norm(e.target.value); paint(q?users.filter(u=>norm(u.name).includes(q)).slice(0,40):users.slice(0,40)); };
  });
}

/* ---------- alertas proativos ---------- */
let ALERTS_CACHE=[], alertFilter="", _lastAlertRefresh=0;
const ALERT_KIND_LABEL={sla:"SLA",reactivation:"Reativar",stale_deal:"Parado"};
async function fetchAlerts(){
  try{
    const r = await fetch("/api/alerts");
    const j = await r.json();
    if(j.from_cache !== false) return j;
    return j;
  }catch(e){ return {alerts:[],count:0,by_kind:{}}; }
}
function setAlertsBadge(n){ const b=document.getElementById("alerts-badge"); if(!b) return; if(n>0){ b.textContent=n>99?"99+":n; b.style.display=""; } else b.style.display="none"; }
async function refreshAlertsBadge(){ const r=await fetchAlerts(); ALERTS_CACHE=r.alerts||[]; _lastAlertRefresh=Date.now(); setAlertsBadge(r.count||0); }
function refreshAlertsBadgeThrottled(){ if(Date.now()-_lastAlertRefresh>20000) refreshAlertsBadge(); }
function railReset(){ document.querySelectorAll(".rail-btn").forEach(x=>x.classList.remove("on")); const ib=document.getElementById("rail-inbox"); if(ib) ib.classList.add("on"); }
function renderAlerts(){
  const body=document.getElementById("alerts-body");
  const by=ALERTS_CACHE.reduce((m,a)=>(m[a.kind]=(m[a.kind]||0)+1,m),{});
  let list=alertFilter?ALERTS_CACHE.filter(a=>a.kind===alertFilter):ALERTS_CACHE;
  const chip=(k,lbl)=>`<button class="btn ${alertFilter===k?"primary":"ghost"}" data-af="${k}">${lbl}${by[k]?` (${by[k]})`:""}</button>`;
  const filters=`<div class="alert-filters">
    <button class="btn ${alertFilter===""?"primary":"ghost"}" data-af="">Todos (${ALERTS_CACHE.length})</button>
    ${chip("sla","Aguardando")}${chip("reactivation","Reativar")}${chip("stale_deal","Parado")}</div>`;
  const rows=list.length?list.map(a=>`
    <div class="alert-row" data-id="${esc(a.conv_id)}">
      <span class="alert-dot ${a.severity}"></span>
      <div class="alert-main">
        <div class="alert-name">${esc(a.name||"—")}</div>
        <div class="alert-title">${esc(a.title||"")}</div>
        ${a.detail?`<div class="alert-detail">${esc(a.detail)}</div>`:""}
      </div>
      <div class="alert-actions">
        <button type="button" class="btn ghost" data-act="open">Abrir</button>
        <button type="button" class="btn ghost" data-act="snooze">Adiar 2h</button>
        <button type="button" class="btn ghost" data-act="tpl">Sugerir</button>
      </div>
      <span class="alert-kind">${esc(ALERT_KIND_LABEL[a.kind]||a.kind)}</span>
    </div>`).join(""):`<div class="alert-empty">Nada pendente por aqui. 👏</div>`;
  body.innerHTML=filters+rows;
  body.querySelectorAll(".alert-filters .btn").forEach(b=>b.onclick=()=>{ alertFilter=b.dataset.af; renderAlerts(); });
  body.querySelectorAll(".alert-row").forEach(row=>{
    const id = row.dataset.id;
    row.querySelector('[data-act="open"]')?.addEventListener("click", e=>{ e.stopPropagation(); openAlertConv(id); });
    row.querySelector('[data-act="snooze"]')?.addEventListener("click", async e=>{
      e.stopPropagation();
      await fetch(`/api/conversations/${encodeURIComponent(id)}/snooze`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({hours:2})});
      toast("Adiado por 2h"); await refreshAlertsBadge(); renderAlerts();
    });
    row.querySelector('[data-act="tpl"]')?.addEventListener("click", e=>{
      e.stopPropagation(); openAlertConv(id); setTimeout(()=>document.querySelector(".sugg-use")?.click(), 400);
    });
    row.addEventListener("click", ()=>openAlertConv(id));
  });
}
async function openAlerts(){
  document.getElementById("alerts-overlay").classList.add("show");
  document.getElementById("alerts-body").innerHTML='<div class="alert-empty">Carregando…</div>';
  await refreshAlertsBadge(); renderAlerts();
}
async function openAlertConv(id){
  document.getElementById("alerts-overlay").classList.remove("show"); railReset();
  if(!DATA.some(c=>c.id===id)){ try{ await loadConversations(); }catch(e){} }
  state.activeId=id;
  if(window.innerWidth<=820) document.body.classList.add("show-thread");
  renderAll();
}
document.getElementById("alerts-close").onclick=()=>{ document.getElementById("alerts-overlay").classList.remove("show"); railReset(); };
document.getElementById("alerts-overlay").addEventListener("click",e=>{ if(e.target.id==="alerts-overlay"){ e.currentTarget.classList.remove("show"); railReset(); } });

document.getElementById("um-report")?.addEventListener("click", ()=>{
  window.location.href = "/api/reports/weekly?format=csv";
  document.getElementById("usermenu")?.classList.remove("show");
});

/* ---------- Carteira (portfolio) ---------- */
let PF = { stats: null, filter: "has_phone", q: "", offset: 0, total: 0, items: [], templates: [] };

async function loadPfStats(){
  const r = await fetch("/api/portfolio/stats");
  if(!r.ok) throw new Error("Erro ao carregar carteira");
  const j = await r.json();
  PF.stats = j.stats;
  const sync = j.sync || {};
  const el = document.getElementById("pf-sync-label");
  if(el){
    if(sync.status === "running") el.textContent = `Sincronizando… ${sync.synced||0}/${sync.total||"?"}`;
    else if(sync.finished_at) el.textContent = sync.message || `${PF.stats?.total||0} clientes`;
    else el.textContent = "Clique em Atualizar para importar do Ploomes";
  }
  document.getElementById("pf-campaign-btn").disabled = !(PF.stats?.total > 0);
}

function renderPfDash(){
  const s = PF.stats || {};
  const chips = [
    ["", "Total", s.total],
    ["has_phone", "Com WhatsApp", s.with_phone],
    ["open_quote", "Orç. aberto", s.open_quote],
    ["no_purchase_7", "7+ dias", s.no_purchase_7],
    ["no_purchase_30", "30+ dias", s.no_purchase_30],
    ["no_purchase_60", "60+ dias", s.no_purchase_60],
  ];
  document.getElementById("pf-dash").innerHTML = chips.map(([k,lbl,n])=>
    `<div class="pf-kpi ${PF.filter===k?"on":""}" data-pf="${esc(k)}"><div class="n">${(n??0).toLocaleString("pt-BR")}</div><div class="k">${esc(lbl)}</div></div>`
  ).join("");
  document.getElementById("pf-dash").querySelectorAll(".pf-kpi").forEach(el=>{
    el.onclick = ()=>{ PF.filter = el.dataset.pf; document.getElementById("pf-filter").value = PF.filter; PF.offset=0; loadPfList(false); };
  });
}

async function loadPfList(append){
  if(!append) PF.offset = 0;
  const q = encodeURIComponent(PF.q||"");
  const f = encodeURIComponent(PF.filter||"");
  const r = await fetch(`/api/portfolio/contacts?filter=${f}&q=${q}&offset=${PF.offset}&limit=80`);
  if(!r.ok){ toast("Erro na lista da carteira"); return; }
  const j = await r.json();
  const items = j.items || [];
  PF.items = append ? PF.items.concat(items) : items;
  PF.total = j.total || 0;
  PF.offset += items.length;
  document.getElementById("pf-count").textContent =
    `${PF.items.length} de ${PF.total.toLocaleString("pt-BR")} clientes`;
  const more = document.getElementById("pf-more");
  more.style.display = PF.offset < PF.total ? "block" : "none";
  more.onclick = ()=>loadPfList(true);
  const tb = document.getElementById("pf-tbody");
  const rows = (append ? items : PF.items).map(row=>{
    const tags = (row.tags||[]).map(t=>`<span class="chip ${t.k||""}">${esc(t.l)}</span>`).join("");
    const dias = row.days_without_purchase != null ? `${row.days_without_purchase}d` : "—";
    const orc = row.open_quotes > 0 ? `${row.open_quotes} (${moneyShort(row.open_quotes_value||0)})` : "—";
    return `<tr data-cid="${row.contact_id}">
      <td><div class="pf-name">${esc(row.name||"—")}</div><div style="color:var(--faint);font-size:11px">${esc(row.company||row.segment||"")}</div></td>
      <td>${esc(row.phone||"—")}</td>
      <td>${esc(dias)}</td>
      <td>${esc(orc)}</td>
      <td><div class="pf-tags">${tags||"—"}</div></td>
      <td><button type="button" class="btn ghost pf-open" style="height:28px;font-size:11px">Inbox</button></td>
    </tr>`;
  }).join("");
  if(append) tb.innerHTML += rows;
  else tb.innerHTML = rows;
  tb.querySelectorAll(".pf-open").forEach(btn=>{
    btn.onclick = ()=>{
      const tr = btn.closest("tr");
      const cid = tr?.dataset.cid;
      const row = PF.items.find(x=>String(x.contact_id)===String(cid));
      if(row) openPortfolioInbox(row);
    };
  });
}

function openPortfolioInbox(row){
  document.body.classList.remove("view-portfolio");
  railReset();
  const tail = (row.phone||"").replace(/\D/g,"").slice(-8);
  let c = DATA.find(x=>(x.phone||"").replace(/\D/g,"").includes(tail));
  if(!c && tail) c = DATA.find(x=>x.id===`wa_${tail}`);
  if(c){ state.activeId=c.id; if(window.innerWidth<=820) document.body.classList.add("show-thread"); renderAll(); }
  else toast("Conversa não encontrada — sincronize o inbox ou aguarde mensagem do cliente");
}

async function openPortfolio(){
  document.body.classList.add("view-portfolio");
  document.querySelectorAll(".rail-btn").forEach(x=>x.classList.remove("on"));
  document.getElementById("rail-portfolio")?.classList.add("on");
  PF.filter = document.getElementById("pf-filter").value || "has_phone";
  try{
    await loadPfStats();
    renderPfDash();
    await loadPfList(false);
  }catch(e){ toast(e.message||"Erro na carteira"); }
}

function showInboxView(){
  document.body.classList.remove("view-portfolio");
  railReset();
}

async function pfSync(){
  const btn = document.getElementById("pf-sync-btn");
  btn.disabled = true;
  try{
    const r = await fetch("/api/portfolio/sync",{method:"POST"});
    const j = await r.json().catch(()=>({}));
    toast(j.message||"Sincronização iniciada");
    const poll = setInterval(async ()=>{
      await loadPfStats();
      renderPfDash();
      const j = await (await fetch("/api/portfolio/stats")).json();
      const sync = j.sync;
      if(sync?.status !== "running"){
        clearInterval(poll);
        await loadPfList(false);
        btn.disabled = false;
        toast(sync?.message || "Carteira atualizada");
      }
    }, 2500);
    setTimeout(()=>{ clearInterval(poll); btn.disabled=false; }, 120000);
  }catch(e){ btn.disabled=false; toast("Falha ao sincronizar"); }
}

async function openPfCampaign(){
  if(!PF.templates.length){
    try{ PF.templates = (await (await fetch("/api/portfolio/templates")).json()).templates||[]; }catch(_){}
  }
  const sel = document.getElementById("pf-template");
  sel.innerHTML = PF.templates.map(t=>`<option value="${esc(t.id)}">${esc(t.title)}</option>`).join("");
  document.getElementById("pf-campaign-overlay").classList.add("show");
  await refreshPfPreview();
  sel.onchange = refreshPfPreview;
}

async function refreshPfPreview(){
  const tid = document.getElementById("pf-template").value;
  const r = await fetch("/api/portfolio/campaigns/preview",{
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ filter: PF.filter||"", template_id: tid, limit: 500 }),
  });
  const j = await r.json().catch(()=>({}));
  const prev = document.getElementById("pf-preview");
  if(!r.ok){ prev.textContent = j.detail||"Erro"; return; }
  const sample = (j.samples||[])[0];
  prev.innerHTML = `<div style="margin-bottom:8px;color:var(--dim)">Alcance: <b>${j.with_phone||0}</b> com telefone (máx. ${j.will_send||0} por campanha)</div>`
    + (sample ? `<div><b>${esc(sample.name)}</b> — ${esc(sample.phone)}</div><div style="margin-top:8px">${esc(sample.message)}</div>` : "");
}

document.getElementById("rail-portfolio")?.addEventListener("click", openPortfolio);
document.getElementById("rail-inbox")?.addEventListener("click", showInboxView);
document.getElementById("pf-sync-btn")?.addEventListener("click", pfSync);
document.getElementById("pf-campaign-btn")?.addEventListener("click", openPfCampaign);
const pfCampClose = document.getElementById("pf-campaign-close");
if(pfCampClose) pfCampClose.onclick = ()=>document.getElementById("pf-campaign-overlay").classList.remove("show");
document.getElementById("pf-campaign-overlay")?.addEventListener("click", e=>{
  if(e.target.id==="pf-campaign-overlay") e.currentTarget.classList.remove("show");
});
const pfCampGo = document.getElementById("pf-campaign-go");
if(pfCampGo) pfCampGo.onclick = async ()=>{
  const tid = document.getElementById("pf-template").value;
  const r = await fetch("/api/portfolio/campaigns",{
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ filter: PF.filter||"", template_id: tid, confirm: true, limit: 500 }),
  });
  const j = await r.json().catch(()=>({}));
  if(r.ok){ toast(j.message||"Campanha na fila"); document.getElementById("pf-campaign-overlay").classList.remove("show"); }
  else toast(j.detail||"Falha");
};
document.getElementById("pf-q")?.addEventListener("input", e=>{
  PF.q = e.target.value;
  clearTimeout(window._pfSearchT);
  window._pfSearchT = setTimeout(()=>loadPfList(false), 350);
});
const pfFilterEl = document.getElementById("pf-filter");
if(pfFilterEl) pfFilterEl.onchange = e=>{ PF.filter = e.target.value; PF.offset=0; loadPfList(false); };

async function boot(){
  try {
    if(typeof Notification !== "undefined" && Notification.permission === "default")
      Notification.requestPermission().catch(()=>{});
    await loadMe();
    try{ AI=await (await fetch("/api/ai/status")).json(); }catch(_){ AI={available:false}; }
    await loadGoal();
    await loadConversations(false);
    await renderAll();
    renderGoalBar();
    initTools();
    initSSE();
    refreshAlertsBadge();
    setInterval(refreshAlertsBadge, 60000);
  } catch(e) {
    toast(e.message || "Servidor offline — verifique se o Cortex está rodando");
    console.error(e);
  }
}
boot();