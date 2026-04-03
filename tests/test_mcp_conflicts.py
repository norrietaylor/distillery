"""Tests for conflict detection logic (previously distillery_check_conflicts MCP tool, T04.4).

Tests cover the run_conflict_discovery and run_conflict_evaluation helpers:

  First pass (run_conflict_discovery):
    - Returns conflict_candidates with LLM prompts when similar entries exist
    - Returns empty conflict_candidates when no similar entries found
    - Each candidate includes entry_id, conflict_prompt, content_preview, similarity_score

  Second pass (run_conflict_evaluation):
    - Returns has_conflicts=True and conflict list when LLM indicates conflict
    - Returns has_conflicts=False and empty list when LLM indicates no conflict
    - Handles multiple candidates where only some are conflicts
    - Conflict entries include entry_id, content_preview, similarity_score, conflict_reasoning

  Edge cases:
    - Error during conflict discovery is caught
    - Empty store returns empty conflict_candidates
    - Orthogonal vectors (similarity = 0) below threshold returns empty candidates
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
from distillery.mcp.tools.quality import run_conflict_discovery, run_conflict_evaluation
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


def _parse_llm_responses(
    raw: dict[str, dict[str, object]],
) -> dict[str, tuple[bool, str]]:
    """Convert test-style llm_responses to run_conflict_evaluation format."""
    return {
        entry_id: (bool(item["is_conflict"]), str(item.get("reasoning", "")))
        for entry_id, item in raw.items()
    }


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------


def _make_config(conflict_threshold: float = 0.60) -> DistilleryConfig:
    """Return a DistilleryConfig with an in-memory DB and controlled embedding model."""
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
def embedding_provider(
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> ControlledEmbeddingProvider:
    """Provide the 8D controlled embedding provider for similarity control."""
    return controlled_embedding_provider


@pytest.fixture
async def store(embedding_provider: ControlledEmbeddingProvider) -> DuckDBStore:  # type: ignore[return]
    """Provide an initialized in-memory DuckDBStore for tests."""
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# First-pass tests: no llm_responses
# ---------------------------------------------------------------------------


class TestCheckConflictsFirstPassWithSimilarEntries:
    """First pass returns conflict_candidates when similar entries exist."""

    async def test_returns_conflict_candidates_key(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Response contains a 'conflict_candidates' key."""
        existing_text = "Water boils at 100 degrees Celsius"
        query_text = "Water boils at 50 degrees Celsius"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        await store.store(make_entry(content=existing_text))

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        assert "conflict_candidates" in data

    async def test_candidates_list_is_non_empty(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """At least one candidate is returned when similar entries exist."""
        existing_text = "Cats are nocturnal hunters"
        query_text = "Cats are diurnal animals"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        await store.store(make_entry(content=existing_text))

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        assert len(data["conflict_candidates"]) >= 1

    async def test_candidate_has_entry_id_field(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Each candidate includes an 'entry_id' field."""
        existing_text = "The Earth orbits the Sun"
        query_text = "The Sun orbits the Earth"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        await store.store(make_entry(content=existing_text))

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        candidate = data["conflict_candidates"][0]
        assert "entry_id" in candidate

    async def test_candidate_has_conflict_prompt_field(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Each candidate includes a 'conflict_prompt' for LLM evaluation."""
        existing_text = "Exercise reduces stress levels"
        query_text = "Exercise increases stress levels"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        await store.store(make_entry(content=existing_text))

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        candidate = data["conflict_candidates"][0]
        assert "conflict_prompt" in candidate
        assert isinstance(candidate["conflict_prompt"], str)
        assert len(candidate["conflict_prompt"]) > 0

    async def test_candidate_has_content_preview_field(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Each candidate includes a 'content_preview' field."""
        existing_text = "Python is a compiled language"
        query_text = "Python is an interpreted language"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        await store.store(make_entry(content=existing_text))

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        candidate = data["conflict_candidates"][0]
        assert "content_preview" in candidate
        assert isinstance(candidate["content_preview"], str)

    async def test_candidate_has_similarity_score_field(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Each candidate includes a 'similarity_score' field."""
        existing_text = "Sleep deprivation improves mood"
        query_text = "Sleep deprivation worsens mood"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        await store.store(make_entry(content=existing_text))

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        candidate = data["conflict_candidates"][0]
        assert "similarity_score" in candidate
        assert isinstance(candidate["similarity_score"], float)

    async def test_conflict_prompt_contains_both_contents(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """The conflict_prompt includes both new and existing content."""
        existing_text = "Coffee improves cognitive performance"
        query_text = "Coffee impairs cognitive performance"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        await store.store(make_entry(content=existing_text))

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        candidate = data["conflict_candidates"][0]
        prompt = candidate["conflict_prompt"]
        assert existing_text in prompt
        assert query_text in prompt

    async def test_first_pass_has_conflicts_false(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """First pass always returns has_conflicts=False (LLM hasn't evaluated yet)."""
        existing_text = "Vaccines cause autism"
        query_text = "Vaccines do not cause autism"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        await store.store(make_entry(content=existing_text))

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        assert data.get("has_conflicts") is False

    async def test_first_pass_message_mentions_llm_responses(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """The message in first-pass response instructs caller to provide llm_responses."""
        existing_text = "The speed of light is constant"
        query_text = "The speed of light varies with medium"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        await store.store(make_entry(content=existing_text))

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        assert "message" in data
        assert "llm_responses" in data["message"]

    async def test_multiple_similar_entries_all_returned_as_candidates(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """All similar entries above the threshold are returned as candidates."""
        texts = [
            "Statement alpha about topic X",
            "Statement beta about topic X",
            "Statement gamma about topic X",
        ]
        query_text = "Contradicting statement about topic X"

        for text in texts:
            embedding_provider.register(text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        for text in texts:
            await store.store(make_entry(content=text))

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        assert len(data["conflict_candidates"]) >= 1


# ---------------------------------------------------------------------------
# First-pass tests: no similar entries
# ---------------------------------------------------------------------------


class TestCheckConflictsFirstPassNoSimilarEntries:
    """First pass returns empty conflict_candidates when no similar entries exist."""

    async def test_empty_store_returns_empty_candidates(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Empty store produces no conflict candidates."""
        query_text = "Completely new and unique content"
        embedding_provider.register(query_text, _UNIT_A)

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        assert data.get("conflict_candidates", []) == []
        assert data.get("has_conflicts") is False

    async def test_orthogonal_vectors_returns_empty_candidates(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Orthogonal vectors (cosine similarity near 0) are below the threshold."""
        existing_text = "Ancient Roman history and architecture"
        query_text = "Quantum computing and superposition states"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_B)

        await store.store(make_entry(content=existing_text))

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        assert data.get("conflict_candidates", []) == []
        assert data.get("has_conflicts") is False

    async def test_no_similar_message_indicates_none_found(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """When no similar entries exist, the message indicates no similar entries."""
        query_text = "Completely unique knowledge here"
        embedding_provider.register(query_text, _UNIT_A)

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        assert "message" in data
        assert data["conflicts"] == []


# ---------------------------------------------------------------------------
# Second-pass tests: with llm_responses
# ---------------------------------------------------------------------------


class TestCheckConflictsSecondPassWithConflict:
    """Second pass with conflict LLM responses returns has_conflicts=True."""

    async def test_has_conflicts_true_when_llm_confirms(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """has_conflicts is True when LLM response says is_conflict=True."""
        existing_text = "Regular exercise reduces blood pressure"
        query_text = "Exercise has no effect on blood pressure"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        entry = make_entry(content=existing_text)
        entry_id = await store.store(entry)

        config = _make_config(conflict_threshold=0.60)
        llm_responses = _parse_llm_responses(
            {entry_id: {"is_conflict": True, "reasoning": "Direct contradiction on blood pressure"}}
        )
        data = await run_conflict_evaluation(
            store, config.classification.conflict_threshold, query_text, llm_responses
        )

        assert data.get("has_conflicts") is True

    async def test_conflicts_list_contains_entry(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """The conflicts list contains one entry when LLM confirms a single conflict."""
        existing_text = "The Milky Way has 100 billion stars"
        query_text = "The Milky Way has only 1 billion stars"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        entry = make_entry(content=existing_text)
        entry_id = await store.store(entry)

        config = _make_config(conflict_threshold=0.60)
        llm_responses = _parse_llm_responses(
            {entry_id: {"is_conflict": True, "reasoning": "Different star count claims"}}
        )
        data = await run_conflict_evaluation(
            store, config.classification.conflict_threshold, query_text, llm_responses
        )

        assert len(data.get("conflicts", [])) == 1

    async def test_conflict_entry_has_entry_id(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Each conflict entry includes the 'entry_id' of the conflicting entry."""
        existing_text = "Humans use only 10% of their brain"
        query_text = "Humans use nearly all their brain capacity"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        entry = make_entry(content=existing_text)
        entry_id = await store.store(entry)

        config = _make_config(conflict_threshold=0.60)
        llm_responses = _parse_llm_responses(
            {entry_id: {"is_conflict": True, "reasoning": "Brain usage myth"}}
        )
        data = await run_conflict_evaluation(
            store, config.classification.conflict_threshold, query_text, llm_responses
        )

        conflict = data["conflicts"][0]
        assert conflict["entry_id"] == entry_id

    async def test_conflict_entry_has_conflict_reasoning(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Each conflict entry includes 'conflict_reasoning' from the LLM response."""
        existing_text = "Antibiotics are effective against viruses"
        query_text = "Antibiotics only work against bacteria"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        entry = make_entry(content=existing_text)
        entry_id = await store.store(entry)

        config = _make_config(conflict_threshold=0.60)
        expected_reasoning = "Antibiotics vs viruses contradiction"
        llm_responses = _parse_llm_responses(
            {entry_id: {"is_conflict": True, "reasoning": expected_reasoning}}
        )
        data = await run_conflict_evaluation(
            store, config.classification.conflict_threshold, query_text, llm_responses
        )

        conflict = data["conflicts"][0]
        assert "conflict_reasoning" in conflict
        assert conflict["conflict_reasoning"] == expected_reasoning

    async def test_conflict_entry_has_similarity_score(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Each conflict entry includes a 'similarity_score' field."""
        existing_text = "Sugar causes hyperactivity in children"
        query_text = "Sugar does not cause hyperactivity"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        entry = make_entry(content=existing_text)
        entry_id = await store.store(entry)

        config = _make_config(conflict_threshold=0.60)
        llm_responses = _parse_llm_responses(
            {entry_id: {"is_conflict": True, "reasoning": "Hyperactivity myth"}}
        )
        data = await run_conflict_evaluation(
            store, config.classification.conflict_threshold, query_text, llm_responses
        )

        conflict = data["conflicts"][0]
        assert "similarity_score" in conflict
        assert isinstance(conflict["similarity_score"], float)

    async def test_conflict_entry_has_content_preview(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Each conflict entry includes a 'content_preview' field."""
        existing_text = "Light travels faster than sound"
        query_text = "Sound travels faster than light"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        entry = make_entry(content=existing_text)
        entry_id = await store.store(entry)

        config = _make_config(conflict_threshold=0.60)
        llm_responses = _parse_llm_responses(
            {entry_id: {"is_conflict": True, "reasoning": "Speed comparison"}}
        )
        data = await run_conflict_evaluation(
            store, config.classification.conflict_threshold, query_text, llm_responses
        )

        conflict = data["conflicts"][0]
        assert "content_preview" in conflict
        assert isinstance(conflict["content_preview"], str)


class TestCheckConflictsSecondPassNoConflict:
    """Second pass with no-conflict LLM responses returns has_conflicts=False."""

    async def test_has_conflicts_false_when_llm_says_no_conflict(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """has_conflicts is False when LLM response says is_conflict=False."""
        existing_text = "Python supports functional programming"
        query_text = "Python supports object-oriented programming"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        entry = make_entry(content=existing_text)
        entry_id = await store.store(entry)

        config = _make_config(conflict_threshold=0.60)
        llm_responses = _parse_llm_responses(
            {
                entry_id: {
                    "is_conflict": False,
                    "reasoning": "Both are true — Python supports multiple paradigms",
                }
            }
        )
        data = await run_conflict_evaluation(
            store, config.classification.conflict_threshold, query_text, llm_responses
        )

        assert data.get("has_conflicts") is False

    async def test_conflicts_list_empty_when_no_conflict(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """conflicts list is empty when LLM indicates no contradiction."""
        existing_text = "Renewable energy reduces carbon emissions"
        query_text = "Solar power is a form of renewable energy"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        entry = make_entry(content=existing_text)
        entry_id = await store.store(entry)

        config = _make_config(conflict_threshold=0.60)
        llm_responses = _parse_llm_responses(
            {entry_id: {"is_conflict": False, "reasoning": "Complementary statements"}}
        )
        data = await run_conflict_evaluation(
            store, config.classification.conflict_threshold, query_text, llm_responses
        )

        assert data.get("conflicts", []) == []


class TestCheckConflictsSecondPassMultipleCandidates:
    """Second pass with multiple candidates filters correctly."""

    async def test_only_true_conflict_entries_included(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Only entries marked as conflicts by LLM appear in the conflicts list."""
        texts = {
            "conflicting entry text alpha": True,
            "related but non-conflicting entry beta": False,
        }
        query_text = "New query content for multi-candidate test"

        entry_ids = []
        for text in texts:
            embedding_provider.register(text, _UNIT_A)
            entry = make_entry(content=text)
            entry_id = await store.store(entry)
            entry_ids.append(entry_id)
        embedding_provider.register(query_text, _UNIT_A)

        config = _make_config(conflict_threshold=0.60)
        is_conflict_list = list(texts.values())
        llm_responses = _parse_llm_responses(
            {
                entry_ids[0]: {"is_conflict": is_conflict_list[0], "reasoning": "Conflict found"},
                entry_ids[1]: {"is_conflict": is_conflict_list[1], "reasoning": "Not a conflict"},
            }
        )
        data = await run_conflict_evaluation(
            store, config.classification.conflict_threshold, query_text, llm_responses
        )

        conflict_ids = {c["entry_id"] for c in data.get("conflicts", [])}
        assert entry_ids[0] in conflict_ids
        assert entry_ids[1] not in conflict_ids

    async def test_multiple_conflicts_all_included(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """All conflicting entries appear in the conflicts list."""
        texts = [
            "First contradicting claim",
            "Second contradicting claim",
        ]
        query_text = "New contradicting statement for multi-conflict test"

        entry_ids = []
        for text in texts:
            embedding_provider.register(text, _UNIT_A)
            entry = make_entry(content=text)
            entry_id = await store.store(entry)
            entry_ids.append(entry_id)
        embedding_provider.register(query_text, _UNIT_A)

        config = _make_config(conflict_threshold=0.60)
        llm_responses = _parse_llm_responses(
            {
                entry_ids[0]: {"is_conflict": True, "reasoning": "First conflict"},
                entry_ids[1]: {"is_conflict": True, "reasoning": "Second conflict"},
            }
        )
        data = await run_conflict_evaluation(
            store, config.classification.conflict_threshold, query_text, llm_responses
        )

        assert data.get("has_conflicts") is True
        assert len(data.get("conflicts", [])) >= 2


# ---------------------------------------------------------------------------
# Threshold tests
# ---------------------------------------------------------------------------


class TestCheckConflictsThreshold:
    """Helpers respect the conflict_threshold from config."""

    async def test_high_threshold_excludes_moderate_similarity(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Entries below the conflict threshold are not returned as candidates."""
        existing_text = "Moderate similarity existing entry"
        query_text = "Moderate similarity query entry"

        # Use interpolated vectors with moderate similarity
        interp = _interpolated_vector(_UNIT_A, _UNIT_B, 0.9)
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, interp)

        await store.store(make_entry(content=existing_text))

        # Set very high threshold — entry should not appear as candidate
        config = _make_config(conflict_threshold=0.99)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        assert data.get("conflict_candidates", []) == []

    async def test_low_threshold_includes_moderate_similarity(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Entries above the conflict threshold are returned as candidates."""
        existing_text = "Above threshold existing entry"
        query_text = "Above threshold query entry"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        await store.store(make_entry(content=existing_text))

        # Low threshold — identical vector should appear as candidate
        config = _make_config(conflict_threshold=0.50)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        assert len(data.get("conflict_candidates", [])) >= 1


# ---------------------------------------------------------------------------
# Edge case: content_preview truncation
# ---------------------------------------------------------------------------


class TestCheckConflictsContentPreview:
    """Content previews are truncated appropriately."""

    async def test_content_preview_truncated_to_120_chars(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Candidates with long content have their preview truncated to 120 chars."""
        long_existing = "X" * 300
        query_text = "Query for long content entry"
        embedding_provider.register(long_existing, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        await store.store(make_entry(content=long_existing))

        config = _make_config(conflict_threshold=0.60)
        data = await run_conflict_discovery(
            store, config.classification.conflict_threshold, query_text
        )

        assert len(data["conflict_candidates"]) >= 1
        candidate = data["conflict_candidates"][0]
        assert len(candidate["content_preview"]) <= 120

    async def test_second_pass_conflict_preview_truncated(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Conflict entries from second pass have content_preview truncated to 120 chars."""
        long_existing = "Y" * 300
        query_text = "Second pass long content preview query"
        embedding_provider.register(long_existing, _UNIT_A)
        embedding_provider.register(query_text, _UNIT_A)

        entry = make_entry(content=long_existing)
        entry_id = await store.store(entry)

        config = _make_config(conflict_threshold=0.60)
        llm_responses = _parse_llm_responses(
            {entry_id: {"is_conflict": True, "reasoning": "conflict confirmed"}}
        )
        data = await run_conflict_evaluation(
            store, config.classification.conflict_threshold, query_text, llm_responses
        )

        assert len(data.get("conflicts", [])) >= 1
        conflict = data["conflicts"][0]
        assert len(conflict["content_preview"]) <= 120
