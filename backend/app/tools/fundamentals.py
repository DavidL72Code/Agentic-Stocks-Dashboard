from __future__ import annotations
from ..providers import edgar, yahoo
from ._util import empty, fail, ok, pct
from .registry import tool


@tool("fundamentals", "quarterly revenue / net income / operating income from SEC filings")
async def income_statement(ticker: str, **_):
    rev = await edgar.concept(ticker, "revenue", limit=6)
    ni = await edgar.concept(ticker, "net_income", limit=6)
    if not rev and not ni:
        return fail("income_statement", ticker, "no SEC XBRL data (non-US filer?)")
    if all((edgar.stale_days(x) or 0) > 200 for x in (rev, ni) if x):
        return fail("income_statement", ticker, "SEC quarterly figures on file are over 200 days old")
    return ok("income_statement", ticker, {
        "quarterly_revenue": [{"end": r["end"], "usd": r["val"]} for r in rev],
        "quarterly_net_income": [{"end": r["end"], "usd": r["val"]} for r in ni],
        "note": "each row is a single ~91-day quarter, not a cumulative rollup",
    }, source="sec-edgar")


@tool("fundamentals", "P/E, forward P/E, price/book, market cap")
async def valuation_multiples(ticker: str, **_):
    q = await yahoo.quote(ticker) or {}
    d = {k: q.get(v) for k, v in {"pe_trailing": "trailingPE", "pe_forward": "forwardPE",
                                  "price_to_book": "priceToBook", "market_cap": "marketCap"}.items()}
    d = {k: v for k, v in d.items() if v is not None}
    return ok("valuation_multiples", ticker, d) if d else fail("valuation_multiples", ticker, "none available")


@tool("fundamentals", "margins, ROE, ROA - profitability quality")
async def profitability(ticker: str, **_):
    i = await yahoo.info(ticker)
    keys = {"profitMargins": "net_margin", "grossMargins": "gross_margin",
            "operatingMargins": "operating_margin", "returnOnEquity": "roe",
            "returnOnAssets": "roa", "ebitdaMargins": "ebitda_margin"}
    d = {v: round(i[k] * 100, 2) for k, v in keys.items() if isinstance(i.get(k), (int, float))}
    return ok("profitability", ticker, d) if d else fail("profitability", ticker, "no margin data")


@tool("fundamentals", "revenue growth YoY and QoQ computed from SEC filings", derived=True)
async def growth_rates(ticker: str, **_):
    rev = await edgar.concept(ticker, "revenue", limit=9)
    if len(rev) < 5:
        return fail("growth_rates", ticker, "need 5+ quarters of filings")
    age = edgar.stale_days(rev)
    if age is not None and age > 200:
        return fail("growth_rates", ticker,
                    f"newest quarterly revenue in SEC filings ends {rev[-1]['end']} - too old to describe current growth")
    # matched by date: a missing quarter must not turn "a year ago" into five
    # quarters ago
    ya, qb = edgar.year_ago(rev), edgar.quarter_before(rev)
    if not ya:
        return fail("growth_rates", ticker, "no quarter on file from a year earlier")
    out = {"latest_quarter_end": rev[-1]["end"], "latest_revenue_usd": rev[-1]["val"],
           "yoy_pct": pct(rev[-1]["val"], ya["val"])}
    if qb:
        out["qoq_pct"] = pct(rev[-1]["val"], qb["val"])
        prev_i = rev.index(qb)
        ya2 = edgar.year_ago(rev, prev_i)
        if ya2:
            out["yoy_pct_prior_quarter"] = pct(qb["val"], ya2["val"])
            out["growth_accelerating"] = out["yoy_pct"] > out["yoy_pct_prior_quarter"]
    return ok("growth_rates", ticker, out, source="sec-edgar+derived")


@tool("fundamentals", "debt/equity, current ratio, cash - balance sheet risk")
async def leverage_liquidity(ticker: str, **_):
    i = await yahoo.info(ticker)
    keys = {"currentRatio": "current_ratio", "quickRatio": "quick_ratio",
            "totalCash": "total_cash", "totalDebt": "total_debt"}
    d = {v: i[k] for k, v in keys.items() if i.get(k) is not None}
    # Yahoo's debtToEquity is a PERCENT (16.97 means debt is 17% of equity).
    # Passed through raw, the agent wrote "a debt-to-equity ratio of 16.97" for
    # a balance sheet holding more cash than debt. Give it both readings, named.
    de = i.get("debtToEquity")
    if isinstance(de, (int, float)):
        d["debt_to_equity_ratio"] = round(de / 100, 2)
        d["debt_as_pct_of_equity"] = round(de, 1)
    if isinstance(d.get("total_cash"), (int, float)) and isinstance(d.get("total_debt"), (int, float)):
        d["net_cash_usd"] = d["total_cash"] - d["total_debt"]     # negative = net debt
    return ok("leverage_liquidity", ticker, d) if d else fail("leverage_liquidity", ticker, "no balance sheet data")


@tool("fundamentals", "dividend yield, payout ratio, latest payment - or that there is none")
async def dividend_economics(ticker: str, **_):
    i = await yahoo.info(ticker)
    y, payout = i.get("dividendYield"), i.get("payoutRatio")
    if not y and not i.get("lastDividendValue"):
        return empty("dividend_economics", ticker, f"{ticker} pays no dividend")
    return ok("dividend_economics", ticker, {
        "dividend_yield_pct": round(y, 2) if isinstance(y, (int, float)) else None,
        "payout_ratio_pct": round(payout * 100, 1) if isinstance(payout, (int, float)) else None,
        "last_dividend": i.get("lastDividendValue"),
    })


@tool("fundamentals", "shares outstanding and buyback/dilution trend")
async def share_count(ticker: str, **_):
    i = await yahoo.info(ticker)
    d = {k: i[k] for k in ("sharesOutstanding", "floatShares", "impliedSharesOutstanding") if i.get(k)}
    return ok("share_count", ticker, d) if d else fail("share_count", ticker, "unavailable")
