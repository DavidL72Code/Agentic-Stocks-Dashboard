# Hosting Monsoon

Nothing here is needed to run locally — `.env.example` covers that. This is
what changes when the app is reachable from the internet.

## The three that will bite you

Read these before the table.

**1. SQLite on an ephemeral filesystem loses your data on every deploy.**
Render, Railway, Fly and Heroku give each deploy a fresh container. `DB_PATH`
points at a file in that container, so a redeploy silently resets every user,
portfolio and position. Two fixes: mount a persistent volume and point
`DB_PATH` into it, or move the database to Turso (`TURSO_DATABASE_URL`) — see
[DATABASE.md](DATABASE.md). Decide this first; it is the only setting whose
mistake destroys data rather than causing an error.

**2. `APP_BASE_URL` controls whether your session cookie is marked `Secure`.**
It is derived, not separately configured: `secure=APP_BASE_URL.startswith("https")`.
Leave the default and every session cookie ships without `Secure`, so a browser
will send it over plain HTTP. The app logs a warning at startup when
`APP_BASE_URL` is neither https nor localhost — but a warning in a log is easy
to miss, so set it deliberately.

**3. Your host assigns the port.** The app does not read `PORT`; uvicorn takes
it on the command line. Your start command must be:

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT
```

`--host 0.0.0.0` matters too — the default binds loopback only, and the
platform's router cannot reach that.

## Every variable the code reads

Authoritative list (`grep -r os.environ backend/`), 22 of them. Only one is
required for the full product.

### Required for the agent

| Variable | Notes |
|---|---|
| `GEMINI_API_KEY` | Free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Without it the dashboard, charts, financials, news, analysts and the data-plane brief all still work — only the Ask box, Analyze buttons and the written brief go dark. |

### Set these when hosting

| Variable | Value | Why |
|---|---|---|
| `APP_BASE_URL` | `https://your-domain` | Cookie `Secure` flag, OAuth redirects, default CORS origin. See above. |
| `DB_PATH` | a path on a **persistent volume** | Otherwise data dies on redeploy. Or use Turso instead. |
| `SEC_USER_AGENT` | `monsoon/0.1 (you@example.com)` | The SEC returns 403 to any User-Agent without an email-shaped contact. Their fair-access policy expects a real address. |
| `AUTH_ENABLED` | `true` (the default) | `false` runs the whole app as one implicit user with no login. Never set it false on a public host. |

### Optional

| Variable | Default | Notes |
|---|---|---|
| `CORS_ORIGINS` | `APP_BASE_URL` + localhost | Only needed if the frontend is served from a different origin than the API. |
| `SESSION_DAYS` | `30` | Cookie lifetime and the session row's expiry. |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Synthesis and the final write-up. |
| `GEMINI_FAST_MODEL` | same as above | Tool selection and the guard. Cheap model is fine. |
| `LLM_BASE_URL` | Gemini's OpenAI-compatible endpoint | Not a "switch providers" knob — the client is `ChatOpenAI`, which would otherwise default to `api.openai.com`. |
| `OPENAI_API_KEY` | — | Only if you repoint `LLM_BASE_URL` at OpenAI. |
| `STORE_PATH` | `data/store.json` | Legacy single-file store, read once to import, then renamed. Leave it. |
| `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN` | — | Hosted database instead of a local file. [DATABASE.md](DATABASE.md). |
| `REDIS_URL`, `REDIS_PREFIX`, `REDIS_STALE_FACTOR`, `REDIS_TIMEOUT` | — | Cache second tier. Below. |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | — | OAuth alongside passwords. Callback `{APP_BASE_URL}/api/auth/callback/github`. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | — | Callback `{APP_BASE_URL}/api/auth/callback/google`. Not wired into the UI yet. |

A minimal production `.env`:

```
GEMINI_API_KEY=...
APP_BASE_URL=https://monsoon.example.com
SEC_USER_AGENT=monsoon/0.1 (you@example.com)
DB_PATH=/data/monsoon.db
AUTH_ENABLED=true
```

## Getting a `REDIS_URL`

The format is always:

```
redis://[username]:[password]@host:port/db
rediss://...                                  # TLS - note the double s
```

**The single most common mistake: using `redis://` against a managed Redis.**
Nearly all of them are TLS-only and need `rediss://`. Because the cache has a
circuit breaker, a wrong scheme does not crash — it trips, stands down, and you
get no cache at all. The only symptom is `cache.l2.paused: true` in
`/api/health`, so check that after wiring it up.

**Upstash** — create a database; the console shows a connection string under
the Redis tab. It already starts `rediss://` and embeds the password:

```
REDIS_URL=rediss://default:AbCd...@eu1-xxx.upstash.io:6379
```

Serverless and priced per command, so it scales to zero rather than idling out.
Note Upstash also publishes a *REST* endpoint — that is a different protocol and
`redis-py` cannot use it. Take the Redis-protocol string.

**Redis Cloud** — create a database, then read the endpoint and password off its
page and assemble it yourself:

```
REDIS_URL=rediss://default:<password>@redis-12345.c1.us-east-1-2.ec2.cloud.redislabs.com:12345
```

**Railway** — add a Redis service and it injects `REDIS_URL` into your app
automatically; reference it rather than pasting a literal. Use the internal
hostname if offered, so traffic stays on their network.

**Render** — add a Redis instance and copy the *Internal* connection string.
The external one leaves their network and costs latency.

**Fly.io** — `fly redis create` prints the URL once, at creation. Save it then;
it is not shown again.

**Docker Compose / your own box** — the service name is the host, no TLS needed
inside the network:

```
REDIS_URL=redis://redis:6379/0
```

Two more things once it is hosted:

- **Raise `REDIS_TIMEOUT`.** The default is `0.25` seconds, which suits a Redis
  on the same machine. A managed instance in another region can exceed that on
  one round trip, and the breaker will then trip on *latency* rather than on
  failure. Use `1` or `2`.
- **Keep `/db` at `0` unless you know otherwise.** Many managed providers expose
  only database 0, and a URL ending `/15` will fail against them.

Then confirm it is actually working, rather than assuming:

```bash
curl -s https://your-domain/api/health | python3 -m json.tool
```

`cache.l2.backend` should read `redis`, `paused` should be `false`, and `hits`
should climb as you use the app.

## What does NOT need Redis

Sessions and the login throttle live in SQLite. They are already server-side
and already revocable — logout deletes the row, and a password change revokes
every other device ([evals/AUTH.md](evals/AUTH.md)). Keeping them there means a
Redis outage costs cache misses and never a login. If you later run on several
machines, move the *database* (Turso or Postgres) rather than reaching for
Redis; the session and throttle tables travel with it.

Live prices are deliberately never cached at all, in L1 or L2 — the batch
loader coalesces concurrent callers into one upstream request without storing
the result. A test pins that, since caching prices is the tempting wrong move.

## Before you open it to the public

- `AUTH_ENABLED=true`, and `APP_BASE_URL` on https.
- `DB_PATH` on a volume, or Turso. Then actually redeploy once and confirm your
  account survived.
- `.env` is gitignored — keep it that way; the Gemini key, the Turso token and
  the Redis password are all in there.
- yfinance is an unofficial scraper with no SLA and no versioned contract. It is
  fine for your own use; it is not a backbone to put real users on top of.
- `RESEARCH ONLY` and the not-financial-advice disclaimer are in the UI for a
  reason. Leave them.
