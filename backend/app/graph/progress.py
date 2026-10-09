"""Live progress from inside the graph.

LangGraph's update stream only speaks when a node FINISHES, and a specialist is
one node wrapping a whole subgraph - so for 10-30 seconds the reader saw a chip
that said "working" and nothing else. Nodes call emit() as each step starts
(router reading, a specialist picking tools, fetching them, writing up, the
writer drafting, the figure check) and the streaming route forwards those as
they happen.

The sink is a context variable: the route sets it before starting the graph,
the graph's tasks inherit it, and anything run outside a streaming request -
the plain /ask endpoint, the evals - has no sink, so emit() costs nothing.
"""
from __future__ import annotations
import time
from contextvars import ContextVar
from typing import Any, Callable

_sink: ContextVar[Callable[[dict], None] | None] = ContextVar("progress_sink", default=None)


def emit(step: str, **data: Any) -> None:
    f = _sink.get()
    if f is None:
        return
    try:
        f({"step": step, "t": round(time.time(), 3), **data})
    except Exception:
        pass                      # progress is a nicety; it must never break a run


def attach(fn: Callable[[dict], None]):
    """Route a run's progress to `fn`. Returns the token to detach with."""
    return _sink.set(fn)


def detach(token) -> None:
    _sink.reset(token)
