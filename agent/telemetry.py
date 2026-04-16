from __future__ import annotations

import contextlib
import contextvars
from typing import Any, Callable


_event_sink_var: contextvars.ContextVar[Callable[[dict[str, Any]], None] | None] = contextvars.ContextVar(
    "agent_event_sink",
    default=None,
)


@contextlib.contextmanager
def bind_event_sink(sink: Callable[[dict[str, Any]], None] | None):
    token = _event_sink_var.set(sink)
    try:
        yield
    finally:
        _event_sink_var.reset(token)


def emit_event(event_type: str, payload: dict[str, Any] | None = None) -> None:
    sink = _event_sink_var.get()
    if sink is None:
        return
    body = {"type": str(event_type)}
    if payload:
        body.update(payload)
    sink(body)
