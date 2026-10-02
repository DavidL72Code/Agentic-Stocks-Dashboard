"""SQLite store with a multi-user schema.

Everything is scoped to a user_id from day one, even though only one user
exists right now. That is the whole point: adding OAuth later becomes a login
route and a session cookie, not a rewrite of every query.

stdlib sqlite3 in a worker thread - no extra dependency, no server. WAL mode so
reads do not block the writer.

Set TURSO_DATABASE_URL (and TURSO_AUTH_TOKEN) to run the same schema and the
same queries against Turso instead, which is libSQL - a fork of SQLite that
speaks the same dialect over the network. Nothing below changes; only where
conn() points. See README for the walkthrough.
"""
from __future__ import annotations
import asyncio, json, os, pathlib, sqlite3, threading, time, uuid
from collections.abc import Mapping

DB_PATH = pathlib.Path(os.environ.get("DB_PATH", "data/monsoon.db"))
TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "").strip()
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
LOCAL_USER_ID = "local"          # the implicit single user until auth is switched on
_local = threading.local()


def backend_name() -> str:
    return "turso" if TURSO_URL else "sqlite"

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  email         TEXT UNIQUE,
  name          TEXT,
  provider      TEXT,              -- 'password' | 'local' | 'google' / 'github' later
  provider_id   TEXT,
  created_at    REAL NOT NULL,
  UNIQUE(provider, provider_id)
);

-- username/password accounts. password_hash holds an argon2id (or scrypt)
-- digest and its salt - never the password. OAuth users keep it NULL, so the
-- two kinds of account coexist in one table.
CREATE TABLE IF NOT EXISTS sessions (
  id          TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  REAL NOT NULL,
  expires_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS portfolios (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  kind       TEXT,
  created_at REAL NOT NULL,
  UNIQUE(user_id, name)
);
CREATE INDEX IF NOT EXISTS ix_portfolios_user ON portfolios(user_id);

CREATE TABLE IF NOT EXISTS positions (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  portfolio_id TEXT NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
  ticker       TEXT NOT NULL,
  qty          REAL NOT NULL,
  basis        REAL NOT NULL,
  UNIQUE(portfolio_id, ticker)     -- same ticker in two ACCOUNTS stays two rows
);
CREATE INDEX IF NOT EXISTS ix_positions_pf ON positions(portfolio_id);

CREATE TABLE IF NOT EXISTS watchlist (
  user_id  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  ticker   TEXT NOT NULL,
  added_at REAL NOT NULL,
  PRIMARY KEY (user_id, ticker)
);

CREATE TABLE IF NOT EXISTS prefs (
  user_id           TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  active_portfolio  TEXT,
  seeded            INTEGER NOT NULL DEFAULT 1
);

-- Failed login attempts. This lives in the database rather than in a dict in
-- one process so that the lockout is real: it survives a restart (otherwise a
-- crash loop resets the counter) and it is shared by every worker (otherwise
-- an attacker just spreads guesses across them).
CREATE TABLE IF NOT EXISTS login_fails (
  key  TEXT NOT NULL,          -- 'u:<username>' or 'ip:<address>'
  at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_login_fails ON login_fails(key, at);

CREATE TABLE IF NOT EXISTS snapshots (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  day     TEXT NOT NULL,
  prices  TEXT NOT NULL,
  PRIMARY KEY (user_id, day)
);
"""


# Columns added after the first release. CREATE TABLE IF NOT EXISTS will not
# add them to a database that already exists, so they are applied explicitly.
ADD_COLUMNS = [
    ("users", "username",      "TEXT"),
    ("users", "password_hash", "TEXT"),
]
POST_SCHEMA = [
    # case-insensitive: "David" and "david" must not be two accounts
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_username"
    " ON users(lower(username)) WHERE username IS NOT NULL",
]


def _migrate(c) -> None:
    for table, col, decl in ADD_COLUMNS:
        # libSQL rows are tuples, not sqlite3.Row; PRAGMA table_info puts the
        # column name second either way
        cols = {(r["name"] if hasattr(r, "keys") else r[1])
                for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
        if col not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    for stmt in POST_SCHEMA:
        c.execute(stmt)
    c.commit()


# ── libSQL compatibility shim ────────────────────────────────────────────
# The libsql driver is DB-API-ish but not sqlite3: its cursor is not iterable,
# its rows are plain tuples rather than sqlite3.Row, and its connection is not
# a context manager. Every query in this file is written against sqlite3's
# conveniences, so the differences are absorbed here rather than smeared across
# forty call sites.
class _Row(Mapping):
    __slots__ = ("_k", "_v")

    def __init__(self, keys, values):
        self._k, self._v = keys, values

    def __getitem__(self, k):
        return self._v[k] if isinstance(k, int) else self._v[self._k.index(k)]

    def __iter__(self):
        return iter(self._k)

    def __len__(self):
        return len(self._k)

    def keys(self):
        return list(self._k)


class _Cursor:
    def __init__(self, cur):
        self._c = cur
        self._keys = [d[0] for d in (cur.description or ())]

    def _wrap(self, row):
        return _Row(self._keys, row) if row is not None else None

    def fetchall(self):
        return [self._wrap(r) for r in self._c.fetchall()]

    def fetchone(self):
        return self._wrap(self._c.fetchone())

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def rowcount(self):
        return self._c.rowcount


class _Conn:
    """sqlite3-shaped wrapper over a libsql connection."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        return _Cursor(self._raw.execute(sql, params))

    def executescript(self, script):
        for stmt in (x.strip() for x in script.split(";")):
            if stmt and not stmt.upper().startswith("PRAGMA"):
                self._raw.execute(stmt)
        self._raw.commit()

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    # sqlite3 connections commit on a clean `with` block and roll back on error
    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        self._raw.rollback() if exc_type else self._raw.commit()
        return False


def _connect_turso():
    try:
        import libsql_experimental as libsql
    except ImportError:                      # pragma: no cover - deployment path
        raise RuntimeError(
            "TURSO_DATABASE_URL is set but libsql-experimental is not installed. "
            "Run: pip install libsql-experimental") from None
    c = _Conn(libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN))
    c.executescript(SCHEMA)                  # PRAGMAs are the server's business
    return c


def conn():
    c = getattr(_local, "c", None)
    if c is None:
        if TURSO_URL:
            c = _connect_turso()
        else:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.executescript(SCHEMA)
        _migrate(c)
        _local.c = c
    return c


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ───────────────────────── users ─────────────────────────
def ensure_user(uid: str = LOCAL_USER_ID, *, email=None, name=None,
                provider="local", provider_id=None) -> str:
    c = conn()
    row = c.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
    if row:
        return row["id"]
    c.execute("INSERT INTO users(id,email,name,provider,provider_id,created_at)"
              " VALUES(?,?,?,?,?,?)",
              (uid, email, name or "Local user", provider, provider_id or uid, time.time()))
    c.execute("INSERT OR IGNORE INTO prefs(user_id,seeded) VALUES(?,1)", (uid,))
    c.commit()
    return uid


def user_by_provider(provider: str, provider_id: str) -> dict | None:
    r = conn().execute("SELECT * FROM users WHERE provider=? AND provider_id=?",
                       (provider, provider_id)).fetchone()
    return dict(r) if r else None


def user_by_username(username: str) -> dict | None:
    r = conn().execute("SELECT * FROM users WHERE lower(username)=lower(?)",
                       (username,)).fetchone()
    return dict(r) if r else None


def create_password_user(username: str, password_hash: str, *,
                         name: str | None = None, email: str | None = None) -> str:
    """Raises sqlite3.IntegrityError if the username is taken - the unique
    index is the authority, not a prior SELECT, so two simultaneous signups
    cannot both succeed."""
    uid = new_id()
    c = conn()
    with c:
        c.execute("INSERT INTO users(id,email,name,provider,provider_id,created_at,"
                  "username,password_hash) VALUES(?,?,?,?,?,?,?,?)",
                  (uid, email, name or username, "password", uid, time.time(),
                   username, password_hash))
        c.execute("INSERT OR IGNORE INTO prefs(user_id,seeded) VALUES(?,1)", (uid,))
    return uid


def set_password_hash(uid: str, password_hash: str) -> None:
    c = conn()
    with c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, uid))


def get_user(uid: str) -> dict | None:
    r = conn().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return dict(r) if r else None


# ───────────────────────── sessions (for OAuth later) ─────────────────────────
def create_session(uid: str, ttl_days: int = 30) -> str:
    sid = uuid.uuid4().hex
    now = time.time()
    c = conn()
    c.execute("INSERT INTO sessions(id,user_id,created_at,expires_at) VALUES(?,?,?,?)",
              (sid, uid, now, now + ttl_days * 86400))
    # expired rows are dead weight that still name a user - drop them here
    # rather than adding a cron for one DELETE
    c.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    c.commit()
    return sid


def user_for_session(sid: str) -> str | None:
    r = conn().execute("SELECT user_id FROM sessions WHERE id=? AND expires_at>?",
                       (sid, time.time())).fetchone()
    return r["user_id"] if r else None


def count_password_users() -> int:
    return conn().execute(
        "SELECT COUNT(*) n FROM users WHERE password_hash IS NOT NULL").fetchone()["n"]


def legacy_book_summary(uid: str = LOCAL_USER_ID) -> dict | None:
    """What the pre-login local user still holds, or None if there is nothing
    worth claiming. `seeded` means the rows are the untouched demo book, which
    nobody needs to inherit."""
    c = conn()
    pr = c.execute("SELECT seeded FROM prefs WHERE user_id=?", (uid,)).fetchone()
    if not pr or pr["seeded"]:
        return None
    pfs = c.execute("SELECT COUNT(*) n FROM portfolios WHERE user_id=?", (uid,)).fetchone()["n"]
    pos = c.execute("SELECT COUNT(*) n FROM positions p JOIN portfolios f"
                    " ON f.id=p.portfolio_id WHERE f.user_id=?", (uid,)).fetchone()["n"]
    wl = c.execute("SELECT COUNT(*) n FROM watchlist WHERE user_id=?", (uid,)).fetchone()["n"]
    if not (pfs or wl):
        return None
    names = [r["name"] for r in c.execute(
        "SELECT name FROM portfolios WHERE user_id=? ORDER BY created_at", (uid,))]
    return {"portfolios": pfs, "positions": pos, "watchlist": wl, "names": names}


def adopt_user_data(src_uid: str, dst_uid: str) -> bool:
    """Hand the pre-login local user's book to a real account, on request.

    Never automatic: see the claim-legacy route for why.
    """
    c = conn()
    if src_uid == dst_uid or not get_user(src_uid):
        return False
    has = c.execute("SELECT 1 FROM portfolios WHERE user_id=? LIMIT 1", (src_uid,)).fetchone()
    if not has:
        return False
    with c:
        # A just-registered account is holding the untouched demo seed; that is
        # not worth preserving, and it is also what collides on name.
        pr = c.execute("SELECT seeded FROM prefs WHERE user_id=?", (dst_uid,)).fetchone()
        if pr and pr["seeded"]:
            c.execute("DELETE FROM portfolios WHERE user_id=?", (dst_uid,))
        c.execute("DELETE FROM prefs WHERE user_id=?", (dst_uid,))

        # Anything still colliding on UNIQUE(user_id, name) gets a suffix rather
        # than failing the whole claim half-done.
        taken = {r["name"].lower() for r in c.execute(
            "SELECT name FROM portfolios WHERE user_id=?", (dst_uid,))}
        for r in c.execute("SELECT id,name FROM portfolios WHERE user_id=?",
                           (src_uid,)).fetchall():
            name = r["name"]
            if name.lower() in taken:
                n = 2
                while f"{name} ({n})".lower() in taken:
                    n += 1
                name = f"{name} ({n})"
                c.execute("UPDATE portfolios SET name=? WHERE id=?", (name, r["id"]))
            taken.add(name.lower())

        # the watchlist is keyed (user_id, ticker), so merge instead of move
        for r in c.execute("SELECT ticker,added_at FROM watchlist WHERE user_id=?",
                           (src_uid,)).fetchall():
            c.execute("INSERT OR IGNORE INTO watchlist(user_id,ticker,added_at)"
                      " VALUES(?,?,?)", (dst_uid, r["ticker"], r["added_at"]))
        c.execute("DELETE FROM watchlist WHERE user_id=?", (src_uid,))

        for t in ("portfolios", "prefs", "snapshots"):
            c.execute(f"UPDATE {t} SET user_id=? WHERE user_id=?", (dst_uid, src_uid))
    return True


def delete_user(uid: str) -> None:
    """Everything hangs off users(id) with ON DELETE CASCADE, so one row does
    it - as long as foreign keys are actually on, which conn() enforces."""
    c = conn()
    with c:
        c.execute("PRAGMA foreign_keys=ON")
        for t in ("positions",):          # positions reach users only via portfolios
            c.execute(f"DELETE FROM {t} WHERE portfolio_id IN"
                      " (SELECT id FROM portfolios WHERE user_id=?)", (uid,))
        c.execute("DELETE FROM users WHERE id=?", (uid,))


def drop_user_sessions(uid: str, keep: str | None = None) -> int:
    """Revoke every session for a user, optionally sparing the current one.
    Called on password change: a stolen cookie must not outlive the password."""
    c = conn()
    with c:
        cur = c.execute("DELETE FROM sessions WHERE user_id=? AND id IS NOT ?", (uid, keep))
    return cur.rowcount


def drop_session(sid: str) -> None:
    c = conn()
    c.execute("DELETE FROM sessions WHERE id=?", (sid,))
    c.commit()


# ───────────────────────── documents ─────────────────────────
def read_doc(uid: str) -> dict:
    """Assemble this user's whole state. Callers work with a plain dict; the
    schema underneath is relational and user-scoped."""
    c = conn()
    ensure_user(uid)
    pfs = []
    for p in c.execute("SELECT * FROM portfolios WHERE user_id=? ORDER BY created_at", (uid,)):
        pos = [dict(ticker=r["ticker"], qty=r["qty"], basis=r["basis"])
               for r in c.execute("SELECT ticker,qty,basis FROM positions"
                                  " WHERE portfolio_id=? ORDER BY id", (p["id"],))]
        pfs.append({"id": p["id"], "name": p["name"], "kind": p["kind"], "positions": pos})
    wl = [r["ticker"] for r in c.execute(
        "SELECT ticker FROM watchlist WHERE user_id=? ORDER BY added_at", (uid,))]
    pr = c.execute("SELECT * FROM prefs WHERE user_id=?", (uid,)).fetchone()
    snaps = {}
    for r in c.execute("SELECT day,prices FROM snapshots WHERE user_id=?"
                       " ORDER BY day DESC LIMIT 2", (uid,)):
        key = "last" if not snaps else "prev"
        snaps[key] = {"day": r["day"], "prices": json.loads(r["prices"])}
    ids = [p["id"] for p in pfs]
    active = pr["active_portfolio"] if pr else None
    return {"user_id": uid, "watchlist": wl, "portfolios": pfs,
            "active": active if (active in ids or active == "all") else (ids[0] if ids else None),
            "seeded": bool(pr["seeded"]) if pr else False,
            "snapshots": snaps}


def write_doc(uid: str, d: dict, touched: bool = True) -> None:
    """Persist the whole document for one user, transactionally."""
    c = conn()
    ensure_user(uid)
    with c:                                  # one transaction
        keep = {p["id"] for p in d.get("portfolios", [])}
        for r in c.execute("SELECT id FROM portfolios WHERE user_id=?", (uid,)).fetchall():
            if r["id"] not in keep:
                c.execute("DELETE FROM portfolios WHERE id=?", (r["id"],))
        for p in d.get("portfolios", []):
            # an id that already belongs to somebody else is never written
            # through: upserting it would hand this user's edits to them
            owner = c.execute("SELECT user_id FROM portfolios WHERE id=?",
                              (p["id"],)).fetchone()
            if owner and owner["user_id"] != uid:
                p["id"] = new_id()
            c.execute("INSERT INTO portfolios(id,user_id,name,kind,created_at)"
                      " VALUES(?,?,?,?,?)"
                      " ON CONFLICT(id) DO UPDATE SET name=excluded.name, kind=excluded.kind",
                      (p["id"], uid, p["name"], p.get("kind"), time.time()))
            tickers = {x["ticker"] for x in p.get("positions", [])}
            for r in c.execute("SELECT ticker FROM positions WHERE portfolio_id=?",
                               (p["id"],)).fetchall():
                if r["ticker"] not in tickers:
                    c.execute("DELETE FROM positions WHERE portfolio_id=? AND ticker=?",
                              (p["id"], r["ticker"]))
            for x in p.get("positions", []):
                c.execute("INSERT INTO positions(portfolio_id,ticker,qty,basis)"
                          " VALUES(?,?,?,?)"
                          " ON CONFLICT(portfolio_id,ticker)"
                          " DO UPDATE SET qty=excluded.qty, basis=excluded.basis",
                          (p["id"], x["ticker"], x["qty"], x["basis"]))

        wl = d.get("watchlist", [])
        c.execute("DELETE FROM watchlist WHERE user_id=?", (uid,))
        for i, t in enumerate(wl):
            c.execute("INSERT OR IGNORE INTO watchlist(user_id,ticker,added_at)"
                      " VALUES(?,?,?)", (uid, t, time.time() + i * 1e-6))

        seeded = 0 if touched else (1 if d.get("seeded") else 0)
        c.execute("INSERT INTO prefs(user_id,active_portfolio,seeded) VALUES(?,?,?)"
                  " ON CONFLICT(user_id) DO UPDATE SET"
                  " active_portfolio=excluded.active_portfolio, seeded=excluded.seeded",
                  (uid, d.get("active"), seeded))


# ───────────────────────── login throttle ─────────────────────────
def recent_fails(key: str, window: float) -> list[float]:
    cut = time.time() - window
    return [r["at"] for r in conn().execute(
        "SELECT at FROM login_fails WHERE key=? AND at>? ORDER BY at", (key, cut))]


def add_fail(key: str, window: float) -> None:
    c = conn()
    with c:
        c.execute("INSERT INTO login_fails(key,at) VALUES(?,?)", (key, time.time()))
        # opportunistic prune, so the table cannot grow without bound
        c.execute("DELETE FROM login_fails WHERE at<?", (time.time() - window * 4,))


def clear_fails(key: str) -> None:
    c = conn()
    with c:
        c.execute("DELETE FROM login_fails WHERE key=?", (key,))


def put_snapshot(uid: str, day: str, prices: dict) -> None:
    c = conn()
    with c:
        c.execute("INSERT INTO snapshots(user_id,day,prices) VALUES(?,?,?)"
                  " ON CONFLICT(user_id,day) DO UPDATE SET prices=excluded.prices",
                  (uid, day, json.dumps(prices)))
        c.execute("DELETE FROM snapshots WHERE user_id=? AND day NOT IN"
                  " (SELECT day FROM snapshots WHERE user_id=? ORDER BY day DESC LIMIT 30)",
                  (uid, uid))


def migrate_from_json(path: pathlib.Path, uid: str = LOCAL_USER_ID) -> bool:
    """One-time import of the old single-file store."""
    if not path.exists():
        return False
    c = conn()
    ensure_user(uid)
    has = c.execute("SELECT 1 FROM portfolios WHERE user_id=? LIMIT 1", (uid,)).fetchone()
    if has:
        return False
    d = json.loads(path.read_text())
    if "portfolios" not in d:                 # even older flat layout
        d["portfolios"] = [{"id": "default", "name": "Brokerage", "kind": "taxable",
                            "positions": d.get("positions", [])}]
    for p in d["portfolios"]:
        p.setdefault("id", new_id())
    write_doc(uid, d, touched=False)
    path.rename(path.with_suffix(".json.migrated"))
    return True
