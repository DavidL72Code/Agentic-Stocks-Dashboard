"""The optional Redis cache tier.

Covers the four things that can go wrong with a second cache tier:

  1. it changes behaviour when it is NOT configured (it must not),
  2. its keys collide, so one symbol's data is served for another,
  3. it corrupts values on the round trip,
  4. it is down, and every cache miss now pays a connect timeout.

A real redis-py async client is used throughout - against fakeredis for the
round-trip tests, so no server is needed, and against a genuinely closed port
for the circuit breaker. If REDIS_TEST_URL points at a real Redis, the
round-trip block runs against that instead.

    python evals/cache_probe.py
"""
from __future__ import annotations
import asyncio, json, os, sys, time

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))

R: list[dict] = []


def chk(name, cond, detail="", why=""):
    R.append({"id": name, "pass": bool(cond), "detail": str(detail)[:130],
              "ms": 0, "why": why})
    print(f"  {'PASS' if cond else 'FAIL'}  {name:<42} {str(detail)[:60]}")


async def main() -> int:
    from app import cache as C

    print("\n── unconfigured: nothing may change ──")
    chk("l2_off_by_default", C.L2 is None or not C.REDIS_URL,
        f"REDIS_URL={C.REDIS_URL!r}, L2={type(C.L2).__name__ if C.L2 else None}",
        "the default install must not grow a dependency")

    calls = {"n": 0}

    async def fetch():
        calls["n"] += 1
        return {"v": calls["n"]}

    C.CACHE._d.clear()
    v1, _ = await C.cached(("probe", "a"), 60, fetch)
    v2, _ = await C.cached(("probe", "a"), 60, fetch)
    chk("l1_still_caches", v1 == v2 and calls["n"] == 1,
        f"{calls['n']} upstream call(s) for 2 reads",
        "with no Redis the in-process tier must behave exactly as before")

    print("\n── keys: readable, and collision-safe ──")
    k = C.RedisL2.key(("bars", "NVDA", "1mo", "1d"))
    chk("key_is_prefixed_and_labelled",
        k.startswith(f"{C.REDIS_PREFIX}:bars:"), k,
        "redis-cli --scan --pattern 'monsoon:v1:bars:*' should be useful")
    a, b = C.RedisL2.key(("a", "b:c")), C.RedisL2.key(("a:b", "c"))
    chk("key_no_separator_collision", a != b, f"{a[-12:]} vs {b[-12:]}",
        "a naive ':'.join makes ('a','b:c') and ('a:b','c') the same key - "
        "which would serve one ticker's data for another")
    chk("key_is_stable",
        C.RedisL2.key(("bars", "NVDA", "1mo", "1d")) == k, "same input, same key",
        "an unstable key is a cache that never hits")
    chk("key_distinguishes_symbols",
        C.RedisL2.key(("bars", "NVDA")) != C.RedisL2.key(("bars", "AMD")),
        "NVDA != AMD", "")

    print("\n── round trip through a real redis-py client ──")
    live = os.environ.get("REDIS_TEST_URL", "").strip()
    l2 = C.RedisL2(live or "redis://127.0.0.1:6379/15")
    if live:
        backend = f"live Redis at {live}"
    else:
        import fakeredis.aioredis
        l2._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        backend = "fakeredis (real redis-py async API, in-memory server)"
    print(f"  using: {backend}")

    payload = {"price": 230.86, "name": "NVIDIA Corporation",
               "history": [1.5, 2.5, None], "nested": {"pe": 28.9}}
    await l2.set(("quote", "NVDA"), payload, 60)
    got = await l2.get(("quote", "NVDA"))
    chk("round_trip_is_lossless", got is not None and got[0] == payload,
        f"wrote {len(json.dumps(payload))}B, read back equal: "
        f"{got is not None and got[0] == payload}",
        "a cache that changes a value's shape is worse than a miss")
    chk("round_trip_not_stale", got is not None and got[1] is False,
        f"stale={got[1] if got else '?'}", "a fresh write must not read as stale")
    chk("miss_returns_none", await l2.get(("quote", "NEVER-WRITTEN")) is None,
        "None", "")

    # logical expiry vs physical TTL: get_stale must still find it
    await l2.set(("quote", "OLD"), {"price": 1.0}, 0.01)
    await asyncio.sleep(0.05)
    old = await l2.get(("quote", "OLD"))
    chk("expired_value_is_kept_but_flagged",
        old is not None and old[1] is True and old[0] == {"price": 1.0},
        f"value survived, stale={old[1] if old else '?'}",
        "degrading to a last-known value beats blanking the UI")
    # measured at a realistic TTL: at ttl=0.01 the max(1, ...) floor would pass
    # this on its own and prove nothing about STALE_FACTOR
    await l2.set(("quote", "TTL"), {"price": 1.0}, 60)
    ttl = await (await l2.client()).ttl(C.RedisL2.key(("quote", "TTL")))
    want = int(60 * C.STALE_FACTOR)
    chk("physical_ttl_outlives_logical", ttl is not None and abs(ttl - want) <= 2,
        f"logical 60s -> physical {ttl}s (expected ~{want}s)",
        f"STALE_FACTOR={C.STALE_FACTOR} is what keeps a value around to degrade to")

    print("\n── values JSON cannot represent ──")
    import datetime
    before = l2.unserialisable
    await l2.set(("attr", "NVDA", "earnings_dates"),
                 {datetime.datetime(2026, 11, 17): {"eps": 2.47}}, 60)
    chk("unserialisable_is_skipped_not_fatal", l2.unserialisable == before + 1,
        f"not_json counter {before} -> {l2.unserialisable}",
        "a Timestamp-keyed dict must skip L2 quietly, not raise into a request")
    chk("unserialisable_is_not_written",
        await l2.get(("attr", "NVDA", "earnings_dates")) is None, "nothing stored",
        "better no entry than a silently coerced one")

    print("\n── a dead Redis must not slow every request ──")
    dead = C.RedisL2("redis://127.0.0.1:1/0")       # port 1, nothing listens
    t0 = time.time()
    for _ in range(C.RedisL2._TRIP):
        await dead.get(("probe", "x"))
    tripped = time.time() - t0
    chk("failures_trip_the_breaker", dead.paused(),
        f"{dead.errors} errors in {tripped*1000:.0f}ms -> paused",
        "without this, every miss pays a connect timeout forever")
    t0 = time.time()
    for _ in range(50):
        await dead.get(("probe", "x"))
        await dead.set(("probe", "x"), {"a": 1}, 60)
    after = time.time() - t0
    chk("paused_calls_are_free", after < 0.05, f"100 ops in {after*1000:.1f}ms",
        "while paused it must not touch the socket at all")
    chk("breaker_reports_itself", dead.stats()["paused"] is True
        and "last_error" in dead.stats(), dead.stats().get("last_error", "")[:60],
        "/api/health must say the cache tier is degraded")

    print("\n── cached() uses L2, and promotes into L1 ──")
    import fakeredis.aioredis
    shared = fakeredis.aioredis.FakeRedis(decode_responses=True)
    orig = C.L2
    try:
        C.L2 = C.RedisL2("redis://unused")
        C.L2._client = shared
        hits = {"n": 0}

        async def slow():
            hits["n"] += 1
            return {"price": 123.45}

        C.CACHE._d.clear()
        await C.cached(("quote", "SHARED"), 60, slow)
        chk("cached_writes_through_to_l2", C.L2.writes >= 1,
            f"{C.L2.writes} L2 write(s)", "")

        # a RESTART: L1 is gone, L2 is not. This is the whole point.
        C.CACHE._d.clear()
        val, stale = await C.cached(("quote", "SHARED"), 60, slow)
        chk("survives_an_l1_wipe",
            val == {"price": 123.45} and hits["n"] == 1 and not stale,
            f"{hits['n']} upstream call(s) across a cleared L1",
            "a restart used to cold-start every quote and bar")
        chk("l2_hit_is_promoted_to_l1",
            C.CACHE.get(("quote", "SHARED")) == {"price": 123.45},
            "present in L1 after an L2 hit",
            "otherwise every read pays the network hop")
    finally:
        C.L2 = orig

    print("\n── what must NOT be cached ──")
    import inspect
    from app.providers import yahoo
    src = inspect.getsource(yahoo.quote) + inspect.getsource(yahoo.quotes)
    chk("live_prices_are_not_ttl_cached", "cached(" not in src,
        "quote()/quotes() go straight through BatchLoader",
        "prices must be fetched every time. Batching coalesces concurrent "
        "callers into one request; a TTL cache would serve a stale price, and "
        "L2 would make it stale across restarts too")
    chk("bars_are_cached", "cached(" in inspect.getsource(yahoo.bars),
        "bars() goes through cached()",
        "charts, financials, news and logos are what L2 is for")

    n = sum(x["pass"] for x in R)
    print(f"\n{n}/{len(R)} checks passed")
    print("@@" + json.dumps(R))
    return 0 if n == len(R) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
