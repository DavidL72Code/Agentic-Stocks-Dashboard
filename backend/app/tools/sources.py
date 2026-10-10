"""Where each figure came from, as a page a reader can open.

Every ToolResult carries a source name; this turns (tool, ticker, provider)
into a human label and a URL - the exact SEC filing, the Yahoo Finance page the
quote or statistics are shown on, the Nasdaq page, the article. Derived numbers
(RSI, moving averages, correlations, event studies) say they were computed here
and link to the price history they were computed FROM.

Honesty rule: the link names the provider that actually answered. On Render
Yahoo refuses its crumb and company metrics come from Finnhub instead, so the
label says Finnhub there and links that endpoint's documentation - not a Yahoo
page whose numbers might not match.
"""
from __future__ import annotations
from urllib.parse import quote as _q

YF = "https://finance.yahoo.com/quote/{t}/"
NQ = "https://www.nasdaq.com/market-activity/stocks/{t}"
FINNHUB_METRICS = "https://finnhub.io/docs/api/company-basic-financials"
FINNHUB_RECS = "https://finnhub.io/docs/api/recommendation-trends"
SEC_COMPANY = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=40"
CNN_FG = "https://www.cnn.com/markets/fear-and-greed"
SCREENER = "https://www.nasdaq.com/market-activity/stocks/screener"

# which provider answered yahoo.info()/attr() for a symbol, set by providers.yahoo
INFO_SRC: dict[str, str] = {}
TARGETS_SRC: dict[str, str] = {}
RECS_SRC: dict[str, str] = {}

PRICE = {"quote", "range_52w"}
HISTORY = {"price_series", "moving_averages", "rsi_momentum", "volatility", "volume_profile",
           "drawdown", "relative_strength"}
INFO_TOOLS = {"profitability", "leverage_liquidity", "dividend_economics", "share_count",
              "ex_dividend", "short_interest"}
COMPUTED = {"correlation", "event_study", "peer_performance", "peer_moves", "read_across",
            "sector_proxy"}


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")


def long_date(iso: str) -> str:
    """'2026-07-26' -> 'July 26th 2026', the way the app writes dates everywhere."""
    y, m, d = (int(x) for x in str(iso)[:10].split("-"))
    suf = "th" if 11 <= d % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
    return f"{MONTHS[m - 1]} {d}{suf} {y}"


def yf(t: str, page: str = "") -> str:
    return YF.format(t=_q(t, safe="")) + page


def source_for(tool: str, ticker: str, source: str = "") -> tuple[str, str | None]:
    """(label, url) for one tool's result."""
    t = (ticker or "").upper()
    if tool in PRICE:
        return f"Yahoo Finance · {t} quote", yf(t)
    if tool in HISTORY:
        return f"Yahoo Finance · {t} price history (indicator computed here)", yf(t, "history/")
    if tool == "valuation_multiples":
        return f"Yahoo Finance · {t} summary (market cap, P/E)", yf(t)
    if tool in INFO_TOOLS:
        if INFO_SRC.get(t) == "finnhub":
            return f"Finnhub · {t} company metrics", FINNHUB_METRICS
        return (f"Yahoo Finance · {t} statistics" + (" (gross margin = Gross Profit ÷ Revenue, ttm)"
                if tool == "profitability" else "")), yf(t, "key-statistics/")
    if tool == "analyst_ratings":
        if RECS_SRC.get(t) == "finnhub" or INFO_SRC.get(t) == "finnhub":
            return f"Finnhub · {t} analyst recommendation trends", FINNHUB_RECS
        return f"Yahoo Finance · {t} analyst ratings", yf(t, "analysis/")
    if tool == "price_targets":
        if TARGETS_SRC.get(t) == "nasdaq":
            return f"Nasdaq · {t} analyst price target", NQ.format(t=t.lower()) + "/price-target"
        return f"Yahoo Finance · {t} analyst price targets", yf(t, "analysis/")
    if tool == "rating_changes":
        return f"Yahoo Finance · {t} upgrades and downgrades", yf(t, "analysis/")
    if tool == "institutional_holders":
        return f"Yahoo Finance · {t} holders", yf(t, "holders/")
    if tool == "insider_transactions":
        return f"Yahoo Finance · {t} insider transactions", yf(t, "insider-transactions/")
    if tool in ("news", "news_history"):
        return f"Yahoo Finance · {t} news (each headline links its article)", yf(t, "news/")
    if tool in ("next_earnings", "earnings_surprise_history"):
        return f"Yahoo Finance · {t} earnings", yf(t, "analysis/")
    if tool == "recent_filings":
        return f"SEC EDGAR · {t} filings", f"https://www.sec.gov/edgar/browse/?CIK={_q(t)}"
    if tool == "peer_set":
        return f"Yahoo Finance · people also watch, for {t}", yf(t)
    if tool in COMPUTED:
        return f"Computed here from Yahoo Finance price history · {t}", yf(t, "history/")
    if tool == "index_levels":
        return "Yahoo Finance · S&P 500, Nasdaq, 10-year, VIX", yf("^GSPC")
    if tool in ("market_news", "sector_news"):
        return "Yahoo Finance · market news (each headline links its article)", "https://finance.yahoo.com/topic/stock-market-news/"
    if tool in ("screen_stocks", "cap_movers"):
        return "Nasdaq stock screener, enriched with Yahoo Finance statistics", SCREENER
    if tool in ("positions", "day_pnl", "concentration", "correlation_matrix", "portfolio_beta"):
        return "Your holdings in Monsoon, priced from Yahoo Finance", None
    return (source or "data") + (f" · {t}" if t else ""), None


def sec_filing_url(cik: int | None, accn: str | None) -> str | None:
    """The filing's index page on EDGAR - every document in it, as filed."""
    if not cik or not accn:
        return None
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/{accn}-index.htm"


def sec_doc_url(cik: int | None, accn: str | None, doc: str | None) -> str | None:
    if not cik or not accn or not doc:
        return sec_filing_url(cik, accn)
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/{doc}"
