"""The two architectures this app replaced, kept runnable for comparison.

DESIGN.md argued twice that a change was better. An argument is not a
measurement, so both predecessors are rebuilt here over the SAME tools and the
SAME model. Only the agent structure differs.

  react  - the original Colab shape. One agent per tool, looping
           think -> act -> observe until it decides it is done.
  flat   - one agent per tool, single shot. No loop, no tool choice:
           the tool is fixed, so the LLM call is pure phrasing.
  domain - what ships. One agent per DOMAIN, choosing 2-4 of ~9 tools
           and reasoning over all results together.

The hypothesis the whole redesign rests on: `flat` and `react` cannot form
conjunctions, because each agent sees exactly one tool's output. If they score
anywhere near `domain` on conjunction rate, the architecture was not worth it.
"""
from __future__ import annotations
import asyncio, json, time
from .. import llm
from ..models import DomainFinding, RunStep, ToolFailure, ToolResult
from ..tools import TOOLS, domain_tools

MAX_REACT_STEPS = 3

FLAT_PROMPT = """You are a specialist analyst. You have exactly one tool and its
result is below. Write ONE clear, factual sentence answering the question using
that data. Never invent a number.
Reply with ONLY JSON: {"finding": "..."}"""

REACT_PROMPT = """You are a specialist analyst with ONE tool: {tool}.
{desc}

You work in a think-act-observe loop. Given the question and what you have
observed so far, decide what to do next.

Reply with ONLY JSON, one of:
  {{"thought": "...", "action": "call_tool", "args": {{}}}}
  {{"thought": "...", "action": "answer", "finding": "one factual sentence"}}

Call the tool again only if the previous call failed and retrying could help."""


async def _call_tool(name: str, ticker: str, **kw):
    try:
        return await TOOLS[name].fn(ticker, **kw)
    except Exception as e:
        return ToolFailure(tool=name, ticker=ticker,
                           reason=f"{type(e).__name__}: {e}", kind="error")


async def run_flat(question: str, ticker: str, tools: list[str]):
    """One agent per tool, single shot. The LLM call is pure phrasing - there is
    no decision left to make, which was the argument for removing it."""
    findings, steps = [], []

    async def one(name: str):
        t0 = time.time()
        r = await _call_tool(name, ticker)
        if not isinstance(r, ToolResult):
            return None, RunStep(node=f"flat.{name}", detail="no data",
                                 latency_ms=int((time.time()-t0)*1000))
        try:
            reply = await llm.call(FLAT_PROMPT,
                json.dumps({"question": question, "ticker": ticker,
                            "tool": name, "result": r.data}, default=str)[:6000])
            text = (llm.parse_json(reply.text) or {}).get("finding") or reply.text
            tok, ms = reply.tokens, reply.latency_ms
        except Exception:
            text, tok, ms = json.dumps(r.data, default=str)[:200], 0, 0
        return (DomainFinding(domain=name, ticker=ticker, narrative=text.strip(),
                              evidence=[r], tools_used=[name], tokens=tok, latency_ms=ms),
                RunStep(node=f"flat.{name}", detail="1 tool", tools=1,
                        tokens=tok, latency_ms=ms, llm=tok > 0))

    for f, s in await asyncio.gather(*(one(t) for t in tools)):
        if f:
            findings.append(f)
        steps.append(s)
    return findings, steps


async def run_react(question: str, ticker: str, tools: list[str]):
    """The original shape: each one-tool agent loops until it answers."""
    findings, steps = [], []

    async def one(name: str):
        obs, tok_total, calls = [], 0, 0
        t0 = time.time()
        for _ in range(MAX_REACT_STEPS):
            try:
                reply = await llm.call(
                    REACT_PROMPT.format(tool=name, desc=TOOLS[name].desc),
                    json.dumps({"question": question, "ticker": ticker,
                                "observations": obs}, default=str)[:6000])
                calls += 1
                tok_total += reply.tokens
                j = llm.parse_json(reply.text) or {}
            except Exception:
                break
            if j.get("action") == "call_tool":
                r = await _call_tool(name, ticker)
                obs.append(r.data if isinstance(r, ToolResult)
                           else {"error": getattr(r, "reason", "no data")})
                continue
            if j.get("finding"):
                ev = [ToolResult(tool=name, ticker=ticker, data=o,
                                 prov=__import__("app.models", fromlist=["Provenance"]).Provenance(source="react"))
                      for o in obs if isinstance(o, dict) and "error" not in o]
                return (DomainFinding(domain=name, ticker=ticker,
                                      narrative=str(j["finding"]).strip(), evidence=ev,
                                      tools_used=[name], tokens=tok_total),
                        RunStep(node=f"react.{name}", detail=f"{calls} loop step(s)",
                                tools=len(obs), tokens=tok_total,
                                latency_ms=int((time.time()-t0)*1000), llm=True))
        return None, RunStep(node=f"react.{name}", detail=f"gave up after {calls} step(s)",
                             tokens=tok_total, latency_ms=int((time.time()-t0)*1000),
                             llm=calls > 0)

    for f, s in await asyncio.gather(*(one(t) for t in tools)):
        if f:
            findings.append(f)
        steps.append(s)
    return findings, steps


def tools_for(domains: list[str]) -> list[str]:
    """The tool set a flat/react run gets: every tool in the domains the router
    would have picked. That is the fair comparison - same evidence available."""
    out = []
    for d in domains:
        out += [t.name for t in domain_tools(d)]
    return out
