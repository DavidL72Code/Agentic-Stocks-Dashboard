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


# Filing events that bear on how a company is run, as opposed to how it trades.
# Every one is a fact in an SEC filing, not an opinion about management.
_RED_FORMS = {"NT 10-K": "filed its annual report late",
              "NT 10-Q": "filed a quarterly report late",
              "NT 20-F": "filed its annual report late"}
_RED_ITEMS = {"prior financials unreliable": "restated or withdrew prior financials",
              "auditor change": "changed auditor",
              "delisting notice": "received a delisting or listing-standard notice",
              "unregistered share sale": "sold unregistered shares",
              "change in control": "change in control"}
_CHURN_ITEM = "executive or director change"


@tool("events",
      "GOVERNANCE FLAGS from SEC filings: late reports, restatements, auditor "
      "changes, delisting notices, executive churn. Use for questions about "
      "whether management is trustworthy or well run", derived=True)
async def governance_flags(ticker: str, years: int = 5, **_):
    """What "is management trustworthy" can honestly be grounded in.

    These are filing FACTS, each with a date and an SEC link: a restatement
    (8-K item 4.02) means the company told the SEC its own past numbers could
    not be relied on. An auditor change right after one is a different story
    from a routine rotation. Late filings and delisting notices are similarly
    hard evidence.

    What this deliberately does NOT do is score or rank "trust", and it does
    not look for scandals - there is no structured feed for those, and an
    opinion dressed as a metric is worse than no metric. Absence of flags is
    reported as exactly that: nothing filed, not a clean bill of health.
    """
    since = f"{datetime.now(timezone.utc).year - years}-01-01"
    f = await edgar.filings(ticker, limit=4000, since=since)
    if not f:
        return empty("governance_flags", ticker, "no SEC filings (non-US filer?)")

    events, churn = [], 0
    for row in f:
        if row["form"] in _RED_FORMS:
            events.append({"date": row["date"], "what": _RED_FORMS[row["form"]],
                           "form": row["form"], "url": row.get("url")})
        for reason in row.get("reasons", []):
            if reason in _RED_ITEMS:
                events.append({"date": row["date"], "what": _RED_ITEMS[reason],
                               "form": row["form"], "url": row.get("url")})
            elif reason == _CHURN_ITEM:
                churn += 1

    events.sort(key=lambda e: e["date"], reverse=True)
    counts: dict[str, int] = {}
    for e in events:
        counts[e["what"]] = counts.get(e["what"], 0) + 1

    if events:
        reading = (f"{len(events)} governance event(s) in SEC filings since {since[:4]}: "
                   + "; ".join(f"{v}x {k}" for k, v in counts.items()))
    else:
        reading = (f"no late filings, restatements, auditor changes or delisting "
                   f"notices filed since {since[:4]}")
    if churn:
        reading += f". {churn} executive/director change filing(s) over the window"

    return ok("governance_flags", ticker, {
        "window_from": since, "events": events[:12], "counts": counts,
        "exec_change_filings": churn,
        "filings_scanned": len(f), "reading": reading,
        "note": ("filing facts only. No scandal search and no trust score - "
                 "there is no structured source for either, and an opinion "
                 "presented as a metric is worse than none. No flags means "
                 "nothing was filed, not that nothing happened."),
    }, source="sec-edgar")
