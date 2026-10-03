"""Finnhub provider - the fallback for Yahoo's crumb-gated data.

From Render, Yahoo refuses the crumb (429 on the very first getcrumb call), so
.info and .recommendations come back empty there. Finnhub's free tier covers
most of the same ground over a plain API key. Everything here returns data in
YAHOO'S shape and units, so callers of yahoo.info() never know the difference:

  Finnhub sends margins / ROE / growth / payout as percent -> Yahoo fractions
  Finnhub sends market cap and shares in millions          -> Yahoo absolute
  Finnhub debt/equity is a ratio                           -> Yahoo percent
  dividend yield stays percent (yfinance 1.x reports it as percent too)

Not on the free tier: price targets, forward P/E, short interest. Those stay
empty rather than being estimated.

Off unless FINNHUB_API_KEY is set. Free tier: 60 calls/min. A new ticker costs
3 calls in all (profile2, metric, recommendation - the last shared by info()
and recommendations()), then nothing until the cache expires.
"""
from __future__ import annotations
import asyncio, logging, os

import httpx

from ..cache import cached

log = logging.getLogger("provider.finnhub")
BASE = "https://finnhub.io/api/v1"


def enabled() -> bool:
    return bool(os.environ.get("FINNHUB_API_KEY", "").strip())


async def _get(c: httpx.AsyncClient, path: str, **params) -> dict | list:
    r = await c.get(f"{BASE}{path}", params=params,
                    headers={"X-Finnhub-Token": os.environ["FINNHUB_API_KEY"].strip()})
    r.raise_for_status()
    return r.json()


def _pct(v):          # percent -> fraction
    return v / 100 if isinstance(v, (int, float)) else None


def _mul(v, k):
    return v * k if isinstance(v, (int, float)) else None


def _consensus(rec: dict) -> dict:
    """Yahoo's 1 (strong buy) .. 5 (strong sell) mean, from Finnhub's counts."""
    w = (("strongBuy", 1), ("buy", 2), ("hold", 3), ("sell", 4), ("strongSell", 5))
    n = sum(int(rec.get(k) or 0) for k, _ in w)
    if not n:
        return {}
    mean = round(sum(int(rec.get(k) or 0) * s for k, s in w) / n, 2)
    key = ("strong_buy" if mean < 1.5 else "buy" if mean < 2.5 else "hold" if mean < 3.5
           else "underperform" if mean < 4.5 else "sell")
    return {"recommendationMean": mean, "recommendationKey": key,
            "numberOfAnalystOpinions": n}


async def _rec_rows(symbol: str) -> list:
    """/stock/recommendation, fetched once and shared: info() needs it for the
    consensus mean and recommendations() for the breakdown chart."""
    async def load():
        async with httpx.AsyncClient(timeout=15) as c:
            return await _get(c, "/stock/recommendation", symbol=symbol)
    val, _ = await cached(("finnhub", "rec_rows", symbol), 43200, load)
    return val or []


async def _load_info(symbol: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        prof, met, rec = await asyncio.gather(
            _get(c, "/stock/profile2", symbol=symbol),
            _get(c, "/stock/metric", symbol=symbol, metric="all"),
            _rec_rows(symbol),
            return_exceptions=True)
    for name, v in (("profile2", prof), ("metric", met), ("recommendation", rec)):
        if isinstance(v, Exception):
            log.warning("finnhub %s %s failed: %s", name, symbol, v)
    prof = prof if isinstance(prof, dict) else {}
    m = (met if isinstance(met, dict) else {}).get("metric") or {}
    rec = rec[0] if isinstance(rec, list) and rec else {}

    out = {
        "shortName": prof.get("name"), "longName": prof.get("name"),
        "industry": prof.get("finnhubIndustry"), "website": prof.get("weburl"),
        "currency": prof.get("currency"),
        "marketCap": _mul(prof.get("marketCapitalization") or m.get("marketCapitalization"), 1e6),
        "sharesOutstanding": _mul(prof.get("shareOutstanding"), 1e6),
        "trailingPE": m.get("peTTM") or m.get("peBasicExclExtraTTM"),
        "priceToBook": m.get("pbQuarterly") or m.get("pbAnnual"),
        "profitMargins": _pct(m.get("netProfitMarginTTM")),
        "operatingMargins": _pct(m.get("operatingMarginTTM")),
        "grossMargins": _pct(m.get("grossMarginTTM")),
        "returnOnEquity": _pct(m.get("roeTTM")),
        "returnOnAssets": _pct(m.get("roaTTM")),
        "revenueGrowth": _pct(m.get("revenueGrowthQuarterlyYoy") or m.get("revenueGrowthTTMYoy")),
        "earningsGrowth": _pct(m.get("epsGrowthQuarterlyYoy") or m.get("epsGrowthTTMYoy")),
        "debtToEquity": _mul(m.get("totalDebt/totalEquityQuarterly")
                             or m.get("totalDebt/totalEquityAnnual"), 100),
        "currentRatio": m.get("currentRatioQuarterly") or m.get("currentRatioAnnual"),
        "quickRatio": m.get("quickRatioQuarterly") or m.get("quickRatioAnnual"),
        "dividendYield": m.get("dividendYieldIndicatedAnnual") or m.get("currentDividendYieldTTM"),
        "payoutRatio": _pct(m.get("payoutRatioTTM") or m.get("payoutRatioAnnual")),
        "beta": m.get("beta"),
        "fiftyTwoWeekHigh": m.get("52WeekHigh"), "fiftyTwoWeekLow": m.get("52WeekLow"),
        **_consensus(rec),
    }
    out = {k: v for k, v in out.items() if v is not None}
    if out:
        out["_source"] = "finnhub"
    return out


async def info(symbol: str) -> dict:
    """Yahoo-shaped .info subset. {} when disabled or Finnhub has nothing."""
    if not enabled():
        return {}
    val, _ = await cached(("finnhub", "info", symbol.upper()), 86400,
                          lambda: _load_info(symbol.upper()))
    return val or {}


async def company_news(symbol: str, frm: str, to: str) -> list[dict]:
    """Dated headlines. Each call returns at most ~250 items, NEWEST first, and the
    free tier keeps about a year - so ask for narrow windows (a day or two), not
    a whole period. Past news does not change, so cache it for a week."""
    if not enabled():
        return []
    async def load():
        async with httpx.AsyncClient(timeout=15) as c:
            return await _get(c, "/company-news", symbol=symbol, **{"from": frm, "to": to})
    val, _ = await cached(("finnhub", "news", symbol.upper(), frm, to), 7 * 86400, load)
    return val if isinstance(val, list) else []


async def _load_recs(symbol: str) -> dict:
    rows = await _rec_rows(symbol)
    # Yahoo's .recommendations: one row per month back, "0m" = current
    return {str(i): {"period": f"-{i}m" if i else "0m",
                     **{k: r.get(k) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}}
            for i, r in enumerate(rows or [])}


async def recommendations(symbol: str) -> dict:
    if not enabled():
        return {}
    try:
        val, _ = await cached(("finnhub", "recs", symbol.upper()), 43200,
                              lambda: _load_recs(symbol.upper()))
        return val or {}
    except Exception as e:
        log.warning("finnhub recommendations %s failed: %s", symbol, e)
        return {}
