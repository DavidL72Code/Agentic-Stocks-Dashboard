# Isolation model — and no, there is no row-level security

## The short answer

Can one user read another's holdings, wipe their table, or dump the whole
thing? **Tested, and no** — on every path I could find to try it:

| Attack | Result |
|---|---|
| Call any endpoint with another user's portfolio id | 404, nothing returned, not even the account name |
| Insert / edit / delete a position in their account | denied, their book unchanged |
| Rename, activate, reset or delete their account | denied, 404 |
| Read `all accounts` and hope theirs is included | only your own |
| Rotate their password / delete their account | denied |
| Ask the **agent** about "my portfolio" | each user gets their own book |
| Hammer both users' reads concurrently | 24 interleaved reads, no crossover |
| SQL injection through any user input | no path: every value is bound with `?` |
| Read another user's data from the cache | the cache holds market data only, keyed by symbol |

There is no endpoint that returns more than one user's rows, no endpoint that
takes a filter or a query, and no raw SQL path. The closest thing to "read the
whole table" is `all accounts`, which means all of *yours*.

**But the guarantee comes from the application, not the database** — so the
honest version is "tested, not structurally impossible". The rest of this page
is what that distinction costs.

**We do not have row-level security.** SQLite has no such feature, and neither
does libSQL/Turso. RLS is a Postgres feature (`ALTER TABLE … ENABLE ROW LEVEL
SECURITY` plus `CREATE POLICY`), which is why you meet it through Supabase.

What we have instead is **application-level scoping**. That is a genuinely
weaker guarantee and worth being precise about.

## What enforces isolation today

Every request becomes a `user_id` in exactly one place — `auth.resolve_user()`,
from a server-side session row keyed by an opaque httpOnly cookie. From there:

1. **Every query is scoped by `user_id`.** `portfolios`, `watchlist`, `prefs`,
   `snapshots` and `sessions` all carry the column, and every statement in
   `db.py` that touches them filters on it.
2. **Anything reached by `portfolio_id` is resolved against the caller's own
   document first.** `store.account(pid)` searches only
   `store.load()["portfolios"]`, which is already user-scoped, so a foreign id
   resolves to `None` and the route returns 404 — it never reaches a query.
3. **`write_doc` refuses to write through a foreign id.** If a portfolio id
   already belongs to another user, it is re-issued rather than upserted.
4. **Guests cannot write at all.** `_require_account()` on every mutating route.

## The weak link, stated plainly

`positions` has **no `user_id` column**. It is scoped *transitively*, through
`portfolio_id → portfolios.user_id`. So isolation for the most sensitive table
in the app — share counts and cost basis — rests on every caller having
resolved that `portfolio_id` against the current user first.

With RLS, a policy on the table makes that structurally impossible: a missing
`WHERE` returns zero rows instead of someone else's. Without it, one forgotten
check is a cross-account leak and the database will not stop it.

Which is why it is tested rather than asserted.

## The tests

**`evals/tenancy_probe.py`** creates two real accounts with real holdings, then
hands user A user B's actual ids and tries **every id-taking operation in the
API**: read the portfolio, read its analytics, rename it, insert a position,
edit a position, delete a position, activate it, reset it, delete the account,
rotate the other user's password, delete the other user's account.

```
24/24 checks passed
```

It also asserts the negative space: that a foreign id leaks not even the
account *name*, that `positions` still has no `user_id` (so the check keeps
being necessary), and that foreign keys are on.

**`evals/agent_tenancy_probe.py`** goes after the agent plane specifically,
because that is where the per-request identity is most likely to break: the
router fans out with `Send` into parallel subgraphs, each subgraph gathers
several tools at once, and every portfolio tool resolves the user from that
contextvar. It gives two users deliberately disjoint books, gives the *local*
user a distinctive marker holding, and checks that neither user's answer ever
contains the other's ticker or the marker. It also interleaves 24 concurrent
reads looking for crossover, and asserts a context-less caller sees nothing and
cannot write.

Both run in the suite as the **Tenancy** suite.

## Three bugs this found

Both were reachable with your *own* valid ids, so neither was a leak — but both
were real.

**1. A per-account reset wiped the whole watchlist.**
`POST /api/reset?portfolio_id=X` cleared that one account's positions and then
cleared `d["watchlist"]` unconditionally. A request that named one account
destroyed a list belonging to no account. Worse, an id matching *nothing* still
wiped it — so a typo cost you your watchlist. The watchlist is now only touched
by a whole-book reset.

**2. Two destructive routes returned 200 for a no-op.**
`DELETE /api/portfolios/{unknown}` and `POST /api/reset?portfolio_id={unknown}`
both reported success having done nothing. Now 404.

**3. The current-user default failed open.**
Requests get their `user_id` from a `contextvars.ContextVar`, set once by
`UserMiddleware`. Its default was `LOCAL_USER_ID` — so any code running
*outside* a request context read one real user's holdings and watchlist instead
of nothing. Demonstrated from a bare thread: it returned that user's positions
and full watchlist.

Nothing reaches it today. The middleware sets it on every request, and
contextvars propagate correctly through the agent's `Send` fan-out and its
concurrent tool execution — both tested. But a fail-open default is a bug
waiting for the first background job, scheduled brief or thread pool that does
not inherit the context, and it would fail *silently*. The default is now
`GUEST`, which owns nothing and cannot write, so a lost context yields `[]`.

Note what `asyncio` does and does not do here: `asyncio.to_thread` and
`create_task` both **copy** the current context, so neither loses it — my first
attempt at this test used `to_thread`, inherited the user I had just set, and
looked like a cross-user leak that wasn't one. Only a bare `threading.Thread`
inherits nothing.

The first tenancy run passed 18/18 *with both bugs present*, because I only
asserted the victim's data was intact and never checked the caller's. A passing
isolation test is not a passing blast-radius test.

## What it would take to get real RLS

RLS needs Postgres (or Supabase, which is Postgres). The schema ports nearly
unchanged — see [DATABASE.md](DATABASE.md) — and then:

```sql
ALTER TABLE portfolios ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_portfolios ON portfolios
  USING (user_id = current_setting('app.user_id')::text);

-- positions needs the join, since it has no user_id of its own
ALTER TABLE positions ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_positions ON positions
  USING (EXISTS (SELECT 1 FROM portfolios f
                 WHERE f.id = positions.portfolio_id
                   AND f.user_id = current_setting('app.user_id')::text));
```

with `SET LOCAL app.user_id = …` per transaction, from the same
`resolve_user()` that scopes queries today. Note that the `positions` policy
needs a subquery precisely because of the missing column — adding `user_id` to
`positions` would be worth doing first, and is worth doing anyway: it would turn
the transitive scoping above into direct scoping.

Until then: the scoping is in the application, and the tenancy probe is what
keeps it honest.

## Known limits

- **No RLS**, as above.
- **No CSRF tokens.** The session cookie is `SameSite=Lax`, which blocks
  cross-site POSTs carrying it; that is the whole defence. A token would be
  belt-and-braces.
- **CORS is `allow_origins=["*"]`** with credentials off, so a browser will not
  attach the session cookie cross-origin. Tighten it before putting this behind
  a real domain.
- **No audit log.** Nothing records who changed what, so a mistake is not
  reconstructable.
- **The throttle counters are not secrets** but they are in the same database;
  a compromised database reveals who tried to log in and when.
