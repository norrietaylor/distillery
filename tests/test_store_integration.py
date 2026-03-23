"""End-to-end integration tests for the store -> embed -> search flow.

Uses a real in-memory DuckDB instance (no mocking of the database) with a
mock embedding provider that returns fully deterministic vectors.  This
lets us verify the complete data path from Entry creation through storage,
retrieval, search ranking, and similarity detection.
"""

from __future__ import annotations

import math

import pytest

from distillery.models import Entry, EntrySource, EntryStatus, EntryType
from distillery.store.duckdb import DuckDBStore
from distillery.store.protocol import SearchResult

# ---------------------------------------------------------------------------
# Deterministic mock embedding provider
# ---------------------------------------------------------------------------


class _DeterministicEmbeddingProvider:
    """Embedding provider with predictable, controlled vectors.

    The key insight: we can pre-program per-text embeddings so that we know
    exactly which entries should appear as similar and which should not.

    Texts not found in the registry fall back to a hash-based unit vector.
    """

    _DIMS = 4

    def __init__(self) -> None:
        # Maps text -> fixed unit vector
        self._registry: dict[str, list[float]] = {}

    def register(self, text: str, vector: list[float]) -> None:
        """Register a deterministic vector for a specific text."""
        mag = math.sqrt(sum(x * x for x in vector))
        self._registry[text] = [x / mag for x in vector]

    def _vector_for(self, text: str) -> list[float]:
        if text in self._registry:
            return self._registry[text]
        # Hash-based fallback for texts without explicit registration
        h = hash(text) & 0xFFFFFFFF
        parts = [(h >> (8 * i)) & 0xFF for i in range(self._DIMS)]
        floats = [float(p) + 1.0 for p in parts]
        magnitude = math.sqrt(sum(x * x for x in floats))
        return [x / magnitude for x in floats]

    def embed(self, text: str) -> list[float]:
        return self._vector_for(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for(t) for t in texts]

    @property
    def dimensions(self) -> int:
        return self._DIMS

    @property
    def model_name(self) -> str:
        return "deterministic-4d"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(**kwargs) -> Entry:
    """Return a minimal valid Entry, optionally overriding fields."""
    defaults = {
        "content": "Default content",
        "entry_type": EntryType.INBOX,
        "source": EntrySource.MANUAL,
        "author": "integration-test",
    }
    defaults.update(kwargs)
    return Entry(**defaults)


@pytest.fixture
async def embedding_provider() -> _DeterministicEmbeddingProvider:
    return _DeterministicEmbeddingProvider()


@pytest.fixture
async def store(
    embedding_provider: _DeterministicEmbeddingProvider,
) -> DuckDBStore:  # type: ignore[return]
    """Initialised in-memory DuckDBStore, yielded for test use, then closed."""
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Basic store -> get round trip
# ---------------------------------------------------------------------------


class TestStoreGetRoundTrip:
    async def test_store_and_retrieve_preserves_content(
        self, store: DuckDBStore
    ) -> None:
        entry = _make_entry(content="integration test content")
        entry_id = await store.store(entry)
        fetched = await store.get(entry_id)
        assert fetched is not None
        assert fetched.content == "integration test content"

    async def test_store_and_retrieve_preserves_metadata(
        self, store: DuckDBStore
    ) -> None:
        entry = _make_entry(
            content="entry with metadata",
            metadata={"source_url": "https://example.com", "priority": "high"},
        )
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.metadata["source_url"] == "https://example.com"
        assert fetched.metadata["priority"] == "high"

    async def test_store_and_retrieve_preserves_tags(
        self, store: DuckDBStore
    ) -> None:
        entry = _make_entry(content="tagged entry", tags=["integration", "test", "alpha"])
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert set(fetched.tags) == {"integration", "test", "alpha"}

    async def test_store_and_retrieve_preserves_type(
        self, store: DuckDBStore
    ) -> None:
        entry = _make_entry(content="session entry", entry_type=EntryType.SESSION)
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.entry_type is EntryType.SESSION

    async def test_multiple_entries_independent(self, store: DuckDBStore) -> None:
        """Storing multiple entries does not corrupt individual records."""
        entries = [
            _make_entry(content=f"entry number {i}", author=f"user-{i}")
            for i in range(10)
        ]
        for entry in entries:
            await store.store(entry)

        for entry in entries:
            fetched = await store.get(entry.id)
            assert fetched is not None
            assert fetched.content == entry.content
            assert fetched.author == entry.author


# ---------------------------------------------------------------------------
# Store -> search flow
# ---------------------------------------------------------------------------


class TestStoreSearchFlow:
    async def test_search_returns_stored_entry(
        self,
        store: DuckDBStore,
        embedding_provider: _DeterministicEmbeddingProvider,
    ) -> None:
        """A stored entry is retrievable via semantic search."""
        query = "machine learning"
        # Register identical vector for document and query so it ranks first
        vec = [1.0, 0.0, 0.0, 0.0]
        embedding_provider.register("machine learning knowledge", vec)
        embedding_provider.register(query, vec)

        entry = _make_entry(content="machine learning knowledge")
        await store.store(entry)

        results = await store.search(query, filters=None, limit=10)
        assert isinstance(results, list)
        assert len(results) >= 1
        result_ids = [r.entry.id for r in results]
        assert entry.id in result_ids

    async def test_search_results_have_scores(
        self,
        store: DuckDBStore,
    ) -> None:
        """SearchResult objects must have float scores."""
        entry = _make_entry(content="scored search result")
        await store.store(entry)

        results = await store.search("scored search result", filters=None, limit=5)
        for r in results:
            assert isinstance(r, SearchResult)
            assert isinstance(r.score, float)

    async def test_search_ranks_similar_content_higher(
        self,
        store: DuckDBStore,
        embedding_provider: _DeterministicEmbeddingProvider,
    ) -> None:
        """Content similar to the query should rank above dissimilar content."""
        # "related" content gets a vector close to the query vector
        # "unrelated" content gets an orthogonal vector
        query_vec = [1.0, 0.0, 0.0, 0.0]
        related_vec = [0.9, 0.1, 0.0, 0.0]
        unrelated_vec = [0.0, 0.0, 0.0, 1.0]

        embedding_provider.register("my search query", query_vec)
        embedding_provider.register("related content to query", related_vec)
        embedding_provider.register("completely different topic", unrelated_vec)

        related_entry = _make_entry(content="related content to query")
        unrelated_entry = _make_entry(content="completely different topic")
        await store.store(related_entry)
        await store.store(unrelated_entry)

        results = await store.search("my search query", filters=None, limit=10)
        assert len(results) >= 2

        result_ids = [r.entry.id for r in results]
        related_rank = result_ids.index(related_entry.id)
        unrelated_rank = result_ids.index(unrelated_entry.id)
        assert related_rank < unrelated_rank, (
            f"Related entry (rank {related_rank}) should appear before "
            f"unrelated entry (rank {unrelated_rank})"
        )

    async def test_search_with_entry_type_filter(
        self, store: DuckDBStore
    ) -> None:
        """search() with entry_type filter only returns matching entries."""
        bookmark = _make_entry(
            content="bookmark entry content",
            entry_type=EntryType.BOOKMARK,
        )
        idea = _make_entry(
            content="idea entry content",
            entry_type=EntryType.IDEA,
        )
        await store.store(bookmark)
        await store.store(idea)

        results = await store.search(
            "entry content",
            filters={"entry_type": "bookmark"},
            limit=10,
        )
        for r in results:
            assert r.entry.entry_type is EntryType.BOOKMARK

    async def test_search_with_author_filter(self, store: DuckDBStore) -> None:
        """search() filters by author correctly."""
        alice_entry = _make_entry(content="alice wrote this", author="alice")
        bob_entry = _make_entry(content="bob wrote this", author="bob")
        await store.store(alice_entry)
        await store.store(bob_entry)

        results = await store.search(
            "wrote this", filters={"author": "alice"}, limit=10
        )
        for r in results:
            assert r.entry.author == "alice"

    async def test_search_respects_limit(self, store: DuckDBStore) -> None:
        """search() never returns more entries than the limit."""
        for i in range(10):
            await store.store(_make_entry(content=f"limit test entry {i}"))

        results = await store.search("limit test entry", filters=None, limit=3)
        assert len(results) <= 3


# ---------------------------------------------------------------------------
# find_similar flow
# ---------------------------------------------------------------------------


class TestFindSimilarIntegration:
    async def test_find_similar_identifies_duplicate_content(
        self,
        store: DuckDBStore,
        embedding_provider: _DeterministicEmbeddingProvider,
    ) -> None:
        """find_similar correctly identifies entries with identical content."""
        # Register the same vector for both the original and the duplicate text
        duplicate_vec = [1.0, 0.0, 0.0, 0.0]
        original_text = "This is important knowledge"
        duplicate_text = "This is important knowledge"

        embedding_provider.register(original_text, duplicate_vec)
        embedding_provider.register(duplicate_text, duplicate_vec)

        original_entry = _make_entry(content=original_text)
        await store.store(original_entry)

        # Query with the same content: cosine similarity should be ~1.0
        results = await store.find_similar(
            duplicate_text, threshold=0.9, limit=10
        )
        assert len(results) >= 1
        result_ids = [r.entry.id for r in results]
        assert original_entry.id in result_ids

    async def test_find_similar_threshold_filters_dissimilar(
        self,
        store: DuckDBStore,
        embedding_provider: _DeterministicEmbeddingProvider,
    ) -> None:
        """Entries below the similarity threshold are excluded from results."""
        similar_vec = [1.0, 0.0, 0.0, 0.0]
        dissimilar_vec = [0.0, 0.0, 0.0, 1.0]
        query_vec = [1.0, 0.0, 0.0, 0.0]

        embedding_provider.register("query text for similarity", query_vec)
        embedding_provider.register("very similar content", similar_vec)
        embedding_provider.register("completely unrelated content", dissimilar_vec)

        similar_entry = _make_entry(content="very similar content")
        dissimilar_entry = _make_entry(content="completely unrelated content")
        await store.store(similar_entry)
        await store.store(dissimilar_entry)

        # With a high threshold, only the similar entry should appear
        results = await store.find_similar(
            "query text for similarity", threshold=0.9, limit=10
        )
        result_ids = [r.entry.id for r in results]
        assert similar_entry.id in result_ids
        assert dissimilar_entry.id not in result_ids

    async def test_find_similar_scores_above_threshold(
        self, store: DuckDBStore
    ) -> None:
        """Every result from find_similar must have score >= threshold."""
        for i in range(5):
            await store.store(_make_entry(content=f"similarity test content {i}"))

        threshold = 0.5
        results = await store.find_similar(
            "similarity test content", threshold=threshold, limit=10
        )
        for r in results:
            assert r.score >= threshold, (
                f"Score {r.score} is below threshold {threshold}"
            )

    async def test_find_similar_orders_by_score_descending(
        self,
        store: DuckDBStore,
        embedding_provider: _DeterministicEmbeddingProvider,
    ) -> None:
        """find_similar results are ordered by descending similarity score."""
        # Register vectors with different cosine similarities to query
        query_vec = [1.0, 0.0, 0.0, 0.0]
        high_sim_vec = [0.95, 0.05, 0.0, 0.0]
        low_sim_vec = [0.6, 0.4, 0.0, 0.0]

        embedding_provider.register("the search query text", query_vec)
        embedding_provider.register("high similarity text", high_sim_vec)
        embedding_provider.register("lower similarity text", low_sim_vec)

        high_entry = _make_entry(content="high similarity text")
        low_entry = _make_entry(content="lower similarity text")
        await store.store(high_entry)
        await store.store(low_entry)

        results = await store.find_similar(
            "the search query text", threshold=0.0, limit=10
        )
        assert len(results) >= 2

        # Verify scores are in descending order
        scores = [r.score for r in results]
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Results out of order: score[{i}]={scores[i]} < "
                f"score[{i+1}]={scores[i+1]}"
            )

    async def test_find_similar_empty_store(self, store: DuckDBStore) -> None:
        """find_similar on an empty store returns an empty list."""
        results = await store.find_similar("query text", threshold=0.0, limit=10)
        assert results == []

    async def test_find_similar_with_limit(self, store: DuckDBStore) -> None:
        """find_similar respects the limit parameter."""
        for i in range(10):
            await store.store(_make_entry(content=f"similar item {i}"))

        results = await store.find_similar(
            "similar item", threshold=0.0, limit=3
        )
        assert len(results) <= 3


# ---------------------------------------------------------------------------
# Full lifecycle: store -> update -> search reflects changes
# ---------------------------------------------------------------------------


class TestUpdateEmbeddingRefresh:
    async def test_update_content_refreshes_embedding(
        self,
        store: DuckDBStore,
        embedding_provider: _DeterministicEmbeddingProvider,
    ) -> None:
        """After update(content=...), search uses the new embedding vector."""
        original_vec = [1.0, 0.0, 0.0, 0.0]
        updated_vec = [0.0, 1.0, 0.0, 0.0]
        updated_query_vec = [0.0, 1.0, 0.0, 0.0]
        original_query_vec = [1.0, 0.0, 0.0, 0.0]

        embedding_provider.register("original content here", original_vec)
        embedding_provider.register("updated content here", updated_vec)
        embedding_provider.register("search for updated", updated_query_vec)
        embedding_provider.register("search for original", original_query_vec)

        entry = _make_entry(content="original content here")
        await store.store(entry)

        # Update with content that gets a very different vector
        await store.update(entry.id, {"content": "updated content here"})

        # Search for the updated content -- entry should now rank high
        results = await store.search(
            "search for updated", filters=None, limit=10
        )
        result_ids = [r.entry.id for r in results]
        assert entry.id in result_ids

    async def test_get_after_update_reflects_new_content(
        self, store: DuckDBStore
    ) -> None:
        """get() after update() returns the updated content."""
        entry = _make_entry(content="before update")
        await store.store(entry)
        await store.update(entry.id, {"content": "after update"})
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.content == "after update"

    async def test_update_version_increments(self, store: DuckDBStore) -> None:
        """Each update increments the version counter."""
        entry = _make_entry(content="initial content")
        await store.store(entry)
        updated1 = await store.update(entry.id, {"content": "update 1"})
        assert updated1.version == 2
        updated2 = await store.update(entry.id, {"content": "update 2"})
        assert updated2.version == 3


# ---------------------------------------------------------------------------
# Delete interaction with search and list
# ---------------------------------------------------------------------------


class TestDeleteIntegration:
    async def test_deleted_entry_still_in_db_with_archived_status(
        self, store: DuckDBStore
    ) -> None:
        """Deleted (soft-deleted) entries remain in DB with archived status."""
        entry = _make_entry(content="to be deleted")
        await store.store(entry)
        result = await store.delete(entry.id)
        assert result is True

        entries = await store.list_entries(
            filters={"status": "archived"}, limit=10, offset=0
        )
        ids = [e.id for e in entries]
        assert entry.id in ids

    async def test_active_entries_not_filtered_by_default(
        self, store: DuckDBStore
    ) -> None:
        """Active entries show up in list_entries with no filter."""
        active_entry = _make_entry(content="active entry", status=EntryStatus.ACTIVE)
        await store.store(active_entry)

        entries = await store.list_entries(filters=None, limit=10, offset=0)
        ids = [e.id for e in entries]
        assert active_entry.id in ids

    async def test_delete_false_for_nonexistent(self, store: DuckDBStore) -> None:
        """delete() returns False for entries that were never stored."""
        result = await store.delete("nonexistent-id-xyz")
        assert result is False


# ---------------------------------------------------------------------------
# Meta table consistency
# ---------------------------------------------------------------------------


class TestMetaTableIntegration:
    async def test_embedding_metadata_recorded_on_first_init(
        self, store: DuckDBStore
    ) -> None:
        """The _meta table records model name and dimensions after initialize."""
        conn = store.connection
        result = conn.execute(
            "SELECT key, value FROM _meta WHERE key IN "
            "('embedding_model', 'embedding_dimensions')"
        ).fetchall()
        meta = {row[0]: row[1] for row in result}

        assert "embedding_model" in meta
        assert "embedding_dimensions" in meta
        assert meta["embedding_model"] == "deterministic-4d"
        assert meta["embedding_dimensions"] == "4"

    async def test_model_mismatch_raises_on_reopen(self) -> None:
        """Re-opening a DB with a different model raises RuntimeError."""
        import os
        import tempfile

        # Use a temp directory and construct a path that doesn't exist yet
        # (NamedTemporaryFile creates the file, but DuckDB can't open existing
        # empty files -- so we delete it first to let DuckDB create it fresh).
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_mismatch.db")

            # First open with provider A
            provider_a = _DeterministicEmbeddingProvider()
            store_a = DuckDBStore(db_path=db_path, embedding_provider=provider_a)
            await store_a.initialize()
            await store_a.close()

            # Second open with provider B (different model name)
            class _DifferentProvider(_DeterministicEmbeddingProvider):
                @property
                def model_name(self) -> str:
                    return "different-model-name"

            provider_b = _DifferentProvider()
            store_b = DuckDBStore(db_path=db_path, embedding_provider=provider_b)
            with pytest.raises(RuntimeError, match="mismatch"):
                await store_b.initialize()
