from __future__ import annotations
from datetime import datetime, timezone
from ..providers import edgar, yahoo
from ._util import empty, fail, ok
from .registry import tool


@tool("events", "next earnings date and the consensus EPS estimate")
async def next_earnings(ticker: str, **_):
    cal = await yahoo.attr(ticker, "calendar", ttl=21600) or {}
    d = cal.get("Earnings Date")
    if isinstance(d, list) and d:
        d = d[0]
    if not d:
        return empty("next_earnings", ticker, "no scheduled earnings date")
    out = {"earnings_date": str(d)[:10], "eps_estimate": cal.get("Earnings Average"),
           "revenue_estimate": cal.get("Revenue Average")}
    try:
        out["days_away"] = (datetime.fromisoformat(str(d)[:10]).date() - datetime.now(timezone.utc).date()).days
    except Exception:
        pass
    return ok("next_earnings", ticker, {k: v for k, v in out.items() if v is not None})


@tool("events", "past earnings: estimate vs actual, i.e. beat/miss history")
async def earnings_surprise_history(ticker: str, limit: int = 6, **_):
    raw = await yahoo.attr(ticker, "earnings_dates", ttl=21600) or {}
    rows = sorted(raw.items(), key=lambda kv: str(kv[0]), reverse=True)
    out = []
    for k, v in rows:
        est, act = v.get("EPS Estimate"), v.get("Reported EPS")
        if est is None or act is None:
            continue
        out.append({"date": str(k)[:10], "eps_estimate": est, "eps_actual": act,
                    "surprise_pct": round((act - est) / abs(est) * 100, 1) if est else None,
                    "beat": act > est})
        if len(out) >= limit:
            break
    if not out:
        return empty("earnings_surprise_history", ticker, "no reported earnings history")
    return ok("earnings_surprise_history", ticker,
              {"history": out, "beats": sum(1 for r in out if r["beat"]), "of": len(out)})


@tool("events", "recent SEC filings (10-Q, 8-K, Form 4 insider filings)")
async def recent_filings(ticker: str, limit: int = 6, **_):
    f = await edgar.filings(ticker, limit=limit)
    if not f:
        return empty("recent_filings", ticker, "no SEC filings (non-US filer?)")
    return ok("recent_filings", ticker, {"filings": f}, source="sec-edgar")


@tool("events", "ex-dividend date and dividend payment schedule")
async def ex_dividend(ticker: str, **_):
    i = await yahoo.info(ticker)
    d = {k: i[k] for k in ("exDividendDate", "dividendDate", "lastDividendValue") if i.get(k)}
    if not d:
        return empty("ex_dividend", ticker, f"{ticker} pays no dividend")
    return ok("ex_dividend", ticker, d)
