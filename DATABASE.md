# Database

Monsoon stores your watchlist, accounts, positions, sessions and login throttle
in SQLite. One file, no server, no setup. `data/monsoon.db`, created on first
run, ignored by git.

That is the right default and you may never need to change it. The rest of this
page is for when you want the same app running somewhere other than your laptop.

## Why SQLite at all

The whole dataset is a few hundred rows. Postgres would mean a server to run,
back up, patch and pay for, to hold less data than a spreadsheet. SQLite gives
you real transactions, real foreign keys and real indexes in a file you can
copy. WAL mode is on, so reads never block the writer.

What it cannot do is be shared by two machines. That is the only reason to move.

## Moving to Turso (free, and it does not sleep)

[Turso](https://turso.tech) hosts **libSQL** — a fork of SQLite that speaks the
same dialect over the network. The schema, the queries and every line of
`backend/app/db.py` stay exactly as they are; only where `conn()` points
changes.

Its free tier is 5 GB and 500 databases, and — the reason it is here rather
than Supabase — **a free database is not paused for inactivity.** Come back in
three months and your portfolio is still there.

### 1. Install the CLI and sign in

```bash
curl -sSfL https://tur.so/install.sh | bash
turso auth signup
```

### 2. Create the database and read its credentials

```bash
turso db create monsoon
turso db show monsoon --url          # libsql://monsoon-<you>.turso.io
turso db tokens create monsoon       # a long-lived auth token
```

### 3. Install the driver

```bash
./.venv/bin/pip install libsql-experimental
```

### 4. Point the app at it

Add to `.env` — never commit this file, the token is a credential:

```
TURSO_DATABASE_URL=libsql://monsoon-<you>.turso.io
TURSO_AUTH_TOKEN=<the token from step 2>
```

Start the app. It creates the schema on first connect, exactly as it does
locally. `GET /api/health` reports which backend is live.

Unset `TURSO_DATABASE_URL` and you are back on the local file, untouched.

### 5. Bring your existing data across (optional)

A local database is a plain SQLite file, so the move is a dump and a replay:

```bash
sqlite3 data/monsoon.db .dump > monsoon.sql
turso db shell monsoon < monsoon.sql
```

Check it landed before you trust it:

```bash
turso db shell monsoon "SELECT COUNT(*) FROM positions"
```

Keep `data/monsoon.db` until you have. It costs nothing to keep a copy.

## What the code actually does

`backend/app/db.py` picks a backend in `conn()`:

- no `TURSO_DATABASE_URL` → `sqlite3.connect(DB_PATH)`, WAL on
- `TURSO_DATABASE_URL` set → `libsql.connect(url, auth_token=...)`

The libsql driver is DB-API-*ish* but not `sqlite3`: its cursor is not
iterable, its rows are plain tuples rather than `sqlite3.Row`, and its
connection is not a context manager, so `with conn():` would raise. A small
shim in `db.py` (`_Row`, `_Cursor`, `_Conn`) absorbs those three differences in
one place instead of rewriting forty call sites. `PRAGMA journal_mode` is
dropped on the remote path, where the journal is the server's business.

**Verified end to end against the libSQL driver** — register, sign in, sign out
and back in with state intact, watchlist, named accounts, positions, portfolio
valuation, login throttle, password rotation. All nine tables are created by
the same `SCHEMA` string the local path uses.

The one leg not verified here is the network itself: the run above used libSQL
against a local file, because verifying the hosted path needs a Turso account
and a token, which only you can create. If step 4 fails it will fail loudly at
startup on the first connect, not silently at runtime.

## Caching (Redis, optional)

Separate question from where the data lives. Market data — quotes, bars, EDGAR
filings, logos — is cached so a 20-ticker watchlist costs one upstream request.
By default that cache is an in-process dict: it works, but it dies on every
restart and is not shared between workers. A dev-server reload cold-starts
every quote and bar.

Set `REDIS_URL` and it gains a second tier.

```bash
brew install redis && brew services start redis     # or: docker run -p 6379:6379 redis
./.venv/bin/pip install redis
```

```
REDIS_URL=redis://localhost:6379/0
```

`GET /api/health` then reports `cache.l2.backend = "redis"` with hit, miss,
write and error counts, so "is Redis actually being used" is answerable without
reading the config.

**Two tiers, not a replacement.** The in-process dict stays as L1, so no call
site changes and a hot read never pays a network hop. Redis is L2: read on an
L1 miss, written on a fetch, and promoted into L1 on a hit. It all happens
inside `cached()` in `backend/app/cache.py`, which is the single place TTL
caching has ever happened.

**What deliberately does NOT move to Redis:** sessions and the login throttle.
They are already server-side and already revocable in SQLite — see
[evals/AUTH.md](evals/AUTH.md). Putting them in Redis would buy a faster lookup
on a table that answers in microseconds, and would make Redis a hard dependency
for logging in. As scoped, a Redis outage costs cache misses and nothing else.

**What it covers, and what it must not.** L2 caches whatever goes through
`cached()`: bars, company info, analyst data, earnings calendars, EDGAR
financials, news and logos. **Live prices are deliberately not cached at all** —
`quote()` goes straight through the batch loader, which coalesces concurrent
callers into one upstream request without ever storing the result. A TTL cache
on prices would serve a stale number, and L2 would make it stale across
restarts too. `evals/cache_probe.py` asserts this stays true.

Three more details worth knowing before you rely on it:

- **JSON, not pickle.** A pickle read from a shared store lets anything that
  can write to the keyspace run code in this process. The cost is that values
  JSON cannot represent are not cached in L2 — `attr(symbol,
  "earnings_dates")` is one, being a dict keyed by pandas Timestamps. They
  still cache in L1, and `/api/health` counts the skips under `not_json` so it
  is visible rather than silent.
- **There is a circuit breaker.** Without one, a dead Redis adds a connect
  timeout to *every* cache miss — slower than having no cache. Three
  consecutive failures and it stands down for 30s; `health` shows `paused:
  true` and the last error.
- **Keys look like `monsoon:v1:bars:<sha1>`.** Readable prefix so
  `redis-cli --scan --pattern 'monsoon:v1:bars:*'` is useful, digest over the
  whole key tuple so `("a","b:c")` cannot collide with `("a:b","c")` — which a
  naive `":".join` allows, and which would serve one ticker's data for another.

Free either way: Redis runs locally for nothing, and hosted free tiers
(Upstash, Redis Cloud) are far larger than this needs — the cache is kilobytes.
Verify current limits before relying on them.

Tested by `evals/cache_probe.py`, which needs no server: round trips go through
a real `redis-py` async client against `fakeredis`, and the breaker is tested
against a genuinely closed port. Point `REDIS_TEST_URL` at a real Redis to run
the round-trip block against that instead.

## Postgres

If you end up wanting Postgres — several app servers, or an ops team that
already runs one — the schema ports almost unchanged. Three differences worth
knowing before you start:

| | SQLite | Postgres |
|---|---|---|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | implicit rowid | `GENERATED ALWAYS AS IDENTITY` |
| `REAL` timestamps | unix float, as used here | `timestamptz` is better |
| `lower(username)` unique index | expression index, supported | identical |

The throttle table (`login_fails`) moves with everything else. There is still
no reason to add Redis — see [evals/AUTH.md](evals/AUTH.md).
