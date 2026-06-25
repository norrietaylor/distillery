"""Tests for the write-path tag canonicalization choke-point (issue #653).

Phase 1 backfilled existing tags one-time; this is the complementary guarantee
that *new* writes stay canonical. Every entry persisted through the store
(store / store_batch / update) has its tags run through the configured controlled
vocabulary, so the graph cannot silently re-fragment as new feed items arrive.

The choke-point is configured via the DuckDBStore constructor; tests set the
private attributes directly on the in-memory fixture store to exercise the same
code path without standing up a second store.
"""

from __future__ import annotations

import pytest

from tests.conftest import make_entry

pytestmark = pytest.mark.unit

_ALIASES = {"domain/sandbox": "domain/build/sandboxing"}


async def test_store_canonicalizes_tags(store) -> None:  # type: ignore[no-untyped-def]
    store._tag_aliases = _ALIASES
    e = make_entry(content="x", tags=["domain/sandbox", "tech/duckdb"])
    await store.store(e)

    got = await store.get(e.id)
    assert set(got.tags) == {"domain/build/sandboxing", "tech/duckdb"}


async def test_store_dedupes_alias_and_target(store) -> None:  # type: ignore[no-untyped-def]
    """An entry carrying both an alias and its canonical target collapses to one."""
    store._tag_aliases = _ALIASES
    e = make_entry(content="x", tags=["domain/sandbox", "domain/build/sandboxing"])
    await store.store(e)

    got = await store.get(e.id)
    assert got.tags == ["domain/build/sandboxing"]


async def test_store_batch_canonicalizes(store) -> None:  # type: ignore[no-untyped-def]
    store._tag_aliases = _ALIASES
    e1 = make_entry(content="a", tags=["domain/sandbox"])
    e2 = make_entry(content="b", tags=["tech/duckdb"])
    await store.store_batch([e1, e2])

    assert (await store.get(e1.id)).tags == ["domain/build/sandboxing"]
    assert (await store.get(e2.id)).tags == ["tech/duckdb"]


async def test_update_canonicalizes_and_returns_canonical(store) -> None:  # type: ignore[no-untyped-def]
    """update() canonicalizes the new tags AND the returned Entry reflects them."""
    store._tag_aliases = _ALIASES
    e = make_entry(content="x", tags=["tech/duckdb"])
    await store.store(e)

    updated = await store.update(e.id, {"tags": ["domain/sandbox", "tech/duckdb"]})
    assert set(updated.tags) == {"domain/build/sandboxing", "tech/duckdb"}
    # And it is what was persisted.
    assert set((await store.get(e.id)).tags) == {"domain/build/sandboxing", "tech/duckdb"}


async def test_inert_by_default_preserves_tags(store) -> None:  # type: ignore[no-untyped-def]
    """With no alias map and no namespace normalization, tags are stored verbatim."""
    e = make_entry(content="x", tags=["domain/sandbox", "tech/duckdb"])
    await store.store(e)

    got = await store.get(e.id)
    assert got.tags == ["domain/sandbox", "tech/duckdb"]


async def test_namespace_normalization_on_write(store) -> None:  # type: ignore[no-untyped-def]
    """When configured, separator variants of a reserved-prefix tag collapse on write."""
    store._tag_normalize_namespaces = True
    store._tag_reserved_prefixes = ["entity"]
    e = make_entry(content="x", tags=["entity/cloudflare/workers"])
    await store.store(e)

    got = await store.get(e.id)
    assert got.tags == ["entity/cloudflare-workers"]
