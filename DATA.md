# Data sourcing — what actually feeds each surface

Every claim here was probed on 2026-09-27 against live endpoints. Raw results at
the bottom. Re-run before trusting this: free tiers churn.

---

## 1. The structural point

The design lists ~45 tools. That is **not** ~45 API calls — it's **8 upstream
fetches per ticker**, cached, with everything else computed locally:

| Upstream fetch | Source | Feeds | TTL |
|---|---|---|---|
| daily/weekly bars | yfinance `.history()` | chart, all technicals | 1d (intraday 60s) |
| last price tick | Finnhub WS *(unverified)* | live quote badge | stream |
| `.info` (189 fields) | yfinance | Overview stats, short interest, sector | 24h |
| financial statements | **SEC EDGAR XBRL** | Financials tab | on-filing |
| news | yfinance `.news` / Finnhub | News tab | 15m |
| ratings + targets + changes | yfinance | Analysts tab | 12h |
| calendar + earnings history | yfinance | Events tab | 6h |
| holders / insiders / dividends | yfinance | street, events | 24h |

**Everything derived is free.** RSI, moving averages, realized vol, beta,
drawdown, relative strength, correlation matrices, revenue CAGR, margin trends,
leverage ratios, portfolio P&L and concentration — all arithmetic over the two
cached payloads above. That's roughly half the tool catalog at zero API cost.

---

## 2. Per-surface sourcing

### Chart — yfinance `.history()`
Verified: 22 daily bars in 1.54s; **390 intraday 5m bars in 0.12s**.
Interval limits are the real constraint: `1m` ≤ 7 days, `5m`–`60m` ≤ 60 days,
`1d`+ full history. So the 1D/5D tabs use intraday, 1M+ uses daily. The 5Y tab
should request weekly, not daily.

### Overview — yfinance `.info`
189 fields returned. **All 10 fields the mockup displays were present** —
`marketCap`, `trailingPE`, `profitMargins`, `returnOnEquity`,
`shortPercentOfFloat`, `fiftyTwoWeekHigh`, `sector`, `recommendationKey`,
`targetMeanPrice`, `numberOfAnalystOpinions`.
This is the single most fragile dependency in the system — one undocumented
scrape, 189 fields, no contract. Treat every field as optional at the DTO level.

### Financials — SEC EDGAR XBRL *(primary)*
`data.sec.gov/api/xbrl/companyconcept/CIK.../us-gaap/Revenues.json` → HTTP 200,
no key, no quota beyond a 10 req/s courtesy limit and a `User-Agent` header
identifying you. **This is the only source here with an actual public API
contract**, and it's the authoritative one — it *is* the filing.

⚠️ **Gotcha, observed directly:** one filing returns multiple period lengths
under the same tag. NVDA's 2026-08-26 10-Q yields both `$177.8B` (six-month
cumulative) and `$96.2B` (the quarter). You must filter on `end - start` or you
will silently report double revenue. Any naive `[-1]` index gets this wrong.

yfinance `.quarterly_income_stmt` (42 cells) and `.balance_sheet` (79) work and
are far easier to parse — good as the fast path, with EDGAR as the source of
truth for anything a user might act on.

### News — yfinance `.news` (10 items) + Finnhub `/company-news`
yfinance gives ~10 recent headlines with no date-range control. Finnhub's
free-tier company-news supports date ranges and is the better primary — **not
verified here, needs a key.**

⚠️ **The sentiment chips in the mockup are not sourced.** No free feed supplies
per-headline sentiment. Those labels have to be produced by the `street` agent's
`synthesize` step (or a small local classifier). I invented them for the mockup;
in the build they're a model output and must be badged as such, not shown as
data.

### Analysts — yfinance, fully verified
- `.recommendations` → 4 rows (the strongBuy/buy/hold/sell buckets)
- `.upgrades_downgrades` → **983 rows** of dated firm-by-firm rating history
- `.analyst_price_targets` → 5 fields (low/high/mean/median/current)

This backs the entire Analysts tab, including the 90-day rating-changes list,
with no second provider needed.

### Events — yfinance + EDGAR
`.calendar` (9 fields: earnings date, EPS estimate, revenue estimate),
`.earnings_dates` (**25 rows** incl. estimate vs. actual → surprise history),
`.dividends` (56 rows). Filings list from EDGAR `submissions`.

### Portfolio — your own Postgres
No external source. Positions and cost basis are user-entered; prices come from
the cached bars. The only auth-scoped data in the system.

---

## 3. Load test — no throttling observed

10 tickers × 8 fetches, 5 concurrent (a realistic watchlist refresh):

```
total 4.27s for 80 fetches  ->  18.7 fetch/s, zero rate-limit errors
```

The only 4 "failures" were `dividends:empty` on PLTR, AMZN, TSLA, AMD — which
is **correct**: those companies pay no dividend. This is exactly the case the
design insists on treating as information rather than error, and the probe
confirms the distinction is load-bearing in practice.

Cold, uncached, a 10-ticker watchlist costs ~4s. Warm, it costs a Redis read.

---

## 4. Risks

**yfinance is an unofficial scraper**, not an API. No SLA, no versioned
contract, and Yahoo's terms don't contemplate programmatic use or
redistribution. It works well today — 14/14 endpoints, sub-second after session
warm-up — and it can break on any Tuesday. Acceptable for a local portfolio
project; **do not deploy it publicly as the backbone.** Say so in the README;
knowing this is a better signal than pretending it's production-grade.

**Stooq is no longer a keyless fallback.** It now returns a JavaScript
proof-of-work bot challenge instead of CSV (verified: HTTP 200, 796 bytes of
challenge script, no data). Scratch it from the provider list.

**Finnhub is unverified.** Needs a key. Before committing to it, confirm which
endpoints are still free — `/stock/candle` in particular moved behind the paid
tier at some point, and the WS trade stream is the main reason to use it at all.

**Alpha Vantage** is a poor fallback: its free tier is ~25 requests/day, which
cannot refresh even one watchlist once.

**EDGAR covers US filers only.** Any non-US ticker falls back to yfinance
statements with no authoritative source behind it.

---

## 5. Probe log (2026-09-27)

```
=== yfinance 1.7.0 endpoint probe (NVDA) ===
history 1mo daily          OK n=22    1.54s
history 5d 5m intra        OK n=390   0.12s
info                       OK n=189   0.28s
quarterly_income_stmt      OK n=42    0.18s
balance_sheet              OK n=79    0.19s
news                       OK n=10    0.33s
recommendations            OK n=4     0.08s
upgrades_downgrades        OK n=983   0.13s
analyst_price_targets      OK n=5     0.08s
calendar                   OK n=9     0.08s
earnings_dates             OK n=25    0.55s
institutional_holders      OK n=10    0.10s
insider_transactions       OK n=150   0.00s
dividends                  OK n=56    0.60s
info fields present: 10/10   missing: none

=== SEC EDGAR companyconcept (CIK0001045810 / us-gaap:Revenues) ===
http=200  entity: NVIDIA CORP
  2026-07-26  $177.8B  10-Q filed 2026-08-26   <- 6-month cumulative
  2026-07-26   $96.2B  10-Q filed 2026-08-26   <- the quarter

=== stooq.com/q/d/l/?s=nvda.us&i=d ===
http=200, 796 bytes = JS proof-of-work challenge, no CSV
```

---

## 6. Batching — correction to §1 (probed 2026-09-27)

§1 said "8 upstream fetches per ticker." For *analysis* that's right. For the
**dashboard** it was badly wrong — tiles don't need 8 fetches, and most of what
they do need batches into a single request.

### What does and doesn't batch

| Need | Endpoint | Batches? | Cost for 20 tickers |
|---|---|---|---|
| price, %chg, mktcap, P/E, 52wk, volume, name | `v7/finance/quote?symbols=A,B,C` | **yes** | **1 request, 0.08s** |
| sparkline / candles | `v8/finance/chart/{sym}` | **no** — one symbol per request | 20 requests (cache 24h) |
| `.info` (189 fields) | scrape | **no** — costs **3 requests each** | 60 requests — avoid |
| statements | SEC EDGAR | no | 20, cached until next filing |

**Measured limits:** 20 symbols → 0.08s · 50 → 0.10s · **100 → 0.15s**, all in
one request, 49 populated fields. Chunk at 100.

### `yf.download()` does NOT batch

Worth stating plainly because the name implies otherwise:

```
A: loop 10x Ticker().history(1mo)        10 HTTP   0.93s
B: yf.download(10 syms, threads=False)   10 HTTP   1.03s
C: yf.download(10 syms, threads=True)    10 HTTP   0.42s
D: loop 10x Ticker().info                30 HTTP   2.81s   <- 3 requests each
```

`yf.download` fires the same 10 requests and only *parallelizes* them. It buys
wall-clock, not quota. The only true batch is `v7/finance/quote`.

### Corrected dashboard cost, 20-ticker watchlist

| Implementation | HTTP requests per page load |
|---|---|
| what §1 implied (8 fetches × 20) | 160 |
| naive tiles using `.info` | 60 |
| **batched `v7/quote`, sparklines warm** | **1** |
| batched, cold first visit | 21 |

### Architectural consequence: coalesce, don't ask agents to batch

Agents reason per-ticker — `market(NVDA)`, `market(AAPL)` are separate subgraph
runs and *should* be. So batching must NOT be the agent's job. Put a
**DataLoader-style coalescer** in the provider registry:

- A tool calls `quote("NVDA")` as if it were a single fetch.
- The registry holds the request for a few ms, collects every other `quote(...)`
  in flight, and issues **one** `v7/quote?symbols=...` for all of them.
- Results are demultiplexed back to each caller.

This is the classic N+1 fix, and it pays off twice: the watchlist refresh
collapses to one request, *and* a 3-ticker comparison question — where three
`market` subgraphs each independently want a quote — also collapses to one,
with no coordination between the agents.

Rule: **per-ticker semantics at the tool layer, batched reality at the transport
layer.** Any provider method that can take a symbol list declares a `batch_key`;
the registry coalesces on it automatically.

### Revised TTLs for the data plane

| Data | TTL | Why |
|---|---|---|
| `v7/quote` batch | 30–60s (or WS push) | the only thing that needs to feel live |
| sparkline bars | 24h | a 1-month sparkline doesn't change intraday |
| `.info` | 24h, **detail page only** | 3 requests each — never fetch for a tile |
| statements (EDGAR) | until next filing | it *is* the filing |
