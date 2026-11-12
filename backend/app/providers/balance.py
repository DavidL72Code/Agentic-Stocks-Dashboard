"""How much a company owes, what it holds, and whether the business pays its own
way - the numbers investors check first when a stock is falling and borrowing
costs are rising.

    debt        loans and bonds: short-term + long-term debt (leases excluded;
                Yahoo's "total debt" adds them, which is why its Oracle figure
                is $169B against $125B of borrowing)
    cash        cash and short-term investments
    net_debt    debt - cash (negative: more cash than debt)
    free_cash_flow_12m   operating cash flow - capital spending, last 4 quarters
    interest_cover       operating profit / interest expense, last 4 quarters:
                how many times over the business earns its interest bill.
                Under 1 means it does not earn enough to pay it.

Source: Nasdaq's standardized quarterly statements (one set of line items for
every company, the same figures as the 10-Q/10-K), each value linked to the SEC
filing for that quarter. Falls back to computing from the filings' XBRL
directly (edgar.leverage) when Nasdaq is unavailable.
"""
from __future__ import annotations
import asyncio, logging
from datetime import date

log = logging.getLogger("provider.balance")


def _row(tbl: dict, *names: str) -> list:
    for n in names:
        if n in (tbl.get("rows") or {}):
            return tbl["rows"][n]
    return []


def _sum4(vals: list) -> float | None:
    v = [x for x in vals[:4] if x is not None]
    return sum(v) if len(v) == 4 else None


async def debt_and_cash(symbol: str) -> dict:
    from . import edgar, nasdaq
    # 400: insider-trade Form 4s crowd the recent list, and CoreWeave's 10-Q
    # was not among its last 40 filings
    st, fil, rows = await asyncio.gather(nasdaq.statements(symbol), edgar.filings(symbol, 400),
                                         nasdaq.screener_rows())
    sector = next((r.get("sector") for r in rows if r["symbol"] == symbol.upper()), "")
    bal, cf, inc = st.get("balance") or {}, st.get("cashflow") or {}, st.get("income") or {}
    ends = bal.get("ends") or []
    if not ends or not ends[0]:
        sec = await edgar.leverage(symbol)
        return {**sec, "source": "sec"} if sec else {}

    first = lambda r: (r[0] if r else None)
    cash_eq = first(_row(bal, "Cash and Cash Equivalents"))
    sti = first(_row(bal, "Short-Term Investments"))
    st_debt = first(_row(bal, "Short-Term Debt / Current Portion of Long-Term Debt"))
    lt_debt = first(_row(bal, "Long-Term Debt"))
    equity = first(_row(bal, "Total Equity"))
    if cash_eq is None and lt_debt is None and st_debt is None:
        sec = await edgar.leverage(symbol)
        return {**sec, "source": "sec"} if sec else {}

    cash = (cash_eq or 0) + (sti or 0)
    debt = (st_debt or 0) + (lt_debt or 0)
    out: dict = {"as_of": ends[0], "cash": cash, "debt": debt, "net_debt": debt - cash,
                 "parts": {k: v for k, v in (("cash and equivalents", cash_eq),
                                             ("short-term investments", sti),
                                             ("debt due within a year", st_debt),
                                             ("long-term debt", lt_debt)) if v is not None},
                 "source": "nasdaq"}
    if equity and equity > 0:
        out["debt_to_equity"] = round(debt / equity, 2)

    cf_ends = cf.get("ends") or []
    ocf = _sum4(_row(cf, "Net Cash Flow-Operating"))
    capex = _sum4(_row(cf, "Capital Expenditures"))          # negative: money spent
    if ocf is not None and cf_ends and cf_ends[0] == ends[0]:
        out["operating_cash_flow_12m"] = ocf
        out["cash_flow_period_end"] = cf_ends[0]
        if capex is not None:
            out["capex_12m"] = -capex
            out["free_cash_flow_12m"] = ocf + capex
    oi = _sum4(_row(inc, "Operating Income"))
    ie = _sum4(_row(inc, "Interest Expense"))
    if oi is not None:
        out["operating_income_12m"] = oi
    if ie is not None and ie > 0:
        out["interest_expense_12m"] = ie
        if oi is not None:
            out["interest_cover"] = round(oi / ie, 2)

    # the filing to check it against: the first 10-Q/10-K filed after the quarter closed
    q_end = date.fromisoformat(ends[0])
    match = sorted((f for f in fil if f.get("form") in ("10-Q", "10-K", "10-Q/A", "10-K/A")
                    and f.get("date") and 0 <= (date.fromisoformat(f["date"]) - q_end).days <= 120),
                   key=lambda f: f["date"])
    if match:
        out["filings"] = [{"form": match[0]["form"], "end": ends[0], "filed": match[0]["date"],
                           "url": match[0]["url"]}]
    if (date.today() - q_end).days > 200:
        out["stale"] = True
    if sector == "Finance":
        # For a bank, "debt" is mostly deposits and borrowing is the business;
        # interest is its cost of funds, not a bill the business struggles to
        # cover (JPM came out at 0.86x). These measures mislead here.
        out["financial"] = True
        for k in ("net_debt", "interest_cover", "free_cash_flow_12m", "debt_to_equity"):
            out.pop(k, None)
    return out
