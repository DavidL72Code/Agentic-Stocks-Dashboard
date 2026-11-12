"""Connections that are reused instead of opened for every request.

Every fetch used to build a new client: a fresh httpx.AsyncClient loads the
certificate bundle again, and a fresh connection pays a TLS handshake. A cold
research page made ~56 handshakes and loaded the bundle 9 times. Cheap on a
laptop; on Render's 0.1 CPU those are the most expensive things the server does
besides parsing. Clients here live as long as their event loop (tests run
several loops; a client cannot cross from one to another), and curl_cffi
sessions live one per thread, since a session is not thread-safe.
"""
from __future__ import annotations
import asyncio, contextlib, threading, weakref
from typing import Any

_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, Any]]" = weakref.WeakKeyDictionary()
_tl = threading.local()


def client(name: str, **kw):
    """One httpx.AsyncClient per (event loop, name); keyword args apply on creation."""
    import httpx
    loop = asyncio.get_running_loop()
    per = _clients.setdefault(loop, {})
    c = per.get(name)
    if c is None or c.is_closed:
        kw.setdefault("limits", httpx.Limits(max_connections=20, max_keepalive_connections=10))
        c = per[name] = httpx.AsyncClient(**kw)
    return c


@contextlib.asynccontextmanager
async def shared(name: str, **kw):
    """`async with shared("sec", ...) as c:` - the old call shape, a kept client."""
    yield client(name, **kw)


def session():
    """This thread's curl_cffi session (browser impersonation, keep-alive)."""
    s = getattr(_tl, "s", None)
    if s is None:
        from curl_cffi import requests as cr
        s = _tl.s = cr.Session(impersonate="chrome")
    return s
