from __future__ import annotations
import operator
from typing import Annotated, Any, TypedDict
from ..models import DomainFinding, RunStep


def merge_findings(a: list, b: list) -> list:
    return (a or []) + (b or [])


class Task(TypedDict):
    id: str
    domain: str
    ticker: str
    question: str
    tools: list[str]          # optional pre-named tools from the router
    args: dict[str, Any]


class ResearchState(TypedDict, total=False):
    question: str
    history: list[dict]       # prior turns {q, a, tickers}, oldest first
    context: list[str]        # tickers on screen: a hint, not a constraint
    resolved: str             # the question rewritten to stand alone, from route
    degraded: str             # set when the router failed and we fell back
    selection: list[str]      # tickers the user explicitly picked
    tickers: list[str]
    tasks: list[Task]
    findings: Annotated[list[DomainFinding], merge_findings]
    steps: Annotated[list[RunStep], merge_findings]
    answer: str
    round: int                # 0 = first wave; review bumps it to cap follow-ups at one
    followups: list[Task]
    refused: str
