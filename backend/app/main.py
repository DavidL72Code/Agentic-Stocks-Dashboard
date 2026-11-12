from __future__ import annotations
import contextlib, logging, os, pathlib

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
    t1 = time.time()
    try:
        await asyncio.to_thread(importlib.import_module, f"{__package__}.graph.build")
        WARM["agent_import_s"] = round(time.time() - t1, 2)
        log.info("warm-up: agent stack imported in %.1fs", time.time() - t1)
    except Exception as e:
        log.warning("warm-up: agent import failed: %s", e)
    WARM["done_after_s"] = round(time.time() - t0, 2)


IO_THREADS = 32


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
    task = None
    if os.environ.get("WARMUP", "1") != "0":
        task = asyncio.create_task(_warm())
    yield
    if task and not task.done():
        task.cancel()


app = FastAPI(title="Agentic Fintech", version="0.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware,
                   allow_origins=sorted(set(CORS_ORIGINS)),
                   allow_credentials=False,
                   allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Content-Type"])

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
    resp = await call_next(request)
    if request.url.path.startswith("/api/"):
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
