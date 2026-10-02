"""The domain subgraph: select -> gather -> synthesize.

This is where the multi-agent part actually lives. Each domain agent:
  - sees ONLY its own tool catalog and its own sub-question
  - decides for itself which 2-4 tools to run (the 84-way choice, not 149k-way)
  - reasons over ALL its results at once, so it can form conjunctions
    ("near highs on thin volume") that a one-tool agent structurally cannot
  - never sees any other domain's evidence
"""
from __future__ import annotations
import asyncio, json, time
from langgraph.graph import END, START, StateGraph
from typing import Any, TypedDict

from .. import llm
from ..models import DomainFinding, RunStep, ToolFailure, ToolResult
from ..tools import DOMAIN_DESC, TOOLS, catalog, domain_tools
from .present import present

SELECT_PROMPT = """You pick tools for the {domain} specialist.
{domain} covers: {desc}

Available tools:
{catalog}

Pick ONLY the tools needed to answer the question. Fewer is better - 2 to 4 is
typical. Do not pick a tool whose data cannot possibly bear on the question
(e.g. quarterly ownership data cannot explain a single day's move).

Reply with ONLY JSON:
{{"tools": ["name", ...], "reason_skipped": "one short sentence on what you left out and why"}}"""

SYNTH_PROMPT = """You are the {domain} specialist. You cover ONLY: {desc}
You are given every tool result you asked for, together.

Write 1-3 sentences answering the question.

THE HARD LIMIT: use at most FOUR figures in the whole answer, and never more
than two in one sentence. You will be shown far more than four. Choosing which
ones carry the answer is the job - quoting all of them is not analysis, it is
transcription.

What to say:
- Look for CONJUNCTIONS across your tools. A relationship between two results
  beats restating each ("near its 52-week high but on below-average volume").
  This is why you get every result at once.
- Lead with the point, then the figure that supports it.
- If a tool says the data does not exist (no dividend, no filings), say so
  plainly. That is information, not a failure.
- Never invent a number. Only use figures you were shown.
- If the question asks about the OUTLOOK, ground it in what you were given: the
  next earnings date and expected EPS, the beat/miss record, the direction of
  margins and growth, leverage. Say what would change it. Never forecast a
  price, never say buy, sell or hold.
- No investment advice. Factual only.

How to write it:
- Short sentences. Aim for 20 words; never more than 30.
- Quote figures as you were shown them: "$96.2B", not "$96,221,000,000".
- No throat-clearing. Not "It is worth noting that", not "The data shows that".

WORKED EXAMPLE - the same evidence, written badly then well.

Evidence: price $230.86, change_pct 1.1, volume 97.5M, avg_volume_20d 112.9M,
ratio 0.87, high_52w $236.54, pct_below_high 2.4, position_in_range_pct 92.1

BAD (8 figures, one 45-word sentence - every number correct, unreadable):
"NVDA advanced 1.1% to $230.86 on volume of 97.5M against a 20-day average of
112.9M for a ratio of 0.87, while sitting 2.4% below its 52-week high of
$236.54 at the 92.1st percentile of its range."

GOOD (3 figures, two sentences, and it makes a POINT the numbers alone do not):
"NVDA is 2.4% off its 52-week high after rising 1.1%. It got there on
below-average volume - 0.87x its 20-day norm - so the move lacks conviction."

Reply with ONLY JSON: {{"finding": "..."}}"""


class DState(TypedDict, total=False):
    domain: str
    ticker: str
    question: str
    tools: list[str]
    args: dict
    selected: list[str]
    skipped: list[str]
    skip_reason: str
    results: list
    steps: list
    finding: DomainFinding


def build_domain(domain: str):
    desc = DOMAIN_DESC[domain]
    names = [t.name for t in domain_tools(domain)]

    async def select(s: DState) -> dict:
        # fast path: router already named the tools, or only a few exist
        pre = [t for t in (s.get("tools") or []) if t in names]
        if pre:
            return {"selected": pre, "skipped": [n for n in names if n not in pre],
                    "skip_reason": "named by router", "steps": [
                        RunStep(node=f"{domain}.select", detail="router-named",
                                tools=len(pre), llm=False)]}
        t0 = time.time()
        try:
            r = await llm.call(
                SELECT_PROMPT.format(domain=domain, desc=desc, catalog=catalog(domain)),
                f"Ticker: {s['ticker']}\nQuestion: {s['question']}", fast=True)
            j = llm.parse_json(r.text) or {}
            sel = [t for t in j.get("tools", []) if t in names][:5]
            reason = str(j.get("reason_skipped", ""))[:240]
            tok, ms = r.tokens, r.latency_ms
        except Exception as e:
            sel, reason, tok, ms = names[:3], f"selector unavailable ({type(e).__name__}); used defaults", 0, 0
        if not sel:
            sel = names[:3]
        return {"selected": sel, "skipped": [n for n in names if n not in sel],
                "skip_reason": reason,
                "steps": [RunStep(node=f"{domain}.select", detail=reason[:80],
                                  tools=len(sel), tokens=tok,
                                  latency_ms=ms or int((time.time() - t0) * 1000),
                                  llm=tok > 0)]}

    async def gather(s: DState) -> dict:
        t0 = time.time()
        args = s.get("args") or {}
        async def run(name: str):
            try:
                return await TOOLS[name].fn(s["ticker"], **args)
            except Exception as e:
                return ToolFailure(tool=name, ticker=s["ticker"],
                                   reason=f"{type(e).__name__}: {e}", kind="error")
        res = await asyncio.gather(*(run(n) for n in s["selected"]))
        return {"results": list(res),
                "steps": [RunStep(node=f"{domain}.gather",
                                  detail=f"{sum(1 for r in res if isinstance(r, ToolResult))}/{len(res)} returned data",
                                  tools=len(res), latency_ms=int((time.time() - t0) * 1000))]}

    async def synthesize(s: DState) -> dict:
        res = s.get("results") or []
        okr = [r for r in res if isinstance(r, ToolResult)]
        bad = [r for r in res if isinstance(r, ToolFailure)]
        # The model sees rounded, human-unit values; the DTOs keep full
        # precision for the grounding check.
        payload = {
            "question": s["question"], "ticker": s["ticker"],
            "tool_results": {r.tool: present(r.data) for r in okr},
            "tools_with_no_data": {f.tool: f.reason for f in bad},
        }
        conf = "high" if okr and not bad else "partial" if okr else "unavailable"
        if not okr:
            note = "; ".join(f.reason for f in bad) or "no data available"
            return {"finding": DomainFinding(
                domain=domain, ticker=s["ticker"],
                narrative=f"No {domain} data available for {s['ticker']}: {note}.",
                evidence=[], failures=bad, tools_used=[], tools_skipped=s.get("skipped", []),
                skip_reason=s.get("skip_reason", ""), confidence="unavailable"),
                "steps": [RunStep(node=f"{domain}.synthesize", detail="skipped - no data")]}
        try:
            r = await llm.call(SYNTH_PROMPT.format(domain=domain, desc=desc),
                               json.dumps(payload, default=str)[:12000])
            j = llm.parse_json(r.text) or {}
            text = str(j.get("finding") or r.text).strip()
            tok, ms = r.tokens, r.latency_ms
        except Exception as e:
            text = "; ".join(f"{r.tool}: {json.dumps(r.data, default=str)[:160]}" for r in okr)
            tok, ms = 0, 0
        return {"finding": DomainFinding(
                    domain=domain, ticker=s["ticker"], narrative=text, evidence=okr,
                    failures=bad, tools_used=[r.tool for r in okr],
                    tools_skipped=s.get("skipped", []), skip_reason=s.get("skip_reason", ""),
                    confidence=conf, tokens=tok, latency_ms=ms),
                "steps": [RunStep(node=f"{domain}.synthesize", detail=f"{len(okr)} results",
                                  tokens=tok, latency_ms=ms, llm=tok > 0)]}

    g = StateGraph(DState)
    g.add_node("select", select); g.add_node("gather", gather); g.add_node("synthesize", synthesize)
    g.add_edge(START, "select"); g.add_edge("select", "gather")
    g.add_edge("gather", "synthesize"); g.add_edge("synthesize", END)
    return g.compile()


SUBGRAPHS = {d: build_domain(d) for d in DOMAIN_DESC}
