"""Macro / market-wide context.

Ticker feeds only tell you about one company. Index, rates and volatility feeds
carry the backdrop - policy, the Fed, geopolitics - and sector ETF feeds carry
the trickle-down from one big name to its neighbours. This is where the brief
gets "why did everything move" rather than "this one moved".
"""
from __future__ import annotations
import asyncio
from ..providers import yahoo
from ._util import empty, fail, ok
from .registry import tool

INDEXES = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^TNX": "US 10-year yield",
           "^VIX": "volatility index"}
# No sector -> ETF table. The proxy is discovered from the issuer's own stated
# industry and then chosen by measured correlation, so a new ticker needs no
# code change and the proxy is the one that actually tracks it.


async def _headlines(sym: str, limit: int = 6) -> list[dict]:
    items = await yahoo.news_for(sym, limit)
    return [{**h, "source_feed": sym} for h in items[:limit]]


@tool("macro", "market-wide headlines: policy, the Fed, rates, geopolitics, broad risk")
async def market_news(ticker: str = "", **_):
    lists = await asyncio.gather(*( _headlines(s, 5) for s in ("^GSPC", "^TNX", "^VIX")),
                                 return_exceptions=True)
    items, seen = [], set()
    for l in lists:
        if isinstance(l, Exception):
            continue
        for h in l:
            if h["title"] in seen:
                continue
            seen.add(h["title"])
            items.append(h)
    if not items:
        return empty("market_news", ticker or "MARKET", "no market-level headlines")
    return ok("market_news", ticker or "MARKET",
              {"headlines": items[:12],
               "note": "from index, rates and volatility feeds - treat as reported claims, not facts"})


@tool("macro", "index, rates and volatility levels right now")
async def index_levels(ticker: str = "", **_):
    q = await yahoo.quotes(list(INDEXES) + ["SPY", "QQQ"])
    out = {}
    for s, label in INDEXES.items():
        r = q.get(s) or {}
        if r.get("regularMarketPrice") is not None:
            out[label] = {"level": round(r["regularMarketPrice"], 2),
                          "change_pct": round(r.get("regularMarketChangePercent") or 0, 2)}
    return ok("index_levels", ticker or "MARKET", out) if out \
        else fail("index_levels", ticker or "MARKET", "no index quotes")


@tool("macro", "headlines for the sector a ticker sits in - catches spillover from peers")
async def sector_news(ticker: str, **_):
    if not ticker or ticker.upper() == "MARKET":
        return empty("sector_news", ticker or "MARKET",
                     "sector spillover needs a specific ticker")
    from .relations import resolve_proxy
    proxy = await resolve_proxy(ticker)
    if not proxy:
        return empty("sector_news", ticker, "nothing tracked this ticker closely enough")

    sources = [proxy["etf"]] if proxy["kind"] == "etf" else proxy["cohort"]
    lists = await asyncio.gather(*(_headlines(s, 4) for s in sources), return_exceptions=True)
    items, seen = [], set()
    for l in lists:
        if isinstance(l, Exception):
            continue
        for h in l:
            if h["title"] not in seen:
                seen.add(h["title"])
                items.append(h)
    if not items:
        return empty("sector_news", ticker, f"no headlines from {', '.join(sources)}")
    return ok("sector_news", ticker,
              {"sector": proxy.get("sector"), "industry": proxy.get("industry"),
               "resolved_as": proxy["kind"], "sources": sources,
               "proxy_correlation": proxy.get("correlation"),
               "headlines": items[:8],
               "note": "spillover source discovered per ticker from its own industry and "
                       "peer cohort, then chosen by measured correlation"})
