from __future__ import annotations
import numpy as np, pandas as pd
from ..models import Provenance, ToolFailure, ToolResult
from ..providers import yahoo


def ok(tool: str, ticker: str, data: dict, source: str = "yahoo") -> ToolResult:
    return ToolResult(tool=tool, ticker=ticker, data=data, prov=Provenance(source=source))


def empty(tool: str, ticker: str, why: str) -> ToolFailure:
    """Not an error. 'No dividend' is a fact about the company."""
    return ToolFailure(tool=tool, ticker=ticker, reason=why, kind="empty")


def fail(tool: str, ticker: str, why: str) -> ToolFailure:
    return ToolFailure(tool=tool, ticker=ticker, reason=why, kind="error")


async def closes(ticker: str, period: str = "1y") -> pd.Series:
    b = await yahoo.bars(ticker, period=period)
    if not b:
        return pd.Series(dtype=float)
    return pd.Series([x["c"] for x in b],
                     index=pd.to_datetime([x["t"] for x in b], unit="s"))


def rsi(s: pd.Series, n: int = 14) -> float | None:
    if len(s) < n + 1:
        return None
    d = s.diff().dropna()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = g.iloc[-1] / l.iloc[-1] if l.iloc[-1] else np.inf
    return round(float(100 - 100 / (1 + rs)), 1)


def pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 2) if b else 0.0
