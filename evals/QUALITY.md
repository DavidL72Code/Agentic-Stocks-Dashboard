# Answer quality

The golden set checks mechanics: the right domain ran, the figures are
grounded, the refusals refuse. On 2026-10-03 it passed 13/13, with every
deterministic suite green (328/328). A suite that is fully green can no longer
point at anything to fix. `evals/quality.py` asks a different question: is the
answer actually good?

## Method

- **Cases.** Fifteen realistic questions, each stating what a good answer has
  to do. Two only make sense with the turn before them ("What about AMD?",
  "Why is that?"). Answers come from the live server, so each one is a real
  end-to-end run.
- **Judge.** A different and stronger model than the one that wrote the answer.
  It scores against the anchored rubric in `rubric.py`, and only after the
  `judge_control` fixtures show it can tell a good answer from each
  deliberately broken one.
- **Pairwise.** The two versions' answers to each question go to the judge side
  by side, in random order (`--pairwise BASE NEW`). That is one call per
  question, both sides are scored in the same context, and the judge says which
  answer a reader would rather have. Absolute scores saturate: most answers
  from either version get a 5.

**Free-tier limits shape the method — plan around them:**

- `gemini-3-flash` allows 20 requests a day, about one judged run.
- `gemma-4-31b-it` has plenty of quota but takes roughly ten minutes per verdict
  on real evidence.
- `gemini-3.5-flash-lite`, the agent, allows 500 a day. Two collection runs and
  the golden set use most of that.
- The rate limiter is per process. Two servers on one key get twice the
  per-minute budget the key actually has, so their answers degrade to fallbacks.
  Collect one server at a time.

## Baseline (b0258da)

Agent `gemini-3.5-flash-lite`, judged by `gemini-3-flash-preview`, which passed
validation. The judge hit its rate limit on the last 3 cases, so 12 of 15 are
judged and the means below cover those 12.

| task_fit | usefulness | calibration | readability | grounded | median wall | median calls |
|---|---|---|---|---|---|---|
| 4.75 | 4.25 | 4.75 | 4.75 | 15/15 | 10.0s | 4 |

"Median calls" undercounts: until a later fix, each specialist subgraph's
nodes overwrote one another's steps, so tool-selection calls were never
recorded. Real runs make roughly 6-11 calls.

The high means hide five specific failures, and those were the work:

| Case | What happened | Cause | Fix |
|---|---|---|---|
| `followup_why` | "Why is that?" was **refused** as off-topic | Each question went to the server alone; no conversation reached the router | The last 3 turns are sent as `history`. The router reads them as a transcript (data, not instructions) and returns a standalone rewrite, which the UI shows as "Read as: …" |
| `compare_pair` | Judge: use 3, cal 3, "massive date discrepancy" — MSFT growth came from **2010** filings | `edgar.concept` took the first XBRL tag with any data; MSFT left `Revenues` around 2010 | Fetch every candidate tag and keep the series that is current. Reject quarters over 200 days old |
| (same) | YoY compared against **five** quarters back whenever Q4 was missing | 10-Ks report the year, not Q4, and growth used "four rows back" | Derive Q4 as the year less its three quarters; match YoY and QoQ by date, never by position |
| `leverage` | The agent wrote "a debt-to-equity ratio of **16.97**" for a balance sheet with more cash than debt | Yahoo's `debtToEquity` is a percent and was passed through raw | The tool now emits `debt_to_equity_ratio` (0.17), `debt_as_pct_of_equity`, `net_cash_usd`; the UI shows 0.17× and the net cash |
| `street_change` | Judge: fit 3, use 2 — ignored "has that changed recently" | Nothing required every part of a two-part question to reach a specialist | Rule added to the router, specialist and writer prompts: every part lands somewhere, or the answer says it has no data for it |

Found by reading code, not by the judge:

- **The writer lost findings on wide fan-outs.** Its payload was
  `json.dumps(...)[:16000]`, so on a five- or six-domain run the last findings
  were cut off. Every narrative is now kept, and evidence is trimmed per finding
  to fit.
- **The UI never sent the user's selection.** `streamAsk` posted only
  `{question}`, so "Analyse selected", and any question asked on a ticker page,
  reached the router with no ticker. The selection is now sent as `tickers`
  (hard), and the page's ticker as `context_tickers` (soft: "compare with AMD"
  still fetches AMD).
- **A rate-limited run showed the user raw JSON.** The router failed on a
  per-minute 429 and the user got a raw JSON dump. A 429 now waits the time
  Gemini names (up to 30s) and retries; a daily cap fails at once. When a model
  is down, the fallback text is readable.

## After — status

All of these are in place and checked deterministically. Each new guard has a
regression case, and `negative_control.py` sabotages it and shows the case going
red:

- `edgar_current_tag`
- `edgar_no_missing_q4`
- `edgar_q4_derived`
- `growth_is_current`
- `leverage_ratio_not_percent`
- `writer_keeps_every_finding`

The follow-up and context cases were also run end to end:

- "Why is that?" after an AAPL analyst question → read as *"Why do analysts
  maintain a positive view and a high price target on AAPL?"*, routed to street
  and fundamentals, and answered.
- "What about AMD?" after an NVDA valuation question → read as *"How is AMD
  performing relative to its peers, and what is its valuation relative to its
  earnings?"*
- "Is it expensive relative to what it earns?" on the NVDA page → NVDA,
  fundamentals and peers.

**Not yet measured:** the judged pairwise comparison, which is the number that
would say how much the answers improved overall. The agent model's daily quota
ran out partway through collecting both versions' answers. To run it once the
quota resets, collect one server at a time with nothing else calling the model:

```bash
REPO=$PWD
git worktree add /tmp/monsoon-base b0258da && ln -s "$REPO/.env" /tmp/monsoon-base/.env
(cd /tmp/monsoon-base && TURSO_DATABASE_URL= DB_PATH=/tmp/base.db \
   "$REPO/.venv/bin/uvicorn" app.main:app --app-dir backend --port 8079) &
EVAL_BASE=http://localhost:8079 TURSO_DATABASE_URL= python -m evals.quality --tag base --no-judge
TURSO_DATABASE_URL= python -m evals.quality --tag new --no-judge
JUDGE_MODEL=gemini-3.6-flash python -m evals.quality --pairwise base new
```

The three follow-up and context cases were added to `golden.yaml`
(`followup_resolves`, `context_ticker`, `context_not_a_fence`). They run with
`evals.run --agent`, which was not re-run for the same quota reason.
