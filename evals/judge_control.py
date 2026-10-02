"""Validate the judge before trusting its scores.

A judge that rates everything 4/5 is worse than no judge - it launders bad
output as good. These fixtures pair one solid answer with four deliberately
broken ones. If the judge cannot separate them, run.py reports its scores as
UNVALIDATED rather than printing them as fact.
"""
from __future__ import annotations
import asyncio, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend"))
try:                                   # evals run outside the app, load .env too
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass
from evals.rubric import judge  # noqa: E402

Q = "Is AMD expensive relative to what it actually earns, compared with NVDA?"
FINDINGS = [{"domain": "fundamentals", "ticker": "AMD", "evidence": [
                {"tool": "valuation_multiples",
                 "data": {"pe_trailing": 157.07, "pe_forward": 39.51, "market_cap": 1.01e12}},
                {"tool": "profitability", "data": {"net_margin": 15.58}}]},
            {"domain": "fundamentals", "ticker": "NVDA", "evidence": [
                {"tool": "valuation_multiples",
                 "data": {"pe_trailing": 29.22, "pe_forward": 14.71}},
                {"tool": "profitability", "data": {"net_margin": 63.66}}]}]

# Each fixture probes ONE dimension. Readability is deterministic, so the judge
# is not expected to catch number soup - the metric is.
FIXTURES = [
    ("good", "high", (
        "AMD trades at a trailing P/E of 157.07 against NVDA's 29.22, while earning a "
        "15.58% net margin versus NVDA's 63.66% - so the market is paying roughly five "
        "times more per dollar of current profit for the less profitable business. The "
        "forward multiples narrow that gap sharply, to 39.51 against 14.71, which means "
        "the premium rests on AMD delivering the earnings growth already assumed.")),
    ("ignores_question", "task_fit", (
        "NVIDIA Corporation operates as a computing infrastructure company. It offers "
        "graphics and compute platforms, and serves gaming, data centre, professional "
        "visualisation and automotive markets worldwide.")),
    ("number_soup", "readability", (
        "AMD 157.07 39.51 1.01e12 15.58 NVDA 29.22 14.71 63.66 per the data provided "
        "across both tickers for the periods reported in the evidence supplied.")),
    ("fabricated", "usefulness", (
        "AMD trades at a P/E of 157.07 while NVDA sits at 29.22. AMD's upcoming Zen 7 "
        "launch in March will add $40 billion of revenue and management has guided to a "
        "92% margin, which fully justifies the premium.")),
    ("gives_advice", "calibration", (
        "AMD at 157.07 trailing is far dearer than NVDA at 29.22. You should sell AMD "
        "and buy NVDA instead - it is clearly the better value here and the time to "
        "switch is now.")),
]


async def main() -> int:
    sys.path.insert(0, str(ROOT / "backend"))
    from app import llm
    from evals.rubric import readability
    if not llm.api_key():
        print("no API key - cannot validate the judge"); return 1

    scored = {}
    for name, probes, answer in FIXTURES:
        s = await judge(Q, answer, FINDINGS, llm)
        s["readability"] = readability(answer)["score"]
        scored[name] = s
        print(f"  {name:<18} task_fit={s['task_fit']} usefulness={s['usefulness']} "
              f"calibration={s['calibration']} readability={s['readability']}   {s['note'][:52]}")

    # each fixture must be caught on the axis it was built to break
    checks = [
        ("good answer scores high everywhere",
         all(scored["good"][k] >= 4 for k in ("task_fit", "usefulness", "calibration"))
         and scored["good"]["readability"] >= 4),
        ("off-topic answer craters task_fit",      scored["ignores_question"]["task_fit"] <= 2),
        ("number soup craters readability",        scored["number_soup"]["readability"] <= 2),
        ("fabrication craters usefulness",         scored["fabricated"]["usefulness"] <= 2),
        ("advice craters calibration",             scored["gives_advice"]["calibration"] <= 2),
    ]
    print()
    ok = True
    for label, passed in checks:
        ok &= passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")

    gap = (sum(scored["good"][k] for k in ("task_fit","usefulness","calibration"))/3
           - max(sum(scored[n][k] for k in ("task_fit","usefulness","calibration"))/3
                 for n in scored if n != "good"))
    print(f"\n  judged-mean gap good vs worst bad: {gap:+.1f}")
    print("  " + ("judge VALIDATED - each failure mode is caught on its own axis"
                  if ok else "judge NOT validated - scores are unreliable"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
