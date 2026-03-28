"""Tests for the distillery_check_dedup MCP tool (T03).

Tests cover the _handle_check_dedup handler at various similarity levels:
  - No similar entries -> action=create
  - Score at or above skip threshold -> action=skip
  - Score at or above merge threshold (below skip) -> action=merge
  - Score at or above link threshold (below merge) -> action=link

The test harness uses an in-memory DuckDBStore with a controlled embedding
provider so that cosine similarity scores can be driven deterministically.
"""

from __future__ import annotations

import math

import pytest

from distillery.config import (
    ClassificationConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp.server import _handle_check_dedup
from distillery.store.duckdb import DuckDBStore
from tests.conftest import ControlledEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider(controlled_embedding_provider):
    """Alias for controlled_embedding_provider used by test methods."""
    return controlled_embedding_provider


@pytest.fixture
async def store(embedding_provider) -> DuckDBStore:  # type: ignore[return]
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


def _make_config(
    *,
    skip: float = 0.95,
    merge: float = 0.80,
    link: float = 0.60,
    limit: int = 5,
) -> DistilleryConfig:
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="controlled-8d", dimensions=8),
        classification=ClassificationConfig(
            confidence_threshold=0.6,
            dedup_skip_threshold=skip,
            dedup_merge_threshold=merge,
            dedup_link_threshold=link,
            dedup_limit=limit,
        ),
    )


# ---------------------------------------------------------------------------
# Helper: build identical unit vectors (cosine sim = 1.0)
# ---------------------------------------------------------------------------

_UNIT_A = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
_UNIT_B = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def _interpolated_vector(a: list[float], b: list[float], t: float) -> list[float]:
    """Return an L2-normalised vector that lies between *a* and *b*.

    *t=0* returns *a*, *t=1* returns *b*.  The cosine similarity between
    the result and *a* depends on the angle between *a* and *b*.
    """
    vec = [a[i] * (1.0 - t) + b[i] * t for i in range(len(a))]
    magnitude = math.sqrt(sum(x * x for x in vec))
    return [x / magnitude for x in vec]


def _cosine(u: list[float], v: list[float]) -> float:
    return sum(a * b for a, b in zip(u, v, strict=True))


# ---------------------------------------------------------------------------
# Test: no entries in store -> action=create
# ---------------------------------------------------------------------------


class TestCheckDedupNoEntries:
    async def test_empty_store_returns_create(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("new content", _UNIT_A)
        config = _make_config()
        response = await _handle_check_dedup(store, config, {"content": "new content"})
        data = parse_mcp_response(response)
        assert data["action"] == "create"
        assert data["similar_entries"] == []
        assert data["highest_score"] == pytest.approx(0.0)

    async def test_create_result_has_reasoning(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("unique text", _UNIT_A)
        config = _make_config()
        response = await _handle_check_dedup(store, config, {"content": "unique text"})
        data = parse_mcp_response(response)
        assert data["action"] == "create"
        assert isinstance(data["reasoning"], str)
        assert len(data["reasoning"]) > 0


# ---------------------------------------------------------------------------
# Test: missing required field -> error response
# ---------------------------------------------------------------------------


class TestCheckDedupValidation:
    async def test_missing_content_returns_error(self, store: DuckDBStore) -> None:
        config = _make_config()
        response = await _handle_check_dedup(store, config, {})
        data = parse_mcp_response(response)
        assert data.get("error") is True
        assert data.get("code") == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# Test: near-identical content -> action=skip
# ---------------------------------------------------------------------------


class TestCheckDedupSkipAction:
    async def test_identical_embedding_returns_skip(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        """Vectors that are identical (cosine=1.0) must produce action=skip."""
        existing_text = "Identical content stored"
        new_text = "Identical content new"

        # Register identical vectors for both
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(new_text, _UNIT_A)

        entry = make_entry(content=existing_text)
        await store.store(entry)

        config = _make_config(skip=0.95, merge=0.80, link=0.60)
        response = await _handle_check_dedup(store, config, {"content": new_text})
        data = parse_mcp_response(response)

        assert data["action"] == "skip"
        assert data["highest_score"] >= 0.95
        assert len(data["similar_entries"]) >= 1

    async def test_skip_result_includes_entry_fields(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        """similar_entries items must include expected serialised fields."""
        existing_text = "Content to skip"
        new_text = "Content skip query"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(new_text, _UNIT_A)

        entry = make_entry(content=existing_text, author="alice", project="proj-x")
        await store.store(entry)

        config = _make_config(skip=0.95, merge=0.80, link=0.60)
        response = await _handle_check_dedup(store, config, {"content": new_text})
        data = parse_mcp_response(response)

        assert data["action"] == "skip"
        similar = data["similar_entries"]
        assert len(similar) >= 1
        first = similar[0]
        assert "entry_id" in first
        assert "score" in first
        assert "content_preview" in first
        assert "entry_type" in first
        assert "author" in first


# ---------------------------------------------------------------------------
# Test: very similar content -> action=merge
# ---------------------------------------------------------------------------


class TestCheckDedupMergeAction:
    async def test_high_similarity_returns_merge(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        """Vectors with cosine similarity between merge and skip thresholds -> merge."""
        # Build two vectors with a known cosine similarity.
        # cos(theta) where theta = ~20 degrees -> cos ~= 0.94 (below skip=0.95)
        # We use t=0.3 interpolation so cosine is meaningfully < 1.0
        existing_vec = _UNIT_A
        # interpolated vector: cos(angle with A) = dot(interp, A)
        interp = _interpolated_vector(_UNIT_A, _UNIT_B, 0.3)
        cos_sim = _cosine(interp, existing_vec)
        # Adjust skip threshold so this score falls between merge and skip
        assert cos_sim < 1.0

        existing_text = "Merge existing content"
        new_text = "Merge query content"
        embedding_provider.register(existing_text, existing_vec)
        embedding_provider.register(new_text, interp)

        entry = make_entry(content=existing_text)
        await store.store(entry)

        # Set thresholds so that cos_sim is between merge and skip
        config = _make_config(skip=cos_sim + 0.01, merge=cos_sim - 0.01, link=0.0)
        response = await _handle_check_dedup(store, config, {"content": new_text})
        data = parse_mcp_response(response)

        assert data["action"] == "merge"
        assert data["highest_score"] >= config.classification.dedup_merge_threshold
        assert data["highest_score"] < config.classification.dedup_skip_threshold


# ---------------------------------------------------------------------------
# Test: related content -> action=link
# ---------------------------------------------------------------------------


class TestCheckDedupLinkAction:
    async def test_moderate_similarity_returns_link(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        """Vectors with cosine similarity between link and merge thresholds -> link."""
        existing_vec = _UNIT_A
        interp = _interpolated_vector(_UNIT_A, _UNIT_B, 0.7)
        cos_sim = _cosine(interp, existing_vec)
        assert cos_sim < 1.0

        existing_text = "Link existing content"
        new_text = "Link query content"
        embedding_provider.register(existing_text, existing_vec)
        embedding_provider.register(new_text, interp)

        entry = make_entry(content=existing_text)
        await store.store(entry)

        # Set thresholds so that cos_sim is between link and merge
        config = _make_config(skip=0.99, merge=cos_sim + 0.01, link=cos_sim - 0.01)
        response = await _handle_check_dedup(store, config, {"content": new_text})
        data = parse_mcp_response(response)

        assert data["action"] == "link"
        assert data["highest_score"] >= config.classification.dedup_link_threshold
        assert data["highest_score"] < config.classification.dedup_merge_threshold


# ---------------------------------------------------------------------------
# Test: config thresholds are respected (custom values)
# ---------------------------------------------------------------------------


class TestCheckDedupConfigThresholds:
    async def test_custom_skip_threshold_applied(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        """When skip threshold is set very low, identical vectors still produce skip."""
        text = "Custom threshold test"
        embedding_provider.register(text, _UNIT_A)

        entry = make_entry(content=text)
        await store.store(entry)

        config = _make_config(skip=0.5, merge=0.3, link=0.1)
        response = await _handle_check_dedup(store, config, {"content": text})
        data = parse_mcp_response(response)
        assert data["action"] == "skip"

    async def test_dedup_limit_controls_similar_entries_returned(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        """dedup_limit restricts the number of similar_entries returned."""
        # Store 3 entries with identical vectors
        for i in range(3):
            t = f"Stored entry {i}"
            embedding_provider.register(t, _UNIT_A)
            entry = make_entry(content=t)
            await store.store(entry)

        query_text = "limit query"
        embedding_provider.register(query_text, _UNIT_A)

        # Limit to 2
        config = _make_config(skip=0.95, merge=0.80, link=0.60, limit=2)
        response = await _handle_check_dedup(store, config, {"content": query_text})
        data = parse_mcp_response(response)

        assert data["action"] == "skip"
        assert len(data["similar_entries"]) <= 2