from __future__ import annotations
import logging, os, pathlib

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
from .routes import agent, data, debug

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

app = FastAPI(title="Agentic Fintech", version="0.1")
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
app.include_router(debug.router)          # TEMPORARY Yahoo-on-Render probe

BUILD = str(int(__import__("time").time()))
WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


class NoCacheStatic(StaticFiles):
    """Dev server: never let a browser hold a stale asset."""
    def file_response(self, *a, **kw):
        r = super().file_response(*a, **kw)
        r.headers["Cache-Control"] = "no-store, must-revalidate"
        return r


if WEB.exists():
    app.mount("/static", NoCacheStatic(directory=str(WEB)), name="static")

    @app.get("/build")
    async def build():
        return {"build": BUILD}

    @app.get("/")
    async def index():
        # The shell is read fresh and its asset query stamped at serve time. A
        # hardcoded ?v= goes stale the moment anyone forgets to bump it, which
        # is every time; this way the stamp cannot drift from the build.
        html = (WEB / "index.html").read_text().replace("__BUILD__", BUILD)
        return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})
