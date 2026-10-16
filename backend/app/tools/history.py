"""History: what happened the last times this stock fell hard, and what turned it.

"Will it go back up?" was answered from today's snapshot alone - RSI, the
50-day average, sentiment - when the stock's own record says more. APLD in
October 2026 sat at its 52-week low and the answer never mentioned that it had
been here before: down 50% into March 30, then +142% by May 28. This tool finds
every big drop in the window, measures how far and how fast it fell, whether
the market fell with it, how stretched it was at the bottom, how far it
rebounded and what the turn looked like (the first up-days, with their
headlines, and when it got back above its 50-day average) - then sets today
against those lows. It reports what happened; it does not forecast.
"""
from __future__ import annotations
import asyncio
from datetime import timedelta
import numpy as np
import pandas as pd
from ..providers import finnhub, yahoo
from ._util import FETCH, fail, ok, rsi, window_start
from .registry import tool

MAX_EPISODES = 4
TURN_WINDOW = 15          # trading days after a low in which to look for the turn
NEAR_LOW = 1.05           # within 5% of the 52-week low


async def _frame(ticker: str, period: str) -> pd.DataFrame:
    b = await yahoo.bars(ticker, period=FETCH.get(period, period))
    if not b:
        return pd.DataFrame()
    df = pd.DataFrame({"c": [x["c"] for x in b], "v": [x.get("v") or 0 for x in b]},
                      index=pd.to_datetime([x["t"] for x in b], unit="s").normalize())
    return df[~df.index.duplicated(keep="last")]


def _threshold(c: pd.Series) -> float:
    """What counts as a BIG drop for this stock: about three months' worth of its
    normal swings, between 12% (a utility) and 35% (a volatile small cap)."""
    vol = float(c.pct_change().std() * np.sqrt(21) * 100)
    return float(np.clip(3 * vol, 12, 35))


def _pivots(c: pd.Series, th: float) -> list[tuple[str, pd.Timestamp]]:
    """Zigzag: alternating peaks and troughs, each swing at least th%."""
    piv: list[tuple[str, pd.Timestamp]] = []
    hi_t = lo_t = c.index[0]
    trend = 0                                  # 1 rising, -1 falling, 0 unknown
    for t, px in c.items():
        if px > c[hi_t]:
            hi_t = t
        if px < c[lo_t]:
            lo_t = t
        if trend >= 0 and px <= c[hi_t] * (1 - th / 100):
            piv.append(("peak", hi_t)); trend = -1; lo_t = t
        elif trend <= 0 and px >= c[lo_t] * (1 + th / 100):
            piv.append(("trough", lo_t)); trend = 1; hi_t = t
    return piv


def _rsi_series(c: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI for every day - the same formula as the rsi_momentum tool."""
    d = c.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))


def _vs_ma(c: pd.Series, t, n: int) -> float | None:
    s = c[:t]
    return round((float(s.iloc[-1]) / float(s.tail(n).mean()) - 1) * 100, 1) if len(s) >= n else None


async def _headlines(ticker: str, day, name_words: list[str]) -> list[str]:
    if not finnhub.enabled():
        return []
    items = await finnhub.company_news(ticker, str(day - timedelta(days=1)), str(day))
    def rel(h: str) -> bool:
        hl = (h or "").lower()
        return ticker.lower() in hl.split() or any(w in hl for w in name_words)
    hits = sorted((i for i in items if rel(i.get("headline"))), key=lambda i: -i.get("datetime", 0))
    return [i["headline"][:160] for i in hits[:2]]


@tool("market",
      "PAST LOWS AND REBOUNDS: each big drop over the window (default 2y) - how far it fell, whether "
      "the market fell too, how oversold it was at the bottom, how far it rebounded, and what the turn "
      "looked like (first up-days with their headlines, getting back above the 50-day average) - set "
      "against today. Use for trend, outlook, 'will it go back up / bounce / recover', 'has it bottomed'",
      derived=True)
async def turning_points(ticker: str, period: str = "2y", **_):
    if period not in ("1y", "2y", "5y"):
        period = "2y"                          # a few months holds no past lows worth comparing
    df, spy = await asyncio.gather(_frame(ticker, period), _frame("SPY", period))
    if len(df) < 120:
        return fail("turning_points", ticker, f"need more price history than {len(df)} days")
    start = window_start(df.index, period)
    df = df[df.index >= start]
    c, v = df["c"], df["v"]
    sp = spy["c"].reindex(c.index).ffill() if not spy.empty else None
    th = _threshold(c)
    piv = _pivots(c, th)

    q = await yahoo.quote(ticker) or {}
    nm = (q.get("shortName") or q.get("longName") or "").lower().replace(",", "").split()
    words = [w for w in nm[:2] if len(w) > 3 and w not in ("inc", "corp", "the", "company", "holdings")]

    def spy_pct(a, b):
        if sp is None or pd.isna(sp.get(a)) or pd.isna(sp.get(b)):
            return None
        return round((float(sp[b]) / float(sp[a]) - 1) * 100, 1)

    def fwd(t, n):
        i = c.index.get_loc(t)
        return round((float(c.iloc[i + n]) / float(c[t]) - 1) * 100, 1) if i + n < len(c) else None

    rs, ma50 = _rsi_series(c), c.rolling(50).mean()
    pct_day = c.pct_change() * 100
    episodes = []
    for k, (kind, t) in enumerate(piv):
        if kind != "trough":
            continue
        peak_t = next((pt for pk, pt in reversed(piv[:k]) if pk == "peak"), c[:t].idxmax())
        nxt = next((pt for pk, pt in piv[k + 1:] if pk == "peak"), None)
        after = c[t:]
        reb_t = nxt or after.idxmax()
        i = c.index.get_loc(t)
        back = after[(after > ma50.reindex(after.index)) & (after.index > t)]
        prior = c[:t].tail(252)
        top_up = sorted(pct_day.iloc[i + 1:i + 1 + TURN_WINDOW].sort_values(ascending=False).head(2).items())
        heads = await asyncio.gather(*(_headlines(ticker, d.date(), words) for d, _ in top_up))
        turn_days = [{"date": str(d.date()), "move_pct": round(float(mv), 1),
                      "spy_move_pct": round(float(sp.pct_change()[d] * 100), 1) if sp is not None else None,
                      "headlines": h} for (d, mv), h in zip(top_up, heads)]
        avg_v = float(v[:t].tail(50).mean() or 0)
        episodes.append({
            "peak_date": str(peak_t.date()), "peak": round(float(c[peak_t]), 2),
            "low_date": str(t.date()), "low": round(float(c[t]), 2),
            "drop_pct": round((float(c[t]) / float(c[peak_t]) - 1) * 100, 1),
            "trading_days_falling": int(c.index.get_loc(t) - c.index.get_loc(peak_t)),
            "spy_pct_same_window": spy_pct(peak_t, t),
            "at_low_rsi14": round(float(rs[t]), 1) if pd.notna(rs[t]) else None,
            "at_low_pct_vs_200d_avg": _vs_ma(c, t, 200),
            "at_low_near_52w_low": bool(len(prior) and float(c[t]) <= float(prior.min()) * NEAR_LOW),
            "at_low_volume_vs_50d_avg": round(float(v[t]) / avg_v, 2) if avg_v else None,
            "rebound_to": round(float(c[reb_t]), 2), "rebound_peak_date": str(reb_t.date()),
            "rebound_pct": round((float(c[reb_t]) / float(c[t]) - 1) * 100, 1),
            "return_20d_after_low_pct": fwd(t, 20), "return_60d_after_low_pct": fwd(t, 60),
            "back_above_50d_avg": str(back.index[0].date()) if len(back) else None,
            "trading_days_low_to_50d_avg": int(c.index.get_loc(back.index[0]) - i) if len(back) else None,
            "turn_days": turn_days,
        })
    # the zigzag can open on a trough whose fall began before the window: only
    # drops that were actually big count as past lows
    episodes = [e for e in episodes if e["drop_pct"] <= -0.9 * th][-MAX_EPISODES:]

    # today, against those lows
    last_t = c.index[-1]
    last_peak = next((pt for pk, pt in reversed(piv) if pk == "peak"), c.idxmax())
    if piv and piv[-1][0] == "trough":         # rebounding: measure from the high since that low
        last_peak = c[piv[-1][1]:].idxmax()
    ma50_now = float(c.tail(50).mean())
    prior = c.tail(252)
    now = {
        "date": str(last_t.date()), "price": round(float(c.iloc[-1]), 2),
        "from_peak_date": str(last_peak.date()), "peak": round(float(c[last_peak]), 2),
        "drop_from_peak_pct": round((float(c.iloc[-1]) / float(c[last_peak]) - 1) * 100, 1),
        "trading_days_since_peak": int(c.index.get_loc(last_t) - c.index.get_loc(last_peak)),
        "spy_pct_same_window": spy_pct(last_peak, last_t),
        "rsi14": rsi(c.tail(126)),            # six months, as rsi_momentum reads it
        "pct_vs_200d_avg": _vs_ma(c, last_t, 200),
        "near_52w_low": bool(float(c.iloc[-1]) <= float(prior.min()) * NEAR_LOW),
        "above_50d_avg": bool(float(c.iloc[-1]) > ma50_now),
        "pct_vs_50d_avg": round((float(c.iloc[-1]) / ma50_now - 1) * 100, 1),
        "volume_vs_50d_avg": round(float(v.iloc[-1]) / float(v.tail(51).head(50).mean() or 1), 2),
    }

    # the base rate: every time it was this stretched near a 52-week low
    low252 = c.rolling(252, min_periods=120).min()
    sig = c.index[(rs < 30) & (c <= low252 * NEAR_LOW)]
    picked, last_pick = [], None
    for t in sig:
        if last_pick is None or c.index.get_loc(t) - c.index.get_loc(last_pick) >= 20:
            picked.append(t); last_pick = t
    f20 = [x for x in (fwd(t, 20) for t in picked) if x is not None]
    f60 = [x for x in (fwd(t, 60) for t in picked) if x is not None]
    base = {"times": len(picked), "dates": [str(t.date()) for t in picked][-6:],
            "higher_20d_later": sum(x > 0 for x in f20), "measured_20d": len(f20),
            "median_20d_pct": round(float(np.median(f20)), 1) if f20 else None,
            "higher_60d_later": sum(x > 0 for x in f60), "measured_60d": len(f60),
            "median_60d_pct": round(float(np.median(f60)), 1) if f60 else None}

    return ok("turning_points", ticker, {
        "period": period, "big_drop_threshold_pct": round(th, 1),
        "past_lows": episodes, "now": now,
        "oversold_near_52w_low_history": base,
        "headlines_available": finnhub.enabled(),
        "note": ("What happened before, not a forecast. A handful of past lows is a small sample; "
                 "headlines on a turn day may coincide with the move without causing it."),
    }, source="derived")
