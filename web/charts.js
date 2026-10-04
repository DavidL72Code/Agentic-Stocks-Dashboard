/* Recharts islands. Colors come from the validated palette in index.html's token
   layer (dataviz validator, dark mode, surface #0d0f14):
     series  #9085e9 / #c98500 / #3987e5   — ALL PASS
     pos/neg #199e70 / #e66767             — CVD ΔE 6.5, paired with ± signs
   Every chart ships a hover tooltip, per the skill's interaction default. */
import React from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
import * as RC from "https://esm.sh/recharts@2.12.7?deps=react@18.3.1,react-dom@18.3.1";

const h = React.createElement;
const roots = new WeakMap();
export const C = { s1:"#9085e9", s2:"#c98500", s3:"#3987e5",
                   pos:"#199e70", neg:"#e66767", ink:"#8d95a4", faint:"#15181f" };

function mount(el, node) {
  if (!el) return;
  let r = roots.get(el);
  if (!r) { r = createRoot(el); roots.set(el, r); }
  r.render(node);
}
const abbr = v => { const a = Math.abs(v ?? 0);
  return a>=1e12?(v/1e12).toFixed(2)+"T":a>=1e9?(v/1e9).toFixed(1)+"B"
       :a>=1e6?(v/1e6).toFixed(1)+"M":a>=1e3?(v/1e3).toFixed(1)+"K":String(v ?? "—"); };

/* shared tooltip shell so every chart reads the same */
const Tip = (label, value, sub) => h("div", { className: "rt-tip" },
  h("div", { className: "lab" }, label),
  h("div", { className: "val" }, value),
  sub ? h("div", { className: "sub" }, sub) : null);

/* ── sparkline: identity of one series, no axes, hover disabled (too small) ── */
export function sparkline(el, values, positive) {
  if (!el) return;
  const data = (values || []).map((v, i) => ({ i, v }));
  const col = positive ? C.pos : C.neg;
  const id = "sg" + Math.random().toString(36).slice(2, 8);
  mount(el, h(RC.ResponsiveContainer, { width: "100%", height: 26 },
    h(RC.AreaChart, { data, margin: { top: 2, right: 0, bottom: 0, left: 0 } },
      h("defs", null, h("linearGradient", { id, x1: "0", y1: "0", x2: "0", y2: "1" },
        h("stop", { offset: "0%", stopColor: col, stopOpacity: .32 }),
        h("stop", { offset: "100%", stopColor: col, stopOpacity: 0 }))),
      h(RC.YAxis, { hide: true, domain: ["dataMin", "dataMax"] }),
      h(RC.Area, { type: "monotone", dataKey: "v", stroke: col, strokeWidth: 1.4,
                   fill: `url(#${id})`, isAnimationActive: false, dot: false }))));
}

/* ── quarterly revenue: magnitude over time, one series, 4px rounded ends ── */
export function revenue(el, quarters) {
  const data = (quarters || []).map(q => ({
    q: q.end.slice(2, 7), rev: q.revenue, ni: q.net_income, margin: q.operating_margin, end: q.end }));
  mount(el, h(RC.ResponsiveContainer, { width: "100%", height: 200 },
    h(RC.BarChart, { data, margin: { top: 18, right: 4, bottom: 0, left: -14 } },
      h("defs", null, h("linearGradient", { id: "revg", x1: "0", y1: "0", x2: "0", y2: "1" },
        h("stop", { offset: "0%", stopColor: C.s1, stopOpacity: .95 }),
        h("stop", { offset: "100%", stopColor: C.s1, stopOpacity: .30 }))),
      h(RC.CartesianGrid, { vertical: false, stroke: C.faint }),
      h(RC.XAxis, { dataKey: "q", tickLine: false, axisLine: false, dy: 6 }),
      h(RC.YAxis, { tickFormatter: abbr, tickLine: false, axisLine: false, width: 56 }),
      h(RC.Tooltip, { cursor: { fill: "rgba(144,133,233,.07)" },
        content: ({ active, payload }) => active && payload?.[0]
          ? Tip(payload[0].payload.end, "$" + abbr(payload[0].payload.rev),
                payload[0].payload.margin != null
                  ? `net ${"$" + abbr(payload[0].payload.ni)} · op margin ${payload[0].payload.margin}%`
                  : null) : null }),
      h(RC.Bar, { dataKey: "rev", fill: "url(#revg)", radius: [4, 4, 0, 0],
                  maxBarSize: 46, isAnimationActive: true, animationDuration: 620 }))));
}

/* ── earnings surprise: polarity around zero → diverging, two poles + zero line ── */
export function surprise(el, history) {
  const data = (history || []).slice().reverse().map(r => ({
    d: r.date.slice(2), s: r.surprise_pct, a: r.actual, e: r.estimate }));
  mount(el, h(RC.ResponsiveContainer, { width: "100%", height: 170 },
    h(RC.BarChart, { data, margin: { top: 10, right: 4, bottom: 0, left: -18 } },
      h(RC.CartesianGrid, { vertical: false, stroke: C.faint }),
      h(RC.XAxis, { dataKey: "d", tickLine: false, axisLine: false, dy: 6 }),
      h(RC.YAxis, { tickFormatter: v => v + "%", tickLine: false, axisLine: false, width: 48 }),
      h(RC.ReferenceLine, { y: 0, stroke: "#2a303c" }),
      h(RC.Tooltip, { cursor: { fill: "rgba(144,133,233,.07)" },
        content: ({ active, payload }) => active && payload?.[0]
          ? Tip(payload[0].payload.d,
                payload[0].payload.s == null ? "—" : (payload[0].payload.s >= 0 ? "+" : "") + payload[0].payload.s + "%",
                `actual ${payload[0].payload.a} vs ${payload[0].payload.e} est`) : null }),
      h(RC.Bar, { dataKey: "s", radius: [4, 4, 0, 0], maxBarSize: 40,
                  animationDuration: 560 },
        data.map((d, i) => h(RC.Cell, { key: i, fill: d.s >= 0 ? C.pos : C.neg }))))));
}

/* ── analyst consensus: ordered categories → one stacked bar, 2px surface gaps ── */
export function consensus(el, buckets) {
  const rows = buckets.filter(b => b.n > 0);
  const total = rows.reduce((a, b) => a + b.n, 0) || 1;
  mount(el, h("div", null,
    h("div", { style: { display: "flex", gap: 2, height: 12, marginBottom: 10 } },
      rows.map((b, i) => h("div", {
        key: b.label, title: `${b.label}: ${b.n}`,
        style: { width: (b.n / total * 100) + "%", background: b.color,
                 borderRadius: i === 0 ? "6px 2px 2px 6px"
                            : i === rows.length - 1 ? "2px 6px 6px 2px" : "2px" } }))),
    h("div", { style: { display: "flex", flexWrap: "wrap", gap: "6px 16px" } },
      rows.map(b => h("div", { key: b.label,
        style: { display: "flex", alignItems: "center", gap: 6, fontSize: 11 } },
        h("span", { style: { width: 8, height: 8, borderRadius: 3, background: b.color } }),
        h("span", { style: { color: "var(--muted-foreground)" } }, b.label),
        h("b", { style: { fontFamily: "JetBrains Mono, monospace" } }, b.n))))));
}

/* ── portfolio allocation: part-to-whole → donut with a hero number ── */
export function allocation(el, positions, total) {
  const pal = [C.s1, C.s2, C.s3, "#b7adf7", "#7a6fd0", "#4d7fb8"];
  const data = (positions || []).map((p, i) => ({
    name: p.ticker, value: p.market_value, color: pal[i % pal.length] }));
  mount(el, h(RC.ResponsiveContainer, { width: "100%", height: 208 },
    h(RC.PieChart, null,
      h(RC.Tooltip, { content: ({ active, payload }) => active && payload?.[0]
        ? Tip(payload[0].payload.name, "$" + abbr(payload[0].payload.value),
              (payload[0].payload.value / total * 100).toFixed(1) + "% of book") : null }),
      h(RC.Pie, { data, dataKey: "value", nameKey: "name", innerRadius: 58, outerRadius: 86,
                  paddingAngle: 2, stroke: "var(--surface)", strokeWidth: 2,
                  animationDuration: 620 },
        data.map((d, i) => h(RC.Cell, { key: i, fill: d.color }))),
      h(RC.Legend, { verticalAlign: "bottom", height: 24,
        formatter: v => h("span", { style: { color: "var(--muted-foreground)", fontSize: 11 } }, v) }))));
}


/* ── index sparkline: a month of closes, no axes, just the shape ── */
export function indexSpark(el, values, positive, neutral) {
  if (!el || !(values||[]).length) return;
  const data = values.map((v,i)=>({i,v}));
  const col = neutral ? "#8d95a4" : (positive ? C.pos : C.neg);
  const id = "ix" + Math.random().toString(36).slice(2,8);
  mount(el, h(RC.ResponsiveContainer, { width:"100%", height:34 },
    h(RC.AreaChart, { data, margin:{top:3,right:0,bottom:0,left:0} },
      h("defs", null, h("linearGradient", { id, x1:"0", y1:"0", x2:"0", y2:"1" },
        h("stop", { offset:"0%", stopColor:col, stopOpacity:.34 }),
        h("stop", { offset:"100%", stopColor:col, stopOpacity:0 }))),
      h(RC.YAxis, { hide:true, domain:["dataMin","dataMax"] }),
      h(RC.Tooltip, { cursor:{stroke:"rgba(255,255,255,.2)"},
        content: ({active,payload}) => active && payload?.[0]
          ? Tip("Level", num2(payload[0].payload.v)) : null }),
      h(RC.Area, { type:"monotone", dataKey:"v", stroke:col, strokeWidth:1.5,
                   fill:`url(#${id})`, isAnimationActive:false, dot:false }))));
}
const num2 = v => Number(v).toLocaleString(undefined,{maximumFractionDigits:2});

/* ── fear & greed: a 0-100 position, so a gauge reads better than a line ── */
export const FNG_BANDS = [
  { to:25,  label:"extreme fear",  color:"#e66767" },
  { to:45,  label:"fear",          color:"#e0916b" },
  { to:55,  label:"neutral",       color:"#8d95a4" },
  { to:75,  label:"greed",         color:"#57b98f" },
  { to:101, label:"extreme greed", color:"#199e70" },
];
export const fngColor = s => (FNG_BANDS.find(b => s < b.to) || FNG_BANDS.at(-1)).color;

export function fngGauge(el, score, history) {
  if (!el) return;
  const col = fngColor(score);
  // 180deg speedometer: extreme fear at the left stop, extreme greed at the right
  const W = 200, H = 112, cx = W/2, cy = 96, rOut = 86, rIn = 62;
  const pol = (r, deg) => { const a = (180 - deg) * Math.PI / 180;
    return [cx + r*Math.cos(a), cy - r*Math.sin(a)]; };
  const arc = (from, to, r1, r2) => {
    const [x1,y1]=pol(r1,from), [x2,y2]=pol(r1,to), [x3,y3]=pol(r2,to), [x4,y4]=pol(r2,from);
    return `M${x1},${y1} A${r1},${r1} 0 0 1 ${x2},${y2} L${x3},${y3} A${r2},${r2} 0 0 0 ${x4},${y4} Z`;
  };
  const clamped = Math.max(0, Math.min(100, score ?? 0));
  const needleDeg = clamped * 1.8;                 // 0..100 -> 0..180
  // The reading is a marker ON the dial, not a needle from the centre: a
  // centre needle ran straight through the number and the band label for
  // most of the range, in the same colour, so the digits merged into it.
  const [m1x, m1y] = pol(rIn - 7, needleDeg), [m2x, m2y] = pol(rOut + 4, needleDeg);

  let from = 0;
  const bands = FNG_BANDS.map(b => {
    const to = Math.min(b.to, 100) * 1.8;
    const d = arc(from + (from ? 1.2 : 0), to, rOut, rIn);
    const active = clamped < b.to && (from === 0 || clamped >= from/1.8);
    from = to;
    return h("path", { key:b.label, d, fill:b.color, opacity: active ? 1 : .26 });
  });

  mount(el, h("div", { style:{display:"flex",flexDirection:"column",alignItems:"center"} },
    h("svg", { viewBox:`0 0 ${W} ${H}`, width:"100%", style:{maxWidth:"210px",display:"block"},
               role:"img", "aria-label":`Fear and greed index ${Math.round(clamped)}` },
      bands,
      h("line", { x1:m1x, y1:m1y, x2:m2x, y2:m2y, stroke:"#0b0d13", strokeWidth:6, strokeLinecap:"round" }),
      h("line", { x1:m1x, y1:m1y, x2:m2x, y2:m2y, stroke:"#fff", strokeWidth:2.5, strokeLinecap:"round" }),
      // end labels
      h("text", { x:6, y:H-2, fill:"#8d95a6", fontSize:7.5, fontFamily:"Inter,sans-serif",
                  letterSpacing:".06em" }, "EXTREME FEAR"),
      h("text", { x:W-6, y:H-2, textAnchor:"end", fill:"#8d95a6", fontSize:7.5,
                  fontFamily:"Inter,sans-serif", letterSpacing:".06em" }, "EXTREME GREED"),
      // the reading, centred in the dial with the band name under it
      h("text", { x:cx, y:cy-14, textAnchor:"middle", fill:col, fontSize:28, fontWeight:650,
                  fontFamily:"JetBrains Mono,monospace", letterSpacing:"-.04em" },
        String(Math.round(clamped))),
      h("text", { x:cx, y:cy, textAnchor:"middle", fill:"#adb4c2", fontSize:8,
                  fontWeight:700, letterSpacing:".14em", fontFamily:"Inter,sans-serif" },
        (FNG_BANDS.find(b=>clamped<b.to)||FNG_BANDS.at(-1)).label.toUpperCase()))));
}


/* ── relative performance: N normalised paths on one axis ──
   Series colours use the reference palette's published slot order (blue,
   orange, aqua, yellow, magenta, violet) rather than an order I invented,
   since adjacent-pair CVD separation was validated for that sequence.
   Every line is also direct-labelled, which is the secondary encoding the
   skill requires when CVD separation sits in the warn band. */
export function multiLine(el, paths, symbols, colors) {
  if (!el || !(paths || []).length) return;
  const data = paths.map(p => ({ ...p, d: new Date(p.t * 1000) }));
  const fmt = t => new Date(t * 1000).toLocaleDateString(undefined,
    { month: "short", day: "numeric" });
  mount(el, h(RC.ResponsiveContainer, { width: "100%", height: 300 },
    h(RC.LineChart, { data, margin: { top: 10, right: 54, bottom: 0, left: -12 } },
      h(RC.CartesianGrid, { vertical: false, stroke: C.faint }),
      h(RC.XAxis, { dataKey: "t", tickFormatter: fmt, tickLine: false,
                    axisLine: false, dy: 6, minTickGap: 48 }),
      h(RC.YAxis, { tickFormatter: v => v + "", tickLine: false, axisLine: false, width: 48,
                    domain: ["auto", "auto"] }),
      h(RC.ReferenceLine, { y: 100, stroke: "#2a303c", strokeDasharray: "3 3" }),
      h(RC.Tooltip, {
        cursor: { stroke: "rgba(255,255,255,.2)" },
        content: ({ active, payload, label }) => active && payload?.length
          ? h("div", { className: "rt-tip" },
              h("div", { className: "lab" }, fmt(label)),
              payload.slice().sort((a, b) => b.value - a.value).map(pl =>
                h("div", { key: pl.dataKey, className: "sub",
                           style: { color: pl.stroke, fontFamily: "JetBrains Mono, monospace" } },
                  `${pl.dataKey}  ${(pl.value - 100) >= 0 ? "+" : ""}${(pl.value - 100).toFixed(1)}%`)))
          : null }),
      h(RC.Legend, { verticalAlign: "top", height: 28, iconType: "plainline",
        formatter: v => h("span", { style: { color: "var(--muted-foreground)", fontSize: 11.5 } }, v) }),
      symbols.map((sym, i) => h(RC.Line, {
        key: sym, type: "monotone", dataKey: sym,
        stroke: (colors || [])[i % (colors || []).length] || C.s1,
        strokeWidth: 2, dot: false, isAnimationActive: true, animationDuration: 520,
        label: ({ index, x, y, value }) =>                    // direct label at the end
          index === data.length - 1 && value != null
            ? h("text", { x: x + 6, y: y + 4, fill: (colors || [])[i % (colors || []).length],
                          fontSize: 10.5, fontWeight: 650,
                          fontFamily: "JetBrains Mono, monospace" }, sym)
            : null })))));
}
