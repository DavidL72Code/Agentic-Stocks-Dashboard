"""TTL cache + in-flight coalescing + DataLoader-style batching.

Three separate jobs:
  TTLCache   - don't refetch what we already have
  coalesce   - N concurrent callers asking for the same key => 1 upstream call
  BatchLoader- N concurrent callers asking for DIFFERENT keys of the same kind
               => 1 batched upstream call (the v7/quote win)
"""
from __future__ import annotations
import asyncio, time
from typing import Any, Awaitable, Callable, Hashable, Iterable


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
    """Returns (value, is_stale). Falls back to stale data if the fetch fails."""
    hit = CACHE.get(key)
    if hit is not None:
        return hit, False
    try:
        val = await coalesce(key, factory)
        CACHE.set(key, val, ttl)
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
