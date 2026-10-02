"""Can the AGENT be made to read another user's book?

The API routes are scoped by store.current_user_id(), which reads a
contextvars.ContextVar set once per request. The agent plane is where that is
most likely to break: the router fans out with Send into parallel subgraphs,
each subgraph gathers several tools concurrently, and every portfolio tool calls
store.all_positions() - which trusts that ContextVar.

Two things make this worth testing rather than reasoning about:

  * contextvars propagate to tasks created from the current context, but NOT
    across a bare loop.run_in_executor, and not if a task outlives the request.
  * the ContextVar's default is LOCAL_USER_ID, so losing the context does not
    raise - it silently reads the implicit local user's holdings.

    DB_PATH=/tmp/t.db python evals/agent_tenancy_probe.py [--agent]
"""
from __future__ import annotations
import asyncio, json, os, sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))

from fastapi.testclient import TestClient              # noqa: E402
from backend.app.main import app                       # noqa: E402
from backend.app import db, store                      # noqa: E402

R: list[dict] = []
PW = "harbor-lantern-agent-9"
# deliberately disjoint books, so a crossover is unmistakable
BOOKS = {"ann": ("KO", 11.0, 50.0), "ben": ("XOM", 77.0, 77.0)}
LOCAL_MARK = "PLTR"          # only the implicit local user holds this


def _write_fails() -> bool:
    import threading
    box = {}

    def go():
        try:
            store.save({"watchlist": ["ZZZ"], "portfolios": []})
            box["ok"] = False          # a write went through with no identity
        except Exception:
            box["ok"] = True

    t = threading.Thread(target=go)
    t.start()
    t.join()
    return box.get("ok", False)


def chk(name, cond, detail="", why=""):
    R.append({"id": name, "pass": bool(cond), "detail": str(detail)[:130],
              "ms": 0, "why": why})
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<44} {str(detail)[:58]}")


def setup():
    # give the LOCAL user a distinctive holding: if the context is ever lost,
    # the default kicks in and this ticker shows up where it must not
    store.set_current_user(db.LOCAL_USER_ID)
    d = store.load()
    d["portfolios"][0]["positions"] = [{"ticker": LOCAL_MARK, "qty": 999, "basis": 1.0}]
    store.save(d)

    clients = {}
    for user, (tk, qty, basis) in BOOKS.items():
        c = TestClient(app)
        c.post("/api/auth/register", json={"username": user, "password": PW})
        c.post("/api/reset?keep_watchlist=true")            # drop the demo seed
        pid = c.get("/api/portfolios").json()["accounts"][0]["id"]
        c.post("/api/positions", json={"ticker": tk, "qty": qty, "basis": basis,
                                       "portfolio_id": pid})
        clients[user] = c
    return clients


async def main(run_agent: bool) -> int:
    clients = setup()

    print("\n── the tools themselves, under the request's context ──")
    from backend.app.tools import TOOLS
    for user, (tk, _, _) in BOOKS.items():
        uid = db.user_by_username(user)["id"]
        store.set_current_user(uid)
        # exactly how a subgraph runs them: several at once, from one context
        res = await asyncio.gather(TOOLS["positions"].fn("", account="all"),
                                   TOOLS["day_pnl"].fn("", account="all"),
                                   TOOLS["concentration"].fn("", account="all"))
        blob = json.dumps([getattr(r, "data", None) for r in res])
        others = [o for o, (otk, _, _) in BOOKS.items() if o != user and otk in blob]
        chk(f"tools_see_only_{user}s_book",
            tk in blob and not others and LOCAL_MARK not in blob,
            f"{tk} present, foreign {others or 'none'}, local-leak "
            f"{'YES' if LOCAL_MARK in blob else 'no'}",
            "parallel tool execution must inherit the caller's context")

    print("\n── concurrent requests must not cross over ──")
    # interleave both users' portfolio reads many times over
    async def read(user):
        return clients[user].get("/api/portfolio?portfolio_id=all").json()

    rounds = await asyncio.gather(*[read(u) for u in list(BOOKS) * 12])
    bad = []
    for i, d in enumerate(rounds):
        user = (list(BOOKS) * 12)[i]
        tks = {p["ticker"] for p in d["positions"]}
        want = {BOOKS[user][0]}
        if tks != want:
            bad.append((user, sorted(tks)))
    chk("concurrent_reads_never_cross", not bad, bad or f"{len(rounds)} reads, each its own",
        "a ContextVar set per request must not bleed between in-flight requests")

    print("\n── a lost context must fail closed ──")
    # A BARE THREAD is the real test. asyncio.to_thread and create_task both
    # COPY the current context, so neither loses it - my first attempt used
    # to_thread and inherited the user I had just set, which looked like a leak
    # and was not. threading.Thread inherits nothing.
    import threading
    seen = {}

    def orphan():
        seen["uid"] = store.current_user_id()
        seen["tickers"] = [p["ticker"] for p in store.all_positions("all")]
        seen["watchlist"] = store.load()["watchlist"]

    store.set_current_user(db.user_by_username("ben")["id"])
    t = threading.Thread(target=orphan)
    t.start()
    t.join()
    chk("lost_context_sees_no_holdings",
        seen["tickers"] == [] and seen["watchlist"] == [],
        f"resolved to {seen['uid']!r}, saw {seen['tickers']} / {seen['watchlist']}",
        "REGRESSION: the contextvar defaulted to the local user, so code "
        "outside a request read one real person's book instead of nothing")
    chk("lost_context_cannot_write", _write_fails(),
        "store.save() raises for a context-less caller",
        "a fail-open default on writes would corrupt a real book")

    if run_agent:
        print("\n── the agent, asked about 'my portfolio' ──")
        for user, (tk, _, _) in BOOKS.items():
            d = clients[user].post("/api/agent/ask",
                                   json={"question": "What is in my portfolio right now?"},
                                   timeout=300).json()
            blob = json.dumps(d.get("findings", [])) + d.get("answer", "")
            others = [o for o, (otk, _, _) in BOOKS.items() if o != user and otk in blob]
            chk(f"agent_answers_{user}_from_{user}s_book",
                not others and LOCAL_MARK not in blob,
                f"foreign {others or 'none'}, local-leak "
                f"{'YES' if LOCAL_MARK in blob else 'no'}",
                "the agent reads the book through the same contextvar")
    else:
        print("\n  SKIP  live agent calls (pass --agent to spend tokens)")

    n = sum(x["pass"] for x in R)
    print(f"\n{n}/{len(R)} checks passed")
    print("@@" + json.dumps(R))
    return 0 if n == len(R) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--agent" in sys.argv)))
