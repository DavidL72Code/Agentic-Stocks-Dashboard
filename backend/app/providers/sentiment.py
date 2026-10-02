"""CNN Fear & Greed index.

CNN's dataviz endpoint returns 418 to a bare client - it needs browser-ish
headers. Free, no key, and it ships a year of daily history for the sparkline.
"""
from __future__ import annotations
import logging
import httpx
from ..cache import cached

log = logging.getLogger("provider.sentiment")
URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://edition.cnn.com/",
    "Origin": "https://edition.cnn.com",
    "Accept-Language": "en-US,en;q=0.9",
}
# CNN's own bands
BANDS = [(25, "extreme fear"), (45, "fear"), (55, "neutral"), (75, "greed"), (101, "extreme greed")]


def band(score: float) -> str:
    for hi, name in BANDS:
        if score < hi:
            return name
    return "extreme greed"


async def fear_greed() -> dict | None:
    async def load() -> dict:
        async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as c:
            r = await c.get(URL)
            r.raise_for_status()
            js = r.json()
        f = js.get("fear_and_greed") or {}
        hist = (js.get("fear_and_greed_historical") or {}).get("data") or []
        score = f.get("score")
        return {
            "score": round(score, 1) if score is not None else None,
            "rating": f.get("rating") or (band(score) if score is not None else None),
            "previous_close": round(f.get("previous_close", 0), 1) or None,
            "week_ago": round(f.get("previous_1_week", 0), 1) or None,
            "month_ago": round(f.get("previous_1_month", 0), 1) or None,
            "year_ago": round(f.get("previous_1_year", 0), 1) or None,
            "history": [round(h["y"], 1) for h in hist[-60:] if h.get("y") is not None],
            "as_of": f.get("timestamp"),
        }
    try:
        val, _ = await cached(("fng",), 1800, load)
        return val
    except Exception as e:
        log.warning("fear & greed unavailable: %s", e)
        return None
