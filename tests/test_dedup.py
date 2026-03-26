"""Tests for DeduplicationChecker.

All tests use a mock store that returns pre-configured similarity results,
so no real database or embedding provider is required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from distillery.classification import (
    DeduplicationAction,
    DeduplicationChecker,
    DeduplicationResult,
)
from distillery.models import EntrySource, EntryType
from distillery.store.protocol import SearchResult
from tests.conftest import make_entry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_search_result(score: float, content: str = "Sample entry content") -> SearchResult:
    """Return a SearchResult with the given similarity score."""
    entry = make_entry(
        content=content,
        entry_type=EntryType.SESSION,
        source=EntrySource.CLAUDE_CODE,
        author="test-user",
    )
    return SearchResult(entry=entry, score=score)


def _make_mock_store(results: list[SearchResult]) -> Any:
    """Return a mock DistilleryStore whose find_similar returns *results*."""
    store = AsyncMock()
    store.find_similar = AsyncMock(return_value=results)
    return store


def _make_checker(
    store: Any,
    *,
    skip_threshold: float = 0.95,
    merge_threshold: float = 0.80,
    link_threshold: float = 0.60,
    dedup_limit: int = 5,
) -> DeduplicationChecker:
    return DeduplicationChecker(
        store=store,
        skip_threshold=skip_threshold,
        merge_threshold=merge_threshold,
        link_threshold=link_threshold,
        dedup_limit=dedup_limit,
    )


# ---------------------------------------------------------------------------
# Skip action
# ---------------------------------------------------------------------------


class TestSkipAction:
    """Similarity score >= skip_threshold recommends skip."""

    async def test_score_at_skip_threshold_returns_skip(self) -> None:
        result_entry = _make_search_result(0.95)
        store = _make_mock_store([result_entry])
        checker = _make_checker(store)

        result = await checker.check("Some content")

        assert result.action == DeduplicationAction.SKIP

    async def test_score_above_skip_threshold_returns_skip(self) -> None:
        result_entry = _make_search_result(0.97)
        store = _make_mock_store([result_entry])
        checker = _make_checker(store)

        result = await checker.check("Some content")

        assert result.action == DeduplicationAction.SKIP
        assert result.highest_score == pytest.approx(0.97)

    async def test_skip_reasoning_mentions_duplicate(self) -> None:
        result_entry = _make_search_result(0.97)
        store = _make_mock_store([result_entry])
        checker = _make_checker(store)

        result = await checker.check("Some content")

        assert "duplicate" in result.reasoning.lower() or "skip" in result.reasoning.lower()

    async def test_skip_includes_similar_entries(self) -> None:
        result_entry = _make_search_result(0.97)
        store = _make_mock_store([result_entry])
        checker = _make_checker(store)

        result = await checker.check("Some content")

        assert len(result.similar_entries) == 1
        assert result.similar_entries[0].score == pytest.approx(0.97)


# ---------------------------------------------------------------------------
# Merge action
# ---------------------------------------------------------------------------


class TestMergeAction:
    """Similarity score between merge_threshold and skip_threshold recommends merge."""

    async def test_score_at_merge_threshold_returns_merge(self) -> None:
        result_entry = _make_search_result(0.80)
        store = _make_mock_store([result_entry])
        checker = _make_checker(store)

        result = await checker.check("Some content")

        assert result.action == DeduplicationAction.MERGE

    async def test_score_between_merge_and_skip_returns_merge(self) -> None:
        result_entry = _make_search_result(0.88)
        store = _make_mock_store([result_entry])
        checker = _make_checker(store)

        result = await checker.check("Some content")

        assert result.action == DeduplicationAction.MERGE
        assert result.highest_score == pytest.approx(0.88)

    async def test_merge_reasoning_mentions_merging(self) -> None:
        result_entry = _make_search_result(0.88)
        store = _make_mock_store([result_entry])
        checker = _make_checker(store)

        result = await checker.check("Some content")

        assert "merg" in result.reasoning.lower()

    async def test_merge_includes_similar_entries(self) -> None:
        result_entry = _make_search_result(0.88)
        store = _make_mock_store([result_entry])
        checker = _make_checker(store)

        result = await checker.check("Some content")

        assert len(result.similar_entries) >= 1


# ---------------------------------------------------------------------------
# Link action
# ---------------------------------------------------------------------------


class TestLinkAction:
    """Similarity score between link_threshold and merge_threshold recommends link."""

    async def test_score_at_link_threshold_returns_link(self) -> None:
        result_entry = _make_search_result(0.60)
        store = _make_mock_store([result_entry])
        checker = _make_checker(store)

        result = await checker.check("Some content")

        assert result.action == DeduplicationAction.LINK

    async def test_score_between_link_and_merge_returns_link(self) -> None:
        result_entry = _make_search_result(0.72)
        store = _make_mock_store([result_entry])
        checker = _make_checker(store)

        result = await checker.check("Some content")

        assert result.action == DeduplicationAction.LINK
        assert result.highest_score == pytest.approx(0.72)

    async def test_link_includes_similar_entries(self) -> None:
        result_entry = _make_search_result(0.72)
        store = _make_mock_store([result_entry])
        checker = _make_checker(store)

        result = await checker.check("Some content")

        assert len(result.similar_entries) >= 1

    async def test_link_reasoning_mentions_linking(self) -> None:
        result_entry = _make_search_result(0.72)
        store = _make_mock_store([result_entry])
        checker = _make_checker(store)

        result = await checker.check("Some content")

        assert "link" in result.reasoning.lower() or "relat" in result.reasoning.lower()


# ---------------------------------------------------------------------------
# Create action
# ---------------------------------------------------------------------------


class TestCreateAction:
    """No entries above link_threshold recommends create."""

    async def test_no_similar_entries_returns_create(self) -> None:
        store = _make_mock_store([])
        checker = _make_checker(store)

        result = await checker.check("Completely novel content")

        assert result.action == DeduplicationAction.CREATE

    async def test_create_has_empty_similar_entries(self) -> None:
        store = _make_mock_store([])
        checker = _make_checker(store)

        result = await checker.check("Completely novel content")

        assert result.similar_entries == []

    async def test_create_has_zero_highest_score(self) -> None:
        store = _make_mock_store([])
        checker = _make_checker(store)

        result = await checker.check("Completely novel content")

        assert result.highest_score == pytest.approx(0.0)

    async def test_create_has_reasoning(self) -> None:
        store = _make_mock_store([])
        checker = _make_checker(store)

        result = await checker.check("Completely novel content")

        assert len(result.reasoning) > 0


# ---------------------------------------------------------------------------
# dedup_limit respected
# ---------------------------------------------------------------------------


class TestDedupLimit:
    """Checker passes dedup_limit to find_similar."""

    async def test_dedup_limit_passed_to_store(self) -> None:
        store = _make_mock_store([])
        checker = _make_checker(store, dedup_limit=3)

        await checker.check("Content")

        store.find_similar.assert_called_once()
        _, kwargs = store.find_similar.call_args
        assert kwargs.get("limit", store.find_similar.call_args[0][2] if store.find_similar.call_args[0] else None) == 3 or store.find_similar.call_args[0][2] == 3

    async def test_dedup_limit_3_with_10_results_caps_list(self) -> None:
        """Simulate store returning exactly limit results as configured."""
        # The store itself enforces the limit; we verify our call passes it.
        many_results = [_make_search_result(0.70 + i * 0.01) for i in range(3)]
        store = _make_mock_store(many_results)
        checker = _make_checker(store, dedup_limit=3)

        result = await checker.check("Content")

        # We asked for 3; the mock returned 3.
        assert len(result.similar_entries) <= 3

    async def test_default_dedup_limit_is_5(self) -> None:
        store = _make_mock_store([])
        checker = DeduplicationChecker(store=store)

        await checker.check("Content")

        store.find_similar.assert_called_once()
        # Extract the limit argument (positional or keyword)
        call_args = store.find_similar.call_args
        if call_args.kwargs.get("limit") is not None:
            limit = call_args.kwargs["limit"]
        else:
            limit = call_args.args[2]
        assert limit == 5


# ---------------------------------------------------------------------------
# find_similar called with link_threshold
# ---------------------------------------------------------------------------


class TestStoreCalls:
    """Checker always queries with the link_threshold as minimum score."""

    async def test_find_similar_called_with_link_threshold(self) -> None:
        store = _make_mock_store([])
        checker = _make_checker(store, link_threshold=0.55)

        await checker.check("Some content text")

        store.find_similar.assert_called_once()
        call_args = store.find_similar.call_args
        if call_args.kwargs.get("threshold") is not None:
            threshold = call_args.kwargs["threshold"]
        else:
            threshold = call_args.args[1]
        assert threshold == pytest.approx(0.55)

    async def test_find_similar_called_with_content(self) -> None:
        store = _make_mock_store([])
        checker = _make_checker(store)
        content = "Unique content string for testing"

        await checker.check(content)

        store.find_similar.assert_called_once()
        call_args = store.find_similar.call_args
        if call_args.kwargs.get("content") is not None:
            called_content = call_args.kwargs["content"]
        else:
            called_content = call_args.args[0]
        assert called_content == content


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


class TestReturnType:
    """check() always returns a DeduplicationResult."""

    async def test_returns_deduplication_result_instance(self) -> None:
        store = _make_mock_store([])
        checker = _make_checker(store)

        result = await checker.check("Content")

        assert isinstance(result, DeduplicationResult)

    async def test_result_with_entries_is_deduplication_result(self) -> None:
        store = _make_mock_store([_make_search_result(0.97)])
        checker = _make_checker(store)

        result = await checker.check("Content")

        assert isinstance(result, DeduplicationResult)


# ---------------------------------------------------------------------------
# Highest score reflects most similar entry
# ---------------------------------------------------------------------------


class TestHighestScore:
    """highest_score is the score of the first (highest) result."""

    async def test_highest_score_is_first_result_score(self) -> None:
        results = [
            _make_search_result(0.92),
            _make_search_result(0.85),
            _make_search_result(0.71),
        ]
        store = _make_mock_store(results)
        checker = _make_checker(store)

        result = await checker.check("Content")

        assert result.highest_score == pytest.approx(0.92)

    async def test_action_determined_by_highest_score(self) -> None:
        # First result is 0.92 (< skip 0.95, >= merge 0.80) → merge
        results = [
            _make_search_result(0.92),
            _make_search_result(0.65),
        ]
        store = _make_mock_store(results)
        checker = _make_checker(store)

        result = await checker.check("Content")

        assert result.action == DeduplicationAction.MERGE
