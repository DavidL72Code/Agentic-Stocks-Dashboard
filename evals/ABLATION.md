# Three-way ablation

Same tools, same model, same questions. Only the agent structure changes.

- `react`  — the original Colab shape: one agent per tool, looping think → act → observe
- `flat`   — one agent per tool, single shot (the tool is fixed, so the call is pure phrasing)
- `domain` — what ships: one agent per DOMAIN, picking 2–4 of ~9 tools and
             reasoning over all results together

> **Status: cost metrics are solid, quality metrics are provisional.**
> Two independent runs with different orderings produced nearly identical cost
> figures, so those are real. The quality rows rest on 2–3 scored runs per
> architecture — the Gemini free tier allows **500 requests per model per day**
> and the ablation exhausted it. Rerun once the quota resets for a full sample.

## Cost — reproducible across runs

| | ReAct per tool | Flat (1 agent = 1 tool) | Domain subgraphs |
|---|---|---|---|
| LLM calls / run — run A | 8.2 | 6.2 | **1.8** |
| LLM calls / run — run B | 7.0 | 6.0 | **1.7** |
| Tokens / run — run A | 4,463 | 2,454 | **1,302** |
| Tokens / run — run B | 3,578 | 2,092 | **1,361** |

Domain subgraphs answer the same questions in roughly **a quarter of the LLM
calls** and **~35% of ReAct's tokens**. Both runs agree to within ~15%, across
different execution orders, so this is the one result worth quoting.

## Latency — not conclusive

| | ReAct | Flat | Domain |
|---|---|---|---|
| Run A (s) | 32.6 | 13.9 | 3.3 |
| Run B (s) | 26.9 | 8.7 | 11.7 |

Flat and domain swap places between runs. That spread is API variance under
load, not architecture. No claim is made here.

## Quality — provisional, small n

| | ReAct | Flat | Domain |
|---|---|---|---|
| Validity /5 | 5.0 | 5.0 | 5.0 |
| Readability /5 | 4.7 | 4.5 | **3.3** |
| Conjunction rate | 33% | 100% | 67% |
| Scored runs | 3 | 2 | 3 |

**The conjunction row is not yet evidence.** "100%" is two samples. The metric
itself was rebuilt mid-ablation (see below), so these numbers come from a
handful of runs under a corrected definition and need a full sample before they
mean anything.

**Readability was a real finding against the shipped design — now addressed.**
Domain scored 3.3/5 against 4.7 and 4.5. The cause was structural: when a single
domain fired, the writer **short-circuited** and the specialist's `synthesize`
output became the answer verbatim. Specialists write denser prose than the
writer does, so single-domain answers never got the writing pass multi-domain
ones did.

**Fix:** the short-circuit is gone. The writer now runs on a lone finding as an
**editor** (`POLISH_PROMPT`) rather than a re-analyser — it keeps the
specialist's point, order, voice and figures, and changes only the prose. Two
guards: a rewrite more than 2.2x the original length is rejected as overreach,
and any editor failure falls back to the specialist's own words. Cost: one extra
LLM call on single-domain questions, which is what the short-circuit was saving.

*Not yet measured against live output* — the Gemini free-tier daily quota (500
requests/model) was exhausted when this landed. Logic is verified with a stubbed
model; the readability delta needs a rerun once quota resets.

## The conjunction metric was wrong first time

The first version counted connective words — "but", "while", "despite". It gave
domain **25%** against flat's **80%**, the opposite of the hypothesis. That was
an artifact, not a result: an architecture producing many one-tool findings
scores highly because the **writer** glues them together with "while", even
though every underlying claim came from a single tool. Domain short-circuits
the writer entirely and so got no credit.

It now measures the actual claim: **how many distinct tools' values appear in a
single sentence.** Validated against fixtures —

| Sentence | Tools in one sentence | Hit |
|---|---|---|
| "4.85% below its 52-week high on volume at 0.71× average" | 2 | yes |
| "Trades at $230.86. Volume is 0.71× average." | 1 | no |
| "Trades at $230.86, however that is only one datapoint" | 1 | no |

## Reproducing

```bash
python evals/ablation.py          # 5 questions x 3 architectures
python evals/ablation.py --full   # doubled sample
```

The runner rotates execution order, paces between runs, retries twice, and
**excludes any run whose LLM calls failed** — a fallback to raw tool JSON is an
infrastructure failure, not a bad answer, and scoring it would misattribute the
fault to whichever architecture happened to run last. It also refuses to
overwrite a good report with an empty one, and names a quota exhaustion
explicitly rather than reporting it as "did not complete".
