"""Negative control — proves the suite can actually fail.

A suite that reports 100% is worthless unless you have shown it detects a real
break. This deliberately sabotages three defences and asserts the matching test
goes red, then restores them.

    python evals/negative_control.py
"""
from __future__ import annotations
import asyncio, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "backend"))
try:                                   # evals run outside the app, load .env too
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass
from evals.suites import sign_in_for_evals, suite_auth, suite_regressions  # noqa: E402


async def main() -> int:
    import app.routes.data as D, app.graph.build as B, app.tools.relations as R

    base = await suite_regressions()
    print(f"baseline: {sum(r['pass'] for r in base)}/{len(base)} pass\n")

    checks, ok = [], True

    async def sabotage(label, test_id, apply, undo):
        nonlocal ok
        apply()
        try:
            r = await suite_regressions()
            caught = not next(x for x in r if x["id"] == test_id)["pass"]
        finally:
            undo()
        ok &= caught
        checks.append((label, test_id, caught))
        print(f"  {label:<34} {test_id:<24} {'CAUGHT' if caught else 'MISSED'}")

    o = D.BIG_MOVE_PCT
    await sabotage("threshold raised to 99%", "threshold_5pct",
                   lambda: setattr(D, "BIG_MOVE_PCT", 99.0),
                   lambda: setattr(D, "BIG_MOVE_PCT", o))

    on = B._NOISE
    await sabotage("date/name stripper disabled", "grounding:dates",
                   lambda: setattr(B, "_NOISE", []),
                   lambda: setattr(B, "_NOISE", on))

    op = R.yahoo.peers
    async def dead(_s): return []
    await sabotage("peer discovery returns nothing", "peers_dynamic",
                   lambda: setattr(R.yahoo, "peers", dead),
                   lambda: setattr(R.yahoo, "peers", op))

    # ── the fixes from the quality loop: each guard must be able to fail ──
    import json as _json
    import app.providers.edgar as E
    from app.tools import TOOLS as _T
    oq = E._quarterly
    await sabotage("fiscal Q4 no longer derived", "edgar_q4_derived",
                   lambda: setattr(E, "_quarterly", lambda u, derive_q4=True: oq(u, False)),
                   lambda: setattr(E, "_quarterly", oq))

    ow = B.writer_payload
    def cut(findings, budget=16000):          # the old json.dumps(...)[:16000]
        return _json.dumps([{"domain": f.domain, "ticker": f.ticker, "finding": f.narrative,
                             "evidence": {e.tool: e.data for e in f.evidence}}
                            for f in findings], default=str)[:budget]
    await sabotage("writer payload cut at 16k", "writer_keeps_every_finding",
                   lambda: setattr(B, "writer_payload", cut),
                   lambda: setattr(B, "writer_payload", ow))

    lt = _T["leverage_liquidity"]
    olf = lt.fn
    async def raw_pct(t, **_):                # Yahoo's percent handed over raw
        from app.models import ToolResult, Provenance
        return ToolResult(tool="leverage_liquidity", ticker=t, prov=Provenance(source="x"),
                          data={"debt_to_equity": 16.97})
    await sabotage("leverage percent passed raw", "leverage_ratio_not_percent",
                   lambda: setattr(lt, "fn", raw_pct), lambda: setattr(lt, "fn", olf))

    # ── the auth defences, sabotaged the same way ──
    import app.passwords as P
    print()
    sign_in_for_evals()
    abase = suite_auth()
    print(f"auth baseline: {sum(r['pass'] for r in abase)}/{len(abase)} pass")

    def sab_sync(label, test_id, apply, undo):
        nonlocal ok
        apply()
        try:
            r = suite_auth()
            caught = not next(x for x in r if x["id"] == test_id)["pass"]
        finally:
            undo()
        ok &= caught
        checks.append((label, test_id, caught))
        print(f"  {label:<34} {test_id:<24} {'CAUGHT' if caught else 'MISSED'}")

    ol = P.MIN_LEN
    sab_sync("password minimum dropped to 1", "rejects_weak_passwords",
             lambda: setattr(P, "MIN_LEN", 1), lambda: setattr(P, "MIN_LEN", ol))

    om = P.MAX_FAILS
    sab_sync("login throttle disabled", "throttle_locks_out",
             lambda: setattr(P, "MAX_FAILS", 10**9), lambda: setattr(P, "MAX_FAILS", om))

    oh = P.hash_password
    sab_sync("hashing replaced by plaintext", "hash_not_plaintext",
             lambda: setattr(P, "hash_password", lambda pw: "plain:" + pw),
             lambda: setattr(P, "hash_password", oh))

    aafter = suite_auth()
    arest = sum(r["pass"] for r in aafter) == len(aafter)
    print(f"auth restored: {sum(r['pass'] for r in aafter)}/{len(aafter)} pass")

    after = await suite_regressions()
    restored = sum(r["pass"] for r in after) == len(after) and arest
    print(f"\nrestored: {sum(r['pass'] for r in after)}/{len(after)} pass")
    print("\n" + ("negative control PASSED - every sabotage was detected"
                  if ok and restored else "negative control FAILED"))
    return 0 if (ok and restored) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
