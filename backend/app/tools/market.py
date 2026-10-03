from __future__ import annotations
import numpy as np
from ..providers import yahoo
from ._util import closes, empty, fail, ok, pct, rsi
from .registry import tool


@tool("market", "current price, day change %, volume, market state")
async def quote(ticker: str, **_):
    q = await yahoo.quote(ticker)
    if not q or q.get("regularMarketPrice") is None:
        return fail("quote", ticker, "no quote returned")
    return ok("quote", ticker, {
        "price": q["regularMarketPrice"],
        "change": q.get("regularMarketChange"),
        "change_pct": q.get("regularMarketChangePercent"),
        "volume": q.get("regularMarketVolume"),
        "market_state": q.get("marketState"), "name": q.get("shortName"),
    })


@tool("market", "OHLCV history summary over a window (start, end, high, low, % move)")
async def price_series(ticker: str, period: str = "3mo", **_):
    s = await closes(ticker, period)
    if s.empty:
        return fail("price_series", ticker, "no bars")
    return ok("price_series", ticker, {
        "period": period, "bars": len(s),
        "start": round(float(s.iloc[0]), 2), "end": round(float(s.iloc[-1]), 2),
        "high": round(float(s.max()), 2), "low": round(float(s.min()), 2),
        "change_pct": pct(float(s.iloc[-1]), float(s.iloc[0])),
    })


@tool("market", "52-week high/low and where the price sits inside that range")
async def range_52w(ticker: str, **_):
    q = await yahoo.quote(ticker)
    hi, lo, px = (q or {}).get("fiftyTwoWeekHigh"), (q or {}).get("fiftyTwoWeekLow"), (q or {}).get("regularMarketPrice")
    if not all(isinstance(v, (int, float)) for v in (hi, lo, px)):
        return fail("range_52w", ticker, "range unavailable")
    return ok("range_52w", ticker, {
        "high_52w": hi, "low_52w": lo, "price": px,
        "pct_below_high": round((hi - px) / hi * 100, 2) if hi else None,
        "pct_above_low": round((px - lo) / lo * 100, 2) if lo else None,
        "position_in_range_pct": round((px - lo) / (hi - lo) * 100, 1) if hi > lo else None,
    })


@tool("market", "50/200-day moving averages and price position vs them", derived=True)
async def moving_averages(ticker: str, **_):
    s = await closes(ticker, "1y")
    if len(s) < 50:
        return fail("moving_averages", ticker, "need 50+ bars")
    px = float(s.iloc[-1]); ma50 = float(s.tail(50).mean())
    ma200 = float(s.tail(200).mean()) if len(s) >= 200 else None
    return ok("moving_averages", ticker, {
        "price": round(px, 2), "ma50": round(ma50, 2),
        "ma200": round(ma200, 2) if ma200 else None,
        "vs_ma50_pct": pct(px, ma50),
        "vs_ma200_pct": pct(px, ma200) if ma200 else None,
        "golden_cross": (ma200 is not None and ma50 > ma200),
    }, source="derived")


@tool("market", "14-day RSI momentum (over 70 overbought, under 30 oversold)", derived=True)
async def rsi_momentum(ticker: str, **_):
    s = await closes(ticker, "6mo")
    v = rsi(s)
    if v is None:
        return fail("rsi_momentum", ticker, "insufficient history")
    return ok("rsi_momentum", ticker, {
        "rsi14": v,
        "reading": "overbought" if v > 70 else "oversold" if v < 30 else "neutral",
    }, source="derived")


@tool("market", "annualised realised volatility and beta vs SPY", derived=True)
async def volatility(ticker: str, **_):
    s = await closes(ticker, "1y"); spy = await closes("SPY", "1y")
    if len(s) < 60:
        return fail("volatility", ticker, "insufficient history")
    r = s.pct_change().dropna()
    out = {"realised_vol_annual_pct": round(float(r.std() * np.sqrt(252) * 100), 1),
           "avg_daily_move_pct": round(float(r.abs().mean() * 100), 2)}
    j = r.to_frame("a").join(spy.pct_change().dropna().to_frame("b"), how="inner").dropna()
    if len(j) > 60:
        out["beta_vs_spy"] = round(float(np.polyfit(j["b"], j["a"], 1)[0]), 2)
        out["corr_vs_spy"] = round(float(j["a"].corr(j["b"])), 2)
    return ok("volatility", ticker, out, source="derived")


@tool("market", "today's volume vs 20-day average; flags unusual participation", derived=True)
async def volume_profile(ticker: str, **_):
    b = await yahoo.bars(ticker, period="3mo")
    if len(b) < 21:
        return fail("volume_profile", ticker, "insufficient history")
    vols = [x["v"] for x in b if x["v"]]
    today, avg20 = vols[-1], sum(vols[-21:-1]) / 20
    ratio = today / avg20 if avg20 else None
    return ok("volume_profile", ticker, {
        "volume": today, "avg_volume_20d": int(avg20),
        "ratio": round(ratio, 2) if ratio else None,
        "unusual": bool(ratio and ratio > 1.5),
    }, source="derived")


@tool("market", "drawdown from the highest close in the window", derived=True)
async def drawdown(ticker: str, period: str = "1y", **_):
    s = await closes(ticker, period)
    if s.empty:
        return fail("drawdown", ticker, "no bars")
    peak = float(s.max()); px = float(s.iloc[-1])
    return ok("drawdown", ticker, {
        "peak": round(peak, 2), "price": round(px, 2),
        "drawdown_pct": round((px - peak) / peak * 100, 2),
        "peak_date": str(s.idxmax().date()),
    }, source="derived")


@tool("market", "performance vs SPY over 1m and 3m, plus any requested window (relative strength)", derived=True)
async def relative_strength(ticker: str, period: str | None = None, **_):
    s = await closes(ticker, "1y"); spy = await closes("SPY", "1y")
    if len(s) < 65 or len(spy) < 65:
        return fail("relative_strength", ticker, "insufficient history")
    out = {}
    if period and period not in ("1mo", "3mo"):
        ws, wm = await closes(ticker, period), await closes("SPY", period)
        if len(ws) > 5 and len(wm) > 5:
            t, m = pct(float(ws.iloc[-1]), float(ws.iloc[0])), pct(float(wm.iloc[-1]), float(wm.iloc[0]))
            out.update({f"{period}_stock_pct": t, f"{period}_spy_pct": m,
                        f"{period}_excess_pct": round(t - m, 2)})
    for label, n in (("1m", 21), ("3m", 63)):
        t = pct(float(s.iloc[-1]), float(s.iloc[-n]))
        m = pct(float(spy.iloc[-1]), float(spy.iloc[-n]))
        out[f"{label}_stock_pct"] = t
        out[f"{label}_spy_pct"] = m
        out[f"{label}_excess_pct"] = round(t - m, 2)
    return ok("relative_strength", ticker, out, source="derived")
