"""Tool registry. A tool is a plain async fn + metadata - never an agent.

Roughly half of these hit no API at all: they are arithmetic over bars the
cache already holds (RSI, MAs, vol, beta, drawdown, correlation, event study).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from ..models import ToolFailure, ToolResult

Fn = Callable[..., Awaitable[ToolResult | ToolFailure]]


@dataclass
class Tool:
    name: str
    domain: str
    desc: str
    fn: Fn
    derived: bool = False        # True = computed locally, costs no upstream call


TOOLS: dict[str, Tool] = {}


def tool(domain: str, desc: str, derived: bool = False):
    def wrap(fn: Fn) -> Fn:
        TOOLS[fn.__name__] = Tool(fn.__name__, domain, desc, fn, derived)
        return fn
    return wrap


def domain_tools(domain: str) -> list[Tool]:
    return [t for t in TOOLS.values() if t.domain == domain]


def catalog(domain: str) -> str:
    return "\n".join(f"- {t.name}: {t.desc}" for t in domain_tools(domain))


DOMAIN_DESC = {
    "market": "price action, technicals, volume, 52-week range, relative strength",
    "fundamentals": "financial statements, valuation multiples, margins, growth, leverage, dividends",
    "street": "news, analyst ratings and changes, price targets, ownership, insiders, short interest",
    "events": "earnings dates and surprise history, ex-dividend dates, SEC filings",
    "relations": ("how this ticker relates to OTHER tickers: peers, correlation, "
                  "read-across from one name's news to another, and SIZE-ADJUSTED "
                  "PEER PERFORMANCE. Include this for any question about how a stock "
                  "is performing or doing: a return means little without the peer "
                  "cohort's return and a beta adjustment, since a high-beta name "
                  "beats a low-beta one in any rising market on its own."),
    "macro": ("the market backdrop: index levels, rates, volatility, Fed and policy news, "
              "geopolitics, and sector-level spillover. Use when the question is about WHY "
              "the market or a sector moved rather than one company."),
    "portfolio": ("the USER'S OWN holdings: positions, cost basis, unrealised and daily P&L, "
                  "concentration, correlation between holdings, portfolio beta. Use this for any "
                  "question about 'my portfolio', 'my holdings', 'my book' or 'what I own'. "
                  "Ticker is irrelevant here - pass PORTFOLIO."),
}
