"""SEC EDGAR XBRL - the only source here with a real API contract.

Handles the trap that bites everyone: one filing reports the SAME tag at
multiple period lengths (NVDA's 2026-08-26 10-Q carries both $177.8B for six
months and $96.2B for the quarter). Filtering on end-start is mandatory or you
silently report double revenue.
"""
from __future__ import annotations
import asyncio, logging, os
from datetime import date
from typing import Any
import httpx
from ..cache import cached

log = logging.getLogger("provider.edgar")
# SEC rejects (403) any User-Agent without an email-shaped contact.
# Set SEC_USER_AGENT to your own contact per SEC's fair-access policy.
UA = os.environ.get("SEC_USER_AGENT", "agentic-fintech/0.1 (admin@example.com)")
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
CONCEPT = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/{tag}.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# fallbacks: issuers tag the same economics differently
TAGS = {
    "revenue":  ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                 "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "gross_profit": ["GrossProfit"],
    "eps": ["EarningsPerShareDiluted"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
}
QUARTER_DAYS = (80, 100)     # a 10-Q period is ~91 days; reject 6/9/12-month rollups


async def _get(url: str) -> Any:
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": UA}) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.json()


async def cik_for(ticker: str) -> int | None:
    async def load() -> dict[str, int]:
        js = await _get(TICKERS_URL)
        return {v["ticker"].upper(): int(v["cik_str"]) for v in js.values()}
    m, _ = await cached(("edgar", "tickermap"), 86400 * 7, load)
    return m.get(ticker.upper())


def _quarterly(units: list[dict]) -> list[dict]:
    """Keep only ~3-month periods, dedupe by end date keeping the latest filing."""
    out: dict[str, dict] = {}
    for u in units:
        s, e = u.get("start"), u.get("end")
        if not s or not e:
            continue
        span = (date.fromisoformat(e) - date.fromisoformat(s)).days
        if not (QUARTER_DAYS[0] <= span <= QUARTER_DAYS[1]):
            continue                              # <-- the double-counting guard
        prev = out.get(e)
        if prev is None or u.get("filed", "") > prev.get("filed", ""):
            out[e] = {"end": e, "start": s, "val": u["val"],
                      "form": u.get("form"), "filed": u.get("filed"), "days": span}
    return sorted(out.values(), key=lambda r: r["end"])


async def concept(ticker: str, metric: str, limit: int = 8) -> list[dict]:
    cik = await cik_for(ticker)
    if cik is None:
        return []
    async def load() -> list[dict]:
        for tag in TAGS.get(metric, [metric]):
            try:
                js = await _get(CONCEPT.format(cik=cik, tag=tag))
            except Exception:
                continue
            units = js.get("units", {}).get("USD") or js.get("units", {}).get("USD/shares")
            if not units:
                continue
            q = _quarterly(units)
            if q:
                for r in q: r["tag"] = tag
                return q
        return []
    val, _ = await cached(("edgar", ticker.upper(), metric), 86400, load)
    return val[-limit:]


# Why an 8-K was filed. EDGAR lists the item numbers; these are the ones that
# can move a stock. Without them an 8-K is just "a filing happened".
ITEMS_8K = {"1.01": "material agreement", "1.02": "agreement terminated",
            "2.01": "acquisition or disposal completed", "2.02": "quarterly results",
            "2.03": "new debt obligation", "2.05": "restructuring / exit costs",
            "2.06": "impairment", "3.01": "delisting notice", "3.02": "unregistered share sale",
            "4.01": "auditor change", "4.02": "prior financials unreliable",
            "5.01": "change in control", "5.02": "executive or director change",
            "5.07": "shareholder vote", "7.01": "Reg FD disclosure", "8.01": "other material event"}


async def filings(ticker: str, limit: int = 8, since: str | None = None) -> list[dict]:
    cik = await cik_for(ticker)
    if cik is None:
        return []
    async def load() -> list[dict]:
        js = await _get(SUBMISSIONS.format(cik=cik))
        r = js.get("filings", {}).get("recent", {})
        out = []
        for d, f, p, it in zip(r.get("filingDate", []), r.get("form", []),
                               r.get("primaryDocument", []), r.get("items", [""] * 10**4)):
            row = {"date": d, "form": f, "doc": p}
            reasons = [ITEMS_8K[x.strip()] for x in (it or "").split(",") if x.strip() in ITEMS_8K]
            if reasons:
                row["reasons"] = reasons
            out.append(row)
        return out          # EDGAR "recent" is up to ~1000 rows; Form 4s crowd it
    val, _ = await cached(("edgar", ticker.upper(), "filings2"), 86400, load)
    if since:
        val = [x for x in val if x["date"] >= since]
    return val[:limit]
