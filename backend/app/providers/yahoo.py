"""Yahoo provider.

Everything blocking runs in a thread. The important bit is `quotes()`, which
uses the v7 batch endpoint: up to 100 symbols in ONE http request (~0.15s),
vs 3 requests per ticker for .info. yf.download does NOT batch - it only
parallelises - so it is not used here.
"""
from __future__ import annotations
import asyncio, logging, math, threading, time
from typing import Any
import pandas as pd, yfinance as yf
from yfinance.data import YfData

from ..cache import BatchLoader, cached
from . import finnhub, nasdaq

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


# ---------------- crumb breaker -------------------------------------------------
# Some hosts (Render) get 429 from getcrumb on the very first request - an IP
# block, not a rate limit. Every crumb-gated call then fails, but only after a
# round trip. Check once an hour and skip those calls while blocked, so a new
# ticker does not pay for three requests that cannot succeed.
CRUMB_ATTRS = {"info", "recommendations", "upgrades_downgrades"}
_crumb = {"checked": 0.0, "ok": True}
_crumb_lock = threading.Lock()


def _block_crumb(reason: str) -> None:
    if _crumb["ok"]:
        log.warning("Yahoo crumb blocked (%s); skipping crumb-gated calls for 1h", reason)
    _crumb.update(checked=time.time(), ok=False)


def crumb_ok() -> bool:
    with _crumb_lock:
        if time.time() - _crumb["checked"] < 3600:
            return _crumb["ok"]
        from curl_cffi import requests as cr
        try:
            s = cr.Session(impersonate="chrome")
            s.get("https://fc.yahoo.com", timeout=10)
            r = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10)
            ok = r.status_code == 200 and 0 < len(r.text.strip()) < 64
        except Exception as e:      # a network blip is not evidence of a block
            log.warning("crumb check failed: %s", e)
            _crumb.update(checked=time.time() - 3300, ok=True)   # retry in 5 min
            return True
        if ok:
            _crumb.update(checked=time.time(), ok=True)
        else:
            _block_crumb(f"getcrumb -> {r.status_code}")
        return ok


CHART_URL ="https://query2.finance.yahoo.com/v8/finance/chart/{}"


def _market_state(meta: dict) -> str:
    now = time.time()
    for name, state in (("regular", "REGULAR"), ("pre", "PRE"), ("post", "POST")):
        p = (meta.get("currentTradingPeriod") or {}).get(name) or {}
        if p.get("start", 0) <= now < p.get("end", 0):
            return state
    return "CLOSED"


def _chart_quote(session, symbol: str) -> dict | None:
    """A v7-shaped quote rebuilt from the v8 chart's meta block. The chart
    endpoint needs no crumb, so it still answers where Yahoo refuses the crumb
    (Render: getcrumb returns 429 on the first request - an IP block, not a rate
    limit). No marketCap / P/E here; those come from info() instead."""
    try:
        r = session.get(CHART_URL.format(symbol), params={"range": "1d", "interval": "1d"},
                        timeout=10)
        m = r.json()["chart"]["result"][0]["meta"]
    except Exception:
        return None
    px, prev = m.get("regularMarketPrice"), m.get("chartPreviousClose")
    if px is None:
        return None
    return {"symbol": symbol, "shortName": m.get("shortName"), "longName": m.get("longName"),
            "regularMarketPrice": px,
            "regularMarketChange": round(px - prev, 4) if prev else None,
            "regularMarketChangePercent": m.get("regularMarketChangePercent")
                or (round((px / prev - 1) * 100, 4) if prev else None),
            "regularMarketVolume": m.get("regularMarketVolume"),
            "fiftyTwoWeekHigh": m.get("fiftyTwoWeekHigh"),
            "fiftyTwoWeekLow": m.get("fiftyTwoWeekLow"),
            "marketState": _market_state(m), "currency": m.get("currency"),
            "exchange": m.get("exchangeName"), "_source": "yahoo-chart"}


def _chart_quotes(symbols: list[str]) -> dict[str, dict]:
    from concurrent.futures import ThreadPoolExecutor
    from curl_cffi import requests as cr
    s = cr.Session(impersonate="chrome")
    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = ex.map(lambda sym: _chart_quote(s, sym), symbols)
    return {r["symbol"]: r for r in rows if r}


def _quotes_blocking(symbols: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if crumb_ok():
        _warm_session()
        try:
            js = _data.get_raw_json(QUOTE_URL,
                                    params={"symbols": ",".join(symbols), "fields": QUOTE_FIELDS})
            rows = js.get("quoteResponse", {}).get("result", []) or []
            out = {r["symbol"]: r for r in rows if r.get("symbol")}
        except Exception as e:
            log.warning("v7 quote failed (%s); falling back to chart meta", e)
            if any(c in str(e) for c in ("401", "429", "Crumb")):
                _block_crumb(f"v7 quote: {e}")
    missing = [s for s in symbols if s not in out]
    if missing:
        out.update(_chart_quotes(missing))
    return out


async def _quotes_batch(symbols: list[str]) -> dict[str, dict]:
    return await asyncio.to_thread(_quotes_blocking, symbols)


# One loader process-wide: every quote() call in flight coalesces into one request.
QUOTE_LOADER = BatchLoader(_quotes_batch, window=0.02, max_batch=100)


async def quote(symbol: str) -> dict | None:
    """Per-ticker semantics, batched transport. A failed batch returns None, as
    quotes() already does: callers treat a missing quote as optional, and a
    Yahoo outage must not turn /overview and /news into 500s."""
    try:
        return await QUOTE_LOADER.load(symbol.upper())
    except Exception as e:
        log.warning("quote %s failed: %s", symbol, e)
        return None


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
    if attr in CRUMB_ATTRS and not crumb_ok():
        return {}               # would 401 anyway; Finnhub fills info/recommendations
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
    # Crumb-gated attrs come back near-empty where Yahoo blocks the crumb (Render
    # gets {"trailingPegRatio": None}). Fill from Finnhub when it is configured;
    # Yahoo's own values win wherever it did return them.
    if name == "info" and len(val or {}) < 5 and finnhub.enabled():
        fh = await finnhub.info(symbol)
        val = {**fh, **{k: v for k, v in (val or {}).items() if v is not None}}
    # Price targets: Yahoo's need the crumb and Finnhub's need a paid plan
    if name == "info" and not (val or {}).get("targetMeanPrice"):
        tg = await nasdaq.targets(symbol)
        if tg:
            val = {**(val or {}), **tg}
            if val.get("currentPrice") is None:     # for "upside vs last"
                q = await quote(symbol)
                if q and q.get("regularMarketPrice") is not None:
                    val["currentPrice"] = q["regularMarketPrice"]
    elif name == "recommendations" and not val and finnhub.enabled():
        val = await finnhub.recommendations(symbol)
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
