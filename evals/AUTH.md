# Sign-in — what was built, what was tested, what broke

Username and password, argon2id. Google OAuth is deferred; the provider
scaffolding in `backend/app/auth.py` stays, unused, until then.

## Shape

| Piece | Where | Note |
|---|---|---|
| Hashing + throttling | `backend/app/passwords.py` | argon2id `t=3, m=64MiB, p=4`; stdlib scrypt fallback |
| Schema | `backend/app/db.py` | `users.username`, `users.password_hash`, unique on `lower(username)` |
| Routes | `backend/app/auth.py` | register, login, password change, claim-legacy, delete account, logout |
| Throttle state | `login_fails` table | shared across workers, survives restart |
| UI | `web/index.html`, `web/app.js` | account chip, sign-in sheet, guest states |

A password is never stored, logged, or returned. Sessions are server-side rows
with an opaque id in an httpOnly cookie, so logout genuinely revokes.

## What the 63 cases check

They split in two. **Auth (34)** checks the primitives — hashing, the rules,
the boundaries — mostly in-process. **Sign-in (29)**, `evals/login_probe.py`,
drives the whole flow the way a person does, in its own process against a
throwaway database: register, own something, sign out, sign back in, rotate the
password, get locked out.

**Hashing** — the stored string never contains the password; two hashes of one
password differ (salted); the backend is memory-hard, not SHA; verify accepts
the right password and rejects the wrong one; a corrupt hash returns False
instead of raising.

**Registration** — weak passwords and malformed usernames are rejected
server-side, not just in the form; `Dave` and `dave` cannot become two
accounts; the response body carries no password field; the cookie set at
registration identifies the user on the next call.

**Login** — a wrong password and an unknown username return byte-identical
status and message, so the form is not a list of who banks here; five failures
lock the identifier for 15 minutes; a correct password clears the counter.

**Guests** — a signed-out visitor gets 401 on any write, an empty watchlist
(never the local user's), and full market data.

**Claiming the pre-login book** — run in a subprocess against a throwaway
database, because this is the only path that moves a portfolio between users.

**Deletion** — `confirm` must equal the username; after deletion the account
cannot log in.

**The round trip (the Sign-in suite)** — the cookie is httpOnly, SameSite=lax
and has a max-age, so it survives a browser restart and cannot be read by JS or
replayed cross-site; what you saved before signing out is there when you sign
back in; the username is case-insensitive and trimmed but the password is
neither; rotating a password revokes every *other* session while keeping the
tab you did it in; an expired session row stops resolving; and the lockout is
visible from a *separate process*, which is the property the old in-process
dict could not have.

## Bugs this found

**1. The pre-login book was grabbable.** First version: whichever account
registered first inherited the implicit `local` user's portfolios. My own eval
harness registered first and took the real book — three accounts including a
Roth IRA and a 401(k). Restored from the live rows, then replaced with an
explicit `POST /api/auth/claim-legacy`, shown as a banner that names what is
being claimed. Covered by `register_does_not_adopt`.

**2. The demo seed used a fixed portfolio id.** `portfolios.id` is a *global*
primary key, and the seed shipped `"default"`. The second user to be seeded
upserted the **first user's row** instead of getting one of their own, so they
ended up with no portfolios at all and the first user's got renamed. Fixed by
minting a fresh id per user, plus a guard in `write_doc` that re-ids rather
than writing through to another user's row. Covered by
`seeded_ids_are_per_user`.

**3. Claiming collided on `UNIQUE(user_id, name)`.** The claiming account
already had its own demo "Brokerage". The claim raised IntegrityError
mid-transaction. Fixed: drop the destination's untouched seed, suffix any
remaining name collision, and merge the watchlist (keyed `(user, ticker)`)
rather than moving it. Covered by `claim_survives_name_collision`.

**4. The unknown-user path was measurably faster.** `dummy_verify()` hashed
*and* verified — two argon2 operations — while a real wrong password cost one.
Median 146ms vs 272ms over the HTTP boundary: enough to enumerate usernames
with a stopwatch. Fixed by caching one throwaway hash so both paths cost
exactly one verify.

    before   wrong password 272ms   unknown user 146ms
    after    wrong password  98ms   unknown user  80ms   (median of 12, sd ~20ms)

The 18ms gap that remains is inside one standard deviation of the measurement.

**5. The throttle was a dict in one process.** A restart or a second worker
reset it. Moved into SQLite. See "Why not Redis" below.

**6. The action that prompted sign-in was thrown away.** Typing a ticker as a
guest opened the sign-in sheet, and after registering the ticker was gone — you
had to type it again. The pending action is now kept in `sessionStorage`
(it has to survive the reload) and replayed once you are in.

**7. My own test was wrong.** `rejects_weak_passwords` fed `"1234567890"`
expecting the digits-only rule, but `"12345678"` is on the common-password list
and matched first. The rule was right; the fixture was not.

## Why not Redis

The first version kept failed-attempt counts in a Python dict. That is wrong
for two reasons that have nothing to do with scale:

- **A restart wipes it.** Five wrong guesses, `uvicorn --reload` notices a file
  change, and the attacker has five more. A lockout that any crash resets is
  not a lockout.
- **Each worker has its own.** Run two workers and the limit is ten, not five;
  run eight and it is forty. The attacker does not even have to try — the load
  balancer spreads the guesses for them.

Both are the same problem: the counter has to be *shared state*, and a dict in
one process is not. Redis is the usual answer because it is fast shared state
with expiry built in. But we already have shared state — SQLite — and the
numbers say it is plenty:

- A login costs one argon2id verify: **~80ms**. One `INSERT` into a two-column
  table is **microseconds**. The throttle is roughly 0.01% of the request.
- Writes only happen on a *failed* login. A successful one does a single
  indexed `DELETE`. There is no write amplification to worry about.
- Rows are pruned opportunistically on every insert, so the table stays small.

Redis would buy sub-millisecond reads we do not need, native TTL we can do with
a `WHERE at > ?`, and a second service to run, back up and secure. The only
case that actually changes this is running the app on several *machines*, where
SQLite is no longer shared — and at that point the database moves to Postgres
or Turso anyway, and the throttle table moves with it. No Redis either way.

## Negative control

`evals/negative_control.py` sabotages three auth defences and asserts the
matching case goes red. A green suite means nothing until you have watched it
go red.

    auth baseline: 28/28 pass
      password minimum dropped to 1      rejects_weak_passwords   CAUGHT
      login throttle disabled            throttle_locks_out       CAUGHT
      hashing replaced by plaintext      hash_not_plaintext       CAUGHT
    auth restored: 28/28 pass

    negative control PASSED - every sabotage was detected

Writing it surfaced one more bug, in the test rather than the code:
`throttle_locks_out` looped `range(MAX_FAILS)`, so raising that setting to 1e9
made the *test* try to insert a billion rows and the control hung for twenty
minutes. A test that derives its workload from the value under test cannot be
used to sabotage that value. The loop bound is now a fixed constant.

## Known limits

- ~~The throttle is in-process.~~ Fixed: the counters live in SQLite
  (`login_fails`), so the lockout survives a restart and is shared by every
  worker. No Redis needed — see below.
- Per-username lockout lets someone deliberately lock a known account for 15
  minutes. The usual trade; the IP counter limits how cheaply it scales.
- No password reset. With no email on file there is nothing to reset *to* —
  that arrives with Google sign-in.
