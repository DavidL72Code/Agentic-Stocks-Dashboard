"""Yahoo provider.

Everything blocking runs in a thread. The important bit is `quotes()`, which
uses the v7 batch endpoint: up to 100 symbols in ONE http request (~0.15s),
vs 3 requests per ticker for .info. yf.download does NOT batch - it only
parallelises - so it is not used here.
"""
from __future__ import annotations
import asyncio, logging, math
from typing import Any
import pandas as pd, yfinance as yf
from yfinance.data import YfData

from ..cache import BatchLoader, cached

log = logging.getLogger("provider.yahoo")
_data = YfData()
_warm = False

QUOTE_URL = "https://query2.finance.yahoo.com/v7/finance/quote"
QUOTE_FIELDS = (
    "symbol,shortName,longName,regularMarketPrice,regularMarketChange,"
    "regularMarketChangePercent,regularMarketVolume,averageDailyVolume3Month,"
    "marketCap,trailingPE,forwardPE,priceToBook,fiftyTwoWeekHigh,fiftyTwoWeekLow,"
    "fiftyDayAverage,twoHundredDayAverage,marketState,currency,exchange"
)


def _warm_session() -> None:
    """v7/quote needs Yahoo's cookie+crumb; yfinance acquires it on any call."""
    global _warm
    if not _warm:
        try:
            yf.Ticker("SPY").history(period="1d")
        except Exception as e:
            log.warning("session warm-up failed: %s", e)
        _warm = True


def _quotes_blocking(symbols: list[str]) -> dict[str, dict]:
    _warm_session()
    js = _data.get_raw_json(QUOTE_URL,
                            params={"symbols": ",".join(symbols), "fields": QUOTE_FIELDS})
    rows = js.get("quoteResponse", {}).get("result", []) or []
    return {r["symbol"]: r for r in rows if r.get("symbol")}


async def _quotes_batch(symbols: list[str]) -> dict[str, dict]:
    return await asyncio.to_thread(_quotes_blocking, symbols)


# One loader process-wide: every quote() call in flight coalesces into one request.
QUOTE_LOADER = BatchLoader(_quotes_batch, window=0.02, max_batch=100)


async def quote(symbol: str) -> dict | None:
    """Per-ticker semantics, batched transport."""
    return await QUOTE_LOADER.load(symbol.upper())


async def quotes(symbols: list[str]) -> dict[str, dict]:
    return await QUOTE_LOADER.load_many([s.upper() for s in symbols])


# ---------------- single-symbol endpoints (no batch endpoint exists) -------------

def _bars_blocking(symbol: str, period: str, interval: str) -> list[dict]:
    h = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
    if h is None or h.empty:
        return []
    h = h.reset_index()
    tcol = "Datetime" if "Datetime" in h.columns else "Date"
    return [
        {"t": int(pd.Timestamp(r[tcol]).timestamp()),
         "o": round(float(r["Open"]), 4), "h": round(float(r["High"]), 4),
         "l": round(float(r["Low"]), 4),  "c": round(float(r["Close"]), 4),
         "v": int(r["Volume"] or 0)}
        for _, r in h.iterrows() if pd.notna(r["Close"])
    ]


async def bars(symbol: str, period: str = "1y", interval: str = "1d") -> list[dict]:
    ttl = 60 if interval.endswith(("m", "h")) else 3600
    val, _ = await cached(("bars", symbol.upper(), period, interval), ttl,
                          lambda: asyncio.to_thread(_bars_blocking, symbol.upper(),
                                                    period, interval))
    return val


def clean(o: Any) -> Any:
    """pandas NaN/Inf are not JSON-serialisable - scrub at the boundary."""
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if o is None or isinstance(o, (str, int, bool)):
        return o
    if isinstance(o, (pd.Timestamp,)):
        return str(o)
    try:
        if pd.isna(o):
            return None
    except (TypeError, ValueError):
        pass
    return o


def _attr_blocking(symbol: str, attr: str) -> Any:
    obj = getattr(yf.Ticker(symbol), attr)
    if isinstance(obj, pd.DataFrame):
        return clean(obj.to_dict("index")) if not obj.empty else {}
    if isinstance(obj, pd.Series):
        return clean({str(k): v for k, v in obj.items()})
    return clean(obj)


async def attr(symbol: str, name: str, ttl: float = 86400) -> Any:
    """Cached access to any yfinance Ticker attribute (info, news, calendar, ...)."""
    val, stale = await cached(("attr", symbol.upper(), name), ttl,
                              lambda: asyncio.to_thread(_attr_blocking, symbol.upper(), name))
    return val


async def info(symbol: str) -> dict:
    """3 http requests - detail pages only, never for watchlist tiles."""
    return await attr(symbol, "info", ttl=86400) or {}


PEERS_URL = "https://query2.finance.yahoo.com/v6/finance/recommendationsbysymbol/{sym}"


def _peers_blocking(symbol: str) -> list[str]:
    _warm_session()
    js = _data.get_raw_json(PEERS_URL.format(sym=symbol))
    res = (js.get("finance", {}).get("result") or [{}])[0]
    return [x["symbol"] for x in res.get("recommendedSymbols", []) if x.get("symbol")]


async def peers(symbol: str) -> list[str]:
    """Yahoo's 'people also watch' cohort - a real starting point for peers."""
    val, _ = await cached(("peers", symbol.upper()), 86400,
                          lambda: asyncio.to_thread(_peers_blocking, symbol.upper()))
    return val


SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
# the big three plus the two that explain a risk-off day
INDEXES = ["^GSPC", "^DJI", "^IXIC", "^VIX", "^TNX"]   # the big three + the two that explain a risk-off day


def _search_blocking(q: str) -> list[dict]:
    _warm_session()
    js = _data.get_raw_json(SEARCH_URL, params={"q": q, "quotesCount": 10, "newsCount": 0})
    out = []
    for x in js.get("quotes", []):
        sym, qt = x.get("symbol"), x.get("quoteType")
        if not sym or qt not in ("EQUITY", "ETF", "INDEX"):
            continue                      # drop futures / options / CDR noise
        out.append({"symbol": sym, "name": x.get("shortname") or x.get("longname") or "",
                    "type": qt, "exchange": x.get("exchDisp") or ""})
    return out[:8]


async def search(q: str) -> list[dict]:
    if not q or len(q) < 1:
        return []
    val, _ = await cached(("search", q.lower()), 3600,
                          lambda: asyncio.to_thread(_search_blocking, q))
    return val


async def etfs_for(term: str, limit: int = 6) -> list[str]:
    """Discover ETFs for a sector/industry phrase via Yahoo search.

    Replaces a hand-written sector -> ETF table: whatever the issuer calls its
    industry, we look it up and let correlation decide which proxy actually
    tracks the stock.
    """
    if not term:
        return []
    rows = await search(term)
    return [r["symbol"] for r in rows if r.get("type") == "ETF"][:limit]


def _news_search_blocking(symbol: str, limit: int) -> list[dict]:
    _warm_session()
    js = _data.get_raw_json(SEARCH_URL,
                            params={"q": symbol, "quotesCount": 0, "newsCount": limit})
    out = []
    for n in js.get("news", []):
        t = n.get("title")
        if not t:
            continue
        out.append({"title": t, "publisher": n.get("publisher"),
                    "published": n.get("providerPublishTime"),
                    "url": n.get("link"), "via": "search"})
    return out


async def news_for(symbol: str, limit: int = 10) -> list[dict]:
    """Headlines, with a fallback path.

    Yahoo's per-ticker .news endpoint intermittently returns an empty list for
    every symbol at once. v1/finance/search carries news on a different path, so
    we fall through to it rather than showing the user nothing.
    """
    async def load() -> list[dict]:
        raw = await asyncio.to_thread(_attr_blocking, symbol.upper(), "news")
        items = []
        for n in (raw or [])[:limit]:
            c = n.get("content") or {}
            t = n.get("title") or c.get("title")
            if not t:
                continue
            items.append({"title": t,
                          "publisher": (c.get("provider") or {}).get("displayName") or n.get("publisher"),
                          "published": str(c.get("pubDate") or n.get("providerPublishTime") or "")[:10],
                          "url": (c.get("canonicalUrl") or {}).get("url") or n.get("link"),
                          "via": "ticker"})
        if items:
            return items
        log.info("news: .news empty for %s, falling back to search", symbol)
        return await asyncio.to_thread(_news_search_blocking, symbol.upper(), limit)

    val, _ = await cached(("news", symbol.upper(), limit), 900, load)
    return val
