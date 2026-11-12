"""Production smoke test: does every dashboard and research feature return
real content, not just a 200?

    python evals/smoke.py                                   # the live site
    python evals/smoke.py --base http://127.0.0.1:8077      # a local server

Standard library only, so CI needs no install. Exit code 1 on any failure.

Why this exists. Every bug found on Nov 11 2026 answered 200 with an empty
or wrong body, and every one passed the local suite, because this machine
gets Yahoo's crumb and Render does not:
  * the market map drew nothing (no market caps on the chart-quote path)
  * the earnings panel said "no large companies report this week" with
    1,031 companies reporting, CoreWeave among them, the night it reported
  * /api/news was a 500 for every ticker and the market-news panel was empty
  * "next earnings" was null for NVDA six days before its report
A status check passes all of those. These checks read the content.
"""
from __future__ import annotations
import argparse, json, sys, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone

DEFAULT = "https://agentic-stocks-dashboard.onrender.com"
STOCKS = ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "LLY", "CRWV"]
SLOW_S = 6.0          # a warm call slower than this is a failure, not a nuisance


def ny_today() -> str:
    # New York date without zoneinfo data on the runner: EST/EDT by US rule
    now = datetime.now(timezone.utc)
    y = now.year
    mar = datetime(y, 3, 8, 7, tzinfo=timezone.utc)
    dst_start = mar + timedelta(days=(6 - mar.weekday()) % 7)          # 2nd Sunday of March
    nov = datetime(y, 11, 1, 6, tzinfo=timezone.utc)
    dst_end = nov + timedelta(days=(6 - nov.weekday()) % 7)            # 1st Sunday of November
    off = -4 if dst_start <= now < dst_end else -5
    return (now + timedelta(hours=off)).date().isoformat()


class Smoke:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.rows: list[tuple[str, bool, str, float]] = []

    def get(self, path: str, timeout: float = 60) -> tuple[int, dict | str, float, dict]:
        t0 = time.time()
        req = urllib.request.Request(self.base + path, headers={"User-Agent": "monsoon-smoke/1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body, code, hdr = r.read().decode(), r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            body, code, hdr = e.read().decode(errors="replace"), e.code, dict(e.headers)
        except Exception as e:                       # timeouts, DNS, resets
            return 0, f"{type(e).__name__}: {e}", time.time() - t0, {}
        dt = time.time() - t0
        try:
            return code, json.loads(body), dt, hdr
        except ValueError:
            return code, body, dt, hdr

    def check(self, name: str, path: str, test, timeout: float = 60) -> dict | None:
        code, body, dt, _ = self.get(path, timeout)
        if code != 200 or not isinstance(body, dict):
            self.rows.append((name, False, f"HTTP {code}: {str(body)[:90]}", dt))
            return None
        try:
            ok, detail = test(body)
        except Exception as e:
            ok, detail = False, f"check raised {type(e).__name__}: {e}"
        if ok and dt > SLOW_S:
            ok, detail = False, f"slow: {dt:.1f}s (budget {SLOW_S:.0f}s) - {detail}"
        self.rows.append((name, bool(ok), detail, dt))
        return body

    def run(self) -> int:
        today = ny_today()
        # wake it first; a sleeping Render instance takes about a minute
        code, _, dt, _ = self.get("/api/health", timeout=150)
        self.rows.append(("wake: /api/health", code == 200, f"HTTP {code}", dt))
        if code != 200:
            return self.report()

        self.check("indices: levels and history", "/api/indices", lambda d: (
            len(d["indices"]) >= 5 and all(i.get("level") is not None and len(i.get("history") or []) > 5
                                           for i in d["indices"]),
            f"{len(d['indices'])} gauges"))

        def caps(d):
            q = {x["symbol"]: x for x in d["quotes"]}
            missing_px = [s for s in STOCKS if (q.get(s) or {}).get("price") is None]
            missing_cap = [s for s in STOCKS if not (q.get(s) or {}).get("market_cap")]
            return (not missing_px and not missing_cap,
                    f"no price: {missing_px or '-'}; no market cap (the map sizes by it): {missing_cap or '-'}")
        self.check("quotes: price and market cap", "/api/quotes?symbols=" + ",".join(STOCKS), caps)

        def earnings(d):
            items, total = d.get("items") or [], d.get("total_reporting") or 0
            lo, hi = (d.get("window") or [today, today])
            wrong = [e["symbol"] for e in items if not (lo <= e["date"] <= hi)]
            future_as_done = [e["symbol"] for e in items if e.get("reported") and e["date"] > today]
            return (bool(items) == bool(total) and not wrong and not future_as_done,
                    f"{len(items)} shown of {total} reporting; outside window: {wrong or '-'}; "
                    f"future marked reported: {future_as_done or '-'}")
        self.check("earnings this week: non-empty when anyone reports", "/api/calendar/earnings?limit=30", earnings)

        self.check("news: headlines for a ticker", "/api/news/NVDA",
                   lambda d: (len(d.get("items") or []) > 0, f"{len(d.get('items') or [])} headlines"))
        self.check("brief: market headlines", "/api/brief",
                   lambda d: (len(d.get("market_headlines") or []) > 0,
                              f"{len(d.get('market_headlines') or [])} headlines, {len(d.get('signals') or [])} signals"))

        # NVDA always has a report on the calendar, so "none" is a failure too
        self.check("events: next report is upcoming, not past or missing", "/api/events/NVDA", lambda d: (
            (d.get("next_earnings") or "") >= today and len(d.get("surprise_history") or []) > 0,
            f"next {d.get('next_earnings')} (today {today}), {len(d.get('surprise_history') or [])} past reports"))

        def fin(d):
            up = d.get("upcoming") or {}
            withrev = sum(1 for q in d.get("quarters") or [] if q.get("revenue"))
            return ((up.get("date") or "") >= today and withrev >= 4,
                    f"upcoming {up.get('date')}, {withrev} quarters with revenue, ttm {'yes' if d.get('ttm') else 'no'}")
        self.check("financials: SEC quarters and upcoming report", "/api/financials/NVDA", fin)

        def overview(d):
            need = ["price", "market_cap", "pe", "sector", "industry"]
            gone = [k for k in need if d.get(k) in (None, "")]
            pe_ok = d.get("pe") is None or 0 < d["pe"] < 1000
            dy_ok = d.get("dividend_yield") is None or 0 <= d["dividend_yield"] < 20
            pb_ok = d.get("price_to_book") is None or 0 < d["price_to_book"] < 500
            return (not gone and pe_ok and dy_ok and pb_ok,
                    f"missing {gone or '-'}; P/E {d.get('pe')}, P/B {d.get('price_to_book')}, "
                    f"yield {d.get('dividend_yield')}%")
        self.check("overview: valuation and profile", "/api/overview/NVDA", overview)

        def debt(d):
            b = d.get("balance") or {}
            need = ["debt", "cash", "net_debt", "free_cash_flow_12m", "interest_cover", "as_of"]
            gone = [k for k in need if b.get(k) is None]
            linked = bool(((b.get("filings") or [{}])[0]).get("url"))
            fresh = (b.get("as_of") or "") >= (datetime.now(timezone.utc) - timedelta(days=200)).date().isoformat()
            return (not gone and linked and fresh,
                    f"missing {gone or '-'}; as of {b.get('as_of')}, filing linked: {linked}; "
                    f"debt {b.get('debt')}, FCF {b.get('free_cash_flow_12m')}, cover {b.get('interest_cover')}")
        # CRWV: borrowing heavy and the case that was blank - every figure must be there
        self.check("debt and cash: debt, free cash flow, interest cover", "/api/overview/CRWV", debt)

        self.check("analysts: ratings and targets", "/api/analysts/NVDA", lambda d: (
            len(d.get("distribution") or []) > 0 and (d.get("targets") or {}).get("targetMeanPrice") is not None,
            f"{sum(x['n'] for x in d.get('distribution') or [])} ratings, mean target "
            f"{(d.get('targets') or {}).get('targetMeanPrice')}, rating changes "
            f"{'unavailable' if d.get('changes_unavailable') else len(d.get('changes') or [])}"))

        def study(d):
            r = d.get("result") or {}
            ev = r.get("events") or []
            same, base, p = r.get("peer_same_direction_pct"), r.get("baseline_same_direction_pct"), r.get("binomial_p_one_sided")
            consistent = None in (same, base, p) or (p < 0.5) == (same > base) or abs(same - base) < 1
            return (len(ev) >= 3 and consistent,
                    f"{len(ev)} events from {ev[0]['date'] if ev else '-'}; {same}% vs {base}% baseline, p={p}")
        self.check("event study: real events, p in the right tail", "/api/related/NVDA/event-study/AMD", study)

        def bars(d):
            b = d.get("bars") or []
            age = (time.time() - b[-1]["t"]) / 86400 if b else 99
            return len(b) >= 15 and age < 6, f"{len(b)} bars, newest {age:.1f} days old"
        self.check("bars: a month of daily prices", "/api/bars/NVDA?period=1mo&interval=1d", bars)
        self.check("sparklines: the watchlist's 30 days", "/api/sparklines?symbols=AAPL,NVDA", lambda d: (
            all(len(d["sparklines"].get(s) or []) > 10 for s in ("AAPL", "NVDA")), "AAPL and NVDA"))
        self.check("search: a company name finds its ticker", "/api/search?q=nvidia", lambda d: (
            any(r["symbol"] == "NVDA" for r in d.get("results") or []), f"{len(d.get('results') or [])} results"))
        self.check("compare: a basket side by side", "/api/compare?symbols=NVDA,AMD&period=6mo", lambda d: (
            len(d.get("rows") or []) == 2 and len(d.get("paths") or []) > 20,
            f"{len(d.get('rows') or [])} rows, {len(d.get('paths') or [])} path points"))
        return self.report()

    def report(self) -> int:
        w = max(len(r[0]) for r in self.rows)
        for name, ok, detail, dt in self.rows:
            print(f"  {'PASS' if ok else 'FAIL'}  {name:<{w}}  {dt:5.2f}s  {detail}")
        bad = [r for r in self.rows if not r[1]]
        print(f"\n{len(self.rows) - len(bad)}/{len(self.rows)} passed against {self.base}")
        return 1 if bad else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT)
    sys.exit(Smoke(ap.parse_args().base).run())
