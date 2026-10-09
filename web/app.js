/* Monsoon — client. Three routed views over one API. Every value is live. */
import * as CH from "./charts.js";

let animate = null, stagger = null;
try { const m = await import("https://cdn.jsdelivr.net/npm/motion@11.18.2/+esm");
      animate = m.animate; stagger = m.stagger; }
catch (e) { console.warn("motion unavailable", e); }
const REDUCED = (() => { try { return matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; } })();
const mo = (el, kf, op) => { try {
    if (REDUCED || !animate || !el || (el.length === 0)) return null;
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
const sgn = v => v==null||isNaN(v) ? "" : v>=0 ? "up" : "dn";
const usd = v => v==null||isNaN(v) ? "—" : "$" + abbr(v);
const usdp = (v, d=2) => v==null||isNaN(v) ? "—" : "$" + num(v, d);
/* a symbol is letters, digits and . ^ = - ; anything else in a URL is not one,
   and it goes into markup, so it is rejected here rather than escaped later */
const SYM_RE = /^[A-Z0-9][A-Z0-9.^=-]{0,11}$/;
const cleanSyms = list => [...new Set(list.map(x => x.trim().toUpperCase()).filter(x => SYM_RE.test(x)))];
const LOGO_V = 2;
const logo = s => url(`/api/logo/${encodeURIComponent(s)}?v=${LOGO_V}`);
const IC = {
  edit:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>`,
  del:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>`,
  x:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>`,
  arrow:`<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>`,
  refresh:`<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/></svg>`,
  spark:`<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M10.5 3.2l1.75 4.8 4.8 1.75-4.8 1.75-1.75 4.8-1.75-4.8L4 9.75l4.75-1.75z"/><path d="M17.8 14.4l.85 2.3 2.3.85-2.3.85-.85 2.3-.85-2.3-2.3-.85 2.3-.85z"/></svg>`,
  chev:`<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>`,
};

const DISCLAIMER = "Informational only, not financial advice. Monsoon summarises public data and cannot account for your circumstances.";
const LAST_TICKER = "monsoon.lastTicker";
// null = never saved, so default to NVDA; "" = you closed every ticker, so stay empty
const lastTicker = () => { try { const v = localStorage.getItem(LAST_TICKER);
  return v == null ? "NVDA" : cleanSyms(v.split(",")).join(","); } catch { return "NVDA"; } };
const S = { route:"dashboard", cur:null, wl:[], q:{}, sparks:{}, pf:null,
            tf:"1M", tab:"overview", show:{MA:true,Vol:true},
            run:null, tabAgent:{}, pending:[], llm:false, brief:null, acct:null, accounts:[], kinds:[],
            basket:[], picked:new Set(), focus:null, compare:null };

/* Where the API lives.

   Same origin by default, which is the case both when FastAPI serves this file
   itself and when Vercel proxies /api/* through to Render - the browser sees
   one origin either way, so the session cookie stays same-site and SameSite=Lax
   keeps protecting against cross-site POSTs.

   Setting window.MONSOON_API (see index.html) points the client at a different
   origin instead. That path needs the server on SameSite=None with
   allow_credentials=True, which gives up the Lax CSRF defence - so it exists as
   an escape hatch, not as the recommended setup. */
const API = (globalThis.MONSOON_API || "").replace(/\/$/, "");
const url = path => API + path;

/* A free Render service sleeps after 15 idle minutes and takes about a minute
   to wake. Behind a proxy that first request fails rather than waits, so the
   page would load and every call under it would error - looking broken when it
   is only asleep. Retry the transient shapes (network error, 502/503/504) with
   backoff, and say so on screen instead of failing silently. */
const WAKE_MS = 90_000, WAKE_CODES = new Set([502, 503, 504]);
let waking = false;

function wakingBanner(on) {
  if (on === waking) return;
  waking = on;
  let el = $("waking");
  if (on && !el) {
    el = document.createElement("div");
    el.id = "waking";
    el.className = "guestbar";
    el.style.cssText = "position:fixed;left:50%;transform:translateX(-50%);" +
      "top:14px;z-index:95;max-width:min(560px,92vw)";
    el.innerHTML = `<span>Waking the server &mdash; it sleeps when idle and takes
      about a minute. Nothing is wrong.</span>`;
    document.body.appendChild(el);
  } else if (!on && el) { el.remove(); }
}

async function api(path, opts) {
  const started = Date.now();
  let wait = 1500;
  // A POST that times out at the proxy may already have run on the server:
  // retrying "add 10 NVDA" would average the lot in twice. Only reads retry.
  const idempotent = !opts?.method || /^(GET|HEAD)$/i.test(opts.method) || opts.retry;
  for (;;) {
    try {
      return await apiOnce(path, opts);
    } catch (e) {
      const transient = idempotent && (e.status === undefined || WAKE_CODES.has(e.status)) && !e.parse;
      if (!transient || Date.now() - started > WAKE_MS) { wakingBanner(false); throw e; }
      wakingBanner(true);
      await new Promise(r => setTimeout(r, wait));
      wait = Math.min(wait * 1.6, 8000);
    }
  }
}

async function apiOnce(path, opts) {
  const r = await fetch(url(path), {credentials: "include", ...opts});
  if (r.ok) wakingBanner(false);
  if (!r.ok) {
    let msg = "";
    try { const j = JSON.parse(await r.text()); msg = j.detail || j.error || ""; } catch {}
    const e = new Error((msg || `request failed (${r.status})`).slice(0,200));
    e.status = r.status;
    throw e;
  }
  try { return await r.json(); }
  catch { const e = new Error("The server sent something that wasn't JSON."); e.status = r.status; e.parse = true; throw e; }
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
    if (a === "out") { await fetch(url("/api/auth/logout"), {method:"POST", credentials:"include"}); location.reload(); }
    if (a === "pw") changePassword();
  };
  $("acct").appendChild(m);
  setTimeout(() => addEventListener("click", closeAcctMenu, {once:true}), 0);
}

/* Deliberately a prompt pair rather than a sheet: changing a password is rare,
   and a rarely-used form is a rarely-tested form. */
function changePassword() {
  ["pwcur", "pwnew", "pwnew2"].forEach(id => $(id).value = "");
  $("pwerr").textContent = "";
  $("pwsheet").classList.add("on");
  setTimeout(() => $("pwcur").focus(), 40);
}
const closePw = () => $("pwsheet").classList.remove("on");
$("pwcx").onclick = closePw;
$("pwsheet").onclick = e => { if (e.target.id === "pwsheet") closePw(); };
$("pwbox").onsubmit = async e => {
  e.preventDefault();
  const current = $("pwcur").value, next = $("pwnew").value;
  if (next !== $("pwnew2").value) { $("pwerr").textContent = "The new passwords don't match."; return; }
  const b = $("pwgo"); b.disabled = true;
  try {
    const r = await jpost("/api/auth/password", {current, new: next});
    closePw();
    toast(r.other_sessions_revoked
      ? `Password changed. ${r.other_sessions_revoked} other session(s) signed out.` : "Password changed.", "ok");
  } catch (err) { $("pwerr").textContent = err.message; }
  b.disabled = false;
};

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
let chartRO = null;
function buildChart() {
  const el = $("chart");
  if (!el || !window.LightweightCharts) return;
  try { chartRO?.disconnect(); chart?.remove(); } catch {}
  const pro = PRO(), ink = pro ? cssv("--subtle-foreground") : "#8d95a6";
  const grid = pro ? cssv("--border-subtle") : "rgba(255,255,255,.045)";
  const edge = pro ? cssv("--border") : "rgba(255,255,255,.08)";
  const hair = pro ? (LIGHT() ? "rgba(15,23,42,.35)" : "rgba(255,255,255,.3)") : "rgba(255,255,255,.25)";
  const lab = pro ? cssv("--foreground") : "#1a1d28";
  chart = LightweightCharts.createChart(el, {
    width: el.clientWidth||800, height: el.clientHeight||340,
    layout:{background:{color:"transparent"},textColor:ink,fontSize:pro ? 11 : 10,
            fontFamily: pro ? "Inter, system-ui, sans-serif" : "JetBrains Mono, monospace"},
    grid:{vertLines:{color: pro ? "transparent" : grid},horzLines:{color:grid}},
    rightPriceScale:{borderColor:edge,scaleMargins:{top:.1,bottom:.26}},
    timeScale:{borderColor:edge,rightOffset:3,barSpacing:9,
               fixLeftEdge:true,fixRightEdge:true},
    crosshair:{mode:0,
      vertLine:{color:hair,width:1,style:3,labelBackgroundColor:lab},
      horzLine:{color:hair,width:1,style:3,labelBackgroundColor:lab}},
    handleScale:false, handleScroll:false });
  cs = chart.addCandlestickSeries({upColor:CH.C.pos,downColor:CH.C.neg,
    borderUpColor:CH.C.pos,borderDownColor:CH.C.neg,
    wickUpColor:"rgba(25,158,112,.65)",wickDownColor:"rgba(230,103,103,.65)"});
  vs = chart.addHistogramSeries({priceScaleId:"",priceFormat:{type:"volume"}});
  vs.priceScale().applyOptions({scaleMargins:{top:.84,bottom:0}});
  maA = chart.addLineSeries({color:CH.C.s3,lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
  maB = chart.addLineSeries({color:CH.C.s2,lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false});
  const mine = chart;
  chartRO = new ResizeObserver(()=>{ if(!el.clientWidth || chart !== mine) return;
    chart.applyOptions({width:el.clientWidth,height:el.clientHeight});
    chart.timeScale().fitContent(); });
  chartRO.observe(el);
}
const sma = (b,n) => b.length<n ? [] : b.map((x,i)=> i<n-1 ? null
  : ({time:x.t, value:+(b.slice(i-n+1,i+1).reduce((a,y)=>a+y.c,0)/n).toFixed(2)})).filter(Boolean);
async function drawChart() {
  if (!chart || !S.cur) return;
  const [period,interval] = TF[S.tf];
  const want = S.cur, wantTf = S.tf;
  let bars; try { bars = await getBars(S.cur, period, interval); }
  catch { return; }
  if (S.cur !== want || S.tf !== wantTf) return;   // a later click already won
  if (!bars?.length) return;
  cs.setData(bars.map(b=>({time:b.t,open:b.o,high:b.h,low:b.l,close:b.c})));
  vs.setData(S.show.Vol ? bars.map(b=>({time:b.t,value:b.v,
    color:b.c>=b.o?"rgba(25,158,112,.24)":"rgba(230,103,103,.24)"})) : []);
  maA.setData(S.show.MA ? sma(bars, Math.min(50, Math.max(3, bars.length>>2))) : []);
  maB.setData(S.show.MA ? sma(bars, Math.min(200, Math.max(5, bars.length>>1))) : []);
  chart.applyOptions({timeScale:{timeVisible:/m|h/.test(interval)}});
  requestAnimationFrame(()=>chart.timeScale().fitContent());
  if (PRO()) wireOhlc(bars);
}

/* ─────────────── shared bits ─────────────── */
function quoteRow(sym) { return S.q[sym] || {}; }
/* the agent panel is global - scope the question to whatever view you are on */
function askScope() {
  if (S.route === "ticker") {
    // what you are looking at is CONTEXT, not a constraint: "how does it
    // compare with AMD?" on the NVDA page must still be allowed to fetch AMD
    // The ticked tickers, in the order they are open, focused one first. A
    // ticker you unticked is not "looked at"; with nothing ticked, the one on
    // screen is.
    const picks = (S.basket || []).filter(t => S.picked?.has(t));
    const ctx = picks.length ? [...picks.filter(t => t === S.cur), ...picks.filter(t => t !== S.cur)]
                             : (S.cur ? [S.cur] : []);
    const who = ctx.length <= 1 ? (ctx[0] || "a ticker")
      : ctx.length <= 3 ? ctx.slice(0, -1).join(", ") + " and " + ctx.at(-1)
      : `${ctx.slice(0, 2).join(", ")} and ${ctx.length - 2} more`;
    return { ph: `Ask about ${who}…`,
             pre: q => q, context: ctx, label: ctx.length ? `Looking at ${ctx.join(", ")}` : "" };
  }
  if (S.route === "brief") {
    const chk = S.brief?.checked || [];
    return { ph: "Ask about today's brief…", label: "Today's brief",
             pre: q => chk.length ? `About today's brief across ${chk.join(", ")}: ${q}` : q };
  }
  if (S.route === "portfolio")
    return { ph: "Ask about your portfolio…", label: ME.guest ? "" : "Your portfolio",
             pre: q => ME.guest ? q : `About MY PORTFOLIO "${S.pf?.portfolio_name||""}" (holdings: ${(S.pf?.positions||[]).map(p=>`${p.qty} ${p.ticker} @ ${p.basis}${p.account?" in "+p.account:""}`).join(", ") || "none"}): ${q}` };
  if (!S.wl.length) return { ph: "Ask about any stock or the market…", pre: q => q };
  return { ph: "Ask about your watchlist or any stock…", label: "Your watchlist",
           pre: q => `About my watchlist (${S.wl.join(", ")}): ${q}` };
}
function syncAsk() {
  const a = $("ask"); if (!a) return;
  const sc = askScope();
  a.placeholder = sc.ph;
  const l = $("askscope"); if (l) { l.textContent = sc.label || ""; l.classList.toggle("on", !!sc.label); }
  if (!T.turns.length) renderThread(false);         // suggestions follow the view
}

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
  `<div class="tile"><div class="k">${esc(k)}</div><div class="v mono" title="${esc(String(v).replace(/<[^>]*>/g,""))}">${v}</div><div class="s">${s||""}</div></div>`).join("")}</div>`;

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
      <span class="r">${!b.checked.length ? "market-wide · " + sigs.length + " flagged"
        : `${sigs.length} flagged · ${b.checked.length} tracked${
        b.adjacent_checked?.length?` + ${b.adjacent_checked.length} adjacent`:""}`}</span>
      <a class="btn btn-sm btn-ghost" href="#/brief">Full brief</a></div>
    <div class="panel-b" style="display:grid;gap:8px">
      ${sigs.length ? sigs.map(g=>`<div class="sigline" data-go="${esc(g.ticker)}" tabindex="0">
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
  return sorted.map(r=>`<tr data-go="${esc(r.sym)}" data-sym="${esc(r.sym)}" tabindex="0">
    <td><div class="wname"><img src="${logo(r.sym)}" alt="" loading="lazy">
      <div><div class="s">${r.sym}</div><div class="n">${esc(r.name||"")}</div></div></div></td>
    <td class="mono px" style="font-weight:600">${num(r.price)}</td>
    <td class="mono chg ${sgn(r.change_pct)}" style="font-weight:600">${pct(r.change_pct)}</td>
    <td><div class="wspark" data-spark="${r.sym}" style="margin-left:auto"></div></td>
    <td class="mono">${usd(r.market_cap)}</td>
    <td class="mono">${num(r.pe,1)}</td>
    <td>${r.held?`<span class="badge brand">held</span>`:""}</td></tr>`).join("");
}

/* what a guest (or an empty watchlist) sees instead of a table of headers */
const POPULAR = ["NVDA","AAPL","MSFT","AMZN","GOOGL","META","AVGO","TSLA"];

async function viewDashboard(nav) {
  if (PRO()) return viewDashboardPro(nav);
  crumbs([{label:"Dashboard"}]);
  const v = $("views");
  const pf = S.pf;
  const held = new Set((pf?.positions||[]).map(p=>p.ticker));
  const demo = !S.wl.length;
  const list = demo ? POPULAR : S.wl;
  if (demo && POPULAR.some(x => !S.q[x])) {
    try {
      const [d, sp] = await Promise.all([api(`/api/quotes?symbols=${POPULAR.join(",")}`),
                                        api(`/api/sparklines?symbols=${POPULAR.join(",")}`)]);
      d.quotes.forEach(q => S.q[q.symbol] = q); Object.assign(S.sparks, sp.sparklines);
    } catch {}
    if (nav !== undefined && nav !== NAV.seq) return;
  }
  const rows = list.map(x => ({ sym:x, held:held.has(x), ...quoteRow(x) }))
                   .filter(r => r.price != null);

  v.innerHTML = `<div class="page">
    <div class="page-head">
      <div><div class="ttl">Dashboard</div>
        <div class="sub">${demo ? "The broad market and the names most people are watching"
                                 : `The broad market and your ${rows.length} tracked tickers`}</div></div>
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
      <div class="panel-h"><h4>${demo ? "Most watched" : "Watchlist"}</h4>
        <span class="r">${demo ? (ME.guest ? "sign in to keep your own list" : "add a ticker above to start your own")
                               : `live · ${rows.length} tickers in 1 request`}</span></div>
      <table class="wtable wl"><thead><tr>
        ${[["sym","Symbol"],["price","Last"],["change_pct","Change"],[null,"30-day"],
           ["market_cap","Mkt cap"],["pe","P/E"],[null,""]]
          .map(([k,label])=>`<th ${k?`data-sort="${k}" class="sortable${wlSort.key===k?" on":""}"`:""}>${label}${
            k&&wlSort.key===k?`<span class="caret">${wlSort.dir<0?"▾":"▴"}</span>`:""}</th>`).join("")}
      </tr></thead><tbody id="wlbody">${wlRows(rows) || `<tr><td colspan="7"><div class="empty">
        Prices are unavailable right now.</div></td></tr>`}</tbody></table>
    </div></div></div>`;

  wireAdd();
  if ($("gbsign")) $("gbsign").onclick = () => openAuth("register");
  loadIndices();
  const paintSparks = () => $$("[data-spark]").forEach(el => {
    const val = S.sparks[el.dataset.spark] || [];
    if (val.length>1) CH.sparkline(el, val, val.at(-1)>=val[0]); });
  const wireRows = () => $$("#wlbody [data-go], .sigline[data-go]").forEach(el => {
    el.onclick = () => location.hash = "#/t/"+el.dataset.go;
    el.onkeydown = e => { if (e.key === "Enter") el.click(); }; });
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
       {duration:.32,delay:stag(.04),easing:[.22,1,.36,1]}); })
    .catch(() => { const w = $("sigwrap"); if (w) w.innerHTML = ""; });
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
  return `<div class="agentbox"><div class="ah"><span class="dot"></span>${esc(DOMAIN_LABEL[f.domain]||f.domain)} specialist · ${f.tools_used.length} tools</div>
    ${paras(f.narrative)}
    <div class="disclaim">${esc(DISCLAIMER)}</div>
    <button class="link" data-trace="${esc(domain)}">Show work ${IC.arrow}</button></div>`;
}

const TABS = {
  overview: async t => {
    const o = await api(`/api/overview/${t}`);
    const p = x => x==null ? "—" : num(x*100,1)+"%";
    if (PRO()) return kvHTML([
        ["Market cap", usd(o.market_cap)], ["P/E (TTM)", num(o.pe,1)],
        ["Forward P/E", num(o.forward_pe,1)], ["Price / book", num(o.price_to_book,1)],
        ["Gross margin", p(o.gross_margin), "TTM"], ["Operating margin", p(o.operating_margin), "TTM"],
        ["Net margin", p(o.net_margin), "TTM"], ["Return on equity", p(o.roe), "TTM"],
        ["Revenue growth", o.revenue_growth!=null ? pct(o.revenue_growth*100) : "—", "YoY"],
        ["Debt / equity", o.debt_to_equity==null ? "—" : num(o.debt_to_equity/100,2)+"×",
          o.cash!=null&&o.debt!=null ? (o.cash>=o.debt ? `net cash ${usd(o.cash-o.debt)}` : `net debt ${usd(o.debt-o.cash)}`) : ""],
        ["Free cash flow", usd(o.fcf), "TTM"], ["Dividend yield", o.dividend_yield ? num(o.dividend_yield,2)+"%" : "—"],
        ["Employees", o.employees ? Number(o.employees).toLocaleString() : "—"],
        ["Sector", esc(o.sector || "—"), o.industry || ""]])
      + `<div class="section"><div class="panel"><div class="panel-h"><h4>About ${esc(t)}</h4></div>
          <div class="panel-b"><div class="prose">${o.summary ? esc(o.summary) : "No profile available."}</div></div>
        </div></div>` + agentSlot("fundamentals");
    return tilesHTML([
      ["Market cap",usd(o.market_cap),""],["P/E",num(o.pe,1),"trailing"],
      ["Fwd P/E",num(o.forward_pe,1),""],["P/B",num(o.price_to_book,1),""],
      ["Net margin",p(o.net_margin),"TTM"],["Op margin",p(o.operating_margin),"TTM"],
      // Yahoo reports debt/equity in percent (16.97 = 0.17x); shown as the ratio
      ["ROE",p(o.roe),"TTM"],["Debt/Equity",o.debt_to_equity==null?"—":num(o.debt_to_equity/100,2)+"×",
        o.cash!=null&&o.debt!=null?(o.cash>=o.debt?`net cash ${usd(o.cash-o.debt)}`:`net debt ${usd(o.debt-o.cash)}`):""]])
      + `<div class="section"><div class="panel"><div class="panel-h"><h4>Profile</h4>
          <span class="r">${esc(o.sector||"")}${o.industry?" · "+esc(o.industry):""}</span></div>
          <div class="panel-b"><div class="prose">${o.summary ? esc(o.summary.length > 620 ? o.summary.slice(0,620).replace(/\s+\S*$/,"") + "…" : o.summary)
                                  : "No profile available."}</div></div>
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
          ["Revenue expected", usd(u.revenue_estimate), u.revenue_low!=null?`range ${usd(u.revenue_low)}–${usd(u.revenue_high)}`:""],
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
          <td class="mono">${usd(q.revenue)}</td><td class="mono">${usd(q.gross_profit)}</td>
          <td class="mono">${usd(q.operating_income)}</td><td class="mono">${usd(q.net_income)}</td>
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
        <div class="h">${/^https?:\/\//i.test(i.url||"")?`<a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}</a>`:esc(i.title)}</div>
        <div class="m">${esc(i.publisher||"")}${i.published?" · "+esc(String(i.published).slice(0,10)):""}</div></div>
        <span class="badge ${i.mentions_issuer?"brand":"ghost"}">${i.mentions_issuer?esc(t):"unrelated"}</span></div>`).join("")}
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
      ["Consensus", esc(c.recommendationKey||"—").replace(/_/g," ").replace(/^\w/, m => m.toUpperCase()),
        c.numberOfAnalystOpinions?c.numberOfAnalystOpinions+" analysts":""],
      ["Low target", usdp(g.targetLowPrice), ""],
      ["Mean target", usdp(g.targetMeanPrice), up!=null?pct(up)+" vs last price":""],
      ["High target", usdp(g.targetHighPrice), ""]])
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

async function viewResearch(symbols, nav) {
  // A ticker you just added is one you mean to look at: it starts ticked.
  // Tickers already open keep whatever you set them to.
  const prev = S.basket || [];
  S.basket = symbols;
  S.cur = S.focus && symbols.includes(S.focus) ? S.focus : symbols[0];
  S.picked = new Set([...(S.picked || [])].filter(t => symbols.includes(t)));
  symbols.filter(t => !prev.includes(t)).forEach(t => S.picked.add(t));
  if (!S.picked.size) symbols.forEach(t => S.picked.add(t));
  try { localStorage.setItem(LAST_TICKER, symbols.join(",")); } catch {}
  const rl = document.querySelector('.navitem[data-route="ticker"]');
  if (rl) rl.setAttribute("href", "#/t/" + symbols.join(","));

  crumbs([{label:"Research", href:"#/dashboard"},
          {label: symbols.length > 1 ? `${symbols.length} tickers` : symbols[0] || "Empty"}]);

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
    ${symbols.length > 1 ? `<div class="section" id="overlaywrap">
      <button class="btn btn-sm" id="showOverlay">Compare performance</button></div>` : ""}
    <div class="section" id="detailwrap"></div>
  </div>`;

  wireLookup(true);
  $("analyzeSel").onclick = openComposer;

  if (!symbols.length) {
    $("panels").outerHTML = `<div class="empty">No tickers open. Add one with the search above.</div>`;
    S.compare = null; syncSel(); afterRender(v); return;
  }

  let cmp;
  try { cmp = await api(`/api/compare?symbols=${symbols.map(encodeURIComponent).join(",")}&period=6mo`); }
  catch (e) { if (nav === NAV.seq && $("panels")) $("panels").innerHTML = `<div class="empty">Couldn't load: ${esc(e.message)}</div>`; return; }
  if (nav !== undefined && nav !== NAV.seq) return;            // you have already moved on
  S.compare = cmp;
  const by = Object.fromEntries(cmp.rows.map(r => [r.symbol, r]));

  if (PRO()) {
    const pg = $("panels"); pg.className = ""; pg.innerHTML = qBarHTML(symbols, cmp);
    $$("[data-qfocus]").forEach(c => c.onclick = async e => {
      if (e.target.closest("input,[data-close]")) return;
      if (S.cur === c.dataset.qfocus) return;
      S.focus = S.cur = c.dataset.qfocus;
      $$("[data-qfocus]").forEach(x => x.classList.toggle("on", x.dataset.qfocus === S.cur));
      await renderDetail(); syncAsk(); });
    if ($("showOverlay2")) $("showOverlay2").onclick = () => { renderOverlay(cmp, symbols);
      $("overlaywrap")?.scrollIntoView({ behavior: "smooth", block: "start" }); };
  } else
  $("panels").innerHTML = symbols.map((t, i) => {
    const r = by[t] || {};
    const col = PANEL_COLORS[i % PANEL_COLORS.length];
    return `<div class="tpanel ${S.picked.has(t)?"picked":""} ${t===S.cur?"focus":""}" data-panel="${esc(t)}">
      <div class="tp-head">
        <label class="tick"><input type="checkbox" data-pick="${esc(t)}" aria-label="Include ${esc(t)} in analysis" ${S.picked.has(t)?"checked":""}>
          <span class="box" style="--c:${col}"></span></label>
        <img src="${logo(t)}" alt="" loading="lazy">
        <div class="tp-id"><div class="s">${esc(t)}</div>
          <div class="n">${esc(r.name||"")}</div></div>
        <button class="tp-x" data-close="${esc(t)}" title="Close ${esc(t)}" aria-label="Close ${esc(t)}">${IC.x}</button>
      </div>
      <div class="tp-px">
        <span class="mono lv">${r.price!=null?"$"+num(r.price):"—"}</span>
        <span class="badge ${sgn(r.change_pct)}">${pct(r.change_pct)}</span>
        <span class="badge ghost">6mo ${pct(r.period_pct)}</span>
      </div>
      <div class="tp-spark" data-tspark="${t}" data-col="${col}"></div>
      <div class="tp-stats">
        ${[["P/E",num(r.pe,1)],["Mkt cap",usd(r.market_cap)],
           ["Net mgn", r.net_margin!=null?num(r.net_margin*100,1)+"%":"—"],
           ["Rev gr", r.revenue_growth!=null?pct(r.revenue_growth*100):"—"]]
          .map(([k,val])=>`<div><span class="k">${k}</span><span class="v mono">${val}</span></div>`).join("")}
      </div>
      <button class="tp-open" data-focus="${esc(t)}">${t===S.cur?"Showing below":"Open detail"}</button>
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
    location.hash = "#/t/" + left.join(","); });
  // click anywhere on a card to show its detail; the checkbox and close stay separate
  $$(".tpanel").forEach(p => p.onclick = e => {
    if (e.target.closest(".tick, [data-close], [data-focus]")) return;
    p.querySelector("[data-focus]").click(); });
  $$("[data-focus]").forEach(b => b.onclick = async () => {
    if (S.cur === b.dataset.focus) return;
    S.focus = S.cur = b.dataset.focus;
    $$(".tpanel").forEach(x => x.classList.toggle("focus", x.dataset.panel === S.cur));
    $$("[data-focus]").forEach(x => x.textContent = x.dataset.focus===S.cur ? "Showing below" : "Open detail");
    await renderDetail(); $("detailwrap").scrollIntoView({behavior:"smooth", block:"start"}); });

  // relative performance is opt-in: most of the time you want one ticker's detail
  const so = $("showOverlay");
  if (so) so.onclick = () => renderOverlay(cmp, symbols);
  await renderDetail();
  syncSel();
  afterRender(v);
}

function syncSel() {
  syncAsk();                       // the agent's "Looking at" follows every tick
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
    ${PRO() ? `<div class="qhead" id="qhead"><div class="skel" style="height:64px;width:100%"></div></div>
      <div class="qstats" id="qstats"></div>`
    : `<div class="section-h"><h3>${esc(S.cur)} detail</h3>
      <span class="r">${esc(q.name||"")}</span></div>`}
    <div class="panel" id="chartpanel">
      <div class="panel-h"><h4>Price</h4>
        <div class="seg" id="tfseg" style="margin-left:auto">
          ${Object.keys(TF).map(k=>`<button data-tf="${k}" class="${k===S.tf?"on":""}">${k}</button>`).join("")}
        </div>
        <button class="btn btn-sm ${S.show.MA?"on":""}" id="tgMA" aria-pressed="${S.show.MA}" title="Moving averages">MA</button>
        <button class="btn btn-sm ${S.show.Vol?"on":""}" id="tgVol" aria-pressed="${S.show.Vol}" title="Volume">Vol</button>
      </div>
      <div class="panel-b tight">${PRO() ? `<div class="ohlc" id="ohlc"></div>` : ""}<div id="chart"></div></div>
    </div>
    <div class="section">
      <div class="section-h"><div class="seg tabseg" role="tablist">
        ${Object.keys(TABS).map(k=>`<button role="tab" aria-selected="${k===S.tab}" class="${k===S.tab?"on":""}" data-tab="${k}">${k[0].toUpperCase()+k.slice(1)}</button>`).join("")}
      </div><span id="explainslot"></span></div>
      <div id="tabbody"></div>
    </div>`;
  try { chartRO?.disconnect(); chart?.remove(); } catch {}
  chart = null;
  buildChart(); drawChart(); prefetchFrames(S.cur);
  if (PRO()) fillQuoteHeader(S.cur);
  $("tfseg").onclick = e => { const b = e.target.closest("[data-tf]"); if(!b) return;
    $$("#tfseg button").forEach(x=>x.classList.remove("on")); b.classList.add("on");
    S.tf = b.dataset.tf; drawChart(); };
  ["MA","Vol"].forEach(k => { const b=$("tg"+k);
    b.onclick = () => { S.show[k]=!S.show[k]; b.classList.toggle("on",S.show[k]);
      b.setAttribute("aria-pressed", String(S.show[k])); drawChart(); }; });
  $$(".tabseg button").forEach(b => b.onclick = () => {
    $$(".tabseg button").forEach(x=>x.classList.remove("on")); b.classList.add("on");
    $$(".tabseg button").forEach(x=>x.setAttribute("aria-selected", String(x===b)));
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
    streamAsk(q, { tickers: picks });
  };
  $("cm_go").onclick = run;
  ta.onkeydown = e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); };
}

async function renderTab() {
  const el = $("tabbody"); if (!el) return;
  el.innerHTML = `<div class="grid">${"<div class='skel' style='height:86px'></div>".repeat(4)}</div>`;
  const want = { tab: S.tab, cur: S.cur };
  S.pending = [];
  let html;
  try { html = await TABS[S.tab](S.cur); }
  catch (e) { html = `<div class="empty">Couldn't load: ${esc(e.message)}</div>`; }
  // a slower earlier tab must not paint over the one you clicked since
  if (want.tab !== S.tab || want.cur !== S.cur || !el.isConnected) return;
  el.innerHTML = html;
  const dom = TAB_DOMAIN[S.tab], have = S.tabAgent[S.cur + ":" + dom];
  const slot = $("explainslot");
  if (slot) {
    slot.innerHTML = S.llm && !have ? `<button class="btn btn-sm btn-ghost explain" id="explain"
        title="One ${esc(DOMAIN_LABEL[dom]||dom)} specialist reads this tab's data">${IC.spark} Explain ${esc(S.tab)}</button>` : "";
    if ($("explain")) $("explain").onclick = runAnalyze;
  }
  el.querySelectorAll("[data-trace]").forEach(b => b.onclick = () => {
    const f = S.tabAgent[S.cur + ":" + b.dataset.trace]; if (!f) return;
    openTrace({ question: `${DOMAIN_LABEL[f.domain]||f.domain} · ${f.ticker}`, findings: [f],
                steps: f.steps || [], llm_calls: (f.steps||[]).filter(s=>s.llm).length,
                total_tokens: (f.steps||[]).reduce((a,s)=>a+(s.tokens||0),0) }); });
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
      try { const res = (await api(`/api/search?q=${encodeURIComponent(q)}`)).results;
            if (box.value.trim() !== q) return;
            items = res; active = -1; paint(); }
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
async function viewPortfolio(nav) {
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
  if (!v.querySelector(".hero")) v.innerHTML = `<div class="page"><div class="page-head"><div>
      <div class="ttl">Portfolio</div><div class="sub">Loading…</div></div></div>
      <div class="skel" style="height:150px"></div></div>`;
  let list;
  try { list = await api("/api/portfolios"); }
  catch (e) { if (nav === undefined || nav === NAV.seq)
    v.innerHTML = `<div class="page"><div class="empty">Couldn't load your portfolio: ${esc(e.message)}</div></div>`; return; }
  if (nav !== undefined && nav !== NAV.seq) return;
  S.accounts = list.accounts;
  S.kinds = list.kinds;
  const pid = S.acct ?? list.active ?? (list.accounts[0]?.id);
  S.acct = pid;
  const d = await api(`/api/portfolio?portfolio_id=${encodeURIComponent(pid)}`).catch(() => null);
  if (nav !== undefined && nav !== NAV.seq) return;
  if (!d) { v.innerHTML = `<div class="page"><div class="empty">Couldn't load this account.</div></div>`; return; }
  S.pf = d;
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
          <button class="btn btn-sm" data-edit="${esc(p.ticker)}" data-acc="${esc(p.account_id||pid)}" aria-label="Edit ${esc(p.ticker)}" title="Edit">${IC.edit}</button>
          <button class="btn btn-sm" data-del="${esc(p.ticker)}" data-acc="${esc(p.account_id||pid)}" aria-label="Delete ${esc(p.ticker)}" title="Delete">${IC.del}</button>
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
                  toast(err.message, "error"); }
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
    const pos = d.positions.find(x => x.ticker === b.dataset.del);
    if (!confirm(`Remove ${b.dataset.del} (${pos?.qty ?? "?"} shares) from ${pos?.account || d.portfolio_name}?`)) return;
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
  return signals.map(g => `<div class="sigrow" data-go="${esc(g.ticker)}">
      <img src="${logo(g.ticker)}" alt="" loading="lazy">
      <div><div class="h">${esc(g.headline)}${g.held?` <span class="badge brand" style="margin-left:6px">held</span>`:""}</div>
        <div class="d">${esc(g.detail)}</div></div>
      <span class="sigkind ${g.kind}">${SIG_LABEL[g.kind]||g.kind}</span>
    </div>${whyHTML(g.why)}`).join("");
}
/* ── dates read the way a person writes them: October 4th 2026 ── */
const MONTHS_LONG = ["January","February","March","April","May","June","July","August",
                     "September","October","November","December"];
const ordinal = n => n + ((n % 100 >= 11 && n % 100 <= 13) ? "th" : ({1:"st", 2:"nd", 3:"rd"}[n % 10] || "th"));
/* accepts "2026-10-04", an epoch in seconds or ms, or anything Date can parse */
function toDate(v) {
  if (v == null || v === "") return null;
  const str = String(v);
  if (/^\d{4}-\d{2}-\d{2}$/.test(str)) { const [y, m, d] = str.split("-").map(Number); return new Date(y, m - 1, d); }
  if (/^\d{9,13}$/.test(str)) { const n = Number(str); return new Date(n < 1e12 ? n * 1000 : n); }
  const d = new Date(str); return isNaN(d) ? null : d;
}
function longDate(v) {
  const d = toDate(v); if (!d) return v == null ? "" : String(v);
  return `${MONTHS_LONG[d.getMonth()]} ${ordinal(d.getDate())} ${d.getFullYear()}`;
}
/* a headline's age: "3h ago" while it is fresh, its date once it is not */
function whenPublished(v) {
  const d = toDate(v); if (!d) return "";
  const s = (Date.now() - d.getTime()) / 1000;
  if (s >= 0 && s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
  if (s >= 0 && s < 86400) return `${Math.round(s / 3600)}h ago`;
  if (s >= 0 && s < 172800) return "yesterday";
  return longDate(d);
}

/* ── the brief, in numbered sections ──
   It used to be one long scroll - a summary box, then tiles, then flags, then
   headlines tagged GSPC / TNX / VIX - with nothing saying where one part ended.
   Each part is now its own section with a heading, a one-line note on where it
   comes from, and a jump bar to get to it. */
const FEED_TOPIC = { "^GSPC": "Stocks", "^TNX": "Rates & bonds", "^VIX": "Volatility" };

function bsec(id, n, title, note, body) {
  return `<section class="panel bsec" id="bs-${id}" data-bsec="${id}">
    <div class="panel-h"><span class="bnum">${n}</span><h4>${esc(title)}</h4>
      ${note ? `<span class="r">${note}</span>` : ""}</div>
    <div class="panel-b">${body}</div></section>`;
}

function briefSummary(b) {
  const n = b.narrative || {};
  if (n.summary) return `<p class="bsum">${esc(n.summary)}</p><div class="disclaim">${esc(DISCLAIMER)}</div>`;
  if (b.error) return `<div class="bnote warn">${esc(b.error)}</div>`;
  return `<div class="bnote">No written summary for today. The sections below come straight from the data.</div>`;
}

function briefMarkets(b) {
  const lv = Object.entries(b.index_levels || {});
  const p = b.portfolio || {};
  const cells = lv.map(([k, v]) => `<div class="bstat"><div class="k">${esc(k.replace(/^./, c => c.toUpperCase()))}</div>
      <div class="v">${num(v.level, v.level > 1000 ? 0 : 2)}${/yield/i.test(k) ? "%" : ""}</div>
      <div class="c ${/volatility|yield/i.test(k) ? "" : sgn(v.change_pct)}">${pct(v.change_pct)}</div></div>`);
  if (!ME.guest && p.market_value != null) cells.unshift(
    `<div class="bstat mine"><div class="k">Your book</div><div class="v">$${num(p.market_value)}</div>
       <div class="c ${sgn(p.pnl_pct)}">${pct(p.pnl_pct)} all time</div></div>`,
    `<div class="bstat mine"><div class="k">Today</div>
       <div class="v ${sgn(p.day_change)}">${(p.day_change || 0) >= 0 ? "+" : "−"}$${num(Math.abs(p.day_change || 0))}</div>
       <div class="c ${sgn(p.day_change_pct)}">${pct(p.day_change_pct)}</div></div>`);
  return cells.length ? `<div class="bstats">${cells.join("")}</div>` : `<div class="bnote">Index levels are unavailable right now.</div>`;
}

function briefThreads(n) {
  return (n.threads || []).map(t => `<div class="thread">
      <div class="th">${esc(t.title || "")}</div>
      <div class="tb">${esc(t.body || "")}</div>
      <div class="tf">
        ${(t.tickers || []).map(x => `<span class="badge brand" data-go="${esc(x)}" style="cursor:pointer">${esc(x)}</span>`).join("")}
        ${(t.sources || []).map(src => { const bad = (t.unverified_sources || []).includes(src);
          return `<span class="src ${bad ? "bad" : ""}" title="${esc(src)}">${bad ? "⚠ " : ""}${esc(src.slice(0, 68))}${src.length > 68 ? "…" : ""}</span>`; }).join("")}
      </div></div>`).join("");
}

function briefTickers(b) {
  if (ME.guest) return `<div class="bnote">Today's brief is market-wide. Sign in and your watchlist and holdings
      are scanned every day for unusual moves, earnings and peer spillover.
      <div style="margin-top:10px"><button class="btn btn-sm btn-brand" data-signin="1">Create a free account</button></div></div>`;
  const parts = [];
  parts.push(b.signals.length ? `<div class="bsub-h">Flagged today <span>ranked by how unusual the move is, not how big</span></div>${sigRows(b.signals)}`
    : `<div class="bnote">Nothing unusual across your ${b.checked.length} tickers today.</div>`);
  if (b.since_last?.length) parts.push(`<div class="bsub-h">Since you were last here
      <span>${b.since_last_day ? esc(longDate(b.since_last_day)) : ""}</span></div>
    ${b.since_last.map(r => `<div class="lrow" data-go="${esc(r.ticker)}" style="cursor:pointer">
      <span class="d mono">${esc(r.ticker)}</span>
      <span class="mono">$${num(r.from)} → $${num(r.to)}</span>
      <span class="badge ${sgn(r.pct)}">${pct(r.pct)}</span></div>`).join("")}`);
  if (b.quiet?.length) parts.push(`<div class="bsub-h">Checked, nothing to flag</div>
    <div class="qt">${b.quiet.map(q => `<span class="badge ghost">${esc(q)}</span>`).join("")}</div>
    ${b.adjacent_checked?.length ? `<div class="muted" style="margin-top:9px">Plus ${b.adjacent_checked.length}
      adjacent names watched for spillover: ${b.adjacent_checked.slice(0, 14).map(esc).join(", ")}${b.adjacent_checked.length > 14 ? "…" : ""}</div>` : ""}`);
  return parts.join("");
}

function briefHeadlines(items) {
  const groups = {};
  for (const h of items) (groups[FEED_TOPIC[h.source_feed] || "Other"] ||= []).push(h);
  return Object.entries(groups).map(([topic, hs]) => `<div class="bgroup"><div class="bsub-h">${esc(topic)}</div>
    ${hs.map(h => { const ok = /^https?:\/\//i.test(h.url || "");
      return `<${ok ? `a href="${esc(h.url)}" target="_blank" rel="noopener"` : "div"} class="bnrow">
        <div class="h">${esc(h.title)}</div>
        <div class="m">${esc(h.publisher || "")}${h.published ? " · " + esc(whenPublished(h.published)) : ""}</div></${ok ? "a" : "div"}>`; }).join("")}
  </div>`).join("");
}

function briefInner(b) {
  const n = b.narrative || {};
  const secs = [["summary", "Summary", "", briefSummary(b)],
                ["markets", "Markets at a glance", "index, rates and volatility levels", briefMarkets(b)]];
  if (n.threads?.length) secs.push(["meaning", "What it means", "written from the headlines in section " +
                                    (secs.length + 3), briefThreads(n)]);
  secs.push(["tickers", "Your tickers", ME.guest ? "" : `${b.signals.length} flagged · ${b.checked.length} tracked`,
             briefTickers(b)]);
  if ((b.market_headlines || []).length)
    secs.push(["headlines", "Headlines", "what the market feeds are carrying", briefHeadlines(b.market_headlines)]);
  // "section N" in the What-it-means note must point at Headlines' actual number
  const hi = secs.findIndex(x => x[0] === "headlines");
  const mi = secs.findIndex(x => x[0] === "meaning");
  if (mi >= 0) secs[mi][2] = hi >= 0 ? `written from the headlines in section ${hi + 1}` : "written from today's headlines";
  return `<nav class="bjump" aria-label="Brief sections">${secs.map(([id, title]) =>
      `<button type="button" data-jump="${id}">${esc(title)}</button>`).join("")}</nav>
    ${secs.map(([id, title, note, body], i) => bsec(id, i + 1, title, note, body)).join("")}`;
}

/* jump bar + sign-in + ticker links, for wherever the brief was rendered */
function wireBrief(root, onGo) {
  root.querySelectorAll("[data-jump]").forEach(b => b.onclick = () => {
    const sec = root.querySelector(`[data-bsec="${b.dataset.jump}"]`); if (!sec) return;
    // land below the sticky jump bar, whatever height it has at this width
    sec.style.scrollMarginTop = ((root.querySelector(".bjump")?.offsetHeight || 0) + 10) + "px";
    sec.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" }); });
  root.querySelectorAll("[data-signin]").forEach(b => b.onclick = () => { closeBrief(); openAuth("register"); });
  root.querySelectorAll("[data-go]").forEach(el => el.onclick = () => onGo(el.dataset.go));
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

async function viewBrief(nav) {
  crumbs([{label:"Daily brief"}]);
  const v = $("views");
  v.innerHTML = `<div class="page"><div class="page-head">
      <div><div class="ttl">Daily brief</div><div class="sub" id="bsub">Loading…</div></div>
      <div class="acts"><button class="btn btn-sm btn-brand" id="askhere">Ask ${IC.arrow}</button></div>
    </div><div id="briefview"><div class="skel" style="height:200px"></div></div></div>`;
  try {
    const b = await loadBrief();
    if ((nav !== undefined && nav !== NAV.seq) || !$("bsub")) return;
    $("bsub").textContent = (b.llm_calls || b.error)
      ? `${longDate(b.date)} · curated from ${b.checked.length ? b.checked.length + " tickers plus " : ""}market, rates and sector feeds`
      : `${longDate(b.date)} · set GEMINI_API_KEY to add the written summary`;
    $("briefview").innerHTML = briefInner(b);
    wireBrief($("briefview"), t => location.hash = "#/t/" + t);
  } catch (e) {
    if ($("briefview")) $("briefview").innerHTML = `<div class="empty">Couldn't build the brief: ${esc(e.message)}</div>`;
  }
  afterRender(v);
}

/* first visit of the day -> show it as a sheet */
const BRIEF_KEY = "monsoon.brief.seen";
async function maybeShowBrief() {
  let b; try { b = await loadBrief(); } catch { return; }
  let seen = null; try { seen = localStorage.getItem(BRIEF_KEY); } catch {}
  $("navdot").classList.toggle("on", seen !== b.date && b.signals.length > 0);
  if (seen === b.date) return;
  if (!b.signals.length && !b.since_last?.length && !b.narrative?.threads?.length) {  // nothing to say
    try { localStorage.setItem(BRIEF_KEY, b.date); } catch {} return;
  }
  $("briefdate").textContent = longDate(b.date) + (b.checked.length
    ? ` · ${b.signals.length} flagged · ${b.checked.length} tracked` : " · market-wide");
  $("briefnote").textContent = b.note;
  $("briefbody").innerHTML = briefInner(b);
  wireBrief($("briefbody"), t => { closeBrief(); location.hash = "#/t/" + t; });
  $("briefsheet").classList.add("on");
  mo($("briefbox"), { opacity:[0,1], scale:[.96,1], y:[16,0] },
     { duration:.42, easing:[.22,1,.36,1] });
  mo($("briefbody").querySelectorAll(".bsec"), { opacity:[0,1], y:[10,0] },
     { duration:.36, delay:stag(.04), easing:[.22,1,.36,1] });
}
function closeBrief() {
  const b = S.brief;
  if (b) try { localStorage.setItem(BRIEF_KEY, b.date); } catch {}
  $("navdot").classList.remove("on");
  $("briefsheet").classList.remove("on");
}

/* ═══════════════ agent panel ═══════════════
   A conversation, not a single slot. Each turn keeps its question, its live
   progress, its answer and its trace, and the last few turns go back to the
   server as `history` so "what about AMD?" or "why?" means something. */
const openAgent = on => { document.getElementById("app").classList.toggle("agent-open", on);
  $("right").inert = !on;
  $("agenttoggle").classList.toggle("on", on);
  $("agenttoggle").setAttribute("aria-expanded", String(on));
  setTimeout(()=>{ if (on) growAsk(); if (chart) { const el=$("chart");
    if (el?.clientWidth) chart.applyOptions({width:el.clientWidth}); chart.timeScale().fitContent(); } }, 340); };

const THREAD_KEY = "monsoon.thread", HISTORY_TURNS = 3;
const T = { turns: [], ctl: null, seq: 0 };
try { T.turns = JSON.parse(sessionStorage.getItem(THREAD_KEY) || "[]")
                  .filter(t => t.status === "done" || t.status === "error"); } catch {}
const saveThread = () => { try { sessionStorage.setItem(THREAD_KEY,
  JSON.stringify(T.turns.slice(-12).map(t => ({...t, live: undefined})))); } catch {} };

const DOMAIN_LABEL = { market:"Price action", fundamentals:"Fundamentals", street:"Analysts & news",
  events:"Earnings & filings", relations:"Peers", macro:"Macro", portfolio:"Portfolio", screener:"Screener" };

/* suggested first questions, scoped to wherever you are */
function suggestions() {
  if (S.route === "ticker" && S.cur) {
    const ctx = askScope().context || [];
    if (ctx.length > 1) {
      const names = ctx.length <= 3 ? ctx.slice(0, -1).join(", ") + " and " + ctx.at(-1) : "these";
      return [`Compare ${names} on margins and growth`, "Which of these looks most expensive relative to what it earns?",
              "Do these trade as one bet or separately?", "Which is holding up best, and why?"];
    }
    const t = S.cur;
    return [`How is ${t} performing this year?`, `Is ${t} expensive relative to what it earns?`,
            `What's the setup for ${t} into its next earnings?`, `What do analysts think of ${t} right now?`];
  }
  if (S.route === "portfolio" && !ME.guest)
    return ["Where is my portfolio most concentrated?", "Which holding is doing the most work today?",
            "How exposed am I to a tech sell-off?"];
  if (S.route === "brief")
    return ["What's driving the market today?", "Which flagged move matters most, and why?",
            "Which small caps are moving most today?"];
  return ["What's driving the market today?", "Find small caps with fast revenue growth",
          "Find cheap, profitable mid caps", "How is NVDA performing versus its peers?"];
}

/* figures stand out from the prose - the answer is about them */
/* Marked on the RAW text, escaping each piece: run over escaped text, the
   pattern found the 39 inside &#39; and broke the entity. A number glued to a
   letter ("Q3", "52w", "S&P 500" stays plain via the letter check) is a name,
   not a figure. */
const FIG_RE = /[$−-]?\d[\d,]*(?:\.\d+)?(?:\s?(?:%|×|x(?![a-z])|bps(?![a-z])|[KMBT](?![a-z])))?(?![\w-]|\.\d)/gi;
const INDEX_BEFORE = /(S&P|Russell|Nasdaq|Dow|FTSE|Nikkei)\s$/i;
function markFigures(raw) {
  const s = String(raw ?? ""); let out = "", last = 0;
  for (const m of s.matchAll(FIG_RE)) {
    const prev = s[m.index - 1] || "";
    if (/[A-Za-z&]/.test(prev) || INDEX_BEFORE.test(s.slice(Math.max(0, m.index - 9), m.index))) continue;
    out += esc(s.slice(last, m.index)) + `<span class="fig">${esc(m[0])}</span>`;
    last = m.index + m[0].length;
  }
  return out + esc(s.slice(last));
}
const paras = s => String(s||"").split(/\n{2,}/).map(p => `<p>${markFigures(p.trim())}</p>`).join("");

function tickerChips(tks) {
  return (tks||[]).filter(t => t && t !== "MARKET")
    .map(t => `<button class="tchip" data-go="${esc(t)}" title="Open ${esc(t)}">${esc(t)}</button>`).join("");
}

/* ── live progress: a timeline of the four agents, fed by the stream ──
   The router reads the question, specialists each pick tools / fetch / write
   up in parallel, the writer composes (and may send for more), the figure
   check runs last. Every line is driven by a real event from the server. */
const MODEL_SHORT = m => !m ? "" : /gemma/i.test(m) ? "Gemma" : m.replace(/^gemini-/, "").replace(/-lite$/, " Lite");
function specLine(sp) {
  const n = (sp.tools || []).length;
  const tl = n ? (sp.tools.slice(0, 3).map(t => t.replace(/_/g, " ")).join(", ") + (n > 3 ? "…" : "")) : "";
  switch (sp.stage) {
    case "queued":   return "waiting to start";
    case "select":   return "choosing which data to pull…";
    case "picked":   return `picked ${n} tool${n === 1 ? "" : "s"}${sp.model ? ` (${esc(MODEL_SHORT(sp.model))})` : ""} · ${esc(tl)}`;
    case "gather":   return `fetching ${n} source${n === 1 ? "" : "s"}: ${esc(tl)}…`;
    case "synth":    return `got ${sp.ok}/${sp.of} · writing up what it found…`;
    case "done":     return `done · ${sp.used ?? sp.ok ?? n} source${(sp.used ?? sp.ok ?? n) === 1 ? "" : "s"} used`;
    case "skip":     return "no data available";
    default:         return "";
  }
}
function progressHTML(turn) {
  const L = turn.live || {};
  const el = Math.max(0, Math.round((Date.now() - (turn.t0 || Date.now())) / 1000));
  const specs = L.specs || [];
  const specsDone = specs.length && specs.every(x => x.stage === "done" || x.stage === "skip");
  const phase = L.verify ? (L.verify === "repair" ? "Fixing figures the check could not match…" : "Checking every figure against the evidence…")
    : L.writer === "run" ? (L.writerMode === "edit" ? "Writer agent is editing the specialist's answer…" : "Writer agent is drafting the final answer…")
    : L.writer === "asked" && !specsDone ? "Writer agent asked for more · specialists back at work…"
    : L.route === "done" ? "Specialist agents are gathering data…"
    : "Router agent is reading your question…";
  const st = k => k === "done" ? "done" : k === "run" ? "run" : "wait";
  const routeSt = L.route === "done" ? "done" : "run";
  const specSt = !specs.length ? "wait" : specsDone ? "done" : "run";
  const wrSt = L.writer === "done" || L.verify ? "done" : L.writer === "run" ? "run" : L.writer === "asked" ? "run" : "wait";
  const vSt = L.verify === "done" ? "done" : L.verify ? "run" : "wait";
  return `<div class="prog">
    <div class="phead"><span class="spin"></span><b>${esc(phase)}</b><span class="el" data-el>${el}s</span></div>
    <ol class="ptl">
      <li class="${routeSt}"><span class="pi"></span><div><div class="pt">Router agent</div>
        <div class="pd2">${L.route === "done" ? `sent it to ${specs.length} specialist${specs.length === 1 ? "" : "s"}${L.resolved ? ` · read as “${esc(L.resolved)}”` : ""}`
                                               : "working out which specialists the question needs…"}</div></div></li>
      <li class="${specSt}"><span class="pi"></span><div><div class="pt">Specialist agents${specs.length ? ` <span class="pn">${specs.filter(x => x.stage === "done" || x.stage === "skip").length}/${specs.length}</span>` : ""}</div>
        ${specs.length ? specs.map(sp => `<div class="psub ${sp.stage === "done" ? "done" : sp.stage === "skip" ? "skip" : "run"}">
            <span class="dot2"></span><span class="who">${esc(DOMAIN_LABEL[sp.domain] || sp.domain)}${sp.ticker && sp.ticker !== "MARKET" ? ` · ${esc(sp.ticker)}` : ""}${sp.round > 1 ? ` <i>follow-up</i>` : ""}</span>
            <span class="what">${specLine(sp)}</span></div>`).join("")
          : `<div class="pd2">each pulls its own data in parallel</div>`}</div></li>
      <li class="${wrSt}"><span class="pi"></span><div><div class="pt">Writer agent</div>
        <div class="pd2">${L.writer === "asked" ? `found a gap · asked for ${esc(L.asked || "another specialist")}`
          : L.writer === "run" ? (L.writerMode === "edit" ? "editing the specialist's answer…" : `combining ${L.writerN || specs.length} findings into one answer…`)
          : wrSt === "done" ? "final answer drafted" : "will combine the findings into one answer"}</div></div></li>
      <li class="${vSt}"><span class="pi"></span><div><div class="pt">Fact check</div>
        <div class="pd2">${L.verify === "repair" ? `${L.unsupported ? `${L.unsupported} figure${L.unsupported === 1 ? "" : "s"} not in the evidence · ` : ""}repairing…`
          : L.verify ? "matching every figure to the data the specialists fetched…" : "every figure gets checked against the evidence"}</div></div></li>
    </ol></div>
    ${L.draft ? `<div class="answer draft"><div class="dlab">${L.verify ? "Draft · checking figures…" : "Writing…"}</div>
      <div class="dtext" data-draft>${paras(L.draft)}<span class="caret"></span></div></div>` : ""}`;
}

/* fold one stream event into the live state */
function spec(L, domain, ticker) {
  let sp = L.specs.find(x => x.domain === domain && x.ticker === ticker && x.stage !== "done" && x.stage !== "skip");
  if (!sp) { sp = { domain, ticker, stage: "queued", round: L.writer === "asked" ? 2 : 1 }; L.specs.push(sp); }
  return sp;
}
function applyEvent(L, ev, d) {
  if (ev === "progress") {
    const k = d.step;
    if (k === "route") L.route = "run";
    else if (["select", "picked", "gather", "gathered", "synth"].includes(k)) {
      const sp = spec(L, d.domain, d.ticker);
      if (k === "picked") { sp.tools = d.tools; sp.model = d.model; }
      if (k === "gather") sp.tools = d.tools || sp.tools;
      if (k === "gathered") { sp.ok = d.ok; sp.of = d.of; }
      sp.stage = k === "gathered" ? "synth" : k;
    }
    else if (k === "write") { L.writer = "run"; L.writerMode = d.mode; L.writerN = d.findings; L.draft = ""; }
    else if (k === "draft") { L.writer = "run"; L.draft = (L.draft || "") + (d.text || ""); }
    else if (k === "verify") { L.writer = "done"; L.verify = "run"; }
    else if (k === "repair") { L.verify = "repair"; L.unsupported = d.unsupported; }
    else if (k === "cached") L.cached = d.age_s;
    return;
  }
  if (ev !== "node") return;
  if (d.node === "route") {
    L.route = "done";
    for (const t of d.tasks || []) spec(L, t.domain, t.ticker);
  }
  for (const f of d.findings || []) {
    const sp = L.specs.find(x => x.domain === f.domain && x.ticker === f.ticker && x.stage !== "done" && x.stage !== "skip")
      || spec(L, f.domain, f.ticker);
    sp.stage = f.confidence === "unavailable" ? "skip" : "done";
    sp.used = (f.tools_used || []).length;
  }
  const dec = (d.steps || []).find(x => x.node === "writer.decide");
  if (dec) { L.writer = "asked"; L.draft = ""; L.asked = (dec.detail || "").replace(/^needs more -> /, "")
    .replace(/(\w+)\((\w[\w.^=-]*)\)/g, (_, dm, tk) => `${DOMAIN_LABEL[dm] || dm} · ${tk}`); }
  if ((d.steps || []).some(x => x.node === "writer")) { L.writer = "done"; L.verify = L.verify || "done"; }
}

function stepsHTML(run) {
  return (run.steps||[]).filter(s => !/\.(gather|select)$/.test(s.node)).map(s => {
    const f = (run.findings||[]).find(x => s.node === x.domain + ".synthesize");
    const label = s.node.replace(".synthesize","");
    return `<div class="node ${f && f.confidence==="unavailable" ? "skip" : "done"}"><span class="nd"></span>
      <div class="nrow"><span class="nname">${esc(label)}</span>
        <span class="nmeta">${s.model ? esc(s.model.replace(/^gemini-/,"")) + " · " : ""}${s.latency_ms ? `${(s.latency_ms/1000).toFixed(1)}s` : ""}</span></div>
      ${s.detail ? `<div class="why">${esc(s.detail)}</div>` : ""}</div>`;
  }).join("");
}

function turnHTML(turn, i) {
  const r = turn.run;
  let body = "";
  if (turn.status === "running") body = progressHTML(turn);
  else if (turn.status === "error" || turn.status === "stopped")
    body = `<div class="aerr">${turn.status === "stopped" ? "Stopped." : esc(turn.error || "Something went wrong.")}
      ${turn.status === "error" ? `<button class="link" data-retry="${i}">Try again ${IC.arrow}</button>` : ""}</div>`;
  else if (r && (r.refused || !(r.findings||[]).length))
    body = `<div class="anote">${esc(r.answer || "No answer.")}</div>`;
  else if (r) {
    const ndom = new Set((r.findings||[]).map(f => f.domain)).size;
    const warn = r.grounded === false
      ? `<div class="awarn">Couldn't match ${esc((r.ungrounded_numbers||[]).join(", "))} to the data the specialists fetched — treat ${(r.ungrounded_numbers||[]).length > 1 ? "them" : "it"} with care.</div>` : "";
    const degraded = r.degraded ? `<div class="awarn">${esc(r.degraded)}</div>` : "";
    const gaps = (r.findings||[]).filter(f => f.confidence === "unavailable");
    const gapLine = gaps.length ? `<div class="agap">No data: ${gaps.map(f =>
      `${esc(DOMAIN_LABEL[f.domain]||f.domain)} ${f.ticker!=="MARKET"?esc(f.ticker):""}`).join(", ")}</div>` : "";
    const meta = r.cached ? `answered from the same question ${r.cached_age_s < 60 ? "just now" : Math.round(r.cached_age_s / 60) + "m ago"} · no new model calls`
      : ndom ? `${ndom} specialist${ndom>1?"s":""} · ${r.llm_calls} model calls · ${((turn.wall_ms||r.wall_ms||r.latency_ms)/1000).toFixed(1)}s` : "";
    body = `<div class="answer">
      ${(r.tickers||[]).some(t => t !== "MARKET") || r.grounded ? `<div class="top">${tickerChips(r.tickers)}
        ${r.grounded ? `<span class="ok" title="Every figure in this answer was matched to the data the specialists fetched">✓ figures checked</span>` : ""}</div>` : ""}
      ${paras(r.answer)}${degraded}${warn}${gapLine}
      <div class="afoot">
        ${meta ? `<button class="link" data-how="${i}">${esc(meta)} ${IC.chev}</button>` : ""}
        <div class="grow"></div>
        ${(r.findings||[]).length ? `<button class="link" data-trace="${i}">Evidence ${IC.arrow}</button>` : ""}
      </div>
      <div class="how" id="how${i}">${stepsHTML(r)}</div>
    </div>`;
  }
  return `<div class="turn" data-turn="${i}">
    <div class="uq">${esc(turn.q)}</div>
    ${r?.resolved && r.resolved.toLowerCase() !== turn.q.toLowerCase()
      ? `<div class="interp">Read as: ${esc(r.resolved)}</div>` : ""}
    ${body}</div>`;
}

function renderThread(scroll = true) {
  const el = $("thread"); if (!el) return;
  if (!T.turns.length) {
    el.innerHTML = `<div class="intro">
      <div class="ih">Ask the research agent</div>
      <p>A router sends your question to the specialists it needs — price action, fundamentals,
        analysts and news, earnings, peers, macro — in parallel. Every figure in the answer is
        checked against the data they fetched.</p>
      ${S.llm && S.route !== "ticker" ? screenerHTML() : ""}
      ${S.llm ? `<div class="isugg">${suggestions().map(q =>
        `<button class="sugg" data-ask="${esc(q)}">${esc(q)}</button>`).join("")}</div>`
        : `<div class="awarn">Agent disabled — set <span class="mono">GEMINI_API_KEY</span> and restart. The dashboard works without it.</div>`}
    </div>`;
  } else {
    el.innerHTML = T.turns.map(turnHTML).join("");
  }
  wireThread(el);
  if (scroll) { const sc = $("rscroll"); sc.scrollTop = sc.scrollHeight; }
}

/* stock screener: three choices make a question the router knows how to read */
const SCR = { cap: "small", style: "growth", sector: "" };
const SCR_STYLE = { growth: "fast revenue growth", value: "low P/E and positive operating margins",
                    momentum: "prices near their 52-week highs", quality: "the highest operating margins" };
function screenerHTML() {
  const seg = (k, opts) => `<div class="seg" data-sg="${k}">${opts.map(([v, l]) =>
    `<button type="button" data-v="${v}" class="${SCR[k] === v ? "on" : ""}">${l}</button>`).join("")}</div>`;
  return `<div class="scrb"><div class="scrh">Stock screener <span>whole US market · measurable criteria</span></div>
    <div class="scrrow"><span class="lbl">Size</span>${seg("cap", [["micro","Micro"],["small","Small"],["mid","Mid"],["large","Large"]])}</div>
    <div class="scrrow"><span class="lbl">Style</span>${seg("style", [["growth","Growth"],["value","Value"],["momentum","Momentum"],["quality","Quality"]])}</div>
    <div class="scrrow"><span class="lbl">Sector</span><select class="inp" data-sg-sector>
      ${["", "Technology", "Health Care", "Finance", "Consumer Discretionary", "Consumer Staples", "Industrials",
         "Energy", "Utilities", "Real Estate", "Basic Materials", "Telecommunications"].map(x =>
         `<option value="${x}" ${SCR.sector === x ? "selected" : ""}>${x || "Any sector"}</option>`).join("")}</select>
      <button type="button" class="btn btn-sm btn-primary" data-screen>Screen ${IC.arrow}</button></div></div>`;
}

function wireThread(el) {
  el.querySelectorAll("[data-sg] button").forEach(b => b.onclick = () => {
    const g = b.closest("[data-sg]"); SCR[g.dataset.sg] = b.dataset.v;
    g.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); });
  el.querySelectorAll("[data-sg-sector]").forEach(x => x.onchange = () => SCR.sector = x.value);
  el.querySelectorAll("[data-screen]").forEach(b => b.onclick = () =>
    submitAsk(`Find ${SCR.cap}-cap ${SCR.sector ? SCR.sector.toLowerCase() + " " : ""}stocks with ${SCR_STYLE[SCR.style]}`));
  el.querySelectorAll("[data-ask]").forEach(b => b.onclick = () => submitAsk(b.dataset.ask));
  el.querySelectorAll("[data-go]").forEach(b => b.onclick = () => location.hash = "#/t/" + b.dataset.go);
  el.querySelectorAll("[data-trace]").forEach(b => b.onclick = () => openTrace(T.turns[+b.dataset.trace]?.run));
  el.querySelectorAll("[data-how]").forEach(b => b.onclick = () => {
    const h = $("how" + b.dataset.how); h?.classList.toggle("on"); b.classList.toggle("open"); });
  el.querySelectorAll("[data-retry]").forEach(b => b.onclick = () => {
    const t = T.turns[+b.dataset.retry]; T.turns.splice(+b.dataset.retry, 1); submitAsk(t.q); });
}

/* repaint ONE turn as its stream advances; the rest of the thread (and any
   section you have expanded in it) is left alone */
function paintTurn(turn) {
  const i = T.turns.indexOf(turn);
  const node = document.querySelector(`#thread [data-turn="${i}"]`);
  if (!node) return renderThread();
  const tmp = document.createElement("div");
  tmp.innerHTML = turnHTML(turn, i);
  const fresh = tmp.firstElementChild;
  node.replaceWith(fresh);
  wireThread(fresh);
  const sc = $("rscroll"); sc.scrollTop = sc.scrollHeight;
}

let tick = null;
const busy = on => { $("rst").textContent = on ? "working" : "idle"; $("rdot").classList.toggle("live", on);
  clearInterval(tick);
  if (on) tick = setInterval(() => { const t = T.turns.at(-1);
    if (t?.status === "running") document.querySelectorAll("#thread [data-el]").forEach(e =>
      e.textContent = Math.round((Date.now() - t.t0) / 1000) + "s"); }, 1000);
  const b = $("send"); b.classList.toggle("stop", on);
  b.setAttribute("aria-label", on ? "Stop" : "Ask"); b.title = on ? "Stop" : "Ask";
  b.innerHTML = on ? `<svg class="ico" viewBox="0 0 24 24" fill="currentColor"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>`
                   : `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>`; };

/* what the server needs to read a follow-up: the user's own words, the answer,
   the tickers it was about. Prefixed scope text stays out of it. */
const historyFor = () => T.turns.filter(t => t.status === "done" && t.run?.answer)
  .slice(-HISTORY_TURNS).map(t => ({ q: t.q, a: t.run.answer.slice(0, 700),
                                     tickers: (t.run.tickers||[]).filter(x => x !== "MARKET") }));

async function streamAsk(question, opts = {}) {
  if (T.ctl) T.ctl.abort();                          // one run at a time
  openAgent(true);
  const turn = { id: ++T.seq, q: opts.display || question, status: "running", t0: Date.now(),
                 live: { specs: [], route: "run" } };
  const history = historyFor();
  T.turns.push(turn); renderThread(); busy(true);
  const ctl = T.ctl = new AbortController();
  try {
    const body = { question, history };
    if (opts.tickers?.length) body.tickers = opts.tickers;          // hard selection
    if (opts.context?.length) body.context_tickers = opts.context;  // what you're looking at
    const r = await fetch(url("/api/agent/ask/stream"), { method:"POST", credentials:"include",
      headers:{"Content-Type":"application/json"}, body: JSON.stringify(body), signal: ctl.signal });
    if (!r.ok) { let m = ""; try { const j = await r.json(); m = j.detail || j.error; } catch {}
                 throw new Error(m || `request failed (${r.status})`); }
    const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "";
    for (;;) { const {value, done} = await rd.read(); if (done) break;
      buf += dec.decode(value, {stream:true});
      const parts = buf.split(/\r?\n\r?\n/); buf = parts.pop();
      for (const p of parts) {
        const ev = (p.match(/^event:\s*(.*)$/m)||[])[1];
        const dl = p.split(/\r?\n/).filter(l=>l.startsWith("data:")).map(l=>l.slice(5).trim()).join("");
        if (!dl) continue;
        let d; try { d = JSON.parse(dl); } catch { continue; }
        const L = turn.live;
        if (ev === "node" || ev === "progress") {
          if (ev === "node" && d.node === "route" && (d.steps || [])[0]?.detail?.startsWith?.("ROUTER UNAVAILABLE")) L.degraded = true;
          const hadDraft = !!L.draft;
          applyEvent(L, ev, d);
          const box = ev === "progress" && d.step === "draft" && hadDraft
            ? document.querySelector(`#thread [data-turn="${T.turns.indexOf(turn)}"] [data-draft]`) : null;
          if (box) {
            if (!turn.raf) turn.raf = requestAnimationFrame(() => { turn.raf = 0;
              box.innerHTML = paras(L.draft) + `<span class="caret"></span>`;
              const sc = $("rscroll"); if (sc.scrollHeight - sc.scrollTop - sc.clientHeight < 140) sc.scrollTop = sc.scrollHeight; });
          } else paintTurn(turn);
        } else if (ev === "done") {
          turn.run = d; turn.status = "done"; turn.wall_ms = Date.now() - turn.t0;
        } else if (ev === "error") {
          turn.status = "error"; turn.error = d.error;
        }
      } }
    if (turn.status === "running") { turn.status = "error"; turn.error = "The connection closed before the answer arrived."; }
  } catch (e) {
    turn.status = e.name === "AbortError" ? "stopped" : "error";
    turn.error = e.message;
  }
  delete turn.live;
  if (T.ctl === ctl) { T.ctl = null; busy(false); }
  paintTurn(turn); saveThread();
}

/* the per-tab Explain button: ONE domain specialist, no router, no writer */
async function runAnalyze() {
  const domain = TAB_DOMAIN[S.tab] || "fundamentals", sym = S.cur;
  const b = $("explain"); if (!b) return;
  b.disabled = true; b.classList.add("busy"); b.innerHTML = `<span class="spin"></span>Reading ${esc(S.tab)}…`;
  try {
    const r = await jpost("/api/agent/analyze", {ticker: sym, domain,
      question: `Looking at ${sym}'s ${S.tab}, what stands out?`});
    if (r.finding) S.tabAgent[sym + ":" + domain] = { ...r.finding, steps: r.steps };
    if (S.cur === sym) await renderTab();
  } catch (e) {
    b.disabled = false; b.classList.remove("busy");
    b.innerHTML = `${IC.spark} Explain ${esc(S.tab)}`;
    b.insertAdjacentHTML("afterend", `<span class="muted" style="color:var(--neg);margin-left:8px">${esc(e.message)}</span>`);
  }
}

function openTrace(run) {
  const box = $("tbody");
  if (!run) box.innerHTML = `<div class="empty">No run yet.</div>`;
  else {
    $("tsub").textContent = `${run.question||""} · ${run.llm_calls} model calls · ${run.total_tokens} tokens`;
    const findings = run.findings || [];
    box.innerHTML = `${findings.map(f => `<div class="section"><div class="section-h">
          <h3>${esc(DOMAIN_LABEL[f.domain]||f.domain)} · ${esc(f.ticker)}</h3>
          <span class="r">${f.tools_used.length} tools used · ${f.tools_skipped.length} skipped · ${esc(f.confidence)}</span></div>
        <div class="tfind">${paras(f.narrative)}</div>
        ${f.tools_used.length ? `<div class="tools">${f.tools_used.map(t=>`<span class="tc sel">${esc(t)}</span>`).join("")}
          ${f.tools_skipped.map(t=>`<span class="tc skp">${esc(t)}</span>`).join("")}</div>` : ""}
        ${(f.failures||[]).length ? `<div class="muted">${f.failures.map(x=>`${esc(x.tool)}: ${esc(x.reason)}`).join(" · ")}</div>` : ""}
        <details class="raw"><summary>Raw evidence</summary>
          <pre>${esc(JSON.stringify((f.evidence||[]).reduce((a,e)=>(a[e.tool]=e.data,a),{}),null,1)).slice(0,6000)}</pre></details>
      </div>`).join("")}
      <div class="section"><div class="section-h"><h3>Steps</h3></div>
      <table><thead><tr><th>Node</th><th>Detail</th><th>Model</th><th>Tools</th><th>Tokens</th><th>Latency</th></tr></thead>
      <tbody>${(run.steps||[]).map(s=>`<tr><td style="color:var(--b2);font-weight:600">${esc(s.node)}</td>
        <td style="text-align:left;color:var(--muted-foreground)">${esc(s.detail||"")}</td>
        <td>${s.model ? `<span class="badge brand">${esc(s.model.replace(/^gemini-/,""))}</span>`
                      : `<span class="badge ghost">no model</span>`}</td>
        <td class="mono">${s.tools||"—"}</td><td class="mono">${s.tokens||0}</td>
        <td class="mono">${((s.latency_ms||0)/1000).toFixed(2)}s</td></tr>`).join("")}</tbody></table></div>
      <div class="disclaim">${esc(run.disclaimer||DISCLAIMER)}</div>`;
  }
  $("trace").classList.add("on");
  setTimeout(() => $("tclose").focus(), 30);
  mo($("tbox"),{opacity:[0,1],scale:[.97,1],y:[10,0]},{duration:.3,easing:[.22,1,.36,1]});
}
const closeTrace = () => $("trace").classList.remove("on");

function submitAsk(text) {
  const v = (text || "").trim(); if (!v) return;
  if (!S.llm) { openAgent(true); renderThread(); return; }
  const sc = askScope();
  streamAsk(sc.pre(v), { display: v, tickers: sc.tickers, context: sc.context });
}

/* ═══════════════════════════ Pro UI ═══════════════════════════
   A second interface over the same data and the same agent, so the two can be
   compared side by side: top-bar switch, or ?ui=pro / ?ui=classic. Everything
   below renders only when Pro is on; Classic's views are untouched. */
const PRO = () => document.documentElement.dataset.ui === "pro";
const LIGHT = () => PRO() && document.documentElement.dataset.theme === "light";
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function applyPalette() {
  CH.setPalette(PRO() ? { pos: cssv("--pos"), neg: cssv("--neg"), faint: cssv("--border-subtle"),
                          ink: cssv("--subtle-foreground") } : null);
}

/* the market map's universe: large caps by sector, sized by cap, coloured by move */
const UNIVERSE = {
  "Technology": ["AAPL","MSFT","NVDA","AVGO","ORCL","AMD","CRM","ADBE","CSCO","QCOM","INTC","IBM","TXN","PLTR"],
  "Communication": ["GOOGL","META","NFLX","DIS"],
  "Consumer": ["AMZN","TSLA","HD","COST","WMT","KO","PEP","MCD","NKE"],
  "Financials": ["BRK-B","JPM","V","MA","BAC","GS"],
  "Health care": ["LLY","UNH","JNJ","MRK","ABBV","TMO"],
  "Energy": ["XOM","CVX"],
  "Industrials": ["GE","CAT","BA","LIN"],
};
const UNIVERSE_SYMS = Object.values(UNIVERSE).flat();
const SECTOR_ETFS = [["XLK","Technology"],["XLC","Communication"],["XLY","Consumer disc."],
  ["XLP","Consumer staples"],["XLF","Financials"],["XLV","Health care"],["XLE","Energy"],
  ["XLI","Industrials"],["XLB","Materials"],["XLU","Utilities"],["XLRE","Real estate"]];
const TAPE = [["^GSPC","S&P 500"],["^DJI","Dow"],["^IXIC","Nasdaq"],["^RUT","Russell 2000"],
  ["^VIX","VIX"],["^TNX","US 10Y"],["DX-Y.NYB","Dollar"],["CL=F","Crude"],["GC=F","Gold"],
  ["BTC-USD","Bitcoin"],["EURUSD=X","EUR/USD"]];
const MKT = { q: {}, t: 0 };

/* one request for everything the Pro shell and dashboard price: 70-odd symbols */
async function loadMarket(force) {
  if (!force && Date.now() - MKT.t < 55_000 && Object.keys(MKT.q).length) return MKT.q;
  const syms = [...UNIVERSE_SYMS, ...SECTOR_ETFS.map(x => x[0]), ...TAPE.map(x => x[0]), "SPY"];
  const d = await api(`/api/quotes?symbols=${syms.map(encodeURIComponent).join(",")}`);
  d.quotes.forEach(q => { MKT.q[q.symbol] = q; S.q[q.symbol] = S.q[q.symbol] || q; });
  MKT.t = Date.now();
  return MKT.q;
}

/* ── market status: open / pre / after / closed, from the ET clock, with the
      quote feed's own market_state to catch holidays ── */
function marketStatus() {
  const el = $("mktstatus"); if (!el || !PRO()) return;
  const et = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
  const day = et.getDay(), m = et.getHours() * 60 + et.getMinutes(), wk = day >= 1 && day <= 5;
  const spy = (MKT.q.SPY || {}).market_state || "";
  const dur = mins => mins >= 60 ? `${Math.floor(mins / 60)}h ${mins % 60}m` : `${mins}m`;
  const nextOpen = () => { let d = 0, dd = day, mm = m;
    do { if (dd >= 1 && dd <= 5 && (d > 0 || mm < 570)) break; d++; dd = (dd + 1) % 7; mm = 0; } while (d < 8);
    return d === 0 ? 570 - m : d * 1440 - m + 570; };
  let cls = "", label, sub;
  if (wk && m >= 570 && m < 960 && spy !== "CLOSED") { cls = "open"; label = "Market open"; sub = `closes in ${dur(960 - m)}`; }
  else if (wk && m >= 240 && m < 570) { cls = "ext"; label = "Pre-market"; sub = `opens in ${dur(570 - m)}`; }
  else if (wk && m >= 960 && m < 1200) { cls = "ext"; label = "After hours"; sub = `opens in ${dur(nextOpen())}`; }
  else { label = wk && m >= 570 && m < 960 ? "Market closed today" : "Market closed"; sub = `opens in ${dur(nextOpen())}`; }
  const clock = et.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  el.className = "pro-only " + cls;
  el.innerHTML = `<span class="dot"></span><b>${label}</b><span>· ${sub} · ${clock} ET</span>`;
}

async function loadTape() {
  const el = $("tape"); if (!el || !PRO()) return;
  try { await loadMarket(); } catch { return; }
  el.innerHTML = TAPE.map(([sym, lbl]) => { const q = MKT.q[sym]; if (!q || q.price == null) return "";
    const d = sym === "EURUSD=X" ? 4 : sym === "^TNX" ? 2 : q.price > 1000 ? 0 : 2;
    return `<div class="tp-item" style="cursor:default"><span class="tl">${esc(lbl)}</span>
      <span class="tv">${num(q.price, d)}${sym === "^TNX" ? "%" : ""}</span>
      <span class="tc ${sgn(q.change_pct)}">${pct(q.change_pct)}</span></div>`; }).join("");
  marketStatus();
}

/* ── colour for a move: diverging, clamped at ±3% ── */
function moveColor(p) {
  const t = Math.max(-1, Math.min(1, (p || 0) / 3));
  const mid = [59, 65, 80], up = [31, 157, 97], dn = [214, 64, 58];
  const to = t >= 0 ? up : dn, k = Math.abs(t);
  return `rgb(${mid.map((c, i) => Math.round(c + (to[i] - c) * k)).join(",")})`;
}

/* squarified treemap (Bruls, Huizing, van Wijk) - rows that keep cells near square */
function squarify(items, x, y, w, h) {
  const out = [], total = items.reduce((a, b) => a + b.v, 0);
  if (!total || w <= 0 || h <= 0) return out;
  let rest = items.map(it => ({ ...it, a: it.v * (w * h) / total }));
  let rx = x, ry = y, rw = w, rh = h;
  while (rest.length) {
    const side = Math.min(rw, rh); let row = [], best = Infinity;
    for (const it of rest) {
      const t = [...row, it], sum = t.reduce((a, b) => a + b.a, 0);
      const mx = Math.max(...t.map(r => r.a)), mn = Math.min(...t.map(r => r.a));
      const worst = Math.max(side * side * mx / (sum * sum), (sum * sum) / (side * side * mn));
      if (worst > best) break;
      best = worst; row = t;
    }
    const sum = row.reduce((a, b) => a + b.a, 0);
    if (rw >= rh) { const cw = sum / rh; let cy = ry;
      for (const r of row) { const ch = r.a / cw; out.push({ ...r, x: rx, y: cy, w: cw, h: ch }); cy += ch; }
      rx += cw; rw -= cw; }
    else { const ch = sum / rw; let cx = rx;
      for (const r of row) { const cw = r.a / ch; out.push({ ...r, x: cx, y: ry, w: cw, h: ch }); cx += cw; }
      ry += ch; rh -= ch; }
    rest = rest.slice(row.length);
  }
  return out;
}

function paintMarketMap(el) {
  if (!el) return;
  const W = el.clientWidth, H = el.clientHeight; if (!W) return;
  const secs = Object.entries(UNIVERSE).map(([name, syms]) => {
    const kids = syms.map(s => ({ s, q: MKT.q[s] || {} })).filter(k => k.q.market_cap)
      .map(k => ({ ...k, v: k.q.market_cap })).sort((a, b) => b.v - a.v);
    return { name, kids, v: kids.reduce((a, b) => a + b.v, 0) };
  }).filter(x => x.v).sort((a, b) => b.v - a.v);
  let html = "";
  for (const sec of squarify(secs, 0, 0, W, H)) {
    const lab = sec.h > 60 && sec.w > 70 ? 16 : 0;
    html += `<div class="mm-sec" style="left:${sec.x}px;top:${sec.y}px;width:${sec.w}px;height:${sec.h}px">
      ${lab ? `<span class="sl">${esc(sec.name)}</span>` : ""}</div>`;
    for (const c of squarify(sec.kids, sec.x, sec.y + lab, sec.w, sec.h - lab)) {
      const fs = Math.max(9, Math.min(22, Math.sqrt(c.w * c.h) / 5.2));
      const showS = c.w > 26 && c.h > 16, showP = c.w > 42 && c.h > fs * 2.4;
      html += `<div class="mm-cell" data-go="${esc(c.s)}" title="${esc(c.s)} ${esc(c.q.name || "")} ${pct(c.q.change_pct)}"
        style="left:${c.x}px;top:${c.y}px;width:${c.w}px;height:${c.h}px;background:${moveColor(c.q.change_pct)}">
        ${showS ? `<span class="s" style="font-size:${fs}px">${esc(c.s)}</span>` : ""}
        ${showP ? `<span class="p" style="font-size:${Math.max(9, fs * .62)}px">${pct(c.q.change_pct)}</span>` : ""}</div>`;
    }
  }
  el.innerHTML = html;
  el.querySelectorAll("[data-go]").forEach(c => c.onclick = () => location.hash = "#/t/" + c.dataset.go);
}

function moversHTML(kind) {
  const rows = UNIVERSE_SYMS.map(s => MKT.q[s]).filter(q => q && q.change_pct != null)
    .sort((a, b) => kind === "losers" ? a.change_pct - b.change_pct : b.change_pct - a.change_pct).slice(0, 6);
  return rows.map(q => `<div class="mv-row" data-go="${esc(q.symbol)}">
      <img src="${logo(q.symbol)}" alt="" loading="lazy">
      <div style="min-width:0"><div class="s">${esc(q.symbol)}</div><div class="n">${esc(q.name || "")}</div></div>
      <span class="px">${usdp(q.price)}</span>
      <span class="ch ${sgn(q.change_pct)}">${pct(q.change_pct)}</span></div>`).join("")
    || `<div class="pd-empty">No prices yet.</div>`;
}

function sectorsHTML() {
  const rows = SECTOR_ETFS.map(([s, n]) => ({ s, n, c: (MKT.q[s] || {}).change_pct }))
    .filter(r => r.c != null).sort((a, b) => b.c - a.c);
  const mx = Math.max(.5, ...rows.map(r => Math.abs(r.c)));
  return rows.map(r => { const w = Math.abs(r.c) / mx * 50;
    return `<div class="sec-row" title="${esc(r.s)}"><span class="n">${esc(r.n)}</span>
      <span class="bar"><i style="${r.c >= 0 ? `left:50%;width:${w}%;background:var(--pos)` : `right:50%;width:${w}%;background:var(--neg)`}"></i></span>
      <span class="c ${sgn(r.c)}">${pct(r.c)}</span></div>`; }).join("") || `<div class="pd-empty">No sector data.</div>`;
}

const DOW = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
function earningsHTML(d) {
  if (!d) return `<div class="skel" style="height:160px;margin:12px"></div>`;
  if (!d.items?.length) return `<div class="pd-empty">${esc(d.unavailable || "No large companies report this week.")}</div>`;
  return d.items.map(e => { const dt = new Date(e.date + "T12:00:00");
    return `<div class="er-row" data-go="${esc(e.symbol)}">
      <div class="dt"><span>${DOW[dt.getDay()]}</span><b>${dt.getDate()}</b></div>
      <div style="min-width:0"><div class="s">${esc(e.symbol)}</div><div class="n">${esc(e.name || "")}</div></div>
      <div class="when">${e.hour === "bmo" ? "Before open" : e.hour === "amc" ? "After close" : "Time TBA"}
        ${e.eps_estimate != null ? `<div>EPS est. ${num(e.eps_estimate)}</div>` : ""}</div></div>`; }).join("");
}

function newsHTML(items) {
  if (!items) return `<div class="skel" style="height:160px;margin:12px"></div>`;
  if (!items.length) return `<div class="pd-empty">No market headlines right now.</div>`;
  return items.slice(0, 7).map(h => { const ok = /^https?:\/\//i.test(h.url || "");
    return `<${ok ? `a href="${esc(h.url)}" target="_blank" rel="noopener"` : "div"} class="nw-row">
      <div class="h">${esc(h.title)}</div>
      <div class="m">${esc(h.publisher || "")}${h.published ? " · " + esc(whenPublished(h.published)) : ""}</div></${ok ? "a" : "div"}>`; }).join("");
}

function idxCellsHTML(d) {
  return d.indices.map(i => {
    if (i.kind === "sentiment") {
      const band = (CH.FNG_BANDS.find(b => i.level < b.to) || CH.FNG_BANDS.at(-1)).label;
      return `<div class="pd-ix"><div class="l">Fear &amp; Greed</div>
        <div class="v">${num(i.level, 0)} <span style="font-size:12px;font-weight:600;color:var(--muted-foreground);text-transform:capitalize">${esc(band)}</span></div>
        <div class="c" style="color:var(--subtle-foreground);font-weight:500">${i.change != null ? `${i.change >= 0 ? "+" : ""}${num(i.change, 1)} vs yesterday` : ""}</div>
        <div class="fg"><i style="left:calc(${Math.max(0, Math.min(100, i.level))}% - 1.5px)"></i></div></div>`;
    }
    const neutral = i.kind !== "index";
    return `<div class="pd-ix"><div class="l">${esc(i.label)}</div>
      <div class="v">${i.kind === "rate" ? num(i.level) + "%" : num(i.level, i.level > 1000 ? 0 : 2)}</div>
      <div class="c ${neutral ? "" : sgn(i.change_pct)}" ${neutral ? 'style="color:var(--muted-foreground)"' : ""}>${pct(i.change_pct)}</div>
      <div class="sp" data-ixp="${esc(i.symbol)}"></div></div>`;
  }).join("");
}

const HERO_KEY = "monsoon.pro.hero";
async function viewDashboardPro(nav) {
  crumbs([{label:"Dashboard"}]);
  const v = $("views");
  let heroOff = false; try { heroOff = localStorage.getItem(HERO_KEY) === "off"; } catch {}
  const demo = !S.wl.length;
  v.innerHTML = `<div class="page">
    ${ME.guest && !heroOff ? `<div class="pd-hero">
      <div><h1>Research any stock in plain English.</h1>
        <p>Live quotes, SEC financials and analyst data, plus a research agent that sends your question to
          specialists in parallel and checks every figure it quotes. No account needed.</p>
        <form class="ask" id="heroask"><input class="inp" id="heroq" placeholder="e.g. Is NVDA expensive relative to what it earns?" autocomplete="off">
          <button class="btn btn-primary" type="submit">Ask ${IC.arrow}</button></form>
        <div class="chips">${suggestions().slice(0, 3).map(q => `<button class="sugg" data-ask="${esc(q)}">${esc(q)}</button>`).join("")}</div></div>
      <button class="btn btn-sm btn-ghost x" id="herox" aria-label="Hide">${IC.x.replace("<svg", '<svg class="ico"')}</button></div>` : ""}
    <div class="pd-idx" id="pdidx">${Array(6).fill(`<div class="pd-ix"><div class="skel" style="height:62px"></div></div>`).join("")}</div>
    <div class="pd-grid">
      <div class="pd-col">
        <div class="pcard"><div class="pcard-h"><h4>Market map</h4>
          <span class="r"><span class="mm-legend"><span>−3%</span><i style="background:${moveColor(-3)}"></i><i style="background:${moveColor(-1)}"></i><i style="background:${moveColor(0)}"></i><i style="background:${moveColor(1)}"></i><i style="background:${moveColor(3)}"></i><span>+3%</span></span></span></div>
          <div class="mmap" id="mmap"><div class="skel" style="height:100%;border-radius:0"></div></div></div>
        <div id="pdsig"></div>
        <div class="pcard"><div class="pcard-h"><h4>${demo ? "Most watched" : "Watchlist"}</h4>
          <span class="r">${demo ? (ME.guest ? "sign in to keep your own list" : "add a ticker to start your own")
                                 : `${S.wl.length} tickers · live`}
            <input id="addinput" class="inp" style="width:150px;height:28px;padding:4px 9px" placeholder="Add ticker…"></span></div>
          <table class="wtable wl"><thead><tr>
            ${[["sym","Symbol"],["price","Last"],["change_pct","Change"],[null,"30-day"],["market_cap","Mkt cap"],["pe","P/E"],[null,""]]
              .map(([k,label])=>`<th ${k?`data-sort="${k}" class="sortable${wlSort.key===k?" on":""}"`:""}>${label}</th>`).join("")}
          </tr></thead><tbody id="wlbody"></tbody></table></div>
      </div>
      <div class="pd-col">
        <div class="pcard"><div class="pcard-h"><h4>Top movers</h4>
          <span class="r"><span class="seg" id="mvseg"><button class="on" data-mv="gainers">Gainers</button><button data-mv="losers">Losers</button></span></span></div>
          <div id="movers"><div class="skel" style="height:200px;margin:12px"></div></div></div>
        <div class="pcard"><div class="pcard-h"><h4>Sectors</h4><span class="r">SPDR sector funds · today</span></div>
          <div id="sectors" style="padding:6px 0"><div class="skel" style="height:200px;margin:12px"></div></div></div>
        <div class="pcard"><div class="pcard-h"><h4>Earnings this week</h4><span class="r">largest first</span></div>
          <div id="earnings">${earningsHTML(null)}</div></div>
        <div class="pcard"><div class="pcard-h"><h4>Market news</h4></div>
          <div id="mnews">${newsHTML(null)}</div></div>
      </div>
    </div></div>`;

  if ($("herox")) $("herox").onclick = () => { try { localStorage.setItem(HERO_KEY, "off"); } catch {} viewDashboardPro(); };
  if ($("heroask")) $("heroask").onsubmit = e => { e.preventDefault(); const q = $("heroq").value.trim(); if (q) submitAsk(q); };
  v.querySelectorAll("[data-ask]").forEach(b => b.onclick = () => submitAsk(b.dataset.ask));
  wireAdd();
  afterRender(v);
  const live = () => nav === undefined || nav === NAV.seq;

  // indices
  api("/api/indices").then(d => { if (!live() || !$("pdidx")) return;
    $("pdidx").innerHTML = idxCellsHTML(d);
    const by = Object.fromEntries(d.indices.map(i => [i.symbol, i]));
    $$("[data-ixp]").forEach(m => { const i = by[m.dataset.ixp]; if (i?.history?.length)
      CH.indexSpark(m, i.history, i.change_pct >= 0, i.kind !== "index"); });
  }).catch(() => { if ($("pdidx")) $("pdidx").innerHTML = `<div class="pd-empty">Index levels unavailable.</div>`; });

  // one request prices the map, movers, sectors and the watchlist
  const wl = demo ? POPULAR : S.wl;
  Promise.all([loadMarket(true), wl.length ? api(`/api/sparklines?symbols=${wl.join(",")}`).catch(() => null) : null])
    .then(([, sp]) => { if (!live()) return;
      if (sp) Object.assign(S.sparks, sp.sparklines);
      const mm = $("mmap"); paintMarketMap(mm);
      if (mm) new ResizeObserver(() => { if ($("mmap") === mm) paintMarketMap(mm); }).observe(mm);
      const paintMovers = k => { $("movers").innerHTML = moversHTML(k);
        $$("#movers [data-go]").forEach(r => r.onclick = () => location.hash = "#/t/" + r.dataset.go); };
      paintMovers("gainers");
      $$("#mvseg button").forEach(b => b.onclick = () => { $$("#mvseg button").forEach(x => x.classList.toggle("on", x === b)); paintMovers(b.dataset.mv); });
      $("sectors").innerHTML = sectorsHTML();
      paintWatch(); loadTape();
    }).catch(e => { if ($("mmap")) $("mmap").innerHTML = `<div class="pd-empty">Couldn't load prices: ${esc(e.message)}</div>`; });

  const paintWatch = () => {
    const held = new Set((S.pf?.positions || []).map(p => p.ticker));
    const rows = wl.map(x => ({ sym: x, held: held.has(x), ...quoteRow(x) })).filter(r => r.price != null);
    const body = $("wlbody"); if (!body) return;
    body.innerHTML = wlRows(rows) || `<tr><td colspan="7"><div class="empty">Prices are unavailable right now.</div></td></tr>`;
    $$("#wlbody [data-spark]").forEach(el => { const val = S.sparks[el.dataset.spark] || [];
      if (val.length > 1) CH.sparkline(el, val, val.at(-1) >= val[0]); });
    $$("#wlbody [data-go]").forEach(el => { el.onclick = () => location.hash = "#/t/" + el.dataset.go;
      el.onkeydown = e => { if (e.key === "Enter") el.click(); }; });
    $$("[data-sort]").forEach(th => th.onclick = () => { const k = th.dataset.sort;
      wlSort = { key: k, dir: wlSort.key === k ? -wlSort.dir : (k === "sym" ? 1 : -1) };
      $$("[data-sort]").forEach(x => x.classList.toggle("on", x.dataset.sort === wlSort.key)); paintWatch(); });
  };

  api("/api/calendar/earnings?days=7&limit=8").then(d => { if (live() && $("earnings")) {
    $("earnings").innerHTML = earningsHTML(d);
    $$("#earnings [data-go]").forEach(r => r.onclick = () => location.hash = "#/t/" + r.dataset.go); } })
    .catch(() => { if ($("earnings")) $("earnings").innerHTML = earningsHTML({ items: [], unavailable: "Earnings calendar unavailable." }); });

  // market news and today's flagged moves, straight from the data plane (no model call)
  api("/api/brief").then(b => { if (!live()) return;
    if ($("mnews")) $("mnews").innerHTML = newsHTML(b.market_headlines || []);
    const sigs = (b.signals || []).slice(0, 4);
    if (sigs.length && $("pdsig")) { $("pdsig").innerHTML = signalStrip({ ...b, signals: sigs });
      $$("#pdsig [data-go]").forEach(el => el.onclick = () => location.hash = "#/t/" + el.dataset.go); }
  }).catch(() => { if ($("mnews")) $("mnews").innerHTML = newsHTML([]); });
}

/* ── ticker page: a quote header and a stats strip in place of the card grid ── */
function qBarHTML(symbols, cmp) {
  const by = Object.fromEntries((cmp?.rows || []).map(r => [r.symbol, r]));
  return `<div class="q-bar">${symbols.map(t => { const r = by[t] || {};
    return `<div class="q-chip ${t === S.cur ? "on" : ""}" data-qfocus="${esc(t)}">
      ${symbols.length > 1 ? `<input type="checkbox" data-pick="${esc(t)}" aria-label="Include ${esc(t)} in analysis" ${S.picked.has(t) ? "checked" : ""}>` : ""}
      <img src="${logo(t)}" alt="">${esc(t)}<span class="c ${sgn(r.change_pct)}">${pct(r.change_pct)}</span>
      <button class="xx" data-close="${esc(t)}" aria-label="Close ${esc(t)}" title="Close">${IC.x}</button></div>`; }).join("")}
    ${symbols.length > 1 ? `<button class="btn btn-sm" id="showOverlay2">Compare performance</button>` : ""}</div>`;
}

async function fillQuoteHeader(sym) {
  const head = $("qhead"); if (!head) return;
  const [qd, bars, ov] = await Promise.all([
    api(`/api/quotes?symbols=${encodeURIComponent(sym)}`).catch(() => null),
    getBars(sym, "1mo", "1d").catch(() => []),
    api(`/api/overview/${encodeURIComponent(sym)}`).catch(() => ({}))]);
  if (S.cur !== sym || !$("qhead")) return;
  const q = qd?.quotes?.[0] || {}, last = bars.at(-1) || {}, prev = bars.at(-2) || {};
  const avgVol = bars.length ? bars.slice(-20).reduce((a, b) => a + (b.v || 0), 0) / Math.min(20, bars.length) : null;
  const st = (q.market_state || "").toUpperCase();
  const stLabel = st === "REGULAR" ? "Live · market open" : st.startsWith("PRE") ? "Pre-market"
    : st.startsWith("POST") ? "After hours" : "At close";
  const inWl = S.wl.includes(sym);
  head.innerHTML = `<img src="${logo(sym)}" alt="">
    <div class="id"><div class="sym">${esc(sym)} ${ov.sector ? `<span class="badge ghost">${esc(ov.sector)}</span>` : ""}</div>
      <div class="nm">${esc(q.name || ov.name || "")}${ov.industry ? " · " + esc(ov.industry) : ""}</div></div>
    <div class="px"><div class="p">${usdp(q.price ?? ov.price)}</div>
      <div class="c ${sgn(q.change_pct)}">${q.change != null ? `${q.change >= 0 ? "+" : "−"}${num(Math.abs(q.change))} ` : ""}(${pct(q.change_pct)})</div>
      <div class="st">${stLabel}${last.t ? " · " + new Date(last.t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : ""}</div>
      <div class="acts"><button class="btn btn-sm" id="qwatch">${inWl ? "✓ Watching" : "+ Watchlist"}</button>
        <button class="btn btn-sm btn-primary" id="qask">${IC.spark} Ask about ${esc(sym)}</button></div></div>`;
  const lo = q.low_52w ?? ov.low_52w, hi = q.high_52w ?? ov.high_52w, px = q.price ?? ov.price;
  const pos52 = lo != null && hi != null && hi > lo && px != null ? (px - lo) / (hi - lo) * 100 : null;
  const stat = (k, v) => `<div class="qstat"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  $("qstats").innerHTML = [
    stat("Open", usdp(last.o)), stat("Day range", last.l != null ? `${num(last.l)}–${num(last.h)}` : "—"),
    stat("Prev close", usdp(prev.c)), stat("Volume", abbr(q.volume ?? last.v)), stat("Avg vol (20d)", abbr(avgVol)),
    stat("Market cap", usd(q.market_cap ?? ov.market_cap)), stat("P/E (TTM)", num(q.pe ?? ov.pe, 1)),
    stat("Fwd P/E", num(ov.forward_pe, 1)),
    stat("Div yield", ov.dividend_yield ? num(ov.dividend_yield, 2) + "%" : "—"),
    `<div class="qstat" style="grid-column:span 2"><div class="k">52-week range</div>
      <div class="v">${lo != null ? `${num(lo)}–${num(hi)}` : "—"}</div>
      ${pos52 != null ? `<div class="rng"><i style="left:calc(${pos52.toFixed(1)}% - 1.5px)"></i></div>` : ""}</div>`
  ].join("");
  $("qwatch").onclick = async () => {
    if (S.wl.includes(sym)) return;
    try { S.wl = (await jpost("/api/watchlist", { ticker: sym })).watchlist; $("qwatch").textContent = "✓ Watching";
          toast(`${sym} added to your watchlist`, "ok"); }
    catch (err) { if (err.status === 401) needAccount(`Create an account to keep ${sym} on a watchlist.`, { kind: "watch", ticker: sym });
                  else toast(err.message, "error"); }
  };
  $("qask").onclick = () => { openAgent(true); syncAsk(); $("ask").focus(); };
}

/* OHLC readout above the chart: the bar under the crosshair, else the latest */
function ohlcHTML(b, prevClose) {
  if (!b) return "";
  const ch = prevClose ? (b.close - prevClose) / prevClose * 100 : null;
  return `<span>O<b>${num(b.open)}</b></span><span>H<b>${num(b.high)}</b></span><span>L<b>${num(b.low)}</b></span>
    <span>C<b>${num(b.close)}</b></span>${b.vol != null ? `<span>Vol<b>${abbr(b.vol)}</b></span>` : ""}
    ${ch != null ? `<span class="${sgn(ch)}" style="font-weight:600">${pct(ch)}</span>` : ""}`;
}
function wireOhlc(bars) {
  const el = $("ohlc"); if (!el || !chart || !bars?.length) return;
  const byT = new Map(bars.map((b, i) => [b.t, i]));
  const show = i => { const b = bars[i]; if (!b) return;
    el.innerHTML = ohlcHTML({ open: b.o, high: b.h, low: b.l, close: b.c, vol: b.v }, bars[i - 1]?.c); };
  show(bars.length - 1);
  if (chart.__ohlc) chart.unsubscribeCrosshairMove(chart.__ohlc);
  chart.__ohlc = p => { const i = p?.time != null ? byT.get(p.time) : undefined; show(i ?? bars.length - 1); };
  chart.subscribeCrosshairMove(chart.__ohlc);
}

/* overview as a two-column list: label left, value right - reads like a quote sheet */
function kvHTML(rows) {
  return `<dl class="kv">${rows.map(([k, v, s]) => `<div><dt>${esc(k)}</dt><dd>${v}${s ? `<span class="s">${esc(s)}</span>` : ""}</dd></div>`).join("")}</dl>`;
}

/* ── ⌘K: every ticker, view and question one keystroke away ── */
const CMD = { items: [], active: 0, timer: 0, seq: 0 };
const ICN = {
  page: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/></svg>`,
  ask: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M10.5 3.2l1.75 4.8 4.8 1.75-4.8 1.75-1.75 4.8-1.75-4.8L4 9.75l4.75-1.75z"/></svg>`,
  cog: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>`,
};
function cmdBase(q) {
  const ql = q.toLowerCase(), out = [];
  if (q.length > 2) out.push({ grp: "Ask the agent", icon: ICN.ask, t: q, d: "Send to the research agent", run: () => submitAsk(q) });
  const pages = [["Dashboard", "#/dashboard"], ["Research", "#/t/" + (lastTicker() || "NVDA")], ["Daily brief", "#/brief"], ["Portfolio", "#/portfolio"]];
  pages.filter(([n]) => !ql || n.toLowerCase().includes(ql))
       .forEach(([n, h]) => out.push({ grp: "Go to", icon: ICN.page, t: n, run: () => location.hash = h }));
  const acts = [["Switch to Classic interface", () => setUI("classic")],
                [LIGHT() ? "Switch to dark theme" : "Switch to light theme", toggleTheme],
                ["New agent conversation", () => $("agentnew").click()]];
  acts.filter(([n]) => !ql || n.toLowerCase().includes(ql))
      .forEach(([n, f]) => out.push({ grp: "Actions", icon: ICN.cog, t: n, run: f }));
  return out;
}
function cmdPaint() {
  let grp = "", html = "";
  CMD.items.forEach((it, i) => {
    if (it.grp !== grp) { grp = it.grp; html += `<div class="cmdgrp">${esc(grp)}</div>`; }
    html += `<div class="cmditem ${i === CMD.active ? "on" : ""}" data-i="${i}" role="option">
      ${it.sym ? `<img src="${logo(it.sym)}" alt="">` : `<span class="ci">${it.icon}</span>`}
      <div style="min-width:0"><div class="t">${esc(it.t)}</div>${it.d ? `<div class="d">${esc(it.d)}</div>` : ""}</div>
      <span class="k">${it.k ? esc(it.k) : ""}</span></div>`;
  });
  $("cmdres").innerHTML = html || `<div class="lkempty">No matches</div>`;
  $$("#cmdres .cmditem").forEach(el => { el.onmousemove = () => { if (CMD.active !== +el.dataset.i) { CMD.active = +el.dataset.i; cmdPaint(); } };
    el.onclick = () => cmdRun(+el.dataset.i); });
  $("cmdres").querySelector(".cmditem.on")?.scrollIntoView({ block: "nearest" });
}
function cmdRun(i) { const it = CMD.items[i]; if (!it) return; closeCmd(); it.run(); }
function openCmd() {
  if (!PRO()) return;
  $("cmdpal").classList.add("on"); $("cmdq").value = ""; CMD.active = 0;
  const recent = [...new Set([...(S.basket || []), ...S.wl])].slice(0, 5);
  CMD.items = [...recent.map(s => ({ grp: "Recent", sym: s, t: s, d: (S.q[s] || {}).name || "", k: pct((S.q[s] || {}).change_pct),
                                     run: () => location.hash = "#/t/" + s })), ...cmdBase("")];
  cmdPaint(); setTimeout(() => $("cmdq").focus(), 20);
}
const closeCmd = () => $("cmdpal").classList.remove("on");
$("cmdq").oninput = () => {
  const q = $("cmdq").value.trim(); clearTimeout(CMD.timer); CMD.active = 0;
  CMD.items = cmdBase(q); cmdPaint();
  if (!q) return openCmd();
  const seq = ++CMD.seq;
  CMD.timer = setTimeout(async () => {
    let r = []; try { r = (await api(`/api/search?q=${encodeURIComponent(q)}`)).results || []; } catch {}
    if (seq !== CMD.seq) return;                          // a newer keystroke won
    const tick = r.filter(x => SYM_RE.test(String(x.symbol).toUpperCase())).slice(0, 6)
      .map(x => ({ grp: "Tickers", sym: x.symbol, t: x.symbol, d: x.name, k: x.exchange || x.type,
                   run: () => location.hash = "#/t/" + x.symbol }));
    const base = cmdBase(q);
    // a query that looks like a ticker puts tickers first; a sentence puts "ask" first
    CMD.items = /\s/.test(q) ? [...base.slice(0, 1), ...tick, ...base.slice(1)] : [...tick, ...base];
    CMD.active = 0; cmdPaint();
  }, 160);
};
$("cmdq").onkeydown = e => {
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault();
    CMD.active = Math.max(0, Math.min(CMD.items.length - 1, CMD.active + (e.key === "ArrowDown" ? 1 : -1))); cmdPaint(); }
  else if (e.key === "Enter") { e.preventDefault(); cmdRun(CMD.active); }
  else if (e.key === "Escape") closeCmd();
};
$("cmdpal").onclick = e => { if (e.target.id === "cmdpal") closeCmd(); };
$("cmdk").onclick = openCmd;

/* ── interface + theme switches ── */
function syncSwitch() {
  $$("#uiswitch button").forEach(b => b.classList.toggle("on", b.dataset.ui === document.documentElement.dataset.ui));
  const m = document.querySelector('meta[name="theme-color"]');
  if (m) m.content = LIGHT() ? "#ffffff" : "#0b0d12";
}
function setUI(ui) {
  document.documentElement.dataset.ui = ui;
  try { localStorage.setItem("monsoon.ui", ui); } catch {}
  syncSwitch(); applyPalette(); rerender();
  if (PRO()) loadTape();
}
function toggleTheme() {
  const t = LIGHT() ? "dark" : "light";
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("monsoon.theme", t); } catch {}
  syncSwitch(); applyPalette(); rerender();
}
function rerender() { try { chartRO?.disconnect(); chart?.remove(); } catch {} chart = null; route(); }
$$("#uiswitch button").forEach(b => b.onclick = () => setUI(b.dataset.ui));
$("themebtn").onclick = toggleTheme;
$("navcollapse").onclick = () => {
  const c = document.documentElement.dataset.nav === "collapsed";
  if (c) delete document.documentElement.dataset.nav; else document.documentElement.dataset.nav = "collapsed";
  try { localStorage.setItem("monsoon.nav", c ? "open" : "collapsed"); } catch {}
  setTimeout(() => { if (chart) { const el = $("chart"); if (el?.clientWidth) chart.applyOptions({ width: el.clientWidth }); }
    const mm = $("mmap"); if (mm) paintMarketMap(mm); }, 60);
};

/* ── notices instead of alert() ── */
function toast(msg, kind = "info", ms = 4200) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`; el.textContent = msg; el.setAttribute("role", kind === "error" ? "alert" : "status");
  $("toasts").appendChild(el);
  mo(el, { opacity: [0, 1], y: [8, 0] }, { duration: .22 });
  setTimeout(() => el.remove(), ms);
}

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

/* Every view awaits the network, and you can click away while it does. Each
   navigation takes a number; a view whose number is no longer current does
   not paint, so a slow earlier page never lands on top of a newer one. */
const NAV = { seq: 0 };
async function route() {
  const nav = ++NAV.seq;
  document.getElementById("views").scrollTop = 0;   // new destination starts at the top
  const h = (location.hash || "#/dashboard").slice(2);
  const [head, arg] = h.split("/");
  const r = head==="t" ? "ticker" : head;
  $$(".navitem").forEach(n => { const on = n.dataset.route === r;
    n.classList.toggle("on", on); on ? n.setAttribute("aria-current", "page") : n.removeAttribute("aria-current"); });
  if (head === "t") {
    S.route = "ticker";
    let raw = ""; try { raw = decodeURIComponent(arg || ""); } catch { raw = ""; }
    const syms = cleanSyms(raw.split(",")).slice(0, 8);
    syncAsk();
    await viewResearch(syms, nav);
  }
  else if (head === "brief") { S.route="brief"; syncAsk(); await viewBrief(nav); }
  else if (head === "portfolio") { S.route="portfolio"; syncAsk(); await viewPortfolio(nav); }
  else { S.route="dashboard"; syncAsk(); await viewDashboard(nav); }
  if (nav !== NAV.seq) return;
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
$("right").inert = true;                              // collapsed: out of the tab order
$("agentnew").onclick = () => { if (T.ctl) T.ctl.abort(); T.turns = []; saveThread(); renderThread(); $("ask").focus(); };
$("tclose").onclick = closeTrace;
$("briefclose").onclick = closeBrief;
$("briefopen").onclick = () => { closeBrief(); location.hash = "#/brief"; };
$("briefsheet").onclick = e => { if (e.target.id === "briefsheet") closeBrief(); };
$("trace").onclick = e => { if (e.target.id==="trace") closeTrace(); };
addEventListener("keydown", e => {
  if (e.key==="Escape") { closeTrace(); closeBrief(); closeAuth(); closeCmd(); closePw(); }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k" && PRO()) { e.preventDefault(); openCmd(); return; }
  // "/" opens the agent from anywhere that is not already a text field
  if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName||"")) {
    e.preventDefault(); openAgent(true); $("ask").focus(); }
});
/* the panel animates open from zero width, and a textarea measured mid-slide
   wraps every character onto its own line - so measure only once it is laid out */
const growAsk = () => { const a = $("ask"); if (a.clientWidth < 120) return;
  a.style.height = "auto"; a.style.height = Math.min(a.scrollHeight + 2, 132) + "px"; };
$("ask").oninput = growAsk;
$("ask").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
  e.preventDefault(); $("askform").requestSubmit(); } };
$("askform").onsubmit = e => { e.preventDefault();
  if (T.ctl) { T.ctl.abort(); return; }               // the send button doubles as stop
  const v = $("ask").value.trim();
  if (v) { submitAsk(v); $("ask").value = ""; growAsk(); } };

api("/build").then(b => $("buildstamp").textContent = b.build.slice(-6)).catch(()=>{});
await loadMe();
await replayResume();
const health = await api("/api/health").catch(()=>({}));
S.llm = !!health.llm_configured;
if (!S.llm) $("rst").textContent = "no key";
syncSwitch(); applyPalette();
try { await refreshAll(); } catch (e) { console.warn("initial load", e); }   // still paint the view
renderThread();
await route();
maybeShowBrief();
loadTape();
setInterval(() => { if (!document.hidden && PRO()) { loadTape(); } }, 60_000);
setInterval(marketStatus, 30_000);
/* "live" means the cells move: patch price and change in place, flash on a tick */
function patchPrices() {
  $$("#wlbody tr[data-sym]").forEach(tr => {
    const q = S.q[tr.dataset.sym]; if (!q) return;
    const px = tr.querySelector(".px"), ch = tr.querySelector(".chg");
    if (px && px.textContent !== num(q.price)) {
      const was = parseFloat(px.textContent.replace(/,/g,""));
      px.textContent = num(q.price);
      tr.classList.remove("flash-up","flash-dn"); void tr.offsetWidth;
      if (!isNaN(was)) tr.classList.add(q.price >= was ? "flash-up" : "flash-dn");
    }
    if (ch) { ch.textContent = pct(q.change_pct); ch.className = `mono chg ${sgn(q.change_pct)}`; }
  });
}
setInterval(async () => {
  if (document.hidden) return;
  const syms = S.wl.length ? S.wl : (S.route === "dashboard" ? POPULAR : []);
  if (!syms.length) return;
  const d = await api(`/api/quotes?symbols=${syms.join(",")}`).catch(()=>null);
  if (!d) return; d.quotes.forEach(q=>S.q[q.symbol]=q); pfSummary();
  if (S.route === "dashboard") patchPrices(); }, 30000);
