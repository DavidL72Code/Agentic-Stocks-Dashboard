"""Answer-quality scorecard for the agent - the measurement behind every change
to a prompt, a node or a gate.

The golden set (run.py --agent) checks MECHANICS: the right domain ran, the
figures are grounded, the refusals refuse. It cannot tell a sharp answer from a
dull one. This runs a broader set of realistic questions through the live
server and scores each answer two ways:

    judged          task_fit, usefulness, calibration (1-5), by a DIFFERENT and
                    stronger model than the one that wrote the answer, against
                    the anchored rubric in rubric.py, after judge_control's
                    fixtures prove it can tell good from bad
    deterministic   grounded, readability, conjunction, cost (tokens, calls,
                    wall-clock seconds)

    python -m evals.quality --tag before          # needs the server on :8077
    python -m evals.quality --tag after --only perf_ytd,why_move
    python -m evals.quality --compare before after
    python -m evals.quality --tag base --no-judge  # collect answers only
    python -m evals.quality --pairwise base after # one judge call per question

Pairwise is the sharper instrument. Absolute 1-5 scores saturate - most answers
from either version get a 5 - and a free-tier judge allows ~20 calls a day.
Showing the judge both answers to the same question at once, in random order,
costs one call per case, scores both sides against the same rubric in the same
context, and asks which one a reader would rather have.

Scorecards land in evals/quality/<tag>.json. One sample per question, so a
single case moving by one point is noise; read the means, and the cases that
move together.
"""
from __future__ import annotations
import argparse, asyncio, json, os, pathlib, statistics, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass
from evals.rubric import conjunction, judge, readability  # noqa: E402
from evals.suites import api  # noqa: E402

OUT = ROOT / "evals" / "quality"
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gemini-3-flash-preview")
PACE_S = float(os.environ.get("QUALITY_PACE_S", "4"))

# Each case says what a good answer has to do, so a reader of the scorecard can
# check the judge's verdict against something concrete. `history` is a prior
# turn - the question only makes sense with it.
CASES = [
    {"id": "perf_ytd", "q": "How is NVDA performing this year?",
     "needs": "a YTD return set against peers or beta, not a bare number"},
    {"id": "valuation", "q": "Is AMD expensive relative to what it earns?",
     "needs": "multiples set against margins or growth"},
    {"id": "earnings_outlook", "q": "What's the setup for AAPL into its next earnings?",
     "needs": "the date, the estimate, the beat/miss record"},
    {"id": "why_move", "q": "Why did TSLA move today?",
     "needs": "a cause from news/ratings/filings, or a plain statement that none was found"},
    {"id": "compare_pair", "q": "Compare MSFT and GOOGL on margins and growth.",
     "needs": "both names, the same metrics side by side"},
    {"id": "street_change", "q": "What do analysts think about META, and has that changed recently?",
     "needs": "consensus and targets, plus recent rating changes"},
    {"id": "read_across", "q": "If NVDA sells off, does AMD usually follow?",
     "needs": "measured correlation or beta, not an assertion"},
    {"id": "market_today", "q": "What's driving the market today?",
     "needs": "index moves tied to a named macro event"},
    {"id": "broad_read", "q": "Give me the overall read on AMZN right now.",
     "needs": "both sides of the evidence, the backdrop, what would change it; no advice"},
    {"id": "dividend_safety", "q": "Is KO's dividend safe?",
     "needs": "payout ratio or cash-flow cover"},
    {"id": "leverage", "q": "How leveraged is NVDA's balance sheet?",
     "needs": "debt against equity or cash, in correct units"},
    {"id": "six_month_peers", "q": "How has PLTR done over the last six months versus its peers?",
     "needs": "a six-month window, not a one-year one"},
    {"id": "company_name", "q": "Is Nvidia's rally backed by earnings growth?",
     "needs": "resolves the name to NVDA; price move set against EPS/revenue growth"},
    {"id": "followup_swap", "q": "What about AMD?",
     "history": [{"q": "How is NVDA performing this year?",
                  "a": "NVDA is up this year and ahead of its semiconductor peers."}],
     "needs": "reads the prior turn: AMD's performance this year"},
    {"id": "followup_why", "q": "Why is that?",
     "history": [{"q": "What do analysts think about AAPL?",
                  "a": "Most analysts rate AAPL a buy, with a mean target above the "
                       "current price."}],
     "needs": "reads the prior turn: what drives the analyst view on AAPL"},
]


def _post(c: dict) -> tuple[int, dict, float]:
    body = {"question": c["q"]}
    if c.get("tickers"):
        body["tickers"] = c["tickers"]
    if c.get("history"):
        body["history"] = c["history"]
    t0 = time.time()
    code, d = api("/api/agent/ask", "POST", body, timeout=300)
    return code, d, time.time() - t0


async def run_case(c: dict, llm, judge_it: bool = True) -> dict:
    code, d, wall = await asyncio.to_thread(_post, c)
    if code == 200 and d.get("degraded"):           # quota window; try once more
        await asyncio.sleep(PACE_S * 4)
        code, d, wall = await asyncio.to_thread(_post, c)
    row = {"id": c["id"], "q": c["q"], "needs": c["needs"], "http": code,
           "wall_s": round(wall, 1)}
    if code != 200:
        return row | {"error": str(d)[:200]}
    ans = d.get("answer", "")
    findings = d.get("findings", [])
    question = c["q"] if not c.get("history") else (
        "\n".join(f"(earlier) {h['q']}" for h in c["history"]) + f"\n(now) {c['q']}")
    j = await judged(question, ans, findings, llm) if judge_it else \
        {"task_fit": 0, "usefulness": 0, "calibration": 0, "note": "not judged"}
    return row | {
        "answer": ans, "tickers": d.get("tickers", []),
        "domains": sorted({f["domain"] for f in findings}),
        "degraded": d.get("degraded", ""),
        "grounded": d.get("grounded"), "ungrounded": d.get("ungrounded_numbers", []),
        "tokens": d.get("total_tokens", 0), "calls": d.get("llm_calls", 0),
        "readability": readability(ans)["score"] if ans else 0,
        "conjunction": conjunction(ans, findings)["score"] if ans else 0,
        "task_fit": j["task_fit"], "usefulness": j["usefulness"],
        "calibration": j["calibration"], "judge_note": j["note"],
        "steps": [f"{s['node']}: {s['detail']}" for s in d.get("steps", [])],
        "resolved": d.get("resolved", ""),
        # kept so a later, stricter judge can re-score this exact answer
        "findings": [{"domain": f["domain"], "ticker": f["ticker"],
                      "evidence": [{"tool": e["tool"], "data": e["data"]} for e in f.get("evidence", [])]}
                     for f in findings],
    }


async def judged(question, ans, findings, llm, tries: int = 4) -> dict:
    """The judge model's free tier rate-limits after a dozen calls. An
    unavailable verdict is NOT a score of zero - it used to be averaged in as
    one, which dragged the mean down for reasons that had nothing to do with
    the answer. Back off and retry; if it still fails, the row is unjudged."""
    for n in range(tries):
        j = await judge(question, ans, findings, llm, model=JUDGE_MODEL)
        if not j["note"].startswith("judge unavailable"):
            return j
        await asyncio.sleep(20 * (n + 1))
    return j | {"unjudged": True}


async def validate_judge(llm) -> bool:
    import evals.judge_control as jc
    s = {n: await judged(jc.Q, a, jc.FINDINGS, llm) for n, _, a in jc.FIXTURES}
    ok = (all(s["good"][k] >= 4 for k in ("task_fit", "usefulness", "calibration"))
          and s["ignores_question"]["task_fit"] <= 2
          and s["fabricated"]["usefulness"] <= 2
          and s["gives_advice"]["calibration"] <= 2)
    print(f"judge {JUDGE_MODEL}: {'VALIDATED' if ok else 'NOT VALIDATED'} "
          + " ".join(f"{n}={s[n]['task_fit']}/{s[n]['usefulness']}/{s[n]['calibration']}"
                     for n in s))
    return ok


KEYS = ("task_fit", "usefulness", "calibration", "readability", "conjunction")

PAIR_PROMPT = """You compare two answers a stock-research assistant gave to the SAME
question. Each comes with the evidence it was given. Grade only what is in front
of you; the two were produced by different versions of the assistant, possibly
from different data pulls.

Score EACH answer 1-5 on these anchors:

task_fit - did it answer the question that was ACTUALLY asked, every part of it?
  5 answers the specific question directly, including every part of it
  3 answers a neighbouring question, or only part of a multi-part one
  1 ignores the question, refuses it, or recites generic facts
usefulness - does it tell the reader something the raw numbers do not?
  5 relates facts to each other or to context, producing a non-obvious point
  3 accurate but mostly restates figures a table would show
  1 padding, truisms, or nothing a dashboard tile would not already show
calibration - is it honest about what it knows?
  5 hedges where evidence is thin, names missing data, gives no advice, units right
  3 slightly over-confident, glosses over a gap, or a misleading unit or date
  1 states guesses as fact, misreads the data, or tells the reader to buy/sell

Penalise any claim not present in that answer's evidence, and any figure that is
misread (a percent read as a ratio, a stale period presented as current).
If the question refers back to an earlier turn, the earlier turn is shown; an
answer that ignores it fails task_fit.

Then say which answer a careful reader would rather have: "A", "B" or "tie".

Reply with ONLY JSON:
{"A": {"task_fit": n, "usefulness": n, "calibration": n},
 "B": {"task_fit": n, "usefulness": n, "calibration": n},
 "better": "A" | "B" | "tie", "why": "one sentence"}"""


def _evidence(findings) -> dict:
    from app.graph.present import present
    return {f"{f.get('ticker','?')}:{f['domain']}:{e['tool']}": present(e["data"])
            for f in findings or [] for e in f.get("evidence", [])}


def _fit_evidence(ev: dict, budget: int = 18000) -> dict:
    """Trim one side's evidence to a budget - lists first, then the largest
    tools - so neither answer is ever cut off the end of the prompt."""
    from app.graph.build import present_short
    size = lambda: len(json.dumps(ev, default=str))
    if size() > budget:
        ev = {k: present_short(v) for k, v in ev.items()}
    while size() > budget and ev:
        ev.pop(max(ev, key=lambda k: len(json.dumps(ev[k], default=str))))
    return ev


async def pair_judge(llm, question, a, b, tries: int = 4) -> dict:
    body = json.dumps({"question": question,
                       "A": {"answer": a.get("answer", ""), "evidence": _fit_evidence(_evidence(a.get("findings")))},
                       "B": {"answer": b.get("answer", ""), "evidence": _fit_evidence(_evidence(b.get("findings")))}},
                      default=str)
    for n in range(tries):
        try:
            r = await llm.call(PAIR_PROMPT, body, model=JUDGE_MODEL)
            j = llm.parse_json(r.text) or {}
            if j.get("A") and j.get("B"):
                return j
        except Exception as e:
            j = {"error": f"{type(e).__name__}: {e}"[:200]}
            if "quota" in str(e).lower() and "day" in str(e).lower():
                return j
        await asyncio.sleep(15 * (n + 1))
    return j


async def validate_pair(llm) -> bool:
    """Three calls: the known-good fixture against each deliberately broken one,
    good placed first, second, first. A judge that cannot pick it every time,
    or that scores the broken one high on the axis it was built to break, is
    not fit to compare two versions of the agent."""
    import evals.judge_control as jc
    fx = {n: a for n, _, a in jc.FIXTURES}
    findings = jc.FINDINGS
    ok = True
    for i, (bad, axis) in enumerate((("ignores_question", "task_fit"),
                                     ("fabricated", "usefulness"),
                                     ("gives_advice", "calibration"))):
        good = {"answer": fx["good"], "findings": findings}
        worse = {"answer": fx[bad], "findings": findings}
        first, second = (good, worse) if i != 1 else (worse, good)
        j = await pair_judge(llm, jc.Q, first, second)
        gs, bs = (j.get("A", {}), j.get("B", {})) if i != 1 else (j.get("B", {}), j.get("A", {}))
        picked = j.get("better") == ("A" if i != 1 else "B")
        caught = (bs.get(axis) or 9) <= 2
        ok &= picked and caught
        print(f"  pair-validate good vs {bad:<17} picked_good={picked} {axis}: good={gs.get(axis)} bad={bs.get(axis)}")
    print(f"pairwise judge {JUDGE_MODEL}: {'VALIDATED' if ok else 'NOT VALIDATED'}")
    return ok


async def pairwise(base: str, new: str, llm) -> int:
    validated = await validate_pair(llm)
    import random
    A = {r["id"]: r for r in json.loads((OUT / f"{base}.json").read_text())["rows"]}
    B = {r["id"]: r for r in json.loads((OUT / f"{new}.json").read_text())["rows"]}
    rng = random.Random(7)                       # fixed: the same order on a re-run
    rows, tally = [], {"new": 0, "base": 0, "tie": 0}
    for c in CASES:
        if c["id"] not in A or c["id"] not in B:
            continue
        q = c["q"] if not c.get("history") else (
            "\n".join(f"(earlier turn) user: {h['q']}\n(earlier turn) assistant: {h['a']}"
                       for h in c["history"]) + f"\n(now) user: {c['q']}")
        flip = rng.random() < .5                 # position bias: new is A half the time
        first, second = (B[c["id"]], A[c["id"]]) if flip else (A[c["id"]], B[c["id"]])
        j = await pair_judge(llm, q, first, second)
        if j.get("error") and not j.get("A"):
            print(f"  {c['id']:<18} JUDGE ERROR {j['error'][:120]}"); continue
        sn, sb = (j["A"], j["B"]) if flip else (j["B"], j["A"])
        winner = {"A": "new" if flip else "base", "B": "base" if flip else "new"}.get(j.get("better"), "tie")
        tally[winner] += 1
        rows.append({"id": c["id"], "new": sn, "base": sb, "winner": winner, "why": j.get("why", ""),
                     "new_answer": B[c["id"]].get("answer", ""), "base_answer": A[c["id"]].get("answer", "")})
        print(f"  {c['id']:<18} base {sb.get('task_fit')}/{sb.get('usefulness')}/{sb.get('calibration')}"
              f"  new {sn.get('task_fit')}/{sn.get('usefulness')}/{sn.get('calibration')}"
              f"  -> {winner:<4}  {j.get('why','')[:90]}")
        await asyncio.sleep(PACE_S)
    def mean(side, k):
        v = [r[side].get(k) for r in rows if isinstance(r[side].get(k), (int, float))]
        return round(statistics.mean(v), 2) if v else None
    summ = {"judge": JUDGE_MODEL, "judge_validated": validated, "cases": len(rows), "wins": tally,
            **{f"{side}_{k}": mean(side, k) for side in ("base", "new")
               for k in ("task_fit", "usefulness", "calibration")}}
    (OUT / f"pair-{base}-vs-{new}.json").write_text(json.dumps({"summary": summ, "rows": rows}, indent=1))
    print("\n" + json.dumps(summ))
    print(f"-> evals/quality/pair-{base}-vs-{new}.json")
    return 0


def summary(rows: list[dict]) -> dict:
    ok = [r for r in rows if r.get("answer")]
    judged_ok = [r for r in ok if r.get("task_fit")]          # 0 = judge never answered
    s = {k: round(statistics.mean(r[k] for r in (judged_ok if k in
                  ("task_fit", "usefulness", "calibration") else ok)), 2)
         for k in KEYS} if judged_ok else {}
    s["judged"] = f"{len(judged_ok)}/{len(ok)}"
    s["grounded"] = f"{sum(1 for r in ok if r.get('grounded'))}/{len(ok)}"
    s["errors"] = sum(1 for r in rows if not r.get("answer"))
    s["degraded"] = sum(1 for r in ok if r.get("degraded"))
    for k in ("tokens", "calls", "wall_s"):
        vals = [r[k] for r in ok if r.get(k)]
        s[f"median_{k}"] = statistics.median(vals) if vals else 0
    return s


def compare(a: str, b: str) -> None:
    A = json.loads((OUT / f"{a}.json").read_text())
    B = json.loads((OUT / f"{b}.json").read_text())
    sa, sb = A["summary"], B["summary"]
    print(f"{'metric':<16}{a:>12}{b:>12}")
    for k in [*KEYS, "judged", "grounded", "errors", "degraded",
              "median_tokens", "median_calls", "median_wall_s"]:
        print(f"{k:<16}{str(sa.get(k)):>12}{str(sb.get(k)):>12}")
    ra = {r["id"]: r for r in A["rows"]}
    print(f"\n{'case':<18}" + "".join(f"{k[:6]:>14}" for k in ("task_fit", "usefulness", "calibration")))
    for r in B["rows"]:
        o = ra.get(r["id"], {})
        print(f"{r['id']:<18}" + "".join(
            f"{str(o.get(k, '-')) + ' -> ' + str(r.get(k, '-')):>14}"
            for k in ("task_fit", "usefulness", "calibration")))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=time.strftime("%Y%m%d-%H%M"))
    ap.add_argument("--only", default="")
    ap.add_argument("--compare", nargs=2)
    ap.add_argument("--skip-validate", action="store_true")
    ap.add_argument("--no-judge", action="store_true", help="collect answers only")
    ap.add_argument("--pairwise", nargs=2, metavar=("BASE", "NEW"))
    a = ap.parse_args()
    if a.compare:
        compare(*a.compare); return 0
    if a.pairwise:
        from app import llm
        return await pairwise(*a.pairwise, llm)

    code, health = api("/api/health")
    if code != 200:
        print("server not reachable on :8077 - start it first"); return 1
    from app import llm
    validated = None if (a.skip_validate or a.no_judge) else await validate_judge(llm)

    only = {x for x in a.only.split(",") if x}
    rows = []
    for n, c in enumerate(x for x in CASES if not only or x["id"] in only):
        if n:
            await asyncio.sleep(PACE_S)
        r = await run_case(c, llm, judge_it=not a.no_judge)
        rows.append(r)
        print(f"  {r['id']:<18} fit={r.get('task_fit','-')} use={r.get('usefulness','-')} "
              f"cal={r.get('calibration','-')} read={r.get('readability','-')} "
              f"grounded={r.get('grounded')} {r.get('wall_s')}s {r.get('calls','-')} calls"
              + (f"  ERROR {r.get('error')}" if r.get("error") else ""))

    OUT.mkdir(exist_ok=True)
    s = summary(rows)
    (OUT / f"{a.tag}.json").write_text(json.dumps(
        {"tag": a.tag, "model": health.get("model"), "judge": JUDGE_MODEL,
         "judge_validated": validated, "summary": s, "rows": rows}, indent=1))
    print("\n" + json.dumps(s))
    print(f"-> evals/quality/{a.tag}.json")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
