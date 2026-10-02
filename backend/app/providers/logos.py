"""Company logos.

Primary: Financial Modeling Prep's public stock-image CDN - keyed by TICKER,
so no domain lookup is needed (measured ~250px for most US names, vs 16px for
AMD's favicon). Falls back to favicon services via the issuer's website, then
to a generated monogram so a tile is never empty.
"""
from __future__ import annotations
import hashlib, logging
from urllib.parse import urlparse
import httpx
from ..cache import cached
from . import yahoo

log = logging.getLogger("provider.logos")
FMP = "https://financialmodelingprep.com/image-stock/{sym}.png"
BY_DOMAIN = ["https://icons.duckduckgo.com/ip3/{d}.ico",
             "https://www.google.com/s2/favicons?domain={d}&sz=256"]
PALETTE = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444",
           "#8b5cf6", "#ec4899", "#14b8a6", "#f97316", "#84cc16"]
MIN_BYTES = 700          # smaller than this is a placeholder glyph, not a logo


def monogram(symbol: str) -> bytes:
    h = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
    c = PALETTE[h % len(PALETTE)]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{c}" stop-opacity=".95"/>'
            f'<stop offset="1" stop-color="{c}" stop-opacity=".55"/></linearGradient></defs>'
            f'<rect width="64" height="64" rx="15" fill="url(#g)"/>'
            f'<text x="32" y="41" font-family="Inter,system-ui,sans-serif" font-size="23" '
            f'font-weight="650" fill="#fff" text-anchor="middle" letter-spacing="-.5">'
            f'{symbol[:2].upper()}</text></svg>').encode()


async def _try(c: httpx.AsyncClient, url: str) -> tuple[bytes, str] | None:
    try:
        r = await c.get(url)
        ct = r.headers.get("content-type", "")
        if r.status_code == 200 and len(r.content) > MIN_BYTES and "image" in ct:
            return r.content, ct
    except Exception as e:
        log.debug("logo %s failed: %s", url, e)
    return None


async def fetch(symbol: str) -> tuple[bytes, str]:
    sym = symbol.upper()

    async def load() -> tuple[bytes, str]:
        async with httpx.AsyncClient(timeout=9, follow_redirects=True) as c:
            hit = await _try(c, FMP.format(sym=sym))
            if hit:
                return hit
            # fallback path needs a domain, which costs an .info call - only now
            try:
                site = (await yahoo.info(sym)).get("website") or ""
                host = (urlparse(site if "//" in site else f"//{site}").netloc or site)
                host = host.replace("www.", "").strip("/")
            except Exception:
                host = ""
            if host:
                for tpl in BY_DOMAIN:
                    hit = await _try(c, tpl.format(d=host))
                    if hit:
                        return hit
        return monogram(sym), "image/svg+xml"

    val, _ = await cached(("logo", sym), 86400 * 7, load)
    return val
