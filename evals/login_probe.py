"""End-to-end sign-in sweep, run as its own process against a throwaway database.

Not a unit test of the hash: this drives the whole flow the way a person does —
register, own something, sign out, sign back in, change the password, get
locked out — and checks the state that should persist actually persists.

Run directly, or via `suite_login` in evals/suites.py, which parses the @@ line.
"""
from __future__ import annotations
import json, os, subprocess, sys, time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))

from fastapi.testclient import TestClient            # noqa: E402
from backend.app.main import app                     # noqa: E402
from backend.app import db                           # noqa: E402

U, P1, P2 = "davidle", "harbor-lantern-first-9", "harbor-lantern-second-9"
RESULTS: list[dict] = []


def chk(name, cond, detail="", why=""):
    RESULTS.append({"id": name, "pass": bool(cond), "detail": str(detail)[:120],
                    "ms": 0, "why": why})
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<42} {str(detail)[:70]}")


def main() -> int:
    c = TestClient(app)

    print("\n-- registration --")
    r = c.post("/api/auth/register", json={"username": U, "password": P1, "name": "David"})
    ck = r.headers.get("set-cookie", "").lower()
    chk("register_200", r.status_code == 200, str(r.json())[:70], "the happy path")
    chk("cookie_httponly", "httponly" in ck, "", "JS must never be able to read the session")
    chk("cookie_samesite_lax", "samesite=lax" in ck, "",
        "blocks another site POSTing with your cookie - this is the CSRF defence")
    chk("cookie_persists", "max-age=" in ck, "",
        "a session cookie would drop on every browser restart")

    print("\n-- identity sticks across calls --")
    me = c.get("/api/me").json()
    chk("me_knows_user", me["username"] == U and me["signed_in"], me["name"],
        "the cookie must identify the user on the NEXT request, not just at login")
    chk("can_save", me["can_save"] is True, "", "the client gates its UI on this")

    print("\n-- the account can actually own things --")
    r = c.post("/api/watchlist", json={"ticker": "TSM"})
    chk("watchlist_write", r.status_code == 200, str(r.json())[:60],
        "signing in is pointless if it does not unlock writes")
    chk("watchlist_read_back", "TSM" in c.get("/api/watchlist").json()["watchlist"], "",
        "written state must come back")
    r = c.post("/api/portfolios", json={"name": "Roth IRA", "kind": "roth ira"})
    chk("portfolio_create", r.status_code in (200, 201), str(r.json())[:60], "same for accounts")

    print("\n-- sign out --")
    chk("logout_204", c.post("/api/auth/logout").status_code == 204, "", "")
    me = c.get("/api/me").json()
    chk("logout_returns_to_guest", me["guest"] and not me["signed_in"], "",
        "the session row must be revoked server-side, not just the cookie cleared")
    chk("guest_cannot_write",
        c.post("/api/watchlist", json={"ticker": "X"}).status_code == 401, "", "")
    chk("guest_sees_nothing", c.get("/api/watchlist").json()["watchlist"] == [], "",
        "a signed-out visitor must not see the book they just left")

    print("\n-- sign back in --")
    r = c.post("/api/auth/login", json={"username": U, "password": P1})
    chk("login_200", r.status_code == 200, str(r.json())[:60], "")
    chk("state_survived_logout", "TSM" in c.get("/api/watchlist").json()["watchlist"], "",
        "the whole point: what you saved is there when you come back")
    chk("accounts_survived_logout",
        {"Brokerage", "Roth IRA"} <= {a["name"] for a in
                                      c.get("/api/portfolios").json()["accounts"]}, "", "")

    print("\n-- username is forgiving, password is not --")
    c2 = TestClient(app)
    chk("username_case_insensitive", c2.post("/api/auth/login",
        json={"username": U.upper(), "password": P1}).status_code == 200, "",
        "nobody remembers how they capitalised it")
    chk("password_case_sensitive", TestClient(app).post("/api/auth/login",
        json={"username": U, "password": P1.upper()}).status_code == 401, "",
        "a case-insensitive password throws away most of its entropy")
    chk("username_trimmed", TestClient(app).post("/api/auth/login",
        json={"username": f"  {U}  ", "password": P1}).status_code == 200, "",
        "autofill and mobile keyboards add spaces")

    print("\n-- password change --")
    r = c.post("/api/auth/password", json={"current": P1, "new": P2})
    chk("change_200", r.status_code == 200, str(r.json())[:60], "")
    chk("old_password_dead", TestClient(app).post("/api/auth/login",
        json={"username": U, "password": P1}).status_code == 401, "", "")
    chk("new_password_works", TestClient(app).post("/api/auth/login",
        json={"username": U, "password": P2}).status_code == 200, "", "")
    chk("changer_stays_signed_in", c.get("/api/me").json()["signed_in"], "",
        "rotating your own password must not sign you out of the tab you did it in")
    chk("other_sessions_revoked", r.json().get("other_sessions_revoked", 0) >= 1,
        f"{r.json().get('other_sessions_revoked')} revoked",
        "a stolen cookie must not outlive the password it was obtained with")
    chk("revoked_session_is_dead", c2.get("/api/me").json()["guest"], "", "")

    print("\n-- throttle, and whether it survives a restart --")
    c3 = TestClient(app)
    codes = [c3.post("/api/auth/login",
                     json={"username": U, "password": "nope-nope-nope"}).status_code
             for _ in range(6)]
    chk("locks_after_max_fails", codes == [401] * 5 + [429], str(codes), "")
    chk("lockout_beats_correct_password", c3.post("/api/auth/login",
        json={"username": U, "password": P2}).status_code == 429, "",
        "otherwise the lockout is bypassed by the one password that matters")
    probe = subprocess.run(
        [sys.executable, "-c", "import sys;sys.path.insert(0,'backend');"
         f"from app import passwords as P;print(P.locked_for('u:{U}'))"],
        capture_output=True, text=True, cwd=os.getcwd())
    left = probe.stdout.strip()
    chk("lockout_shared_across_processes", left.isdigit() and int(left) > 0,
        f"{left}s left in a separate process",
        "REGRESSION: an in-process dict gave every worker, and every restart, "
        "a fresh five guesses")

    print("\n-- registration guards --")
    for name in ("guest", "ADMIN", "monsoon"):
        chk(f"reserved_{name.lower()}", TestClient(app).post("/api/auth/register",
            json={"username": name, "password": "harbor-lantern-third-9"}
            ).status_code == 400, "", "a reserved name must not become an account")
    codes = [TestClient(app).post("/api/auth/register",
             json={"username": f"spam{i}", "password": f"harbor-lantern-{i}-xyz"}
             ).status_code for i in range(12)]
    chk("signup_budget_per_ip", 429 in codes,
        f"{codes.count(200)} created, first 429 at #{codes.index(429)+1}"
        if 429 in codes else str(codes),
        "one host must not be able to mint accounts in a loop")

    print("\n-- session expiry --")
    sid = db.create_session(db.user_by_username(U)["id"], ttl_days=30)
    with db.conn() as k:
        k.execute("UPDATE sessions SET expires_at=? WHERE id=?", (time.time() - 1, sid))
    chk("expired_session_rejected", db.user_for_session(sid) is None, "",
        "a 30-day cookie must stop working on day 31")
    db.create_session(db.user_by_username(U)["id"])        # triggers the prune
    left = db.conn().execute("SELECT COUNT(*) n FROM sessions WHERE expires_at<?",
                             (time.time(),)).fetchone()["n"]
    chk("expired_sessions_pruned", left == 0, f"{left} expired rows left",
        "dead rows that still name a user should not accumulate")

    n = sum(r["pass"] for r in RESULTS)
    print(f"\n{n}/{len(RESULTS)} checks passed")
    print("@@" + json.dumps(RESULTS))
    return 0 if n == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
