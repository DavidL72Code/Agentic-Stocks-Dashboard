"""The next earnings report for one company - one answer for the research page,
the events endpoint, the brief and the agent's next_earnings tool.

Two things went wrong when each read Yahoo's calendar on its own:
  * Yahoo keeps a report's date after it has happened. The day after CoreWeave
    reported, "next earnings" was still yesterday, days_away -1.
  * Yahoo's calendar needs the crumb, which Render never gets, so on the live
    site every one of them was null - NVDA six days from reporting showed none.
So: Yahoo's date only if it has not passed (New York time, not the server's
UTC), otherwise Finnhub's next scheduled report.
"""
from __future__ import annotations
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

log = logging.getLogger("provider.earnings")
NY = ZoneInfo("America/New_York")


def ny_today() -> date:
    return datetime.now(NY).date()


def _iso(v: Any) -> str | None:
    s = str(v)[:10] if v not in (None, "") else ""
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return None


async def next_report(symbol: str) -> dict:
    """{date, days_away, hour, eps_estimate, eps_low, eps_high, revenue_estimate,
    revenue_low, revenue_high, source} - or {} when nothing is scheduled."""
    from . import finnhub, yahoo
    sym, today = symbol.upper(), ny_today()
    try:
        cal = await yahoo.attr(sym, "calendar", 21600) or {}
    except Exception as e:
        log.info("yahoo calendar %s failed: %s", sym, e)
        cal = {}
    dates = cal.get("Earnings Date")
    dates = dates if isinstance(dates, list) else [dates]
    ahead = sorted(d for d in (_iso(x) for x in dates) if d and d >= today.isoformat())
    if ahead:
        out = {"date": ahead[0], "hour": "",
               "eps_estimate": cal.get("Earnings Average"),
               "eps_low": cal.get("Earnings Low"), "eps_high": cal.get("Earnings High"),
               "revenue_estimate": cal.get("Revenue Average"),
               "revenue_low": cal.get("Revenue Low"), "revenue_high": cal.get("Revenue High"),
               "source": "yahoo"}
    elif finnhub.enabled():
        try:
            rows = await finnhub.earnings_calendar(today.isoformat(),
                                                   (today + timedelta(days=120)).isoformat(), sym)
        except Exception as e:
            log.info("finnhub calendar %s failed: %s", sym, e)
            rows = []
        fut = sorted((r for r in rows if (r.get("symbol") or "").upper() == sym
                      and (_iso(r.get("date")) or "") >= today.isoformat()), key=lambda r: r["date"])
        if not fut:
            return {}
        r = fut[0]
        out = {"date": _iso(r["date"]), "hour": r.get("hour") or "",
               "eps_estimate": r.get("epsEstimate"), "eps_low": None, "eps_high": None,
               "revenue_estimate": r.get("revenueEstimate"),
               "revenue_low": None, "revenue_high": None, "source": "finnhub"}
    else:
        return {}
    out["days_away"] = (date.fromisoformat(out["date"]) - today).days
    from ..tools.sources import CAL_SRC          # so the page's source line names who said so
    CAL_SRC[sym] = out["source"]
    return out
