# Whole-app sweep

`evals/sweep.py` — every route, end to end, on a throwaway database so it can
create, mutate, reset and delete without touching anyone's book.

```bash
DB_PATH=/tmp/t.db python evals/sweep.py            # 78 checks, no tokens
DB_PATH=/tmp/t.db python evals/sweep.py --agent    # adds the agent plane
```

It also runs inside `python -m evals.run` as the **App sweep** suite.

## Coverage

47 routes exist. The sweep touches 34 and asserts a real property of each —
not that it returned 200, but that the thing the UI reads is present and sane:
quotes carry a price *and* a name, bars are well-formed OHLCV, financials are
single-quarter rather than cumulative, analyst buckets are counted rather than
fitted, peers are *measured* (correlation plus observation count), the
portfolio total equals the sum of its rows, adding a ticker twice averages the
lot instead of duplicating it.

The 13 it does not touch are covered elsewhere or cannot be: OAuth
callbacks (need a live provider), the login and claim routes
(`login_probe.py`, `suite_claim`), the streaming agent endpoint, and FastAPI's
own `/docs`. A `every_route_touched` check fails the suite if a new route is
added and left out, so the gap cannot grow quietly.

## What this sweep found

**1. The daily brief ran twice per page load.** `loadBrief()` cached the
*result*, so two callers racing before the first response landed both saw
`null` and both fired. The dashboard and the brief sheet do exactly that on
every load, so the curator ran twice for one page view — double the tokens for
identical output. Fixed by caching the promise. Confirmed in a clean browser
tab: one `POST /api/agent/brief`, down from two.

**2. A rate-limited router answered a different question in silence.** When the
route LLM call failed, it fell through to a price-only fallback and returned a
confident answer that did not address the question. No error, no marker,
nothing in the trace. `AgentRun.degraded` now carries the reason, the trace
reads `ROUTER UNAVAILABLE`, and the client renders it under the answer.

**3. The fallback matched `WHEN` as a ticker.** It uppercased the question
first, so every word became a candidate — and WHEN is a real listed symbol. The
degraded answer to "**When** does NVDA report?" was a summary of a penny stock.
Now matched against the user's original casing, because people type tickers in
caps and that is the signal; a short stop-list handles genuine all-caps words
(AI, US, CEO).

**4. The asset cache-buster was frozen.** `app.js?v=1790903367` was hardcoded
days earlier and only harmless because static files are served `no-store`. The
server now stamps it from the build at serve time, so it cannot drift.

**5. Guests saw `BOOK $— / TODAY −$0.00` on the brief.** A zero reads as a
broken number, not an absent one. Replaced with what is actually true.

## What it did not find, and that matters

The agent golden set and the deterministic suites passed as they were. Of the
nine failures the first sweep reported, **five were bugs in the sweep itself** —
assertions written against shapes I assumed rather than checked: `/api/quotes`
returns normalised keys (`price`), not raw Yahoo ones; `distribution` is a list,
not a dict; `read_across` is a dict with a `peers` list; `PATCH /positions`
takes `ticker` in the body; the event study is wrapped in `result` and is
deliberately "does the *peer's* earnings move *this* ticker".

Checking the real response shape before writing the assertion would have caught
all five. A failing test is a claim about the code that still has to be earned.

## Rate limits and the golden set

Two golden cases failed as routing mistakes in one run and passed 5/5 and 3/5
on retry in isolation — the misses were quota, not judgement. The runner now
paces cases (`GOLDEN_PACE_S`, default 6s), retries once when the server reports
a degraded run, and if it still degrades reports it as
`DEGRADED (not a routing verdict)` rather than scoring it as a bad decision.
