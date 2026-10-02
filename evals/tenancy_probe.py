"""Tenancy probe: can one account reach another's book?

SQLite has no row-level security, so isolation here is enforced by the
application: every query is scoped by user_id, and anything reached by
portfolio_id is resolved against the CURRENT user's document first. That is a
weaker guarantee than RLS - one missing WHERE is a cross-account leak and the
database will not stop it - so it gets tested directly rather than assumed.

Two users, each with their own accounts and positions. Then user A is handed
user B's real ids and tries every id-taking operation in the API.

    DB_PATH=/tmp/t.db python evals/tenancy_probe.py
"""
from __future__ import annotations
import json, os, sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))

from fastapi.testclient import TestClient              # noqa: E402
from backend.app.main import app                       # noqa: E402
from backend.app import db                             # noqa: E402

R: list[dict] = []
PW = "harbor-lantern-tenancy-9"


def chk(name, cond, detail="", why=""):
    R.append({"id": name, "pass": bool(cond), "detail": str(detail)[:130],
              "ms": 0, "why": why})
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<42} {str(detail)[:62]}")


def person(username: str, account: str, ticker: str, qty: float, basis: float):
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": username, "password": PW})
    pf = c.post("/api/portfolios", json={"name": account, "kind": "roth ira"}).json()
    pid = next(a["id"] for a in pf["accounts"] if a["name"] == account)
    c.post("/api/positions", json={"ticker": ticker, "qty": qty, "basis": basis,
                                   "portfolio_id": pid})
    c.post("/api/watchlist", json={"ticker": ticker})
    return c, pid


def main() -> int:
    A, a_pid = person("alice", "Alice Roth", "KO", 11, 50.0)
    B, b_pid = person("bob", "Bob Roth", "XOM", 77, 77.0)
    print(f"\nalice account {a_pid}, bob account {b_pid}")

    print("\n── each book is its own ──")
    a_names = {x["name"] for x in A.get("/api/portfolios").json()["accounts"]}
    b_names = {x["name"] for x in B.get("/api/portfolios").json()["accounts"]}
    chk("accounts_not_shared", "Bob Roth" not in a_names and "Alice Roth" not in b_names,
        f"alice sees {sorted(a_names)}", "the listing must be per-user")
    a_wl = set(A.get("/api/watchlist").json()["watchlist"])
    chk("watchlist_not_shared", "XOM" not in a_wl, f"alice: {sorted(a_wl)}", "")
    a_all = A.get("/api/portfolio?portfolio_id=all").json()
    chk("combined_view_is_own_only",
        all(p["ticker"] != "XOM" for p in a_all["positions"]),
        f"{[p['ticker'] for p in a_all['positions']]}",
        "'all accounts' must mean all of MINE")

    print("\n── alice attacks bob's ids (read) ──")
    r = A.get(f"/api/portfolio?portfolio_id={b_pid}").json()
    chk("read_foreign_portfolio_empty",
        r["positions"] == [] and r["market_value"] == 0,
        f"{len(r['positions'])} rows, ${r['market_value']}",
        "a foreign id must resolve to nothing, not to its owner's holdings")
    chk("read_foreign_portfolio_leaks_no_name", r.get("portfolio_name") != "Bob Roth",
        r.get("portfolio_name"), "not even the account NAME may leak")
    an = A.get(f"/api/portfolio/analytics?portfolio_id={b_pid}").json()
    blob = json.dumps(an)
    chk("analytics_on_foreign_id_is_empty", "XOM" not in blob and "Bob" not in blob,
        f"concentration={an.get('concentration')}",
        "derived numbers are still the owner's data")

    print("\n── alice attacks bob's ids (write) ──")
    r = A.patch(f"/api/portfolios/{b_pid}", json={"name": "pwned"})
    chk("rename_foreign_account_denied", r.status_code in (403, 404), r.status_code,
        "renaming someone else's account must fail")
    chk("rename_had_no_effect",
        "pwned" not in {x["name"] for x in B.get("/api/portfolios").json()["accounts"]},
        sorted(x["name"] for x in B.get("/api/portfolios").json()["accounts"]), "")

    r = A.post("/api/positions", json={"ticker": "NVDA", "qty": 1, "basis": 1.0,
                                       "portfolio_id": b_pid})
    b_rows = B.get(f"/api/portfolio?portfolio_id={b_pid}").json()["positions"]
    chk("insert_into_foreign_account_denied",
        all(p["ticker"] != "NVDA" for p in b_rows),
        f"bob holds {[p['ticker'] for p in b_rows]} (request returned {r.status_code})",
        "writing into someone else's account is the worst case - it is silent")

    r = A.patch("/api/positions/XOM", json={"ticker": "XOM", "qty": 1, "basis": 1.0,
                                            "portfolio_id": b_pid})
    xom = next((p for p in B.get(f"/api/portfolio?portfolio_id={b_pid}"
                                 ).json()["positions"] if p["ticker"] == "XOM"), {})
    chk("edit_foreign_position_denied",
        r.status_code in (403, 404) and xom.get("qty") == 77,
        f"{r.status_code}; bob's XOM qty still {xom.get('qty')}", "")

    r = A.delete(f"/api/positions/XOM?portfolio_id={b_pid}")
    still = [p["ticker"] for p in B.get(f"/api/portfolio?portfolio_id={b_pid}"
                                        ).json()["positions"]]
    chk("delete_foreign_position_denied", "XOM" in still,
        f"{r.status_code}; bob still holds {still}", "")

    r = A.post(f"/api/portfolios/{b_pid}/activate")
    chk("activate_foreign_account_denied", r.status_code in (403, 404), r.status_code,
        "activating a foreign id would point every later call at it")

    a_wl_before = set(A.get("/api/watchlist").json()["watchlist"])
    r = A.post(f"/api/reset?portfolio_id={b_pid}")
    chk("reset_foreign_id_rejected", r.status_code == 404, r.status_code,
        "a no-op must not report success - it used to return 200")
    chk("reset_cannot_wipe_foreign_account",
        [p["ticker"] for p in B.get(f"/api/portfolio?portfolio_id={b_pid}"
                                     ).json()["positions"]] == ["XOM"],
        "bob's book intact", "reset is the most destructive verb here")
    chk("reset_foreign_id_spares_own_watchlist",
        set(A.get("/api/watchlist").json()["watchlist"]) == a_wl_before,
        f"{sorted(a_wl_before)} still there",
        "REGRESSION: a reset naming ONE account wiped the whole watchlist, even "
        "when the id matched nothing")

    r = A.delete(f"/api/portfolios/{b_pid}")
    chk("delete_foreign_account_denied", r.status_code == 404,
        f"{r.status_code} (was 200 - a silent no-op reported as success)", "")
    chk("delete_foreign_had_no_effect",
        "Bob Roth" in {x["name"] for x in B.get("/api/portfolios").json()["accounts"]},
        "bob's account still exists", "")

    print("\n── reset blast radius on your OWN book ──")
    own = next(x["id"] for x in A.get("/api/portfolios").json()["accounts"]
               if x["name"] == "Alice Roth")
    A.post("/api/watchlist", json={"ticker": "TSM"})
    before = set(A.get("/api/watchlist").json()["watchlist"])
    r = A.post(f"/api/reset?portfolio_id={own}")
    after = set(A.get("/api/watchlist").json()["watchlist"])
    rows = [p for p in A.get(f"/api/portfolio?portfolio_id={own}").json()["positions"]]
    chk("per_account_reset_clears_that_account", r.status_code == 200 and rows == [],
        f"{r.status_code}, {len(rows)} positions left", "")
    chk("per_account_reset_keeps_watchlist", after == before,
        f"{len(before)} before, {len(after)} after",
        "REGRESSION: the watchlist belongs to no single account, so a "
        "per-account reset must not touch it")
    other = [p["ticker"] for p in A.get("/api/portfolio?portfolio_id=all"
                                         ).json()["positions"]]
    chk("per_account_reset_spares_other_accounts", len(other) > 0,
        f"alice's other accounts still hold {other}", "")

    print("\n── session boundaries ──")
    chk("cannot_change_another_password",
        A.post("/api/auth/password", json={"current": PW, "new": PW + "x"}
               ).status_code == 200
        and TestClient(app).post("/api/auth/login",
                                 json={"username": "bob", "password": PW + "x"}
                                 ).status_code == 401,
        "alice's rotation did not touch bob", "")
    r = A.delete("/api/auth/account?confirm=bob")
    chk("cannot_delete_another_account", r.status_code == 400
        and db.user_by_username("bob") is not None, r.status_code,
        "confirm must match the CALLER's username, not any username")

    print("\n── what the database itself enforces ──")
    cols = {r_["name"] if hasattr(r_, "keys") else r_[1]
            for r_ in db.conn().execute("PRAGMA table_info(positions)").fetchall()}
    chk("positions_carries_user_id", "user_id" in cols, sorted(cols),
        "positions used to be scoped only TRANSITIVELY via portfolio_id, so "
        "isolation depended on every caller resolving the portfolio first")
    chk("positions_scope_invariant_holds", db.positions_scope_mismatches() == 0,
        f"{db.positions_scope_mismatches()} rows disagree with their portfolio's owner",
        "the denormalised column is only safe if it can never drift")
    rows = db.conn().execute("SELECT user_id, COUNT(*) n FROM positions"
                             " GROUP BY user_id").fetchall()
    owners = {r_["user_id"]: r_["n"] for r_ in rows}
    chk("every_position_row_is_owned", None not in owners, owners,
        "a NULL owner would be invisible to a user_id filter")
    a_uid = db.user_by_username("alice")["id"]
    direct = db.conn().execute("SELECT ticker FROM positions WHERE user_id=?",
                               (a_uid,)).fetchall()
    chk("direct_user_scoped_query_works",
        {r_["ticker"] for r_ in direct} and "XOM" not in {r_["ticker"] for r_ in direct},
        f"alice's rows by user_id alone: {sorted(r_['ticker'] for r_ in direct)}",
        "the whole point of the column: scoping without a join")
    fk = db.conn().execute("PRAGMA foreign_keys").fetchone()
    chk("foreign_keys_enforced", (fk["foreign_keys"] if hasattr(fk, "keys") else fk[0]) == 1,
        "ON", "cascade deletes rely on this being on")

    print("\n── the backfill, on a database that predates the column ──")
    import shutil, sqlite3, subprocess, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        old = os.path.join(tmp, "old.db")
        # build a pre-migration database by hand: positions WITHOUT user_id
        k = sqlite3.connect(old)
        k.executescript("""
          CREATE TABLE users(id TEXT PRIMARY KEY, email TEXT, name TEXT,
            provider TEXT, provider_id TEXT, created_at REAL NOT NULL);
          CREATE TABLE portfolios(id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
            name TEXT NOT NULL, kind TEXT, created_at REAL NOT NULL);
          CREATE TABLE positions(id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_id TEXT NOT NULL, ticker TEXT NOT NULL,
            qty REAL NOT NULL, basis REAL NOT NULL, UNIQUE(portfolio_id,ticker));
          INSERT INTO users VALUES('u1',NULL,'One','local','u1',0),
                                  ('u2',NULL,'Two','local','u2',0);
          INSERT INTO portfolios VALUES('p1','u1','A',NULL,0),('p2','u2','B',NULL,0);
          INSERT INTO positions(portfolio_id,ticker,qty,basis)
            VALUES('p1','KO',1,1),('p1','PEP',2,2),('p2','XOM',3,3);
        """)
        k.commit()
        k.close()
        probe = ("import sys;sys.path.insert(0,'backend');from app import db;"
                 "c=db.conn();"
                 "print(sorted((r['user_id'],r['ticker']) for r in "
                 "c.execute('SELECT user_id,ticker FROM positions')));"
                 "print(db.positions_scope_mismatches())")
        r = subprocess.run([sys.executable, "-c", probe],
                           env={**os.environ, "DB_PATH": old},
                           capture_output=True, text=True, cwd=os.getcwd())
        lines = [x for x in r.stdout.strip().splitlines() if x]
    want = "[('u1', 'KO'), ('u1', 'PEP'), ('u2', 'XOM')]"
    chk("backfill_assigns_the_right_owner", lines and lines[0] == want,
        lines[0] if lines else (r.stderr or "")[-110:],
        "an existing install must come up with every row correctly owned")
    chk("backfill_leaves_no_mismatch", len(lines) > 1 and lines[1] == "0",
        lines[1] if len(lines) > 1 else "no output", "")

    n = sum(x["pass"] for x in R)
    print(f"\n{n}/{len(R)} checks passed")
    print("@@" + json.dumps(R))
    return 0 if n == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
