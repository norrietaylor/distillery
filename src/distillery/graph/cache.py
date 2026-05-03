"""Tiny TTL cache for graph builds."""

from __future__ import annotations

import time
from typing import Any


class TTLCache:
    """Simple time-to-live cache keyed by string.

    Uses ``time.monotonic()`` to avoid wall-clock jumps and proactively evicts
    expired entries on every ``get()`` and ``set()`` so high-cardinality
    one-off keys do not accumulate forever (CodeRabbit, PR #426).
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}

    def _evict_expired(self, now: float) -> None:
        """Drop every entry whose timestamp is older than the TTL."""
        expired = [k for k, (ts, _) in self._store.items() if now - ts > self._ttl]
        for k in expired:
            self._store.pop(k, None)

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        self._evict_expired(now)
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if now - ts > self._ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        now = time.monotonic()
        self._evict_expired(now)
        self._store[key] = (now, value)


_default_cache = TTLCache(ttl_seconds=300)


def default_cache() -> TTLCache:
    return _default_cache
