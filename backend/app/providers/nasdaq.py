"""Nasdaq.com's site API - analyst price targets where Yahoo's are missing.

Yahoo's targets live behind the crumb, which Render cannot get; Finnhub's are
on paid plans only. Nasdaq's analyst endpoint needs no key, has no daily cap,
and answers from Render (probed: 200 in 132ms). It is the API nasdaq.com's own
pages call, so it wants browser-looking headers.

Returns Yahoo's .info key names, so yahoo.info() can merge it in directly.
"""
from __future__ import annotations
import asyncio, logging

from ..cache import cached

log = logging.getLogger("provider.nasdaq")
URL = "https://api.nasdaq.com/api/analyst/{}/targetprice"
HEADERS = {"Accept": "application/json", "Origin": "https://www.nasdaq.com",
           "Referer": "https://www.nasdaq.com/"}


def _num(v):
    try:
        return float(v) if v not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None


def _targets_blocking(symbol: str) -> dict:
    from curl_cffi import requests as cr
    r = cr.get(URL.format(symbol), headers=HEADERS, impersonate="chrome", timeout=10)
    r.raise_for_status()
    o = ((r.json() or {}).get("data") or {}).get("consensusOverview") or {}
    out = {"targetLowPrice": _num(o.get("lowPriceTarget")),
           "targetMeanPrice": _num(o.get("priceTarget")),
           "targetHighPrice": _num(o.get("highPriceTarget"))}
    return {k: v for k, v in out.items() if v}


async def targets(symbol: str) -> dict:
    """{targetLowPrice, targetMeanPrice, targetHighPrice}; {} if none or on error."""
    try:
        val, _ = await cached(("nasdaq", "targets", symbol.upper()), 43200,
                              lambda: asyncio.to_thread(_targets_blocking, symbol.upper()))
        return val or {}
    except Exception as e:
        log.warning("nasdaq targets %s failed: %s", symbol, e)
        return {}
