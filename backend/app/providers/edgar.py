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


def _quarterly(units: list[dict], derive_q4: bool = True) -> list[dict]:
    """Keep only ~3-month periods, dedupe by end date keeping the latest filing.

    A 10-K reports the fiscal year, not its fourth quarter, so Q4 is missing
    from the raw facts - and anything that takes "four rows back" as a year ago
    then compares against FIVE quarters back. Q4 is derived as the year minus
    the three quarters inside it, the standard EDGAR reconstruction. Not done
    for per-share values: EPS does not subtract (the share count moves).
    """
    out: dict[str, dict] = {}
    annual: dict[str, dict] = {}
    for u in units:
        s, e = u.get("start"), u.get("end")
        if not s or not e:
            continue
        span = (date.fromisoformat(e) - date.fromisoformat(s)).days
        if 350 <= span <= 380:
            a = annual.get(e)
            if a is None or u.get("filed", "") > a.get("filed", ""):
                annual[e] = {"end": e, "start": s, "val": u["val"],
                             "form": u.get("form"), "filed": u.get("filed")}
            continue
        if not (QUARTER_DAYS[0] <= span <= QUARTER_DAYS[1]):
            continue                              # <-- the double-counting guard
        prev = out.get(e)
        if prev is None or u.get("filed", "") > prev.get("filed", ""):
            out[e] = {"end": e, "start": s, "val": u["val"],
                      "form": u.get("form"), "filed": u.get("filed"), "days": span}
    if derive_q4:
        for e, a in annual.items():
            if e in out:
                continue
            inside = [q for q in out.values() if a["start"] <= q["start"] and q["end"] < e]
            if len(inside) != 3:
                continue
            last = max(q["end"] for q in inside)
            out[e] = {"end": e, "start": last, "val": a["val"] - sum(q["val"] for q in inside),
                      "form": a["form"], "filed": a["filed"],
                      "days": (date.fromisoformat(e) - date.fromisoformat(last)).days,
                      "derived": "fiscal year less three reported quarters"}
    return sorted(out.values(), key=lambda r: r["end"])


def year_ago(rows: list[dict], i: int = -1) -> dict | None:
    """The row ~one year before rows[i], matched by DATE, never by position."""
    end = date.fromisoformat(rows[i]["end"])
    for r in rows:
        if abs((end - date.fromisoformat(r["end"])).days - 365) <= 20:
            return r
    return None


def quarter_before(rows: list[dict], i: int = -1) -> dict | None:
    end = date.fromisoformat(rows[i]["end"])
    for r in rows:
        if 75 <= (end - date.fromisoformat(r["end"])).days <= 105:
            return r
    return None


async def concept(ticker: str, metric: str, limit: int = 8) -> list[dict]:
    cik = await cik_for(ticker)
    if cik is None:
        return []
    async def load() -> list[dict]:
        # Issuers MOVE between tags. Microsoft reported `Revenues` until about
        # 2010 and RevenueFromContract... since, so taking the first tag with
        # any data handed the agent 2010 revenue as "the latest quarter" - and
        # it compared GOOGL's 2026 growth with MSFT's 2010 growth. Fetch every
        # candidate and keep the series that is CURRENT; list order only
        # breaks a tie.
        async def one(tag: str) -> list[dict]:
            try:
                js = await _get(CONCEPT.format(cik=cik, tag=tag))
            except Exception:
                return []
            usd = js.get("units", {}).get("USD")
            units = usd or js.get("units", {}).get("USD/shares")
            q = _quarterly(units, derive_q4=bool(usd)) if units else []
            for r in q: r["tag"] = tag
            return q
        tags = TAGS.get(metric, [metric])
        series = [q for q in await asyncio.gather(*(one(t) for t in tags)) if q]
        if not series:
            return []
        newest = max(q[-1]["end"] for q in series)
        return next(q for q in series if q[-1]["end"] == newest)
    val, _ = await cached(("edgar", ticker.upper(), metric, "v3"), 86400, load)
    return val[-limit:]


def stale_days(rows: list[dict]) -> int | None:
    """How old the newest quarter is. A 10-Q lands within ~45 days of quarter
    end, so anything past ~200 days means the issuer stopped using this tag or
    stopped filing - a number from it is history, not the current picture."""
    if not rows:
        return None
    return (date.today() - date.fromisoformat(rows[-1]["end"])).days


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
