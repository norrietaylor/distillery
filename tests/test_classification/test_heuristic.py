"""Tests for HeuristicClassifier -- centroid computation and similarity classification.

All tests use the DeterministicEmbeddingProvider (4D, registry-backed) from
conftest.py so that cosine similarity values are predictable.  No LLM or
network calls are made.
"""

from __future__ import annotations

import math

import pytest

from distillery.classification.heuristic import (
    MIN_ENTRIES_PER_TYPE,
    SIMILARITY_THRESHOLD,
    HeuristicClassifier,
    cosine_similarity,
)
from distillery.models import EntrySource, EntryStatus, EntryType
from tests.conftest import DeterministicEmbeddingProvider, make_entry

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise(v: list[float]) -> list[float]:
    """Return L2-normalised copy of *v*."""
    mag = math.sqrt(sum(x * x for x in v))
    return [x / mag for x in v]


async def _populate_store(
    store,  # type: ignore[no-untyped-def]
    entry_type: EntryType,
    count: int,
    content_prefix: str = "",
) -> None:
    """Store *count* active entries of *entry_type* in *store*."""
    for i in range(count):
        entry = make_entry(
            content=f"{content_prefix or entry_type.value} entry {i}",
            entry_type=entry_type,
            source=EntrySource.MANUAL,
            status=EntryStatus.ACTIVE,
        )
        await store.store(entry)


# ---------------------------------------------------------------------------
# cosine_similarity unit tests
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    """Pure math tests for the cosine_similarity helper."""

    def test_identical_vectors_return_one(self) -> None:
        v = _normalise([1.0, 2.0, 3.0, 4.0])
        assert cosine_similarity(v, v) == pytest.approx(1.0, abs=1e-9)

    def test_orthogonal_vectors_return_zero(self) -> None:
        a = [1.0, 0.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-9)

    def test_opposite_vectors_return_negative_one(self) -> None:
        a = _normalise([1.0, 1.0, 1.0, 1.0])
        b = [-x for x in a]
        assert cosine_similarity(a, b) == pytest.approx(-1.0, abs=1e-9)

    def test_zero_vector_returns_zero(self) -> None:
        a = [0.0, 0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0, 4.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Centroid computation
# ---------------------------------------------------------------------------


class TestComputeCentroids:
    """Test compute_centroids with controlled store contents."""

    async def test_computes_centroid_for_type_with_enough_entries(
        self,
        store,  # type: ignore[no-untyped-def]
        deterministic_embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        """A type with >= MIN_ENTRIES_PER_TYPE entries produces a centroid."""
        await _populate_store(store, EntryType.SESSION, MIN_ENTRIES_PER_TYPE)

        classifier = HeuristicClassifier()
        centroids = await classifier.compute_centroids(store, deterministic_embedding_provider)

        assert "session" in centroids
        assert len(centroids["session"]) == deterministic_embedding_provider.dimensions

    async def test_skips_type_with_insufficient_entries(
        self,
        store,  # type: ignore[no-untyped-def]
        deterministic_embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        """A type with < MIN_ENTRIES_PER_TYPE entries is excluded."""
        await _populate_store(store, EntryType.SESSION, MIN_ENTRIES_PER_TYPE - 1)

        classifier = HeuristicClassifier()
        centroids = await classifier.compute_centroids(store, deterministic_embedding_provider)

        assert "session" not in centroids

    async def test_inbox_type_excluded_from_centroids(
        self,
        store,  # type: ignore[no-untyped-def]
        deterministic_embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        """INBOX entries are never used as centroid sources."""
        await _populate_store(store, EntryType.INBOX, MIN_ENTRIES_PER_TYPE + 5)

        classifier = HeuristicClassifier()
        centroids = await classifier.compute_centroids(store, deterministic_embedding_provider)

        assert "inbox" not in centroids

    async def test_centroid_is_normalised(
        self,
        store,  # type: ignore[no-untyped-def]
        deterministic_embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        """The computed centroid vector has unit magnitude."""
        await _populate_store(store, EntryType.BOOKMARK, MIN_ENTRIES_PER_TYPE)

        classifier = HeuristicClassifier()
        centroids = await classifier.compute_centroids(store, deterministic_embedding_provider)

        assert "bookmark" in centroids
        magnitude = math.sqrt(sum(c * c for c in centroids["bookmark"]))
        assert magnitude == pytest.approx(1.0, abs=1e-6)

    async def test_no_active_entries_returns_empty(
        self,
        store,  # type: ignore[no-untyped-def]
        deterministic_embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        """An empty store yields no centroids."""
        classifier = HeuristicClassifier()
        centroids = await classifier.compute_centroids(store, deterministic_embedding_provider)

        assert centroids == {}

    async def test_multiple_types_produce_multiple_centroids(
        self,
        store,  # type: ignore[no-untyped-def]
        deterministic_embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        """Two types with enough entries both get centroids."""
        await _populate_store(store, EntryType.SESSION, MIN_ENTRIES_PER_TYPE)
        await _populate_store(store, EntryType.BOOKMARK, MIN_ENTRIES_PER_TYPE)

        classifier = HeuristicClassifier()
        centroids = await classifier.compute_centroids(store, deterministic_embedding_provider)

        assert "session" in centroids
        assert "bookmark" in centroids


# ---------------------------------------------------------------------------
# classify_entry (static method-like)
# ---------------------------------------------------------------------------


class TestClassifyEntry:
    """Test classify_entry with manually constructed centroids."""

    def test_best_match_above_threshold(self) -> None:
        """When a centroid matches well, returns (type, similarity)."""
        v = _normalise([1.0, 0.0, 0.0, 0.0])
        centroids = {
            "session": _normalise([1.0, 0.1, 0.0, 0.0]),  # very similar
            "bookmark": _normalise([0.0, 1.0, 0.0, 0.0]),  # orthogonal
        }

        classifier = HeuristicClassifier()
        best_type, similarity = classifier.classify_entry(v, centroids)

        assert best_type == "session"
        assert similarity >= SIMILARITY_THRESHOLD

    def test_no_match_above_threshold(self) -> None:
        """When no centroid exceeds threshold, returns (None, best_similarity)."""
        # Entry embedding points in a direction far from both centroids.
        v = _normalise([0.0, 0.0, 0.0, 1.0])
        centroids = {
            "session": _normalise([1.0, 0.0, 0.0, 0.0]),
            "bookmark": _normalise([0.0, 1.0, 0.0, 0.0]),
        }

        classifier = HeuristicClassifier()
        best_type, similarity = classifier.classify_entry(v, centroids)

        assert best_type is None
        assert similarity < SIMILARITY_THRESHOLD

    def test_exact_match_returns_similarity_one(self) -> None:
        """An embedding identical to a centroid returns similarity ~1.0."""
        v = _normalise([1.0, 2.0, 3.0, 4.0])
        centroids = {"reference": list(v)}

        classifier = HeuristicClassifier()
        best_type, similarity = classifier.classify_entry(v, centroids)

        assert best_type == "reference"
        assert similarity == pytest.approx(1.0, abs=1e-9)

    def test_selects_best_among_multiple(self) -> None:
        """When multiple centroids exceed threshold, the highest wins."""
        v = _normalise([1.0, 0.5, 0.0, 0.0])
        centroids = {
            "session": _normalise([1.0, 0.4, 0.0, 0.0]),    # very close
            "bookmark": _normalise([1.0, 0.0, 0.0, 0.0]),   # close but less
            "idea": _normalise([0.0, 0.0, 1.0, 0.0]),       # far
        }

        classifier = HeuristicClassifier()
        best_type, similarity = classifier.classify_entry(v, centroids)

        assert best_type == "session"
        # Verify it picked the highest similarity
        for name, centroid in centroids.items():
            if name != best_type:
                assert cosine_similarity(v, centroid) <= similarity


# ---------------------------------------------------------------------------
# Full classify() integration
# ---------------------------------------------------------------------------


class TestClassifyIntegration:
    """End-to-end tests using classify() with store and embedding provider."""

    async def test_classifies_entry_matching_centroid(
        self,
        store,  # type: ignore[no-untyped-def]
        deterministic_embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        """An inbox entry similar to session entries is classified as session."""
        # Register known vectors: session entries cluster around [1,0,0,0].
        session_vec = _normalise([1.0, 0.0, 0.0, 0.0])
        for i in range(MIN_ENTRIES_PER_TYPE):
            content = f"session work item {i}"
            deterministic_embedding_provider.register(
                content, [session_vec[j] + (i * 0.01) for j in range(4)]
            )
            entry = make_entry(
                content=content,
                entry_type=EntryType.SESSION,
                status=EntryStatus.ACTIVE,
            )
            await store.store(entry)

        # The inbox entry is very similar to the session cluster.
        inbox_content = "new session work item"
        deterministic_embedding_provider.register(inbox_content, session_vec)
        inbox_entry = make_entry(
            content=inbox_content,
            entry_type=EntryType.INBOX,
            status=EntryStatus.PENDING_REVIEW,
        )

        classifier = HeuristicClassifier()
        result = await classifier.classify(
            inbox_entry, store, deterministic_embedding_provider
        )

        assert result.entry_type == EntryType.SESSION
        assert result.status == EntryStatus.ACTIVE
        assert result.confidence >= SIMILARITY_THRESHOLD

    async def test_pending_review_when_no_centroid_match(
        self,
        store,  # type: ignore[no-untyped-def]
        deterministic_embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        """An entry far from all centroids gets pending_review status."""
        # Session cluster in one direction.
        for i in range(MIN_ENTRIES_PER_TYPE):
            content = f"session content {i}"
            deterministic_embedding_provider.register(
                content, _normalise([1.0, 0.0, 0.0, 0.0])
            )
            entry = make_entry(
                content=content,
                entry_type=EntryType.SESSION,
                status=EntryStatus.ACTIVE,
            )
            await store.store(entry)

        # Inbox entry in an orthogonal direction.
        inbox_content = "completely unrelated content"
        deterministic_embedding_provider.register(
            inbox_content, _normalise([0.0, 0.0, 0.0, 1.0])
        )
        inbox_entry = make_entry(
            content=inbox_content,
            entry_type=EntryType.INBOX,
        )

        classifier = HeuristicClassifier()
        result = await classifier.classify(
            inbox_entry, store, deterministic_embedding_provider
        )

        assert result.entry_type == EntryType.INBOX
        assert result.status == EntryStatus.PENDING_REVIEW
        assert result.confidence < SIMILARITY_THRESHOLD

    async def test_pending_review_when_no_centroids_available(
        self,
        store,  # type: ignore[no-untyped-def]
        deterministic_embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        """With an empty store, the entry goes to pending_review."""
        inbox_entry = make_entry(
            content="orphan entry",
            entry_type=EntryType.INBOX,
        )

        classifier = HeuristicClassifier()
        result = await classifier.classify(
            inbox_entry, store, deterministic_embedding_provider
        )

        assert result.entry_type == EntryType.INBOX
        assert result.status == EntryStatus.PENDING_REVIEW
        assert result.confidence == 0.0

    async def test_insufficient_data_sends_to_review(
        self,
        store,  # type: ignore[no-untyped-def]
        deterministic_embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        """Types with < MIN_ENTRIES_PER_TYPE entries are not candidates."""
        # Only 2 session entries -- insufficient.
        for i in range(MIN_ENTRIES_PER_TYPE - 1):
            content = f"session item {i}"
            deterministic_embedding_provider.register(
                content, _normalise([1.0, 0.0, 0.0, 0.0])
            )
            entry = make_entry(
                content=content,
                entry_type=EntryType.SESSION,
                status=EntryStatus.ACTIVE,
            )
            await store.store(entry)

        inbox_content = "similar to session"
        deterministic_embedding_provider.register(
            inbox_content, _normalise([1.0, 0.0, 0.0, 0.0])
        )
        inbox_entry = make_entry(
            content=inbox_content,
            entry_type=EntryType.INBOX,
        )

        classifier = HeuristicClassifier()
        result = await classifier.classify(
            inbox_entry, store, deterministic_embedding_provider
        )

        assert result.status == EntryStatus.PENDING_REVIEW

    async def test_result_is_classification_result(
        self,
        store,  # type: ignore[no-untyped-def]
        deterministic_embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        """classify() always returns a ClassificationResult instance."""
        from distillery.classification.models import ClassificationResult

        inbox_entry = make_entry(content="anything", entry_type=EntryType.INBOX)

        classifier = HeuristicClassifier()
        result = await classifier.classify(
            inbox_entry, store, deterministic_embedding_provider
        )

        assert isinstance(result, ClassificationResult)
