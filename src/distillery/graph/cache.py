"""Tiny TTL cache for graph builds."""

from __future__ import annotations

import time
from typing import Any


class TTLCache:
    """Simple time-to-live cache keyed by string."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > self._ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time(), value)


_default_cache = TTLCache(ttl_seconds=300)


def default_cache() -> TTLCache:
    return _default_cache
