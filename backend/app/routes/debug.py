"""TEMPORARY: diagnose why Yahoo returns nothing from Render.

Hits each step yfinance takes - cookie, crumb, v7 quote, quoteSummary, v8 chart -
and reports the status code and a short body snippet for each, plus what the
app's own code path raises. No secrets in or out. The result is cached for 60s
so the endpoint cannot be used to hammer Yahoo. Delete once the cause is known.
"""
from __future__ import annotations
import asyncio, time

from fastapi import APIRouter

router = APIRouter(prefix="/api/debug")
_last: tuple[float, dict] | None = None


def _probe() -> dict:
    from curl_cffi import requests as cr
    import yfinance as yf
    from ..providers import yahoo

    out: dict = {"yfinance": yf.__version__}
    s = cr.Session(impersonate="chrome")

    def step(name, url, **kw):
        t = time.time()
        try:
            r = s.get(url, timeout=15, allow_redirects=True, **kw)
            out[name] = {"status": r.status_code, "ms": int((time.time() - t) * 1000),
                         "body": r.text[:160].replace("\n", " ")}
            return r
        except Exception as e:
            out[name] = {"error": f"{type(e).__name__}: {e}"[:200]}
            return None

    step("1_cookie_fc", "https://fc.yahoo.com")
    out["1_cookie_names"] = sorted(s.cookies.keys())
    r = step("2_crumb", "https://query1.finance.yahoo.com/v1/test/getcrumb")
    crumb = r.text.strip() if r is not None and r.status_code == 200 else ""
    q = {"symbols": "NVDA", "crumb": crumb} if crumb else {"symbols": "NVDA"}
    step("3_v7_quote", "https://query2.finance.yahoo.com/v7/finance/quote", params=q)
    step("4_quoteSummary", "https://query2.finance.yahoo.com/v10/finance/quoteSummary/NVDA",
         params={"modules": "price", **({"crumb": crumb} if crumb else {})})
    step("5_v8_chart", "https://query2.finance.yahoo.com/v8/finance/chart/NVDA",
         params={"range": "5d", "interval": "1d"})

    # Nasdaq's site API: candidate source for price targets (no key, no daily cap)
    nh = {"Accept": "application/json", "Origin": "https://www.nasdaq.com",
          "Referer": "https://www.nasdaq.com/"}
    step("8_nasdaq_targetprice", "https://api.nasdaq.com/api/analyst/NVDA/targetprice", headers=nh)
    step("9_nasdaq_ratings", "https://api.nasdaq.com/api/analyst/NVDA/ratings", headers=nh)

    # the app's real code paths, exceptions included
    try:
        out["6_app_quotes"] = {"rows": len(yahoo._quotes_blocking(["NVDA"]))}
    except Exception as e:
        out["6_app_quotes"] = {"error": f"{type(e).__name__}: {e}"[:300]}
    try:
        out["7_app_info"] = {"keys": len(yf.Ticker("NVDA").info or {})}
    except Exception as e:
        out["7_app_info"] = {"error": f"{type(e).__name__}: {e}"[:300]}
    return out


@router.get("/yahoo")
async def yahoo_probe():
    global _last
    if _last and time.time() - _last[0] < 60:
        return {"cached": True, **_last[1]}
    res = await asyncio.to_thread(_probe)
    _last = (time.time(), res)
    return res
