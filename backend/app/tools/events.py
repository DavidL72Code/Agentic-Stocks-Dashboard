from __future__ import annotations
from datetime import datetime, timezone
from ..providers import edgar, yahoo
from ._util import empty, fail, ok
from .registry import tool


def _since(period: str | None) -> str | None:
    from datetime import date, timedelta
    days = {"1mo": 31, "3mo": 92, "6mo": 183, "1y": 366, "2y": 731, "5y": 1827}.get(period or "")
    if period == "ytd":
        return f"{date.today().year}-01-01"
    return str(date.today() - timedelta(days=days)) if days else None


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
async def recent_filings(ticker: str, limit: int = 6, period: str | None = None, **_):
    # with a window, list what was filed IN it (8-Ks carry their reasons), not just
    # the last six - a CEO exit in May is invisible in "the six most recent"
    since = _since(period)
    f = await edgar.filings(ticker, limit=1000 if since else limit, since=since)
    if since:   # drop insider Form 4s etc. BEFORE capping, or they crowd out the 8-Ks
        f = [x for x in f if x["form"] in ("8-K", "10-Q", "10-K", "8-K/A")][:15] or f[:limit]
    if not f:
        return empty("recent_filings", ticker, "no SEC filings (non-US filer?)")
    from .sources import SEC_COMPANY
    from ..providers.edgar import cik_for
    cik = await cik_for(ticker)
    return ok("recent_filings", ticker, {"filings": f}, source="sec-edgar",
              url=SEC_COMPANY.format(cik=cik, form="") if cik else None,
              label=f"SEC EDGAR · {ticker.upper()} filings (each filing links its document)")


@tool("events", "ex-dividend date and dividend payment schedule")
async def ex_dividend(ticker: str, **_):
    i = await yahoo.info(ticker)
    d = {k: i[k] for k in ("exDividendDate", "dividendDate", "lastDividendValue") if i.get(k)}
    if not d:
        return empty("ex_dividend", ticker, f"{ticker} pays no dividend")
    return ok("ex_dividend", ticker, d)
