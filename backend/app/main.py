from __future__ import annotations
import contextlib, logging, os, pathlib, time

# Load .env before anything else imports - module-level config (model names,
# base URL) is read at import time, so this has to happen first.
try:
    from dotenv import load_dotenv
    _ROOT = pathlib.Path(__file__).resolve().parents[2]
    load_dotenv(_ROOT / ".env")
except ImportError:          # dotenv is optional; real env vars still work
    pass
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import auth, db
from .routes import agent, data

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-5s %(name)s %(message)s")

db.ensure_user(db.LOCAL_USER_ID)        # schema init + the implicit local user

# ── CORS ────────────────────────────────────────────────────────────────
# The UI is served from this same origin, so cross-origin access is not needed
# for the app to work at all. It used to be allow_origins=["*"], which let any
# website on the internet read every unauthenticated response (quotes, research,
# the agent) from a visitor's browser. Not a session-theft hole - credentials
# were off, so no cookie was ever attached - but it was a standing invitation
# and it cost nothing to close.
#
# Set CORS_ORIGINS to a comma-separated list to serve the UI from elsewhere.
# Credentials stay OFF: a cross-origin caller must never be able to ride the
# session cookie, and "*" with credentials is rejected by browsers anyway.
_base = os.environ.get("APP_BASE_URL", "http://localhost:8077").rstrip("/")
CORS_ORIGINS = [o.strip().rstrip("/") for o
                in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()] or [
    _base,
    "http://localhost:8077", "http://127.0.0.1:8077",
]

log = logging.getLogger("monsoon.main")


async def _warm() -> None:
    """Fill the caches a dashboard visit needs, then load the agent's libraries.

    Runs in the background once the server is listening, so it never delays
    the first request - it only means that request, usually the visitor who
    woke a sleeping Render instance, finds the market already fetched. The
    agent stack (LangGraph, LangChain, the OpenAI SDK) is imported last and
    off the event loop: deferred from start-up so the dashboard is not kept
    waiting for it, but loaded before anyone asks a question."""
    import asyncio, importlib, time
    from . import store
    from .providers import nasdaq, yahoo
    t0 = time.time()
    store.set_current_user(store.GUEST)            # warm the public view only
    jobs = {"caps": nasdaq.caps(), "indices": data.indices(),
            "earnings": data.earnings_week(days=7, limit=30), "brief": data.brief(),
            "spy": yahoo.quote("SPY")}
    res = await asyncio.gather(*jobs.values(), return_exceptions=True)
    bad = [k for k, r in zip(jobs, res) if isinstance(r, Exception)]
    from .status import WARM
    WARM.update(dashboard_s=round(time.time() - t0, 2), failed=bad)
    log.info("warm-up: dashboard data in %.1fs%s", time.time() - t0,
             f" (failed: {', '.join(bad)})" if bad else "")
    # The agent's libraries cost ~10s of CPU to import on Render's 0.1 CPU
    # (measured: agent_import_s 9.89). Imported straight after start-up, that
    # landed on the visitor who had just woken the server - every page they
    # opened in those seconds crawled. Wait for 15s with no request in flight;
    # a question asked before then imports it on demand.
    import sys
    from .status import ACTIVITY
    mod = f"{__package__}.graph.build"
    while mod not in sys.modules and (ACTIVITY["inflight"] or time.time() - ACTIVITY["last"] < 15):
        await asyncio.sleep(3)
    if mod in sys.modules:
        WARM["agent_import_s"] = "imported on demand"
    else:
        t1 = time.time()
        try:
            await asyncio.to_thread(importlib.import_module, mod)
            WARM["agent_import_s"] = round(time.time() - t1, 2)
            log.info("warm-up: agent stack imported in %.1fs", time.time() - t1)
        except Exception as e:
            log.warning("warm-up: agent import failed: %s", e)
    WARM["done_after_s"] = round(time.time() - t0, 2)


IO_THREADS = 32


# ── staying awake ──
# Render's free tier sleeps after 15 minutes without an inbound request, and a
# visit to a sleeping server waits about a minute. The GitHub keep-warm job was
# meant to prevent that, but GitHub runs a repo's 5-minute schedule when it
# gets round to it: on Nov 12 2026 it ran at 11:45, 18:43 and 23:53 UTC, and a
# visit at 9pm New York time sat on a loading screen for a minute. So the server
# pings itself through its public address (Render routes that back in as
# inbound traffic) every 10 minutes from 6am to midnight New York time, and
# sleeps overnight - ~560 of the workspace's 750 free hours a month. The GitHub
# job still wakes it in the morning; the first visitor does too.
AWAKE_FROM, AWAKE_UNTIL = 6, 24          # New York hours


async def _keep_awake() -> None:
    import asyncio
    url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not url:                           # not on Render: nothing to keep awake
        return
    from .clock import ny_now
    from . import http
    while True:
        await asyncio.sleep(600)
        if not (AWAKE_FROM <= ny_now().hour < AWAKE_UNTIL):
            continue                      # let it sleep overnight
        try:
            await http.client("self", timeout=30).get(url + "/api/health")
        except Exception as e:
            log.info("keep-awake ping failed: %s", e)


@contextlib.asynccontextmanager
async def lifespan(_app):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from .status import WARM
    # Every blocking fetch (yfinance, Nasdaq, Yahoo's chart and spark) runs on
    # the default thread pool, which Python sizes from the CPU count: 5 threads
    # on a 1-CPU host. Nine research calls each waiting on several of them
    # queued behind one another - a single one-symbol quote took 4.5s on Render
    # while it waited for a free thread (live, Nov 12 2026). The threads spend
    # their time waiting on the network, so 32 of them cost almost nothing.
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=IO_THREADS, thread_name_prefix="io"))
    WARM.update(cpu_count=os.cpu_count(), io_threads=IO_THREADS)
    WARM["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tasks = [asyncio.create_task(_keep_awake())]
    if os.environ.get("WARMUP", "1") != "0":
        tasks.append(asyncio.create_task(_warm()))
    yield
    for t in tasks:
        if not t.done():
            t.cancel()


app = FastAPI(title="Agentic Fintech", version="0.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware,
                   allow_origins=sorted(set(CORS_ORIGINS)),
                   allow_credentials=False,
                   allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Content-Type"])

# Endpoints whose answer does not depend on who asks - and only these may be
# cached at the edge. Everything with an account behind it (me, auth, watchlist,
# portfolio, the brief, the agent) is not in this list and stays no-store.
import re as _re
PUBLIC_API = _re.compile(
    r"^/api/(quotes|indices|sparklines|search|compare|calendar/earnings"
    r"|(bars|overview|financials|news|analysts|events|logo)/[^/]+"
    r"|related/[^/]+(/event-study/[^/]+)?)$")


@app.middleware("http")
async def no_store_api(request, call_next):
    """Never let a CDN or proxy cache an API response.

    Not theoretical. Vercel caches rewrites to external origins by default and
    honours upstream cache-control, and nothing here was sending any - so
    /api/me and /api/portfolio could have been cached at the edge and served to
    a different visitor. That is the cross-user leak the tenancy probe exists to
    prevent, reintroduced one layer up where no application test would see it.
    Cheap to state explicitly, and correct behind any proxy, not just Vercel.
    """
    from .status import ACTIVITY
    # Health checks are not activity: Render polls /api/health every few
    # seconds (healthCheckPath in render.yaml), and so does the keep-awake
    # ping. Counted, they kept the server from ever looking idle - the agent
    # import waiting for a quiet moment never ran on Render.
    track = request.url.path != "/api/health" and request.method != "HEAD"
    if track:
        ACTIVITY["inflight"] += 1
        ACTIVITY["last"] = time.time()
    try:
        resp = await call_next(request)
    finally:
        if track:
            ACTIVITY["inflight"] -= 1
            ACTIVITY["last"] = time.time()
    if request.url.path.startswith("/api/"):
        if (request.method == "GET" and resp.status_code == 200
                and PUBLIC_API.match(request.url.path)):
            # The same answer for every visitor, so Vercel's CDN may keep it -
            # and keep serving it while it fetches a fresh one. At night, when
            # this server sleeps, a visitor gets the last prices at once
            # instead of a minute of skeletons; the refresh wakes the server.
            # Browsers still never store it (vercel.json sends no-store).
            resp.headers["Cache-Control"] = "no-cache"
            resp.headers["Vercel-CDN-Cache-Control"] = "max-age=20, stale-while-revalidate=86400"
        else:
            resp.headers["Cache-Control"] = "no-store, private"
            resp.headers["Vary"] = "Cookie"
    return resp


app.add_middleware(auth.UserMiddleware)
app.include_router(auth.router)
app.include_router(auth.me_router)
app.include_router(data.router)
app.include_router(agent.router)

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


def _build_stamp() -> str:
    """A fingerprint of the shipped files - name, size and modification time -
    read on every page load. Stamped from the clock at start-up, every Render
    wake-up was a "new build" and every visitor re-downloaded ~250KB of app.js
    and ui.css that had not changed. Stamped once at start-up from content, an
    edit on a running dev server kept the old URL, and the browser kept the old
    file (it is served immutable). Four stat() calls per page load cost nothing."""
    import hashlib
    h = hashlib.sha1()
    for f in sorted(WEB.glob("*.*")) if WEB.exists() else []:
        if f.suffix in (".js", ".css", ".html"):
            st = f.stat()
            h.update(f"{f.name}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()[:12]


class Static(StaticFiles):
    """Versioned assets (?v=<build>) are immutable: a new build is a new URL.
    Anything else - charts.js, imported by app.js without a stamp - must be
    revalidated, which costs a 304 when it has not changed."""
    def file_response(self, *a, **kw):
        r = super().file_response(*a, **kw)
        scope = kw.get("scope") or (a[2] if len(a) > 2 else {})
        versioned = b"v=" in (scope.get("query_string") or b"")
        r.headers["Cache-Control"] = ("public, max-age=31536000, immutable" if versioned
                                      else "no-cache")
        return r


if WEB.exists():
    app.mount("/static", Static(directory=str(WEB)), name="static")

    @app.get("/build")
    async def build():
        return {"build": _build_stamp()}

    @app.get("/")
    async def index():
        # The shell is read fresh and its asset query stamped at serve time. A
        # hardcoded ?v= goes stale the moment anyone forgets to bump it, which
        # is every time; this way the stamp cannot drift from the build.
        html = (WEB / "index.html").read_text().replace("__BUILD__", _build_stamp())
        return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})
