"""Portfolio domain - reads the user's own holdings, not an external feed.
All derived: no upstream call beyond the batched quote the data plane already
warmed."""
from __future__ import annotations
import numpy as np, pandas as pd
from .. import store
from ..providers import yahoo
from ._util import closes, empty, fail, ok, pct
from .registry import tool


async def _priced(account: str | None = "all") -> list[dict]:
    """Default to every account combined - a question about "my portfolio"
    means the whole book unless an account is named."""
    pos = store.all_positions(account)
    if not pos:
        return []
    q = await yahoo.quotes([p["ticker"] for p in pos])
    out = []
    for p in pos:
        r = q.get(p["ticker"]) or {}
        px = r.get("regularMarketPrice")
        if px is None:
            continue
        out.append({**p, "price": px, "value": px * p["qty"],
                    "cost": p["basis"] * p["qty"],
                    "pnl": (px - p["basis"]) * p["qty"],
                    "pnl_pct": round((px / p["basis"] - 1) * 100, 2),
                    "day_pct": r.get("regularMarketChangePercent")})
    return out


@tool("portfolio", "every holding with shares, cost basis, market value and P&L", derived=True)
async def positions(ticker: str = "", account: str = "all", **_):
    rows = await _priced(account)
    if not rows:
        return empty("positions", ticker or "-", "no holdings recorded")
    tot = sum(r["value"] for r in rows)
    return ok("positions", ticker or "PORTFOLIO", {
        "holdings": [{"ticker": r["ticker"], "account": r.get("account"),
                      "shares": r["qty"], "avg_cost": r["basis"],
                      "price": round(r["price"], 2), "market_value": round(r["value"], 2),
                      "pnl": round(r["pnl"], 2), "pnl_pct": r["pnl_pct"],
                      "weight_pct": round(r["value"] / tot * 100, 1) if tot else None}
                     for r in rows],
        "accounts": sorted({r.get("account") for r in rows if r.get("account")}),
        "total_market_value": round(tot, 2),
        "total_cost": round(sum(r["cost"] for r in rows), 2),
        "total_pnl": round(sum(r["pnl"] for r in rows), 2)}, source="user+derived")


@tool("portfolio", "today's profit and loss across the whole book", derived=True)
async def day_pnl(ticker: str = "", account: str = "all", **_):
    rows = await _priced(account)
    if not rows:
        return empty("day_pnl", ticker or "-", "no holdings recorded")
    day = sum(r["value"] * (r["day_pct"] or 0) / 100 for r in rows)
    tot = sum(r["value"] for r in rows)
    best = max(rows, key=lambda r: (r["day_pct"] or 0))
    worst = min(rows, key=lambda r: (r["day_pct"] or 0))
    return ok("day_pnl", ticker or "PORTFOLIO", {
        "day_pnl_usd": round(day, 2),
        "day_pnl_pct": round(day / (tot - day) * 100, 2) if tot - day else None,
        "best_today": {"ticker": best["ticker"], "pct": best["day_pct"]},
        "worst_today": {"ticker": worst["ticker"], "pct": worst["day_pct"]}},
        source="user+derived")


@tool("portfolio", "how concentrated the book is - top weights and any outsized position", derived=True)
async def concentration(ticker: str = "", account: str = "all", **_):
    rows = await _priced(account)
    if not rows:
        return empty("concentration", ticker or "-", "no holdings recorded")
    tot = sum(r["value"] for r in rows)
    w = sorted(((r["ticker"], r["value"] / tot * 100) for r in rows), key=lambda x: -x[1])
    hhi = sum((x[1] / 100) ** 2 for x in w)
    return ok("concentration", ticker or "PORTFOLIO", {
        "weights_pct": [{"ticker": t, "pct": round(p, 1)} for t, p in w],
        "top_holding": {"ticker": w[0][0], "pct": round(w[0][1], 1)},
        "top3_pct": round(sum(p for _, p in w[:3]), 1),
        "herfindahl": round(hhi, 3),
        "reading": "highly concentrated" if hhi > .3 else "concentrated" if hhi > .18 else "reasonably spread"},
        source="derived")


@tool("portfolio", "how correlated the holdings are with each other", derived=True)
async def correlation_matrix(ticker: str = "", account: str = "all", **_):
    rows = await _priced(account)
    syms = sorted({r["ticker"] for r in rows})
    if len(syms) < 2:
        return empty("correlation_matrix", ticker or "-", "need at least two holdings")
    ser = {}
    for s in syms:
        c = await closes(s, "1y")
        if len(c) > 60:
            ser[s] = c
    if len(ser) < 2:
        return fail("correlation_matrix", ticker or "-", "insufficient overlapping history")
    r = pd.DataFrame(ser).dropna().pct_change().dropna()
    cm = r.corr()
    pairs = [{"pair": f"{a}/{b}", "corr": round(float(cm.loc[a, b]), 2)}
             for i, a in enumerate(cm.columns) for b in cm.columns[i + 1:]]
    pairs.sort(key=lambda d: -d["corr"])
    return ok("correlation_matrix", ticker or "PORTFOLIO", {
        "pairs": pairs, "most_correlated": pairs[0], "least_correlated": pairs[-1],
        "average_pairwise": round(float(np.mean([p["corr"] for p in pairs])), 2),
        "note": "high average pairwise correlation means the book moves as one position"},
        source="derived")


@tool("portfolio", "portfolio beta vs SPY - how much it amplifies the market", derived=True)
async def portfolio_beta(ticker: str = "", account: str = "all", **_):
    rows = await _priced(account)
    if not rows:
        return empty("portfolio_beta", ticker or "-", "no holdings recorded")
    spy = await closes("SPY", "1y")
    if spy.empty:
        return fail("portfolio_beta", ticker or "-", "no benchmark history")
    tot = sum(r["value"] for r in rows)
    betas, used = [], []
    for r in rows:
        c = await closes(r["ticker"], "1y")
        j = pd.concat([c.rename("a"), spy.rename("b")], axis=1).dropna().pct_change().dropna()
        if len(j) > 60:
            b = float(np.polyfit(j["b"], j["a"], 1)[0])
            betas.append(b * r["value"] / tot)
            used.append({"ticker": r["ticker"], "beta": round(b, 2)})
    if not betas:
        return fail("portfolio_beta", ticker or "-", "insufficient history")
    return ok("portfolio_beta", ticker or "PORTFOLIO", {
        "portfolio_beta": round(sum(betas), 2), "per_holding": used,
        "reading": "more volatile than the market" if sum(betas) > 1.1
                   else "less volatile than the market" if sum(betas) < 0.9 else "roughly market-like"},
        source="derived")
