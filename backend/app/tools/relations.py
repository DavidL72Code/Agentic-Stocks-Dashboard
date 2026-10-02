"""Read-across between tickers.

Governing rule: MEASURE the relationship in code, EXPLAIN it with the LLM.
Asked cold, a model will confidently say a good APLD print is bullish for IREN
because both are AI-datacentre names. Measured, that is not what happens.

Two traps this module handles, both found empirically:
  1. earnings_dates returns several rows per reaction day -> dedupe on the
     normalised date, or the sample is inflated and the stats are wrong.
  2. a co-direction hit rate is meaningless without the all-days BASELINE.
     44% looks like a weak positive until you know baseline co-movement is 71%,
     at which point it is a negative result.
"""
from __future__ import annotations
from math import comb
import numpy as np, pandas as pd
from ..providers import yahoo
from ._util import closes, empty, fail, ok, pct
from .registry import tool

# No fixed proxy list. Candidates are discovered from the issuer's OWN stated
# sector and industry via symbol search, then ranked by measured correlation.


# Leveraged / inverse products track the sector but are not a proxy for it -
# their returns are a multiple of it, so correlation alone would happily pick one.
LEVERED = ("ultra", "2x", "3x", "inverse", "short", "bear", "bull", "daily",
           "leveraged", "-1x", "proshares ultra")


def _is_levered(name: str) -> bool:
    n = (name or "").lower()
    return any(w in n for w in LEVERED)


async def resolve_proxy(ticker: str) -> dict | None:
    """Find what this ticker actually trades with - discovered, never declared.

    1. ask the issuer its own sector / industry (yfinance .info)
    2. search those phrases for ETFs, discard leveraged and inverse products
    3. rank survivors by realised correlation; accept only a genuine tracker
    4. if no ETF qualifies, fall back to the ticker's OWN peer cohort, which is
       itself discovered per-ticker - so every path is data, not a table

    A ticker in a sector this code has never seen resolves the same way.
    """
    info = await yahoo.info(ticker)
    sector, industry = info.get("sector") or "", info.get("industry") or ""

    cands: dict[str, str] = {}
    for term in [t for t in (industry, sector, f"{sector} sector" if sector else "") if t]:
        for r in await yahoo.search(term):
            if r.get("type") != "ETF":
                continue
            sym, nm = r["symbol"], r.get("name", "")
            if sym.upper() == ticker.upper() or _is_levered(nm):
                continue
            cands.setdefault(sym, nm)

    scored = []
    for c in list(cands)[:10]:
        r = await _aligned(ticker, c, "1y")
        if len(r) >= 60:
            scored.append({"etf": c, "name": cands[c],
                           "correlation": round(float(r["a"].corr(r["b"])), 2)})
    scored.sort(key=lambda d: -d["correlation"])

    if scored and scored[0]["correlation"] >= 0.5:
        best = scored[0]
        return {"kind": "etf", "etf": best["etf"], "name": best["name"],
                "correlation": best["correlation"], "sector": sector,
                "industry": industry, "candidates": scored[:5]}

    # no ETF tracks it well enough - use the names that actually move with it
    cohort = await yahoo.peers(ticker)
    if not cohort:
        return None
    ranked = []
    for c in cohort:
        r = await _aligned(ticker, c, "1y")
        if len(r) >= 60:
            ranked.append({"peer": c, "correlation": round(float(r["a"].corr(r["b"])), 2)})
    if not ranked:
        return None
    ranked.sort(key=lambda d: -d["correlation"])
    return {"kind": "cohort", "cohort": [r["peer"] for r in ranked[:3]],
            "correlation": ranked[0]["correlation"], "sector": sector,
            "industry": industry, "candidates": ranked[:5],
            "rejected_etfs": scored[:3]}


async def _aligned(a: str, b: str, period: str = "2y") -> pd.DataFrame:
    sa, sb = await closes(a, period), await closes(b, period)
    if sa.empty or sb.empty:
        return pd.DataFrame()
    df = pd.concat([sa.rename("a"), sb.rename("b")], axis=1).dropna()
    return df.pct_change().dropna()


@tool("relations", "return correlation and beta between two tickers", derived=True)
async def correlation(ticker: str, other: str = "SPY", period: str = "2y", **_):
    r = await _aligned(ticker, other, period)
    if len(r) < 60:
        return fail("correlation", ticker, f"not enough overlapping history with {other}")
    return ok("correlation", ticker, {
        "other": other.upper(), "period": period, "observations": len(r),
        "correlation": round(float(r["a"].corr(r["b"])), 2),
        "beta_to_other": round(float(np.polyfit(r["b"], r["a"], 1)[0]), 2),
        "co_direction_pct_all_days": round(float(((r["a"] > 0) == (r["b"] > 0)).mean() * 100), 1),
    }, source="derived")


@tool("relations", "discover this ticker's peers and rank them by how closely they actually trade together", derived=True)
async def peer_set(ticker: str, candidates: list[str] | None = None, **_):
    if not candidates:
        candidates = await yahoo.peers(ticker)          # Yahoo's cohort, then ranked by behaviour
    if not candidates:
        info = await yahoo.info(ticker)
        return empty("peer_set", ticker,
                     f"no peer cohort found for {ticker} ({info.get('industry') or 'unknown industry'})")
    scored = []
    for c in candidates:
        if c.upper() == ticker.upper():
            continue
        r = await _aligned(ticker, c)
        if len(r) >= 60:
            scored.append({"ticker": c.upper(),
                           "correlation": round(float(r["a"].corr(r["b"])), 2),
                           "observations": len(r)})
    if not scored:
        return fail("peer_set", ticker, "no candidate had enough overlapping history")
    scored.sort(key=lambda d: -d["correlation"])
    return ok("peer_set", ticker, {"peers_by_correlation": scored}, source="derived")


@tool("relations",
      "READ-ACROSS: does `other` actually move when `ticker` reports earnings? "
      "Compares earnings-day co-movement against the all-days baseline and reports significance",
      derived=True)
async def event_study(ticker: str, other: str, **_):
    r = await _aligned(ticker, other)
    if len(r) < 120:
        return fail("event_study", ticker, f"not enough overlapping history with {other}")

    raw = await yahoo.attr(ticker, "earnings_dates", ttl=21600) or {}
    if not raw:
        return empty("event_study", ticker, "no earnings dates on record")

    # TRAP 1: dedupe multiple rows per announcement day.
    # TRAP 3 (off-by-one): bars are indexed from unix timestamps, i.e. naive UTC
    # (midnight ET -> 04:00 UTC). Comparing a raw index against a normalised
    # date therefore matches the announcement day's OWN bar. Normalise both
    # sides to calendar dates before comparing, or you measure the session
    # BEFORE the reaction.
    anns = {}
    for k in raw:
        ts = pd.Timestamp(str(k))
        hour = ts.hour
        ts = ts.tz_localize(None) if ts.tz is not None else ts
        # after the close (>=16:00) -> reaction is the NEXT session;
        # before the open (<09:30) -> reaction is the SAME session.
        anns[ts.normalize()] = "next" if hour >= 16 or hour == 0 else "same"

    idx = r.index.tz_localize(None) if r.index.tz is not None else r.index
    dates = idx.normalize()

    rows, seen = [], set()
    for d in sorted(anns):
        if anns[d] == "same":
            cand = idx[dates == d]
        else:
            cand = idx[dates > d]
        if len(cand) == 0:
            continue
        day = cand[0]
        if day in seen:
            continue
        seen.add(day)
        pos = int(idx.get_loc(day))
        rows.append({"date": str(pd.Timestamp(day).date()),
                     "source_move_pct": round(float(r["a"].iloc[pos] * 100), 2),
                     "peer_move_pct": round(float(r["b"].iloc[pos] * 100), 2)})
    if len(rows) < 3:
        return empty("event_study", ticker, "fewer than 3 usable earnings reactions")

    e = pd.DataFrame(rows)
    n = len(e)
    same = int(((e.source_move_pct > 0) == (e.peer_move_pct > 0)).sum())
    # TRAP 2: the baseline this must be judged against
    base = float(((r["a"] > 0) == (r["b"] > 0)).mean())
    big = e[e.source_move_pct.abs() > 3]
    capture = float((big.peer_move_pct / big.source_move_pct).median()) if len(big) else None
    # one-sided binomial vs the baseline
    p = sum(comb(n, i) * base**i * (1 - base)**(n - i) for i in range(0, same + 1))

    return ok("event_study", ticker, {
        "source": ticker.upper(), "peer": other.upper(),
        "events": rows,
        "n_events": n,
        "peer_same_direction": f"{same}/{n}",
        "peer_same_direction_pct": round(same / n * 100, 1),
        "baseline_same_direction_pct": round(base * 100, 1),
        "beats_baseline": (same / n) > base,
        "median_capture_of_move": round(capture, 2) if capture is not None else None,
        "capture_sample": len(big),
        "binomial_p_one_sided": round(p, 3),
        "significant_at_05": p < 0.05,
        "verdict": ("read-across NOT supported: peer moves with the source LESS often on "
                    "earnings days than on an average day"
                    if (same / n) <= base else
                    "peer does move with the source on earnings days"),
        "caution": f"n={n} events. Treat as suggestive unless significant_at_05 is true.",
    }, source="derived")


@tool("relations", "which sector ETF this ticker actually tracks, discovered and measured", derived=True)
async def sector_proxy(ticker: str, **_):
    res = await resolve_proxy(ticker)
    if not res:
        return empty("sector_proxy", ticker, "nothing tracked this ticker closely enough")
    return ok("sector_proxy", ticker, {
        "resolved_as": res["kind"],
        "closest": res.get("etf") or ", ".join(res.get("cohort", [])),
        "correlation": res["correlation"],
        "sector": res["sector"], "industry": res["industry"],
        "tracks": res["candidates"][:5],
        "note": ("ETF proxy: searched the issuer's own industry, dropped leveraged and "
                 "inverse products, ranked by realised correlation"
                 if res["kind"] == "etf" else
                 "no ETF correlated >=0.5, so the ticker's own discovered peer cohort "
                 "is used instead")}, source="derived")


@tool("relations",
      "PEER PERFORMANCE, SIZE-ADJUSTED: return over a window against each peer, "
      "with market cap, beta and a beta-adjusted excess return. Use this for ANY "
      "question about how a stock is performing - a raw return is not comparable "
      "across names of different size and volatility", derived=True)
async def peer_performance(ticker: str, period: str = "1y", **_):
    """Why a raw return comparison is not a fair one.

    Share price and splits are irrelevant here - a percentage return is already
    split-adjusted, so a 10-for-1 split changes nothing. What does make two
    returns incomparable is BETA: a name that moves 1.9x the market will beat a
    1.1x name in any rising market without management doing anything right. So
    alongside the raw return this reports beta and the beta-adjusted excess:

        excess = stock_return - beta * market_return

    which is what is left after the market move it was always going to get.
    Market cap comes too, because "outperformed its peers" means something
    different for a $5T company than a $200B one.
    """
    cohort = await yahoo.peers(ticker)
    if not cohort:
        return empty("peer_performance", ticker, "no peer cohort found")

    sym = ticker.upper()
    names = [sym] + [c.upper() for c in cohort]
    series = {}
    for s in names + ["SPY"]:
        c = await closes(s, period)
        if len(c) > 40:
            series[s] = c
    if sym not in series or "SPY" not in series:
        return fail("peer_performance", ticker, f"insufficient history over {period}")

    spy = series["SPY"]
    mkt_ret = pct(float(spy.iloc[-1]), float(spy.iloc[0]))
    spy_r = spy.pct_change().dropna()
    caps = await yahoo.quotes(names)

    def measure(s: str) -> dict | None:
        c = series.get(s)
        if c is None:
            return None
        ret = pct(float(c.iloc[-1]), float(c.iloc[0]))
        r = c.pct_change().dropna()
        j = r.to_frame("a").join(spy_r.to_frame("b"), how="inner").dropna()
        beta = None
        if len(j) > 40 and j["b"].var():
            beta = round(float(j["a"].cov(j["b"]) / j["b"].var()), 2)
        vol = round(float(r.std() * (252 ** 0.5) * 100), 1) if len(r) > 40 else None
        row = {"ticker": s, "return_pct": ret, "beta_vs_spy": beta,
               "volatility_pct": vol,
               "market_cap": (caps.get(s) or {}).get("marketCap"),
               "name": (caps.get(s) or {}).get("shortName")}
        # what is left after the market move this beta was always going to give
        if beta is not None:
            row["beta_adjusted_excess_pct"] = round(ret - beta * mkt_ret, 2)
        # return per unit of risk taken to get it
        if vol:
            row["return_per_vol"] = round(ret / vol, 2)
        return row

    me = measure(sym)
    rows = [r for s in names[1:] if (r := measure(s))]
    if not rows:
        return empty("peer_performance", ticker, "no peer history to compare against")

    def med(key):
        vals = sorted(r[key] for r in rows if r.get(key) is not None)
        if not vals:
            return None
        n = len(vals)
        return round(vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2, 2)

    coh = {"median_return_pct": med("return_pct"), "median_beta": med("beta_vs_spy"),
           "median_excess_pct": med("beta_adjusted_excess_pct"),
           "median_market_cap": med("market_cap"), "peers_measured": len(rows)}

    out = {"ticker": sym, "period": period, "market_return_pct": mkt_ret,
           "subject": me, "peers": sorted(rows, key=lambda r: -(r["return_pct"] or 0)),
           "cohort": coh,
           "note": ("a raw return is not comparable between names of different beta; "
                    "beta_adjusted_excess_pct is the part not explained by the market "
                    "move. Share price level and stock splits do not affect any of "
                    "these figures - returns are split-adjusted.")}

    # the honest one-line reading, computed not narrated
    if me and coh["median_return_pct"] is not None:
        gap = round(me["return_pct"] - coh["median_return_pct"], 2)
        bits = [f"{sym} returned {me['return_pct']:+.1f}% over {period} vs a peer "
                f"median of {coh['median_return_pct']:+.1f}%"]
        if me.get("beta_vs_spy") and coh["median_beta"]:
            bits.append(f"on a beta of {me['beta_vs_spy']} against the cohort's "
                        f"{coh['median_beta']}")
        if me.get("beta_adjusted_excess_pct") is not None \
                and coh["median_excess_pct"] is not None:
            adj = round(me["beta_adjusted_excess_pct"] - coh["median_excess_pct"], 2)
            bits.append(f"which leaves {adj:+.1f}pts once the market move each beta "
                        f"implies is removed (raw gap {gap:+.1f}pts)")
        out["reading"] = "; ".join(bits)
    return ok("peer_performance", ticker, out, source="derived")


@tool("relations",
      "ADJACENT MOVES: how this ticker's peers traded today, and whether it is moving "
      "with them or breaking away from the group", derived=True)
async def peer_moves(ticker: str, **_):
    cohort = await yahoo.peers(ticker)
    if not cohort:
        return empty("peer_moves", ticker, "no peer cohort found")
    q = await yahoo.quotes([ticker] + cohort)
    me = q.get(ticker.upper()) or {}
    my = me.get("regularMarketChangePercent")
    rows = []
    for c in cohort:
        r = q.get(c.upper()) or {}
        if r.get("regularMarketChangePercent") is None:
            continue
        rows.append({"ticker": c.upper(), "name": r.get("shortName"),
                     "change_pct": round(r["regularMarketChangePercent"], 2),
                     "price": r.get("regularMarketPrice")})
    if not rows:
        return empty("peer_moves", ticker, "no peer quotes available")
    avg = sum(r["change_pct"] for r in rows) / len(rows)
    rows.sort(key=lambda r: -abs(r["change_pct"]))
    out = {"ticker": ticker.upper(), "ticker_change_pct": round(my, 2) if my is not None else None,
           "peer_average_pct": round(avg, 2), "peers": rows,
           "biggest_mover": rows[0]}
    if my is not None:
        gap = my - avg
        out["gap_vs_peers_pct"] = round(gap, 2)
        out["reading"] = ("moving with the group" if abs(gap) < 1
                          else f"outperforming its group by {gap:.1f}pts" if gap > 0
                          else f"lagging its group by {abs(gap):.1f}pts")
    return ok("peer_moves", ticker, out, source="derived")


@tool("relations",
      "READ-ACROSS: for each peer, how often this ticker moves with it, how much of the "
      "peer's move it historically captures, and whether the peer's earnings actually "
      "transmit. Answers 'peer X did something - does that matter for me?'", derived=True)
async def read_across(ticker: str, other: str = "", limit: int = 4, **_):
    cohort = [other.upper()] if other else (await yahoo.peers(ticker))[:limit]
    if not cohort:
        return empty("read_across", ticker, "no peer cohort found")
    q = await yahoo.quotes([ticker] + cohort)
    rows = []
    for c in cohort:
        r = await _aligned(ticker, c)
        if len(r) < 60:
            continue
        corr = float(r["a"].corr(r["b"]))
        beta = float(np.polyfit(r["b"], r["a"], 1)[0])
        co = float(((r["a"] > 0) == (r["b"] > 0)).mean() * 100)
        big = r[r["b"].abs() > 0.03]
        capture = float((big["a"] / big["b"]).median()) if len(big) > 4 else None
        pq = q.get(c.upper()) or {}
        rows.append({
            "peer": c.upper(), "peer_name": pq.get("shortName"),
            "peer_change_today_pct": round(pq.get("regularMarketChangePercent"), 2)
                if pq.get("regularMarketChangePercent") is not None else None,
            "correlation": round(corr, 2),
            "co_direction_pct": round(co, 1),
            "beta_to_peer": round(beta, 2),
            "median_capture_of_big_moves": round(capture, 2) if capture is not None else None,
            "observations": len(r),
        })
    if not rows:
        return fail("read_across", ticker, "not enough overlapping history with any peer")
    rows.sort(key=lambda d: -d["correlation"])
    strongest = rows[0]
    return ok("read_across", ticker, {
        "ticker": ticker.upper(), "peers": rows, "strongest_link": strongest,
        "how_to_read": ("co_direction_pct is the share of ALL days the pair moves the same way - "
                        "the baseline any single event must beat. median_capture is how much of a "
                        ">3% peer move this ticker historically follows: near 0 means peer news "
                        "does NOT transmit, near 1 means it moves one-for-one."),
        "caution": "these are statistical associations over ~2y of daily returns, not causation",
    }, source="derived")
