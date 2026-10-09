"""Data plane. No LLM anywhere in this file - that is the point."""
from __future__ import annotations
import asyncio, re
from datetime import date, datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import store
from ..cache import CACHE, cache_stats
from fastapi.responses import Response

from ..providers import edgar, logos, sentiment, yahoo
from ..providers.yahoo import clean          # scrubs pandas NaN/Inf -> None
from ..tools import TOOLS

router = APIRouter(prefix="/api")


@router.get("/health")
async def health():
    from ..llm import MODEL, api_key, status
    from .. import db
    return clean({"ok": True, "llm_configured": bool(api_key()), "model": MODEL,
                  "models": status(),
                  "db": db.backend_name(),
                  "tools": len(TOOLS), "cache": cache_stats(),
                  "quote_batches": yahoo.QUOTE_LOADER.batches,
                  "quote_keys_served": yahoo.QUOTE_LOADER.keys_served})


@router.get("/quotes")
async def quotes(symbols: str = Query(...)):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:100]
    before = yahoo.QUOTE_LOADER.batches          # measure THIS request, not lifetime
    q = await yahoo.quotes(syms)
    used = yahoo.QUOTE_LOADER.batches - before
    out = []
    for s in syms:
        r = q.get(s)
        if not r:
            continue
        out.append({"symbol": s, "name": r.get("shortName") or r.get("longName"),
                    "price": r.get("regularMarketPrice"),
                    "change": r.get("regularMarketChange"),
                    "change_pct": r.get("regularMarketChangePercent"),
                    "volume": r.get("regularMarketVolume"),
                    "market_cap": r.get("marketCap"), "pe": r.get("trailingPE"),
                    "high_52w": r.get("fiftyTwoWeekHigh"),
                    "low_52w": r.get("fiftyTwoWeekLow"),
                    "market_state": r.get("marketState"), "currency": r.get("currency")})
    return clean({"quotes": out, "http_requests_used": used,
                  "http_batches_lifetime": yahoo.QUOTE_LOADER.batches})


@router.get("/bars/{symbol}")
async def bars(symbol: str, period: str = "1mo", interval: str = "1d"):
    b = await yahoo.bars(symbol, period=period, interval=interval)
    if not b:
        raise HTTPException(404, f"no bars for {symbol}")
    return clean({"symbol": symbol.upper(), "period": period,
                  "interval": interval, "bars": b})


@router.get("/sparklines")
async def sparklines(symbols: str = Query(...)):
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:50]
    res = await asyncio.gather(*(yahoo.bars(s, "1mo", "1d") for s in syms),
                               return_exceptions=True)
    return clean({"sparklines": {s: ([x["c"] for x in r] if isinstance(r, list) else [])
                                 for s, r in zip(syms, res)}})


@router.get("/overview/{symbol}")
async def overview(symbol: str):
    i, q = await asyncio.gather(yahoo.info(symbol), yahoo.quote(symbol))
    q = q or {}
    keys = {"marketCap": "market_cap", "trailingPE": "pe", "forwardPE": "forward_pe",
            "priceToBook": "price_to_book", "profitMargins": "net_margin",
            "operatingMargins": "operating_margin", "grossMargins": "gross_margin",
            "returnOnEquity": "roe", "debtToEquity": "debt_to_equity",
            "currentRatio": "current_ratio", "totalCash": "cash", "totalDebt": "debt",
            "freeCashflow": "fcf", "revenueGrowth": "revenue_growth",
            "dividendYield": "dividend_yield", "sector": "sector",
            "industry": "industry", "fullTimeEmployees": "employees",
            "longBusinessSummary": "summary"}
    o = {v: i.get(k) for k, v in keys.items() if i.get(k) is not None}
    o.update({"symbol": symbol.upper(), "name": q.get("shortName") or i.get("shortName"),
              "price": q.get("regularMarketPrice"),
              "change_pct": q.get("regularMarketChangePercent"),
              "high_52w": q.get("fiftyTwoWeekHigh"), "low_52w": q.get("fiftyTwoWeekLow"),
              "market_state": q.get("marketState")})
    return clean(o)


@router.get("/financials/{symbol}")
async def financials(symbol: str):
    rev, ni, oi, gp, cal, ed = await asyncio.gather(
        edgar.concept(symbol, "revenue", 8), edgar.concept(symbol, "net_income", 8),
        edgar.concept(symbol, "operating_income", 8),
        edgar.concept(symbol, "gross_profit", 8),
        yahoo.attr(symbol, "calendar", 21600),
        yahoo.attr(symbol, "earnings_dates", 21600))
    by: dict[str, dict] = {}
    for label, rows in (("revenue", rev), ("net_income", ni),
                        ("operating_income", oi), ("gross_profit", gp)):
        for r in rows:
            by.setdefault(r["end"], {"end": r["end"], "form": r.get("form"),
                                     "filed": r.get("filed")})[label] = r["val"]
    quarters = sorted(by.values(), key=lambda d: d["end"])[-8:]
    for qq in quarters:
        if qq.get("revenue") and qq.get("operating_income"):
            qq["operating_margin"] = round(qq["operating_income"] / qq["revenue"] * 100, 1)
        if qq.get("revenue") and qq.get("gross_profit"):
            qq["gross_margin"] = round(qq["gross_profit"] / qq["revenue"] * 100, 1)
    # --- upcoming earnings + what the street expects ---
    cal = cal or {}
    nxt = cal.get("Earnings Date")
    if isinstance(nxt, list) and nxt:
        nxt = nxt[0]
    upcoming = {"date": str(nxt)[:10] if nxt else None,
                "eps_estimate": cal.get("Earnings Average"),
                "eps_low": cal.get("Earnings Low"), "eps_high": cal.get("Earnings High"),
                "revenue_estimate": cal.get("Revenue Average"),
                "revenue_low": cal.get("Revenue Low"), "revenue_high": cal.get("Revenue High")}
    if upcoming["date"]:
        try:
            d = datetime.fromisoformat(upcoming["date"]).date()
            upcoming["days_away"] = (d - datetime.now(timezone.utc).date()).days
        except Exception:
            pass

    # --- did each past report beat or miss? ---
    track = []
    for k, v in sorted((ed or {}).items(), key=lambda kv: str(kv[0]), reverse=True):
        est, act = v.get("EPS Estimate"), v.get("Reported EPS")
        if est is None or act is None:
            continue
        track.append({"date": str(k)[:10], "eps_estimate": est, "eps_actual": act,
                      "surprise_pct": round((act - est) / abs(est) * 100, 1) if est else None,
                      "result": "beat" if act > est else "miss" if act < est else "in line"})
        if len(track) >= 8:
            break
    beats = sum(1 for t in track if t["result"] == "beat")

    return clean({"symbol": symbol.upper(), "source": "SEC EDGAR XBRL",
                  "note": "each row is one ~91-day quarter; cumulative rollups filtered out",
                  "quarters": quarters,
                  "upcoming": upcoming,
                  "track_record": track,
                  "beats": beats, "reports": len(track)})


def _relevant(title: str, sym: str, name: str | None) -> bool:
    """Yahoo's feed mixes in syndicated filler that never names the company.
    Flag whether the headline actually mentions this issuer."""
    t = (title or "").lower()
    if sym.lower() in t.split() or sym.lower() in t:
        return True
    if name:
        head = name.lower().replace(",", "").split()
        for w in head[:2]:
            if len(w) > 3 and w not in ("inc", "corp", "the", "company", "holdings") and w in t:
                return True
    return False


@router.get("/news/{symbol}")
async def news(symbol: str):
    raw, q = await asyncio.gather(yahoo.news_for(symbol, 12), yahoo.quote(symbol))
    name = (q or {}).get("shortName") or (q or {}).get("longName")
    out = [{**n, "mentions_issuer": _relevant(n["title"], symbol.upper(), name)}
           for n in (raw or [])]
    out.sort(key=lambda x: not x["mentions_issuer"])
    rel = sum(1 for x in out if x["mentions_issuer"])
    return clean({"symbol": symbol.upper(), "items": out,
                  "relevant": rel, "total": len(out),
                  "note": ("sentiment is not supplied by this feed; "
                           f"{rel} of {len(out)} headlines actually name the issuer "
                           "(Yahoo mixes in syndicated filler)")})


@router.get("/analysts/{symbol}")
async def analysts(symbol: str):
    i, ud, rec = await asyncio.gather(
        yahoo.info(symbol),
        yahoo.attr(symbol, "upgrades_downgrades", 43200),
        yahoo.attr(symbol, "recommendations", 43200))
    rows = sorted((ud or {}).items(), key=lambda kv: str(kv[0]), reverse=True)[:10]
    # real bucket counts, current period ("0m") - never modelled from the mean
    cur = None
    for v in (rec or {}).values():
        if str(v.get("period")) == "0m":
            cur = v
            break
    dist = ([{"label": lab, "n": int(cur.get(k) or 0)}
             for k, lab in (("strongBuy", "Strong buy"), ("buy", "Buy"), ("hold", "Hold"),
                            ("sell", "Sell"), ("strongSell", "Strong sell"))]
            if cur else [])
    return clean({
        "symbol": symbol.upper(),
        "consensus": {k: i.get(k) for k in
                      ("recommendationKey", "recommendationMean", "numberOfAnalystOpinions")
                      if i.get(k) is not None},
        "targets": {k: i.get(k) for k in
                    ("targetLowPrice", "targetMeanPrice", "targetHighPrice", "currentPrice")
                    if i.get(k) is not None},
        "distribution": dist,
        "changes": [{"date": str(k)[:10], "firm": v.get("Firm"), "to": v.get("ToGrade"),
                     "from": v.get("FromGrade"), "action": v.get("Action")}
                    for k, v in rows]})


@router.get("/events/{symbol}")
async def events(symbol: str):
    cal, ed, fil = await asyncio.gather(
        yahoo.attr(symbol, "calendar", 21600),
        yahoo.attr(symbol, "earnings_dates", 21600),
        edgar.filings(symbol, 8))
    cal = cal or {}
    d = cal.get("Earnings Date")
    if isinstance(d, list) and d:
        d = d[0]
    hist = []
    for k, v in sorted((ed or {}).items(), key=lambda kv: str(kv[0]), reverse=True):
        est, act = v.get("EPS Estimate"), v.get("Reported EPS")
        if est is None or act is None:
            continue
        hist.append({"date": str(k)[:10], "estimate": est, "actual": act,
                     "surprise_pct": round((act - est) / abs(est) * 100, 1) if est else None})
        if len(hist) >= 6:
            break
    return clean({"symbol": symbol.upper(),
                  "next_earnings": str(d)[:10] if d else None,
                  "eps_estimate": cal.get("Earnings Average"),
                  "surprise_history": hist, "filings": fil})


def _require_account():
    """Guests can read the market and ask the agent; they cannot own a book."""
    if store.is_guest():
        raise HTTPException(401, "Sign in to keep a watchlist or portfolio.")

class Watch(BaseModel):
    ticker: str


class Position(BaseModel):
    ticker: str
    qty: float
    basis: float
    portfolio_id: str | None = None      # None -> the active account


class Account(BaseModel):
    name: str
    kind: str | None = None


async def _price_rows(rows: list[dict]) -> tuple[list[dict], float, float]:
    if not rows:
        return [], 0.0, 0.0
    q = await yahoo.quotes(sorted({r["ticker"] for r in rows}))
    out, total, cost = [], 0.0, 0.0
    for p in rows:
        r = q.get(p["ticker"]) or {}
        px = r.get("regularMarketPrice")
        if px is None:
            continue
        mv, cb = px * p["qty"], p["basis"] * p["qty"]
        total += mv
        cost += cb
        out.append({**p, "price": px, "market_value": round(mv, 2),
                    "cost_basis_total": round(cb, 2), "pnl": round(mv - cb, 2),
                    "pnl_pct": round((mv / cb - 1) * 100, 2) if cb else None,
                    "day_change_pct": r.get("regularMarketChangePercent")})
    return out, total, cost


def _summary(rows, total, cost, extra=None):
    day = sum(r["market_value"] * (r.get("day_change_pct") or 0) / 100 for r in rows)
    return {"positions": rows, "market_value": round(total, 2),
            "cost_basis": round(cost, 2), "pnl": round(total - cost, 2),
            "pnl_pct": round((total / cost - 1) * 100, 2) if cost else None,
            "day_change": round(day, 2),
            "day_change_pct": round(day / (total - day) * 100, 2) if total - day else None,
            **(extra or {})}


@router.get("/portfolios")
async def portfolios():
    """Every account with its own totals, plus the combined book."""
    d = store.load()
    accs = []
    for a in d["portfolios"]:
        rows = [{**p, "account_id": a["id"], "account": a["name"]} for p in a["positions"]]
        priced, tot, cost = await _price_rows(rows)
        accs.append({"id": a["id"], "name": a["name"], "kind": a.get("kind"),
                     "holdings": len(a["positions"]),
                     **_summary(priced, tot, cost)})
    all_rows, atot, acost = await _price_rows(store.all_positions())
    return clean({"accounts": accs, "active": d.get("active"),
                  "kinds": store.KINDS, "seeded": d.get("seeded", False),
                  "combined": _summary(all_rows, atot, acost,
                                       {"holdings": len(all_rows)})})


@router.post("/portfolios")
async def add_portfolio(a: Account):
    _require_account()
    d = store.load()
    name = a.name.strip()
    if not name:
        raise HTTPException(400, "an account needs a name")
    if any(p["name"].lower() == name.lower() for p in d["portfolios"]):
        raise HTTPException(409, f"you already have an account called {name}")
    pid = store.new_id()
    d["portfolios"].append({"id": pid, "name": name,
                            "kind": (a.kind or "other").strip(), "positions": []})
    d["active"] = pid
    store.save(d)
    return await portfolios()


@router.patch("/portfolios/{pid}")
async def edit_portfolio(pid: str, a: Account):
    _require_account()
    d = store.load()
    acc = store.account(pid, d)
    if not acc:
        raise HTTPException(404, "no such account")
    acc["name"] = a.name.strip() or acc["name"]
    if a.kind:
        acc["kind"] = a.kind.strip()
    store.save(d)
    return await portfolios()


@router.delete("/portfolios/{pid}")
async def del_portfolio(pid: str):
    _require_account()
    d = store.load()
    # an id that is not yours matches nothing, and used to return 200 - a no-op
    # reported as success
    if not store.account(pid, d):
        raise HTTPException(404, "no such account")
    if len(d["portfolios"]) <= 1:
        raise HTTPException(400, "keep at least one account")
    d["portfolios"] = [p for p in d["portfolios"] if p["id"] != pid]
    if d.get("active") == pid:
        d["active"] = d["portfolios"][0]["id"]
    store.save(d)
    return await portfolios()


@router.post("/portfolios/{pid}/activate")
async def activate_portfolio(pid: str):
    _require_account()
    d = store.load()
    if pid != "all" and not store.account(pid, d):
        raise HTTPException(404, "no such account")
    d["active"] = pid
    store.save(d, touched=False)
    return clean({"active": pid})


@router.get("/portfolio")
async def portfolio(portfolio_id: str | None = None):
    """One account, or every account combined when portfolio_id is 'all'."""
    d = store.load()
    pid = portfolio_id if portfolio_id is not None else d.get("active")
    rows, total, cost = await _price_rows(store.all_positions(pid))
    acc = store.account(pid, d)
    return clean(_summary(rows, total, cost, {
        "portfolio_id": pid or "all",
        "portfolio_name": acc["name"] if acc else "All accounts",
        "is_combined": acc is None,
        "seeded": d.get("seeded", False)}))


@router.post("/positions")
async def add_position(p: Position):
    _require_account()
    q = await yahoo.quote(p.ticker)
    if not q or q.get("regularMarketPrice") is None:
        raise HTTPException(404, f"{p.ticker.upper()} did not resolve to a tradable symbol")
    d = store.load()
    pid = p.portfolio_id or d.get("active")
    acc = store.account(pid, d)
    if not acc:
        raise HTTPException(400, "pick an account to add this holding to")
    t = p.ticker.upper().strip()
    existing = next((x for x in acc["positions"] if x["ticker"] == t), None)
    if existing:                       # average into the existing lot
        tq = existing["qty"] + p.qty
        existing["basis"] = round(
            (existing["qty"] * existing["basis"] + p.qty * p.basis) / tq, 4) if tq else p.basis
        existing["qty"] = tq
    else:
        acc["positions"].append({"ticker": t, "qty": p.qty, "basis": p.basis})
    if t not in d["watchlist"]:
        d["watchlist"].append(t)
    store.save(d)
    return await portfolio(pid)


@router.patch("/positions/{ticker}")
async def edit_position(ticker: str, p: Position):
    _require_account()
    d = store.load()
    pid = p.portfolio_id or d.get("active")
    acc = store.account(pid, d)
    row = next((x for x in (acc or {}).get("positions", []) if x["ticker"] == ticker.upper()), None)
    if not row:
        raise HTTPException(404, f"no position in {ticker.upper()} in that account")
    row["qty"], row["basis"] = p.qty, p.basis
    store.save(d)
    return await portfolio(pid)


@router.delete("/positions/{ticker}")
async def del_position(ticker: str, portfolio_id: str | None = None):
    _require_account()
    d = store.load()
    pid = portfolio_id or d.get("active")
    acc = store.account(pid, d)
    if not acc:
        raise HTTPException(404, "no such account")
    acc["positions"] = [x for x in acc["positions"] if x["ticker"] != ticker.upper()]
    store.save(d)
    return await portfolio(pid)


@router.post("/reset")
async def reset(keep_watchlist: bool = False, portfolio_id: str | None = None):
    """Clear demo holdings from one account, or all of them.

    Naming an account means THAT account. It used to clear the watchlist too,
    unconditionally - so a per-account reset destroyed a global list that has
    nothing to do with the account, and an id matching nothing still wiped it.
    """
    _require_account()
    d = store.load()
    whole_book = portfolio_id in (None, "", "all")
    if not whole_book and not store.account(portfolio_id, d):
        raise HTTPException(404, "no such account")
    cleared = []
    for a in d["portfolios"]:
        if whole_book or a["id"] == portfolio_id:
            if a["positions"]:
                cleared.append(a["name"])
            a["positions"] = []
    # the watchlist is not part of any one account, so only a whole-book reset
    # may touch it
    if whole_book and not keep_watchlist:
        d["watchlist"] = []
    store.save(d)
    return clean({"ok": True, "cleared": cleared, "watchlist": d["watchlist"]})


@router.get("/watchlist")
async def get_watchlist():
    return clean({"watchlist": store.load()["watchlist"]})


@router.post("/watchlist")
async def add_watch(w: Watch):
    _require_account()
    s = store.load()
    t = w.ticker.upper().strip()
    q = await yahoo.quote(t)
    if not q or q.get("regularMarketPrice") is None:
        raise HTTPException(404, f"{t} did not resolve to a tradable symbol")
    if t not in s["watchlist"]:
        s["watchlist"].append(t)
        store.save(s)
    return clean({"watchlist": s["watchlist"]})


@router.delete("/watchlist/{ticker}")
async def del_watch(ticker: str):
    _require_account()
    s = store.load()
    s["watchlist"] = [x for x in s["watchlist"] if x != ticker.upper()]
    store.save(s)
    return clean({"watchlist": s["watchlist"]})


@router.get("/logo/{symbol}")
async def logo(symbol: str):
    body, ctype = await logos.fetch(symbol)
    return Response(content=body, media_type=ctype,
                    headers={"Cache-Control": "public, max-age=604800"})


# ════════════════════ daily brief ════════════════════
# Entirely data plane: no LLM. Ranks what actually moved against each ticker's
# own recent volatility, so a 2% day on a quiet name outranks 2% on a jumpy one.

BIG_MOVE_PCT = 5.0          # always flag a day beyond +/- this, whatever the ticker's vol


async def _ticker_signals(sym: str, q: dict, seen_peers: set | None = None) -> list[dict]:
    sig: list[dict] = []
    px = q.get("regularMarketPrice")
    chg = q.get("regularMarketChangePercent")
    if px is None:
        return sig

    bars = await yahoo.bars(sym, period="3mo", interval="1d")
    closes = [b["c"] for b in bars if b.get("c")]
    vols = [b["v"] for b in bars if b.get("v")]

    # 1a. hard threshold: a big move is always worth saying, however jumpy the
    #     ticker normally is. A 1.5-sigma test alone lets a 6% day on a volatile
    #     name slip through, which is exactly the day you want to hear about.
    big_move = chg is not None and abs(chg) >= BIG_MOVE_PCT
    if big_move:
        sig.append({"kind": "threshold",
                    "severity": round(3.0 + min(abs(chg) - BIG_MOVE_PCT, 10) * 0.2, 2),
                    "headline": f"{sym} {'up' if chg > 0 else 'down'} {abs(chg):.2f}%",
                    "detail": f"crossed the \u00b1{BIG_MOVE_PCT:.0f}% threshold",
                    "value": chg})

    # 1b. otherwise, measure the move against this ticker's OWN daily volatility
    if chg is not None and len(closes) > 25:
        rets = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))][-20:]
        mean = sum(rets) / len(rets)
        sd = (sum((r - mean) ** 2 for r in rets) / len(rets)) ** 0.5
        z = abs(chg - mean) / sd if sd else 0
        if big_move:
            if sd:
                sig[-1]["detail"] += f" \u00b7 {z:.1f}x its normal daily move (20-day sd {sd:.2f}%)"
        elif z >= 1.5:
            sig.append({"kind": "move", "severity": round(z, 1),
                        "headline": f"{sym} {'up' if chg > 0 else 'down'} {abs(chg):.2f}%",
                        "detail": f"{z:.1f}x its normal daily move (20-day sd {sd:.2f}%)",
                        "value": chg})

    # 2. unusual participation
    if len(vols) > 21 and vols[-1]:
        avg = sum(vols[-21:-1]) / 20
        ratio = vols[-1] / avg if avg else 0
        if ratio >= 1.5:
            sig.append({"kind": "volume", "severity": round(min(ratio, 5), 1),
                        "headline": f"{sym} volume {ratio:.1f}x average",
                        "detail": f"{vols[-1]:,} vs {int(avg):,} 20-day average",
                        "value": ratio})

    # 3. at the edge of the 52-week range
    hi, lo = q.get("fiftyTwoWeekHigh"), q.get("fiftyTwoWeekLow")
    if hi and px >= hi * 0.98:
        sig.append({"kind": "high", "severity": 2.0,
                    "headline": f"{sym} near its 52-week high",
                    "detail": f"${px:,.2f} vs ${hi:,.2f} high", "value": px})
    elif lo and px <= lo * 1.02:
        sig.append({"kind": "low", "severity": 2.0,
                    "headline": f"{sym} near its 52-week low",
                    "detail": f"${px:,.2f} vs ${lo:,.2f} low", "value": px})

    # 4. the adjacent cohort - a peer moving hard is news for this ticker too
    try:
        from ..tools import TOOLS
        pm = await TOOLS["peer_moves"].fn(sym)
        d = getattr(pm, "data", None)
        if d and d.get("peers") and seen_peers is not None:
            seen_peers.update(p["ticker"] for p in d["peers"])
        if d and d.get("peers"):
            gap = d.get("gap_vs_peers_pct")
            biggest = d["biggest_mover"]
            if gap is not None and abs(gap) >= 3:
                sig.append({"kind": "peer_gap", "severity": round(min(abs(gap) / 2, 4), 1),
                            "headline": f"{sym} {'outrunning' if gap > 0 else 'lagging'} its peer group",
                            "detail": f"{sym} {chg:+.2f}% vs peer average "
                                      f"{d['peer_average_pct']:+.2f}% ({len(d['peers'])} peers)",
                            "value": gap})
            elif abs(biggest["change_pct"]) >= 5:
                sig.append({"kind": "peer_move",
                            "severity": round(min(abs(biggest["change_pct"]) / 3, 3), 1),
                            "headline": f"{biggest['ticker']} moved {biggest['change_pct']:+.2f}% "
                                        f"\u2014 adjacent to {sym}",
                            "detail": f"peer group average {d['peer_average_pct']:+.2f}%; "
                                      f"{sym} {chg:+.2f}%",
                            "value": biggest["change_pct"]})
    except Exception:
        pass

    # 5. earnings inside a week
    cal = await yahoo.attr(sym, "calendar", 21600) or {}
    d2 = cal.get("Earnings Date")
    if isinstance(d2, list) and d2:
        d2 = d2[0]
    if d2:
        try:
            days = (datetime.fromisoformat(str(d2)[:10]).date()
                    - datetime.now(timezone.utc).date()).days
            if 0 <= days <= 7:
                sig.append({"kind": "earnings", "severity": 3.0 - days * 0.15,
                            "headline": f"{sym} reports in {days} day{'s' if days != 1 else ''}",
                            "detail": f"{str(d2)[:10]}"
                                      + (f" \u00b7 EPS est {cal['Earnings Average']:.2f}"
                                         if cal.get("Earnings Average") else ""),
                            "value": days})
        except Exception:
            pass

    # A big move with no explanation is just an alarm. Attach what the data can
    # actually say: did the whole cohort move too, did it just report, did volume
    # confirm, and which headlines name the issuer.
    big = next((x for x in sig if x["kind"] == "threshold"), None)
    if big is not None:
        big["why"] = await _explain_move(sym, chg, sig, q)
    return sig


async def _explain_move(sym: str, chg: float, sig: list[dict], q: dict) -> dict:
    """Evidence for a threshold move. Data plane only - no model."""
    from ..tools import TOOLS
    why: dict = {"ticker_move_pct": round(chg, 2)}

    # 1. company-specific or sector-wide?
    try:
        pm = await TOOLS["peer_moves"].fn(sym)
        d = getattr(pm, "data", None)
        if d and d.get("peer_average_pct") is not None:
            avg = d["peer_average_pct"]
            why["peer_average_pct"] = avg
            why["peers"] = [{"ticker": p["ticker"], "change_pct": p["change_pct"]}
                            for p in d["peers"][:4]]
            same_way = (chg < 0) == (avg < 0)
            if same_way and abs(avg) >= abs(chg) * 0.5:
                why["read"] = "sector-wide — its peer group moved the same way"
            elif same_way:
                why["read"] = "moved further than its peer group, which leaned the same way"
            else:
                why["read"] = "company-specific — the peer group did not follow"
    except Exception:
        pass

    # 2. did it just report?
    try:
        ed = await yahoo.attr(sym, "earnings_dates", 21600) or {}
        today = datetime.now(timezone.utc).date()
        for k, v in ed.items():
            try:
                dt = datetime.fromisoformat(str(k)[:10]).date()
            except Exception:
                continue
            if 0 <= (today - dt).days <= 3 and v.get("Reported EPS") is not None:
                est, act = v.get("EPS Estimate"), v["Reported EPS"]
                why["earnings"] = {
                    "date": str(dt), "eps_actual": act, "eps_estimate": est,
                    "result": "beat" if est is not None and act > est
                              else "miss" if est is not None and act < est else "reported"}
                break
    except Exception:
        pass

    # 3. did volume confirm it?
    vol = next((x for x in sig if x["kind"] == "volume"), None)
    if vol:
        why["volume"] = vol["detail"]

    # 4. headlines that actually name the issuer
    try:
        items = await yahoo.news_for(sym, 10)
        name = (q.get("shortName") or "").lower().replace(",", "").split()
        key = [w for w in name[:2] if len(w) > 3 and w not in ("inc", "corp", "the")]
        on_topic = [h for h in items
                    if sym.lower() in h["title"].lower()
                    or any(w in h["title"].lower() for w in key)]
        if on_topic:
            why["headlines"] = [{"title": h["title"], "publisher": h.get("publisher")}
                                for h in on_topic[:3]]
    except Exception:
        pass

    if "read" not in why and "earnings" not in why and "headlines" not in why:
        why["read"] = "no company news, earnings or peer move explains this yet"
    return why

    bars = await yahoo.bars(sym, period="3mo", interval="1d")
    closes = [b["c"] for b in bars if b.get("c")]
    vols = [b["v"] for b in bars if b.get("v")]

    # 1a. hard threshold: a big move is always worth saying, however jumpy the
    #     ticker normally is. A 1.5-sigma test alone lets a 6% day on a volatile
    #     name slip through, which is exactly the day you want to hear about.
    big_move = chg is not None and abs(chg) >= BIG_MOVE_PCT
    if big_move:
        sig.append({"kind": "threshold",
                    "severity": round(3.0 + min(abs(chg) - BIG_MOVE_PCT, 10) * 0.2, 2),
                    "headline": f"{sym} {'up' if chg>0 else 'down'} {abs(chg):.2f}%",
                    "detail": f"crossed the ±{BIG_MOVE_PCT:.0f}% threshold",
                    "value": chg})

    # 1b. move measured against this ticker's OWN daily volatility, for the
    #     smaller moves that are still unusual for that name
    if chg is not None and len(closes) > 25:
        rets = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))][-20:]
        mean = sum(rets) / len(rets)
        sd = (sum((r - mean) ** 2 for r in rets) / len(rets)) ** 0.5
        z = abs(chg - mean) / sd if sd else 0
        if big_move:
            # fold the context into the threshold signal rather than firing twice
            if sd:
                sig[-1]["detail"] += f" · {z:.1f}x its normal daily move (20-day sd {sd:.2f}%)"
        elif z >= 1.5:
            sig.append({"kind": "move", "severity": round(z, 1),
                        "headline": f"{sym} {'up' if chg>0 else 'down'} {abs(chg):.2f}%",
                        "detail": f"{z:.1f}x its normal daily move (20-day sd {sd:.2f}%)",
                        "value": chg})

    # 2. unusual participation
    if len(vols) > 21 and vols[-1]:
        avg = sum(vols[-21:-1]) / 20
        ratio = vols[-1] / avg if avg else 0
        if ratio >= 1.5:
            sig.append({"kind": "volume", "severity": round(min(ratio, 5), 1),
                        "headline": f"{sym} volume {ratio:.1f}x average",
                        "detail": f"{vols[-1]:,} vs {int(avg):,} 20-day average",
                        "value": ratio})

    # 3. at the edge of the 52-week range
    hi, lo = q.get("fiftyTwoWeekHigh"), q.get("fiftyTwoWeekLow")
    if hi and px >= hi * 0.98:
        sig.append({"kind": "high", "severity": 2.0,
                    "headline": f"{sym} near its 52-week high",
                    "detail": f"${px:,.2f} vs ${hi:,.2f} high", "value": px})
    elif lo and px <= lo * 1.02:
        sig.append({"kind": "low", "severity": 2.0,
                    "headline": f"{sym} near its 52-week low",
                    "detail": f"${px:,.2f} vs ${lo:,.2f} low", "value": px})

    # 4. the adjacent cohort - a peer moving hard is news for this ticker too
    try:
        from ..tools import TOOLS
        pm = await TOOLS["peer_moves"].fn(sym)
        d = getattr(pm, "data", None)
        if d and d.get("peers") and seen_peers is not None:
            seen_peers.update(p["ticker"] for p in d["peers"])
        if d and d.get("peers"):
            gap = d.get("gap_vs_peers_pct")
            big = d["biggest_mover"]
            # (a) the ticker is breaking away from its own group
            if gap is not None and abs(gap) >= 3:
                sig.append({"kind": "peer_gap", "severity": round(min(abs(gap) / 2, 4), 1),
                            "headline": f"{sym} {'outrunning' if gap > 0 else 'lagging'} its peer group",
                            "detail": f"{sym} {chg:+.2f}% vs peer average "
                                      f"{d['peer_average_pct']:+.2f}% ({len(d['peers'])} peers)",
                            "value": gap})
            # (b) an adjacent name moved hard even if this one did not
            elif abs(big["change_pct"]) >= 5:
                sig.append({"kind": "peer_move", "severity": round(min(abs(big["change_pct"]) / 3, 3), 1),
                            "headline": f"{big['ticker']} moved {big['change_pct']:+.2f}% — adjacent to {sym}",
                            "detail": f"peer group average {d['peer_average_pct']:+.2f}%; "
                                      f"{sym} {chg:+.2f}%",
                            "value": big["change_pct"]})
    except Exception:
        pass

    # 5. earnings inside a week
    cal = await yahoo.attr(sym, "calendar", 21600) or {}
    d = cal.get("Earnings Date")
    if isinstance(d, list) and d:
        d = d[0]
    if d:
        try:
            days = (datetime.fromisoformat(str(d)[:10]).date()
                    - datetime.now(timezone.utc).date()).days
            if 0 <= days <= 7:
                sig.append({"kind": "earnings", "severity": 3.0 - days * 0.15,
                            "headline": f"{sym} reports in {days} day{'s' if days != 1 else ''}",
                            "detail": f"{str(d)[:10]}"
                                      + (f" · EPS est {cal['Earnings Average']:.2f}"
                                         if cal.get("Earnings Average") else ""),
                            "value": days})
        except Exception:
            pass
    # A big move with no explanation is just an alarm. Attach what the data can
    # actually say: did the whole cohort move too (sector, not company), did it
    # just report, did volume confirm, and which headlines name the issuer.
    big = next((x for x in sig if x["kind"] == "threshold"), None)
    if big is not None:
        big["why"] = await _explain_move(sym, chg, sig, q)
    return sig


async def _market_only_brief(reason: str) -> dict:
    """The brief with nothing personal in it: what moved the whole market."""
    from ..tools import TOOLS
    mn, lv = await asyncio.gather(TOOLS["market_news"].fn(""),
                                  TOOLS["index_levels"].fn(""),
                                  return_exceptions=True)
    return clean({
        "date": str(date.today()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_only": True, "reason": reason,
        "portfolio": None, "signals": [], "checked": [], "quiet": [],
        "adjacent_checked": [], "since_last": [],
        "market_headlines": (getattr(mn, "data", None) or {}).get("headlines", [])[:10],
        "index_levels": getattr(lv, "data", None) or {},
        "note": "market-wide only - sign in to track your own tickers",
    })


@router.get("/brief")
async def brief():
    st = store.load()
    if st.get("guest"):
        return await _market_only_brief("not signed in")
    syms = sorted(set(st["watchlist"]) | {p["ticker"] for p in store.all_positions("all")})
    if not syms:
        return await _market_only_brief("no tickers tracked yet")

    q = await yahoo.quotes(syms)
    seen_peers: set[str] = set()
    sig_lists = await asyncio.gather(
        *(_ticker_signals(s, q.get(s) or {}, seen_peers) for s in syms),
        return_exceptions=True)

    held_syms = {p["ticker"] for p in store.all_positions("all")}
    signals, quiet = [], []
    for s, res in zip(syms, sig_lists):
        found = [] if isinstance(res, Exception) else res
        held = s in held_syms
        for f in found:
            f["ticker"] = s
            f["held"] = held
            f["severity"] = round(f["severity"] * (1.35 if held else 1.0), 2)
        if found:
            signals.extend(found)
        else:
            quiet.append(s)
    # one peer moving hard is ONE story, even if it neighbours several holdings
    merged: dict[str, dict] = {}
    out: list[dict] = []
    for f in signals:
        if f["kind"] != "peer_move":
            out.append(f)
            continue
        mover = f["headline"].split()[0]
        prev = merged.get(mover)
        if prev is None:
            f["affects"] = [f["ticker"]]
            merged[mover] = f
            out.append(f)
        else:
            prev["affects"].append(f["ticker"])
            prev["held"] = prev["held"] or f["held"]
            prev["severity"] = max(prev["severity"], f["severity"])
    for f in merged.values():
        aff = f.get("affects") or []
        if len(aff) > 1:
            f["headline"] = f["headline"].split(" — ")[0] + f" — adjacent to {', '.join(aff)}"
            f["detail"] = f"moves alongside {len(aff)} of your tickers: {', '.join(aff)}"
    signals = out
    signals.sort(key=lambda f: -f["severity"])

    # what changed since the brief was last generated
    snaps = store.snapshots()
    last = (snaps.get("last") or {})
    since = []
    if last.get("prices"):
        for s in syms:
            old = last["prices"].get(s)
            new = (q.get(s) or {}).get("regularMarketPrice")
            if old and new:
                d = (new / old - 1) * 100
                if abs(d) >= 1:
                    since.append({"ticker": s, "from": old, "to": new, "pct": round(d, 2)})
        since.sort(key=lambda r: -abs(r["pct"]))

    # market-wide news: rates, jobs, policy, conflict - the things that move
    # everything at once, which per-ticker feeds never surface
    from ..tools import TOOLS
    macro_items, levels = [], {}
    try:
        mn, lv = await asyncio.gather(TOOLS["market_news"].fn(""),
                                      TOOLS["index_levels"].fn(""),
                                      return_exceptions=True)
        macro_items = (getattr(mn, "data", None) or {}).get("headlines", [])
        levels = getattr(lv, "data", None) or {}
    except Exception:
        pass

    pf = await portfolio("all")
    today = str(date.today())
    store.write_snapshot({s: (q.get(s) or {}).get("regularMarketPrice")
                          for s in syms if (q.get(s) or {}).get("regularMarketPrice")}, today)

    return clean({
        "date": today,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "portfolio": {"market_value": pf["market_value"], "day_change": pf["day_change"],
                      "day_change_pct": pf["day_change_pct"], "pnl": pf["pnl"],
                      "pnl_pct": pf["pnl_pct"], "seeded": pf["seeded"]},
        "signals": signals[:12],
        "since_last": since[:6],
        "since_last_day": last.get("day"),
        "checked": syms, "quiet": quiet,
        "adjacent_checked": sorted(seen_peers - set(syms)),
        "market_headlines": macro_items[:8],
        "index_levels": levels,
        "note": f"computed from price, volume and calendar data - no model involved; "
                f"any move beyond \u00b1{BIG_MOVE_PCT:.0f}% is always flagged",
    })


@router.get("/related/{symbol}")
async def related(symbol: str):
    """Adjacent-stock view: who the peers are, how they traded today, and how
    much of a peer's move this ticker has historically followed."""
    from ..tools import TOOLS
    moves, across = await asyncio.gather(
        TOOLS["peer_moves"].fn(symbol), TOOLS["read_across"].fn(symbol),
        return_exceptions=True)
    d = lambda r: getattr(r, "data", None) if not isinstance(r, Exception) else None
    reason = None
    if d(moves) is None:
        reason = getattr(moves, "reason", None) if not isinstance(moves, Exception) else str(moves)
    return clean({"symbol": symbol.upper(), "moves": d(moves), "read_across": d(across),
                  "unavailable": reason})


@router.get("/related/{symbol}/event-study/{peer}")
async def related_event_study(symbol: str, peer: str):
    """Does that peer's EARNINGS actually move this ticker? Separate question
    from ordinary co-movement - and usually a different answer."""
    from ..tools import TOOLS
    r = await TOOLS["event_study"].fn(peer, other=symbol)
    return clean({"source": peer.upper(), "target": symbol.upper(),
                  "result": getattr(r, "data", None),
                  "unavailable": getattr(r, "reason", None)})


@router.get("/portfolio/analytics")
async def portfolio_analytics(portfolio_id: str | None = None):
    """Concentration, beta and correlation for the book.

    These are the portfolio domain's DERIVED tools called directly - they are
    pure computation over cached data, so they belong on the data plane. No LLM.
    """
    from ..tools import TOOLS
    acct = portfolio_id or store.load().get("active") or "all"
    conc, beta, corr = await asyncio.gather(
        TOOLS["concentration"].fn("", account=acct),
        TOOLS["portfolio_beta"].fn("", account=acct),
        TOOLS["correlation_matrix"].fn("", account=acct), return_exceptions=True)
    d = lambda r: getattr(r, "data", None) if not isinstance(r, Exception) else None
    return clean({"concentration": d(conc), "beta": d(beta), "correlation": d(corr),
                  "note": "derived from cached prices - no model involved"})


@router.get("/search")
async def search(q: str = Query(..., min_length=1)):
    return clean({"query": q, "results": await yahoo.search(q)})


@router.get("/indices")
async def indices():
    """The broad market for the dashboard: the big three, the two risk gauges,
    and CNN's Fear & Greed - each with a month of history for its sparkline."""
    label = {"^GSPC": "S&P 500", "^DJI": "Dow Jones", "^IXIC": "Nasdaq",
             "^VIX": "Volatility", "^TNX": "US 10-year"}
    q, fng, *bar_lists = await asyncio.gather(
        yahoo.quotes(yahoo.INDEXES), sentiment.fear_greed(),
        *(yahoo.bars(s, "1mo", "1d") for s in yahoo.INDEXES),
        return_exceptions=True)
    q = q if isinstance(q, dict) else {}
    spark = {}
    for s_, bl in zip(yahoo.INDEXES, bar_lists):
        if isinstance(bl, list):
            spark[s_] = [b["c"] for b in bl if b.get("c") is not None]

    out = []
    for s_ in yahoo.INDEXES:
        r = q.get(s_) or {}
        if r.get("regularMarketPrice") is None:
            continue
        out.append({"symbol": s_, "label": label.get(s_, s_),
                    "level": r["regularMarketPrice"],
                    "change": r.get("regularMarketChange"),
                    "change_pct": r.get("regularMarketChangePercent"),
                    "history": spark.get(s_, []),
                    "kind": "rate" if s_ == "^TNX" else "vol" if s_ == "^VIX" else "index"})

    f = fng if isinstance(fng, dict) else None
    if f and f.get("score") is not None:
        prev = f.get("previous_close")
        out.insert(3, {                       # sits right after the big three
            "symbol": "FNG", "label": "Fear & Greed", "kind": "sentiment",
            "level": f["score"], "rating": f.get("rating"),
            "change": round(f["score"] - prev, 1) if prev else None,
            "change_pct": None,
            "week_ago": f.get("week_ago"), "month_ago": f.get("month_ago"),
            "history": f.get("history", []), "source": "CNN"})
    return clean({"indices": out})


# ════════════════════ multi-ticker comparison ════════════════════

@router.get("/compare")
async def compare(symbols: str = Query(..., min_length=1), period: str = "6mo"):
    """Any basket of tickers, side by side: normalised price paths, the
    fundamentals that are comparable across names, and how they move together."""
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:8]
    # echoed back into the page; a "symbol" with markup in it is not one
    syms = [x for x in syms if re.match(r"^[A-Z0-9][A-Z0-9.^=-]{0,11}$", x)]
    if not syms:
        raise HTTPException(400, "give at least one valid symbol")

    quotes, *series = await asyncio.gather(
        yahoo.quotes(syms),
        *(yahoo.bars(s, period, "1d") for s in syms),
        return_exceptions=True)
    quotes = quotes if isinstance(quotes, dict) else {}
    bars = {s: (b if isinstance(b, list) else []) for s, b in zip(syms, series)}

    infos = await asyncio.gather(*(yahoo.info(s) for s in syms), return_exceptions=True)
    infos = {s: (i if isinstance(i, dict) else {}) for s, i in zip(syms, infos)}

    # normalise every path to 100 at the first shared date, so a $40 stock and a
    # $900 stock are actually comparable
    dates = [set(b["t"] for b in bars[s]) for s in syms if bars[s]]
    common = sorted(set.intersection(*dates)) if dates else []
    paths, perf = [], {}
    if common:
        base = {}
        for s in syms:
            by = {b["t"]: b["c"] for b in bars[s]}
            first = by.get(common[0])
            if first:
                base[s] = first
        for t in common:
            row = {"t": t}
            for s in syms:
                by = {b["t"]: b["c"] for b in bars[s]}
                if s in base and t in by:
                    row[s] = round(by[t] / base[s] * 100, 2)
            paths.append(row)
        for s in base:
            last = paths[-1].get(s)
            if last:
                perf[s] = round(last - 100, 2)

    rows = []
    for s in syms:
        q, i = quotes.get(s) or {}, infos.get(s) or {}
        rows.append({
            "symbol": s, "name": q.get("shortName") or i.get("shortName"),
            "price": q.get("regularMarketPrice"),
            "change_pct": q.get("regularMarketChangePercent"),
            "period_pct": perf.get(s),
            # the v7 quote carries these; its chart fallback does not, so use info's
            "market_cap": q.get("marketCap") or i.get("marketCap"),
            "pe": q.get("trailingPE") or i.get("trailingPE"),
            "forward_pe": q.get("forwardPE") or i.get("forwardPE"),
            "price_to_book": q.get("priceToBook") or i.get("priceToBook"),
            "net_margin": i.get("profitMargins"), "operating_margin": i.get("operatingMargins"),
            "gross_margin": i.get("grossMargins"), "roe": i.get("returnOnEquity"),
            "revenue_growth": i.get("revenueGrowth"), "earnings_growth": i.get("earningsGrowth"),
            "debt_to_equity": i.get("debtToEquity"), "dividend_yield": i.get("dividendYield"),
            "beta": i.get("beta"), "sector": i.get("sector"), "industry": i.get("industry"),
            "high_52w": q.get("fiftyTwoWeekHigh"), "low_52w": q.get("fiftyTwoWeekLow"),
        })

    # how much of a basket this really is - correlation across the set
    corr = []
    if len(syms) > 1:
        import numpy as np
        rets = {}
        for s in syms:
            cl = [b["c"] for b in bars[s]]
            if len(cl) > 30:
                rets[s] = np.array([cl[i] / cl[i-1] - 1 for i in range(1, len(cl))])
        names = list(rets)
        n = min((len(v) for v in rets.values()), default=0)
        for a_i, a in enumerate(names):
            for b in names[a_i+1:]:
                x, y = rets[a][-n:], rets[b][-n:]
                if n > 30:
                    corr.append({"pair": f"{a}/{b}",
                                 "corr": round(float(np.corrcoef(x, y)[0, 1]), 2)})
        corr.sort(key=lambda d: -d["corr"])

    return clean({"symbols": syms, "period": period, "rows": rows,
                  "paths": paths, "correlations": corr,
                  "note": "paths indexed to 100 at the first shared session"})


# ════════════════════ earnings this week ════════════════════

@router.get("/calendar/earnings")
async def earnings_week(days: int = Query(7, ge=1, le=14), limit: int = Query(10, ge=1, le=30)):
    """Who reports in the next `days`, biggest companies first.

    The calendar lists every filer - most weeks that is hundreds of micro caps.
    Revenue estimate is a free size proxy to cut it to 80 candidates, then one
    batched quote call supplies names and market caps to rank the rest."""
    from datetime import timedelta
    from ..providers import finnhub
    if not finnhub.enabled():
        return {"items": [], "unavailable": "earnings calendar needs FINNHUB_API_KEY"}
    today = date.today()
    rows = await finnhub.earnings_calendar(today.isoformat(),
                                           (today + timedelta(days=days)).isoformat())
    rows = [r for r in rows if r.get("symbol") and "." not in r["symbol"]]
    rows.sort(key=lambda r: r.get("revenueEstimate") or 0, reverse=True)
    cand = rows[:80]
    q = await yahoo.quotes([r["symbol"] for r in cand]) if cand else {}
    items = []
    for r in cand:
        qq = q.get(r["symbol"]) or {}
        cap = qq.get("marketCap")
        if not cap:
            continue
        items.append({"symbol": r["symbol"], "name": qq.get("shortName") or qq.get("longName"),
                      "date": r.get("date"), "hour": r.get("hour") or "",
                      "eps_estimate": r.get("epsEstimate"),
                      "revenue_estimate": r.get("revenueEstimate"), "market_cap": cap})
    items.sort(key=lambda x: x["market_cap"], reverse=True)
    return clean({"items": items[:limit], "window_days": days,
                  "total_reporting": len(rows), "source": "finnhub calendar"})
