"""Tests for issue #629 — config-gated semantic auto-link on ingest.

PR #495 shipped the semantic-link primitive (mechanism #2:
``distillery_find_similar(accept_action="link", exclude_linked=true)``).
Issue #629 wires that primitive into the write path so newly stored / polled
entries automatically gain ``related`` edges to their embedding-neighbours
above a configurable threshold — OFF by default.

These tests exercise the store-level hook directly (``store`` / ``store_batch``,
which the feed poller calls) using the 8-dimensional ``ControlledEmbeddingProvider``
so cosine similarity is reproducible.

Acceptance covered:
  * flag ON  → a newly stored entry gains ``related`` edges to semantic
    neighbours above threshold.
  * flag OFF → NO semantic edges created (current behaviour preserved).
  * re-running ingest is idempotent (no duplicate edges).
  * the throttle cap (``max_links``) is respected.
  * feed poll-ingest (FeedPoller → store) inherits auto-link (R1.2).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import pytest

from distillery.store.duckdb import DuckDBStore
from tests.conftest import ControlledEmbeddingProvider, make_entry

pytestmark = pytest.mark.unit


# Two registered 8D vectors: identical → cosine 1.0 (normalised 1.0, well above
# the 0.85 threshold), and orthogonal → cosine 0.0 (normalised 0.5, below it).
_NEAR = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
_FAR = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


@pytest.fixture
async def auto_link_store(
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> AsyncIterator[DuckDBStore]:
    """In-memory store with semantic auto-link ENABLED (threshold 0.85, cap 5)."""
    s = DuckDBStore(
        db_path=":memory:",
        embedding_provider=controlled_embedding_provider,
        auto_link_enabled=True,
        auto_link_threshold=0.85,
        auto_link_max_links=5,
    )
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
async def no_auto_link_store(
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> AsyncIterator[DuckDBStore]:
    """In-memory store with auto-link at its DEFAULT (disabled)."""
    s = DuckDBStore(
        db_path=":memory:",
        embedding_provider=controlled_embedding_provider,
    )
    await s.initialize()
    yield s
    await s.close()


async def test_flag_on_links_to_neighbours_above_threshold(
    auto_link_store: DuckDBStore,
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> None:
    """With the flag on, a stored entry gains 'related' edges to near neighbours only."""
    controlled_embedding_provider.register("source", _NEAR)
    controlled_embedding_provider.register("near one", _NEAR)
    controlled_embedding_provider.register("near two", _NEAR)
    controlled_embedding_provider.register("far one", _FAR)

    n1 = await auto_link_store.store(make_entry(content="near one"))
    n2 = await auto_link_store.store(make_entry(content="near two"))
    await auto_link_store.store(make_entry(content="far one"))

    src_id = await auto_link_store.store(make_entry(content="source"))

    rows = await auto_link_store.get_related(src_id, direction="outgoing")
    to_ids = {r["to_id"] for r in rows}
    # Only the two near (cosine 1.0) neighbours are linked; the orthogonal one
    # (normalised 0.5 < 0.85) is excluded.
    assert to_ids == {n1, n2}
    assert {r["relation_type"] for r in rows} == {"related"}


async def test_flag_off_creates_no_semantic_edges(
    no_auto_link_store: DuckDBStore,
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> None:
    """With the flag off (default), no semantic edges are created — current behaviour."""
    controlled_embedding_provider.register("source", _NEAR)
    controlled_embedding_provider.register("near one", _NEAR)

    await no_auto_link_store.store(make_entry(content="near one"))
    src_id = await no_auto_link_store.store(make_entry(content="source"))

    rows = await no_auto_link_store.get_related(src_id, direction="outgoing")
    assert rows == []
    # And the relations table itself is empty (no incoming edges either).
    total = no_auto_link_store.connection.execute("SELECT COUNT(*) FROM entry_relations").fetchone()
    assert total is not None and total[0] == 0


async def test_auto_link_is_idempotent_on_re_store(
    auto_link_store: DuckDBStore,
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> None:
    """Re-running the auto-link path over an already-linked entry adds no duplicates."""
    controlled_embedding_provider.register("source", _NEAR)
    controlled_embedding_provider.register("near one", _NEAR)

    n1 = await auto_link_store.store(make_entry(content="near one"))
    src_id = await auto_link_store.store(make_entry(content="source"))

    rows_before = await auto_link_store.get_related(src_id, direction="outgoing")
    assert {r["to_id"] for r in rows_before} == {n1}
    assert len(rows_before) == 1

    # Re-run the hook directly (simulates re-ingest of the same entry) — the
    # unique (from_id, to_id, relation_type) index plus the exclude-linked
    # filter make it a no-op.
    embedding = controlled_embedding_provider.embed("source")
    inserted = await auto_link_store._run_sync(
        auto_link_store._auto_link_semantic,
        auto_link_store.connection,
        src_id,
        embedding,
    )
    assert inserted == 0

    rows_after = await auto_link_store.get_related(src_id, direction="outgoing")
    assert len(rows_after) == 1


async def test_auto_link_skips_targets_linked_in_any_direction_or_type(
    auto_link_store: DuckDBStore,
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> None:
    """exclude_linked matches the shipped primitive: incoming + non-``related`` edges suppress.

    The shipped ``find_similar(exclude_linked=true)`` primitive
    (mcp/tools/search.py) excludes any neighbour already linked to the source in
    *either direction* via *any relation_type* (it calls
    ``get_related(direction="both")`` with no relation_type filter). The
    write-path hook must not be more permissive than that primitive.
    """
    controlled_embedding_provider.register("source", _NEAR)
    controlled_embedding_provider.register("incoming nbr", _NEAR)
    controlled_embedding_provider.register("typed nbr", _NEAR)
    controlled_embedding_provider.register("fresh nbr", _NEAR)

    # Seed entries + edges with the hook disabled so the only auto-link run is
    # the one under test (otherwise each store() would link everything eagerly).
    auto_link_store._auto_link_enabled = False
    incoming = await auto_link_store.store(make_entry(content="incoming nbr"))
    typed = await auto_link_store.store(make_entry(content="typed nbr"))
    fresh = await auto_link_store.store(make_entry(content="fresh nbr"))
    src_id = await auto_link_store.store(make_entry(content="source"))

    # Pre-seed edges that the *narrow* (outgoing-``related``-only) filter would
    # have missed: an INCOMING ``related`` edge and an outgoing non-``related``
    # ("link") edge. Both must suppress an auto-link to that target.
    await auto_link_store.add_relation(incoming, src_id, "related")
    await auto_link_store.add_relation(src_id, typed, "link")
    auto_link_store._auto_link_enabled = True

    embedding = controlled_embedding_provider.embed("source")
    inserted = await auto_link_store._run_sync(
        auto_link_store._auto_link_semantic,
        auto_link_store.connection,
        src_id,
        embedding,
    )

    # Only the un-linked ``fresh`` neighbour gets a new ``related`` edge.
    assert inserted == 1
    outgoing_related = {
        r["to_id"]
        for r in await auto_link_store.get_related(src_id, direction="outgoing")
        if r["relation_type"] == "related"
    }
    assert outgoing_related == {fresh}
    assert incoming not in outgoing_related
    assert typed not in outgoing_related


async def test_auto_link_respects_max_links_cap(
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> None:
    """The throttle caps edges per entry at auto_link_max_links."""
    s = DuckDBStore(
        db_path=":memory:",
        embedding_provider=controlled_embedding_provider,
        auto_link_enabled=True,
        auto_link_threshold=0.85,
        auto_link_max_links=2,
    )
    await s.initialize()
    try:
        controlled_embedding_provider.register("source", _NEAR)
        # Five near neighbours, all above threshold — but the cap is 2.
        for i in range(5):
            controlled_embedding_provider.register(f"near {i}", _NEAR)
            await s.store(make_entry(content=f"near {i}"))

        src_id = await s.store(make_entry(content="source"))

        rows = await s.get_related(src_id, direction="outgoing")
        assert len(rows) == 2
        assert {r["relation_type"] for r in rows} == {"related"}
    finally:
        await s.close()


async def test_store_batch_auto_links_each_entry(
    auto_link_store: DuckDBStore,
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> None:
    """store_batch links each batched entry to a pre-existing near neighbour."""
    controlled_embedding_provider.register("anchor", _NEAR)
    controlled_embedding_provider.register("b1", _NEAR)
    controlled_embedding_provider.register("b2", _NEAR)

    anchor_id = await auto_link_store.store(make_entry(content="anchor"))

    e1 = make_entry(content="b1")
    e2 = make_entry(content="b2")
    [e1_id, e2_id] = await auto_link_store.store_batch([e1, e2])

    rows1 = await auto_link_store.get_related(e1_id, direction="outgoing")
    rows2 = await auto_link_store.get_related(e2_id, direction="outgoing")
    # Each batched entry links to the anchor (and to its in-batch sibling, which
    # is visible via the in-flight transactional view).
    assert anchor_id in {r["to_id"] for r in rows1}
    assert anchor_id in {r["to_id"] for r in rows2}
    assert {r["relation_type"] for r in rows1} == {"related"}
    assert {r["relation_type"] for r in rows2} == {"related"}


async def test_default_config_enables_auto_link(
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> None:
    """Store instantiated with defaults (no args) has auto_link enabled (edge-by-default)."""
    controlled_embedding_provider.register("source", _NEAR)
    controlled_embedding_provider.register("near one", _NEAR)

    # Instantiate with no explicit auto_link arguments — should use defaults
    # from DuckDBStore.__init__ signature (auto_link_enabled=False param default).
    # However, the config module now defaults AutoLinkConfig.enabled to True,
    # and when a config is loaded (or created with defaults), the server passes
    # enabled=True to DuckDBStore. This test verifies that default-construction
    # preserves backwards-compat: no args → enabled=False (store layer default).
    # But when created via config (the production path), enabled=True (config default).

    # For this test, we verify the store-level default (no args) is still False
    # to ensure we don't break stateless unit tests that rely on the old behaviour.
    default_store = DuckDBStore(
        db_path=":memory:",
        embedding_provider=controlled_embedding_provider,
    )
    await default_store.initialize()
    try:
        # Verify the store-level default is still False (for test compatibility)
        assert default_store._auto_link_enabled is False
    finally:
        await default_store.close()

    # But when config loads with defaults, it now returns enabled=True
    from distillery.config import AutoLinkConfig

    cfg = AutoLinkConfig()
    assert cfg.enabled is True


async def test_config_default_enabled_true_creates_edges(
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> None:
    """With config default (enabled=True), a store created via config creates edges."""
    controlled_embedding_provider.register("source", _NEAR)
    controlled_embedding_provider.register("near one", _NEAR)

    # Simulate what the MCP server does: load config (which now defaults
    # enabled=True), then pass it to DuckDBStore.
    from distillery.config import AutoLinkConfig

    cfg = AutoLinkConfig()
    assert cfg.enabled is True

    # Create store with config-provided value
    store = DuckDBStore(
        db_path=":memory:",
        embedding_provider=controlled_embedding_provider,
        auto_link_enabled=cfg.enabled,
        auto_link_threshold=cfg.threshold,
        auto_link_max_links=cfg.max_links,
    )
    await store.initialize()
    try:
        n1 = await store.store(make_entry(content="near one"))
        src_id = await store.store(make_entry(content="source"))

        rows = await store.get_related(src_id, direction="outgoing")
        to_ids = {r["to_id"] for r in rows}
        assert to_ids == {n1}
        assert {r["relation_type"] for r in rows} == {"related"}
    finally:
        await store.close()


async def test_config_default_disabled_creates_no_edges(
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> None:
    """With config.enabled=False (kill switch), no edges are created."""
    controlled_embedding_provider.register("source", _NEAR)
    controlled_embedding_provider.register("near one", _NEAR)

    # Load config and explicitly disable auto_link (the kill switch)
    from distillery.config import AutoLinkConfig

    cfg = AutoLinkConfig()
    cfg.enabled = False

    store = DuckDBStore(
        db_path=":memory:",
        embedding_provider=controlled_embedding_provider,
        auto_link_enabled=cfg.enabled,
        auto_link_threshold=cfg.threshold,
        auto_link_max_links=cfg.max_links,
    )
    await store.initialize()
    try:
        await store.store(make_entry(content="near one"))
        src_id = await store.store(make_entry(content="source"))

        rows = await store.get_related(src_id, direction="outgoing")
        assert rows == []

        total = store.connection.execute("SELECT COUNT(*) FROM entry_relations").fetchone()
        assert total is not None and total[0] == 0
    finally:
        await store.close()


async def test_feed_poll_ingest_auto_links(
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> None:
    """R1.2: auto-link fires on the feed poll-ingest path (FeedPoller → store.store).

    FeedPoller calls ``self._store.store(entry)`` for each accepted feed item,
    which is the same write path exercised by the direct ``store()`` tests.
    This test wires a real DuckDBStore (auto-link ON) to a FeedPoller whose
    adapter is replaced by a stub so no network calls are made.  After a
    successful poll the ingested entry must have a ``related`` edge to the
    pre-existing near-neighbour.
    """
    from distillery.config import (
        DistilleryConfig,
        FeedsConfig,
        FeedSourceConfig,
        FeedsThresholdsConfig,
    )
    from distillery.feeds.models import FeedItem
    from distillery.feeds.poller import FeedPoller

    # The feed item text and the pre-existing neighbour share the same _NEAR
    # vector so cosine similarity is 1.0 (normalised 1.0 > threshold 0.85).
    feed_text = "feed item near content"
    controlled_embedding_provider.register("pre-existing near", _NEAR)
    controlled_embedding_provider.register(feed_text, _NEAR)

    store = DuckDBStore(
        db_path=":memory:",
        embedding_provider=controlled_embedding_provider,
        auto_link_enabled=True,
        auto_link_threshold=0.85,
        auto_link_max_links=5,
    )
    await store.initialize()
    try:
        # Register a feed source so the poller has something to poll.
        source_url = "https://example.com/rss"
        await store.add_feed_source(
            url=source_url,
            source_type="rss",
            poll_interval_minutes=60,
        )

        # Pre-populate the near-neighbour AFTER the store is initialised so
        # its vector is already in the HNSW index when the poller runs.
        neighbour_id = await store.store(make_entry(content="pre-existing near"))

        # Stub the adapter so no network I/O occurs.
        feed_item = FeedItem(
            source_url=source_url,
            source_type="rss",
            item_id="poll-item-1",
            title=None,
            content=feed_text,
        )
        mock_adapter = MagicMock()
        mock_adapter.fetch.return_value = [feed_item]

        # digest threshold 0.0 ensures the item is stored regardless of its
        # relevance score (score >= 0.0 always holds).
        cfg = DistilleryConfig()
        cfg.feeds = FeedsConfig(
            sources=[FeedSourceConfig(url=source_url, source_type="rss")],
            thresholds=FeedsThresholdsConfig(alert=0.85, digest=0.0),
        )

        with patch("distillery.feeds.poller._build_adapter", return_value=mock_adapter):
            poller = FeedPoller(store=store, config=cfg, relevance_threshold=0.0)
            summary = await poller.poll()

        assert summary.total_stored == 1, (
            f"Expected 1 item stored, got {summary.total_stored}; "
            f"errors: {[r.errors for r in summary.results]}"
        )

        # Find the newly stored feed entry.
        all_entries = await store.list_entries(
            filters={"metadata.external_id": "poll-item-1"}, limit=1, offset=0
        )
        assert len(all_entries) == 1, "Polled entry not found in store"
        polled_id = str(all_entries[0].id)

        # The polled entry must be linked to the pre-existing near-neighbour.
        rows = await store.get_related(polled_id, direction="outgoing")
        to_ids = {r["to_id"] for r in rows}
        assert neighbour_id in to_ids, (
            f"Expected auto-link edge from polled entry to neighbour {neighbour_id}; "
            f"got outgoing edges: {to_ids}"
        )
        assert {r["relation_type"] for r in rows} == {"related"}
    finally:
        await store.close()
