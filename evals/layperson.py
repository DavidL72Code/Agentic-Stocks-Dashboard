"""Would someone who has never invested understand this answer?

The other checks read the numbers (grounded?), the shape (bullets?) and a word
list (jargon?). None of them reads the answer the way a person does - and an
answer can pass all three and still say "did -9.1 points worse than expected"
or paste a definition into the middle of a sentence. This asks a model to read
it as that person: list every word or phrase it would not understand or that
reads awkwardly, say in one sentence what it learned, and score whether it
could explain the answer to a friend.

The judge has to pass its controls first - a jargon-heavy answer must score
low and a plain one high - or its scores are not reported.

    python -m evals.layperson answers.json      # [{"q": ..., "answer": ...}, ...]
"""
from __future__ import annotations
import asyncio, json, pathlib, statistics, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend"))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass
from app import llm  # noqa: E402
from app.graph.plain import report as plain_report  # noqa: E402

JUDGES = ("gemini-3-flash-preview", "gemini-3.5-flash-lite")
PINNED: str | None = None          # --judge MODEL: one judge for every file being compared

PROMPT = """You are an adult with a job and a bank account. You know what a
company, a stock, a share price, sales, profit, debt and a percentage are, and
you have heard of the stock market - but you have never invested and you do not
know any finance terms (beta, P/E, margins, consensus, volatility and the like).
A friend asked a stock question and got the answer below. Read it as yourself.

1. List EVERY word or phrase you would not understand, or that reads awkwardly
   or wrong (a broken sentence, a definition pasted in brackets, a double
   negative). Quote them exactly. An empty list means none.
2. In one sentence, say what the answer told you, in your own words.
3. Score 1-5: could you explain this answer to someone else?
   5 = yes, easily; 4 = mostly, one thing was unclear; 3 = only the gist;
   2 = I got lost; 1 = I did not understand it.
4. Does the first sentence actually answer the question? true / false.

Reply with ONLY JSON:
{"unclear": ["..."], "told_me": "...", "score": n, "first_line_answers": true}"""

CONTROLS = [
    ("jargon", "How is NVDA doing against its peers this year?",
     "Nvidia outperformed its peer median with a 3.5% beta-adjusted excess return, whereas Applied "
     "Digital remains vulnerable to sharp swings tied to debt-funded AI infrastructure sentiment and "
     "elevated realised volatility despite a strong buy consensus.", (1, 2)),
    ("plain", "How is NVDA doing against its peers this year?",
     "Nvidia's stock has risen more than similar companies' this year.\n\n- It is up 15% this year; "
     "the typical similar company is up 8%.\n- It moves more than the market does, so bigger gains "
     "are expected in a rising market.\n\nWhat would change this: its earnings report on November 17th.",
     (4, 5)),
]


async def judge(q: str, answer: str) -> dict:
    body = f"Question: {q}\n\nAnswer:\n{answer}"
    last = None
    for model in ((PINNED,) if PINNED else JUDGES):
        try:
            r = await llm.call(PROMPT, body, model=model)
            j = llm.parse_json(r.text) or {}
            if isinstance(j.get("score"), (int, float)):
                return {**j, "judge": model}
        except Exception as e:          # quota on the stronger judge: fall back
            last = e
    return {"error": str(last or "no verdict")[:160]}


async def validate() -> bool:
    ok = True
    for name, q, a, (lo, hi) in CONTROLS:
        v = await judge(q, a)
        good = lo <= (v.get("score") or 0) <= hi
        ok &= good
        print(f"  control {name:<7} judge={v.get('judge')} score={v.get('score')} expected {lo}-{hi} "
              f"{'OK' if good else 'FAILED'}  unclear={v.get('unclear')}")
    return ok


async def main(path: str) -> int:
    rows = json.loads(pathlib.Path(path).read_text())
    print("validating the judge...")
    # a judge is a sample, not a constant: one retry, then refuse to score
    if not await validate() and not await validate():
        print("judge failed its controls twice - scores would mean nothing"); return 1
    out = []
    for r in rows:
        v = await judge(r["q"], r["answer"])
        pl = plain_report(r["answer"])
        out.append({"q": r["q"], **v, "jargon": [j["term"] for j in pl["jargon"]], "shaped": pl["shaped"]})
        print(f"\n{v.get('score')}/5  first-line-answers={v.get('first_line_answers')}  {r['q']}\n"
              f"   unclear: {v.get('unclear')}\n   told me: {v.get('told_me')}")
    scores = [x["score"] for x in out if isinstance(x.get("score"), (int, float))]
    summ = {"answers": len(out), "judged": len(scores),
            "mean_score": round(statistics.mean(scores), 2) if scores else None,
            "fully_clear": sum(1 for x in out if not x.get("unclear")),
            "first_line_answers": sum(1 for x in out if x.get("first_line_answers") is True),
            "jargon_terms": sum(len(x["jargon"]) for x in out)}
    print("\n" + json.dumps(summ))
    dest = pathlib.Path(path).with_suffix(".layperson.json")
    dest.write_text(json.dumps({"summary": summ, "rows": out}, indent=1))
    print(f"-> {dest}")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--judge" in args:
        i = args.index("--judge"); PINNED = args[i + 1]; del args[i:i + 2]
    sys.exit(asyncio.run(main(args[0])))
