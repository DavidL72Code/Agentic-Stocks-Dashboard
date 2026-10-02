"""Store facade, backed by SQLite.

Same functions the routes already call, but every one now runs against a
user-scoped relational schema (see db.py). A single implicit local user exists
today; `current_user_id()` is the one place that changes when OAuth is added.
"""
from __future__ import annotations
import contextvars, os, pathlib
from . import db

# Set per request by auth.UserMiddleware. The DEFAULT MATTERS: it used to be
# LOCAL_USER_ID, so any code running outside a request context - a bare thread,
# a background job, a future scheduled brief - silently read one real user's
# holdings and watchlist instead of failing. contextvars propagate correctly
# through the agent's fan-out today (tested), but a fail-open default is a bug
# waiting for the first piece of code that does not inherit the context.
# GUEST reads nothing and cannot write, so a lost context yields nothing.
_user: contextvars.ContextVar[str] = contextvars.ContextVar("user", default="guest")

KINDS = ["taxable", "401(k)", "roth ira", "traditional ira", "hsa", "crypto", "other"]
LEGACY_JSON = pathlib.Path(os.environ.get("STORE_PATH", "data/store.json"))

SEED = {
    "watchlist": ["NVDA", "AAPL", "MSFT", "AMD", "PLTR", "KO"],
    "portfolios": [{
        "id": "default", "name": "Brokerage", "kind": "taxable",
        "positions": [
            {"ticker": "NVDA", "qty": 50, "basis": 139.60},
            {"ticker": "AAPL", "qty": 20, "basis": 218.50},
            {"ticker": "MSFT", "qty": 12, "basis": 412.00},
        ]}],
    "active": "default",
    "seeded": True,
}


GUEST = "guest"          # signed-out visitor: no watchlist, no portfolios


def current_user_id() -> str:
    return _user.get()


def is_guest() -> bool:
    return current_user_id() == GUEST


def set_current_user(uid: str) -> None:
    _user.set(uid)


def _bootstrap(uid: str) -> None:
    """First run for a user: import the old JSON store if present, else seed."""
    if db.migrate_from_json(LEGACY_JSON, uid):
        return
    d = db.read_doc(uid)
    if not d["portfolios"]:
        # portfolio ids are a GLOBAL primary key, so the seed cannot ship a
        # fixed "default" - the second user to be seeded would collide with
        # the first user's row instead of getting one of their own.
        seed = {**SEED, "portfolios": [{**p, "id": db.new_id()} for p in SEED["portfolios"]]}
        seed["active"] = seed["portfolios"][0]["id"]
        db.write_doc(uid, seed, touched=False)


EMPTY = {"user_id": GUEST, "watchlist": [], "portfolios": [],
         "active": None, "seeded": False, "snapshots": {}, "guest": True}


def load() -> dict:
    uid = current_user_id()
    if uid == GUEST:
        # nothing is stored for a signed-out visitor, and nothing can be
        return {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
                for k, v in EMPTY.items()}
    db.ensure_user(uid)
    d = db.read_doc(uid)
    if not d["portfolios"] and not d["watchlist"]:
        _bootstrap(uid)
        d = db.read_doc(uid)
    return d


def save(d: dict, touched: bool = True) -> dict:
    if is_guest():
        raise PermissionError("sign in to save a watchlist or portfolio")
    db.write_doc(current_user_id(), d, touched=touched)
    return d


def new_id() -> str:
    return db.new_id()


def accounts(d: dict | None = None) -> list[dict]:
    return (d or load())["portfolios"]


def account(pid: str | None, d: dict | None = None) -> dict | None:
    d = d or load()
    if pid in (None, "", "all"):
        return None                 # means "every account combined"
    return next((p for p in d["portfolios"] if p["id"] == pid), None)


def all_positions(pid: str | None = None) -> list[dict]:
    """Positions for one account, or every account merged. The same ticker in
    two accounts stays two rows - the cost bases genuinely differ."""
    d = load()
    accs = [account(pid, d)] if pid not in (None, "", "all") else d["portfolios"]
    out = []
    for a in accs:
        if not a:
            continue
        for p in a["positions"]:
            out.append({**p, "account_id": a["id"], "account": a["name"]})
    return out


def snapshots() -> dict:
    return load().get("snapshots") or {}


def write_snapshot(prices: dict[str, float], day: str) -> None:
    if is_guest():
        return                      # nothing to remember between visits
    db.put_snapshot(current_user_id(), day, prices)
