from __future__ import annotations
import logging, pathlib

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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import auth, db
from .routes import agent, data

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-5s %(name)s %(message)s")

db.ensure_user(db.LOCAL_USER_ID)        # schema init + the implicit local user

app = FastAPI(title="Agentic Fintech", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])
app.add_middleware(auth.UserMiddleware)
app.include_router(auth.router)
app.include_router(auth.me_router)
app.include_router(data.router)
app.include_router(agent.router)

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
        # never let a browser hold a stale shell while we are iterating
        return FileResponse(str(WEB / "index.html"),
                            headers={"Cache-Control": "no-store, must-revalidate"})
