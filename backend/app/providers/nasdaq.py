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


# ════════════════════ the whole US market, for screening ════════════════════
# Every listed US stock in one call (~7,000 rows, ~3s): price, today's move,
# volume, market cap, sector, industry, country. The same site API, the same
# headers. It is what lets the agent find names instead of only studying the
# ones it is handed. Cached 15 minutes - a screen does not need tick data.
SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&download=true"


def _money(v):
    try:
        return float(str(v).replace("$", "").replace(",", "").replace("%", "")) if v not in (None, "", "NA", "N/A") else None
    except (TypeError, ValueError):
        return None


def _screener_blocking() -> list[dict]:
    from curl_cffi import requests as cr
    r = cr.get(SCREENER_URL, headers=HEADERS, impersonate="chrome", timeout=30)
    r.raise_for_status()
    rows = ((r.json() or {}).get("data") or {}).get("rows") or []
    out = []
    for x in rows:
        sym = (x.get("symbol") or "").strip().upper()
        # common stock only: no warrants, units, rights or preferred classes
        if not sym or any(c in sym for c in "^/ ") or len(sym) > 6:
            continue
        out.append({"symbol": sym, "name": (x.get("name") or "").replace(" Common Stock", "").strip(),
                    "price": _money(x.get("lastsale")), "change_pct": _money(x.get("pctchange")),
                    "volume": _money(x.get("volume")), "market_cap": _money(x.get("marketCap")),
                    "sector": x.get("sector") or "", "industry": x.get("industry") or "",
                    "country": x.get("country") or ""})
    return out


async def screener_rows() -> list[dict]:
    """Every US-listed common stock with price, move, volume, cap and sector."""
    val, _ = await cached(("nasdaq", "screener"), 900, lambda: asyncio.to_thread(_screener_blocking))
    return val or []
