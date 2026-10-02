"""TTL cache + in-flight coalescing + DataLoader-style batching.

Three separate jobs:
  TTLCache   - don't refetch what we already have
  coalesce   - N concurrent callers asking for the same key => 1 upstream call
  BatchLoader- N concurrent callers asking for DIFFERENT keys of the same kind
               => 1 batched upstream call (the v7/quote win)
"""
from __future__ import annotations
import asyncio, hashlib, json, logging, os, re, time
from typing import Any, Awaitable, Callable, Hashable, Iterable

log = logging.getLogger("monsoon.cache")


class TTLCache:
    def __init__(self) -> None:
        self._d: dict[Hashable, tuple[float, Any]] = {}

    def get(self, key: Hashable) -> Any | None:
        hit = self._d.get(key)
        if hit is None:
            return None
        exp, val = hit
        if time.time() > exp:
            return None          # expired but retained: still reachable via get_stale
        return val

    def get_stale(self, key: Hashable) -> Any | None:
        """Last known value regardless of age - for degrading instead of blanking."""
        hit = self._d.get(key)
        return hit[1] if hit else None

    def set(self, key: Hashable, val: Any, ttl: float) -> None:
        self._d[key] = (time.time() + ttl, val)

    def age(self, key: Hashable, ttl: float) -> float | None:
        hit = self._d.get(key)
        return None if hit is None else max(0.0, time.time() - (hit[0] - ttl))

    def stats(self) -> dict[str, int]:
        now = time.time()
        return {"entries": len(self._d),
                "fresh": sum(1 for exp, _ in self._d.values() if exp > now)}


CACHE = TTLCache()
_inflight: dict[Hashable, asyncio.Task] = {}


# ───────────────────── optional Redis second tier ─────────────────────
# Two tiers, not a replacement. The in-process dict stays as L1, so every
# existing synchronous call site keeps working unchanged and a hot read never
# pays a network hop. Redis is L2: read on an L1 miss, written on a fetch.
#
# What this actually buys: the cache survives a restart and is shared between
# workers. Today a dev-server reload cold-starts every quote and bar. That is
# the whole gain. Sessions and the login throttle deliberately stay in SQLite,
# where they are already revocable and already shared - so a Redis outage costs
# cache misses and can never lock anybody out of their account.
#
# Unset REDIS_URL and none of this runs.
REDIS_URL = os.environ.get("REDIS_URL", "").strip()
REDIS_PREFIX = os.environ.get("REDIS_PREFIX", "monsoon:v1").strip(":")
# Keep the Redis row alive longer than its logical TTL so get_stale() can still
# degrade to a last-known value - which is what L1 does by retaining expired
# entries rather than deleting them.
STALE_FACTOR = float(os.environ.get("REDIS_STALE_FACTOR", "12"))


class RedisL2:
    """A cache tier over Redis that fails quietly and never blocks a request.

    Three deliberate choices:

    * **JSON, not pickle.** A pickle read from a shared store is a
      deserialisation hole: anything able to write to the keyspace can run code
      in this process. JSON cannot. The cost is that values which do not
      survive a JSON round trip are simply not cached here (they still cache in
      L1); `stats()` counts them, so it is visible rather than silent.
    * **A circuit breaker.** Without one a dead Redis adds a connect timeout to
      every cache miss - slower than having no cache at all. After `_TRIP`
      consecutive failures it stands down for `_COOLDOWN` seconds.
    * **Readable keys.** `monsoon:v1:bars:<sha1>` rather than a bare digest, so
      `redis-cli --scan --pattern 'monsoon:v1:bars:*'` is useful. The digest
      covers the whole key tuple, so distinct tuples cannot collide the way a
      naive ":".join lets ("a","b:c") and ("a:b","c") collide.
    """

    _TRIP = 3
    _COOLDOWN = 30.0

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Any = None
        self._fails = 0
        self._blocked_until = 0.0
        self.hits = self.misses = self.writes = 0
        self.unserialisable = 0
        self.errors = 0
        self.last_error = ""

    # ── plumbing ──
    def paused(self) -> bool:
        return time.time() < self._blocked_until

    def _trouble(self, e: Exception) -> None:
        self.errors += 1
        self.last_error = f"{type(e).__name__}: {e}"[:160]
        self._fails += 1
        if self._fails >= self._TRIP:
            self._blocked_until = time.time() + self._COOLDOWN
            self._client = None
            log.warning("redis cache unreachable, pausing %.0fs (%s)",
                        self._COOLDOWN, self.last_error)

    async def client(self) -> Any:
        if self._client is None:
            import redis.asyncio as aioredis          # imported only when used
            self._client = aioredis.from_url(
                self._url, decode_responses=True,
                socket_timeout=0.25, socket_connect_timeout=0.25)
        return self._client

    @staticmethod
    def key(key: Hashable) -> str:
        parts = key if isinstance(key, tuple) else (key,)
        label = re.sub(r"[^A-Za-z0-9_.-]", "_", str(parts[0]))[:32]
        digest = hashlib.sha1(
            json.dumps([str(p) for p in parts], separators=(",", ":")).encode()
        ).hexdigest()[:20]
        return f"{REDIS_PREFIX}:{label}:{digest}"

    # ── the two operations cached() needs ──
    async def get(self, key: Hashable) -> tuple[Any, bool] | None:
        """(value, is_stale), or None when there is nothing usable."""
        if self.paused():
            return None
        try:
            raw = await (await self.client()).get(self.key(key))
            self._fails = 0
        except Exception as e:
            self._trouble(e)
            return None
        if not raw:
            self.misses += 1
            return None
        try:
            env = json.loads(raw)
            self.hits += 1
            return env["v"], time.time() > env["e"]
        except Exception:
            self.misses += 1
            return None

    async def set(self, key: Hashable, val: Any, ttl: float) -> None:
        if self.paused():
            return
        try:
            # Strict on purpose: no default=str. A value that needed coercing
            # would come back a different shape than it went in, and a cache
            # that quietly changes types is worse than a cache miss.
            blob = json.dumps({"e": time.time() + ttl, "v": val},
                              separators=(",", ":"), allow_nan=False)
        except (TypeError, ValueError):
            self.unserialisable += 1
            return
        try:
            await (await self.client()).set(
                self.key(key), blob, ex=max(1, int(ttl * STALE_FACTOR)))
            self.writes += 1
            self._fails = 0
        except Exception as e:
            self._trouble(e)

    def stats(self) -> dict[str, Any]:
        return {"backend": "redis", "prefix": REDIS_PREFIX,
                "hits": self.hits, "misses": self.misses, "writes": self.writes,
                "not_json": self.unserialisable, "errors": self.errors,
                "paused": self.paused(),
                **({"last_error": self.last_error} if self.last_error else {})}


L2: RedisL2 | None = RedisL2(REDIS_URL) if REDIS_URL else None


def cache_stats() -> dict[str, Any]:
    """What /api/health reports, so "is Redis actually in use" is answerable
    without reading the config."""
    return {**CACHE.stats(), "l2": L2.stats() if L2 else {"backend": "none"}}


async def coalesce(key: Hashable, factory: Callable[[], Awaitable[Any]]) -> Any:
    """Concurrent callers for the same key await one shared task."""
    task = _inflight.get(key)
    if task is None:
        task = asyncio.ensure_future(factory())
        _inflight[key] = task
        try:
            return await task
        finally:
            _inflight.pop(key, None)
    return await task


async def cached(key: Hashable, ttl: float, factory: Callable[[], Awaitable[Any]],
                 serve_stale: bool = True) -> tuple[Any, bool]:
    """Returns (value, is_stale). Falls back to stale data if the fetch fails.

    The only place TTL caching happens, which is why Redis slots in here and
    nowhere else: every caller keeps calling this exactly as before.
    """
    hit = CACHE.get(key)
    if hit is not None:
        return hit, False

    # L2: a restart or a sibling worker may already have this
    if L2 is not None:
        found = await L2.get(key)
        if found is not None:
            val, expired = found
            if not expired:
                CACHE.set(key, val, ttl)       # promote, so the next read is local
                return val, False
            # expired in L2: fall through and refetch, but remember it so a
            # failed fetch can still degrade to it below
            CACHE.set(key, val, 0)

    try:
        val = await coalesce(key, factory)
        CACHE.set(key, val, ttl)
        if L2 is not None:
            await L2.set(key, val, ttl)
        return val, False
    except Exception:
        if serve_stale:
            stale = CACHE.get_stale(key)
            if stale is not None:
                return stale, True
        raise


class BatchLoader:
    """Collects keys requested within `window` seconds, issues ONE batched call.

    This is what makes a 20-ticker watchlist cost 1 HTTP request while each
    tool still calls quote("NVDA") as if it were a single fetch.
    """

    def __init__(self, fn: Callable[[list[str]], Awaitable[dict[str, Any]]],
                 window: float = 0.015, max_batch: int = 100) -> None:
        self._fn, self._window, self._max = fn, window, max_batch
        self._pending: dict[str, asyncio.Future] = {}
        self._timer: asyncio.Task | None = None
        self.batches = 0          # observability: how many upstream calls we made
        self.keys_served = 0

    async def load(self, key: str) -> Any:
        fut = self._pending.get(key)
        if fut is None:
            fut = asyncio.get_running_loop().create_future()
            self._pending[key] = fut
        if self._timer is None or self._timer.done():
            self._timer = asyncio.ensure_future(self._flush_soon())
        return await fut

    async def load_many(self, keys: Iterable[str]) -> dict[str, Any]:
        ks = list(keys)
        out = await asyncio.gather(*(self.load(k) for k in ks), return_exceptions=True)
        return {k: (None if isinstance(v, Exception) else v) for k, v in zip(ks, out)}

    async def _flush_soon(self) -> None:
        await asyncio.sleep(self._window)
        pending, self._pending = self._pending, {}
        if not pending:
            return
        keys = list(pending)[: self._max]
        overflow = list(pending)[self._max:]
        try:
            self.batches += 1
            self.keys_served += len(keys)
            res = await self._fn(keys)
            for k in keys:
                if not pending[k].done():
                    pending[k].set_result(res.get(k))
        except Exception as e:
            for k in keys:
                if not pending[k].done():
                    pending[k].set_exception(e)
        for k in overflow:                    # re-queue anything past max_batch
            self._pending[k] = pending[k]
        if self._pending:
            self._timer = asyncio.ensure_future(self._flush_soon())
