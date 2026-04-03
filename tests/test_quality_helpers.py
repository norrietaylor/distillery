"""Tests for the standalone quality helper functions (T02.1).

Tests cover the importable helper functions extracted from quality.py:
  - run_dedup_check: Standalone dedup check returning typed dicts
  - run_conflict_discovery: First-pass conflict discovery returning candidates
  - run_conflict_evaluation: Second-pass conflict evaluation with LLM responses

These helpers accept typed arguments and return plain dicts, independent of
MCP handler signatures.
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock

import pytest

from distillery.config import ClassificationConfig
from distillery.mcp.tools.quality import (
    run_conflict_discovery,
    run_conflict_evaluation,
    run_dedup_check,
)
from distillery.store.duckdb import DuckDBStore
from tests.conftest import ControlledEmbeddingProvider, make_entry

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers: unit vectors for deterministic similarity
# ---------------------------------------------------------------------------

_UNIT_A = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
_UNIT_B = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def _interpolated_vector(a: list[float], b: list[float], t: float) -> list[float]:
    """Return an L2-normalised vector interpolated between a and b at fraction t."""
    vec = [a[i] * (1.0 - t) + b[i] * t for i in range(len(a))]
    magnitude = math.sqrt(sum(x * x for x in vec))
    return [x / magnitude for x in vec]


def _cosine(u: list[float], v: list[float]) -> float:
    return sum(a * b for a, b in zip(u, v, strict=True))


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------


def _make_cls_config(
    *,
    skip: float = 0.95,
    merge: float = 0.80,
    link: float = 0.60,
    limit: int = 5,
    conflict_threshold: float = 0.60,
) -> ClassificationConfig:
    """Return a ClassificationConfig with custom dedup/conflict thresholds."""
    return ClassificationConfig(
        confidence_threshold=0.6,
        dedup_skip_threshold=skip,
        dedup_merge_threshold=merge,
        dedup_link_threshold=link,
        dedup_limit=limit,
        conflict_threshold=conflict_threshold,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider(
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> ControlledEmbeddingProvider:
    return controlled_embedding_provider


@pytest.fixture
async def store(embedding_provider: ControlledEmbeddingProvider) -> DuckDBStore:  # type: ignore[return]
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


# ===========================================================================
# run_dedup_check tests
# ===========================================================================


class TestRunDedupCheckCreate:
    """run_dedup_check returns action=create when no similar entries exist."""

    async def test_empty_store_returns_create(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("new content", _UNIT_A)
        cls_cfg = _make_cls_config()
        result = await run_dedup_check(store, cls_cfg, "new content")
        assert result["action"] == "create"
        assert result["similar_entries"] == []
        assert result["highest_score"] == pytest.approx(0.0)

    async def test_create_has_reasoning(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("unique text", _UNIT_A)
        cls_cfg = _make_cls_config()
        result = await run_dedup_check(store, cls_cfg, "unique text")
        assert isinstance(result["reasoning"], str)
        assert len(result["reasoning"]) > 0


class TestRunDedupCheckSkip:
    """run_dedup_check returns action=skip for near-identical content."""

    async def test_identical_embedding_returns_skip(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("existing", _UNIT_A)
        embedding_provider.register("new query", _UNIT_A)
        await store.store(make_entry(content="existing"))

        cls_cfg = _make_cls_config(skip=0.95, merge=0.80, link=0.60)
        result = await run_dedup_check(store, cls_cfg, "new query")
        assert result["action"] == "skip"
        assert result["highest_score"] >= 0.95
        assert len(result["similar_entries"]) >= 1

    async def test_skip_entry_has_expected_fields(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("content skip", _UNIT_A)
        embedding_provider.register("query skip", _UNIT_A)
        await store.store(make_entry(content="content skip", author="alice", project="proj"))

        cls_cfg = _make_cls_config(skip=0.95)
        result = await run_dedup_check(store, cls_cfg, "query skip")
        first = result["similar_entries"][0]
        assert "entry_id" in first
        assert "score" in first
        assert "content_preview" in first
        assert "entry_type" in first
        assert "author" in first
        assert "project" in first
        assert "created_at" in first


class TestRunDedupCheckMerge:
    """run_dedup_check returns action=merge for very similar content."""

    async def test_high_similarity_returns_merge(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        existing_vec = _UNIT_A
        interp = _interpolated_vector(_UNIT_A, _UNIT_B, 0.3)
        cos_sim = _cosine(interp, existing_vec)
        norm_sim = (cos_sim + 1.0) / 2.0

        embedding_provider.register("merge existing", existing_vec)
        embedding_provider.register("merge query", interp)
        await store.store(make_entry(content="merge existing"))

        cls_cfg = _make_cls_config(skip=norm_sim + 0.01, merge=norm_sim - 0.01, link=0.0)
        result = await run_dedup_check(store, cls_cfg, "merge query")
        assert result["action"] == "merge"


class TestRunDedupCheckLink:
    """run_dedup_check returns action=link for related content."""

    async def test_moderate_similarity_returns_link(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        existing_vec = _UNIT_A
        interp = _interpolated_vector(_UNIT_A, _UNIT_B, 0.7)
        cos_sim = _cosine(interp, existing_vec)
        norm_sim = (cos_sim + 1.0) / 2.0

        embedding_provider.register("link existing", existing_vec)
        embedding_provider.register("link query", interp)
        await store.store(make_entry(content="link existing"))

        cls_cfg = _make_cls_config(skip=0.99, merge=norm_sim + 0.01, link=norm_sim - 0.01)
        result = await run_dedup_check(store, cls_cfg, "link query")
        assert result["action"] == "link"


class TestRunDedupCheckRaisesOnError:
    """run_dedup_check propagates exceptions."""

    async def test_store_error_propagates(self) -> None:
        mock_store = AsyncMock()
        mock_store.find_similar.side_effect = RuntimeError("Store failure")
        cls_cfg = _make_cls_config()
        with pytest.raises(RuntimeError, match="Store failure"):
            await run_dedup_check(mock_store, cls_cfg, "content")


# ===========================================================================
# run_conflict_discovery tests
# ===========================================================================


class TestRunConflictDiscovery:
    """run_conflict_discovery returns candidate prompts for LLM evaluation."""

    async def test_returns_candidates_when_similar_entries_exist(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("existing statement", _UNIT_A)
        embedding_provider.register("new contradicting statement", _UNIT_A)
        await store.store(make_entry(content="existing statement"))

        result = await run_conflict_discovery(store, 0.60, "new contradicting statement")
        assert "conflict_candidates" in result
        assert len(result["conflict_candidates"]) >= 1
        assert result["has_conflicts"] is False

    async def test_candidate_has_required_fields(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("field check existing", _UNIT_A)
        embedding_provider.register("field check query", _UNIT_A)
        await store.store(make_entry(content="field check existing"))

        result = await run_conflict_discovery(store, 0.60, "field check query")
        candidate = result["conflict_candidates"][0]
        assert "entry_id" in candidate
        assert "content_preview" in candidate
        assert "similarity_score" in candidate
        assert "conflict_prompt" in candidate

    async def test_empty_store_returns_empty_candidates(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("no matches query", _UNIT_A)
        result = await run_conflict_discovery(store, 0.60, "no matches query")
        assert result["conflict_candidates"] == []
        assert result["has_conflicts"] is False

    async def test_message_mentions_llm_responses(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("msg existing", _UNIT_A)
        embedding_provider.register("msg query", _UNIT_A)
        await store.store(make_entry(content="msg existing"))

        result = await run_conflict_discovery(store, 0.60, "msg query")
        assert "message" in result
        assert "llm_responses" in result["message"]

    async def test_store_error_propagates(self) -> None:
        mock_store = AsyncMock()
        mock_store.find_similar.side_effect = RuntimeError("Store failure")
        with pytest.raises(RuntimeError, match="Store failure"):
            await run_conflict_discovery(mock_store, 0.60, "content")


# ===========================================================================
# run_conflict_evaluation tests
# ===========================================================================


class TestRunConflictEvaluation:
    """run_conflict_evaluation processes LLM responses and returns results."""

    async def test_has_conflicts_true_when_llm_confirms(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("eval existing", _UNIT_A)
        embedding_provider.register("eval query", _UNIT_A)
        entry = make_entry(content="eval existing")
        entry_id = await store.store(entry)

        llm_responses = {entry_id: (True, "Direct contradiction")}
        result = await run_conflict_evaluation(store, 0.60, "eval query", llm_responses)
        assert result["has_conflicts"] is True
        assert len(result["conflicts"]) == 1

    async def test_has_conflicts_false_when_llm_says_no(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("no conflict existing", _UNIT_A)
        embedding_provider.register("no conflict query", _UNIT_A)
        entry = make_entry(content="no conflict existing")
        entry_id = await store.store(entry)

        llm_responses = {entry_id: (False, "Complementary statements")}
        result = await run_conflict_evaluation(store, 0.60, "no conflict query", llm_responses)
        assert result["has_conflicts"] is False
        assert result["conflicts"] == []

    async def test_conflict_entry_has_expected_fields(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("fields existing", _UNIT_A)
        embedding_provider.register("fields query", _UNIT_A)
        entry = make_entry(content="fields existing")
        entry_id = await store.store(entry)

        llm_responses = {entry_id: (True, "Contradiction found")}
        result = await run_conflict_evaluation(store, 0.60, "fields query", llm_responses)
        conflict = result["conflicts"][0]
        assert "entry_id" in conflict
        assert "content_preview" in conflict
        assert "similarity_score" in conflict
        assert "conflict_reasoning" in conflict
        assert conflict["entry_id"] == entry_id
        assert conflict["conflict_reasoning"] == "Contradiction found"

    async def test_multiple_candidates_filters_correctly(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("multi alpha", _UNIT_A)
        embedding_provider.register("multi beta", _UNIT_A)
        embedding_provider.register("multi query", _UNIT_A)
        entry1 = make_entry(content="multi alpha")
        entry2 = make_entry(content="multi beta")
        id1 = await store.store(entry1)
        id2 = await store.store(entry2)

        llm_responses = {
            id1: (True, "Conflict found"),
            id2: (False, "Not a conflict"),
        }
        result = await run_conflict_evaluation(store, 0.60, "multi query", llm_responses)
        conflict_ids = {c["entry_id"] for c in result["conflicts"]}
        assert id1 in conflict_ids
        assert id2 not in conflict_ids

    async def test_store_error_propagates(self) -> None:
        mock_store = AsyncMock()
        mock_store.find_similar.side_effect = RuntimeError("Store failure")
        with pytest.raises(RuntimeError, match="Store failure"):
            await run_conflict_evaluation(
                mock_store, 0.60, "content", {"some-id": (True, "reason")}
            )


# ===========================================================================
# Verify helpers are importable from quality module
# ===========================================================================


class TestHelperImports:
    """Verify that helpers are importable and in __all__."""

    def test_run_dedup_check_importable(self) -> None:
        from distillery.mcp.tools.quality import run_dedup_check as fn

        assert callable(fn)

    def test_run_conflict_discovery_importable(self) -> None:
        from distillery.mcp.tools.quality import run_conflict_discovery as fn

        assert callable(fn)

    def test_run_conflict_evaluation_importable(self) -> None:
        from distillery.mcp.tools.quality import run_conflict_evaluation as fn

        assert callable(fn)

    def test_all_exports_include_helpers(self) -> None:
        from distillery.mcp.tools import quality

        assert "run_dedup_check" in quality.__all__
        assert "run_conflict_discovery" in quality.__all__
        assert "run_conflict_evaluation" in quality.__all__
