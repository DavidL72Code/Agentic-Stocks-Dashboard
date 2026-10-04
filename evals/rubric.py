"""Quality scoring.

Mechanics (did the right domain run, is the number grounded) are necessary but
not sufficient. These score whether the answer is actually good along six axes.

Three are DETERMINISTIC - computed from the text and the evidence, no model:
    validity        every number traceable to an evidence DTO
    readability     sentence length, number density, jargon load
    conjunction     does it RELATE two tools' data, or just list them

Three need JUDGEMENT, so an LLM judge scores them against anchored 1-5 scales:
    task_fit        did it answer the question actually asked
    usefulness      does it tell you something the raw tiles do not
    calibration     hedges honestly, admits gaps, never advises

The judge is validated in judge_control() - if it cannot separate a known-good
answer from a deliberately bad one, its scores are meaningless and the suite
says so instead of reporting them.
"""
from __future__ import annotations
import json, re, statistics

DIMENSIONS = ["task_fit", "validity", "usefulness", "structure",
              "readability", "calibration"]

# ───────────────────────── deterministic ─────────────────────────
_SENT = re.compile(r"(?<=[.!?])\s+")
_NUM = re.compile(r"(?<![\w.-])-?\d[\d,]*(?:\.\d+)?%?(?![\w-])")
# digits that NAME something rather than measure it - "52-week", "10-year",
# "S&P 500", "June 27, 2026", "Q3". Counting these as figures made a correctly
# written sentence look crowded; the grounding check already excludes them.
_MONTHS = ("january|february|march|april|may|june|july|august|september|october|"
           "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")
_NOT_A_FIGURE = [
    re.compile(rf"\b(?:{_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*\d{{0,4}}", re.I),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\bQ[1-4]\s*(?:FY)?\s*\d{0,4}\b", re.I),
    re.compile(r"\b(?:S&P|Russell|FTSE|Nasdaq|Dow|CAC|DAX|Nikkei)\s*\d+\b", re.I),
    re.compile(r"\b\d+\s*-\s*(?:year|week|day|month|quarter|session)\b", re.I),
]


def _figures(text: str) -> list[str]:
    for pat in _NOT_A_FIGURE:
        text = pat.sub(" ", text)
    return _NUM.findall(text)
_HEDGE = re.compile(r"\b(appears|suggests|indicates|may|might|could|likely|"
                    r"coincides|alongside|unavailable|not provided|unclear|"
                    r"would need|suggestive)\b", re.I)
_ADVICE = re.compile(r"\b(you should (buy|sell)|we recommend|i recommend|"
                     r"time to (buy|sell)|strong buy signal|must buy)\b", re.I)
# a conjunction relates two facts rather than listing them
_RELATES = re.compile(r"\b(but|however|while|whereas|despite|even as|although|"
                      r"alongside|against|relative to|compared (with|to)|"
                      r"rather than|yet|though|in contrast)\b", re.I)


def readability(text: str) -> dict:
    """Sentence length and figures PER SENTENCE.

    An earlier version measured figures per WORD. That penalised concision:
    the same two figures in a 10-word sentence scored worse than in a 25-word
    one, so the metric rewarded padding and contradicted the writing guidance
    the prompts actually give ("at most two figures per sentence").
    """
    sents = [s for s in _SENT.split(text.strip()) if s.strip()]
    words = text.split()
    if not sents or not words:
        return {"score": 1, "detail": "empty"}
    avg_len = len(words) / len(sents)
    per_sent = [len(_figures(s)) for s in sents]
    worst = max(per_sent) if per_sent else 0

    score, notes = 5, []
    if avg_len > 38:
        score -= 2; notes.append(f"sentences too long ({avg_len:.0f} words)")
    elif avg_len > 30:
        score -= 1; notes.append(f"long sentences ({avg_len:.0f} words)")
    if worst >= 6:
        score -= 3; notes.append(f"unreadable: {worst} figures in one sentence")
    elif worst >= 4:
        score -= 2; notes.append(f"{worst} figures crammed into one sentence")
    elif worst == 3:
        score -= 1; notes.append("3 figures in one sentence")
    if len(sents) == 1 and len(words) > 60:
        score -= 1; notes.append("one unbroken sentence")
    return {"score": max(1, score), "detail": "; ".join(notes) or
            f"{len(sents)} sentences, {avg_len:.0f} words each, "
            f"max {worst} figure(s) per sentence"}


def structure(text: str, question: str) -> dict:
    sents = [s for s in _SENT.split(text.strip()) if s.strip()]
    score, notes = 5, []
    if len(sents) < 2:
        score -= 2; notes.append("single sentence")
    if len(sents) > 8:
        score -= 1; notes.append(f"{len(sents)} sentences - padded")
    if len(text.split()) < 18:
        score -= 2; notes.append("too thin to be an answer")
    outlook = re.search(r"\b(outlook|read|view|going forward|future|expect)\b",
                        question, re.I)
    if outlook and not re.search(r"\b(next|watch|confirm|would change|datapoint|"
                                 r"ahead|upcoming)\b", text, re.I):
        score -= 1; notes.append("outlook question with no forward marker")
    return {"score": max(1, score), "detail": "; ".join(notes) or f"{len(sents)} sentences, shaped"}


def _tool_values(findings) -> dict[str, set[float]]:
    """Every numeric value each tool contributed, so we can tell which tool a
    figure in the answer came from."""
    out: dict[str, set[float]] = {}
    for f in findings:
        for e in f.get("evidence", []):
            vals = out.setdefault(e["tool"], set())
            def walk(v):
                if isinstance(v, bool):
                    return
                if isinstance(v, (int, float)):
                    for r in (round(float(v), 2), round(float(v), 1), round(float(v))):
                        vals.add(r)
                    for unit in (1e3, 1e6, 1e9, 1e12):
                        if abs(v) >= unit:
                            vals.add(round(v / unit, 2)); vals.add(round(v / unit, 1))
                elif isinstance(v, dict):
                    for x in v.values(): walk(x)
                elif isinstance(v, (list, tuple)):
                    for x in v: walk(x)
            walk(e.get("data"))
    return out


def conjunction(text: str, findings: list) -> dict:
    """DESIGN.md's conjunction rate, measured properly.

    A conjunction is a single sentence that RELATES values from two different
    tools - "near its 52-week high on below-average volume" draws on range_52w
    AND volume_profile at once.

    The first version of this counted connective words ("but", "while"). That
    was wrong: an architecture that produces many one-tool findings scores
    highly simply because the WRITER glues them together with "while", even
    though every underlying claim came from a single tool. Counting which tools
    a sentence's figures came from tests the actual claim.
    """
    tv = _tool_values(findings)
    sentences = [s for s in _SENT.split(text.strip()) if s.strip()]
    best, per_sentence = 0, []
    for sent in sentences:
        nums = []
        for m in re.finditer(r"(?<![\w.-])-?\d[\d,]*(?:\.\d+)?", sent):
            try:
                nums.append(float(m.group().replace(",", "")))
            except ValueError:
                pass
        hit_tools = {t for t, vals in tv.items()
                     if any(round(n, 2) in vals or round(n, 1) in vals or round(n) in vals
                            for n in nums)}
        per_sentence.append(len(hit_tools))
        best = max(best, len(hit_tools))
    relates = len(_RELATES.findall(text))
    hit = best >= 2
    return {"score": 5 if best >= 3 else 4 if best == 2 else 2 if relates else 1,
            "hit": hit, "max_tools_in_one_sentence": best,
            "detail": f"best sentence draws on {best} tool(s); "
                      f"per-sentence {per_sentence}; {relates} connective(s)"}


def validity(ungrounded: list, grounded: bool | None, findings: list) -> dict:
    ev = sum(len(f.get("evidence", [])) for f in findings)
    if grounded is False:
        return {"score": 1, "detail": f"unverified figures: {ungrounded}"}
    if ev == 0:
        return {"score": 2, "detail": "no evidence attached"}
    return {"score": 5, "detail": f"all figures traceable across {ev} evidence records"}


def calibration_signals(text: str) -> dict:
    advice = bool(_ADVICE.search(text))
    hedges = len(_HEDGE.findall(text))
    return {"advice": advice, "hedges": hedges}


# ───────────────────────── judge ─────────────────────────
JUDGE_PROMPT = """You grade one answer produced by a stock-research assistant.

You get the user's question, the assistant's answer, and the EVIDENCE it was
given. Grade only what is in front of you.

Score three dimensions 1-5 using these anchors:

task_fit - did it answer the question that was ACTUALLY asked?
  5 answers the specific question directly, including every part of it
  3 answers a neighbouring question, or only part of a multi-part one
  1 ignores the question and recites generic facts

usefulness - does it tell the reader something the raw numbers do not?
  5 relates facts to each other or to context, producing a non-obvious point
  3 accurate but mostly restates figures the reader could read off a table
  1 padding, truisms, or nothing a dashboard tile would not already show

calibration - is it honest about what it knows?
  5 hedges where the evidence is thin, names missing data, gives no advice
  3 slightly over-confident, or glosses over a gap
  1 states guesses as fact, or tells the reader to buy/sell

Penalise an answer that asserts anything not present in the evidence.
Reward naming missing data explicitly.

Reply with ONLY JSON:
{"task_fit": n, "usefulness": n, "calibration": n, "note": "one short sentence"}"""


async def judge(question: str, answer: str, findings: list, llm,
                model: str | None = None) -> dict:
    # key by TICKER too - two findings in the same domain for different tickers
    # would otherwise collide and the judge would only see the last one, then
    # correctly report the other ticker's figures as unsupported.
    # rendered the way the writer saw it: raw DTOs for a multi-domain run run
    # past the cut-off, and a judge that cannot see the evidence marks correct
    # figures as unsupported
    from app.graph.present import present
    evidence = {f"{f.get('ticker','?')}:{f['domain']}:{e['tool']}": present(e["data"])
                for f in findings for e in f.get("evidence", [])}
    payload = json.dumps({"question": question, "answer": answer,
                          "evidence": evidence}, default=str)[:30000]
    try:
        r = await llm.call(JUDGE_PROMPT, payload, model=model)
        j = llm.parse_json(r.text) or {}
        return {k: int(j.get(k, 0)) for k in ("task_fit", "usefulness", "calibration")} | \
               {"note": str(j.get("note", ""))[:120], "tokens": r.tokens}
    except Exception as e:
        return {"task_fit": 0, "usefulness": 0, "calibration": 0,
                "note": f"judge unavailable: {type(e).__name__}", "tokens": 0}


def score_all(question, answer, findings, ungrounded, grounded):
    r = readability(answer)
    s = structure(answer, question)
    c = conjunction(answer, findings)
    v = validity(ungrounded, grounded, findings)
    return {"readability": r, "structure": s, "conjunction": c, "validity": v,
            "signals": calibration_signals(answer)}
