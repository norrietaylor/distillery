"""Tests for distillery.graph.cache.

These tests do not depend on the [graph] extra (NetworkX) — they exercise the
TTLCache primitive directly.
"""

from __future__ import annotations

import pytest

from distillery.graph.cache import TTLCache

pytestmark = pytest.mark.unit


def test_cache_evicts_expired_entries_proactively(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Calling set() after the TTL elapses should drop every stale key, not just
    the one being touched. Prevents high-cardinality one-off keys from
    accumulating forever (CodeRabbit, PR #426).
    """
    cache = TTLCache(ttl_seconds=10)

    fake_now = {"t": 100.0}

    def _now() -> float:
        return fake_now["t"]

    # Patch the monotonic clock used by the cache.
    monkeypatch.setattr("distillery.graph.cache.time.monotonic", _now)

    # Populate many keys at t=100.
    for i in range(50):
        cache.set(f"key-{i}", i)
    assert len(cache._store) == 50

    # Advance well past the TTL.
    fake_now["t"] = 200.0

    # A single set() call must trigger a full sweep of expired entries.
    cache.set("fresh", "value")

    assert "fresh" in cache._store
    for i in range(50):
        assert f"key-{i}" not in cache._store, "stale keys should have been evicted"
    assert len(cache._store) == 1


def test_cache_get_also_evicts_expired_entries(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """get() must also sweep expired keys so a long stretch of misses cannot
    leak unbounded memory."""
    cache = TTLCache(ttl_seconds=10)

    fake_now = {"t": 0.0}

    def _now() -> float:
        return fake_now["t"]

    monkeypatch.setattr("distillery.graph.cache.time.monotonic", _now)

    for i in range(20):
        cache.set(f"k{i}", i)
    assert len(cache._store) == 20

    fake_now["t"] = 100.0
    # Looking up an unrelated missing key must still purge the expired ones.
    assert cache.get("does-not-exist") is None
    assert len(cache._store) == 0


def test_cache_returns_value_within_ttl(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Sanity check: values stored within the TTL window are returned by get()."""
    cache = TTLCache(ttl_seconds=10)

    fake_now = {"t": 0.0}

    def _now() -> float:
        return fake_now["t"]

    monkeypatch.setattr("distillery.graph.cache.time.monotonic", _now)

    cache.set("hello", "world")
    assert cache.get("hello") == "world"

    fake_now["t"] = 5.0  # still within TTL
    assert cache.get("hello") == "world"

    fake_now["t"] = 100.0  # well past TTL
    assert cache.get("hello") is None
