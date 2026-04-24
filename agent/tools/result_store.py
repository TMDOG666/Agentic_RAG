"""In-memory store for large tool results referenced by lightweight ids."""

from __future__ import annotations

from threading import Lock
from typing import Any


class InMemoryResultStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._items: dict[str, Any] = {}

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[key] = value

    def get(self, key: str) -> Any | None:
        with self._lock:
            return self._items.get(key)


_STORE = InMemoryResultStore()


def get_result_store() -> InMemoryResultStore:
    return _STORE
