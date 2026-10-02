# Agentic Fintech — Design

A personal stock tracking terminal — the shell of a brokerage app, with a
multi-agent research system as the engine. You populate a watchlist; the system
decides what's worth investigating on each ticker and surfaces it; you can also
just ask.

**The multi-agent system is the product.** The broker-style UI exists to make
that system's output land somewhere useful and legible — not the other way
round. Every design decision below resolves in favor of the agents being
*visible*.

Built as a portfolio project: `docker compose up`, free-tier keys only.

---

## 1. Positioning

**A trading account with no trading.** Watchlist, positions, candlestick charts,
financials tabs — the whole familiar surface — except the thing it does is
*research*, not order entry. No broker integration, no orders, ever (§13).

Three things a reviewer should walk away able to say:

1. They built a hierarchical multi-agent system and can explain why each agent
   boundary is where it is.
2. They dropped ReAct *and* one-agent-per-tool on purpose, and measured all
   three designs.
3. They built a UI where you can watch the agents decide — not a chatbot with a
   stock ticker glued on.

---

## 2. Core decision: domain agents, not tool agents

### 2.1 Why one-agent-per-tool was wrong

The prototype had ten specialists, one tool each. Three problems, only one of
which is cost.

**Cross-tool reasoning becomes structurally impossible.** A price specialist
seeing only `$182.40, +3.2%` cannot say the stock is near its 52-week high on
declining volume — the range and the volume lived in different agents that never
spoke. Every interesting market observation is a *conjunction*, and a one-tool
agent can't form one. The writer can't recover it either: it receives ten
pre-digested sentences, so the conjunction was already discarded upstream.

**No decision is left to make.** One tool, known ticker — the "reasoning step"
is string formatting with extra latency. That was the right reason to drop
ReAct; the same logic kills the per-tool agent.

**It doesn't scale.** Ten tools then; ~45 for the dashboard below. Forty-five
agents is not a design.

### 2.2 The shape instead

Five **domain agents**, each owning a coherent slice of question-space and a
catalog of 6–10 tools. Each is a compiled subgraph:

```
        ┌──────────── domain subgraph ────────────┐
task ──▶│  select  ──▶  gather  ──▶  synthesize   │──▶ DomainFinding
        │  (LLM,      (no LLM,      (LLM, sees    │
        │   cheap,     parallel      ALL raw      │
        │   cached)    tool calls)   results)     │
        └─────────────────────────────────────────┘
```

- **`select`** — the real decision this design creates: given the domain's tool
  catalog and the sub-question, pick 2–4 of 8 tools. Kept cheap via constrained
  structured output (enum list), a small model, a rule fast path, and a
  selection cache keyed on `(domain, normalized_question)` — dashboard tiles and
  alerts are fixed intents and pay for selection once, ever.
- **`gather`** — pure Python. `asyncio.gather`, backoff, cache, provider
  fallback. No LLM.
- **`synthesize`** — one call seeing **every** selected tool's raw output at
  once, prompted explicitly to hunt for conjunctions and tensions.

### 2.3 Honest accounting

| | flat (10 tool-agents) | domain subgraphs |
|---|---|---|
| LLM calls, 3-domain question | 1 + 6 + 1 = **8** | 1 + ~2 select + 3 synth + 1 = **~7** |
| LLM calls, full analysis | **12** | **~10** |
| Tool calls | every planned tool fires | selector prunes; ~40% fewer |
| Writer input | 10 thin sentences | 3–5 rich findings |
| Cross-tool conjunctions | **impossible** | the point |
| Cost of a new tool | a new agent | one catalog entry |

Call count drops modestly — `select` eats much of the saving. The real wins are
tool-call volume and the fact that most calls now see enough context to say
something non-obvious. **Measured, not assumed**: §10.

---

## 3. The five domains

Grouped by **question semantics**, not data source. The provider cache makes
shared fetches free (two domains reading the same `.info` = one network call),
so boundaries follow how people actually think.

**`market`** — price action & technicals
`quote` · `price_series` (OHLCV, any interval) · `range_52w` ·
`moving_averages` · `rsi` · `volatility` (realized vol, beta) ·
`volume_profile` (incl. unusual volume) · `drawdown_from_high` ·
`relative_strength` (vs SPY / sector)
→ *"near highs on thin volume"; "oversold into 50-day support"*

**`fundamentals`** — the business
`income_statement` · `balance_sheet` · `cash_flow` · `valuation_multiples`
(P/E, P/S, EV/EBITDA, PEG) · `profitability` (margins, ROE, ROIC) ·
`growth_rates` · `leverage_liquidity` · `dividend_economics` · `share_count`
(buybacks/dilution) · `peer_valuation`
→ *"margins expanding while revenue growth decelerates"*

**`street`** — what everyone else thinks and is doing
`news` (+sentiment) · `analyst_ratings` · `rating_changes` (90d) ·
`price_targets` · `institutional_holders` · `institutional_flow` (ΔQoQ) ·
`insider_transactions` · `short_interest` · `options_positioning` *(optional)*
→ *"analysts raising targets while insiders sell"*

**`events`** — the calendar
`next_earnings` · `earnings_surprise_history` · `ex_dividend_date` · `splits` ·
`recent_filings` · `corporate_actions` · `macro_calendar`
→ *"earnings in 4 days, missed 3 of last 4"*

**`portfolio`** — your actual money
`positions` · `unrealized_pnl` · `realized_pnl` · `allocation` ·
`concentration_risk` · `portfolio_beta` · `correlation_matrix` ·
`dividend_income_projection` · `contribution_to_return`
Runs on user data in Postgres; the only auth-scoped domain.

A sixth, `screen` ("find me stocks that…"), is a different graph shape
(filter → enrich → rank) — Phase 6.

---

## 4. Two planes (what makes the dashboard affordable)

The binding constraint: **a 20-ticker watchlist must not cost 20 graph runs on
page load.** If tiles call agents, the product is dead on arrival.

**Data plane — no LLM, ever.** Tiles, candles, financial tabs, sparklines, P&L,
alert *evaluation*. Reads the provider layer and cache directly; sub-100ms warm.
90%+ of all reads.

**Agent plane — LLM, on demand or scheduled.** Fires only on: a user question,
an explicit "analyze" click, the watch loop (§6.2), or an alert configured to
want narrative.

Both sit on one provider layer, so the agent plane usually reads cache the data
plane already warmed. Opening a watchlist costs $0 and one batched provider
sweep; asking about a row costs one graph run.

---

## 5. Data layer

```
core/data/
  models.py     # pydantic DTOs; every record carries as_of, source, is_stale
  base.py       # Provider protocol
  yfinance_.py  # primary: historical bars, fundamentals, holders
  finnhub_.py   # fallback + realtime: free-tier WS trade stream, news, estimates
  derived.py    # computed: RSI, MAs, vol, beta, correlation, CAGR
  cache.py      # Redis, per-type TTL
  registry.py   # ordered fallback, normalize, never raise
```

Fixes from the prototype:

- **Five redundant `.info` fetches per question** — `company_financials`,
  `analyst_ratings`, `short_interest`, `sector_industry`, `range_52w` each
  called it independently. Now one fetch per ticker per request, shared.
- **Retries that couldn't work** — `MAX_TOOL_RETRIES=3` re-issued the *identical*
  call with no backoff, so against a rate limit attempts 2 and 3 failed
  identically. Now: jittered exponential backoff for transient errors
  (timeout/429/5xx) only; schema errors fall straight through to the next
  provider.
- **Stringly-typed results** — `result.startswith("Error")` breaks the first
  time a headline begins with "Error", and fails *silently*. Typed DTOs plus a
  `ToolFailure` type fix it, and unlock numeric grounding checks (§10).
- **No freshness** — nothing carried a timestamp, so nothing could say "as of."

TTLs: quote 60s (or WS-pushed) · news 15m · calendar 6h · fundamentals 24h ·
sector 7d. On total failure serve stale with `is_stale=True` and show it
("from 3h ago — live fetch failed"). Degrading beats a blank card.

**Realtime.** Free tiers are delayed ~15min. Finnhub's free tier includes a
websocket trade stream for US equities — use it for last price, yfinance for
historical bars. The UI badges `● live` vs `◐ delayed 15m` per ticker, honestly
and per-source. Never imply realtime we don't have.

---

## 6. Two entry points, one set of agents

The same five domain subgraphs serve both loops. That reuse is the main
structural payoff of the domain design.

### 6.1 Ask loop — user-initiated

```
START ─▶ guard ─(off-topic)─▶ refuse ─▶ END
          │
          ▼
        route ─(ambiguous)─▶ clarify ─▶ END
          │   Send × (ticker × domain)
     ┌────┼────┬────────┬────────┬─────────┐
     ▼    ▼    ▼        ▼        ▼         ▼
   market fund street  events portfolio      ← subgraphs
     └────┴────┴────────┴────────┴─────────┘
                    │
                    ▼
                 writer ─▶ END
```

**`guard`** — cheap non-LLM pass; off-topic/abuse/advice-seeking stopped before
a planner call is spent.
**`route`** — one call → `{tickers[], tasks[{domain, ticker, question, tools?}]}`.
Resolves symbols against a real lookup (not model memory) so hallucinated
tickers fail cheaply. Dispatches `[Send(t.domain, t) for t in tasks]`.
**`writer`** — prose with inline citation markers keyed to evidence ids.

Dynamic fan-out is what makes multi-ticker possible at all: the prototype's ten
hardcoded nodes made "compare AAPL and MSFT" *architecturally* impossible, and
adding one tool meant edits in eight places. Now 2 tickers × 3 domains = 6
parallel subgraph runs, and a new tool is one catalog entry.

### 6.2 Watch loop — system-initiated

This is "the system decides to track info," and it's the most genuinely agentic
part of the product.

```
scheduler ─▶ trigger scan ─▶ curator ─▶ [domain subgraphs] ─▶ insight ─▶ cards
            (data plane,     (LLM:       (only the ones        writer     + push
             no LLM)          what's      curator chose)
                              worth it?)
```

**`trigger scan`** — data plane, runs often, costs nothing: % move vs trailing
vol, volume anomaly, earnings proximity, rating change, short-interest delta,
news volume spike, position-size drift.

**`curator`** — the policy agent. Given a ticker's triggers, its recent insight
history, and whether the user holds it, decide **whether to investigate at all**
and **which domains to spend on**. Earnings in 3 days → `events` + `street`.
5% drop on 3× volume → `market` + `street`. Nothing notable → *spend nothing*,
which is the correct and most common answer. Also suppresses repeats: it sees
what it already told you this week.

**`insight` writer** — writes a short, dated card. Narrates **deltas, not
state** — "two upgrades, short interest down 1.2pts, earnings moved up a week"
— by diffing against yesterday's snapshot.

The curator saying *no* most of the time is the feature. A tracker that
comments on everything is noise; the agent's job is knowing when to stay quiet,
and the trace panel shows it deciding that.

### 6.3 Shared state

```python
class DomainFinding(TypedDict):
    domain: str; ticker: str
    narrative: str
    evidence: list[ToolResult]        # raw DTOs → evidence cards
    tools_used: list[str]
    tools_skipped: list[str]          # surfaced in the trace on purpose
    as_of: datetime
    confidence: Literal["high","partial","unavailable"]
```

`tools_skipped` is carried through state rather than dropped — it's the most
legible proof that routing actually happened.

**Budget guard.** Fan-out capped (default 12 subgraph runs/run), token ceiling
per run. On overflow, drop lowest-priority domains and *say so in the answer*
rather than silently truncating.

---

## 7. The UI

### 7.1 Principle: broker chrome, agent core

A faithful Webull clone would hide the agents, which defeats the point. So: the
**layout** is broker-familiar (instantly legible, no explanation needed), but
the **agent rail is permanent**, not a tab you have to find, and anything an
agent authored is visually distinct with a `show work` affordance that opens its
trace.

Rule: **no agent-written text appears without a path to its evidence.**

### 7.2 Layout

```
┌────────────────────────────────────────────────────────────────────────┐
│ Portfolio  $128,430.22  +$1,204.55 (+0.95%)     [Watch][Ask][Trace] ⚙ │
├──────────────┬─────────────────────────────────────┬───────────────────┤
│ WATCHLIST    │ NVDA  Nvidia Corp                   │ AGENT ACTIVITY    │
│ ●NVDA 182.40 │ $182.40  +3.21 (+1.79%)   ● live    │ ───────────────── │
│  ▁▃▅▇ +1.8%⚡│ ┌─────────────────────────────────┐ │ ⬤ market   2 of 9 │
│ ●AAPL 214.10 │ │   candlesticks + volume pane    │ │ ⬤ street   3 of 9 │
│  ▇▅▃▁ -0.4%  │ │   MA50/MA200 overlay, RSI sub   │ │ ○ events   skipped│
│  MSFT 501.22 │ └─────────────────────────────────┘ │   "no catalyst    │
│  ...      ⚡ │ 1D 5D 1M 6M 1Y 5Y  ·  MA RSI Vol    │    within 30d"    │
│              │ ─────────────────────────────────── │ ───────────────── │
│ [+ ticker]   │ Overview│Financials│News│Analysts│  │ ▸ INSIGHT · 2h    │
│              │ ─────────────────────────────────── │  Two upgrades and │
│ POSITIONS    │ Mkt cap  P/E    Rev YoY   Op margin │  short interest   │
│  NVDA 50sh   │  4.41T   52.1    +62%      54.2%    │  down 1.2pts...   │
│   +$2,140 ▲  │ ─────────────────────────────────── │  [show work] [×]  │
│  AAPL 20sh   │ ┌ quarterly revenue bars ─────────┐ │ ───────────────── │
│   -$88 ▼     │ └─────────────────────────────────┘ │ Ask about NVDA…   │
└──────────────┴─────────────────────────────────────┴───────────────────┘
```

**Left — watchlist & positions.** Tickers *you* add. Row = symbol, last, %chg,
sparkline, and a ⚡ badge when the curator has an unread insight. Positions
below with cost basis and unrealized P&L. Pure data plane.

**Center — ticker detail.** Candlestick chart with timeframe tabs, volume pane,
MA overlays, RSI subchart. Beneath it, broker-standard tabs — Overview /
Financials / News / Analysts / Events — each backed by the *data plane*, so
they're instant and free. Each tab header carries a small `⟳ analyze` button:
that's the one place a tab crosses into the agent plane, running just that
domain's subgraph and pinning the result to the tab.

**Right — the agent rail.** Permanent. Three stacked zones:
1. **Live run** — domain nodes lighting up as they execute, each showing
   `n of m tools` and expanding to reveal *which* tools `select` chose, which it
   skipped, and the stated reason. This is the pitch in one screenshot.
2. **Insight feed** — dated curator cards, dismissible, each with `show work`.
3. **Ask box** — scoped to the current ticker by default, free-form otherwise.
   Streams tokens; citation chips open evidence.

**Trace view** (full-screen, from the top bar) — the run as a DAG: `route` →
fanned-out subgraphs → `writer`, with per-node tokens / latency / cost and the
full prompt and raw tool output per node. The honest-engineering exhibit.

### 7.3 Stack

Next.js + Tailwind + shadcn/ui. **TradingView `lightweight-charts`** for
candles/volume (the Webull look, and it's the right tool); **Recharts** for
sparklines, revenue bars, and allocation donuts. SSE for agent run streaming,
websocket for price ticks. Dark-first — every broker app is, and the accent
color is reserved *exclusively* for agent-authored surfaces so the seam is
unmistakable.

---

## 8. Features

**Core surfaces** — watchlists (multiple), ticker detail, portfolio (CSV import
or manual; allocation, sector exposure, concentration warnings, projected
dividend income), compare view (N tickers × domains).

**Where agents earn their keep**
- **Curated insights** (§6.2) — the system's own take, unprompted.
- **"What changed"** — daily snapshots; agents narrate deltas, not state.
  Nearly free once snapshots exist, and a plain stock app can't do it.
- **Morning digest** — one batched sweep over a watchlist, not N runs.
- **Alerts** — price/%-move/volume/earnings-proximity/rating-change/short-spike.
  Evaluated on the data plane; only optional narrative touches an LLM.
- **Thesis tracking** — you write "I hold NVDA because datacenter growth and
  margin expansion"; the agent periodically re-checks whether evidence still
  supports it and flags contradictions. Mostly reuse.
- **Export** — any run to Markdown/PDF with citations intact.

**Worker** — APScheduler locally (arq if it outgrows that): trigger scans,
snapshots, curator passes, digests, alert evaluation.

---

## 9. Repo layout

```
.
├── docker-compose.yml           # api, worker, web, postgres, redis
├── api/
│   ├── main.py                  # FastAPI; SSE runs, WS prices
│   └── routes/                  # ask, watchlists, portfolio, alerts, insights
├── worker/                      # scheduler: triggers, curator, digests, alerts
├── core/
│   ├── graph/
│   │   ├── ask.py               # ask loop
│   │   ├── watch.py             # watch loop
│   │   ├── state.py
│   │   ├── nodes/               # guard, route, clarify, curator, writer
│   │   └── domains/
│   │       ├── base.py          # select→gather→synthesize factory
│   │       └── {market,fundamentals,street,events,portfolio}.py
│   ├── tools/                   # registry: typed fns + metadata
│   ├── data/                    # providers, cache, DTOs   (§5)
│   ├── prompts/                 # version-tagged, one per agent
│   ├── llm.py                   # clients, Redis rate limiter, token accounting
│   └── telemetry.py             # structlog + per-node run_steps
├── evals/                       # golden.yaml, metrics.py, run.py
├── web/                         # Next.js
└── tests/
```

Each domain file is *only* a tool catalog plus three prompts; `base.py` builds
the subgraph. Adding a domain is one file.

Backend: FastAPI · LangGraph · Pydantic · Redis · Postgres
(`langgraph-checkpoint-postgres`). Gemini free tier default, OpenAI-compatible
client so swapping is a base-url change. Cheap model for `guard`/`select`/
`curator`, stronger for `synthesize`/`writer`.

---

## 10. Measurement

**Three-way ablation** over the golden set — the README centerpiece, and the
reason to keep the old paths behind flags:

| | ReAct per tool | flat 1-agent-per-tool | domain subgraphs |
|---|---|---|---|
| LLM calls / run | | | |
| Tokens / run | | | |
| p50 / p95 latency | | | |
| Tool calls / run | | | |
| Numeric grounding | | | |
| Conjunction rate¹ | | | |

¹ share of golden questions whose reference answer requires relating two tools'
data. The flat design should score near zero **by construction** — that's the
hypothesis this redesign rests on, so it has to be a real number.

**Golden set** — ~60 questions labeled with expected domains *and* expected
tools, so router and selector score separately.

| Metric | How |
|---|---|
| Numeric grounding | every number in the answer appears in some evidence DTO — pure parse check, no judge |
| Router accuracy | precision/recall of domains vs labels |
| Selector accuracy | precision/recall of tools within domain |
| Curator precision | of insights emitted, how many a human labels worth reading — plus **silence rate**, since staying quiet is the desired default |
| Refusal correctness | off-topic / advice-seeking declined; on-topic not |
| Graceful degradation | inject provider failures; assert "unavailable", never an invented number |
| Cost & latency | p50/p95, tokens, $ per run |

---

## 11. Phases

1. **Tools + data plane.** Providers, DTOs, Redis cache, real backoff, ~45 tools
   incl. derived indicators. No agents. *Demo: CLI dumps any domain for any
   ticker in <1s warm.*
2. **Domain subgraphs + ask loop.** `base.py` factory, five domains, guard/route/
   writer, `Send` fan-out. *Demo: "compare AAPL and MSFT on valuation and what
   the street thinks."*
3. **Serve it.** FastAPI, SSE, price WS, Postgres checkpointer, thread
   follow-ups, Redis rate limiter, budget ceilings.
4. **The terminal.** Next.js: watchlist, candlestick chart, financial tabs,
   positions, agent rail, evidence cards, trace view.
5. **Watch loop.** Worker, snapshots, triggers, curator, insight cards, digests,
   alerts, thesis tracking.
6. **Prove it.** Three-way ablation, golden set in CI, cost dashboard, README.

Phase 6 is the tempting cut. Don't — almost nobody does it, and it's the
strongest signal in the repo.

---

## 12. Compliance & safety

- **No order entry, no broker credentials, no brokerage integration** — ever.
  The app looks like a trading account and deliberately cannot trade. Stated
  plainly in the UI so the resemblance never misleads.
- Persistent "informational only, not investment advice" disclaimer on-screen,
  not just in a system prompt users never see.
- Per-source delay badging (§5). Never imply realtime we don't have.
- `guard` is a real node plus a post-hoc check on writer output. **The `street`
  domain ingests untrusted third-party text — headlines are data, never
  instructions**; a prompt-injected article must not be able to steer the writer
  or the curator.
- Portfolio data is user-scoped and never leaves the deployment; it's the only
  genuinely sensitive data here.
- Refusals: one plain sentence plus what the system *can* do. No lecturing.

---

## 13. Open questions

1. **Does `select` earn its call?** If `route` can name tools accurately enough,
   domains collapse to gather→synthesize. A/B in Phase 6 — the fast path may end
   up being the whole path.
2. **Curator cadence and budget.** Per ticker per day? On trigger only? A
   20-ticker watchlist × daily curator passes is the main recurring cost in the
   whole system — needs a hard ceiling and probably a priority queue favoring
   held positions.
3. **Domain granularity.** Is `street` too broad — news sentiment and
   institutional flow are fairly different questions. Splitting is cheap;
   over-splitting reintroduces the one-tool problem.
4. **Ticker resolution.** "Apple" is easy; "the Google one that isn't voting"
   isn't. Needs a real lookup service.
5. **Free-tier ceilings.** Finnhub is 60 req/min and its WS caps concurrent
   symbols. A 50-ticker watchlist needs batching, staggering, or a third
   fallback.
6. **Snapshot retention.** How much history does "what changed" need before
   storage is a real cost?

---

# 14. Addenda — daily brief, `analyze`, and read-across

## 14.1 Daily Brief (the landing page)

Replaces the ticker detail page as the default view on first entry each day.
It is the **watch loop's** output (§6.2), rendered.

**Sections**
1. **Portfolio header** — value, 1d/1w change, biggest contributor and detractor.
2. **What changed** — per holding, deltas since yesterday's snapshot, not state.
3. **Ranked insights** — curator output, most material first.
4. **Cross-holding observations** — the things only a portfolio view can see:
   concentration, correlation clusters, shared factor exposure.
5. **Coming up** — earnings / ex-div inside 7 days across all holdings.
6. **Looked at, nothing to say** — the tickers the curator checked and dismissed.
   Keep this visible: it's what makes the silence trustworthy rather than
   suspicious.

**Cost control — one batched run, not N runs.** This is the part that has to be
right or the feature is unaffordable:

```
trigger scan (code, free) over ALL holdings
        ↓  ranked trigger list
curator — ONE call, sees all 20 tickers' triggers together
        ↓  picks ~5 worth investigating, with reasons
domain subgraphs — only for those ~5
        ↓
brief writer — ONE call
```

≈ 1 + (5 × ~2) + 1 ≈ **12 LLM calls per day, flat**, regardless of watchlist
size. The naive version — curator per ticker — is 20+ calls before any
investigation happens, and scales with the watchlist. Batching the curator is
what makes the daily brief viable.

Generated overnight by the worker; on first load, served from cache. If stale
(worker missed), regenerate on demand with a visible "generating…" state.

## 14.2 What `⟳ analyze` does

It was underspecified. Precisely:

- **On a domain tab** (Financials / News / Analysts / Events) — runs **that one
  domain's subgraph only**: `select → gather → synthesize`. No router, no
  writer. 1–2 LLM calls, ~2s. The narrative pins to that tab.
- **On Overview** — runs the full router-led graph, since Overview isn't a
  single domain.
- **Versus the ask box** — the ask box runs the full graph on an arbitrary
  question. `analyze` is the zero-typing version scoped to what you're looking
  at.

Why it exists: every tab is data-plane and free. `analyze` is the single
explicit opt-in to spend a model call on the thing already on screen.

## 14.3 Read-across — the `relations` domain

**The question:** APLD (AI datacenter) prints well — what does that imply for an
adjacent name like IREN? This needs a sixth domain, because it's a different
*kind* of question: it's about pairs, not about one company.

**Tools** (nearly all computed locally from cached bars — no new API):
`peer_set` (sector/SIC + ETF co-membership + correlation ranking) ·
`correlation(a,b,window)` · `beta_to(a,b)` · **`event_study(a,b)`** ·
`shared_etf_membership` · `sector_performance` · `divergence_scan`

**The governing rule: measure the relationship in code, explain it with the
LLM.** Asked directly, a model will confidently assert that a good APLD print is
bullish for IREN — they're both AI-datacenter names. Measured, 2024-09→2026-07:

| | value |
|---|---|
| APLD↔IREN daily return correlation (2y) | **+0.56** |
| IREN co-directional with APLD on **all** days | **71%** (n=500) |
| IREN co-directional on APLD **earnings** days | **44%** (4 of 9) |
| IREN's median capture of APLD's move (\|APLD\|>3%) | **0.07×** |

APLD moved −35.9% and +31.0% on two earnings reactions; IREN moved −5.2% and
−0.2%. So the pair is tightly coupled day-to-day on shared theme and macro, and
APLD's *earnings* are idiosyncratic — the market does not read them across.
Co-movement on earnings days is *lower* than baseline.

**Uncertainty, stated:** n=9 events, one-sided binomial **p = 0.087** against the
null that earnings days behave like any other day. **Suggestive, not
significant.** The same 44% rate would reach p<0.05 at n=12. The system must
report it at this strength — "weaker than its usual co-movement, but only 9
events" — and never round it up to a finding.

**Two methodological traps, both hit while probing this:**
1. `earnings_dates` returns multiple rows per reaction day. Deduping 18 rows →
   9 distinct events changed IREN's "median capture" from 2.69× to 0.07×. Always
   dedupe on the normalized reaction day.
2. A co-direction hit rate is meaningless without the **baseline**. 4/9 = 44%
   sounds like a weak positive until you know all-days co-movement is 71%, at
   which point it's a *negative* result. Every event study must carry its
   baseline.

**Untracked tickers.** The universe is explicitly not the watchlist. `route`
resolves any symbol via lookup, fetches on demand, and caches. You can ask about
APLD without tracking it; nothing about the graph is watchlist-scoped.

**Where this pays off in the brief:** "You hold IREN. APLD reports Thursday.
Historically that has *not* moved IREN much (0.07× capture over 9 events) —
unlike the sector ETF flows, which do."
