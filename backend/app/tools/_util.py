from __future__ import annotations
import numpy as np, pandas as pd
from ..models import Provenance, ToolFailure, ToolResult
from ..providers import yahoo


def ok(tool: str, ticker: str, data: dict, source: str = "yahoo",
       url: str | None = None, label: str | None = None) -> ToolResult:
    """A successful result, with where it came from as a link a reader can open.
    A tool that knows the exact page (an SEC filing) passes it; the rest are
    resolved from the tool and the provider that actually answered."""
    from .sources import source_for
    lab, link = source_for(tool, ticker, source)
    return ToolResult(tool=tool, ticker=ticker, data=data,
                      prov=Provenance(source=source, label=label or lab, url=url or link))


def empty(tool: str, ticker: str, why: str) -> ToolFailure:
    """Not an error. 'No dividend' is a fact about the company."""
    return ToolFailure(tool=tool, ticker=ticker, reason=why, kind="empty")


def fail(tool: str, ticker: str, why: str) -> ToolFailure:
    return ToolFailure(tool=tool, ticker=ticker, reason=why, kind="error")


# a window is measured back from the LAST BAR, so fetch a longer one and trim
WINDOW = {"1mo": pd.DateOffset(months=1), "3mo": pd.DateOffset(months=3), "6mo": pd.DateOffset(months=6),
          "1y": pd.DateOffset(years=1), "2y": pd.DateOffset(years=2), "5y": pd.DateOffset(years=5)}
FETCH = {"1mo": "3mo", "3mo": "6mo", "6mo": "1y", "1y": "2y", "2y": "5y", "5y": "10y", "ytd": "1y"}


def window_start(index: pd.DatetimeIndex, period: str):
    """The bar a return over `period` is measured from: the last close on or
    before (last bar - period), or for year-to-date last year's final close -
    the bases quote pages use.

    Yahoo's own windows count back from NOW in UTC: after 8pm New York time the
    "1y" window drops a day, and NVDA's one-year return jumped from 19.5% to
    25.5% between afternoon and evening (Oct 9 2025 closed at 192.11, Oct 10 at
    182.72). Its "ytd" opens on the year's first trading day, so it drops that
    day's move (NVDA 21.8% vs the 23.3% Yahoo Finance shows)."""
    if not len(index):
        return None
    last = index[-1].normalize()
    if period == "ytd":
        cut = pd.Timestamp(year=last.year, month=1, day=1)
        before = index[index < cut]
    elif period in WINDOW:
        cut = last - WINDOW[period]
        before = index[index.normalize() <= cut]
    else:
        return index[0]
    return before[-1] if len(before) else index[0]


async def closes(ticker: str, period: str = "1y") -> pd.Series:
    """Daily closes over `period`, anchored as window_start() describes."""
    b = await yahoo.bars(ticker, period=FETCH.get(period, period))
    if not b:
        return pd.Series(dtype=float)
    s = pd.Series([x["c"] for x in b],
                  index=pd.to_datetime([x["t"] for x in b], unit="s"))
    start = window_start(s.index, period)
    return s[s.index >= start] if start is not None else s


def rsi(s: pd.Series, n: int = 14) -> float | None:
    if len(s) < n + 1:
        return None
    d = s.diff().dropna()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = g.iloc[-1] / l.iloc[-1] if l.iloc[-1] else np.inf
    return round(float(100 - 100 / (1 + rs)), 1)


def pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 4) if b else 0.0
