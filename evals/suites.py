"""Deterministic suites: data plane, tools, and regressions for bugs found
during the build. None of these spend a token."""
from __future__ import annotations
import asyncio, http.cookiejar, json, secrets, sys, time, urllib.error, urllib.request

BASE = "http://localhost:8077"

# Login is on by default, so the suite signs in as its own account rather than
# measuring a signed-out guest with an empty book. The cookie jar is what makes
# every later call run as that user.
EVAL_USER = "monsoon-evals"
EVAL_PASS = "evals-only-not-a-real-secret-7"
_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def api(path, method="GET", body=None, timeout=180, anon=False):
    """anon=True sends no cookies - used to check what a guest actually sees."""
    req = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener() if anon else _opener
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def sign_in_for_evals() -> str:
    """Create the eval account on first run, sign in on every run after."""
    c, _ = api("/api/me")
    if c == 0:
        return "server unreachable"
    c, d = api("/api/auth/login", "POST",
               {"username": EVAL_USER, "password": EVAL_PASS})
    if c == 200:
        return "signed in"
    c, d = api("/api/auth/register", "POST",
               {"username": EVAL_USER, "password": EVAL_PASS})
    if c == 200:
        return "registered" + (" (adopted local book)" if d.get("adopted_local_data") else "")
    c2, d2 = api("/api/me")
    if d2.get("auth_enabled") is False:
        return "auth disabled - running as the implicit local user"
    return f"could not sign in: {c} {d.get('detail')}"


# ───────────────────────── data plane ─────────────────────────
def suite_data_plane():
    out = []

    def case(name, fn, why):
        t0 = time.time()
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"
        out.append({"id": name, "pass": bool(ok), "detail": str(detail)[:150],
                    "ms": int((time.time() - t0) * 1000), "why": why})

    def quotes_batch():
        syms = "NVDA,AAPL,MSFT,AMD,PLTR,KO,AMZN,GOOGL"
        c, d = api(f"/api/quotes?symbols={syms}")
        n, req = len(d.get("quotes", [])), d.get("http_requests_used")
        return (c == 200 and n == 8 and req == 1), f"{n} quotes in {req} upstream request(s)"
    case("quotes_batched", quotes_batch,
         "8 tickers must cost ONE upstream call, not 8")

    def bars():
        c, d = api("/api/bars/NVDA?period=1mo&interval=1d")
        b = d.get("bars", [])
        shaped = all(k in b[0] for k in "tohlcv") if b else False
        return (c == 200 and len(b) > 15 and shaped), f"{len(b)} bars, OHLCV shape {shaped}"
    case("bars_shape", bars, "chart data must be well-formed OHLCV")

    def financials_period():
        c, d = api("/api/financials/NVDA")
        qs = d.get("quarters", [])
        # the trap: EDGAR returns 3-month AND cumulative rows under one tag
        sane = all(1e9 < q.get("revenue", 0) < 2e11 for q in qs if q.get("revenue"))
        return (c == 200 and len(qs) >= 4 and sane), f"{len(qs)} quarters, all single-quarter: {sane}"
    case("edgar_single_quarter", financials_period,
         "REGRESSION: cumulative 6-month rollups must be filtered out")

    def financials_forward():
        c, d = api("/api/financials/NVDA")
        u, tr = d.get("upcoming") or {}, d.get("track_record") or []
        return (bool(u.get("date")) and len(tr) >= 3), \
               f"next {u.get('date')}, eps est {u.get('eps_estimate')}, {len(tr)} past reports"
    case("financials_outlook", financials_forward,
         "financials must carry the next report and the beat/miss record")

    for ep, key, why in [
        ("/api/overview/NVDA", "market_cap", "overview stats"),
        ("/api/news/NVDA", "items", "news with relevance flags"),
        ("/api/analysts/NVDA", "distribution", "REAL analyst buckets, not modelled"),
        ("/api/events/NVDA", "surprise_history", "earnings calendar + surprises"),
        ("/api/indices", "indices", "broad market + fear & greed"),
        ("/api/compare?symbols=NVDA,AMD,AVGO", "correlations", "multi-ticker basket"),
        ("/api/related/NVDA", "read_across", "adjacent cohort + transmission"),
        ("/api/portfolio/analytics", "concentration", "risk profile, no LLM"),
        ("/api/search?q=coca", "results", "symbol lookup"),
    ]:
        def mk(ep=ep, key=key):
            def f():
                c, d = api(ep)
                v = d.get(key)
                return (c == 200 and v not in (None, [], {})), f"{key}={str(v)[:60]}"
            return f
        case(ep.split("?")[0].replace("/api/", ""), mk(), why)

    def fng():
        c, d = api("/api/indices")
        f = next((i for i in d.get("indices", []) if i.get("kind") == "sentiment"), None)
        ok = f and 0 <= f.get("level", -1) <= 100 and f.get("history")
        return ok, f"score {f.get('level') if f else None} ({f.get('rating') if f else '—'})"
    case("fear_greed", fng, "CNN F&G must be present and in range")

    def no_russell():
        c, d = api("/api/indices")
        labels = [i["label"] for i in d.get("indices", [])]
        return ("Russell 2000" not in labels and "S&P 500" in labels), str(labels)
    case("indices_set", no_russell, "big three + risk gauges, Russell removed")

    return out


# ───────────────────────── tools ─────────────────────────
async def suite_tools():
    sys.path.insert(0, "backend")
    from app import db, store
    from app.tools import TOOLS, DOMAIN_DESC, domain_tools
    from app.models import ToolResult, ToolFailure
    from app.providers import yahoo

    # Say who we are. The portfolio tools read the current user from a
    # contextvar whose default is now GUEST (which owns nothing), so a suite
    # that stays anonymous would test them against an empty book and quietly
    # stop checking they compute anything.
    store.set_current_user(db.LOCAL_USER_ID)

    out = []
    await yahoo.bars("SPY", "5d")          # warm the session

    async def run(tool, ticker="NVDA", **kw):
        t0 = time.time()
        try:
            r = await TOOLS[tool].fn(ticker, **kw)
        except Exception as e:
            return None, f"RAISED {type(e).__name__}: {e}", int((time.time()-t0)*1000)
        kind = "data" if isinstance(r, ToolResult) else \
               ("empty" if getattr(r, "kind", "") == "empty" else "error")
        return r, kind, int((time.time() - t0) * 1000)

    # every tool must return a typed result, never raise
    for name, t in TOOLS.items():
        tick = "NVDA"
        kw = {}
        if t.domain == "portfolio":
            tick = ""
        if name in ("event_study", "read_across", "correlation"):
            kw = {"other": "AMD"}
        r, kind, ms = await run(name, tick, **kw)
        want = ("data",) if t.domain == "portfolio" else ("data", "empty")
        out.append({"id": f"tool:{name}", "pass": kind in want,
                    "detail": f"{kind} ({t.domain}{', derived' if t.derived else ''})",
                    "ms": ms, "why": "must return typed data or a typed empty, never raise"})

    # derived indicators must be sane, not just present
    r, _, _ = await run("rsi_momentum")
    v = getattr(r, "data", {}).get("rsi14")
    out.append({"id": "rsi_in_range", "pass": v is not None and 0 <= v <= 100,
                "detail": f"RSI {v}", "ms": 0, "why": "RSI is bounded 0-100 by definition"})

    r, _, _ = await run("volatility")
    b = getattr(r, "data", {}).get("beta_vs_spy")
    out.append({"id": "beta_plausible", "pass": b is not None and -3 < b < 5,
                "detail": f"beta {b}", "ms": 0, "why": "a beta outside -3..5 means a maths error"})

    # empty is information, not failure
    r, kind, _ = await run("dividend_economics", "TSLA")
    out.append({"id": "empty_is_not_error", "pass": kind == "empty",
                "detail": f"TSLA dividends -> {kind}", "ms": 0,
                "why": "'pays no dividend' must be typed empty, never an error"})

    # every domain has tools (the portfolio-domain bug)
    for d in DOMAIN_DESC:
        n = len(domain_tools(d))
        out.append({"id": f"domain_populated:{d}", "pass": n > 0, "detail": f"{n} tools",
                    "ms": 0, "why": "REGRESSION: a declared domain with zero tools silently no-ops"})
    return out


# ───────────────────────── regressions ─────────────────────────
async def suite_regressions():
    sys.path.insert(0, "backend")
    from app.routes.data import _ticker_signals, BIG_MOVE_PCT
    from app.tools import relations
    from app.providers import yahoo
    from app.graph.build import grounding_check
    from app.models import AgentRun, DomainFinding, ToolResult, Provenance

    out = []

    def add(id_, ok, detail, why):
        out.append({"id": id_, "pass": bool(ok), "detail": str(detail)[:150],
                    "ms": 0, "why": why})

    await yahoo.bars("SPY", "5d")
    q = await yahoo.quote("AMD") or {"regularMarketPrice": 600.0,
        "shortName": "Advanced Micro Devices, Inc.",
        "fiftyTwoWeekHigh": 700.0, "fiftyTwoWeekLow": 190.0}

    # threshold fires on absolute move, regardless of volatility
    fired = []
    for chg in (-7.4, -5.0, -3.1, 6.8):
        sigs = await _ticker_signals("AMD", {**q, "regularMarketChangePercent": chg}, set())
        fired.append((chg, any(s["kind"] == "threshold" for s in sigs)))
    add("threshold_5pct", fired == [(-7.4, True), (-5.0, True), (-3.1, False), (6.8, True)],
        str(fired), f"any move beyond +/-{BIG_MOVE_PCT}% must always flag")

    # a threshold move must carry its reason
    sigs = await _ticker_signals("AMD", {**q, "regularMarketChangePercent": -6.4}, set())
    t = next((s for s in sigs if s["kind"] == "threshold"), None)
    w = (t or {}).get("why") or {}
    add("threshold_has_reason", bool(w.get("read") or w.get("headlines") or w.get("earnings")),
        f"read={str(w.get('read'))[:60]}", "a big move must explain itself from data")

    # one move never produces two duplicate signals
    kinds = [s["kind"] for s in sigs]
    add("no_duplicate_move_signal", not ("threshold" in kinds and "move" in kinds),
        str(kinds), "REGRESSION: threshold and sigma signals must not both fire")

    # event study: dedupe + correct reaction day + baseline present
    r = await relations.event_study("APLD", other="IREN")
    d = getattr(r, "data", {}) or {}
    dates = [e["date"] for e in d.get("events", [])]
    add("event_study_dedupe", len(dates) == len(set(dates)),
        f"{len(dates)} events, {len(set(dates))} unique",
        "REGRESSION: earnings_dates repeats rows per announcement")
    add("event_study_baseline", d.get("baseline_same_direction_pct") is not None
        and d.get("binomial_p_one_sided") is not None,
        f"baseline {d.get('baseline_same_direction_pct')}%, p={d.get('binomial_p_one_sided')}",
        "a hit rate without its baseline and p-value is meaningless")

    # peer discovery is dynamic, not a lookup table
    peers = {}
    for s in ("IREN", "XOM", "LLY"):
        peers[s] = await yahoo.peers(s)
    add("peers_dynamic", all(len(v) >= 3 for v in peers.values()),
        json.dumps(peers)[:120],
        "REGRESSION: adjacent names must be fetched per ticker, never hard-coded")

    # sector proxy resolves for every ticker and rejects leveraged products
    res = {}
    for s in ("NVDA", "KO", "XOM"):
        p = await relations.resolve_proxy(s)
        res[s] = (p or {}).get("etf") or "+".join((p or {}).get("cohort", []) or [])
    add("sector_proxy_dynamic", all(res.values()), json.dumps(res)[:120],
        "REGRESSION: proxy discovered + measured, no sector->ETF table")

    # presentation layer: the model must never see raw precision or raw magnitudes
    from app.graph.present import present
    q = await yahoo.quote("NVDA") or {}
    shown = present(q)
    raw_precision = any(isinstance(v, float) and len(str(v).split(".")[-1]) > 2
                        for v in shown.values())
    raw_magnitude = any(isinstance(v, (int, float)) and not isinstance(v, bool)
                        and abs(v) >= 1e6 for v in shown.values())
    add("present_rounds", not raw_precision and not raw_magnitude,
        f"shown={ {k: v for k, v in list(shown.items())[:4]} }",
        "REGRESSION: raw precision/magnitude in the prompt causes number soup")

    # rounding must not break the grounding check
    from app.tools import TOOLS as _T
    ev = []
    for t in ("quote", "range_52w"):
        r = await _T[t].fn("NVDA")
        if isinstance(r, ToolResult):
            ev.append(r)
    def ground(ans):
        return grounding_check(AgentRun(question="q", answer=ans, findings=[
            DomainFinding(domain="market", ticker="NVDA", narrative="",
                          evidence=ev)])).grounded
    pres = present(ev[0].data)
    quoted = [v for v in pres.values() if isinstance(v, (int, float))
              and not isinstance(v, bool) and abs(v) > 1.5][:2]
    add("present_stays_grounded", all(ground(f"The figure is {v}.") for v in quoted),
        f"quoted {quoted}", "a figure shown to the model must verify against evidence")
    add("invented_still_fails", not ground("Revenue was $77.7B."), "77.7 rejected",
        "rounding must not make the grounding check permissive")

    # the in-loop gate must block a fabricated figure, and must agree with the report
    from app.graph.build import unverified_figures, grounding_check as _gc
    _ev = [ToolResult(tool="valuation_multiples", ticker="AMD",
                      prov=Provenance(source="x"),
                      data={"pe_trailing": 156.28, "pe_forward": 39.51})]
    _F = [DomainFinding(domain="fundamentals", ticker="AMD", narrative="n", evidence=_ev)]
    FAKE = "AMD trades at a P/E of 156.28 and a net margin of 88.8%."
    gate = unverified_figures(FAKE, _F)
    rep = _gc(AgentRun(question="q", answer=FAKE, findings=_F)).ungrounded_numbers
    add("gate_catches_fabrication", gate == [88.8], f"gate flagged {gate}",
        "a figure absent from evidence must be caught BEFORE the answer ships")
    add("gate_matches_report", gate == rep, f"gate {gate} vs report {rep}",
        "REGRESSION: the blocking check and the reported check must never disagree")
    clean_ans = "AMD trades at a P/E of 156.28, against a forward 39.51."
    add("gate_passes_clean", unverified_figures(clean_ans, _F) == [], "no flags",
        "a well-grounded answer must not trigger a repair call")

    # readability must ignore digits that NAME rather than measure
    from evals.rubric import readability as _read
    good = _read("NVDA is 2.4% off its 52-week high after rising 1.1%. It got there on "
                 "below-average volume - 0.87x its 20-day norm - so the move lacks conviction.")
    soup = _read("AMD 157.07 39.51 1.01e12 15.58 NVDA 29.22 14.71 63.66 per the data.")
    add("readability_ignores_names", good["score"] >= 5 and soup["score"] <= 2,
        f"good={good['score']}/5 soup={soup['score']}/5",
        "REGRESSION: '52-week' counted as a figure, penalising correct prose")

    # a failed router must SAY it fell back, not answer a different question
    import app.graph.build as _B
    import app.llm as _llm

    async def _boom(*a, **k):
        raise RuntimeError("429 rate limit")

    orig = _llm.call
    _llm.call = _boom
    try:
        run = await _B.ask("When does NVDA report next and what is expected?")
    finally:
        _llm.call = orig
    add("degraded_route_is_declared", bool(run.degraded), (run.degraded or "")[:90],
        "REGRESSION: a rate-limited router fell back to price-only and the "
        "answer looked complete - silently answering a different question")
    step = next((s_ for s_ in run.steps if s_.node == "route"), None)
    add("degraded_route_shows_in_trace",
        bool(step and "UNAVAILABLE" in (step.detail or "")), (step.detail if step else "")[:80],
        "the run trace must show where it degraded")
    add("degraded_route_keeps_the_ticker", run.tickers == ["NVDA"], str(run.tickers),
        "REGRESSION: the fallback uppercased the question, so 'When does NVDA "
        "report' matched WHEN - a real penny stock - and answered about that")

    from app.graph.build import _fallback_ticker as _ft
    cases = [("When does NVDA report next?", "NVDA"), ("How is AMD doing?", "AMD"),
             ("What about the AI trade and US rates?", None),
             ("Should I worry about my portfolio?", None)]
    wrong = [(q, _ft(q)) for q, want in cases if _ft(q) != want]
    add("fallback_ticker_extraction", not wrong, wrong or "all 4 correct",
        "capitalised English words are not tickers; CAPS in the user's own text is the signal")

    # grounding checker: the false-positive classes
    def mk(ans, data):
        return grounding_check(AgentRun(question="t", answer=ans, findings=[
            DomainFinding(domain="d", ticker="X", narrative="", evidence=[
                ToolResult(tool="t", ticker="X", data=data, prov=Provenance(source="s"))])]))
    checks = [
        ("dates", "net income was $2,297,000,000 for the quarter ending June 27, 2026",
         {"ni": 2297000000}, True),
        ("index names", "a 32.74% excess return over the S&P 500", {"x": 32.74}, True),
        ("windows", "the US 10-year yield fell to 5.24% near its 52-week high",
         {"y": 5.24}, True),
        ("unit scaling", "net income of $2.297 billion", {"ni": 2297000000}, True),
        ("real fabrication", "a margin of 88.8%", {"pe": 157.07}, False),
    ]
    for name, ans, data, want in checks:
        got = mk(ans, data).grounded
        add(f"grounding:{name}", got == want, f"grounded={got}, expected={want}",
            "REGRESSION: the checker flagged dates/index names/units as hallucinations")
    return out


CLAIM_PROBE = r"""
import json, sys
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app import store, db
c = TestClient(app)
# Act as the implicit pre-login user explicitly. The contextvar's default is
# GUEST now (it used to be this user), and a guest cannot save - which is the
# point of the change.
store.set_current_user(db.LOCAL_USER_ID)
d = store.load()
d["watchlist"].append("TSM")
d["portfolios"].append({"id": db.new_id(), "name": "Roth IRA", "kind": "roth ira",
                        "positions": [{"ticker": "VTI", "qty": 60, "basis": 290.0}]})
store.save(d)                                   # a touched pre-login book
c.post("/api/auth/register", json={"username": "claimer", "password": "correct-horse-9"})
before = [a["name"] for a in c.get("/api/portfolios").json()["accounts"]]
offered = c.get("/api/me").json()["legacy_book"]
r = c.post("/api/auth/claim-legacy", json={})
after = [(a["name"], a["holdings"]) for a in c.get("/api/portfolios").json()["accounts"]]
print("@@" + json.dumps({
    "before": before, "offered": bool(offered), "claim": r.status_code,
    "after": after, "wl": c.get("/api/watchlist").json()["watchlist"],
    "still_offered": c.get("/api/me").json()["legacy_book"],
    "second": c.post("/api/auth/claim-legacy", json={}).status_code}))
"""


def suite_claim():
    """The legacy-book claim, in a subprocess against a throwaway database.

    It has to run somewhere disposable: this is the one path that MOVES a
    portfolio between users, and an earlier version of it quietly moved the
    real one onto the eval account.
    """
    import os, subprocess, tempfile

    out = []

    def add(id_, ok, detail, why):
        out.append({"id": id_, "pass": bool(ok), "detail": str(detail)[:150],
                    "ms": 0, "why": why})

    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "DB_PATH": os.path.join(tmp, "t.db"),
               "STORE_PATH": os.path.join(tmp, "none.json"), "AUTH_ENABLED": "true"}
        r = subprocess.run([sys.executable, "-c", CLAIM_PROBE], env=env,
                           capture_output=True, text=True, timeout=180,
                           cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        line = next((l for l in r.stdout.splitlines() if l.startswith("@@")), None)
        if not line:
            add("claim_probe_ran", False, (r.stderr or r.stdout)[-140:],
                "the claim probe must start at all")
            return out
        d = json.loads(line[2:])

    add("claim_probe_ran", True, "subprocess on a temp database", "isolation")
    add("claim_offered_when_book_exists", d["offered"] and d["before"] == ["Brokerage"],
        f"offered={d['offered']}, fresh book {d['before']}",
        "a touched pre-login book must be offered, not taken")
    names = [n for n, _ in d["after"]]
    add("claim_moves_the_book", d["claim"] == 200 and set(names) == {"Brokerage", "Roth IRA"},
        f"{d['claim']} -> {d['after']}",
        "claiming must bring every account across")
    add("claim_survives_name_collision", ("Brokerage", 3) in [tuple(x) for x in d["after"]],
        str(d["after"]),
        "REGRESSION: the legacy 'Brokerage' collided with the new account's demo one")
    add("claim_merges_watchlist", "TSM" in d["wl"] and "NVDA" in d["wl"], str(d["wl"]),
        "watchlist is keyed (user,ticker) - it merges rather than moves")
    add("claim_is_once_only", d["still_offered"] is None and d["second"] == 409,
        f"still offered={d['still_offered']}, second claim {d['second']}",
        "a claimed book must not stay on offer to the next account")
    return out


def _subprocess_suite(script: str, fallback_id: str, why: str, args=()):
    """Run a probe script on a throwaway database and parse its @@ line."""
    import os, subprocess, tempfile

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "DB_PATH": os.path.join(tmp, "t.db"),
               "STORE_PATH": os.path.join(tmp, "none.json"), "AUTH_ENABLED": "true"}
        r = subprocess.run([sys.executable, script, *args], env=env, cwd=root,
                           capture_output=True, text=True, timeout=900)
    line = next((l for l in r.stdout.splitlines() if l.startswith("@@")), None)
    if not line:
        return [{"id": fallback_id, "pass": False, "ms": 0,
                 "detail": (r.stderr or r.stdout)[-140:], "why": why}]
    return json.loads(line[2:])


def suite_sweep(agent: bool = False):
    """Every route, end to end, on a throwaway database (evals/sweep.py)."""
    return _subprocess_suite("evals/sweep.py", "sweep_ran",
                             "the whole-app sweep must run at all",
                             ("--agent",) if agent else ())


def suite_tenancy(agent: bool = False):
    """Can one account reach another's book? (evals/tenancy_probe.py), and can
    the AGENT be made to (evals/agent_tenancy_probe.py)."""
    rows = _subprocess_suite("evals/tenancy_probe.py", "tenancy_probe_ran",
                             "cross-account isolation must be tested, not assumed")
    rows += _subprocess_suite("evals/agent_tenancy_probe.py", "agent_tenancy_probe_ran",
                              "the agent plane reads the book through a contextvar",
                              ("--agent",) if agent else ())
    return rows


def suite_login():
    """The end-to-end sign-in sweep (evals/login_probe.py), in a subprocess on
    a throwaway database so it can register, lock out and delete freely."""
    import os, subprocess, tempfile

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "DB_PATH": os.path.join(tmp, "t.db"),
               "STORE_PATH": os.path.join(tmp, "none.json"), "AUTH_ENABLED": "true"}
        r = subprocess.run([sys.executable, "evals/login_probe.py"], env=env, cwd=root,
                           capture_output=True, text=True, timeout=300)
    line = next((l for l in r.stdout.splitlines() if l.startswith("@@")), None)
    if not line:
        return [{"id": "login_probe_ran", "pass": False, "ms": 0,
                 "detail": (r.stderr or r.stdout)[-140:],
                 "why": "the end-to-end login sweep must run at all"}]
    return json.loads(line[2:])


# ───────────────────────── auth ─────────────────────────
def suite_auth():
    """Username/password sign-in. These run against the live server and assert
    the properties that matter when the thing being guarded is someone's cost
    basis: no enumeration, no plaintext, no unthrottled guessing, no leakage
    between a guest and an account."""
    from app import passwords

    out = []

    def add(id_, ok, detail, why):
        out.append({"id": id_, "pass": bool(ok), "detail": str(detail)[:150],
                    "ms": 0, "why": why})

    probe = "probe-" + secrets.token_hex(4)
    good = "probe-passphrase-" + secrets.token_hex(4)

    # ── hashing ──
    h = passwords.hash_password(good)
    add("hash_not_plaintext", good not in h and len(h) > 40, f"{h[:28]}...",
        "the stored string must never contain the password")
    add("hash_salted", passwords.hash_password(good) != passwords.hash_password(good),
        "two hashes of one password differ",
        "an unsalted hash makes a rainbow table work against every user at once")
    add("hash_memory_hard", passwords.BACKEND in ("argon2id", "scrypt"),
        passwords.BACKEND, "a fast hash (md5/sha) is brute-forceable on a GPU")
    add("verify_roundtrip",
        passwords.verify_password(good, h) and not passwords.verify_password(good + "x", h),
        "accepts the right one, rejects the wrong one", "the basic contract")
    add("verify_survives_garbage", passwords.verify_password("x", "not-a-hash") is False,
        "returns False instead of raising",
        "a corrupt row must fail closed, not 500 and leak a stack trace")

    weak = [("short", "Use at least"), ("password123", "common"), ("9081726354", "Digits")]
    bad = [p for p, frag in weak if frag not in (passwords.strength_problem(p) or "")]
    add("rejects_weak_passwords", not bad, f"rejected all of {[p for p,_ in weak]}",
        "length and the common list are the two checks that actually matter")

    # ── registration ──
    c, d = api("/api/auth/register", "POST", {"username": probe, "password": "short"},
               anon=True)
    add("register_rejects_weak", c == 400, f"{c} {d.get('detail')}",
        "the strength rule must be enforced server-side, not just in the form")

    c, d = api("/api/auth/register", "POST", {"username": "a b!", "password": good},
               anon=True)
    add("register_rejects_bad_username", c == 400, f"{c} {d.get('detail')}",
        "usernames go into URLs and logs; keep them boring")

    # a throwaway account, with its own cookie jar so it cannot disturb the
    # eval account the rest of the suite runs as
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def as_probe(path, method="GET", body=None):
        req = urllib.request.Request(BASE + path, method=method,
            data=json.dumps(body).encode() if body else None,
            headers={"Content-Type": "application/json"})
        try:
            with op.open(req, timeout=60) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.load(e)
            except Exception:
                return e.code, {}

    c, d = as_probe("/api/auth/register", "POST", {"username": probe, "password": good})
    add("register_succeeds", c == 200 and d.get("signed_in"), f"{c} {d.get('username')}",
        "the happy path")
    add("register_returns_no_password", "password" not in json.dumps(d).lower(),
        "response carries no password field",
        "the password must not come back in the response body")

    c, d = api("/api/auth/register", "POST",
               {"username": probe.upper(), "password": good}, anon=True)
    add("username_case_insensitive_unique", c == 409, f"{c} {d.get('detail')}",
        "'Dave' and 'dave' must not become two accounts")

    c, d = as_probe("/api/me")
    add("session_cookie_works", d.get("username", "").lower() == probe and d.get("can_save"),
        f"{d.get('username')} can_save={d.get('can_save')}",
        "the cookie set at registration must identify the user on later calls")

    # ── no enumeration ──
    c1, d1 = api("/api/auth/login", "POST",
                 {"username": probe, "password": "definitely-wrong-1"}, anon=True)
    c2, d2 = api("/api/auth/login", "POST",
                 {"username": "ghost-" + secrets.token_hex(4),
                  "password": "definitely-wrong-1"}, anon=True)
    add("no_user_enumeration", (c1, d1.get("detail")) == (c2, d2.get("detail")),
        f"real user: {c1} / unknown: {c2}, same text: {d1.get('detail')==d2.get('detail')}",
        "if the two differ, the login form becomes a list of who banks here")

    # ── throttling ──
    # The loop is bounded independently of MAX_FAILS. Deriving the count from
    # the setting under test means raising that setting makes the TEST do the
    # work - the negative control set it to 1e9 and the suite sat there
    # inserting rows. A sane limit is a small number; anything past CAP is a
    # failure of the limit, not a reason to keep counting.
    CAP = 25
    key = "u:throttle-" + secrets.token_hex(3)
    passwords.clear_failures(key)
    before = passwords.locked_for(key)
    for _ in range(CAP):
        passwords.record_failure(key)
    after = passwords.locked_for(key)
    passwords.clear_failures(key)
    add("throttle_locks_out", before == 0 and after > 0,
        f"{CAP} failures -> locked for {after}s (limit {passwords.MAX_FAILS})",
        "unthrottled login is an offline password list run online")

    ipkey = "ip:203.0.113." + str(secrets.randbelow(250))
    passwords.clear_failures(ipkey)
    for _ in range(min(passwords.MAX_FAILS, CAP)):
        passwords.record_failure(ipkey)
    mid = passwords.locked_for(ipkey)
    for _ in range(min(passwords.MAX_FAILS_IP, 100) - min(passwords.MAX_FAILS, CAP)):
        passwords.record_failure(ipkey)
    end = passwords.locked_for(ipkey)
    passwords.clear_failures(ipkey)
    add("ip_budget_is_looser", mid == 0 and end > 0,
        f"{passwords.MAX_FAILS} fails -> {mid}s, {passwords.MAX_FAILS_IP} -> {end}s",
        "one shared office address must not lock out on five typos")
    add("throttle_clears_on_success", passwords.locked_for(key) == 0, "cleared",
        "a correct password must not leave the account locked")

    # ── guest isolation ──
    c, d = api("/api/watchlist", "POST", {"ticker": "NVDA"}, anon=True)
    add("guest_cannot_write", c == 401, f"{c} {d.get('detail')}",
        "a signed-out visitor must not be able to write into anyone's book")
    c, d = api("/api/watchlist", anon=True)
    add("guest_sees_empty_book", c == 200 and d.get("watchlist") == [],
        f"{c} {d.get('watchlist')}",
        "REGRESSION: a guest must never be served the local user's watchlist")
    c, d = api("/api/quotes?symbols=NVDA", anon=True)
    add("guest_keeps_market_data", c == 200 and len(d.get("quotes", [])) == 1,
        f"{c} {len(d.get('quotes', []))} quote(s)",
        "guests lose their book, not the product")

    # ── the pre-login book is not grabbable ──
    # This is the bug this suite exists to prevent: registration used to hand
    # the legacy book to whoever signed up first, and this harness took it.
    c, d = as_probe("/api/portfolios")
    names = {a["name"] for a in d.get("accounts", [])}
    add("register_does_not_adopt", c == 200 and names == {"Brokerage"},
        f"fresh account sees {sorted(names)}",
        "REGRESSION: a new account must not inherit the pre-login book by itself")

    ids = {a["id"] for a in d.get("accounts", [])}
    add("seeded_ids_are_per_user", c == 200 and "default" not in ids, f"ids {sorted(ids)}",
        "REGRESSION: a fixed seed id is a global PK collision with user one")

    c, d = api("/api/auth/claim-legacy", "POST", {}, anon=True)
    add("claim_requires_sign_in", c == 401, f"{c} {d.get('detail')}",
        "claiming a book is not something a signed-out caller may do")

    # ── password change ──
    newpw = "probe-rotated-" + secrets.token_hex(4)
    c, d = as_probe("/api/auth/password", "POST", {"current": "not-it", "new": newpw})
    add("change_needs_current_password", c == 401, f"{c} {d.get('detail')}",
        "a borrowed session must not be able to lock the owner out")
    c, d = as_probe("/api/auth/password", "POST", {"current": good, "new": "short"})
    add("change_enforces_strength", c == 400, f"{c} {d.get('detail')}",
        "the strength rule applies to rotations too")
    c, d = as_probe("/api/auth/password", "POST", {"current": good, "new": newpw})
    add("change_succeeds", c == 200 and d.get("ok"), f"{c} {d}", "the happy path")
    c1, _ = api("/api/auth/login", "POST", {"username": probe, "password": good}, anon=True)
    c2, _ = api("/api/auth/login", "POST", {"username": probe, "password": newpw}, anon=True)
    add("change_rotates_the_secret", c1 == 401 and c2 == 200,
        f"old password {c1}, new password {c2}",
        "the old password must stop working the moment it is replaced")
    good = newpw

    # ── deletion, which also keeps this suite from littering the database ──
    c, _ = as_probe(f"/api/auth/account?confirm=wrong", "DELETE")
    add("delete_needs_confirmation", c == 400, str(c),
        "a stray DELETE must not be able to erase a portfolio")
    c, _ = as_probe(f"/api/auth/account?confirm={probe}", "DELETE")
    c2, d2 = api("/api/auth/login", "POST", {"username": probe, "password": good},
                 anon=True)
    add("delete_removes_account", c == 204 and c2 == 401, f"delete {c}, login after {c2}",
        "deleting an account must actually remove it, not just sign it out")

    return out
