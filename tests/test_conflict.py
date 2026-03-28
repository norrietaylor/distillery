"""Tests for ConflictChecker and conflict-related MCP tools (T03.3).

Covers:
  1. ConflictChecker unit tests:
     - build_prompt: prompt contains both new and existing content
     - parse_response: valid conflict response -> (True, reasoning)
     - parse_response: valid no-conflict response -> (False, reasoning)
     - parse_response: malformed response -> (False, "") gracefully
     - check: with mock store returning similar entries and llm_responses -> ConflictResult with conflicts
     - check: with mock store returning no similar entries -> ConflictResult(has_conflicts=False, conflicts=[])
     - check: threshold filtering works correctly (entries below threshold excluded)

  2. MCP integration tests:
     - distillery_store returns conflict_candidates key when contradictions detected
     - distillery_store has no conflict_candidates when no similar entries
     - distillery_store still stores entry even when conflict check raises exception (non-fatal)
     - distillery_check_conflicts (first pass) returns conflict_candidates list
     - distillery_check_conflicts (second pass, with llm_responses) returns ConflictResult
     - distillery_check_conflicts with no similar entries returns empty result
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock

import pytest

from distillery.classification.conflict import (
    ConflictChecker,
)
from distillery.config import (
    ClassificationConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp.server import _handle_check_conflicts, _handle_store
from distillery.store.duckdb import DuckDBStore
from distillery.store.protocol import SearchResult
from tests.conftest import ControlledEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers: unit vectors for deterministic similarity
# ---------------------------------------------------------------------------

_UNIT_A = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
_UNIT_B = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def _interpolated_vector(a: list[float], b: list[float], t: float) -> list[float]:
    """
    Compute the L2-normalized vector interpolated between a and b at fraction t.

    Parameters:
        a (list[float]): First vector (same length as b).
        b (list[float]): Second vector (same length as a).
        t (float): Interpolation parameter where 0.0 yields `a` and 1.0 yields `b`.

    Returns:
        list[float]: An L2-normalized vector (length 1) positioned between `a` and `b` according to `t`.
    """
    vec = [a[i] * (1.0 - t) + b[i] * t for i in range(len(a))]
    magnitude = math.sqrt(sum(x * x for x in vec))
    return [x / magnitude for x in vec]


def _cosine(u: list[float], v: list[float]) -> float:
    """
    Compute the dot product of two equal-length numeric vectors; if both vectors are L2-normalized, this equals their cosine similarity.

    Parameters:
        u (list[float]): First vector.
        v (list[float]): Second vector of the same length as `u`.

    Returns:
        float: The sum of element-wise products (dot product); equals cosine similarity when inputs are normalized.
    """
    return sum(a * b for a, b in zip(u, v, strict=True))


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------


def _make_config(conflict_threshold: float = 0.60) -> DistilleryConfig:
    """
    Create a DistilleryConfig configured for in-memory tests with a controlled embedding model.

    Parameters:
        conflict_threshold (float): Similarity threshold (0.0–1.0) used to determine whether two entries are considered a conflict.

    Returns:
        DistilleryConfig: Configuration with an in-memory database, a controlled 8-dimensional embedding model, and a classification section using the provided conflict threshold and a fixed confidence threshold of 0.6.
    """
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="controlled-8d", dimensions=8),
        classification=ClassificationConfig(
            confidence_threshold=0.6,
            conflict_threshold=conflict_threshold,
        ),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider(controlled_embedding_provider: ControlledEmbeddingProvider) -> ControlledEmbeddingProvider:
    """
    Provide the injected ControlledEmbeddingProvider fixture for tests.

    Returns:
        The same ControlledEmbeddingProvider instance that was passed in.
    """
    return controlled_embedding_provider


@pytest.fixture
async def store(embedding_provider: ControlledEmbeddingProvider) -> DuckDBStore:  # type: ignore[return]
    """
    Provide an initialized in-memory DuckDBStore backed by the given embedding provider for use in tests.

    Parameters:
        embedding_provider (ControlledEmbeddingProvider): Embedding provider used by the store to generate vectors for entries.

    Returns:
        DuckDBStore: An initialized in-memory store ready for use; the store will be closed after the caller finishes using it.
    """
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Part 1: ConflictChecker unit tests
# ---------------------------------------------------------------------------


class TestConflictCheckerBuildPrompt:
    """ConflictChecker.build_prompt must include both content strings."""

    def test_prompt_contains_new_content(self) -> None:
        mock_store = MagicMock()
        checker = ConflictChecker(store=mock_store)
        prompt = checker.build_prompt("New idea here", "Old idea there")
        assert "New idea here" in prompt

    def test_prompt_contains_existing_content(self) -> None:
        mock_store = MagicMock()
        checker = ConflictChecker(store=mock_store)
        prompt = checker.build_prompt("New idea here", "Old idea there")
        assert "Old idea there" in prompt

    def test_prompt_contains_both_content_strings(self) -> None:
        mock_store = MagicMock()
        checker = ConflictChecker(store=mock_store)
        new_text = "Python 3 is the recommended version"
        existing_text = "Python 2 was the original version"
        prompt = checker.build_prompt(new_text, existing_text)
        assert new_text in prompt
        assert existing_text in prompt

    def test_prompt_is_string(self) -> None:
        mock_store = MagicMock()
        checker = ConflictChecker(store=mock_store)
        result = checker.build_prompt("a", "b")
        assert isinstance(result, str)
        assert len(result) > 0


class TestConflictCheckerParseResponse:
    """ConflictChecker.parse_response must handle valid and malformed responses."""

    def _make_checker(self) -> ConflictChecker:
        """
        Create a ConflictChecker configured with a mocked store for use in tests.

        Returns:
            ConflictChecker: An instance whose `store` is a MagicMock.
        """
        return ConflictChecker(store=MagicMock())

    def test_valid_conflict_response_returns_true(self) -> None:
        checker = self._make_checker()
        raw = '{"is_conflict": true, "reasoning": "These entries directly contradict each other"}'
        is_conflict, reasoning = checker.parse_response(raw)
        assert is_conflict is True
        assert reasoning == "These entries directly contradict each other"

    def test_valid_no_conflict_response_returns_false(self) -> None:
        checker = self._make_checker()
        raw = '{"is_conflict": false, "reasoning": "They discuss the same topic without disagreement"}'
        is_conflict, reasoning = checker.parse_response(raw)
        assert is_conflict is False
        assert reasoning == "They discuss the same topic without disagreement"

    def test_malformed_json_returns_false_empty(self) -> None:
        checker = self._make_checker()
        is_conflict, reasoning = checker.parse_response("not valid json at all")
        assert is_conflict is False
        assert reasoning == ""

    def test_missing_is_conflict_field_returns_false_empty(self) -> None:
        checker = self._make_checker()
        is_conflict, reasoning = checker.parse_response('{"reasoning": "some explanation"}')
        assert is_conflict is False
        assert reasoning == ""

    def test_empty_string_returns_false_empty(self) -> None:
        checker = self._make_checker()
        is_conflict, reasoning = checker.parse_response("")
        assert is_conflict is False
        assert reasoning == ""

    def test_code_fenced_json_is_parsed(self) -> None:
        """parse_response should strip markdown code fences before parsing."""
        checker = self._make_checker()
        raw = '```json\n{"is_conflict": true, "reasoning": "They contradict"}\n```'
        is_conflict, reasoning = checker.parse_response(raw)
        assert is_conflict is True
        assert reasoning == "They contradict"


class TestConflictCheckerCheck:
    """ConflictChecker.check returns ConflictResult based on store results and LLM responses."""

    def _make_search_result(
        self,
        entry_id: str,
        content: str,
        score: float,
    ) -> SearchResult:
        """
        Create a SearchResult whose entry contains the given content and a forced id.

        Parameters:
            entry_id (str): The id to assign to the created entry.
            content (str): The textual content for the entry.
            score (float): The similarity score to attach to the SearchResult.

        Returns:
            SearchResult: A search result with an entry containing `content`, with `entry.id` set to `entry_id`, and the provided `score`.
        """
        entry = make_entry(content=content)
        # Patch id so we can match it
        object.__setattr__(entry, "id", entry_id)
        return SearchResult(entry=entry, score=score)

    async def test_no_similar_entries_returns_no_conflicts(self) -> None:
        mock_store = AsyncMock()
        mock_store.find_similar.return_value = []
        checker = ConflictChecker(store=mock_store)
        result = await checker.check("Some content")
        assert result.has_conflicts is False
        assert result.conflicts == []

    async def test_similar_entries_with_no_llm_responses_returns_no_conflicts(self) -> None:
        """When llm_responses is None, check returns empty conflicts even if similar entries exist."""
        mock_store = AsyncMock()
        mock_store.find_similar.return_value = [
            self._make_search_result("entry-1", "Conflicting content", 0.85),
        ]
        checker = ConflictChecker(store=mock_store)
        result = await checker.check("Some new content", llm_responses=None)
        assert result.has_conflicts is False
        assert result.conflicts == []

    async def test_similar_entries_with_conflict_llm_response_returns_conflict(self) -> None:
        """
        Verifies that when an LLM marks a similar stored entry as a conflict, ConflictChecker.check includes that entry in the returned ConflictResult.

        The resulting conflict entry is expected to contain the stored entry's id, the LLM's conflict reasoning, and the similarity score.
        """
        mock_store = AsyncMock()
        mock_store.find_similar.return_value = [
            self._make_search_result("entry-abc", "Existing contradicting content", 0.75),
        ]
        checker = ConflictChecker(store=mock_store)
        llm_responses = {"entry-abc": (True, "The two claims are mutually exclusive")}
        result = await checker.check("New contradicting content", llm_responses=llm_responses)
        assert result.has_conflicts is True
        assert len(result.conflicts) == 1
        conflict = result.conflicts[0]
        assert conflict.entry_id == "entry-abc"
        assert conflict.conflict_reasoning == "The two claims are mutually exclusive"
        assert conflict.similarity_score == pytest.approx(0.75)

    async def test_similar_entries_with_no_conflict_llm_response_returns_no_conflict(self) -> None:
        """When LLM says is_conflict=False, check returns no conflicts."""
        mock_store = AsyncMock()
        mock_store.find_similar.return_value = [
            self._make_search_result("entry-xyz", "Related but not contradicting", 0.70),
        ]
        checker = ConflictChecker(store=mock_store)
        llm_responses = {"entry-xyz": (False, "Same topic but no contradiction")}
        result = await checker.check("New content", llm_responses=llm_responses)
        assert result.has_conflicts is False
        assert result.conflicts == []

    async def test_multiple_entries_only_conflicts_included(self) -> None:
        """Only entries where is_conflict=True appear in conflicts list."""
        mock_store = AsyncMock()
        mock_store.find_similar.return_value = [
            self._make_search_result("entry-1", "Entry one content", 0.80),
            self._make_search_result("entry-2", "Entry two content", 0.70),
        ]
        checker = ConflictChecker(store=mock_store)
        llm_responses = {
            "entry-1": (True, "Direct contradiction"),
            "entry-2": (False, "No contradiction"),
        }
        result = await checker.check("New content", llm_responses=llm_responses)
        assert result.has_conflicts is True
        assert len(result.conflicts) == 1
        assert result.conflicts[0].entry_id == "entry-1"

    async def test_threshold_filtering_excludes_low_similarity(self) -> None:
        """find_similar is called with the configured threshold."""
        mock_store = AsyncMock()
        # Return empty because nothing meets the higher threshold
        mock_store.find_similar.return_value = []
        checker = ConflictChecker(store=mock_store, threshold=0.85)
        result = await checker.check("Some content")
        assert result.has_conflicts is False
        mock_store.find_similar.assert_called_once_with(
            content="Some content",
            threshold=0.85,
            limit=5,
        )

    async def test_content_preview_truncated_to_120_chars(self) -> None:
        """content_preview in ConflictEntry is truncated to 120 characters."""
        long_content = "A" * 200
        mock_store = AsyncMock()
        mock_store.find_similar.return_value = [
            self._make_search_result("entry-long", long_content, 0.90),
        ]
        checker = ConflictChecker(store=mock_store)
        llm_responses = {"entry-long": (True, "conflict found")}
        result = await checker.check("something", llm_responses=llm_responses)
        assert len(result.conflicts[0].content_preview) <= 120


# ---------------------------------------------------------------------------
# Part 2: MCP integration tests - distillery_store conflict detection
# ---------------------------------------------------------------------------


class TestMCPStoreConflictDetection:
    """distillery_store returns conflicts when similar entries exist."""

    async def test_store_returns_conflicts_when_similar(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """When an existing entry has cosine similarity above conflict_threshold,
        distillery_store returns conflicts in the response."""
        existing_text = "Cats are nocturnal animals that hunt at night"
        new_text = "Cats are diurnal animals that are active during the day"

        # Register identical vectors so similarity = 1.0 (well above threshold)
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(new_text, _UNIT_A)

        existing_entry = make_entry(content=existing_text)
        await store.store(existing_entry)

        config = _make_config(conflict_threshold=0.60)
        response = await _handle_store(
            store,
            {
                "content": new_text,
                "entry_type": "inbox",
                "author": "tester",
            },
            config,
        )
        data = parse_mcp_response(response)

        assert "entry_id" in data
        assert "conflicts" in data
        assert len(data["conflicts"]) >= 1
        # Each conflict entry must have required fields
        conflict = data["conflicts"][0]
        assert "entry_id" in conflict
        assert "content_preview" in conflict
        assert "similarity_score" in conflict
        assert "conflict_reasoning" in conflict

    async def test_store_no_conflicts_when_no_similar(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """When no similar entries exist, distillery_store response has no conflicts."""
        new_text = "A completely new and unique piece of knowledge"
        embedding_provider.register(new_text, _UNIT_A)

        config = _make_config(conflict_threshold=0.60)
        response = await _handle_store(
            store,
            {
                "content": new_text,
                "entry_type": "inbox",
                "author": "tester",
            },
            config,
        )
        data = parse_mcp_response(response)

        assert "entry_id" in data
        # No conflicts key - or empty list - when nothing is similar
        assert data.get("conflicts", []) == []

    async def test_store_succeeds_even_when_conflict_check_raises(
        self,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Entry is stored successfully even when the conflict check raises an exception."""
        # Create a store that raises on find_similar after the first call (dedup check).
        # We accomplish this by using a real store but then patching find_similar
        # to succeed for the dedup call but fail for the conflict call.

        # Simpler approach: use a store mock that always raises on find_similar
        # so both dedup and conflict checks fail — entry_id should still be returned.
        mock_store = AsyncMock()
        mock_store.store.return_value = "test-entry-id"
        mock_store.find_similar.side_effect = RuntimeError("Simulated find_similar failure")

        config = _make_config(conflict_threshold=0.60)
        response = await _handle_store(
            mock_store,
            {
                "content": "Some content",
                "entry_type": "inbox",
                "author": "tester",
            },
            config,
        )
        data = parse_mcp_response(response)

        # The entry must have been stored and entry_id returned
        assert "entry_id" in data
        assert data["entry_id"] == "test-entry-id"
        # No conflict error propagated
        assert data.get("error") is None


# ---------------------------------------------------------------------------
# Part 3: MCP integration tests - distillery_check_conflicts
# ---------------------------------------------------------------------------


class TestMCPCheckConflictsFirstPass:
    """distillery_check_conflicts first pass (no llm_responses) returns conflict_candidates."""

    async def test_first_pass_returns_candidates_when_similar(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """When similar entries exist, first pass returns conflict_candidates with prompts."""
        existing_text = "Water boils at 100°C at sea level"
        query_text = "Water boils at 50°C at sea level"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        existing_entry = make_entry(content=existing_text)
        await store.store(existing_entry)

        config = _make_config(conflict_threshold=0.60)
        response = await _handle_check_conflicts(store, config, {"content": query_text})
        data = parse_mcp_response(response)

        assert "conflict_candidates" in data
        assert len(data["conflict_candidates"]) >= 1
        candidate = data["conflict_candidates"][0]
        assert "entry_id" in candidate
        assert "conflict_prompt" in candidate
        assert "content_preview" in candidate
        assert "similarity_score" in candidate

    async def test_first_pass_no_similar_returns_empty(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """When no similar entries exist, first pass returns empty conflict_candidates."""
        # Use orthogonal vectors so similarity = 0 (below any threshold)
        existing_text = "The history of ancient Rome"
        query_text = "Quantum computing fundamentals"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_B)

        existing_entry = make_entry(content=existing_text)
        await store.store(existing_entry)

        config = _make_config(conflict_threshold=0.60)
        response = await _handle_check_conflicts(store, config, {"content": query_text})
        data = parse_mcp_response(response)

        assert data.get("conflict_candidates", []) == []
        assert data.get("has_conflicts") is False


class TestMCPCheckConflictsSecondPass:
    """distillery_check_conflicts second pass (with llm_responses) returns ConflictResult."""

    async def test_second_pass_with_conflict_llm_response(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """When llm_responses indicate conflict=True, has_conflicts=True is returned."""
        existing_text = "Exercise improves sleep quality"
        query_text = "Exercise worsens sleep quality"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        entry = make_entry(content=existing_text)
        entry_id = await store.store(entry)

        config = _make_config(conflict_threshold=0.60)
        llm_responses = {
            entry_id: {"is_conflict": True, "reasoning": "The two claims directly contradict"}
        }
        response = await _handle_check_conflicts(
            store,
            config,
            {"content": query_text, "llm_responses": llm_responses},
        )
        data = parse_mcp_response(response)

        assert data.get("has_conflicts") is True
        assert len(data.get("conflicts", [])) == 1
        conflict = data["conflicts"][0]
        assert conflict["entry_id"] == entry_id
        assert "conflict_reasoning" in conflict
        assert "similarity_score" in conflict

    async def test_second_pass_with_no_conflict_llm_response(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """When llm_responses indicate conflict=False, has_conflicts=False is returned."""
        existing_text = "Python supports multiple programming paradigms"
        query_text = "Python is a versatile language supporting OOP"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        entry = make_entry(content=existing_text)
        entry_id = await store.store(entry)

        config = _make_config(conflict_threshold=0.60)
        llm_responses = {
            entry_id: {"is_conflict": False, "reasoning": "Both describe Python capabilities without contradiction"}
        }
        response = await _handle_check_conflicts(
            store,
            config,
            {"content": query_text, "llm_responses": llm_responses},
        )
        data = parse_mcp_response(response)

        assert data.get("has_conflicts") is False
        assert data.get("conflicts", []) == []

    async def test_missing_content_returns_error(
        self,
        store: DuckDBStore,
    ) -> None:
        """
        Verify that calling _handle_check_conflicts without a "content" field produces an INVALID_INPUT error in the response.
        """
        config = _make_config()
        response = await _handle_check_conflicts(store, config, {})
        data = parse_mcp_response(response)
        assert data.get("error") is True
        assert data.get("code") == "INVALID_INPUT"

    async def test_invalid_llm_responses_type_returns_error(
        self,
        store: DuckDBStore,
    ) -> None:
        """Passing llm_responses as a non-dict returns an INVALID_INPUT error."""
        config = _make_config()
        response = await _handle_check_conflicts(
            store,
            config,
            {"content": "some content", "llm_responses": "not a dict"},
        )
        data = parse_mcp_response(response)
        assert data.get("error") is True
        assert data.get("code") == "INVALID_INPUT"