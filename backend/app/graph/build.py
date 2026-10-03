"""Top-level graph: guard -> route -> Send(domain subgraphs) -> writer."""
from __future__ import annotations
import json, os, re, time
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .. import llm
from ..models import AgentRun, RunStep
from ..providers import yahoo
from ..tools import DOMAIN_DESC, domain_tools  # imports package => registers tools
from .domains import SUBGRAPHS
from .present import present
from .quality import density_report
from .state import ResearchState, Task

DOMAIN_LIST = "\n".join(f"- {d}: {v}" for d, v in DOMAIN_DESC.items())

ROUTE_PROMPT = f"""You route stock-research questions to specialist agents.

Domains:
{DOMAIN_LIST}

Rules:
- Pick ONLY domains that bear on the question. Most questions need 1-2, not 5.
- If the question asks for an overall VIEW, TAKE, POSITION, OUTLOOK or "what do you
  think" about a ticker, that is a broad read: include `macro` alongside the
  company-level domains, because the market backdrop is part of the answer. A
  broad read typically wants market + street + fundamentals + macro.
- Fundamentals update quarterly, so they cannot explain a single day's move.
- `relations` is for questions about how one ticker affects ANOTHER (read-across,
  peers, correlation). If used, set "other" in args to the second ticker.
- If the question asks how a stock is PERFORMING or DOING, or compares it to
  another name, include `relations` alongside `market`. A return on its own is
  not an answer: the peer cohort's return and a beta adjustment are what make it
  mean anything, since a high-beta name outruns a low-beta one in any rising
  market without doing anything well.
- `macro` needs NO ticker. For a question about the market as a whole - "why is
  everything down", "what moved markets today", rates, the Fed, jobs, policy -
  emit a single macro task with "ticker": "MARKET".
- Write each sub-question standalone - the specialist never sees the original.
- If the question names a time window ("over six months", "this year", "since
  March"), set "period" in EVERY task's args to the closest of: 1mo, 3mo, 6mo,
  ytd, 1y, 2y, 5y. Tools default to other windows, so leaving it out silently
  answers a different question.

Reply with ONLY JSON:
{{"tickers": ["AAPL"],
  "tasks": [{{"domain": "market", "ticker": "AAPL", "question": "...", "args": {{}}}}]}}

If the question is not about markets, companies or investing, reply:
{{"refuse": "one sentence saying what you can help with instead"}}"""

WRITER_PROMPT = """You write the final answer from specialist findings.

You get each specialist's narrative AND its raw evidence numbers. Use both:
the narratives for framing, the numbers for cross-domain relationships the
individual specialists could not see (none of them saw each other's data).

Rules:
- Never state a number that is not in the evidence.
- Prefer a cross-domain observation if the evidence supports one.
- If a specialist reports data is unavailable, say so plainly. Do not guess.
- 2-5 sentences. Plain prose, no headers.

How to write it:
- Short sentences. Aim for 20 words, never more than 30. If a sentence needs an
  "and" plus a "while", it is two sentences.
- At most two figures in any one sentence. A reader cannot hold more than that,
  and a wall of numbers is unreadable even when every number is correct.
- Lead with the point, then the number that supports it. Write "margins are
  expanding - up to 54.2% from 51.7%", not "operating margin of 54.2% versus a
  prior 51.7% indicates expansion".
- Drop figures that do not change the conclusion. Precision you do not use is
  noise: "$96.2B" beats "$96,221,000,000".


When the question asks for a VIEW, TAKE or POSITION on a ticker, answer it as a
balanced read of the evidence, not a recommendation:
- say what the data supports AND what cuts against it - both sides, from the
  evidence you were given
- name what the market appears to be pricing (valuation vs growth, positioning,
  the macro backdrop) rather than what someone should do
- end with what would change the picture - the next datapoint that matters
- NEVER say buy, sell, hold, accumulate, trim, overweight, underweight, or give
  a price target of your own. You summarise evidence; you do not advise.

Reply with ONLY JSON: {"answer": "..."}"""

POLISH_PROMPT = """You are the editor. One specialist has already done the
analysis. Your job is to make it read well - NOT to redo it.

Keep:
- the specialist's point, in its order and emphasis
- its voice. It is a domain specialist, not a generalist summariser
- every figure it used, and no others

Change only the prose:
- Break any sentence over 30 words into two.
- At most two figures per sentence. Move the rest into a second sentence or cut
  them if they do not change the point.
- Lead with the point, then its supporting number.
- Round readable: "$96.2B" not "$96,221,000,000".
- Remove throat-clearing ("It is worth noting that", "The data shows that").

Do not add analysis, caveats, context or recommendations the specialist did not
make. Do not introduce a number that is not already in its text. If it already
reads well, return it close to unchanged.

Reply with ONLY JSON: {"answer": "..."}"""


# Questions that cannot be answered honestly without a peer comparison.
# "how is it trading" is included; "what is the price" deliberately is not -
# that is a lookup, not a judgement about performance.
PERF_RE = re.compile(
    r"\b(perform\w*|doing|compare[sd]?|comparison|versus|vs\.?|against|"
    r"out ?perform\w*|under ?perform\w*|beat\w*|lag\w*|better|worse|"
    r"relative|trailing|ahead of|behind)\b", re.I)

TICKER_RE = re.compile(r"\b[A-Z]{1,5}\b")

# The window the user asked about, read from their words. Backs up the router,
# which sometimes leaves args.period out - tools then fall back to their own
# defaults (1y, 3mo) and the answer drifts to a window nobody asked for.
_NUMW = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "nine": 9,
         "twelve": 12, "a": 1}
_WIN = re.compile(r"\b(\d+|one|two|three|four|five|six|nine|twelve|a)[\s-]*(day|week|month|year)s?\b", re.I)


def question_period(q: str) -> str | None:
    t = q.lower()
    if re.search(r"\b(ytd|year[\s-]to[\s-]date|this year|so far this year)\b", t):
        return "ytd"
    if re.search(r"\b(this|last|past) quarter\b", t):
        return "3mo"
    m = _WIN.search(t)
    if not m:
        return None
    n = int(m.group(1)) if m.group(1).isdigit() else _NUMW[m.group(1).lower()]
    months = {"day": n / 30, "week": n / 4.3, "month": n, "year": n * 12}[m.group(2).lower()]
    for cap, p in ((1.5, "1mo"), (4.5, "3mo"), (9, "6mo"), (18, "1y"), (36, "2y")):
        if months <= cap:
            return p
    return "5y"
# Words that are written in caps but are not tickers. Short, because the real
# filter is "already uppercase in the user's own text" - see _fallback_ticker.
NOT_TICKERS = {"A", "I", "THE", "AND", "OR", "PE", "US", "AI", "CEO", "CFO", "IPO",
               "IS", "IT", "DO", "ETF", "GDP", "CPI", "FED", "SEC", "EPS", "YTD",
               "Q1", "Q2", "Q3", "Q4", "USD", "OK", "MY", "EV", "ROE", "FY"}


def _fallback_ticker(question: str) -> str | None:
    """Pull a ticker out of free text when the router gave us nothing.

    Matches against the ORIGINAL casing, never an uppercased copy. Uppercasing
    first turns every word into a candidate: "When does NVDA report?" matched
    WHEN, which is a real listed symbol, so the fallback answered about a penny
    stock with a straight face. People type tickers in caps; that is the signal.
    """
    for x in TICKER_RE.findall(question):
        if x not in NOT_TICKERS:
            return x
    return None



async def guard(state: ResearchState) -> dict:
    q = (state.get("question") or "").lower()
    bad = ("ignore previous", "ignore all previous", "system prompt", "disregard your")
    if any(b in q for b in bad):
        return {"refused": "That looks like an attempt to change my instructions. "
                           "Ask me about a stock instead.",
                "steps": [RunStep(node="guard", detail="blocked")]}
    if not q.strip():
        return {"refused": "Ask me something about a stock or company.",
                "steps": [RunStep(node="guard", detail="empty")]}
    return {"steps": [RunStep(node="guard", detail="on-topic")]}


async def route(state: ResearchState) -> dict:
    t0 = time.time()
    sel = state.get("selection") or []
    # When the user has picked tickers in the workspace, those ARE the subjects.
    # The router then only decides which domains the question needs.
    prompt = state["question"] if not sel else (
        f"{state['question']}\n\n"
        f"[The user has selected these tickers in their workspace: {', '.join(sel)}. "
        f"Use exactly these tickers and no others. If the question compares them, "
        f"include the `relations` domain and set args.other to the ticker being "
        f"compared against.]")
    route_error = ""
    try:
        r = await llm.call(ROUTE_PROMPT, prompt)
        j = llm.parse_json(r.text) or {}
        tok, ms = r.tokens, r.latency_ms
    except llm.NoAPIKey as e:
        return {"refused": str(e), "steps": [RunStep(node="route", detail="no api key")]}
    except Exception as e:
        # A failed router used to fall through to the market-only fallback
        # below and answer a DIFFERENT question in silence - "when does NVDA
        # report?" came back as a price summary with nothing to say it had
        # degraded. Rate limiting is the common cause and it is invisible.
        j, tok, ms = {}, 0, int((time.time() - t0) * 1000)
        route_error = f"{type(e).__name__}: {e}"[:160]

    if j.get("refuse"):
        return {"refused": str(j["refuse"]),
                "steps": [RunStep(node="route", detail="refused", tokens=tok,
                                  latency_ms=ms, llm=True)]}

    tasks: list[Task] = []
    for i, t in enumerate(j.get("tasks", [])):
        d = t.get("domain")
        if d not in SUBGRAPHS:
            continue
        tk = (t.get("ticker") or "").upper().strip()
        if not tk:
            if d in ("macro",):          # macro is about the market, not a name
                tk = "MARKET"
            else:
                continue
        tasks.append(Task(id=f"t{i}", domain=d, ticker=tk,
                          question=str(t.get("question") or state["question"]),
                          tools=[n.name for n in domain_tools(d)] if False else [],
                          args=t.get("args") or {}))

    if sel:
        # never let the model substitute a ticker the user did not select
        allowed = set(sel)
        tasks = [t for t in tasks if t["ticker"] in allowed]
        covered = {t["ticker"] for t in tasks}
        for miss in [x for x in sel if x not in covered]:
            tasks.append(Task(id=f"s{len(tasks)}", domain="market", ticker=miss,
                              question=state["question"], tools=[], args={}))

    # A performance question ALWAYS gets the peer cohort. The route prompt asks
    # for this, and a small model ignores it about half the time - so it is
    # enforced here rather than hoped for. A bare return is not an answer to
    # "how is it doing": the cohort's return and a beta adjustment are what make
    # it mean anything, since a high-beta name outruns a low-beta one in any
    # rising market without doing anything well.
    if tasks and PERF_RE.search(state["question"]):
        have = {(t["domain"], t["ticker"]) for t in tasks}
        for sym in sorted({t["ticker"] for t in tasks if t["ticker"] != "MARKET"}):
            if ("relations", sym) not in have:
                tasks.append(Task(
                    id=f"p{len(tasks)}", domain="relations", ticker=sym,
                    question=f"How does {sym} compare with its peer cohort over the "
                             f"last year, adjusted for beta and company size?",
                    tools=[], args={}))

    degraded = ""
    if not tasks:   # fallback: pull a ticker out of the text, ask market only
        if route_error:
            degraded = ("The router was unavailable, so this was answered from "
                        "price data alone and may not address the question asked "
                        f"({route_error}).")
        m = _fallback_ticker(state["question"])
        if m:
            tasks = [Task(id="t0", domain="market", ticker=m,
                          question=state["question"], tools=[], args={})]
        else:
            # No ticker is not automatically a dead end: a market-wide question
            # is answerable from index, rates and volatility feeds.
            tasks = [Task(id="m0", domain="macro", ticker="MARKET",
                          question=state["question"], tools=[], args={})]

    tasks = tasks[:12]   # budget guard on fan-out

    # Resolve symbols BEFORE dispatching any work. A ticker that does not exist
    # should cost nothing and say so plainly - fanning out to three domains that
    # all come back empty is slow, confusing, and invites the writer to pad.
    want = sorted({t["ticker"] for t in tasks if t["ticker"] != "MARKET"})
    try:
        q = await yahoo.quotes(want)
    except Exception:
        q = {}
    good = {s_ for s_ in want if (q.get(s_) or {}).get("regularMarketPrice") is not None}
    unknown = [s_ for s_ in want if s_ not in good]
    if unknown and not good and not any(t["ticker"] == "MARKET" for t in tasks):
        names = ", ".join(unknown)
        return {"refused": f"I couldn't find a tradable symbol for {names}. "
                           f"Check the ticker, or search for the company by name.",
                "steps": [RunStep(node="route", detail=f"unresolved: {names}",
                                  tokens=tok, latency_ms=ms, llm=tok > 0)]}
    if unknown:
        tasks = [t for t in tasks if t["ticker"] in good or t["ticker"] == "MARKET"]

    return {"tasks": tasks,
            "tickers": sorted({t["ticker"] for t in tasks}),
            "degraded": degraded,
            "steps": [RunStep(node="route",
                              detail=("ROUTER UNAVAILABLE - fell back to " if degraded else "")
                                     + ", ".join(f"{t['domain']}({t['ticker']})" for t in tasks)
                                     + (f" · dropped unresolved {', '.join(unknown)}" if unknown else ""),
                              tokens=tok, latency_ms=ms, llm=tok > 0)]}


def _with_period(args: dict, state) -> dict:
    p = question_period(state.get("question", ""))
    return {**({"period": p} if p else {}), **(args or {})}


def fan_out(state: ResearchState):
    if state.get("refused"):
        return "writer"
    return [Send(t["domain"], {"domain": t["domain"], "ticker": t["ticker"],
                               "question": t["question"], "tools": t.get("tools") or [],
                               "args": _with_period(t.get("args"), state)})
            for t in state["tasks"]]


def _collect(sub_out: dict) -> dict:
    f = sub_out.get("finding")
    return {"findings": [f] if f else [], "steps": sub_out.get("steps", [])}


# ---------------- one bounded follow-up round ------------------------------------
# The first wave is parallel and blind: no specialist sees another's finding. When
# that finding raises a question only ANOTHER specialist can answer ("fell 8% -
# why?"), a supervisor may send at most two follow-ups, once. The trigger is code,
# not a model call, so a question that does not need it costs nothing extra.
# off | trigger (code gate, then a supervisor call) | writer (the writer decides,
# inside the call it already makes - no extra call when nothing is missing)
FOLLOWUP_MODE = {"0": "off", "1": "writer"}.get(os.environ.get("AGENT_FOLLOWUP", "writer"),
                                                 os.environ.get("AGENT_FOLLOWUP", "writer"))
BIG_MOVE_PCT = 4.0
WHY_RE = re.compile(r"\b(why|what happened|explain|cause|driv)", re.I)
SUPERVISOR_PROMPT = """You supervise stock-research specialists. The first wave has
reported. Decide whether ONE follow-up round would answer something the first
wave raised but could not explain (e.g. a big move with no cause found).

Available specialists you have NOT used yet for that ticker: {free}
Each covers: {desc}

Reply with ONLY JSON: {{"followups": [{{"domain": "...", "ticker": "...",
"question": "the specific thing to find out"}}]}}
At most 2 followups. Return {{"followups": []}} if the findings already answer
the question - that is the common case."""


def _trigger(state: ResearchState) -> str:
    for f in state.get("findings") or []:
        for e in f.evidence:
            if e.tool == "quote" and abs(e.data.get("change_pct") or 0) >= BIG_MOVE_PCT:
                return f"{e.ticker} moved {e.data['change_pct']:+.1f}%"
    if WHY_RE.search(state.get("question", "")):
        return "question asks why"
    return ""


async def review(state: ResearchState) -> dict:
    rnd = state.get("round", 0)
    if FOLLOWUP_MODE != "trigger":
        return {"followups": []}          # writer mode clears its request once served
    if rnd >= 1 or state.get("refused"):
        return {"round": rnd + 1, "followups": []}
    why = _trigger(state)
    if not why:
        return {"round": 1, "followups": [],
                "steps": [RunStep(node="review", detail="no trigger - single round")]}
    findings = state.get("findings") or []
    used = {(f.domain, f.ticker) for f in findings}
    tickers = sorted({f.ticker for f in findings})
    free = {t: [d for d in SUBGRAPHS if d != "portfolio" and (d, t) not in used] for t in tickers}
    t0 = time.time()
    try:
        r = await llm.call(
            SUPERVISOR_PROMPT.format(free=json.dumps(free),
                                     desc=json.dumps({d: DOMAIN_DESC.get(d, "") for d in SUBGRAPHS})),
            f"Question: {state['question']}\nTrigger: {why}\n\nFirst-wave findings:\n"
            + "\n".join(f"- {f.domain}({f.ticker}): {f.narrative}" for f in findings))
        asks = (llm.parse_json(r.text) or {}).get("followups") or []
        tok, ms = r.tokens, r.latency_ms
    except Exception as e:
        return {"round": 1, "followups": [],
                "steps": [RunStep(node="review", detail=f"supervisor failed: {type(e).__name__}")]}
    tasks = [Task(id=f"f{i}", domain=a["domain"], ticker=a["ticker"], question=a.get("question") or state["question"],
                  tools=[], args={})
             for i, a in enumerate(asks[:2])
             if a.get("domain") in free.get(a.get("ticker"), [])]
    return {"round": 1, "followups": tasks, "steps": [RunStep(
        node="review", detail=f"{why} -> " + (", ".join(f"{t['domain']}({t['ticker']})" for t in tasks) or "no follow-up needed"),
        tokens=tok, latency_ms=int(ms), llm=True)]}


def _free_domains(findings) -> dict:
    used = {(f.domain, f.ticker) for f in findings}
    return {t: [d for d in SUBGRAPHS if d != "portfolio" and (d, t) not in used]
            for t in sorted({f.ticker for f in findings})}


WRITER_FOLLOWUP = """

BEFORE WRITING, check: would a reader finish your answer still asking the
obvious follow-up question? Typical gaps: the stock moved sharply but nothing
here says WHY (news, ratings or filings were never checked); a "why" question
answered only with numbers that describe, not explain. Describing a move is
not explaining it. The cause of a price move - today's or one months ago - is
almost always news, a rating change, an earnings result or a filing: for that
gap ask for BOTH `street` (news, incl. headlines on past big-move days, and
rating changes) AND `events` (earnings results, 8-K filings with their reasons).
If there is such a gap AND a specialist below could fill it,
ask for up to 2 of them instead of writing - you get one chance, and you will
write the final answer with their findings added. If no specialist could
help, write the answer and name what is missing. Specialists not yet used, per ticker: {free}
They cover: {desc}{hint}
Reply with ONLY JSON, filling the keys IN THIS ORDER:
{{"gap": "the obvious unanswered follow-up, or none",
  "followups": [{{"domain": "...", "ticker": "...", "question": "what to find out"}}],
  "answer": "..."}}
Leave "followups" as [] when there is no gap a listed specialist could fill.
If you do request followups, "answer" may be empty - it will be rewritten."""


def _writer_clause(state: ResearchState) -> tuple[str, dict]:
    if FOLLOWUP_MODE != "writer" or state.get("round", 0) >= 1:
        return "", {}
    free = _free_domains(state.get("findings") or [])
    if not any(free.values()):
        return "", {}
    why = _trigger(state)
    return WRITER_FOLLOWUP.format(
        free=json.dumps(free), desc=json.dumps({d: DOMAIN_DESC.get(d, "") for d in SUBGRAPHS}),
        hint=f"\nNote: {why}." if why else ""), free


def _requested(j: dict, free: dict, state: ResearchState) -> list:
    return [Task(id=f"w{i}", domain=a["domain"], ticker=a["ticker"],
                 question=a.get("question") or state["question"], tools=[], args={})
            for i, a in enumerate((j.get("followups") or [])[:2])
            if isinstance(a, dict) and a.get("domain") in free.get(a.get("ticker"), [])]


def follow_up(state: ResearchState):
    if FOLLOWUP_MODE != "trigger":
        return "writer"
    if state.get("round", 0) == 1 and state.get("followups"):
        return [Send(t["domain"], {"domain": t["domain"], "ticker": t["ticker"],
                                   "question": t["question"], "tools": [],
                                   "args": _with_period({}, state)})
                for t in state["followups"]]
    return "writer"


def make_domain_node(name: str):
    async def node(s: dict) -> dict:
        out = await SUBGRAPHS[name].ainvoke(s)
        return _collect(out)
    return node


def _ask_more(asks: list, r) -> dict:
    return {"followups": asks, "round": 1, "steps": [RunStep(
        node="writer.decide", detail="needs more -> " + ", ".join(
            f"{t['domain']}({t['ticker']})" for t in asks),
        tokens=r.tokens, latency_ms=r.latency_ms, llm=True)]}


def after_writer(state: ResearchState):
    if FOLLOWUP_MODE == "writer" and state.get("followups") and not state.get("answer"):
        return [Send(t["domain"], {"domain": t["domain"], "ticker": t["ticker"],
                                   "question": t["question"], "tools": [],
                                   "args": _with_period({}, state)})
                for t in state["followups"]]
    return END


async def writer(state: ResearchState) -> dict:
    if state.get("refused"):
        return {"answer": state["refused"]}
    findings = state.get("findings") or []
    if not findings:
        return {"answer": "I couldn't gather any data for that."}
    if len(findings) == 1 and findings[0].confidence != "unavailable":
        # One domain. The specialist already did the analysis, so the writer acts
        # as an EDITOR - it tightens the prose and keeps the specialist's voice.
        # This used to short-circuit straight to the narrative, which saved a call
        # but meant single-domain answers never got the writing pass that
        # multi-domain ones did. Readability measured worst exactly there.
        f = findings[0]
        clause, free = _writer_clause(state)
        try:
            r = await llm.call(POLISH_PROMPT + clause,
                               f"Question: {state['question']}\n\n"
                               f"Specialist ({f.domain}) wrote:\n{f.narrative}")
            j = llm.parse_json(r.text) or {}
            asks = _requested(j, free, state) if clause else []
            if asks:
                return _ask_more(asks, r)
            polished = str(j.get("answer") or "").strip()
            # an editor that rewrites it into something unrecognisable has
            # overstepped; fall back to the specialist's own words
            if not polished or len(polished) > len(f.narrative) * 2.2:
                polished = f.narrative
            # an editor can introduce a figure that was never in the evidence
            if unverified_figures(polished, findings) and not unverified_figures(
                    f.narrative, findings):
                polished = f.narrative
            return await _verify_and_repair(
                state, polished, findings,
                RunStep(node="writer", detail=f"edited {f.domain}",
                        tokens=r.tokens, latency_ms=r.latency_ms, llm=True))
        except Exception:
            return {"answer": f.narrative,
                    "steps": [RunStep(node="writer",
                                      detail="editor unavailable - specialist text used")]}
    payload = [{"domain": f.domain, "ticker": f.ticker, "finding": f.narrative,
                "evidence": {e.tool: present(e.data) for e in f.evidence}}
               for f in findings]
    clause, free = _writer_clause(state)
    try:
        r = await llm.call(WRITER_PROMPT + clause,
                           f"Question: {state['question']}\n\n"
                           + json.dumps(payload, default=str)[:16000])
        j = llm.parse_json(r.text) or {}
        asks = _requested(j, free, state) if clause else []
        if asks:
            return _ask_more(asks, r)
        ans = str(j.get("answer") or r.text).strip()
        step = RunStep(node="writer", detail=f"{len(findings)} findings",
                       tokens=r.tokens, latency_ms=r.latency_ms, llm=True)
    except Exception:
        ans = " ".join(f.narrative for f in findings)
        step = RunStep(node="writer", detail="fallback: concatenated findings")
        return {"answer": ans, "steps": [step]}

    return await _verify_and_repair(state, ans, findings, step)


REPAIR_PROMPT = """You are the editor. Fix the specific problems listed, and
change nothing else - keep the point, the order, the voice.

If figures are listed as UNSUPPORTED: those numbers do not appear in the
evidence. Remove each one, or replace it with a figure that IS in the evidence.
Never substitute a different invented number. If removing it leaves the
sentence empty of substance, drop the sentence.

If the draft is too dense: split long sentences, keep at most two figures per
sentence, and cut figures that do not change the point.

Reply with ONLY JSON: {"answer": "..."}"""


async def _verify_and_repair(state, ans, findings, step):
    """Gate the answer before it ships.

    Two checks, both deterministic and free: is any figure unsupported by the
    evidence, and is the prose too dense to read. Grounding used to be computed
    only AFTER the graph, so an answer with a fabricated number shipped with a
    warning badge attached. For financial output that is the wrong default -
    it is now blocking, with one repair attempt.
    """
    bad = unverified_figures(ans, findings)
    dens = density_report(ans)
    if not bad and dens["ok"]:
        return {"answer": ans, "steps": [step]}

    problems = []
    if bad:
        problems.append("UNSUPPORTED figures (not present in the evidence): "
                        + ", ".join(str(b) for b in bad))
    if not dens["ok"]:
        problems.append("Too dense: " + dens["why"])

    try:
        fix = await llm.call(REPAIR_PROMPT,
                             f"Question: {state['question']}\n\n"
                             f"Problems:\n- " + "\n- ".join(problems) +
                             f"\n\nDraft:\n{ans}")
        cand = str((llm.parse_json(fix.text) or {}).get("answer") or "").strip()
    except Exception:
        cand = ""

    if cand:
        bad2, dens2 = unverified_figures(cand, findings), density_report(cand)
        better = (len(bad2) < len(bad)) or (bad2 == bad and not bad and
                                            dens2["worst_figures"] < dens["worst_figures"])
        if not bad2 and dens2["ok"]:
            better = True
        if better:
            return {"answer": cand, "steps": [step, RunStep(
                node="writer.verify", detail="repaired: " + "; ".join(problems)[:70],
                tokens=fix.tokens, latency_ms=fix.latency_ms, llm=True)]}

    # repair failed or made it no better - ship the draft but record why
    return {"answer": ans, "steps": [step, RunStep(
        node="writer.verify",
        detail="UNRESOLVED: " + "; ".join(problems)[:70])]}


def build():
    g = StateGraph(ResearchState)
    g.add_node("guard", guard)
    g.add_node("route", route)
    for d in SUBGRAPHS:
        g.add_node(d, make_domain_node(d))
    g.add_node("review", review)
    g.add_node("writer", writer)
    g.add_edge(START, "guard")
    g.add_conditional_edges("guard",
                            lambda s: "writer" if s.get("refused") else "route",
                            {"writer": "writer", "route": "route"})
    g.add_conditional_edges("route", fan_out, list(SUBGRAPHS) + ["writer"])
    for d in SUBGRAPHS:
        g.add_edge(d, "review")
    g.add_conditional_edges("review", follow_up, list(SUBGRAPHS) + ["writer"])
    g.add_conditional_edges("writer", after_writer, list(SUBGRAPHS) + [END])
    return g.compile()


GRAPH = build()


MONTHS = ("january|february|march|april|may|june|july|august|september|"
          "october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")

# Text that LOOKS numeric but makes no factual claim, stripped before checking.
_NOISE = [
    re.compile(rf"\b(?:{MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*\d{{0,4}}", re.I),  # June 27, 2026
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),                                          # 2026-06-27
    re.compile(r"\bQ[1-4]\s*(?:FY)?\s*\d{0,4}\b", re.I),                           # Q3 2026
    re.compile(r"\b(?:S&P|Russell|FTSE|Nasdaq|Dow|CAC|DAX|Nikkei)\s*\d+\b", re.I),  # S&P 500
    re.compile(r"\b\d+\s*-\s*(?:year|week|day|month|quarter)\b", re.I),            # 10-year, 52-week
]
SCALE = {"thousand": 1e3, "k": 1e3, "million": 1e6, "m": 1e6,
         "billion": 1e9, "bn": 1e9, "b": 1e9, "trillion": 1e12, "t": 1e12}
_NUM = re.compile(r"(?<![\w.-])(-?\d[\d,]*(?:\.\d+)?)\s*"
                  r"(thousand|million|billion|trillion|bn|[kmbt])?\b(?![\w-])", re.I)

# Digits that name rather than measure.
IGNORE = {30, 50, 52, 100, 200, 400, 500, 600, 1000, 2000,
          2023, 2024, 2025, 2026, 2027, 2028}


def unverified_figures(answer: str, findings) -> list[float]:
    """Numbers the answer asserts that no evidence record supports.

    Shared by the post-hoc report AND the in-loop gate, so the check that
    blocks and the check that reports can never disagree.
    """
    ev: set[float] = set()
    for f in findings:
        evidence = f.evidence if hasattr(f, "evidence") else f.get("evidence", [])
        for e in evidence:
            nums = e.numbers() if hasattr(e, "numbers") else []
            for n in nums:
                for v in (n, round(n, 2), round(n, 1), round(n)):
                    ev.add(float(v))
                for unit in (1e3, 1e6, 1e9, 1e12):
                    if abs(n) >= unit:
                        ev.add(round(n / unit, 3)); ev.add(round(n / unit, 2))
                        ev.add(round(n / unit, 1))

    text = (answer or "").replace("%", "")
    for pat in _NOISE:
        text = pat.sub(" ", text)
    bad = []
    for m in _NUM.finditer(text):
        raw = float(m.group(1).replace(",", ""))
        unit = (m.group(2) or "").lower()
        cands = {raw} | ({raw * SCALE.get(unit, 1)} if unit else set())
        if abs(raw) <= 1.5 or raw in IGNORE:
            continue
        if any(round(c, 2) in ev or round(c, 1) in ev or round(c) in ev or c in ev
               for c in cands):
            continue
        bad.append(raw)
    return bad


def grounding_check(run: AgentRun) -> AgentRun:
    """Post-hoc report. The writer already gated on this; this records it."""
    run.ungrounded_numbers = unverified_figures(run.answer, run.findings)
    run.grounded = not run.ungrounded_numbers
    return run


async def ask(question: str) -> AgentRun:
    out = await GRAPH.ainvoke({"question": question, "findings": [], "steps": []})
    run = AgentRun(question=question, tickers=out.get("tickers", []),
                   findings=out.get("findings", []), answer=out.get("answer", ""),
                   steps=out.get("steps", []), degraded=out.get("degraded", ""))
    return grounding_check(run)
