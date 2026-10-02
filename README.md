# Monsoon

Agentic research terminal. Broker-style dashboard, multi-agent research engine.

## Accounts

Sign-in is username + password (argon2id). Google sign-in is scaffolded in
`backend/app/auth.py` but not wired up yet.

You do not have to sign in. A guest gets the whole product — quotes, charts,
research, the agent, a market-wide daily brief — but no watchlist and no
portfolios, because those belong to an account. Try to save something and the
sign-in sheet appears, and whatever you were doing is replayed once you are in.

Set `AUTH_ENABLED=false` to run the old single-implicit-user mode with no login
at all. Design notes and what the 63 auth cases cover: [evals/AUTH.md](evals/AUTH.md).

## What is real vs. seeded

Everything **market-facing is live** — prices, names, logos, candles, SEC
financials, news, analyst ratings, earnings dates.

The **starting watchlist and holdings are demo placeholders.** Share counts and
cost basis are invented, so the portfolio total is live arithmetic over fake
holdings until you replace them. The app says so on first run and the numbers
become yours the moment you edit anything:

- **+ Add** next to Positions — enter ticker, shares, average cost
- Hover a holding to edit or delete it
- Hover a watchlist row to remove it
- `POST /api/reset` clears everything

Adding the same ticker twice averages the cost basis rather than duplicating
the lot.

## Run

```bash
python3.13 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app.main:app --app-dir backend --port 8077 --reload
```

Open http://localhost:8077

### Views

| Route | What it is |
|---|---|
| `#/dashboard` | book summary, watchlist table, allocation, biggest movers |
| `#/t/SYMBOL` | ticker research — chart + Overview/Financials/News/Analysts/Events |
| `#/portfolio` | named accounts (401k / Roth / taxable) with inline add / edit / delete |
| `#/brief` | daily brief — threshold moves with reasons, adjacent names, macro |

The agent panel is collapsible (the node icon at the bottom of the nav rail).
A build stamp sits under it — if you don't see one, you're on a cached page.

**The dashboard needs no API key.** Quotes, charts, financials, news, analysts,
events, and portfolio P&L all work with zero configuration.

For the agent, set a key (free at https://aistudio.google.com/apikey):

```bash
export GEMINI_API_KEY=...
```

Optional: `SEC_USER_AGENT="you <you@example.com>"` — the SEC returns 403 for any
User-Agent without an email-shaped contact.

## Two planes

| | LLM? | What |
|---|---|---|
| **Data plane** | no | every tile, chart, tab, P&L number. `/api/quotes`, `/api/bars`, `/api/financials`, … |
| **Agent plane** | yes | `/api/agent/ask`, `/api/agent/analyze` only |

A 20-ticker watchlist costs **one** HTTP request and zero tokens.

## Multi-agent structure

```
guard -> route -> Send(N domain subgraphs, parallel) -> writer
                    each: select -> gather -> synthesize
```

7 domains (`market`, `fundamentals`, `street`, `events`, `relations`, `macro`,
`portfolio`), 41 tools.
Each domain agent sees only its own catalog and its own evidence — never
another's. That isolation is the multi-agent part.

## Data sources

- **Yahoo** (via yfinance) — quotes, bars, ownership, analysts, calendar.
  `v7/finance/quote` batches up to 100 symbols in one request; a DataLoader in
  `cache.py` coalesces per-ticker calls into it automatically.
- **SEC EDGAR XBRL** — financial statements. Authoritative, no key. The one
  source here with a real API contract.

yfinance is an unofficial scraper: no SLA, no versioned contract. Fine locally;
don't deploy it publicly as the backbone.

## Evals

```bash
./.venv/bin/python -m evals.run            # deterministic, spends no tokens
./.venv/bin/python -m evals.run --agent    # adds the golden set (spends tokens)
./.venv/bin/python evals/negative_control.py
```

The negative control matters more than the pass count: it sabotages real
defences and asserts the matching case goes red. A green suite you have never
watched fail proves nothing. Reports land in `evals/REPORT.md`.
