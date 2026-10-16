from __future__ import annotations
import numpy as np
from ..providers import yahoo
from ._util import closes, empty, fail, ok, pct, rsi
from .sources import yf
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


@tool("market", "52-week high/low (intraday) and where the price sits inside that range")
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
        "range_basis": "intraday highs and lows, so the high can sit above the highest close",
    }, label=f"Yahoo Finance · {ticker.upper()} quote (52-week range counts intraday trades)")


@tool("market", "50/200-day moving averages and price position vs them", derived=True)
async def moving_averages(ticker: str, **_):
    """Yahoo's published averages when the quote carries them, so the figure
    matches the Statistics page it links to (they average unadjusted closes up
    to yesterday; ours, from dividend-adjusted closes plus today's live price,
    ran ~0.25% off). Computed from the price history only as a fallback."""
    t = ticker.upper()
    s = await closes(ticker, "1y")
    if len(s) < 50:
        return fail("moving_averages", ticker, "need 50+ bars")
    px = float(s.iloc[-1])
    q = await yahoo.quote(ticker) or {}
    a50, a200 = q.get("fiftyDayAverage"), q.get("twoHundredDayAverage")
    published = isinstance(a50, (int, float)) and isinstance(a200, (int, float))
    if published:
        ma50, ma200 = float(a50), float(a200)
    else:
        ma50 = float(s.tail(50).mean())
        ma200 = float(s.tail(200).mean()) if len(s) >= 200 else None
    data = {
        "price": round(px, 2), "ma50": round(ma50, 2),
        "ma200": round(ma200, 2) if ma200 else None,
        "vs_ma50_pct": pct(px, ma50),
        "vs_ma200_pct": pct(px, ma200) if ma200 else None,
        "golden_cross": (ma200 is not None and ma50 > ma200),
    }
    if published:
        return ok("moving_averages", ticker, data, source="yahoo",
                  label=f"Yahoo Finance · {t} statistics (50-day and 200-day moving averages)",
                  url=yf(t, "key-statistics/"))
    return ok("moving_averages", ticker, data, source="derived")


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
        # quote pages publish a 5-year MONTHLY beta (NVDA: Yahoo 2.22 vs this 1.86);
        # say which one this is so a reader who checks isn't told it's wrong
        out["beta_basis"] = "1 year of daily moves vs SPY (Yahoo's 'Beta (5Y Monthly)' uses 5 years of monthly moves)"
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
    # the peak is a CLOSE; the 52-week high is intraday and usually higher, so the
    # keys say which one this is and the writer doesn't present two "peaks"
    s = await closes(ticker, period)
    if s.empty:
        return fail("drawdown", ticker, "no bars")
    peak = float(s.max()); px = float(s.iloc[-1])
    return ok("drawdown", ticker, {
        "peak_close": round(peak, 2), "price": round(px, 2),
        "drawdown_from_peak_close_pct": round((px - peak) / peak * 100, 2),
        "peak_close_date": str(s.idxmax().date()),
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


@tool("market",
      "TREND across several windows at once (1m/6m/1y/3y): direction, strength and "
      "whether short and long term agree or conflict", derived=True)
async def trend(ticker: str, **_):
    """One window cannot answer "what is the trend".

    A name can be down 8% this month inside a 1y uptrend, which is a pullback,
    or down 8% inside a 1y downtrend, which is continuation. The two readings
    call for opposite things, so every window is reported and the agreement
    between them is stated rather than left to be inferred from one number.

    Strength is r-squared of a straight line through log price: how much of the
    move is direction rather than noise. A 40% gain that zig-zagged the whole
    way is a weaker trend than a 12% gain that went straight up.
    """
    import numpy as np
    windows = {"1m": "1mo", "6m": "6mo", "1y": "1y", "3y": "5y"}
    rows, series = {}, {}
    for label, period in windows.items():
        s = await closes(ticker, period)
        if label == "3y" and len(s) > 756:
            s = s.iloc[-756:]                      # 5y fetch, 3y window
        if len(s) < 15:
            continue
        series[label] = s
        y = np.log(s.values.astype(float))
        x = np.arange(len(y), dtype=float)
        slope, intercept = np.polyfit(x, y, 1)
        fit = slope * x + intercept
        ss_res = float(((y - fit) ** 2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum())
        r2 = round(1 - ss_res / ss_tot, 2) if ss_tot else None
        move = pct(float(s.iloc[-1]), float(s.iloc[0]))
        rows[label] = {
            "change_pct": move, "bars": len(s),
            "annualised_pct": round((np.exp(slope * 252) - 1) * 100, 1),
            "straightness_r2": r2,
            "direction": "up" if move > 2 else "down" if move < -2 else "flat",
        }
    if not rows:
        return fail("trend", ticker, "not enough history")

    short = rows.get("1m", {}).get("direction")
    long_ = rows.get("1y", {}).get("direction")
    agree = short == long_ if short and long_ else None
    reading = None
    if short and long_:
        if agree:
            reading = f"short and long term agree: both {short}"
        elif long_ == "up" and short == "down":
            reading = ("a pullback inside a longer uptrend - short term down, "
                       "1y still up")
        elif long_ == "down" and short == "up":
            reading = ("a bounce inside a longer downtrend - short term up, "
                       "1y still down")
        else:
            reading = f"short term {short}, 1y {long_}"

    return ok("trend", ticker, {
        "windows": rows, "short_vs_long_agree": agree, "reading": reading,
        "note": ("straightness_r2 is how much of the move is direction rather "
                 "than noise: 1.0 is a straight line, near 0 is chop"),
    }, source="derived")


@tool("market",
      "SUPPORT AND RESISTANCE, tested: price levels the stock has repeatedly "
      "turned at, with how many times each held versus broke and what happened "
      "next. Use when asked whether a level holds, or about bounces", derived=True)
async def levels(ticker: str, period: str = "2y", **_):
    """"It always bounces off this level" is a claim with a hit rate.

    Swing highs and lows are found first (a bar higher/lower than the five on
    either side), then clustered into zones within 2.5% of each other - traders
    do not respect a price to the cent. A zone counts as a LEVEL only if it was
    touched at least twice, because one touch is not a level, it is a turning
    point.

    For each later touch the outcome is recorded: HELD if price turned away by
    more than 3% within 15 sessions without closing through the zone, BROKE if
    it closed through. The median move after a hold is reported too, so "it
    bounces" can be weighed against how far the bounce actually went.
    """
    import numpy as np
    s = await closes(ticker, period)
    if len(s) < 120:
        return fail("levels", ticker, f"not enough history over {period}")
    v = s.values.astype(float)
    n, last = len(v), float(v[-1])

    # swing points: a local extreme against the 5 bars on each side
    k = 5
    pivots = []
    for i in range(k, n - k):
        w = v[i - k:i + k + 1]
        if v[i] == w.max():
            pivots.append((i, float(v[i]), "high"))
        elif v[i] == w.min():
            pivots.append((i, float(v[i]), "low"))
    if len(pivots) < 4:
        return empty("levels", ticker, "no clear swing points in this window")

    # cluster pivots whose prices sit within 2.5% of the running zone mean
    TOL = 0.025
    zones: list[dict] = []
    for _, price, kind in sorted(pivots, key=lambda p: p[1]):
        if zones and abs(price - zones[-1]["mean"]) / zones[-1]["mean"] <= TOL:
            z = zones[-1]
            z["prices"].append(price)
            z["mean"] = sum(z["prices"]) / len(z["prices"])
            z["kinds"].append(kind)
        else:
            zones.append({"prices": [price], "mean": price, "kinds": [kind]})

    out = []
    for z in zones:
        if len(z["prices"]) < 2:                 # one touch is not a level
            continue
        lo, hi = min(z["prices"]) * (1 - TOL / 2), max(z["prices"]) * (1 + TOL / 2)
        held, broke, moves, dates = 0, 0, [], []
        i = k
        while i < n - 1:
            if lo <= v[i] <= hi:                 # a touch
                fwd = v[i + 1:i + 16]
                if len(fwd) < 5:
                    break
                # Which side was it approached from? That decides what a break
                # even means - the same zone is support from above and
                # resistance from below.
                prior = v[max(0, i - 3)]
                from_above = prior >= z["mean"]
                # A break has to be DECISIVE and it has to stick: a close 2%
                # beyond the far side, and still beyond it at the end of the
                # window. Requiring only "dipped past the zone once" counts
                # ordinary volatility as a break, which made every level in the
                # first version look broken.
                if from_above:
                    through = bool((fwd < lo * 0.98).any()) and fwd[-1] < lo
                    away = (fwd.max() - v[i]) / v[i]
                else:
                    through = bool((fwd > hi * 1.02).any()) and fwd[-1] > hi
                    away = (v[i] - fwd.min()) / v[i]
                if through:
                    broke += 1
                    dates.append(str(s.index[i].date()))
                elif away > 0.03:
                    held += 1
                    moves.append(round(away * 100, 1))
                    dates.append(str(s.index[i].date()))
                # neither: drifted sideways. Counted as no test rather than
                # padding one side of the hit rate.
                i += 15                          # one outcome per visit, not per bar
            else:
                i += 1
        tests = held + broke
        if tests < 2:
            continue
        out.append({
            "level": round(z["mean"], 2),
            "type": "resistance" if z["mean"] > last else "support",
            "distance_pct": round((z["mean"] - last) / last * 100, 1),
            "tests": tests, "held": held, "broke": broke,
            "hold_rate_pct": round(held / tests * 100),
            "median_move_after_hold_pct": (round(float(np.median(moves)), 1)
                                           if moves else None),
            "last_tested": dates[-1] if dates else None,
        })
    if not out:
        return empty("levels", ticker, "no level was tested more than once")

    # BASELINE. "Held 86% of the time" means nothing on its own: in an uptrend
    # almost any price below the market holds. So run the identical rule at
    # random prices that are NOT levels, and report that rate alongside. The
    # event-study tool learned this the hard way - 44% looked positive until the
    # all-days baseline turned out to be 71%.
    rng = np.random.default_rng(0)
    b_held = b_broke = 0
    for idx in rng.choice(np.arange(k, n - 16), size=min(60, max(1, n - 16 - k)),
                          replace=False):
        i = int(idx)
        zlo, zhi = v[i] * (1 - TOL / 2), v[i] * (1 + TOL / 2)
        fwd = v[i + 1:i + 16]
        if len(fwd) < 5:
            continue
        from_above = v[max(0, i - 3)] >= v[i]
        if from_above:
            through = bool((fwd < zlo * 0.98).any()) and fwd[-1] < zlo
            away = (fwd.max() - v[i]) / v[i]
        else:
            through = bool((fwd > zhi * 1.02).any()) and fwd[-1] > zhi
            away = (v[i] - fwd.min()) / v[i]
        if through:
            b_broke += 1
        elif away > 0.03:
            b_held += 1
    baseline = round(b_held / (b_held + b_broke) * 100) if (b_held + b_broke) else None

    out.sort(key=lambda r: abs(r["distance_pct"]))
    near = out[0]
    reading = (f"nearest is {near['type']} at {near['level']} "
               f"({near['distance_pct']:+.1f}% away), tested {near['tests']} times, "
               f"held {near['held']}")
    if near["median_move_after_hold_pct"]:
        reading += f", median move after a hold {near['median_move_after_hold_pct']:+.1f}%"
    if baseline is not None:
        reading += (f". Baseline at non-level prices: {baseline}% - "
                    f"{'above' if near['hold_rate_pct'] > baseline else 'at or below'} it")
    return ok("levels", ticker, {
        "price": round(last, 2), "period": period,
        "levels": out[:6], "nearest": near,
        "baseline_hold_rate_pct": baseline, "reading": reading,
        "note": ("a level needs 2+ touches to count. HELD = turned away >3% within "
                 "15 sessions without closing through; BROKE = closed through. "
                 "Past hold rates are not a forecast."),
    }, source="derived")
