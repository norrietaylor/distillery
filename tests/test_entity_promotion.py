"""Unit tests for DuckDBStore.promote_entities() (spec 17, Unit 2).

Covers:
  - promote_entities creates exactly one entity node per qualifying canonical
    tag and a ``mentions`` edge from every tagged entry to it (R2.1-R2.3).
  - tag variants collapse to one node via the normalize_tag path (R2.5).
  - tags below the frequency threshold are not promoted (R2.1).
  - promote_entities is idempotent: a second consecutive run inserts zero new
    nodes and zero new edges (R2.2/R2.3).
  - concurrent deletion: if a node's embedding is absent from the plan-time
    dict (simulating a node created then deleted between plan and write), the
    write pass skips without raising KeyError (regression for issue #653).
"""

from __future__ import annotations

import pytest

from distillery.models import EntryType
from tests.conftest import make_entry

pytestmark = pytest.mark.unit


async def _store_entry(store, **kwargs):  # type: ignore[no-untyped-def]
    """Store an entry with the given kwargs and return its id."""
    entry = make_entry(**kwargs)
    await store.store(entry)
    return entry.id


async def test_promote_entities_creates_node_and_mentions(store) -> None:  # type: ignore[no-untyped-def]
    """At-threshold tag yields one entity node and one mentions edge per entry."""
    ids = [
        await _store_entry(store, content=f"entry {i}", tags=["entity/cloudflare"])
        for i in range(3)
    ]

    counts = await store.promote_entities(threshold=3)

    assert counts["entities_created"] == 1
    assert counts["entities_reused"] == 0
    assert counts["mentions_created"] == 3

    nodes = await store.list_entries({"entry_type": EntryType.ENTITY.value}, limit=10, offset=0)
    assert len(nodes) == 1
    node = nodes[0]
    assert node.metadata["source_tag"] == "entity/cloudflare"

    # Every seeded entry now has a mentions edge to the single node.
    for entry_id in ids:
        related = await store.get_related(entry_id, relation_type="mentions")
        assert len(related) == 1
        assert related[0]["to_id"] == node.id
        assert related[0]["from_id"] == entry_id


async def test_promote_entities_collapses_tag_variants(store) -> None:  # type: ignore[no-untyped-def]
    """entity/cloudflare/workers and entity/cloudflare-workers map to one node."""
    a = await _store_entry(store, content="slashed", tags=["entity/cloudflare/workers"])
    b = await _store_entry(store, content="hyphenated", tags=["entity/cloudflare-workers"])
    c = await _store_entry(store, content="slashed too", tags=["entity/cloudflare/workers"])

    counts = await store.promote_entities(threshold=3)

    assert counts["entities_created"] == 1
    assert counts["mentions_created"] == 3

    nodes = await store.list_entries({"entry_type": EntryType.ENTITY.value}, limit=10, offset=0)
    assert len(nodes) == 1
    assert nodes[0].metadata["source_tag"] == "entity/cloudflare-workers"

    for entry_id in (a, b, c):
        related = await store.get_related(entry_id, relation_type="mentions")
        assert len(related) == 1
        assert related[0]["to_id"] == nodes[0].id


async def test_promote_entities_below_threshold_skipped(store) -> None:  # type: ignore[no-untyped-def]
    """A tag on fewer than threshold entries is not promoted."""
    await _store_entry(store, content="one", tags=["tech/duckdb"])
    await _store_entry(store, content="two", tags=["tech/duckdb"])

    counts = await store.promote_entities(threshold=3)

    assert counts["entities_created"] == 0
    assert counts["mentions_created"] == 0
    nodes = await store.list_entries({"entry_type": EntryType.ENTITY.value}, limit=10, offset=0)
    assert nodes == []


async def test_promote_entities_is_idempotent(store) -> None:  # type: ignore[no-untyped-def]
    """A second consecutive run inserts zero nodes and zero edges."""
    for i in range(3):
        await _store_entry(store, content=f"e{i}", tags=["entity/datadog"])

    first = await store.promote_entities(threshold=3)
    assert first["entities_created"] == 1
    assert first["mentions_created"] == 3

    second = await store.promote_entities(threshold=3)
    assert second["entities_created"] == 0
    assert second["entities_reused"] == 1
    assert second["mentions_created"] == 0

    nodes = await store.list_entries({"entry_type": EntryType.ENTITY.value}, limit=10, offset=0)
    assert len(nodes) == 1


async def test_promote_entities_missing_embedding_does_not_raise(store) -> None:  # type: ignore[no-untyped-def]
    """Regression: missing embedding (concurrent deletion) is skipped, not KeyError.

    Simulates the race where a node existed at plan time, was deleted between
    plan and write, so its embedding was never computed.  The write pass must
    skip gracefully rather than raising KeyError.
    """
    for i in range(3):
        await _store_entry(store, content=f"concurrent {i}", tags=["entity/acme"])

    # Obtain the canonical set by calling the plan step, then strip the
    # embedding so the write step sees the concurrent-deletion scenario.
    canonical_members, _ = await store._run_sync(
        store._sync_promote_entities_plan, 3, ["entity", "tech"]
    )
    # Deliberately omit the embedding for "entity/acme" to reproduce the race.
    empty_embeddings: dict[str, list[float]] = {}

    # Must not raise KeyError.
    result = await store._run_sync(
        store._sync_promote_entities_write, canonical_members, empty_embeddings
    )

    # The canonical was skipped — no entity node created in this pass.
    assert result["entities_created"] == 0
    assert result["entities_reused"] == 0
    nodes = await store.list_entries({"entry_type": EntryType.ENTITY.value}, limit=10, offset=0)
    assert nodes == []
