"""Charts that support an answer - only when one helps.

Picked deterministically from the figures the answer actually CITES, never by
the model, so a chart can only show numbers the evidence holds and a question
about news or a definition gets none. At most two. A price path goes first when
the answer cites a return - it shows what the text can't (how the shares got
there); the bar charts that follow are ranked by how many cited figures they
illustrate:

  returns of 2+ names           -> price paths indexed to 100 (lines)
  one name's return             -> its path against the S&P 500 (lines)
  margins of 2+ names           -> grouped bars: gross / operating / net
  valuation of 2+ names         -> grouped bars: P/E, forward P/E
  revenue growth of 2+ names    -> bars: revenue vs a year ago
  one name's revenue growth     -> its quarterly revenue (bars, from the filings)

Bar charts carry their values (the same ones the answer cites). Line and
quarterly charts carry only what to fetch: the client loads the price paths
and filings from the cached /api/compare and /api/financials endpoints.
"""
from __future__ import annotations
from collections import Counter

PERIOD = {"1mo": "the past month", "3mo": "the past 3 months", "6mo": "the past 6 months",
          "ytd": "this year", "1y": "the past year", "2y": "the past 2 years", "5y": "the past 5 years"}
BARS = {   # tool -> (title, unit, [(field, legend label)])
    "profitability": ("Margins over the last 12 months", "%",
                      [("gross_margin", "Gross"), ("operating_margin", "Operating"), ("net_margin", "Net")]),
    "valuation_multiples": ("Price-to-earnings", "×",
                            [("pe_trailing", "P/E (last 12 months)"), ("pe_forward", "Forward P/E")]),
    "growth_rates": ("Revenue growth vs a year ago", "%", [("yoy_pct", "Latest quarter")]),
}
MAX_CHARTS = 2
MAX_NAMES = 6
RETURN_TOOLS = ("price_series", "peer_performance", "relative_strength")
LINES_FIRST = 1000


def _evidence(run) -> dict[str, dict[str, object]]:
    """tool -> ticker -> its result, company tickers only (not the market-wide rows)."""
    out: dict[str, dict[str, object]] = {}
    for f in run.findings:
        for e in getattr(f, "evidence", []) or []:
            if e.ticker and e.ticker not in ("MARKET", "PORTFOLIO", "-"):
                out.setdefault(e.tool, {})[e.ticker] = e
    return out


def _cited(run) -> Counter:
    """How many of the answer's figures cite each tool."""
    by_n = {s["n"]: s.get("tool") for s in run.sources or []}
    c: Counter = Counter()
    for sg in run.segments or []:
        for n in sg.get("s", []):
            if by_n.get(n):
                c[by_n[n]] += 1
    return c


def _src(e) -> dict:
    return {"label": e.prov.label if e.prov else e.tool, "url": e.prov.url if e.prov else None}


def _rs_period(d: dict) -> str:
    """relative_strength names its window in its keys ("ytd_stock_pct")."""
    for k in d:
        w = k[:-len("_stock_pct")] if k.endswith("_stock_pct") else None
        if w and w not in ("1m", "3m"):
            return w
    return "3mo"


def _bars(tool: str, results: dict) -> dict | None:
    title, unit, fields = BARS[tool]
    names = list(results)[:MAX_NAMES]
    have = [(f, lab) for f, lab in fields
            if sum(isinstance(results[t].data.get(f), (int, float)) for t in names) >= 2]
    if not have:
        return None
    rows = [{"label": t, **{f: round(float(results[t].data[f]), 2) for f, _ in have
                            if isinstance(results[t].data.get(f), (int, float))}} for t in names]
    rows = [r for r in rows if len(r) > 1]
    if len(rows) < 2:
        return None
    srcs, seen = [], set()
    for t in names:
        for f, _ in have:      # a field's own page when it has one (forward P/E, SEC margins)
            meta = (results[t].data.get("_src") or {}).get(f)
            s = {"label": meta.get("label"), "url": meta.get("url")} if isinstance(meta, dict) else _src(results[t])
            if s["url"] and s["url"] not in seen:
                seen.add(s["url"]); srcs.append(s)
    return {"kind": "bars", "title": title, "unit": unit,
            "series": [{"key": f, "label": lab} for f, lab in have], "rows": rows, "sources": srcs}


def pick(run) -> list[dict]:
    ev, cited = _evidence(run), _cited(run)
    cands: list[tuple[int, dict]] = []

    # a return over a window can come from any of these; each names its window
    ret_n = sum(cited.get(t, 0) for t in RETURN_TOOLS)
    if ret_n:
        by_p: dict[str, list[str]] = {}
        for tool in RETURN_TOOLS:
            for t, e in ev.get(tool, {}).items():
                p = e.data.get("period") or (_rs_period(e.data) if tool == "relative_strength" else "3mo")
                if t not in by_p.setdefault(p, []):
                    by_p[p].append(t)
        period, names = max(by_p.items(), key=lambda kv: len(kv[1]))
        names = names[:MAX_NAMES]
        one = len(names) == 1
        srcs = [_src(next(ev[tool][t] for tool in RETURN_TOOLS if t in ev.get(tool, {}))) for t in names]
        cands.append((LINES_FIRST + ret_n, {
            "kind": "lines", "period": period,
            "symbols": names + (["SPY"] if one else []),
            "labels": {"SPY": "S&P 500"} if one else {},
            "title": (f"{names[0]} vs the S&P 500, {PERIOD.get(period, period)}" if one
                      else f"Share price, {PERIOD.get(period, period)}"),
            "note": "Each line starts at 100, so a move compares fairly whatever the share price.",
            "sources": srcs}))

    for tool in BARS:
        res = ev.get(tool, {})
        if len(res) >= 2 and cited.get(tool):
            ch = _bars(tool, res)
            if ch:
                cands.append((cited[tool], ch))

    g = ev.get("growth_rates", {})
    if len(g) == 1 and cited.get("growth_rates"):
        (t, e), = g.items()
        cands.append((cited["growth_rates"], {
            "kind": "revenue", "symbol": t, "title": f"{t} revenue by quarter",
            "sources": [_src(e)]}))

    cands.sort(key=lambda c: -c[0])         # stable: earlier candidates win a tie
    return [c for _, c in cands[:MAX_CHARTS]]
