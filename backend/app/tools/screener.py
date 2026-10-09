"""Screener - finds stocks instead of studying the ones it is handed.

Every other tool starts from a ticker. These start from the whole US market
(Nasdaq's list, ~7,000 names) and narrow it by size, sector and style, so "find
me some small caps with growing revenue" has an answer that is a measured
screen rather than a model's recollection of names.

Two stages, both code, no model:
  1. filter the full list - size bucket, sector, a liquidity floor and no
     penny stocks, because a screen that surfaces untradeable names is noise
  2. enrich the shortlist - one batched quote call for P/E and the 52-week
     range, then company fundamentals (growth, margins) for the top dozen

The results are CANDIDATES MEETING CRITERIA. The tool says so in its output,
and the writer is told to present them that way: never as picks or buys.
"""
from __future__ import annotations
import asyncio

from ..providers import nasdaq, yahoo
from ._util import fail, ok
from .registry import tool

# Nasdaq's own size buckets, by market cap
CAPS = {"nano": (0, 50e6), "micro": (50e6, 300e6), "small": (300e6, 2e9),
        "mid": (2e9, 10e9), "large": (10e9, 200e9), "mega": (200e9, float("inf"))}
# dollars traded a day, below which a name is too thin to screen in
MIN_DOLLAR_VOL = {"nano": 2e5, "micro": 5e5, "small": 2e6, "mid": 5e6, "large": 2e7, "mega": 5e7}
STYLES = ("balanced", "growth", "value", "momentum", "quality")
# Nasdaq's sector names, and the words people use for them. Matched to the
# SECTOR, never by substring: "technology" used to match biotech, because
# "biotechnology" contains it.
SECTORS = {"Technology": ("tech", "technology", "software", "semiconductor", "semis", "ai"),
           "Health Care": ("health", "healthcare", "health care", "biotech", "pharma", "medical"),
           "Finance": ("finance", "financial", "financials", "bank", "banks", "insurance", "fintech"),
           "Consumer Discretionary": ("consumer discretionary", "consumer", "retail", "discretionary"),
           "Consumer Staples": ("consumer staples", "staples"),
           "Industrials": ("industrial", "industrials", "aerospace", "defense", "defence"),
           "Energy": ("energy", "oil", "gas", "oil and gas"),
           "Utilities": ("utility", "utilities"),
           "Real Estate": ("real estate", "reit", "reits", "property"),
           "Basic Materials": ("materials", "basic materials", "mining", "chemicals"),
           "Telecommunications": ("telecom", "telecommunications", "communication", "communications")}


def _sector(sector: str | None) -> str | None:
    s = (sector or "").lower().strip()
    if not s:
        return None
    for name, words in SECTORS.items():
        if s == name.lower() or s in words:
            return name
    return None
CRITERIA = {
    "growth": "highest year-over-year revenue growth",
    "value": "lowest positive trailing P/E",
    "momentum": "closest to their 52-week high",
    "quality": "highest operating margin, profitable",
    "balanced": "most actively traded, with valuation and growth shown",
}


def _cap(cap: str | None) -> str:
    c = (cap or "small").lower().replace("-cap", "").replace(" cap", "").strip()
    return {"low": "small", "lowcap": "small", "smallcap": "small", "midcap": "mid",
            "largecap": "large", "penny": "micro"}.get(c, c if c in CAPS else "small")


def _style(style: str | None) -> str:
    s = (style or "balanced").lower().strip()
    return s if s in STYLES else {"cheap": "value", "undervalued": "value", "trend": "momentum",
                                   "profitable": "quality", "fast-growing": "growth"}.get(s, "balanced")


async def _universe(cap: str, sector: str | None) -> list[dict]:
    lo, hi = CAPS[cap]
    rows = await nasdaq.screener_rows()
    sec = _sector(sector)
    out = []
    for r in rows:
        mc, px, vol = r["market_cap"], r["price"], r["volume"]
        if not mc or not px or not vol or not (lo <= mc < hi) or px < 1:
            continue
        if px * vol < MIN_DOLLAR_VOL[cap]:
            continue
        if sec and r["sector"] != sec:
            continue
        out.append({**r, "dollar_volume": px * vol})
    return out


async def _fundamentals(sym: str) -> dict:
    try:
        i = await asyncio.wait_for(yahoo.info(sym), timeout=12)
    except Exception:
        return {}
    pick = {"revenueGrowth": "revenue_growth_pct", "operatingMargins": "operating_margin_pct",
            "profitMargins": "net_margin_pct", "returnOnEquity": "roe_pct"}
    return {v: round(i[k] * 100, 1) for k, v in pick.items() if isinstance(i.get(k), (int, float))}


@tool("screener", "screen the whole US market by size (micro/small/mid/large), sector and style "
                  "(growth, value, momentum, quality) - returns candidates, needs no ticker")
async def screen_stocks(ticker: str = "MARKET", cap: str = "small", sector: str = "",
                        style: str = "balanced", limit: int = 6, **_):
    cap, style, limit = _cap(cap), _style(style), max(3, min(int(limit or 6), 10))
    try:
        uni = await _universe(cap, sector)
    except Exception as e:
        return fail("screen_stocks", "MARKET", f"market list unavailable: {type(e).__name__}")
    if sector and not _sector(sector):
        return fail("screen_stocks", "MARKET", f"unknown sector '{sector}'; try one of: "
                                               + ", ".join(SECTORS))
    if not uni:
        return fail("screen_stocks", "MARKET", f"no liquid {cap}-cap stocks matched"
                                               + (f" in {sector}" if sector else ""))
    # the most actively traded names are the ones a screen can say anything
    # reliable about; enrich those
    uni.sort(key=lambda r: r["dollar_volume"], reverse=True)
    short = uni[:80]
    q = await yahoo.quotes([r["symbol"] for r in short])
    for r in short:
        qq = q.get(r["symbol"]) or {}
        r["pe"] = qq.get("trailingPE")
        hi, lo = qq.get("fiftyTwoWeekHigh"), qq.get("fiftyTwoWeekLow")
        r["pct_below_52w_high"] = round((1 - r["price"] / hi) * 100, 1) if hi else None
        r["pct_above_52w_low"] = round((r["price"] / lo - 1) * 100, 1) if lo else None

    if style == "value":
        short = sorted([r for r in short if isinstance(r.get("pe"), (int, float)) and 0 < r["pe"] < 60],
                       key=lambda r: r["pe"])
    elif style == "momentum":
        short = sorted([r for r in short if r.get("pct_below_52w_high") is not None],
                       key=lambda r: r["pct_below_52w_high"])
    # growth and quality need company fundamentals: fetch them for a dozen
    deep = short[:12] if style in ("growth", "quality", "value") else short[:limit]
    funds = await asyncio.gather(*(_fundamentals(r["symbol"]) for r in deep))
    for r, f in zip(deep, funds):
        r.update(f)
    if style == "growth":
        short = sorted([r for r in deep if r.get("revenue_growth_pct") is not None],
                       key=lambda r: r["revenue_growth_pct"], reverse=True)
    elif style == "value":
        # a low P/E on a business losing money at the operating line is usually
        # a one-off gain, not cheapness - the classic value trap
        short = [r for r in deep if (r.get("operating_margin_pct") or 0) > 0] or deep
    elif style == "quality":
        short = sorted([r for r in deep if (r.get("operating_margin_pct") or 0) > 0
                        and (r.get("net_margin_pct") or 0) > 0],
                       key=lambda r: r["operating_margin_pct"], reverse=True)
    picks = short[:limit]
    if not picks:
        return fail("screen_stocks", "MARKET", f"nothing in the {cap}-cap list had the data a "
                                               f"{style} screen needs")
    keep = ("symbol", "name", "sector", "industry", "price", "change_pct", "market_cap", "pe",
            "pct_below_52w_high", "revenue_growth_pct", "operating_margin_pct", "net_margin_pct")
    return ok("screen_stocks", "MARKET", {
        "screen": f"{cap}-cap US stocks" + (f" in {_sector(sector)}" if sector else "")
                  + f", ranked by {CRITERIA[style]}",
        "universe_size": len(uni),
        "liquidity_floor_usd_per_day": MIN_DOLLAR_VOL[cap],
        "results": [{k: r.get(k) for k in keep if r.get(k) is not None} for r in picks],
        "note": "candidates that meet the screen's criteria - not recommendations",
    }, source="nasdaq-screener+yahoo")


@tool("screener", "today's biggest gainers and losers within a size bucket, liquid names only",
      derived=True)
async def cap_movers(ticker: str = "MARKET", cap: str = "small", sector: str = "", **_):
    cap = _cap(cap)
    try:
        uni = [r for r in await _universe(cap, sector) if r.get("change_pct") is not None]
    except Exception as e:
        return fail("cap_movers", "MARKET", f"market list unavailable: {type(e).__name__}")
    if not uni:
        return fail("cap_movers", "MARKET", f"no liquid {cap}-cap stocks to rank")
    uni.sort(key=lambda r: r["change_pct"])
    row = lambda r: {"symbol": r["symbol"], "name": r["name"], "change_pct": r["change_pct"],
                     "price": r["price"], "market_cap": r["market_cap"], "sector": r["sector"]}
    up = [r for r in uni if r["change_pct"] > 0]
    return ok("cap_movers", "MARKET", {
        "bucket": f"{cap}-cap", "names_ranked": len(uni),
        "share_up_today_pct": round(len(up) / len(uni) * 100, 1),
        "top_gainers": [row(r) for r in uni[::-1][:5]],
        "top_losers": [row(r) for r in uni[:5]],
    }, source="nasdaq-screener")
