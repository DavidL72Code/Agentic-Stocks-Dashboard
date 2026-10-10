"""Typed DTOs. Every record carries as_of + source so the UI can cite it,
and ToolFailure is a real type so `startswith("Error")` never happens again."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field


DISCLAIMER = ("Informational only, not financial advice. Monsoon summarises public "
              "data and cannot account for your circumstances.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Provenance(BaseModel):
    source: str
    as_of: datetime = Field(default_factory=_now)
    is_stale: bool = False
    label: str | None = None   # what a reader would call it: "SEC EDGAR · NVDA 10-Q"
    url: str | None = None     # the page the figures can be checked on


class ToolResult(BaseModel):
    """What a tool returns on success. `data` is whatever shape that tool makes."""
    tool: str
    ticker: str
    data: dict[str, Any]
    prov: Provenance

    def numbers(self) -> list[float]:
        """Every numeric leaf - used by the grounding check.

        Strings count too: a figure inside a headline ("$8.2 Billion deal") is
        evidence the agent was legitimately given, so quoting it is faithful,
        not fabrication. Omitting these made the checker flag correct answers.
        """
        import re as _re
        out: list[float] = []
        pat = _re.compile(r"-?\d[\d,]*(?:\.\d+)?")

        def walk(v: Any) -> None:
            if isinstance(v, bool):
                return
            if isinstance(v, (int, float)):
                out.append(float(v))
            elif isinstance(v, str):
                for m in pat.findall(v)[:40]:
                    try:
                        out.append(float(m.replace(",", "")))
                    except ValueError:
                        pass
            elif isinstance(v, dict):
                # "_" keys are bookkeeping (per-field sources): the digits in a
                # URL or an accession number must never ground a figure
                for k, x in v.items():
                    if not str(k).startswith("_"):
                        walk(x)
            elif isinstance(v, (list, tuple)):
                for x in v: walk(x)

        walk(self.data)
        return out


class ToolFailure(BaseModel):
    tool: str
    ticker: str
    reason: str
    kind: Literal["empty", "unavailable", "error"] = "error"

    @property
    def is_empty(self) -> bool:
        """'No dividend' is information, not a failure. The distinction matters."""
        return self.kind == "empty"


class DomainFinding(BaseModel):
    domain: str
    ticker: str
    narrative: str
    evidence: list[ToolResult] = []
    failures: list[ToolFailure] = []
    tools_used: list[str] = []
    tools_skipped: list[str] = []
    skip_reason: str = ""
    confidence: Literal["high", "partial", "unavailable"] = "high"
    tokens: int = 0
    latency_ms: int = 0


class RunStep(BaseModel):
    node: str
    detail: str = ""
    tools: int = 0
    tokens: int = 0
    latency_ms: int = 0
    llm: bool = False
    model: str = ""           # which model answered, so a fallback is visible


class AgentRun(BaseModel):
    question: str
    tickers: list[str] = []
    findings: list[DomainFinding] = []
    answer: str = ""
    steps: list[RunStep] = []
    grounded: bool | None = None
    ungrounded_numbers: list[float] = []
    # where each figure came from: the answer as text and cited-figure
    # segments, and the numbered sources those cite (see graph.build.cite)
    segments: list[dict] = []
    sources: list[dict] = []
    # charts that illustrate the cited figures, when one helps (graph.charts)
    charts: list[dict] = []
    # non-empty when the run answered from a fallback because a step failed;
    # the client shows it, so a degraded answer is never silently passed off
    # as a full one
    degraded: str = ""

    @property
    def total_tokens(self) -> int: return sum(s.tokens for s in self.steps)
    @property
    def llm_calls(self) -> int: return sum(1 for s in self.steps if s.llm)
    @property
    def latency_ms(self) -> int: return sum(s.latency_ms for s in self.steps)
