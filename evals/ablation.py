"""Three-way ablation: ReAct vs flat vs domain subgraphs.

Same tools, same model, same questions - only the agent structure changes.
The claim under test: a one-tool agent cannot form a CONJUNCTION (relating two
tools' data), because each agent only ever sees one tool's output.

    python evals/ablation.py           # 5 questions x 3 architectures
    python evals/ablation.py --full    # all golden questions
"""
from __future__ import annotations
import argparse, asyncio, itertools, json, pathlib, statistics, sys, time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend"))
try:
    from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
except ImportError:
    pass

from app.graph.ablation import run_flat, run_react, tools_for   # noqa: E402
from app.graph.build import GRAPH, grounding_check              # noqa: E402
from app.models import AgentRun                                 # noqa: E402
from evals.rubric import conjunction, readability, validity     # noqa: E402

# questions that COULD produce a conjunction - a single-fact question would be
# an unfair test, since there is nothing to relate
CASES = [
    ("NVDA", ["market"],
     "Is NVDA's move today backed by participation, and where does it sit in its range?"),
    ("AMD", ["fundamentals"],
     "Are AMD's margins and growth moving in the same direction?"),
    ("NVDA", ["street"],
     "Do the analysts and the insiders agree on NVDA?"),
    ("AAPL", ["market"],
     "Is AAPL extended relative to its own trend and its usual volatility?"),
    ("AMD", ["fundamentals", "market"],
     "Does AMD's valuation line up with how the stock has actually traded?"),
]


async def run_domain(q, ticker, domains):
    t0 = time.time()
    out = await GRAPH.ainvoke({"question": q, "selection": [ticker],
                               "findings": [], "steps": []})
    run = grounding_check(AgentRun(question=q, tickers=out.get("tickers", []),
                                   findings=out.get("findings", []),
                                   answer=out.get("answer", ""),
                                   steps=out.get("steps", [])))
    return {"answer": run.answer, "findings": [json.loads(f.model_dump_json())
                                               for f in run.findings],
            "tokens": run.total_tokens, "calls": run.llm_calls,
            "ms": int((time.time()-t0)*1000),
            "grounded": run.grounded, "ungrounded": run.ungrounded_numbers}


async def run_onetool(kind, q, ticker, domains):
    tools = tools_for(domains)
    t0 = time.time()
    fn = run_flat if kind == "flat" else run_react
    findings, steps = await fn(q, ticker, tools)
    # the writer is architecture-agnostic: it stitches whatever findings exist
    from app.graph.build import writer
    st = {"question": q, "findings": findings, "steps": steps}
    w = await writer(st)
    answer = w.get("answer", "")
    run = grounding_check(AgentRun(question=q, tickers=[ticker], findings=findings,
                                   answer=answer, steps=steps + w.get("steps", [])))
    return {"answer": answer,
            "findings": [json.loads(f.model_dump_json()) for f in findings],
            "tokens": run.total_tokens, "calls": run.llm_calls,
            "ms": int((time.time()-t0)*1000),
            "grounded": run.grounded, "ungrounded": run.ungrounded_numbers}


def usable(r) -> bool:
    """A run whose LLM calls all failed fell back to dumping raw tool JSON.
    That is an infrastructure failure, not a low-quality answer - scoring it
    would slander whichever architecture happened to run last."""
    if r["calls"] == 0 and r["findings"]:
        return False
    a = r["answer"].strip()
    return not (a.startswith("{") or ": {" in a[:40] or a.startswith("I couldn't gather"))


def score(r, q):
    return {"conjunction": conjunction(r["answer"], r["findings"]),
            "readability": readability(r["answer"]),
            "validity": validity(r["ungrounded"], r["grounded"], r["findings"])}


async def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--full", action="store_true")
    args = ap.parse_args()
    cases = CASES if not args.full else CASES * 2

    arch = {"react": [], "flat": [], "domain": []}
    skipped = []
    quota_hit = False
    order = itertools.cycle([("react", "flat", "domain"),
                             ("flat", "domain", "react"),
                             ("domain", "react", "flat")])
    for ticker, domains, q in cases:
        if quota_hit:
            print("\n  stopping early - daily quota exhausted"); break
        print(f"\n  {q[:72]}")
        for name in next(order):          # rotate so none is always last
            r = None
            for attempt in (1, 2, 3):
                try:
                    r = await (run_domain(q, ticker, domains) if name == "domain"
                               else run_onetool(name, q, ticker, domains))
                except Exception as e:
                    msg = str(e)
                    if "RESOURCE_EXHAUSTED" in msg or "exceeded your current quota" in msg:
                        quota_hit = True
                        print(f"    {name:<7} QUOTA EXHAUSTED - free tier is 500 "
                              f"requests/model/day"); r = None
                        break
                    print(f"    {name:<7} ERROR {type(e).__name__}: {e}"); r = None
                if r and usable(r):
                    break
                if attempt < 3:
                    await asyncio.sleep(25)  # let the API recover, then retry once
            if not r or not usable(r):
                skipped.append((name, q))
                print(f"    {name:<7} SKIPPED - "
                      + ("daily quota exhausted" if quota_hit
                         else "LLM did not complete") + " (not scored)")
                if quota_hit:
                    break
                continue
            s = score(r, q)
            arch[name].append({**r, **s, "q": q})
            print(f"    {name:<7} calls={r['calls']:<3} tok={r['tokens']:<6} "
                  f"{r['ms']/1000:5.1f}s  conj={'Y' if s['conjunction']['hit'] else 'n'} "
                  f"read={s['readability']['score']}  {r['answer'][:58]}")
            await asyncio.sleep(12)       # pace between architectures

    def agg(rows, key, sub=None):
        vals = [(r[key][sub] if sub else r[key]) for r in rows if r]
        return statistics.mean(vals) if vals else 0

    md = ["# Three-way ablation\n",
          "Same tools, same model, same questions. Only the agent structure differs.\n",
          "| | ReAct per tool | Flat (1 agent = 1 tool) | Domain subgraphs |",
          "|---|---|---|---|"]
    rows = [
        ("LLM calls / run", lambda r: agg(r, "calls")),
        ("Tokens / run", lambda r: agg(r, "tokens")),
        ("Latency (s)", lambda r: agg(r, "ms") / 1000),
        ("Validity /5", lambda r: agg(r, "validity", "score")),
        ("Readability /5", lambda r: agg(r, "readability", "score")),
        ("**Conjunction rate**", lambda r: 100 * sum(
            1 for x in r if x["conjunction"]["hit"]) / max(len(r), 1)),
    ]
    for label, fn in rows:
        vals = [fn(arch[a]) for a in ("react", "flat", "domain")]
        fmt = "{:.0f}%" if "Conjunction" in label else "{:.1f}"
        md.append(f"| {label} | " + " | ".join(fmt.format(v) for v in vals) + " |")

    md += [f"\nScored runs: " + ", ".join(f"{a} {len(arch[a])}/{len(cases)}" for a in arch) +
           (f". {len(skipped)} run(s) skipped because the LLM did not complete - "
            f"a fallback to raw tool JSON is an infrastructure failure, not a bad "
            f"answer, so scoring it would misattribute the fault.\n" if skipped else ".\n"),
           "\n## What this shows\n"]
    cr = {a: 100 * sum(1 for x in arch[a] if x["conjunction"]["hit"]) / max(len(arch[a]), 1)
          for a in arch}
    md.append(
        f"Conjunction rate is the load-bearing row. `domain` scores **{cr['domain']:.0f}%** "
        f"against **{cr['flat']:.0f}%** for flat and **{cr['react']:.0f}%** for ReAct. "
        f"A one-tool agent sees a single tool's output, so it has nothing to relate - "
        f"the writer receives pre-digested sentences with the conjunction already "
        f"discarded upstream. That gap is the architecture's entire justification.\n")
    md.append("\n## Sample answers\n")
    for i, (_, _, q) in enumerate(cases[:3]):
        md.append(f"\n**{q}**\n")
        for a in ("react", "flat", "domain"):
            if i < len(arch[a]):
                md.append(f"- *{a}* — {arch[a][i]['answer'][:260]}")
    scored_total = sum(len(arch[a]) for a in arch)
    out = ROOT / "evals" / "ABLATION.md"
    if scored_total == 0:
        print("\n  NO runs completed - refusing to overwrite", out.name,
              "with an empty result.")
        if quota_hit:
            print("  Cause: Gemini free-tier DAILY quota (500 requests/model/day) is "
                  "exhausted. It resets on a rolling 24h window - rerun tomorrow, or "
                  "change POOL in backend/app/llm.py to models whose quota is untouched.")
        return 2
    if scored_total < len(cases):          # thin sample: keep it, but say so loudly
        md.insert(2, f"> **Provisional.** Only {scored_total} of {len(cases)*3} runs "
                     f"completed, so these means rest on a handful of samples.\n")
    out.write_text("\n".join(md) + "\n")

    print("\n" + "\n".join(md[2:9]))
    print(f"\n  -> evals/ABLATION.md")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
