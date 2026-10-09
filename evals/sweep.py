"""Whole-app sweep: every route, every view-critical shape, in one process.

Runs against a throwaway database (set DB_PATH) so it can create, mutate and
delete without touching anyone's book. The agent routes are included but only
exercised for reachability unless --agent is passed, because they spend tokens.

    DB_PATH=/tmp/t.db python evals/sweep.py [--agent]
"""
from __future__ import annotations
import json, os, sys, time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))

from fastapi.testclient import TestClient              # noqa: E402
from backend.app.main import app                       # noqa: E402

R: list[dict] = []
SEEN: set[str] = set()


def chk(route, name, cond, detail="", why=""):
    SEEN.add(route)
    R.append({"id": name, "pass": bool(cond), "detail": str(detail)[:120],
              "ms": 0, "why": why, "route": route})
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<40} {str(detail)[:66]}")


def head(t):
    print(f"\n── {t} " + "─" * max(0, 58 - len(t)))


def main(run_agent: bool) -> int:
    c = TestClient(app)

    head("shell + health")
    r = c.get("/")
    chk("/", "index_served", r.status_code == 200 and "<title>" in r.text,
        f"{len(r.text)} bytes", "the SPA shell must be served at the root")
    chk("/", "index_no_store", "no-store" in r.headers.get("cache-control", ""),
        r.headers.get("cache-control"), "a stale shell is the #1 phantom bug")
    stamp = c.get("/build").json()["build"]
    chk("/", "asset_stamp_matches_build",
        f"app.js?v={stamp}" in r.text and "__BUILD__" not in r.text,
        f"app.js?v={stamp}",
        "a hardcoded ?v= goes stale the moment anyone forgets to bump it")
    r = c.get("/build")
    chk("/build", "build_stamp", r.status_code == 200 and r.json().get("build"),
        r.json(), "the footer stamp proves which build you are looking at")
    print("\n── no API response may be CDN-cached ──")
    # Vercel caches rewrites to external origins BY DEFAULT and honours
    # upstream cache-control. Nothing here sent any, so /api/me and
    # /api/portfolio could have been cached at the edge and served to a
    # different visitor - the cross-user leak the tenancy probe guards, one
    # layer up where no application test would have seen it.
    for ep in ("/api/me", "/api/portfolio", "/api/watchlist",
               "/api/quotes?symbols=NVDA", "/api/health"):
        h = c.get(ep).headers
        cc = (h.get("cache-control") or "").lower()
        chk(ep.split("?")[0], f"no_store{ep.split('?')[0].replace('/', '_')}",
            "no-store" in cc and "private" in cc, cc or "MISSING",
            "a per-user response cached by a CDN is served to the wrong person")
    chk("/api/me", "varies_on_cookie",
        "cookie" in (c.get("/api/me").headers.get("vary") or "").lower(),
        c.get("/api/me").headers.get("vary"),
        "the response depends on the session cookie; any cache must know that")

    print("\n── CORS ──")
    import backend.app.main as _M
    evil = "https://evil.example"
    r = c.get("/api/quotes?symbols=NVDA", headers={"Origin": evil})
    acao = r.headers.get("access-control-allow-origin")
    chk("/api/quotes", "cors_rejects_unknown_origin", acao not in ("*", evil),
        f"allow-origin: {acao!r} for Origin {evil}",
        "REGRESSION: allow_origins=['*'] let any site read every response")
    own = sorted(_M.CORS_ORIGINS)[0]
    r = c.get("/api/quotes?symbols=NVDA", headers={"Origin": own})
    chk("/api/quotes", "cors_allows_own_origin",
        r.headers.get("access-control-allow-origin") == own,
        f"{own} -> {r.headers.get('access-control-allow-origin')!r}", "")
    chk("/api/quotes", "cors_never_allows_credentials",
        r.headers.get("access-control-allow-credentials") != "true",
        r.headers.get("access-control-allow-credentials"),
        "a cross-origin caller must never be able to ride the session cookie")
    pre = c.options("/api/watchlist", headers={"Origin": evil,
                                               "Access-Control-Request-Method": "POST"})
    chk("/api/watchlist", "cors_preflight_denies_unknown_origin",
        pre.headers.get("access-control-allow-origin") not in ("*", evil),
        f"preflight -> {pre.headers.get('access-control-allow-origin')!r}", "")

    h = c.get("/api/health").json()
    chk("/api/health", "health", "llm_configured" in h and h.get("tools", 0) >= 40,
        f"llm={h.get('llm_configured')} model={h.get('model')} "
        f"tools={h.get('tools')} db={h.get('db')}",
        "says whether the agent plane is usable, and which database is live")
    chk("/api/health", "health_names_db", h.get("db") in ("sqlite", "turso"), h.get("db"),
        "DATABASE.md tells people to check this after switching backends")

    head("market data — no auth needed")
    r = c.get("/api/quotes?symbols=NVDA,AAPL,MSFT,AMD,PLTR,KO,AMZN,GOOGL")
    d = r.json()
    chk("/api/quotes", "quotes_batched",
        len(d.get("quotes", [])) == 8 and d.get("http_requests_used") == 1,
        f"{len(d.get('quotes', []))} quotes / {d.get('http_requests_used')} upstream call(s)",
        "8 tickers must cost ONE upstream request")
    chk("/api/quotes", "quotes_priced",
        all(q.get("price") and q.get("name") for q in d.get("quotes", [])),
        f"{sum(1 for q in d.get('quotes', []) if q.get('price'))}/8 priced and named",
        "a null price renders as an em dash")

    b = c.get("/api/bars/NVDA?period=1mo&interval=1d").json().get("bars", [])
    chk("/api/bars/{symbol}", "bars_ohlcv",
        len(b) > 15 and all(k in b[0] for k in "tohlcv"), f"{len(b)} bars",
        "the candlestick chart needs well-formed OHLCV")
    intraday = c.get("/api/bars/NVDA?period=1d&interval=5m").json().get("bars", [])
    chk("/api/bars/{symbol}", "bars_intraday", len(intraday) > 10, f"{len(intraday)} 5m bars",
        "the 1D timeframe uses a different interval path")

    s = c.get("/api/sparklines?symbols=NVDA,AAPL").json().get("sparklines", {})
    chk("/api/sparklines", "sparklines", len(s) == 2 and len(list(s.values())[0]) > 5,
        f"{ {k: len(v) for k, v in s.items()} }", "the 30-day column on the watchlist")

    o = c.get("/api/overview/NVDA").json()
    chk("/api/overview/{symbol}", "overview",
        o.get("market_cap") and o.get("pe") and o.get("net_margin") is not None,
        f"cap={o.get('market_cap')} pe={o.get('pe')} margin={o.get('net_margin')}",
        "the Overview tab: valuation, margins, balance sheet")
    chk("/api/overview/{symbol}", "overview_has_balance_sheet",
        o.get("debt_to_equity") is not None and o.get("fcf") is not None,
        f"d/e={o.get('debt_to_equity')} fcf={o.get('fcf')}",
        "the future-outlook ask needs debt ratios and cash flow")

    f = c.get("/api/financials/NVDA").json().get("quarters", [])
    sane = all(1e9 < q["revenue"] < 2e11 for q in f if q.get("revenue"))
    chk("/api/financials/{symbol}", "financials", len(f) >= 4 and sane,
        f"{len(f)} quarters, single-quarter only: {sane}",
        "EDGAR mixes 3-month and cumulative rows under one tag")

    nw = c.get("/api/news/NVDA").json()
    n = nw.get("items", [])
    chk("/api/news/{symbol}", "news", len(n) > 0 and n[0].get("title") and n[0].get("url"),
        f"{len(n)} items, {nw.get('relevant')} flagged relevant",
        "yfinance news went empty upstream once; there is a fallback")
    chk("/api/news/{symbol}", "news_relevance_flagged",
        all("mentions_issuer" in x for x in n), "",
        "the UI dims items that only mention the issuer in passing")

    a = c.get("/api/analysts/NVDA").json()
    dist = a.get("distribution") or []
    chk("/api/analysts/{symbol}", "analysts", sum(x["n"] for x in dist) > 0,
        {x["label"]: x["n"] for x in dist},
        "REGRESSION: these were once fitted from a curve, not counted")
    tg = a.get("targets") or {}
    chk("/api/analysts/{symbol}", "analyst_targets",
        tg.get("targetMeanPrice") is not None and tg.get("targetHighPrice") is not None,
        {k: tg.get(k) for k in ("targetLowPrice", "targetMeanPrice", "targetHighPrice")},
        "price targets back the consensus line - web/app.js reads these exact keys")

    e = c.get("/api/events/NVDA").json()
    chk("/api/events/{symbol}", "events", e.get("surprise_history") is not None,
        f"{len(e.get('surprise_history') or [])} past surprises", "earnings calendar")

    idx = c.get("/api/indices").json().get("indices", [])
    names = [i["label"] for i in idx]
    chk("/api/indices", "indices", {"S&P 500", "Dow Jones", "Nasdaq"} <= set(names), names,
        "the big three plus fear & greed, volatility, the 10-year")
    chk("/api/indices", "no_russell", "Russell 2000" not in names, "", "explicitly excluded")
    fg = next((i for i in idx if i["label"] == "Fear & Greed"), None)
    chk("/api/indices", "fear_greed", fg is not None and fg.get("level") is not None,
        f"{(fg or {}).get('level')} ({(fg or {}).get('note') or (fg or {}).get('state')})",
        "the speedometer gauge")
    charted = [i for i in idx if i["label"] != "Fear & Greed"]
    chk("/api/indices", "indices_have_history",
        all(len(i.get("history") or []) > 5 for i in charted),
        {i["label"]: len(i.get("history") or []) for i in charted},
        "the charts under the big three")

    cmp_ = c.get("/api/compare?symbols=NVDA,AMD,AVGO").json()
    chk("/api/compare", "compare",
        len(cmp_.get("rows") or []) == 3 and len(cmp_.get("paths") or []) > 50,
        f"{len(cmp_.get('rows') or [])} rows, {len(cmp_.get('paths') or [])} points, "
        f"{len(cmp_.get('correlations') or [])} pairs",
        "the research terminal compares several tickers at once")
    chk("/api/compare", "compare_pairwise",
        all("correlation" in x or "corr" in x for x in (cmp_.get("correlations") or [])),
        (cmp_.get("correlations") or [None])[0],
        "pairwise correlation is what makes it a comparison, not three charts")

    r = c.get("/api/compare?symbols=%3Cimg%20src%3Dx%3E")
    chk("/api/compare", "compare_rejects_markup", r.status_code == 400, r.status_code,
        "a 'symbol' with markup in it is echoed into the page - it must be refused")

    er = c.get("/api/calendar/earnings?days=7&limit=8").json()
    items = er.get("items") or []
    chk("/api/calendar/earnings", "earnings_week",
        (items and all(i.get("symbol") and i.get("date") for i in items)
         and items == sorted(items, key=lambda i: -(i.get("market_cap") or 0))) or bool(er.get("unavailable")),
        f"{len(items)} of {er.get('total_reporting')} reporting · {er.get('unavailable') or ''}",
        "the Pro dashboard lists who reports this week, largest first")

    rel = c.get("/api/related/NVDA").json()
    peers = ((rel.get("read_across") or {}).get("peers")) or []
    chk("/api/related/{symbol}", "related", len(peers) > 0,
        [x["peer"] for x in peers][:6],
        "adjacent names must be DISCOVERED, never hardcoded")
    chk("/api/related/{symbol}", "related_is_measured",
        all(x.get("correlation") is not None and x.get("observations") for x in peers),
        f"{peers[0]['peer']}: corr={peers[0].get('correlation')} "
        f"n={peers[0].get('observations')}" if peers else "",
        "a peer list without measured co-movement is just a guess")
    chk("/api/related/{symbol}", "related_moves", bool(rel.get("moves")),
        list((rel.get("moves") or {}))[:5], "today's move for the cohort")
    peer = peers[0].get("peer") if peers else None
    if peer:
        es = c.get(f"/api/related/NVDA/event-study/{peer}").json()
        res = es.get("result") or {}
        evs = res.get("events") or []
        chk("/api/related/{symbol}/event-study/{peer}", "event_study", len(evs) > 0,
            f"{es.get('source')} earnings -> {es.get('target')} reaction: {len(evs)} events",
            "does that PEER's earnings move THIS ticker - the route reads "
            "/related/{who reacts}/event-study/{whose earnings}")
        chk("/api/related/{symbol}/event-study/{peer}", "event_study_direction",
            es.get("source") == peer and es.get("target") == "NVDA",
            f"source={es.get('source')} target={es.get('target')}",
            "the labels must say which way round it was measured")
        chk("/api/related/{symbol}/event-study/{peer}", "event_study_deduped",
            len({e["date"] for e in evs}) == len(evs),
            f"{len(evs)} events, {len({e['date'] for e in evs})} unique dates",
            "REGRESSION: earnings_dates repeats rows per announcement")
        chk("/api/related/{symbol}/event-study/{peer}", "event_study_baseline",
            res.get("baseline_same_direction_pct") is not None,
            f"baseline {res.get('baseline_same_direction_pct')}%, "
            f"p={res.get('binomial_p_one_sided')}",
            "a hit rate without a baseline is not evidence of anything")

    sr = c.get("/api/search?q=coca").json().get("results", [])
    chk("/api/search", "search", any(x["symbol"] == "KO" for x in sr),
        [x["symbol"] for x in sr][:5], "symbol lookup for the research terminal")

    lg = c.get("/api/logo/NVDA")
    chk("/api/logo/{symbol}", "logo",
        lg.status_code == 200 and lg.headers["content-type"].startswith("image"),
        f"{lg.status_code} {lg.headers.get('content-type')} {len(lg.content)}B", "")

    head("guest — the whole product minus a book")
    me = c.get("/api/me").json()
    chk("/api/me", "guest_identity", me["guest"] and not me["can_save"], me["name"], "")
    chk("/api/watchlist", "guest_watchlist_empty",
        c.get("/api/watchlist").json()["watchlist"] == [], "",
        "a guest must never be served the local user's book")
    chk("/api/watchlist", "guest_write_401",
        c.post("/api/watchlist", json={"ticker": "NVDA"}).status_code == 401, "", "")
    chk("/api/portfolios", "guest_portfolios_empty",
        c.get("/api/portfolios").json()["accounts"] == [], "", "")
    chk("/api/portfolios", "guest_create_401",
        c.post("/api/portfolios", json={"name": "X"}).status_code == 401, "", "")
    chk("/api/positions", "guest_position_401",
        c.post("/api/positions", json={"ticker": "NVDA", "qty": 1, "basis": 1}
               ).status_code == 401, "", "")
    chk("/api/reset", "guest_reset_401", c.post("/api/reset").status_code == 401, "", "")
    gb = c.get("/api/brief").json()
    chk("/api/brief", "guest_brief_is_macro_only",
        gb.get("market_only") is True and not gb.get("checked")
        and len(gb.get("market_headlines") or []) > 0,
        f"market_only={gb.get('market_only')}, {len(gb.get('checked') or [])} tickers, "
        f"{len(gb.get('market_headlines') or [])} macro headlines",
        "a signed-out brief is market-wide news, not ticker news")
    chk("/api/brief", "guest_brief_says_why",
        bool(gb.get("reason")), gb.get("reason"),
        "the empty state must explain itself, not look broken")
    chk("/api/auth/providers", "providers",
        c.get("/api/auth/providers").json()["password"] is True, "", "")

    head("sign in, then own things")
    r = c.post("/api/auth/register",
               json={"username": "sweeper", "password": "harbor-lantern-sweep-9"})
    chk("/api/auth/register", "register", r.status_code == 200, str(r.json())[:60], "")
    chk("/api/auth/login", "login_reachable",
        TestClient(app).post("/api/auth/login",
                             json={"username": "sweeper",
                                   "password": "harbor-lantern-sweep-9"}
                             ).status_code == 200, "", "")

    chk("/api/watchlist", "watch_add",
        "TSM" in c.post("/api/watchlist", json={"ticker": "TSM"}).json()["watchlist"], "", "")
    chk("/api/watchlist", "watch_rejects_junk",
        c.post("/api/watchlist", json={"ticker": "ZZQQXX"}).status_code == 404, "",
        "an unresolvable symbol must not enter the watchlist")
    chk("/api/watchlist/{ticker}", "watch_delete",
        "TSM" not in c.delete("/api/watchlist/TSM").json()["watchlist"], "", "")

    pf = c.post("/api/portfolios", json={"name": "Roth IRA", "kind": "roth ira"}).json()
    rid = next(a["id"] for a in pf["accounts"] if a["name"] == "Roth IRA")
    chk("/api/portfolios", "account_create", bool(rid), rid, "named accounts: 401k/Roth/taxable")
    chk("/api/portfolios", "account_name_unique",
        c.post("/api/portfolios", json={"name": "Roth IRA"}).status_code == 409, "", "")
    chk("/api/portfolios/{pid}", "account_rename",
        c.patch(f"/api/portfolios/{rid}", json={"name": "Roth"}).status_code == 200, "", "")
    chk("/api/portfolios/{pid}/activate", "account_activate",
        c.post(f"/api/portfolios/{rid}/activate").status_code == 200, "", "")

    chk("/api/positions", "position_add",
        c.post("/api/positions",
               json={"ticker": "NVDA", "qty": 10, "basis": 100.0,
                     "portfolio_id": rid}).status_code == 200, "", "")
    c.post("/api/positions", json={"ticker": "NVDA", "qty": 10, "basis": 200.0,
                                   "portfolio_id": rid})
    p = c.get(f"/api/portfolio?portfolio_id={rid}").json()
    pos = next((x for x in p["positions"] if x["ticker"] == "NVDA"), {})
    chk("/api/positions", "position_averages_basis",
        pos.get("qty") == 20 and abs(pos.get("basis", 0) - 150.0) < 0.01,
        f"qty={pos.get('qty')} basis={pos.get('basis')}",
        "adding the same ticker twice averages the lot, it does not duplicate")
    chk("/api/portfolio", "portfolio_math",
        abs(p["market_value"] - sum(x["market_value"] for x in p["positions"])) < 1,
        f"${p['market_value']:,.0f}", "the total must be the sum of the rows")

    allp = c.get("/api/portfolio?portfolio_id=all").json()
    chk("/api/portfolio", "combined_view", allp.get("is_combined") is True,
        f"${allp['market_value']:,.0f} across {len(allp['positions'])} rows",
        "the same ticker in two accounts stays two cost bases")
    an = c.get(f"/api/portfolio/analytics?portfolio_id={rid}").json()
    conc = an.get("concentration") or {}
    chk("/api/portfolio/analytics", "analytics", bool(conc),
        {k: conc.get(k) for k in list(conc)[:4]}, "risk profile, no LLM in the path")
    chk("/api/portfolio/analytics", "analytics_beta",
        an.get("beta") is not None, an.get("beta"),
        "beta against the market, computed from cached bars")

    r = c.patch("/api/positions/NVDA",
                json={"ticker": "NVDA", "qty": 5, "basis": 120.0, "portfolio_id": rid})
    edited = next((x for x in r.json().get("positions", []) if x["ticker"] == "NVDA"), {})
    chk("/api/positions/{ticker}", "position_edit",
        r.status_code == 200 and edited.get("qty") == 5 and edited.get("basis") == 120.0,
        f"{r.status_code} -> qty={edited.get('qty')} basis={edited.get('basis')}",
        "an edit must REPLACE the lot, not average into it the way adding does")
    chk("/api/positions/{ticker}", "position_edit_404s_cleanly",
        c.patch("/api/positions/ZZQQ",
                json={"ticker": "ZZQQ", "qty": 1, "basis": 1,
                      "portfolio_id": rid}).status_code == 404, "", "")
    chk("/api/positions/{ticker}", "position_delete",
        c.delete(f"/api/positions/NVDA?portfolio_id={rid}").status_code == 200, "", "")
    chk("/api/portfolios/{pid}", "account_delete",
        c.delete(f"/api/portfolios/{rid}").status_code == 200, "", "")

    head("daily brief, signed in")
    c.post("/api/watchlist", json={"ticker": "NVDA"})
    br = c.get("/api/brief").json()
    chk("/api/brief", "brief_signals",
        "signals" in br and br.get("market_only") is not True,
        f"{len(br.get('signals') or [])} signals over "
        f"{len(br.get('checked') or [])} tickers", "")
    chk("/api/brief", "brief_macro", len(br.get("market_headlines") or []) > 0,
        f"{len(br.get('market_headlines') or [])} macro headlines",
        "rates, jobs, war - what moves the whole market")
    chk("/api/brief", "brief_index_levels", bool(br.get("index_levels")),
        list(br.get("index_levels") or {}), "the brief opens on where the market is")
    chk("/api/brief", "brief_checks_adjacent",
        "adjacent_checked" in br, f"{len(br.get('adjacent_checked') or [])} adjacent names",
        "news on names you do NOT hold can still move what you do")
    big = [s for s in (br.get("signals") or []) if s.get("kind") == "threshold"]
    chk("/api/brief", "threshold_moves_explain_themselves",
        all(s.get("why") for s in big) if big else True,
        f"{len(big)} threshold moves, all with a reason: "
        f"{all(s.get('why') for s in big) if big else 'none today'}",
        "a +/-5% flag without a reason is just a number")

    head("agent plane")
    ds = c.get("/api/agent/domains").json()["domains"]
    chk("/api/agent/domains", "domains_registered", len(ds) >= 7,
        [d.get("name") or d.get("domain") for d in ds], "")
    empty = [d.get("name") or d.get("domain") for d in ds
             if not (d.get("tools") or d.get("tool_count"))]
    chk("/api/agent/domains", "every_domain_has_tools", not empty, empty or "all populated",
        "REGRESSION: the portfolio domain once had tools registered but no subgraph")
    ntools = sum(len(d.get("tools") or []) or d.get("tool_count", 0) for d in ds)
    chk("/api/agent/domains", "tool_count", ntools >= 40, f"{ntools} tools", "")
    if run_agent:
        t0 = time.time()
        r = c.post("/api/agent/ask", json={"question": "How is NVDA doing today?",
                                           "tickers": ["NVDA"]}, timeout=300)
        d = r.json()
        chk("/api/agent/ask", "agent_ask", r.status_code == 200 and len(d.get("answer", "")) > 80,
            f"{len(d.get('answer',''))} chars in {time.time()-t0:.0f}s", "")
        chk("/api/agent/ask", "agent_grounded", d.get("grounded") is not False,
            f"ungrounded: {d.get('ungrounded_numbers')}",
            "every figure must trace to evidence")
        # The disclaimer is a response FIELD, not prose inside the answer -
        # the client renders it under every reply, so the model is never asked
        # to remember it and can never drop it.
        chk("/api/agent/ask", "agent_disclaimer",
            "not financial advice" in (d.get("disclaimer") or "").lower(),
            (d.get("disclaimer") or "")[:70], "every reply must carry the disclaimer")
        shell = c.get("/").text
        chk("/api/agent/ask", "disclaimer_rendered",
            "not investment advice" in shell.lower() or "not financial advice" in shell.lower(),
            "present in the shell", "a field nobody renders is not a disclaimer")
    else:
        print("  SKIP  agent ask/analyze/brief (pass --agent to spend tokens)")

    head("reset")
    chk("/api/reset", "reset_keeps_watchlist",
        c.post("/api/reset?keep_watchlist=true").status_code == 200, "", "")
    chk("/api/reset", "reset_clears_positions",
        all(not a["positions"] for a in c.get("/api/portfolios").json()["accounts"]),
        "", "")

    head("config is documented")
    # A setting nobody knows about is a setting that gets left at its default,
    # and two of these have security consequences when that happens.
    import pathlib as _pl, re as _re
    root = _pl.Path(os.getcwd())
    read_by_code = set()
    for f in (root / "backend").rglob("*.py"):
        read_by_code |= set(_re.findall(r'os\.environ(?:\.get\(|\[)"([A-Z_]+)"',
                                        f.read_text()))
    for doc in ("HOSTING.md", ".env.example"):
        text = (root / doc).read_text()
        gaps = sorted(v for v in read_by_code if v not in text)
        chk("meta", f"env_documented_in_{doc.strip('.').replace('.', '_')}",
            not gaps, gaps or f"all {len(read_by_code)} documented",
            "an undocumented env var gets left at its default")
    chk("meta", "cookie_secure_warns_when_insecure",
        "WITHOUT the Secure flag" in (root / "backend/app/auth.py").read_text(),
        "startup warns on a non-https APP_BASE_URL",
        "the cookie's Secure flag is DERIVED from APP_BASE_URL, so a forgotten "
        "env var is a silent downgrade rather than an error")

    head("docker build context")
    # A bare COPY . . bakes .env and data/ into a layer, and deleting them in a
    # later layer does not remove them from the image. This asserts the
    # .dockerignore still excludes everything secret-bearing - the check that
    # matters when a new path holding credentials or user data gets added.
    import fnmatch as _fn
    _di = _pl.Path(os.getcwd()) / ".dockerignore"
    chk("meta", "dockerignore_exists", _di.exists(), str(_di.name),
        "without it the image ships a live API key and somebody's portfolio")
    if _di.exists():
        _pats = [l.strip() for l in _di.read_text().splitlines()
                 if l.strip() and not l.strip().startswith("#")]

        def _excluded(rel: str) -> bool:
            hit = False
            for p in _pats:
                neg = p.startswith("!")
                d = (p[1:] if neg else p).rstrip("/")
                if (_fn.fnmatch(rel, d) or rel.startswith(d + "/")
                        or any(_fn.fnmatch(x, d) for x in rel.split("/"))):
                    hit = not neg
            return hit

        secret = [".env", ".env.bak", "data/monsoon.db", "data/store.json.migrated",
                  ".venv/bin/python", ".git/config"]
        shipped = [f for f in secret if not _excluded(f)]
        chk("meta", "dockerignore_blocks_secrets", not shipped,
            shipped or f"all {len(secret)} excluded",
            "an image layer keeps a file even after a later layer deletes it")
        needed = ["requirements.txt", "backend/app/main.py", "web/index.html",
                  "web/app.js", "web/charts.js"]
        dropped = [f for f in needed if _excluded(f)]
        chk("meta", "dockerignore_keeps_the_app", not dropped,
            dropped or f"all {len(needed)} present",
            "over-broad ignores give you an image that cannot start")

    head("coverage")
    import backend.app.main as M
    routes = {f"{m}:{r.path}" for r in M.app.routes
              for m in (getattr(r, "methods", None) or [])
              if m not in ("HEAD", "OPTIONS")}
    paths = {p.split(":", 1)[1] for p in routes}
    skip = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect",     # FastAPI built-ins
            "/api/auth/callback/{provider}", "/api/auth/login/{provider}",   # need a provider
            "/api/auth/logout", "/api/auth/password", "/api/auth/account",   # login_probe.py
            "/api/auth/claim-legacy",                                        # suite_claim
            "/api/agent/ask/stream", "/api/agent/analyze", "/api/agent/brief",
            "/api/agent/ask"}
    missed = sorted(paths - SEEN - skip)
    chk("meta", "every_route_touched", not missed, missed or "all covered",
        "a sweep that skips routes is not a sweep")

    n = sum(x["pass"] for x in R)
    print(f"\n{n}/{len(R)} checks passed   ({len(SEEN)} routes touched)")
    print("@@" + json.dumps(R))
    return 0 if n == len(R) else 1


if __name__ == "__main__":
    sys.exit(main("--agent" in sys.argv))
