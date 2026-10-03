from __future__ import annotations
from ..providers import yahoo
from ._util import empty, fail, ok
from .registry import tool


@tool("street", "recent news headlines about the company")
async def news(ticker: str, limit: int = 8, **_):
    items = await yahoo.news_for(ticker, limit)
    q = await yahoo.quote(ticker) or {}
    nm = (q.get("shortName") or "").lower().replace(",", "").split()
    key = [w for w in nm[:2] if len(w) > 3 and w not in ("inc", "corp", "the", "company")]
    def rel(t: str) -> bool:
        tl = t.lower()
        return ticker.lower() in tl or any(w in tl for w in key)
    on_topic = [i for i in items if rel(i["title"])]
    if not items:
        return empty("news", ticker, "no recent headlines")
    if not on_topic:
        return empty("news", ticker,
                     f"{len(items)} headlines returned but none name {ticker} "
                     "(Yahoo's feed is padded with syndicated filler)")
    return ok("news", ticker, {"headlines": on_topic, "count": len(on_topic),
                               "filtered_out": len(items) - len(on_topic),
                               "note": "sentiment is NOT provided by the feed; "
                                       "headlines not naming the issuer were dropped"})


@tool("street", "analyst consensus recommendation and how many analysts cover it")
async def analyst_ratings(ticker: str, **_):
    i = await yahoo.info(ticker)
    d = {k: i[k] for k in ("recommendationKey", "recommendationMean", "numberOfAnalystOpinions") if i.get(k) is not None}
    if d:   # different panels give different means - the agent should cite which
        d["panel"] = "Finnhub" if i.get("_source") == "finnhub" else "Yahoo"
    if not d:
        return fail("analyst_ratings", ticker, "no coverage data")
    return ok("analyst_ratings", ticker, d, source=d["panel"].lower())


@tool("street", "analyst price targets: low / mean / high vs current price")
async def price_targets(ticker: str, **_):
    i = await yahoo.info(ticker)
    d = {k: i[k] for k in ("targetLowPrice", "targetMeanPrice", "targetHighPrice", "currentPrice") if i.get(k) is not None}
    if not d:
        return fail("price_targets", ticker, "no targets")
    if d.get("targetMeanPrice") and d.get("currentPrice"):
        d["upside_to_mean_pct"] = round((d["targetMeanPrice"] / d["currentPrice"] - 1) * 100, 1)
    return ok("price_targets", ticker, d)


@tool("street", "recent upgrades and downgrades by firm, with dates")
async def rating_changes(ticker: str, limit: int = 8, **_):
    raw = await yahoo.attr(ticker, "upgrades_downgrades", ttl=43200) or {}
    rows = sorted(raw.items(), key=lambda kv: str(kv[0]), reverse=True)[:limit]
    out = [{"date": str(k)[:10], "firm": v.get("Firm"), "to": v.get("ToGrade"),
            "from": v.get("FromGrade"), "action": v.get("Action")} for k, v in rows]
    if not out:
        return empty("rating_changes", ticker, "no rating changes on record")
    return ok("rating_changes", ticker, {"changes": out})


@tool("street", "largest institutional holders and the % of shares they hold")
async def institutional_holders(ticker: str, limit: int = 5, **_):
    raw = await yahoo.attr(ticker, "institutional_holders") or {}
    rows = [v for _, v in sorted(raw.items())][:limit]
    out = [{"holder": r.get("Holder"), "pct_held": round(r["pctHeld"] * 100, 2) if r.get("pctHeld") else None,
            "shares": r.get("Shares")} for r in rows if r.get("Holder")]
    if not out:
        return empty("institutional_holders", ticker, "no institutional holder data")
    return ok("institutional_holders", ticker, {"top_holders": out})


@tool("street", "recent insider buying and selling")
async def insider_transactions(ticker: str, limit: int = 6, **_):
    raw = await yahoo.attr(ticker, "insider_transactions") or {}
    rows = [v for _, v in sorted(raw.items())][:limit]
    out = [{"insider": r.get("Insider"), "text": r.get("Text"), "shares": r.get("Shares"),
            "value": r.get("Value"), "date": str(r.get("Start Date"))[:10]} for r in rows if r.get("Insider")]
    if not out:
        return empty("insider_transactions", ticker, "no insider transactions on record")
    return ok("insider_transactions", ticker, {"transactions": out})


@tool("street", "short interest: % of float short and days to cover")
async def short_interest(ticker: str, **_):
    i = await yahoo.info(ticker)
    d = {}
    if isinstance(i.get("shortPercentOfFloat"), (int, float)):
        d["short_pct_of_float"] = round(i["shortPercentOfFloat"] * 100, 2)
    for k, v in (("shortRatio", "days_to_cover"), ("sharesShort", "shares_short")):
        if i.get(k) is not None:
            d[v] = i[k]
    if not d:
        return empty("short_interest", ticker, "no short interest reported")
    d["elevated"] = bool(d.get("short_pct_of_float", 0) > 10)
    return ok("short_interest", ticker, d)
