"""SEC EDGAR XBRL - the only source here with a real API contract.

Handles the trap that bites everyone: one filing reports the SAME tag at
multiple period lengths (NVDA's 2026-08-26 10-Q carries both $177.8B for six
months and $96.2B for the quarter). Filtering on end-start is mandatory or you
silently report double revenue.
"""
from __future__ import annotations
import asyncio, logging, os
from .. import http
from datetime import date, timedelta
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
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "eps": ["EarningsPerShareDiluted"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    # Issuers differ on which of these they file, so try them all - the
    # current-series rule in concept() picks the right one.
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding",
                       "WeightedAverageNumberOfDilutedSharesOutstandingAdjustment",
                       "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
                       "WeightedAverageNumberOfSharesOutstandingBasic",
                       "CommonStockSharesOutstanding", "CommonStockSharesIssued"],
}


def split_adjust(rows: list[dict]) -> tuple[list[dict], float | None]:
    """Rescale a share-count series across stock splits.

    A 10-for-1 split multiplies the reported count by ten overnight. Comparing
    across it says NVDA "diluted 872%" when it was actually buying back - the
    exact trap that makes raw share counts untrustworthy. Any step of 1.5x or
    more between consecutive filings is treated as a split and everything
    before it is rescaled onto the later basis.
    """
    if len(rows) < 2:
        return rows, None
    out = [dict(r) for r in rows]
    ratio_total = 1.0
    for i in range(len(out) - 1, 0, -1):
        a, b = out[i - 1]["val"], out[i]["val"]
        if not a or not b:
            continue
        r = b / a
        if r >= 1.5 or r <= 0.67:
            for j in range(i):
                out[j]["val"] = out[j]["val"] * r
                out[j]["split_adjusted"] = True
            ratio_total *= r
    return out, (round(ratio_total, 2) if ratio_total != 1.0 else None)
QUARTER_DAYS = (80, 100)     # a 10-Q period is ~91 days; reject 6/9/12-month rollups


async def _get(url: str) -> Any:
    async with http.shared("sec", timeout=25, headers={"User-Agent": UA}) as c:
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
                             "form": u.get("form"), "filed": u.get("filed"), "accn": u.get("accn")}
            continue
        if not (QUARTER_DAYS[0] <= span <= QUARTER_DAYS[1]):
            continue                              # <-- the double-counting guard
        prev = out.get(e)
        if prev is None or u.get("filed", "") > prev.get("filed", ""):
            out[e] = {"end": e, "start": s, "val": u["val"],
                      "form": u.get("form"), "filed": u.get("filed"), "days": span,
                      "accn": u.get("accn")}
    if derive_q4:
        for e, a in annual.items():
            if e in out:
                continue
            inside = [q for q in out.values() if a["start"] <= q["start"] and q["end"] < e]
            if len(inside) != 3:
                continue
            last = max(q["end"] for q in inside)
            out[e] = {"end": e, "start": last, "val": a["val"] - sum(q["val"] for q in inside),
                      "form": a["form"], "filed": a["filed"], "accn": a.get("accn"),
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
            # "shares" was missing, so every share-count tag came back empty and
            # dilution was unmeasurable. Share counts are also a LEVEL, not a
            # flow, so no Q4 is derived from them by subtraction.
            shares = js.get("units", {}).get("shares")
            units = usd or js.get("units", {}).get("USD/shares") or shares
            q = _quarterly(units, derive_q4=bool(usd)) if units else []
            for r in q: r["tag"] = tag; r["cik"] = cik
            return q
        tags = TAGS.get(metric, [metric])
        series = [q for q in await asyncio.gather(*(one(t) for t in tags)) if q]
        if not series:
            return []
        newest = max(q[-1]["end"] for q in series)
        current = [q for q in series if q[-1]["end"] == newest]
        # Two tags can both be current. APLD files `Revenues` for 2 recent
        # quarters and RevenueFromContract... for all 8: list order picked the
        # 2-quarter series, and 6 of 8 quarters - and the TTM margins - came
        # back empty. Prefer the series covering more of the last two years;
        # max() keeps list order for a tie.
        cutoff = (date.fromisoformat(newest) - timedelta(days=800)).isoformat()
        return max(current, key=lambda q: sum(1 for r in q if r["end"] >= cutoff))
    val, _ = await cached(("edgar", ticker.upper(), metric, "v5"), 86400, load)
    return val[-limit:]


def stale_days(rows: list[dict]) -> int | None:
    """How old the newest quarter is. A 10-Q lands within ~45 days of quarter
    end, so anything past ~200 days means the issuer stopped using this tag or
    stopped filing - a number from it is history, not the current picture."""
    if not rows:
        return None
    return (date.today() - date.fromisoformat(rows[-1]["end"])).days


async def ttm(ticker: str) -> dict | None:
    """The last twelve months, added up from the last four quarterly filings.

    Quote pages disagree on "ttm" margins - NVDA, Oct 2026: Yahoo's "Operating
    Margin (ttm)" of 66.24% is really the latest QUARTER (63.73 / 96.22), the
    filings give 65.21% over four quarters, Finnhub 65.17%. Adding the four
    10-Q/10-K quarters ourselves gives one number, the same everywhere, that a
    reader can rebuild from the filings each row links. None when the four
    quarters aren't consecutive and current - a gap would make it 15 months.
    """
    rev, gp, oi, ni = await asyncio.gather(*(concept(ticker, m, 8) for m in
                                             ("revenue", "gross_profit", "operating_income", "net_income")))
    if len(rev) < 4 or (stale_days(rev) or 0) > 200:
        return None
    last4 = rev[-4:]
    ends = [date.fromisoformat(r["end"]) for r in last4]
    if any(not (75 <= (b - a).days <= 105) for a, b in zip(ends, ends[1:])):
        return None
    def match(rows: list[dict]) -> list[float] | None:
        by = {r["end"]: r["val"] for r in rows}
        vals = [by.get(r["end"]) for r in last4]
        return vals if all(v is not None for v in vals) else None
    g, o, n = match(gp), match(oi), match(ni)
    if g is None:                  # many issuers file cost of revenue, not gross profit
        cr = match(await concept(ticker, "cost_of_revenue", 8))
        if cr is not None:
            g = [r["val"] - c for r, c in zip(last4, cr)]
    from ..tools.sources import sec_filing_url
    quarters = []
    for i, r in enumerate(last4):
        q = {"end": r["end"], "form": r.get("form"), "filed": r.get("filed"),
             "url": sec_filing_url(r.get("cik"), r.get("accn")), "revenue": r["val"]}
        for k, v in (("gross_profit", g), ("operating_income", o), ("net_income", n)):
            if v is not None:
                q[k] = v[i]
        if r.get("derived"):
            q["derived"] = r["derived"]
        quarters.append(q)
    total = sum(r["val"] for r in last4)
    out = {"start": last4[0].get("start"), "end": last4[-1]["end"], "cik": last4[-1].get("cik"),
           "quarters": quarters, "revenue": total}
    for k, v, m in (("gross_profit", g, "gross_margin_pct"), ("operating_income", o, "operating_margin_pct"),
                    ("net_income", n, "net_margin_pct")):
        if v is not None and total:
            out[k] = sum(v)
            out[m] = round(sum(v) / total * 100, 2)
    return out


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
        from ..tools.sources import sec_doc_url
        for d, f, p, it, ac in zip(r.get("filingDate", []), r.get("form", []),
                                   r.get("primaryDocument", []), r.get("items", [""] * 10**4),
                                   r.get("accessionNumber", [""] * 10**4)):
            row = {"date": d, "form": f, "doc": p, "url": sec_doc_url(cik, ac, p)}
            reasons = [ITEMS_8K[x.strip()] for x in (it or "").split(",") if x.strip() in ITEMS_8K]
            if reasons:
                row["reasons"] = reasons
            out.append(row)
        return out          # EDGAR "recent" is up to ~1000 rows; Form 4s crowd it
    val, _ = await cached(("edgar", ticker.upper(), "filings3"), 86400, load)
    if since:
        val = [x for x in val if x["date"] >= since]
    return val[:limit]


# ════════════════ debt, cash and free cash flow, from the filings ════════════════
# Yahoo's totalDebt / totalCash / freeCashflow sit behind the crumb Render never
# gets, and Finnhub's free tier has none of them - so on the live site the three
# numbers an investor checks first when a stock is falling (how much it owes,
# what it holds, whether the business pays its own way) were blank. They come
# from the 10-Q/10-K balance sheet and cash-flow statement instead, each linked
# to its filing.
FILED_FORMS = {"10-Q", "10-K", "10-Q/A", "10-K/A"}
_SEC_SEM = asyncio.Semaphore(6)          # SEC asks for no more than 10 requests a second

LEVEL_TAGS = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "short_term_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                               "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
    "current_debt": ["DebtCurrent", "LongTermDebtCurrent",
                     "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "short_term_borrowings": ["ShortTermBorrowings", "CommercialPaper"],
    "total_debt_fallback": ["LongTermDebt"],
    "finance_leases": ["FinanceLeaseLiability"],
    "finance_leases_noncurrent": ["FinanceLeaseLiabilityNoncurrent"],
    "finance_leases_current": ["FinanceLeaseLiabilityCurrent"],
}
FLOW_TAGS = {
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities",
                            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
                         "InterestAndDebtExpense", "InterestIncomeExpenseNonoperatingNet"],
    "operating_income": ["OperatingIncomeLoss"],
}


async def _usd(cik: int, tag: str) -> list[dict]:
    async with _SEC_SEM:
        try:
            js = await _get(CONCEPT.format(cik=cik, tag=tag))
        except Exception:
            return []
    return [{**u, "tag": tag} for u in ((js.get("units") or {}).get("USD") or [])
            if u.get("form") in FILED_FORMS and u.get("end")]


def _span(u: dict) -> int:
    return (date.fromisoformat(u["end"]) - date.fromisoformat(u["start"])).days


def _instants(units: list[dict]) -> dict[str, dict]:
    """Balance-sheet values by date, the latest filing winning a restatement."""
    by: dict[str, dict] = {}
    for u in units:
        if u.get("start"):
            continue
        if u["end"] not in by or u.get("filed", "") > by[u["end"]].get("filed", ""):
            by[u["end"]] = u
    return by


def _ttm_flow(units: list[dict]) -> dict | None:
    """Twelve months of a flow from the way filings report it: a 10-Q's
    cash-flow statement is year-to-date (6 or 9 months), so the last twelve
    months are this year-to-date + the last full year - the same year-to-date
    a year earlier. Only 3-month periods were read before, so Q2 and Q3 cash
    flow never arrived and free cash flow could not be computed at all."""
    facts: dict[tuple, dict] = {}
    for u in units:
        if not u.get("start"):
            continue
        k = (u["start"], u["end"])
        if k not in facts or u.get("filed", "") > facts[k].get("filed", ""):
            facts[k] = u
    if not facts:
        return None
    latest = max(e for _, e in facts)
    cur = max((f for (s, e), f in facts.items() if e == latest), key=_span)
    sp = _span(cur)
    base = {"end": cur["end"], "accn": cur.get("accn"), "form": cur.get("form"), "tag": cur["tag"]}
    if 350 <= sp <= 380:
        return {**base, "val": cur["val"], "basis": "fiscal year"}
    start = date.fromisoformat(cur["start"])
    end = date.fromisoformat(cur["end"])
    annual = [f for f in facts.values() if 350 <= _span(f) <= 380
              and abs((start - date.fromisoformat(f["end"])).days - 1) <= 7]
    prior = [f for f in facts.values() if f is not cur and abs(_span(f) - sp) <= 10
             and abs((end - date.fromisoformat(f["end"])).days - 365) <= 20]
    if not annual or not prior:
        return None
    a = max(annual, key=lambda f: f.get("filed", ""))
    p = max(prior, key=lambda f: f.get("filed", ""))
    return {**base, "val": cur["val"] + a["val"] - p["val"],
            "basis": f"{round(sp / 30.4)} months to {cur['end']} + fiscal year to {a['end']} "
                     f"- the same {round(sp / 30.4)} months a year earlier"}


def _current(series: list[list[dict]]) -> list[dict]:
    """Of several tags for one line item, the one still being filed."""
    series = [s for s in series if s]
    if not series:
        return []
    newest = max(max(u["end"] for u in s) for s in series)
    return next(s for s in series if max(u["end"] for u in s) == newest)


async def leverage(ticker: str) -> dict:
    """Debt, cash, net debt, free cash flow and interest cover from the latest
    filings. {} when the company files no us-gaap XBRL (foreign filers, funds)."""
    cik = await cik_for(ticker)
    if cik is None:
        return {}

    async def load() -> dict:
        from ..tools.sources import sec_filing_url
        names = [(grp, tag) for grp, tags in {**LEVEL_TAGS, **FLOW_TAGS}.items() for tag in tags]
        got = await asyncio.gather(*(_usd(cik, tag) for _, tag in names))
        by_group: dict[str, list[list[dict]]] = {}
        for (grp, _), units in zip(names, got):
            by_group.setdefault(grp, []).append(units)

        # ── the balance sheet: every part read at the SAME date ──
        cash_series = _current(by_group["cash"])
        if not cash_series:
            return {}
        cash_by = _instants(cash_series)
        if not cash_by:
            return {}
        bs = max(cash_by)

        def at(group: str) -> dict | None:
            for units in by_group.get(group, []):
                hit = _instants(units).get(bs)
                if hit is not None:
                    return hit
            return None

        parts: dict[str, float] = {}
        cited: list[dict] = []

        def take(label: str, f: dict | None) -> float:
            if f is None:
                return 0.0
            parts[label] = f["val"]
            cited.append(f)
            return float(f["val"])

        cash = take("cash and equivalents", cash_by[bs])
        cash += take("short-term investments", at("short_term_investments"))
        lt, cur_d = at("long_term_debt"), at("current_debt")
        debt = 0.0
        if lt is not None or cur_d is not None:
            debt += take("long-term debt", lt)
            debt += take("debt due within a year", cur_d)
            if cur_d is None or cur_d["tag"] != "DebtCurrent":   # DebtCurrent already includes these
                debt += take("short-term borrowings", at("short_term_borrowings"))
        else:
            debt += take("debt", at("total_debt_fallback"))
        # leases count as borrowing unless the debt line already includes them
        if not (lt is not None and lt["tag"] == "LongTermDebtAndCapitalLeaseObligations"):
            fl = at("finance_leases")
            if fl is not None:
                debt += take("finance leases", fl)
            else:
                debt += take("finance leases (long-term)", at("finance_leases_noncurrent"))
                debt += take("finance leases (within a year)", at("finance_leases_current"))

        # ── twelve months of cash flow and interest ──
        flows = {g: _ttm_flow(_current(by_group[g])) for g in FLOW_TAGS}
        ocf, capex = flows["operating_cash_flow"], flows["capex"]
        out: dict[str, Any] = {"as_of": bs, "cash": cash, "debt": debt, "net_debt": debt - cash,
                               "parts": parts}
        if ocf:
            out["operating_cash_flow_12m"] = ocf["val"]
            out["cash_flow_period_end"] = ocf["end"]
            cited.append(ocf)
        if ocf and capex and capex["end"] == ocf["end"]:
            out["capex_12m"] = capex["val"]
            out["free_cash_flow_12m"] = ocf["val"] - capex["val"]
            cited.append(capex)
        ie, oi = flows["interest_expense"], flows["operating_income"]
        if ie:
            # the "net" tag is negative when it is a cost; positive means the
            # company EARNS more interest than it pays, and there is no bill to cover
            cost = -ie["val"] if ie["tag"] == "InterestIncomeExpenseNonoperatingNet" else ie["val"]
            if cost and cost > 0:
                out["interest_expense_12m"] = cost
                cited.append(ie)
                if oi and oi["end"] == ie["end"]:
                    out["operating_income_12m"] = oi["val"]
                    out["interest_cover"] = round(oi["val"] / cost, 2)
        stale = (date.today() - date.fromisoformat(bs)).days > 200
        if stale:
            out["stale"] = True
        filings = {}
        for f in cited:
            if f.get("accn") and f["accn"] not in filings:
                filings[f["accn"]] = {"form": f.get("form"), "end": f["end"],
                                      "url": sec_filing_url(cik, f["accn"])}
        out["filings"] = sorted(filings.values(), key=lambda x: x["end"], reverse=True)
        return out

    try:
        val, _ = await cached(("edgar", ticker.upper(), "leverage", "v1"), 86400, load)
        return val or {}
    except Exception as e:
        log.warning("leverage %s failed: %s", ticker, e)
        return {}
