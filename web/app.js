/* Monsoon — client. Three routed views over one API. Every value is live. */
import * as CH from "./charts.js";

let animate = null, stagger = null;
try { const m = await import("https://cdn.jsdelivr.net/npm/motion@11.18.2/+esm");
      animate = m.animate; stagger = m.stagger; }
catch (e) { console.warn("motion unavailable", e); }
const mo = (el, kf, op) => { try {
    if (!animate || !el || (el.length === 0)) return null;
    const a = animate(el, kf, op);
    a?.finished?.then(() => { for (const n of (el.length != null ? el : [el]))
      n?.style?.removeProperty?.("transform"); }).catch(()=>{});
    return a; } catch { return null; } };
const stag = n => { try { return stagger ? stagger(n) : 0; } catch { return 0; } };

const $ = id => document.getElementById(id);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
const num = (v, d=2) => v==null||isNaN(v) ? "—"
  : Number(v).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const pct = v => v==null||isNaN(v) ? "—" : (v>=0?"+":"") + Number(v).toFixed(2) + "%";
const abbr = v => { if (v==null||isNaN(v)) return "—"; const a=Math.abs(v);
  return a>=1e12?(v/1e12).toFixed(2)+"T":a>=1e9?(v/1e9).toFixed(1)+"B"
       :a>=1e6?(v/1e6).toFixed(1)+"M":a>=1e3?(v/1e3).toFixed(1)+"K":String(v); };
const sgn = v => v>=0 ? "up" : "dn";
const LOGO_V = 2;
const logo = s => `/api/logo/${encodeURIComponent(s)}?v=${LOGO_V}`;
const IC = {
  edit:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>`,
  del:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>`,
  x:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>`,
  arrow:`<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>`,
  refresh:`<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/></svg>`,
  chev:`<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>`,
};

const DISCLAIMER = "Informational only, not financial advice. Monsoon summarises public data and cannot account for your circumstances.";
const LAST_TICKER = "monsoon.lastTicker";
const lastTicker = () => { try { return localStorage.getItem(LAST_TICKER) || "NVDA"; } catch { return "NVDA"; } };
const S = { route:"dashboard", cur:null, wl:[], q:{}, sparks:{}, pf:null,
            tf:"1M", tab:"overview", show:{MA:true,Vol:true},
            run:null, tabAgent:{}, pending:[], llm:false, brief:null, acct:null, accounts:[], kinds:[],
            basket:[], picked:new Set(), focus:null, compare:null };

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = "";
    try { const j = JSON.parse(await r.text()); msg = j.detail || j.error || ""; } catch {}
    const e = new Error((msg || `request failed (${r.status})`).slice(0,200));
    e.status = r.status;
    throw e;
  }
  return r.json();
}
const jpost = (path, body) => api(path, {method:"POST",
  headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});

/* ─────────────── account ─────────────── */
let ME = { guest:true, name:"Guest", can_save:false };

async function loadMe() {
  ME = await api("/api/me").catch(() => ({ guest:true, name:"Guest", can_save:false }));
  renderAcct();
  return ME;
}

function renderAcct() {
  const el = $("acct"); if (!el) return;
  const nm = ME.name || ME.username || "Guest";
  if (ME.guest || !ME.signed_in) {
    el.innerHTML = `<button class="whoami guest" id="signin">
      <span class="av">?</span><span class="nm">Sign in</span></button>`;
    $("signin").onclick = () => openAuth("login");
  } else {
    el.innerHTML = `<button class="whoami" id="acctbtn" title="Account">
      <span class="av">${esc(nm.slice(0,1).toUpperCase())}</span>
      <span class="nm">${esc(nm)}</span></button>`;
    $("acctbtn").onclick = e => { e.stopPropagation(); toggleAcctMenu(); };
  }
}

function closeAcctMenu() { $$(".acctmenu").forEach(n => n.remove()); }

function toggleAcctMenu() {
  if (document.querySelector(".acctmenu")) return closeAcctMenu();
  const m = document.createElement("div");
  m.className = "acctmenu";
  m.innerHTML = `<div class="who"><div class="n">${esc(ME.name || ME.username)}</div>
      <div class="s">@${esc(ME.username || "")}</div></div>
    <button data-a="pw">Change password</button>
    <button data-a="out" class="danger">Sign out</button>`;
  m.onclick = async e => {
    const a = e.target.dataset?.a; if (!a) return;
    closeAcctMenu();
    if (a === "out") { await fetch("/api/auth/logout", {method:"POST"}); location.reload(); }
    if (a === "pw") changePassword();
  };
  $("acct").appendChild(m);
  setTimeout(() => addEventListener("click", closeAcctMenu, {once:true}), 0);
}

/* Deliberately a prompt pair rather than a sheet: changing a password is rare,
   and a rarely-used form is a rarely-tested form. */
async function changePassword() {
  const current = prompt("Current password:"); if (!current) return;
  const next = prompt("New password (at least 10 characters):"); if (!next) return;
  try {
    const r = await jpost("/api/auth/password", {current, new: next});
    alert(r.other_sessions_revoked
      ? `Password changed. ${r.other_sessions_revoked} other session(s) signed out.`
      : "Password changed.");
  } catch (e) { alert(e.message); }
}

/* The sign-in sheet. Guests are never forced through it: it opens when you
   reach for something that needs a book of your own. */
let AUTH_MODE = "login", AUTH_AFTER = null;

function openAuth(mode = "login", why = null) {
  AUTH_MODE = mode; AUTH_AFTER = null;
  $("authsheet").classList.add("on");
  authMode(mode, why);
  setTimeout(() => $("authuser").focus(), 60);
}
const closeAuth = () => { $("authsheet").classList.remove("on"); authErr(""); };
const authErr = m => { const e = $("autherr"); e.textContent = m || "";
                       e.classList.toggle("on", !!m); };

function authMode(mode, why) {
  AUTH_MODE = mode;
  const reg = mode === "register";
  $$(".authtabs button").forEach(b => b.classList.toggle("on", b.dataset.mode === mode));
  $("authttl").textContent = reg ? "Create your account" : "Sign in to Monsoon";
  $("authsub").textContent = why || (reg
    ? "A username and password is all it takes. No email, no verification step."
    : "Your watchlist, portfolios and cost basis live with your account.");
  $("authpass").setAttribute("autocomplete", reg ? "new-password" : "current-password");
  $("authpwhint").style.display = reg ? "" : "none";
  $("authsubmit").textContent = reg ? "Create account" : "Sign in";
  $("authswitch").innerHTML = reg
    ? `Already have one? <button type="button" data-go="login">Sign in</button>`
    : `New here? <button type="button" data-go="register">Create an account</button>`;
  authErr("");
}

/* Call this instead of letting a 401 surface as a raw error.
   `resume` is replayed after a successful sign-in, so the action that prompted
   the sheet is not simply thrown away - signing in reloads the page, so it
   has to survive that, hence sessionStorage rather than a closure. */
const RESUME = "monsoon.resume";
function needAccount(why, resume) {
  try { resume ? sessionStorage.setItem(RESUME, JSON.stringify(resume))
               : sessionStorage.removeItem(RESUME); } catch {}
  openAuth("register", why || "Sign in or create an account to keep this.");
}

async function replayResume() {
  let r = null;
  try { r = JSON.parse(sessionStorage.getItem(RESUME) || "null");
        sessionStorage.removeItem(RESUME); } catch {}
  if (!r || ME.guest) return false;
  if (r.kind === "watch") {
    await jpost("/api/watchlist", {ticker: r.ticker}).catch(()=>{});
    return true;
  }
  return false;
}

/* ─────────────── candlestick chart (ticker view only) ─────────────── */
const TF = { "1D":["1d","5m"],"5D":["5d","30m"],"1M":["1mo","1d"],
             "6M":["6mo","1d"],"1Y":["1y","1d"],"5Y":["5y","1wk"] };
let chart, cs, vs, maA, maB;
const BARS = new Map();                       // sym|period|interval -> {t, bars}
const BAR_TTL = { "5m":55_000, "30m":55_000, "1d":900_000, "1wk":900_000 };
async function getBars(sym, period, interval) {
  const k = `${sym}|${period}|${interval}`, hit = BARS.get(k);
  const ttl = BAR_TTL[interval] ?? 300_000;
  if (hit && Date.now() - hit.t < ttl) return hit.bars;
  const bars = (await api(`/api/bars/${sym}?period=${period}&interval=${interval}`)).bars;
  BARS.set(k, { t: Date.now(), bars });
  return bars;
}
/* warm every timeframe in the background so switching is instant */
function prefetchFrames(sym) {
  const order = ["1M","1D","5D","6M","1Y","5Y"];        // visible first, then the rest
  order.reduce((chain, k) => chain.then(() => {
    if (S.cur !== sym) return;                          // user moved on - stop
    const [p, i] = TF[k];
    return getBars(sym, p, i).catch(()=>{});
  }), Promise.resolve());
}
function buildChart() {
  const el = $("chart");
  if (!el || !window.LightweightCharts) return;
  chart = LightweightCharts.createChart(el, {
    width: el.clientWidth||800, height: el.clientHeight||340,
    layout:{background:{color:"transparent"},textColor:"#8d95a6",fontSize:10,
            fontFamily:"JetBrains Mono, monospace"},
    grid:{vertLines:{color:"rgba(255,255,255,.045)"},horzLines:{color:"rgba(255,255,255,.045)"}},
    rightPriceScale:{borderColor:"rgba(255,255,255,.08)",scaleMargins:{top:.1,bottom:.26}},
    timeScale:{borderColor:"rgba(255,255,255,.08)",rightOffset:3,barSpacing:9,
               fixLeftEdge:true,fixRightEdge:true},
    crosshair:{mode:0,
      vertLine:{color:"rgba(255,255,255,.25)",width:1,style:3,labelBackgroundColor:"#1a1d28"},
      horzLine:{color:"rgba(255,255,255,.25)",width:1,style:3,labelBackgroundColor:"#1a1d28"}},
    handleScale:false, handleScroll:false });
  cs = chart.addCandlestickSeries({upColor:CH.C.pos,downColor:CH.C.neg,
    borderUpColor:CH.C.pos,borderDownColor:CH.C.neg,
    wickUpColor:"rgba(25,158,112,.65)",wickDownColor:"rgba(230,103,103,.65)"});
  vs = chart.addHistogramSeries({priceScaleId:"",priceFormat:{type:"volume"}});
  vs.priceScale().applyOptions({scaleMargins:{top:.84,bottom:0}});
  maA = chart.addLineSeries({color:CH.C.s3,lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
  maB = chart.addLineSeries({color:CH.C.s2,lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
  new ResizeObserver(()=>{ if(!el.clientWidth) return;
    chart.applyOptions({width:el.clientWidth,height:el.clientHeight});
    chart.timeScale().fitContent(); }).observe(el);
}
const sma = (b,n) => b.length<n ? [] : b.map((x,i)=> i<n-1 ? null
  : ({time:x.t, value:+(b.slice(i-n+1,i+1).reduce((a,y)=>a+y.c,0)/n).toFixed(2)})).filter(Boolean);
async function drawChart() {
  if (!chart || !S.cur) return;
  const [period,interval] = TF[S.tf];
  const want = S.cur;
  let bars; try { bars = await getBars(S.cur, period, interval); }
  catch { return; }
  if (S.cur !== want) return;                 // a later click already won
  if (!bars?.length) return;
  cs.setData(bars.map(b=>({time:b.t,open:b.o,high:b.h,low:b.l,close:b.c})));
  vs.setData(S.show.Vol ? bars.map(b=>({time:b.t,value:b.v,
    color:b.c>=b.o?"rgba(25,158,112,.24)":"rgba(230,103,103,.24)"})) : []);
  maA.setData(S.show.MA ? sma(bars, Math.min(50, Math.max(3, bars.length>>2))) : []);
  maB.setData(S.show.MA ? sma(bars, Math.min(200, Math.max(5, bars.length>>1))) : []);
  chart.applyOptions({timeScale:{timeVisible:/m|h/.test(interval)}});
  requestAnimationFrame(()=>chart.timeScale().fitContent());
}

/* ─────────────── shared bits ─────────────── */
function quoteRow(sym) { return S.q[sym] || {}; }
/* the agent panel is global - scope the question to whatever view you are on */
function askScope() {
  if (S.route === "ticker") {
    const picks = [...(S.picked || [])];
    const who = picks.length ? picks.join(", ") : (S.cur || "");
    return { ph: `Ask about ${who}…`, pre: q => q, tickers: picks };
  }
  if (S.route === "brief")
    return { ph: "Ask about today's brief…",
             pre: q => `About today's brief across ${(S.brief?.checked||[]).join(", ")}: ${q}` };
  if (S.route === "portfolio")
    return { ph: "Ask about your portfolio…",
             pre: q => `About MY PORTFOLIO "${S.pf?.portfolio_name||""}" (holdings: ${(S.pf?.positions||[]).map(p=>`${p.qty} ${p.ticker} @ ${p.basis}${p.account?" in "+p.account:""}`).join(", ") || "none"}): ${q}` };
  return { ph: "Ask about your watchlist…",
           pre: q => `About my watchlist (${S.wl.join(", ")}): ${q}` };
}
function syncAsk() { const a = $("ask"); if (a) a.placeholder = askScope().ph; }

function crumbs(parts) {
  $("crumbs").innerHTML = parts.map((p,i)=>
    (i ? `<span class="sep">/</span>` : "") +
    (p.href ? `<a class="c" href="${p.href}" style="text-decoration:none">${esc(p.label)}</a>`
            : `<span class="${i===parts.length-1?"cur":"c"}">${esc(p.label)}</span>`)).join("");
}
function pfSummary() {
  const d = S.pf;
  // book value belongs to the portfolio, not the dashboard
  // a guest has no book, so an empty $0.00 would be a lie, not a zero
  if (!d || ME.guest || S.route !== "portfolio") { $("pfsummary").innerHTML = ""; return; }
  $("pfsummary").innerHTML = `<span class="lbl">Book</span>
    <span class="mono" style="font-weight:600">$${num(d.market_value)}</span>
    <span class="badge ${sgn(d.day_change)}">${d.day_change>=0?"+":"−"}$${num(Math.abs(d.day_change||0))} today</span>`;
}
const tilesHTML = rows => `<div class="grid">${rows.map(([k,v,s])=>
  `<div class="tile"><div class="k">${k}</div><div class="v mono">${v}</div><div class="s">${s||""}</div></div>`).join("")}</div>`;

function afterRender(root) {
  const ah = $("askhere");
  if (ah) ah.onclick = () => { openAgent(true); syncAsk(); $("ask").focus(); };
  S.pending.forEach(fn => { try { fn(); } catch(e){ console.warn(e); } });
  S.pending = [];
  mo(root, { opacity:[0,1], y:[10,0] }, { duration:.34, easing:[.22,1,.36,1] });
  mo(root.querySelectorAll(".panel,.tile"),
     { opacity:[0,1], y:[10,0], scale:[.99,1] },
     { duration:.4, delay:stag(.03), easing:[.22,1,.36,1] });
}

/* ═══════════════ VIEW: dashboard ═══════════════ */
const SIG_ICON = { threshold:"‼", move:"↕", volume:"◫", high:"▲", low:"▼",
                   earnings:"◷", peer_gap:"⇄", peer_move:"⇢" };
let wlSort = { key:"change_pct", dir:-1 };

function signalStrip(b) {
  if (!b) return `<div class="panel"><div class="panel-b"><div class="skel" style="height:54px"></div></div></div>`;
  const sigs = (b.signals||[]).slice(0,4);
  return `<div class="panel">
    <div class="panel-h"><h4>Daily overview</h4>
      <span class="r">${sigs.length} flagged · ${b.checked.length} tracked${
        b.adjacent_checked?.length?` + ${b.adjacent_checked.length} adjacent`:""}</span>
      <a class="btn btn-sm btn-ghost" href="#/brief">Full brief</a></div>
    <div class="panel-b" style="display:grid;gap:8px">
      ${sigs.length ? sigs.map(g=>`<div class="sigline" data-go="${g.ticker}">
          <span class="sigicon ${g.kind}">${SIG_ICON[g.kind]||"•"}</span>
          <div><div class="h">${esc(g.headline)}${g.held?` <span class="badge brand">held</span>`:""}</div>
            <div class="d">${esc(g.detail)}</div></div>
          <span class="sev mono">${g.severity}</span></div>${whyHTML(g.why)}`).join("")
        : `<div class="empty" style="padding:18px">Nothing unusual today.
             ${b.quiet?.length?`<div class="muted" style="margin-top:6px">Checked ${b.quiet.join(", ")}${
               b.adjacent_checked?.length?` and ${b.adjacent_checked.length} adjacent names`:""}</div>`:""}</div>`}
    </div></div>`;
}

function wlRows(rows) {
  const k = wlSort.key;
  const sorted = [...rows].sort((a,c)=>{
    const av=a[k], cv=c[k];
    if (av==null) return 1; if (cv==null) return -1;
    return typeof av==="string" ? av.localeCompare(cv)*wlSort.dir : (av-cv)*wlSort.dir;
  });
  return sorted.map(r=>`<tr data-go="${r.sym}">
    <td><div class="wname"><img src="${logo(r.sym)}" alt="" loading="lazy">
      <div><div class="s">${r.sym}</div><div class="n">${esc(r.name||"")}</div></div></div></td>
    <td class="mono" style="font-weight:600">${num(r.price)}</td>
    <td class="mono ${sgn(r.change_pct)}" style="font-weight:600">${pct(r.change_pct)}</td>
    <td><div class="wspark" data-spark="${r.sym}" style="margin-left:auto"></div></td>
    <td class="mono">${abbr(r.market_cap)}</td>
    <td class="mono">${num(r.pe,1)}</td>
    <td>${r.held?`<span class="badge brand">held</span>`:""}</td></tr>`).join("");
}

async function viewDashboard() {
  crumbs([{label:"Dashboard"}]);
  const v = $("views");
  const pf = S.pf;
  const held = new Set((pf?.positions||[]).map(p=>p.ticker));
  const rows = S.wl.map(x => ({ sym:x, held:held.has(x), ...quoteRow(x) }))
                   .filter(r => r.price != null);

  v.innerHTML = `<div class="page">
    <div class="page-head">
      <div><div class="ttl">Dashboard</div>
        <div class="sub">The broad market and your ${rows.length} tracked tickers</div></div>
      <div class="acts">
        <input id="addinput" class="inp" style="width:170px" placeholder="Add ticker…">
        <button class="btn btn-sm btn-brand" id="askhere">Ask ${IC.arrow}</button></div>
    </div>

    <div id="idxstrip" class="idxstrip">
      ${Array(6).fill(`<div class="idx skel" style="height:122px"></div>`).join("")}</div>

    ${ME.guest ? `<div class="guestbar">
      <span>Browsing as a guest — quotes, research and the agent all work. A free
      account adds a watchlist and portfolios that persist.</span>
      <div class="grow"></div>
      <button class="btn btn-sm btn-brand" id="gbsign">Create account</button></div>` : ""}

    <div class="section" id="sigwrap">${signalStrip(S.brief)}</div>

    <div class="section"><div class="panel">
      <div class="panel-h"><h4>Watchlist</h4>
        <span class="r">live · ${rows.length} tickers in 1 request</span></div>
      <table class="wtable"><thead><tr>
        ${[["sym","Symbol"],["price","Last"],["change_pct","Change"],[null,"30-day"],
           ["market_cap","Mkt cap"],["pe","P/E"],[null,""]]
          .map(([k,label])=>`<th ${k?`data-sort="${k}" class="sortable${wlSort.key===k?" on":""}"`:""}>${label}${
            k&&wlSort.key===k?`<span class="caret">${wlSort.dir<0?"▾":"▴"}</span>`:""}</th>`).join("")}
      </tr></thead><tbody id="wlbody">${wlRows(rows)}</tbody></table>
    </div></div></div>`;

  wireAdd();
  if ($("gbsign")) $("gbsign").onclick = () => openAuth("register");
  loadIndices();
  const paintSparks = () => $$("[data-spark]").forEach(el => {
    const val = S.sparks[el.dataset.spark] || [];
    if (val.length>1) CH.sparkline(el, val, val.at(-1)>=val[0]); });
  const wireRows = () => $$("#wlbody [data-go], .sigline[data-go]")
    .forEach(el => el.onclick = () => location.hash = "#/t/"+el.dataset.go);
  paintSparks(); wireRows();

  $$("[data-sort]").forEach(th => th.onclick = () => {
    const k = th.dataset.sort;
    wlSort = { key:k, dir: wlSort.key===k ? -wlSort.dir : (k==="sym" ? 1 : -1) };
    $("wlbody").innerHTML = wlRows(rows);
    $$("[data-sort]").forEach(x => { x.classList.toggle("on", x.dataset.sort===wlSort.key);
      x.querySelector(".caret")?.remove();
      if (x.dataset.sort===wlSort.key) x.insertAdjacentHTML("beforeend",
        `<span class="caret">${wlSort.dir<0?"▾":"▴"}</span>`); });
    paintSparks(); wireRows();
  });

  afterRender(v);
  // the overview is the slow part - fill it in once it lands
  loadBrief().then(b => { const w = $("sigwrap"); if (!w) return;
    w.innerHTML = signalStrip(b); wireRows();
    mo(w.querySelectorAll(".sigline"), {opacity:[0,1],y:[6,0]},
       {duration:.32,delay:stag(.04),easing:[.22,1,.36,1]}); }).catch(()=>{});
}


/* ───────── broad market strip ───────── */
async function loadIndices() {
  const el = $("idxstrip"); if (!el) return;
  let d; try { d = await api("/api/indices"); } catch { el.innerHTML = ""; return; }

  el.innerHTML = d.indices.map(i => {
    if (i.kind === "sentiment") {
      return `<div class="idx fng">
        <div class="lbl">${esc(i.label)} <span class="src2">${esc(i.source||"")}</span></div>
        <div class="mount" data-fng="${i.level}"></div>
        <div class="chg mono">${i.change!=null?`${i.change>=0?"+":""}${num(i.change,1)} vs yesterday`:""}${
          i.month_ago!=null?` · ${num(i.month_ago,0)} a month ago`:""}</div></div>`;
    }
    // a falling VIX or yield is not "good" — keep those neutral
    const neutral = i.kind !== "index";
    return `<div class="idx">
      <div class="lbl">${esc(i.label)}</div>
      <div class="lvl mono">${i.kind==="rate" ? num(i.level)+"%" : num(i.level, i.level>1000?0:2)}</div>
      <div class="mount" data-ix="${esc(i.symbol)}"></div>
      <div class="chg mono ${neutral?"":sgn(i.change_pct)}">${pct(i.change_pct)}</div></div>`;
  }).join("");

  const by = Object.fromEntries(d.indices.map(i=>[i.symbol,i]));
  el.querySelectorAll("[data-ix]").forEach(m => {
    const i = by[m.dataset.ix]; if (!i?.history?.length) return;
    CH.indexSpark(m, i.history, i.change_pct >= 0, i.kind !== "index");
  });
  el.querySelectorAll("[data-fng]").forEach(m => {
    const i = d.indices.find(x=>x.kind==="sentiment"); if (!i) return;
    CH.fngGauge(m, i.level, i.history);
  });
  mo(el.querySelectorAll(".idx"), { opacity:[0,1], y:[8,0] },
     { duration:.34, delay:stag(.04), easing:[.22,1,.36,1] });
}

/* ═══════════════ VIEW: ticker ═══════════════ */
const TAB_DOMAIN = { overview:"fundamentals", financials:"fundamentals",
                     news:"street", analysts:"street", events:"events",
                     related:"relations" };
function agentSlot(domain) {
  const f = S.tabAgent[S.cur + ":" + domain];
  if (!f) return "";
  return `<div class="agentbox"><div class="ah"><span class="dot"></span>${esc(f.domain)} agent · ${f.tools_used.length} tools</div>
    <p>${esc(f.narrative)}</p>
    <div class="disclaim">${esc(DISCLAIMER)}</div>
    <button class="link" data-trace="1">Show work ${IC.arrow}</button></div>`;
}

const TABS = {
  overview: async t => {
    const o = await api(`/api/overview/${t}`);
    const p = x => x==null ? "—" : num(x*100,1)+"%";
    return tilesHTML([
      ["Market cap",abbr(o.market_cap),""],["P/E",num(o.pe,1),"trailing"],
      ["Fwd P/E",num(o.forward_pe,1),""],["P/B",num(o.price_to_book,1),""],
      ["Net margin",p(o.net_margin),"TTM"],["Op margin",p(o.operating_margin),"TTM"],
      ["ROE",p(o.roe),"TTM"],["Debt/Equity",num(o.debt_to_equity,1),""]])
      + `<div class="section"><div class="panel"><div class="panel-h"><h4>Profile</h4>
          <span class="r">${esc(o.sector||"")}${o.industry?" · "+esc(o.industry):""}</span></div>
          <div class="panel-b"><div class="prose">${esc((o.summary||"No profile available.").slice(0,620))}…</div></div>
        </div></div>` + agentSlot("fundamentals");
  },
  financials: async t => {
    const f = await api(`/api/financials/${t}`);
    if (!f.quarters.length) return `<div class="empty">No SEC XBRL data for ${esc(t)} — likely a non-US filer.</div>`;
    const qs = f.quarters.slice(-8);
    S.pending.push(() => CH.revenue($("revmount"), qs));
    const u = f.upcoming || {}, tr = f.track_record || [];
    if (tr.length) S.pending.push(() => CH.surprise($("trmount"), tr.map(t=>({
      date:t.date, surprise_pct:t.surprise_pct, actual:t.eps_actual, estimate:t.eps_estimate }))));
    const upcomingHTML = u.date ? `
      <div class="panel" style="margin-bottom:14px">
        <div class="panel-h"><h4>Next report</h4>
          <span class="r">${u.days_away!=null?`in ${u.days_away} days`:""}</span></div>
        <div class="panel-b">${tilesHTML([
          ["Date", esc(u.date), u.days_away!=null?`${u.days_away} days away`:""],
          ["EPS expected", num(u.eps_estimate), u.eps_low!=null?`range ${num(u.eps_low)}–${num(u.eps_high)}`:""],
          ["Revenue expected", abbr(u.revenue_estimate), u.revenue_low!=null?`range ${abbr(u.revenue_low)}–${abbr(u.revenue_high)}`:""],
          ["Track record", `${f.beats}/${f.reports}`, "beats on EPS"]])}</div></div>` : "";
    const trackHTML = tr.length ? `
      <div class="section"><div class="panel">
        <div class="panel-h"><h4>Beat / miss history</h4>
          <span class="r">reported EPS vs consensus</span></div>
        <div class="panel-b tight"><div id="trmount" class="chartmount"></div></div>
        <div class="panel-b" style="padding-top:0">
          ${tr.map(t=>`<div class="lrow"><span class="d mono">${esc(t.date)}</span>
            <span class="mono">${num(t.eps_actual)} vs ${num(t.eps_estimate)} est</span>
            <span class="badge ${t.result==="beat"?"pos":t.result==="miss"?"neg":""}">
              ${t.result} ${t.surprise_pct!=null?pct(t.surprise_pct):""}</span></div>`).join("")}
        </div></div></div>` : "";
    return upcomingHTML + `<div class="panel"><div class="panel-h"><h4>Quarterly revenue</h4>
        <span class="r">${esc(f.source)}</span></div>
      <div class="panel-b tight"><div id="revmount" class="chartmount"></div></div></div>
      <div class="section"><div class="panel"><div class="panel-h"><h4>Income statement</h4>
        <span class="r">${esc(f.note)}</span></div>
        <div class="panel-b"><table>
        <thead><tr><th>Quarter</th><th>Revenue</th><th>Gross</th><th>Operating</th><th>Net</th><th>Op margin</th><th>Form</th></tr></thead>
        <tbody>${qs.slice().reverse().map(q=>`<tr><td>${q.end}</td>
          <td class="mono">${abbr(q.revenue)}</td><td class="mono">${abbr(q.gross_profit)}</td>
          <td class="mono">${abbr(q.operating_income)}</td><td class="mono">${abbr(q.net_income)}</td>
          <td class="mono">${q.operating_margin!=null?q.operating_margin+"%":"—"}</td>
          <td><span class="badge">${esc(q.form||"")}</span></td></tr>`).join("")}</tbody>
        </table></div></div></div>` + trackHTML + agentSlot("fundamentals");
  },
  news: async t => {
    const n = await api(`/api/news/${t}`);
    if (!n.items.length) return `<div class="empty">No recent headlines.</div>`;
    return `<div class="panel"><div class="panel-h"><h4>Headlines</h4>
        <span class="r">${n.relevant} of ${n.total} name the issuer</span></div>
      <div class="panel-b">${n.items.map(i=>`<div class="newsrow"><div>
        <div class="h">${i.url?`<a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a>`:esc(i.title)}</div>
        <div class="m">${esc(i.publisher||"")}${i.published?" · "+esc(String(i.published).slice(0,10)):""}</div></div>
        <span class="badge ${i.mentions_issuer?"brand":"ghost"}">${i.mentions_issuer?t:"unrelated"}</span></div>`).join("")}
        <div class="muted" style="margin-top:14px">${esc(n.note)}</div></div></div>`
      + agentSlot("street");
  },
  analysts: async t => {
    const a = await api(`/api/analysts/${t}`), c = a.consensus||{}, g = a.targets||{};
    const up = g.targetMeanPrice && g.currentPrice ? (g.targetMeanPrice/g.currentPrice-1)*100 : null;
    const dist = a.distribution||[], total = dist.reduce((x,y)=>x+y.n,0);
    if (total) { const COL=["#199e70","#57b98f","#8d95a4","#e0916b","#e66767"];
      S.pending.push(()=>CH.consensus($("consmount"), dist.map((b,i)=>({...b,color:COL[i]})))); }
    return tilesHTML([
      ["Consensus", esc(c.recommendationKey||"—").replace(/_/g," "), c.numberOfAnalystOpinions?c.numberOfAnalystOpinions+" analysts":""],
      ["Low target", num(g.targetLowPrice), ""],
      ["Mean target", num(g.targetMeanPrice), up!=null?pct(up)+" vs last":""],
      ["High target", num(g.targetHighPrice), ""]])
      + (total ? `<div class="section"><div class="panel"><div class="panel-h"><h4>Consensus distribution</h4>
          <span class="r">${total} analysts · reported counts</span></div>
          <div class="panel-b"><div id="consmount"></div></div></div></div>` : "")
      + `<div class="section"><div class="panel"><div class="panel-h"><h4>Rating changes</h4></div>
        <div class="panel-b">${a.changes.length ? a.changes.map(r=>`<div class="lrow">
          <span class="d mono">${esc(r.date)}</span><span>${esc(r.firm||"")} → ${esc(r.to||"")}</span>
          <span class="badge ${/up/i.test(r.action||"")?"pos":/down/i.test(r.action||"")?"neg":""}">${esc(r.action||"—")}</span>
        </div>`).join("") : `<div class="empty">No rating changes on record.</div>`}</div></div></div>`
      + agentSlot("street");
  },

  related: async t => {
    const d = await api(`/api/related/${t}`);
    const m = d.moves, a = d.read_across;
    if (!m && !a) return `<div class="empty">No peer cohort found for ${esc(t)}.
      ${d.unavailable?esc(d.unavailable):""}</div>`;
    const gap = m?.gap_vs_peers_pct;
    return (m ? tilesHTML([
        [`${t} today`, pct(m.ticker_change_pct), ""],
        ["Peer average", pct(m.peer_average_pct), `${m.peers.length} peers`],
        ["Gap vs group", gap!=null?pct(gap):"—", m.reading?esc(m.reading):""],
        ["Biggest mover", m.biggest_mover.ticker, pct(m.biggest_mover.change_pct)]]) : "")
      + (m ? `<div class="section"><div class="panel">
          <div class="panel-h"><h4>How the adjacent cohort traded today</h4>
            <span class="r">Yahoo peer set</span></div>
          <table class="wtable"><thead><tr><th>Peer</th><th>Last</th><th>Today</th><th></th></tr></thead>
          <tbody>${m.peers.map(pr=>`<tr data-go="${pr.ticker}">
            <td><div class="wname"><img src="${logo(pr.ticker)}" alt="" loading="lazy">
              <div><div class="s">${pr.ticker}</div>
                <div class="n">${esc(pr.name||"")}</div></div></div></td>
            <td class="mono">${num(pr.price)}</td>
            <td class="mono ${sgn(pr.change_pct)}" style="font-weight:600">${pct(pr.change_pct)}</td>
            <td><span class="badge ${Math.abs(pr.change_pct - m.ticker_change_pct) > 3 ? "" : "ghost"}">
              ${Math.abs(pr.change_pct - m.ticker_change_pct) > 3 ? "diverging" : "in line"}</span></td>
          </tr>`).join("")}</tbody></table></div></div>` : "")
      + (a ? `<div class="section"><div class="panel">
          <div class="panel-h"><h4>Does a peer's move transmit to ${esc(t)}?</h4>
            <span class="r">~2y daily returns · association, not causation</span></div>
          <table class="wtable"><thead><tr><th>Peer</th><th>Today</th><th>Correlation</th>
            <th>Same direction</th><th>Capture of &gt;3% move</th><th></th></tr></thead>
          <tbody>${a.peers.map(pr=>{
            const cap = pr.median_capture_of_big_moves;
            const verdict = cap==null ? "thin sample"
              : cap >= .7 ? "moves together" : cap >= .35 ? "partial" : "barely transmits";
            return `<tr><td style="font-weight:650">${pr.peer}</td>
              <td class="mono ${sgn(pr.peer_change_today_pct)}">${pct(pr.peer_change_today_pct)}</td>
              <td class="mono">${num(pr.correlation)}</td>
              <td class="mono">${num(pr.co_direction_pct,1)}%</td>
              <td class="mono">${cap!=null?num(cap)+"×":"—"}</td>
              <td><span class="badge ${cap>=.7?"pos":cap!=null&&cap<.35?"neg":""}">${verdict}</span></td>
              </tr>`;}).join("")}</tbody></table>
          <div class="panel-b"><div class="muted">${esc(a.how_to_read)}</div>
            <div class="muted" style="margin-top:8px;color:var(--warn)">${esc(a.caution)}</div>
            <button class="btn btn-sm" id="esbtn" data-peer="${a.strongest_link.peer}"
              style="margin-top:12px">Test whether ${a.strongest_link.peer}'s earnings move ${esc(t)}</button>
            <div id="esout"></div></div>
        </div></div>` : "")
      + agentSlot("relations");
  },
  events: async t => {
    const e = await api(`/api/events/${t}`);
    const beats = e.surprise_history.filter(h=>h.surprise_pct>0).length;
    if (e.surprise_history.length) S.pending.push(()=>CH.surprise($("surpmount"), e.surprise_history));
    return tilesHTML([
      ["Next earnings", esc(e.next_earnings||"—"), ""],
      ["EPS estimate", num(e.eps_estimate), ""],
      ["Beat rate", `${beats}/${e.surprise_history.length}`, "recent reports"]])
      + (e.surprise_history.length ? `<div class="section"><div class="panel">
          <div class="panel-h"><h4>Surprise vs estimate</h4></div>
          <div class="panel-b tight"><div id="surpmount" class="chartmount"></div></div></div></div>` : "")
      + `<div class="section"><div class="panel"><div class="panel-h"><h4>SEC filings</h4></div>
        <div class="panel-b">${e.filings.length ? e.filings.map(f=>`<div class="lrow">
          <span class="d mono">${esc(f.date)}</span><span>${esc(f.doc||"")}</span>
          <span class="badge">${esc(f.form)}</span></div>`).join("") : `<div class="empty">None.</div>`}</div></div></div>`
      + agentSlot("events");
  }
};

/* ═══════════ research workspace ═══════════
   Any number of tickers open at once. Tick the ones you care about, press
   Analyze, and say what you want done with that selection. */
const PANEL_COLORS = ["#3987e5","#d95926","#199e70","#c98500","#d55181","#9085e9"];

async function viewResearch(symbols) {
  S.basket = symbols;
  S.cur = S.focus && symbols.includes(S.focus) ? S.focus : symbols[0];
  S.picked = new Set((S.picked && [...S.picked].filter(t => symbols.includes(t))) || []);
  if (!S.picked.size) symbols.forEach(t => S.picked.add(t));
  try { localStorage.setItem(LAST_TICKER, symbols.join(",")); } catch {}
  const rl = document.querySelector('.navitem[data-route="ticker"]');
  if (rl) rl.setAttribute("href", "#/t/" + symbols.join(","));

  crumbs([{label:"Research", href:"#/dashboard"},
          {label: symbols.length > 1 ? `${symbols.length} tickers` : symbols[0]}]);

  const v = $("views");
  v.innerHTML = `<div class="page">
    <div class="page-head">
      <div><div class="ttl">Research</div>
        <div class="sub" id="wsub">${symbols.length} open · tick what to analyse</div></div>
      <div class="acts">
        <div class="lookup">
          <svg class="ico lupe" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4.3-4.3"/></svg>
          <input id="tsearch" class="inp" placeholder="Add a ticker…" autocomplete="off" spellcheck="false">
          <div id="tresults"></div>
        </div>
        <button class="btn btn-sm btn-brand" id="analyzeSel">${IC.refresh}Analyse selected</button>
      </div></div>

    <div id="composer"></div>
    <div id="panels" class="panelgrid">
      ${symbols.map(()=>`<div class="skel" style="height:188px"></div>`).join("")}</div>
    ${symbols.length > 1 ? `<div class="section" id="overlaywrap"></div>` : ""}
    <div class="section" id="detailwrap"></div>
  </div>`;

  wireLookup(true);
  $("analyzeSel").onclick = openComposer;

  let cmp;
  try { cmp = await api(`/api/compare?symbols=${symbols.join(",")}&period=6mo`); }
  catch (e) { $("panels").innerHTML = `<div class="empty">Couldn't load: ${esc(e.message)}</div>`; return; }
  S.compare = cmp;
  const by = Object.fromEntries(cmp.rows.map(r => [r.symbol, r]));

  $("panels").innerHTML = symbols.map((t, i) => {
    const r = by[t] || {};
    const col = PANEL_COLORS[i % PANEL_COLORS.length];
    return `<div class="tpanel ${S.picked.has(t)?"picked":""} ${t===S.cur?"focus":""}" data-panel="${t}">
      <div class="tp-head">
        <label class="tick"><input type="checkbox" data-pick="${t}" ${S.picked.has(t)?"checked":""}>
          <span class="box" style="--c:${col}"></span></label>
        <img src="${logo(t)}" alt="" loading="lazy">
        <div class="tp-id"><div class="s">${t}</div>
          <div class="n">${esc(r.name||"")}</div></div>
        <button class="tp-x" data-close="${t}" title="Close">${IC.x}</button>
      </div>
      <div class="tp-px">
        <span class="mono lv">${r.price!=null?"$"+num(r.price):"—"}</span>
        <span class="badge ${sgn(r.change_pct)}">${pct(r.change_pct)}</span>
        <span class="badge ghost">6mo ${pct(r.period_pct)}</span>
      </div>
      <div class="tp-spark" data-tspark="${t}" data-col="${col}"></div>
      <div class="tp-stats">
        ${[["P/E",num(r.pe,1)],["Mkt cap",abbr(r.market_cap)],
           ["Net mgn", r.net_margin!=null?num(r.net_margin*100,1)+"%":"—"],
           ["Rev gr", r.revenue_growth!=null?pct(r.revenue_growth*100):"—"]]
          .map(([k,val])=>`<div><span class="k">${k}</span><span class="v mono">${val}</span></div>`).join("")}
      </div>
      <button class="tp-open" data-focus="${t}">${t===S.cur?"Showing below":"Open detail"}</button>
    </div>`;
  }).join("");

  // per-panel sparkline from the shared normalised paths
  symbols.forEach(t => {
    const el = document.querySelector(`[data-tspark="${t}"]`);
    const vals = (cmp.paths||[]).map(p => p[t]).filter(x => x != null);
    if (el && vals.length > 1) CH.indexSpark(el, vals, vals.at(-1) >= vals[0], false);
  });

  $$("[data-pick]").forEach(c => c.onchange = () => {
    c.checked ? S.picked.add(c.dataset.pick) : S.picked.delete(c.dataset.pick);
    document.querySelector(`[data-panel="${c.dataset.pick}"]`)?.classList.toggle("picked", c.checked);
    syncSel();
  });
  $$("[data-close]").forEach(b => b.onclick = e => { e.stopPropagation();
    const left = S.basket.filter(x => x !== b.dataset.close);
    location.hash = left.length ? "#/t/" + left.join(",") : "#/dashboard"; });
  $$("[data-focus]").forEach(b => b.onclick = async () => {
    S.focus = S.cur = b.dataset.focus;
    $$(".tpanel").forEach(x => x.classList.toggle("focus", x.dataset.panel === S.cur));
    $$("[data-focus]").forEach(x => x.textContent = x.dataset.focus===S.cur ? "Showing below" : "Open detail");
    await renderDetail(); $("detailwrap").scrollIntoView({behavior:"smooth", block:"start"}); });

  if (symbols.length > 1) renderOverlay(cmp, symbols);
  await renderDetail();
  syncSel();
  afterRender(v);
}

function syncSel() {
  const n = S.picked.size;
  $("wsub").textContent = `${S.basket.length} open · ${n} selected`;
  const b = $("analyzeSel");
  b.disabled = n === 0 || !S.llm;
  b.title = !S.llm ? "Needs GEMINI_API_KEY" : n === 0 ? "Tick at least one ticker" : "";
}

function renderOverlay(cmp, symbols) {
  const w = $("overlaywrap"); if (!w) return;
  w.innerHTML = `<div class="panel">
    <div class="panel-h"><h4>Relative performance</h4>
      <span class="r">${esc(cmp.note)} · 6 months</span></div>
    <div class="panel-b tight"><div id="ovmount" class="chartmount"></div></div>
    ${cmp.correlations?.length ? `<div class="panel-b" style="padding-top:0">
      <div class="corrbar">${cmp.correlations.map(c=>`
        <span class="badge" title="1.0 means they move identically">
          ${esc(c.pair)} <b class="${c.corr>=.7?"up":c.corr<.4?"dn":""}">${num(c.corr)}</b></span>`).join("")}</div>
      <div class="muted" style="margin-top:8px">Pairwise return correlation over the same window —
        high numbers mean the basket is closer to one position than several.</div></div>` : ""}
  </div>`;
  CH.multiLine($("ovmount"), cmp.paths, symbols, PANEL_COLORS);
}

async function renderDetail() {
  const w = $("detailwrap"); if (!w || !S.cur) return;
  const q = (S.compare?.rows || []).find(r => r.symbol === S.cur) || {};
  const open = (quoteRow(S.cur).market_state || "").toUpperCase() === "REGULAR";
  w.innerHTML = `
    <div class="section-h"><h3>${esc(S.cur)} detail</h3>
      <span class="r">${esc(q.name||"")}</span></div>
    <div class="panel" id="chartpanel">
      <div class="panel-h"><h4>Price</h4>
        <div class="seg" id="tfseg" style="margin-left:auto">
          ${Object.keys(TF).map(k=>`<button data-tf="${k}" class="${k===S.tf?"on":""}">${k}</button>`).join("")}
        </div>
        <button class="btn btn-sm ${S.show.MA?"on":""}" id="tgMA">MA</button>
        <button class="btn btn-sm ${S.show.Vol?"on":""}" id="tgVol">Vol</button>
      </div>
      <div class="panel-b tight"><div id="chart"></div></div>
    </div>
    <div class="section">
      <div class="section-h"><div class="seg tabseg">
        ${Object.keys(TABS).map(k=>`<button class="${k===S.tab?"on":""}" data-tab="${k}">${k[0].toUpperCase()+k.slice(1)}</button>`).join("")}
      </div></div>
      <div id="tabbody"></div>
    </div>`;
  chart = null;
  buildChart(); drawChart(); prefetchFrames(S.cur);
  $("tfseg").onclick = e => { const b = e.target.closest("[data-tf]"); if(!b) return;
    $$("#tfseg button").forEach(x=>x.classList.remove("on")); b.classList.add("on");
    S.tf = b.dataset.tf; drawChart(); };
  ["MA","Vol"].forEach(k => { const b=$("tg"+k);
    b.onclick = () => { S.show[k]=!S.show[k]; b.classList.toggle("on",S.show[k]); drawChart(); }; });
  $$(".tabseg button").forEach(b => b.onclick = () => {
    $$(".tabseg button").forEach(x=>x.classList.remove("on")); b.classList.add("on");
    S.tab = b.dataset.tab; renderTab(); });
  await renderTab();
}

/* the prompt composer - you say what to do with the selection */
const SUGGESTIONS = [
  "Which looks expensive relative to what it actually earns?",
  "Do these trade as one bet or separately?",
  "Compare their margins and growth",
  "Which is holding up best and why?",
  "What would have to happen for the laggard to catch up?",
];
function openComposer() {
  const el = $("composer"), picks = [...S.picked];
  if (!picks.length) return;
  el.innerHTML = `<div class="composer">
    <div class="cm-head">
      <span class="cm-k">Analyse</span>
      ${picks.map(t=>`<span class="badge brand">${esc(t)}</span>`).join("")}
      <button class="btn btn-sm btn-ghost" id="cm_x" style="margin-left:auto">Cancel</button>
    </div>
    <textarea id="cm_q" class="inp" rows="2"
      placeholder="What do you want to know about ${esc(picks.join(", "))}?"></textarea>
    <div class="cm-sugg">${SUGGESTIONS.map(x=>`<button class="sugg" data-s="${esc(x)}">${esc(x)}</button>`).join("")}</div>
    <div class="cm-foot">
      <span class="muted">${picks.length} ticker${picks.length>1?"s":""} · the agent only sees what you selected</span>
      <button class="btn btn-primary btn-sm" id="cm_go">Run analysis ${IC.arrow}</button>
    </div></div>`;
  mo(el.firstElementChild, {opacity:[0,1], y:[-8,0]}, {duration:.26, easing:[.22,1,.36,1]});
  const ta = $("cm_q"); ta.focus();
  $("cm_x").onclick = () => el.innerHTML = "";
  $$(".sugg").forEach(b => b.onclick = () => { ta.value = b.dataset.s; ta.focus(); });
  const run = () => {
    const q = ta.value.trim(); if (!q) { ta.focus(); return; }
    el.innerHTML = "";
    streamAsk(q, picks);
  };
  $("cm_go").onclick = run;
  ta.onkeydown = e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); };
}

async function renderTab() {
  const el = $("tabbody"); if (!el) return;
  el.innerHTML = `<div class="grid">${"<div class='skel' style='height:86px'></div>".repeat(4)}</div>`;
  S.pending = [];
  let html;
  try { html = await TABS[S.tab](S.cur); }
  catch (e) { html = `<div class="empty">Couldn't load: ${esc(e.message)}</div>`; }
  el.innerHTML = html;
  el.querySelectorAll("[data-trace]").forEach(b => b.onclick = openTrace);
  el.querySelectorAll("[data-go]").forEach(g => g.onclick = () => location.hash = "#/t/"+g.dataset.go);
  const es = $("esbtn");
  if (es) es.onclick = async () => {
    es.disabled = true; es.textContent = "testing…";
    try {
      const r = await api(`/api/related/${S.cur}/event-study/${es.dataset.peer}`);
      const x = r.result;
      $("esout").innerHTML = x ? `<div class="quietbox" style="margin-top:12px">
          <div class="qh">${esc(r.source)} earnings → ${esc(r.target)}</div>
          <div class="muted" style="line-height:1.75">
            Over <b>${x.n_events}</b> of ${esc(r.source)}'s earnings reactions, ${esc(r.target)} moved the
            same way <b>${x.peer_same_direction}</b> (${x.peer_same_direction_pct}%) — against a
            baseline of <b>${x.baseline_same_direction_pct}%</b> on an average day.
            Median capture of the move: <b>${x.median_capture_of_move ?? "—"}×</b>.<br>
            <span style="color:${x.beats_baseline?"var(--pos)":"var(--neg)"}">${esc(x.verdict)}</span><br>
            <span style="color:var(--warn)">Binomial p = ${x.binomial_p_one_sided} —
            ${x.significant_at_05 ? "significant" : "NOT significant"}. ${esc(x.caution)}</span>
          </div></div>`
        : `<div class="muted" style="margin-top:12px">${esc(r.unavailable||"no result")}</div>`;
    } catch (e) { $("esout").innerHTML = `<div class="muted" style="color:var(--neg)">${esc(e.message)}</div>`; }
    es.disabled = false; es.textContent = `Test whether ${es.dataset.peer}'s earnings move ${S.cur}`;
  };
  S.pending.forEach(fn=>{ try{fn();}catch(e){console.warn(e);} }); S.pending=[];
  mo(el, { opacity:[0,1], y:[8,0] }, { duration:.3, easing:[.22,1,.36,1] });
  mo(el.querySelectorAll(".tile,.panel"), { opacity:[0,1], y:[8,0] },
     { duration:.36, delay:stag(.025), easing:[.22,1,.36,1] });
}


/* ───────── ticker lookup: search any symbol, not just the watchlist ───────── */
function wireLookup(addMode) {
  const box = $("tsearch"), out = $("tresults");
  if (!box) return;
  let timer, items = [], active = -1;

  const close = () => { out.innerHTML = ""; out.classList.remove("on"); active = -1; };
  const go = sym => { close(); box.value = ""; box.blur();
    const cur = addMode ? (S.basket || []) : [];
    const next = [...new Set([...cur, sym])].slice(0, 8);
    location.hash = "#/t/" + next.join(","); };

  const paint = () => {
    if (!items.length) { out.innerHTML = `<div class="lkempty">No matches</div>`; out.classList.add("on"); return; }
    out.innerHTML = items.map((r,i)=>`<div class="lkrow ${i===active?"on":""}" data-sym="${esc(r.symbol)}">
        <img src="${logo(r.symbol)}" alt="" loading="lazy">
        <div><div class="s">${esc(r.symbol)}</div><div class="n">${esc(r.name)}</div></div>
        <span class="badge ghost">${esc(r.exchange||r.type)}</span></div>`).join("");
    out.classList.add("on");
    out.querySelectorAll("[data-sym]").forEach(el => el.onmousedown = e => { e.preventDefault(); go(el.dataset.sym); });
  };

  box.oninput = () => {
    clearTimeout(timer);
    const q = box.value.trim();
    if (!q) return close();
    timer = setTimeout(async () => {
      try { items = (await api(`/api/search?q=${encodeURIComponent(q)}`)).results; active = -1; paint(); }
      catch { close(); }
    }, 180);
  };
  box.onkeydown = e => {
    if (e.key === "Escape") return close();
    if (e.key === "Enter") {
      e.preventDefault();
      if (active >= 0 && items[active]) return go(items[active].symbol);
      const v = box.value.trim().toUpperCase();
      if (v) go(v);                         // let them type a symbol straight in
      return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!items.length) return;
      e.preventDefault();
      active = e.key === "ArrowDown"
        ? Math.min(active + 1, items.length - 1) : Math.max(active - 1, 0);
      paint();
    }
  };
  box.onblur = () => setTimeout(close, 120);
}

/* ═══════════════ VIEW: portfolio ═══════════════ */
/* Accounts are real: the same ticker in a 401(k) and a Roth has different cost
   bases and different tax treatment, so they are never merged into one lot. */
async function viewPortfolio() {
  crumbs([{label:"Portfolio"}]);
  const v = $("views");
  if (ME.guest) {
    // A guest has no book by design. Say so plainly rather than rendering an
    // empty table that looks like a bug.
    v.innerHTML = `<div class="page">
      <div class="page-head"><div><div class="ttl">Portfolio</div>
        <div class="sub">Signed out</div></div></div>
      <div class="card"><div class="empty" style="padding:56px 24px">
        <div style="font-size:14px;font-weight:600;color:var(--foreground);margin-bottom:8px">
          Portfolios belong to an account</div>
        <div style="max-width:380px;margin:0 auto 18px;line-height:1.6">
          Holdings and cost basis are stored against your login, so they are there on
          your next visit. Everything else — quotes, charts, research, the agent — works
          as a guest.</div>
        <button class="btn btn-primary" id="pfsignin">Create an account</button>
      </div></div></div>`;
    $("pfsignin").onclick = () => openAuth("register");
    return;
  }
  const list = await api("/api/portfolios");
  S.accounts = list.accounts;
  S.kinds = list.kinds;
  const pid = S.acct ?? list.active ?? (list.accounts[0]?.id);
  S.acct = pid;
  const d = S.pf = await api(`/api/portfolio?portfolio_id=${encodeURIComponent(pid)}`);
  const combined = d.is_combined;
  const tot = d.market_value || 1;

  const chip = (id, name, val, extra="") => `
    <button class="acct ${String(id)===String(pid)?"on":""}" data-acct="${esc(String(id))}">
      <span class="n">${esc(name)}</span>
      <span class="v mono">$${num(val,0)}</span>${extra}</button>`;

  v.innerHTML = `<div class="page">
    <div class="page-head"><div><div class="ttl">Portfolio</div>
      <div class="sub">${esc(d.portfolio_name)} · ${d.positions.length} holdings</div></div>
      <div class="acts"><button class="btn btn-sm btn-brand" id="askhere">Ask ${IC.arrow}</button>
        <button class="btn btn-sm" id="addpos">+ Add holding</button></div></div>

    <div class="acctbar">
      ${chip("all","All accounts",list.combined.market_value)}
      ${list.accounts.map(a=>chip(a.id,a.name,a.market_value,
          `<span class="k">${esc(a.kind||"")}</span>`)).join("")}
      <button class="acct add" id="newacct">+ Account</button>
    </div>
    <div id="acctform"></div>

    ${ME.legacy_book ? `<div class="guestbar" style="margin:0 0 16px">
      <span>A book from before Monsoon had logins is still sitting on this machine —
      ${ME.legacy_book.portfolios} account(s) (${ME.legacy_book.names.map(esc).join(", ")}),
      ${ME.legacy_book.positions} holdings, ${ME.legacy_book.watchlist} watched tickers.
      Move it onto <b>${esc(ME.name||ME.username||"this account")}</b>?</span>
      <div class="grow"></div>
      <button class="btn btn-sm btn-brand" id="claimlegacy">Claim it</button></div>` : ""}

    ${d.seeded ? `<div class="seedbar" style="margin:0 0 16px"><p><b>These are demo holdings.</b>
        Share counts and cost basis are placeholders — prices and P&L are live, so the totals
        are not yours yet.</p>
      <div class="acts"><button class="btn btn-sm" id="clearpf">Clear &amp; enter mine</button>
        <button class="btn btn-sm btn-ghost" id="keeppf">Keep for now</button></div></div>` : ""}
    <div id="posform"></div>

    <div class="hero">
      <div class="hero-main"><div class="k">${esc(d.portfolio_name)}</div>
        <div class="v mono">$${num(d.market_value)}</div>
        <div class="sub2">
          <span class="badge ${sgn(d.day_change)}">${d.day_change>=0?"+":"−"}$${num(Math.abs(d.day_change||0))} today · ${pct(d.day_change_pct)}</span>
          <span class="badge ${sgn(d.pnl)}">${d.pnl>=0?"+":"−"}$${num(Math.abs(d.pnl))} unrealised · ${pct(d.pnl_pct)}</span>
          <span class="badge ghost">$${num(d.cost_basis)} invested</span>
          ${!combined?`<button class="btn btn-sm btn-ghost" id="renameacct">Rename</button>
            <button class="btn btn-sm btn-ghost" id="delacct">Delete account</button>`:""}
        </div></div>
      <div class="hero-side" id="pallocmount"></div>
    </div>

    <div class="section"><div class="panel">
      <div class="panel-h"><h4>Holdings</h4>
        <span class="r">${combined?"across every account":esc(d.portfolio_name)}</span></div>
      <table class="wtable"><thead><tr>
        <th>Symbol</th>${combined?"<th>Account</th>":""}<th>Weight</th><th>Shares</th>
        <th>Avg cost</th><th>Last</th><th>Today</th><th>Value</th><th>Unrealised</th><th></th></tr></thead>
      <tbody>${d.positions.map(p=>`<tr data-sym="${p.ticker}">
        <td><div class="wname"><img src="${logo(p.ticker)}" alt="" loading="lazy">
          <div><div class="s">${p.ticker}</div></div></div></td>
        ${combined?`<td><span class="badge ghost">${esc(p.account||"")}</span></td>`:""}
        <td><div class="wbar"><span style="width:${(p.market_value/tot*100).toFixed(1)}%"></span></div>
          <span class="mono wpct">${(p.market_value/tot*100).toFixed(1)}%</span></td>
        <td class="mono">${p.qty}</td>
        <td class="mono">$${num(p.basis)}</td>
        <td class="mono">$${num(p.price)}</td>
        <td class="mono ${sgn(p.day_change_pct)}">${pct(p.day_change_pct)}</td>
        <td class="mono" style="font-weight:600">$${num(p.market_value)}</td>
        <td class="mono ${sgn(p.pnl)}" style="font-weight:600">
          ${p.pnl>=0?"+":"−"}$${num(Math.abs(p.pnl))}
          <span class="sub-pct">${pct(p.pnl_pct)}</span></td>
        <td><div class="rowacts">
          <button class="btn btn-sm" data-edit="${p.ticker}" data-acc="${esc(p.account_id||pid)}">${IC.edit}</button>
          <button class="btn btn-sm" data-del="${p.ticker}" data-acc="${esc(p.account_id||pid)}">${IC.del}</button>
        </div></td></tr>`).join("") || `<tr><td colspan="${combined?10:9}">
          <div class="empty">Nothing in ${esc(d.portfolio_name)} yet. Use <b>+ Add holding</b>.</div></td></tr>`}
      </tbody></table></div></div>

    ${d.positions.length>1 ? `<div class="section" id="riskwrap">
      <div class="panel"><div class="panel-h"><h4>Risk profile</h4>
        <span class="r">derived from cached prices · no model involved</span></div>
      <div class="panel-b"><div class="skel" style="height:96px"></div></div></div></div>` : ""}
    </div>`;

  // account switching
  $$("[data-acct]").forEach(b => b.onclick = async () => {
    S.acct = b.dataset.acct;
    await api(`/api/portfolios/${encodeURIComponent(S.acct)}/activate`, {method:"POST"}).catch(()=>{});
    viewPortfolio();
  });
  $("newacct").onclick = () => openAcctForm();
  if ($("claimlegacy")) $("claimlegacy").onclick = async e => {
    e.target.disabled = true; e.target.textContent = "Moving…";
    try { await jpost("/api/auth/claim-legacy", {}); location.reload(); }
    catch (err) { e.target.disabled = false; e.target.textContent = "Claim it";
                  alert(err.message); }
  };
  if ($("renameacct")) $("renameacct").onclick = () =>
    openAcctForm(list.accounts.find(a=>a.id===pid));
  if ($("delacct")) $("delacct").onclick = async () => {
    const a = list.accounts.find(x=>x.id===pid);
    if (!confirm(`Delete "${a?.name}" and its ${a?.holdings||0} holdings? This cannot be undone.`)) return;
    await api(`/api/portfolios/${pid}`, {method:"DELETE"});
    S.acct = null; viewPortfolio();
  };

  $("addpos").onclick = () => openPosForm();
  if ($("clearpf")) $("clearpf").onclick = async () => {
    await api("/api/reset?keep_watchlist=true",{method:"POST"});
    await refreshAll(); viewPortfolio(); };
  if ($("keeppf")) $("keeppf").onclick = () => document.querySelector(".seedbar")?.remove();
  $$("[data-del]").forEach(b => b.onclick = async e => { e.stopPropagation();
    await api(`/api/positions/${b.dataset.del}?portfolio_id=${encodeURIComponent(b.dataset.acc)}`,
              {method:"DELETE"});
    viewPortfolio(); });
  $$("[data-edit]").forEach(b => b.onclick = e => { e.stopPropagation();
    openPosForm(d.positions.find(x=>x.ticker===b.dataset.edit), b.dataset.acc); });
  $$("#views tbody tr[data-sym]").forEach(r => r.onclick = e => {
    if (e.target.closest("button")) return; location.hash = "#/t/"+r.dataset.sym; });
  if (d.positions.length) CH.allocation($("pallocmount"), d.positions, d.market_value);

  if (d.positions.length > 1) api(`/api/portfolio/analytics?portfolio_id=${encodeURIComponent(pid)}`)
    .then(a => {
      const w = $("riskwrap"); if (!w) return;
      const c = a.concentration, bt = a.beta, co = a.correlation;
      w.innerHTML = `<div class="panel"><div class="panel-h"><h4>Risk profile</h4>
          <span class="r">${esc(d.portfolio_name)} · ${esc(a.note)}</span></div>
        <div class="panel-b">${tilesHTML([
          ["Top holding", c?`${c.top_holding.ticker} ${c.top_holding.pct}%`:"—", c?esc(c.reading):""],
          ["Top 3 weight", c?c.top3_pct+"%":"—", "of this account"],
          ["Beta", bt?num(bt.portfolio_beta):"—", bt?esc(bt.reading):""],
          ["Avg pair correlation", co?num(co.average_pairwise):"—",
           co?`most alike ${co.most_correlated.pair} ${co.most_correlated.corr}`:""]])}
          ${co ? `<div class="muted" style="margin-top:12px">${esc(co.note)}</div>` : ""}
        </div></div>`;
      mo(w.querySelectorAll(".tile"), {opacity:[0,1],y:[8,0]},
         {duration:.36,delay:stag(.03),easing:[.22,1,.36,1]});
    }).catch(()=>{ const w=$("riskwrap"); if(w) w.innerHTML=""; });

  pfSummary(); afterRender(v);
}

function openAcctForm(existing) {
  const el = $("acctform"); if (!el) return;
  el.innerHTML = `<div class="pform" style="margin:0 0 14px;max-width:460px">
    <div style="display:grid;grid-template-columns:1fr 150px;gap:6px">
      <input id="ac_n" class="inp" placeholder="Account name (e.g. Roth IRA)"
             value="${esc(existing?.name||"")}" autocomplete="off">
      <select id="ac_k" class="inp">
        ${(S.kinds||[]).map(k=>`<option value="${esc(k)}" ${existing?.kind===k?"selected":""}>${esc(k)}</option>`).join("")}
      </select></div>
    <div class="err" id="ac_e"></div>
    <div class="acts"><button class="btn btn-primary" id="ac_go" style="flex:1">
        ${existing?"Save":"Create account"}</button>
      <button class="btn btn-ghost" id="ac_cx">Cancel</button></div></div>`;
  mo(el.firstElementChild, {opacity:[0,1],y:[-6,0]}, {duration:.24,easing:[.22,1,.36,1]});
  $("ac_cx").onclick = () => el.innerHTML = "";
  $("ac_n").focus();
  $("ac_go").onclick = async () => {
    const name = $("ac_n").value.trim(), kind = $("ac_k").value;
    if (!name) { $("ac_e").textContent = "Give the account a name."; return; }
    $("ac_go").textContent = "…";
    try {
      const r = await api(existing ? `/api/portfolios/${existing.id}` : "/api/portfolios",
        { method: existing ? "PATCH" : "POST", headers:{"Content-Type":"application/json"},
          body: JSON.stringify({name, kind}) });
      S.acct = existing ? existing.id : (r.active || null);
      viewPortfolio();
    } catch (e) { $("ac_e").textContent = String(e.message).slice(0,100);
      $("ac_go").textContent = existing?"Save":"Create account"; }
  };
}

function openPosForm(pos, accId) {
  const el = $("posform"); if (!el) return;
  const edit = !!pos;
  const target = accId || pos?.account_id || (S.acct !== "all" ? S.acct : null);
  const accName = (S.accounts||[]).find(a=>a.id===target)?.name;
  el.innerHTML = `<div class="pform" style="margin:0 0 16px;max-width:460px">
    ${!target ? `<div class="err">Pick an account first — "All accounts" is a view, not a place to add to.</div>`
      : `<div class="muted" style="margin-bottom:2px">Adding to <b>${esc(accName||"account")}</b></div>`}
    <div class="r3">
      <input id="pf_t" class="inp" placeholder="Ticker" value="${pos?.ticker||""}" ${edit?"disabled":""} autocomplete="off">
      <input id="pf_q" class="inp" placeholder="Shares" value="${pos?.qty??""}" inputmode="decimal">
      <input id="pf_b" class="inp" placeholder="Avg cost" value="${pos?.basis??""}" inputmode="decimal">
    </div><div class="err" id="pf_e"></div>
    <div class="acts"><button class="btn btn-primary" id="pf_go" style="flex:1">${edit?"Save":"Add holding"}</button>
      <button class="btn btn-ghost" id="pf_cx">Cancel</button></div></div>`;
  mo(el.firstElementChild, { opacity:[0,1], y:[-6,0] }, { duration:.24, easing:[.22,1,.36,1] });
  $("pf_cx").onclick = () => el.innerHTML = "";
  (edit ? $("pf_q") : $("pf_t")).focus();
  $("pf_go").onclick = async () => {
    const t = ($("pf_t").value || pos?.ticker || "").trim().toUpperCase();
    const q = parseFloat($("pf_q").value), b = parseFloat($("pf_b").value);
    if (!t || !isFinite(q) || !isFinite(b) || q<=0 || b<=0) {
      $("pf_e").textContent = "Enter a ticker, share count and average cost."; return; }
    $("pf_go").textContent = "…";
    if (!target) { $("pf_e").textContent = "Pick an account first."; $("pf_go").textContent = edit?"Save":"Add holding"; return; }
    try { await api(edit?`/api/positions/${t}`:"/api/positions",
        { method: edit?"PATCH":"POST", headers:{"Content-Type":"application/json"},
          body: JSON.stringify({ticker:t,qty:q,basis:b,portfolio_id:target}) });
      await refreshAll(); viewPortfolio();
    } catch (err) { $("pf_e").textContent = String(err.message).slice(0,90);
      $("pf_go").textContent = edit?"Save":"Add holding"; }
  };
}

function wireAdd() {
  const el = $("addinput"); if (!el) return;
  el.onkeydown = async e => {
    if (e.key !== "Enter") return;
    const v = e.target.value.trim().toUpperCase(); if (!v) return;
    e.target.value = "";
    try { S.wl = (await jpost("/api/watchlist", {ticker:v})).watchlist;
      await refreshAll(); viewDashboard();
    } catch (err) {
      if (err.status === 401) {
        needAccount(`Create an account to keep ${v} on a watchlist. You can still `
                    + `look it up as a guest.`, {kind:"watch", ticker:v});
        return;
      }
      e.target.placeholder = `${v} not found`;
      setTimeout(()=>e.target.placeholder="Add ticker…",2200); }
  };
}


/* ═══════════════ daily brief ═══════════════
   Pure data plane: signals are ranked by how unusual a move is against the
   ticker's OWN volatility, so 2% on a quiet name outranks 2% on a jumpy one.
   Held positions get a 1.35x weight. Staying quiet is a valid result. */
const SIG_LABEL = { threshold:"big move", move:"move", volume:"volume", high:"52w high",
                    low:"52w low", earnings:"earnings", peer_gap:"vs peers", peer_move:"peer move" };


/* why a big move happened - every line of it comes from data, not a model */
function whyHTML(w) {
  if (!w) return "";
  const bits = [];
  if (w.read) bits.push(`<div class="wl-read">${esc(w.read)}</div>`);
  if (w.earnings) bits.push(`<div class="wl-row"><span class="wl-k">Earnings</span>
    <span>${esc(w.earnings.date)} · ${esc(w.earnings.result)}
    ${w.earnings.eps_actual!=null?`${num(w.earnings.eps_actual)} vs ${num(w.earnings.eps_estimate)} est`:""}</span></div>`);
  if (w.peer_average_pct != null) bits.push(`<div class="wl-row"><span class="wl-k">Peers</span>
    <span>avg ${pct(w.peer_average_pct)} — ${(w.peers||[]).map(p=>
      `<b class="${sgn(p.change_pct)}">${esc(p.ticker)} ${pct(p.change_pct)}</b>`).join(", ")}</span></div>`);
  if (w.volume) bits.push(`<div class="wl-row"><span class="wl-k">Volume</span><span>${esc(w.volume)}</span></div>`);
  (w.headlines||[]).forEach(h => bits.push(`<div class="wl-row"><span class="wl-k">News</span>
    <span>${esc(h.title)}${h.publisher?` <i>${esc(h.publisher)}</i>`:""}</span></div>`));
  return bits.length ? `<div class="whybox">${bits.join("")}</div>` : "";
}

function sigRows(signals) {
  if (!signals.length) return `<div class="empty">Nothing unusual across your tickers today.</div>`;
  return signals.map(g => `<div class="sigrow" data-go="${g.ticker}">
      <img src="${logo(g.ticker)}" alt="" loading="lazy">
      <div><div class="h">${esc(g.headline)}${g.held?` <span class="badge brand" style="margin-left:6px">held</span>`:""}</div>
        <div class="d">${esc(g.detail)}</div></div>
      <span class="sigkind ${g.kind}">${SIG_LABEL[g.kind]||g.kind}</span>
    </div>${whyHTML(g.why)}`).join("");
}
function sinceRows(since, day) {
  if (!since?.length) return "";
  return `<div class="section"><div class="section-h"><h3>Since you were last here</h3>
      <span class="r">${day?esc(day):""}</span></div>
    ${since.map(r=>`<div class="lrow" data-go="${r.ticker}" style="cursor:pointer">
      <span class="d mono">${r.ticker}</span>
      <span class="mono">$${num(r.from)} → $${num(r.to)}</span>
      <span class="badge ${sgn(r.pct)}">${pct(r.pct)}</span></div>`).join("")}</div>`;
}
/* market-moving news: rates, jobs, policy, conflict - shown without any model */
function marketNews(b) {
  const items = b?.market_headlines || [];
  if (!items.length) return "";
  const lv = b.index_levels || {};
  const chips = Object.entries(lv).map(([k,v]) =>
    `<span class="badge">${esc(k)} ${num(v.level, v.level>1000?0:2)}
      <span class="${v.change_pct>=0?"up":"dn"}">${pct(v.change_pct)}</span></span>`).join("");
  return `<div class="section"><div class="section-h"><h3>Moving the whole market</h3>
      <span class="r">index, rates and volatility feeds</span></div>
    ${chips?`<div class="lvchips">${chips}</div>`:""}
    <div class="mktnews">${items.map(hd=>`<div class="mnrow">
        <span class="feedtag">${esc((hd.source_feed||"").replace("^",""))}</span>
        <div><div class="h">${esc(hd.title)}</div>
          <div class="m">${esc(hd.publisher||"")}${hd.published?" · "+esc(hd.published):""}</div></div>
      </div>`).join("")}</div></div>`;
}

function quietBox(quiet) {
  if (!quiet?.length) return "";
  return `<div class="quietbox"><div class="qh">Checked, nothing to flag</div>
    <div class="qt">${quiet.map(q=>`<span class="badge ghost">${q}</span>`).join("")}</div>
    ${S.brief?.adjacent_checked?.length ? `<div class="muted" style="margin-top:9px">
       Plus ${S.brief.adjacent_checked.length} adjacent names watched for spillover:
       ${S.brief.adjacent_checked.slice(0,14).join(", ")}${S.brief.adjacent_checked.length>14?"…":""}</div>`:""}
    </div>`;
}
function briefInner(b) {
  const p = b.portfolio || {};
  // A guest has no book. "$— / −$0.00" reads as a broken number rather than an
  // absent one, so the two book tiles are replaced by what is actually true.
  const tiles = ME.guest
    ? [["Book","Not signed in","your holdings would show here"],
       ["Market","Covered","quotes, research and the agent work as a guest"],
       ["Flagged",String(b.signals.length),"market-wide only"]]
    : [["Book","$"+num(p.market_value),`${pct(p.pnl_pct)} all time`],
       ["Today",(p.day_change>=0?"+":"−")+"$"+num(Math.abs(p.day_change||0)),pct(p.day_change_pct)],
       ["Flagged",String(b.signals.length),
        `${b.checked.length} tracked + ${b.adjacent_checked?.length||0} adjacent`]];
  return `${threadsHTML(b.narrative, b.error)}
    ${tilesHTML(tiles)}
    <div class="section"><div class="section-h"><h3>Daily overview</h3>
      <span class="r">ranked by how unusual the move is, not how big</span></div>
      ${sigRows(b.signals)}</div>
    ${marketNews(b)}
    ${sinceRows(b.since_last, b.since_last_day)}
    ${quietBox(b.quiet)}`;
}

let briefInFlight = null;
async function loadBrief() {
  if (S.brief) return S.brief;
  // Cache the PROMISE, not just the result. The dashboard and the brief sheet
  // both ask for this on load, and a result-only cache is still null while the
  // first request is in the air - so both fired, and the curator ran twice for
  // one page view. That is double the tokens for identical output.
  if (briefInFlight) return briefInFlight;
  // with a key the curator narrates it; without one we still get the scanner
  briefInFlight = (S.llm
    ? api("/api/agent/brief", { method:"POST" }).catch(() => api("/api/brief"))
    : api("/api/brief"))
    .then(b => { S.brief = b; return b; })
    .finally(() => { briefInFlight = null; });
  return briefInFlight;
}

/* the curator's threads - each one must cite headlines we actually fetched */
function threadsHTML(n, err) {
  if (err) return `<div class="quietbox" style="border-color:rgba(250,178,25,.28)">
      <div class="qh" style="color:var(--warn)">Narrative unavailable</div>
      <div class="muted">${esc(err)}</div></div>`;
  if (!n?.threads?.length) return "";
  return `${n.summary ? `<div class="briefsum">${esc(n.summary)}
      <div class="disclaim">${esc(DISCLAIMER)}</div></div>` : ""}
    <div class="section"><div class="section-h"><h3>What it means</h3>
      <span class="r">written by the curator from the headlines below</span></div>
    ${n.threads.map(t => `<div class="thread">
      <div class="th">${esc(t.title||"")}</div>
      <div class="tb">${esc(t.body||"")}</div>
      <div class="tf">
        ${(t.tickers||[]).map(x=>`<span class="badge brand" data-go="${esc(x)}" style="cursor:pointer">${esc(x)}</span>`).join("")}
        ${(t.sources||[]).map(srcText => {
            const bad = (t.unverified_sources||[]).includes(srcText);
            return `<span class="src ${bad?"bad":""}" title="${esc(srcText)}">${bad?"⚠ ":""}${esc(srcText.slice(0,68))}${srcText.length>68?"…":""}</span>`;
          }).join("")}
      </div></div>`).join("")}</div>`;
}

async function viewBrief() {
  crumbs([{label:"Daily brief"}]);
  const v = $("views");
  v.innerHTML = `<div class="page"><div class="page-head">
      <div><div class="ttl">Daily brief</div><div class="sub" id="bsub">Loading…</div></div>
      <div class="acts"><button class="btn btn-sm btn-brand" id="askhere">Ask ${IC.arrow}</button></div>
    </div><div id="briefview"><div class="skel" style="height:200px"></div></div></div>`;
  try {
    const b = await loadBrief();
    $("bsub").textContent = b.llm_calls
      ? `${b.date} · curated from ${b.checked.length} tickers plus market, rates and sector feeds`
      : `${b.date} · set GEMINI_API_KEY to add the written summary`;
    $("briefview").innerHTML = briefInner(b);
    $$("#briefview [data-go]").forEach(el => el.onclick = () => location.hash = "#/t/"+el.dataset.go);
  } catch (e) {
    $("briefview").innerHTML = `<div class="empty">Couldn't build the brief: ${esc(e.message)}</div>`;
  }
  afterRender(v);
}

/* first visit of the day -> show it as a sheet */
const BRIEF_KEY = "monsoon.brief.seen";
async function maybeShowBrief() {
  let b; try { b = await loadBrief(); } catch { return; }
  const seen = localStorage.getItem(BRIEF_KEY);
  $("navdot").classList.toggle("on", seen !== b.date && b.signals.length > 0);
  if (seen === b.date) return;
  if (!b.signals.length && !b.since_last?.length && !b.narrative?.threads?.length) {  // nothing to say
    localStorage.setItem(BRIEF_KEY, b.date); return;
  }
  $("briefdate").textContent = `${b.date} · ${b.signals.length} flagged · ${b.checked.length} tracked`
    + (b.adjacent_checked?.length ? ` + ${b.adjacent_checked.length} adjacent` : "");
  $("briefnote").textContent = b.note;
  $("briefbody").innerHTML = briefInner(b);
  $$("#briefbody [data-go]").forEach(el => el.onclick = () => {
    closeBrief(); location.hash = "#/t/"+el.dataset.go; });
  $("briefsheet").classList.add("on");
  mo($("briefbox"), { opacity:[0,1], scale:[.96,1], y:[16,0] },
     { duration:.42, easing:[.22,1,.36,1] });
  mo($("briefbody").querySelectorAll(".tile,.sigrow"), { opacity:[0,1], y:[10,0] },
     { duration:.36, delay:stag(.04), easing:[.22,1,.36,1] });
}
function closeBrief() {
  const b = S.brief;
  if (b) localStorage.setItem(BRIEF_KEY, b.date);
  $("navdot").classList.remove("on");
  $("briefsheet").classList.remove("on");
}

/* ═══════════════ agent panel ═══════════════ */
const openAgent = on => { document.getElementById("app").classList.toggle("agent-open", on);
  $("agenttoggle").classList.toggle("on", on);
  setTimeout(()=>{ if (chart) { const el=$("chart");
    if (el?.clientWidth) chart.applyOptions({width:el.clientWidth}); chart.timeScale().fitContent(); } }, 340); };

function nodeHTML(name, meta, cls, why, sel, skp) {
  return `<div class="node ${cls}"><span class="nd"></span>
    <div class="nrow">${IC.chev}<span class="nname">${esc(name)}</span><span class="nmeta">${esc(meta)}</span></div>
    <div class="ndet">${(sel?.length||skp?.length)?`<div class="tools">
        ${(sel||[]).map(t=>`<span class="tc sel">${esc(t)}</span>`).join("")}
        ${(skp||[]).map(t=>`<span class="tc skp">${esc(t)}</span>`).join("")}</div>`:""}
      ${why?`<div class="why">${esc(why)}</div>`:""}</div></div>`;
}
function renderRun(run, running) {
  const el = $("nodes");
  if (!run) { el.innerHTML = `<div class="muted">No run yet — ask a question, or hit Analyze.</div>`; return; }
  const prev = el.querySelectorAll(".node").length;
  let html = "";
  for (const s of run.steps) {
    if (/\.(gather|select)$/.test(s.node)) continue;
    const f = run.findings.find(x => s.node.startsWith(x.domain + "."));
    html += nodeHTML(s.node.replace(".synthesize",""),
      f ? `${f.tools_used.length}/${f.tools_used.length+f.tools_skipped.length}` : (s.tokens?s.tokens+" tok":""),
      f && f.confidence==="unavailable" ? "skip" : "done",
      f ? f.skip_reason : s.detail, f?.tools_used, f?.tools_skipped);
  }
  if (running) html += nodeHTML("working…","","run","");
  el.innerHTML = html || `<div class="muted">no steps</div>`;
  el.querySelectorAll(".nrow").forEach(r => r.onclick = () => {
    const n=r.parentElement, open=n.classList.toggle("open"), d=n.querySelector(".ndet");
    if (animate) mo(d,{height: open?["0px",d.scrollHeight+"px"]:[d.scrollHeight+"px","0px"]},
                     {duration:.26,easing:[.22,1,.36,1]});
    else d.style.height = open?"auto":"0"; });
  mo([...el.querySelectorAll(".node")].slice(prev),
     {opacity:[0,1],x:[-6,0]},{duration:.3,delay:stag(.05),easing:[.22,1,.36,1]});
  $("runmeta").textContent = run.llm_calls!=null
    ? `${(run.latency_ms/1000).toFixed(1)}s · ${run.llm_calls} calls · ${run.total_tokens} tok` : "running…";
}
function renderAnswer(run) {
  const el = $("answer");
  if (!run?.answer) { el.innerHTML=""; return; }
  const warn = run.grounded===false
    ? `<div class="muted" style="color:var(--warn);margin-top:8px">Grounding: ${run.ungrounded_numbers.join(", ")} not in evidence</div>` : "";
  // a run that fell back says so - an answer to a different question is worse
  // than no answer, and worst of all when it looks complete
  const degraded = run.degraded
    ? `<div class="muted" style="color:var(--warn);margin-top:8px">${esc(run.degraded)}</div>` : "";
  el.innerHTML = `<div class="answer"><div class="top">
      <span class="sym">${esc((run.tickers||[]).join(" · "))}</span>
      ${run.grounded?`<span class="ok">✓ grounded</span>`:""}</div>
    <p>${esc(run.answer)}</p>${degraded}${warn}
    <div class="disclaim">${esc(run.disclaimer||DISCLAIMER)}</div>
    <button class="link" data-trace="1">Show work ${IC.arrow}</button></div>`;
  el.querySelectorAll("[data-trace]").forEach(b=>b.onclick=openTrace);
  mo(el.firstElementChild,{opacity:[0,1],y:[8,0],scale:[.98,1]},{duration:.4,easing:[.22,1,.36,1]});
}
const busy = on => { $("rst").textContent = on?"running":"idle"; $("rdot").classList.toggle("live",on); };

async function streamAsk(question, tickers) {
  openAgent(true); busy(true); $("answer").innerHTML=""; renderRun({steps:[],findings:[]},true);
  const acc = {steps:[],findings:[]};
  try {
    const r = await fetch("/api/agent/ask/stream",{method:"POST",
      headers:{"Content-Type":"application/json"},body:JSON.stringify({question})});
    if (!r.ok) throw new Error(await r.text());
    const rd = r.body.getReader(), dec = new TextDecoder(); let buf="";
    for(;;){ const {value,done} = await rd.read(); if(done) break;
      buf += dec.decode(value,{stream:true});
      const parts = buf.split(/\r?\n\r?\n/); buf = parts.pop();
      for (const p of parts) {
        const ev = (p.match(/^event:\s*(.*)$/m)||[])[1];
        const dl = p.split(/\r?\n/).filter(l=>l.startsWith("data:")).map(l=>l.slice(5).trim()).join("");
        if (!dl) continue;
        let d; try { d = JSON.parse(dl); } catch { continue; }
        if (ev==="node"){ acc.steps.push(...(d.steps||[])); acc.findings.push(...(d.findings||[])); renderRun(acc,true); }
        else if (ev==="done"){ S.run=d; renderRun(d,false); renderAnswer(d); }
        else if (ev==="error") $("answer").innerHTML=`<div class="muted" style="color:var(--neg)">${esc(d.error)}</div>`;
      } }
  } catch(e){ $("answer").innerHTML=`<div class="muted" style="color:var(--neg)">${esc(e.message)}</div>`; }
  busy(false);
}

async function runAnalyze() {
  const domain = TAB_DOMAIN[S.tab] || "fundamentals";
  const b = $("analyze"); b.disabled=true; b.classList.add("busy"); openAgent(true); busy(true);
  try {
    const r = await api("/api/agent/analyze",{method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({ticker:S.cur,domain,question:`Looking at ${S.cur}'s ${S.tab}, what stands out?`})});
    if (r.finding) {
      S.tabAgent[S.cur+":"+domain] = r.finding;
      S.run = { question:`analyze ${domain} · ${S.cur}`, steps:r.steps, findings:[r.finding],
                answer:r.finding.narrative, tickers:[S.cur],
                llm_calls:r.steps.filter(s=>s.llm).length,
                total_tokens:r.steps.reduce((a,s)=>a+s.tokens,0),
                latency_ms:r.steps.reduce((a,s)=>a+s.latency_ms,0), grounded:null };
      renderRun(S.run,false); renderAnswer(S.run); await renderTab();
    }
  } catch(e){ $("answer").innerHTML=`<div class="muted" style="color:var(--neg)">${esc(e.message)}</div>`; }
  b.disabled=false; b.classList.remove("busy"); busy(false);
}

function openTrace() {
  const run = S.run, box = $("tbody");
  if (!run) box.innerHTML = `<div class="empty">No run yet.</div>`;
  else {
    $("tsub").textContent = `${run.question||""} · ${(run.latency_ms/1000).toFixed(1)}s · ${run.llm_calls} LLM calls · ${run.total_tokens} tokens`;
    box.innerHTML = `<table><thead><tr><th>Node</th><th>Detail</th><th>Tools</th><th>Tokens</th><th>Latency</th><th>LLM</th></tr></thead>
      <tbody>${run.steps.map(s=>`<tr><td style="color:var(--b2);font-weight:600">${esc(s.node)}</td>
        <td style="text-align:left;color:var(--muted-foreground)">${esc(s.detail||"")}</td>
        <td class="mono">${s.tools||"—"}</td><td class="mono">${s.tokens||0}</td>
        <td class="mono">${(s.latency_ms/1000).toFixed(2)}s</td>
        <td><span class="badge ${s.llm?"brand":"ghost"}">${s.llm?"yes":"no"}</span></td></tr>`).join("")}</tbody></table>
      ${run.findings.map(f=>`<div class="section"><div class="section-h"><h3>${esc(f.domain)} evidence</h3>
        <span class="r">${f.tools_used.length} used · ${f.tools_skipped.length} skipped</span></div>
        <pre>${esc(JSON.stringify(f.evidence.reduce((a,e)=>(a[e.tool]=e.data,a),{}),null,1)).slice(0,3000)}</pre></div>`).join("")}`;
  }
  $("trace").classList.add("on");
  mo($("tbox"),{opacity:[0,1],scale:[.97,1],y:[10,0]},{duration:.3,easing:[.22,1,.36,1]});
}
const closeTrace = () => $("trace").classList.remove("on");

/* ═══════════════ data + router ═══════════════ */
async function refreshAll() {
  S.wl = (await api("/api/watchlist")).watchlist;
  if (S.wl.length) {
    const d = await api(`/api/quotes?symbols=${S.wl.join(",")}`);
    d.quotes.forEach(q => S.q[q.symbol] = q);
    S.sparks = (await api(`/api/sparklines?symbols=${S.wl.join(",")}`)).sparklines;
  }
  S.pf = await api("/api/portfolio").catch(()=>null);
  pfSummary();
}

async function route() {
  document.getElementById("views").scrollTop = 0;   // new destination starts at the top
  const h = (location.hash || "#/dashboard").slice(2);
  const [head, arg] = h.split("/");
  $$(".navitem").forEach(n => n.classList.toggle("on",
    n.dataset.route === (head==="t" ? "ticker" : head)));
  if (head === "t" && arg) {
    S.route = "ticker";
    const syms = [...new Set(decodeURIComponent(arg).toUpperCase()
      .split(",").map(x=>x.trim()).filter(Boolean))].slice(0, 8);
    await viewResearch(syms);
  }
  else if (head === "brief") { S.route="brief"; await viewBrief(); }
  else if (head === "portfolio") { S.route="portfolio"; await viewPortfolio(); }
  else { S.route="dashboard"; await viewDashboard(); }
  syncAsk();
  pfSummary();
}

// the Research tab is not pinned to one symbol - it reopens wherever you were
(() => { const rl = document.querySelector('.navitem[data-route="ticker"]');
         if (rl) rl.setAttribute("href", "#/t/" + lastTicker()); })();
addEventListener("hashchange", route);

/* ─── sign-in wiring ─── */
$$(".authtabs button").forEach(b => b.onclick = () => authMode(b.dataset.mode));
$("authswitch").onclick = e => { const g = e.target.dataset?.go; if (g) authMode(g); };
$("authcancel").onclick = closeAuth;
$("authsheet").onclick = e => { if (e.target.id === "authsheet") closeAuth(); };
$("authform").onsubmit = async e => {
  e.preventDefault();
  const btn = $("authsubmit"), was = btn.textContent;
  const username = $("authuser").value.trim(), password = $("authpass").value;
  authErr(""); btn.disabled = true; btn.textContent = "…";
  try {
    await jpost(`/api/auth/${AUTH_MODE === "register" ? "register" : "login"}`,
                {username, password});
    location.reload();                 // simplest correct reload of every view
  } catch (err) {
    authErr(err.message);
    btn.disabled = false; btn.textContent = was;
    $("authpass").select();
  }
};
$("agenttoggle").onclick = () => openAgent(!document.getElementById("app").classList.contains("agent-open"));
$("agentclose").onclick = () => openAgent(false);
$("tclose").onclick = closeTrace;
$("briefclose").onclick = closeBrief;
$("briefopen").onclick = () => { closeBrief(); location.hash = "#/brief"; };
$("briefsheet").onclick = e => { if (e.target.id === "briefsheet") closeBrief(); };
$("trace").onclick = e => { if (e.target.id==="trace") closeTrace(); };
addEventListener("keydown", e => { if (e.key==="Escape") { closeTrace(); closeBrief(); closeAuth(); } });
$("askform").onsubmit = e => { e.preventDefault();
  const v = $("ask").value.trim();
  if (v) { const sc = askScope(); streamAsk(sc.pre(v), sc.tickers); $("ask").value=""; } };

api("/build").then(b => $("buildstamp").textContent = b.build.slice(-6)).catch(()=>{});
await loadMe();
await replayResume();
const health = await api("/api/health").catch(()=>({}));
S.llm = !!health.llm_configured;
if (!S.llm) {
  $("answer").innerHTML = `<div class="muted" style="color:var(--warn)">Agent disabled — set <span class="mono">GEMINI_API_KEY</span> and restart. The dashboard works without it.</div>`;
  $("rst").textContent = "no key";
}
await refreshAll();
renderRun(null,false);
await route();
maybeShowBrief();
setInterval(async () => { if (!S.wl.length) return;
  const d = await api(`/api/quotes?symbols=${S.wl.join(",")}`).catch(()=>null);
  if (!d) return; d.quotes.forEach(q=>S.q[q.symbol]=q); pfSummary(); }, 30000);
