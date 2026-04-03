"""Unit tests for the distillery.eval.retrieval_scorer module.

All tests use deterministic mock ToolCallRecord data — no actual MCP calls are
made.  The module must be importable and functional regardless of whether the
``ragas`` package is installed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from distillery.eval.models import ToolCallRecord
from distillery.eval.retrieval_scorer import (
    HAS_RAGAS,
    RetrievalMetrics,
    _build_relevance_set,
    _extract_entry_ids,
    _mrr,
    _precision_at_k,
    _recall_at_k,
    score_retrieval,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_search_record(
    entry_ids: list[str],
    tool_name: str = "distillery_search",
    latency_ms: float = 50.0,
) -> ToolCallRecord:
    """Create a ToolCallRecord whose response contains a ``results`` list."""
    results: list[dict[str, Any]] = [
        {"id": eid, "content": f"Content for {eid}"} for eid in entry_ids
    ]
    return ToolCallRecord(
        tool_name=tool_name,
        arguments={"query": "test query"},
        response={"results": results},
        latency_ms=latency_ms,
    )


def _make_golden(entry_ids: list[str], relevant_ids: set[str]) -> list[dict[str, Any]]:
    """Build a golden labels list, marking ids in ``relevant_ids`` as relevant."""
    return [{"entry_id": eid, "relevant": eid in relevant_ids} for eid in entry_ids]


# ---------------------------------------------------------------------------
# HAS_RAGAS flag
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHasRagas:
    def test_has_ragas_is_bool(self) -> None:
        assert isinstance(HAS_RAGAS, bool)


# ---------------------------------------------------------------------------
# _extract_entry_ids
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractEntryIds:
    def test_extracts_id_field(self) -> None:
        record = _make_search_record(["a1", "a2", "a3"])
        ids = _extract_entry_ids([record])
        assert ids == ["a1", "a2", "a3"]

    def test_extracts_entry_id_field(self) -> None:
        """Supports items using the ``entry_id`` key instead of ``id``."""
        record = ToolCallRecord(
            tool_name="distillery_search",
            arguments={},
            response={"results": [{"entry_id": "e1"}, {"entry_id": "e2"}]},
            latency_ms=10.0,
        )
        assert _extract_entry_ids([record]) == ["e1", "e2"]

    def test_skips_non_list_results(self) -> None:
        record = ToolCallRecord(
            tool_name="distillery_search",
            arguments={},
            response={"results": "not-a-list"},
            latency_ms=10.0,
        )
        assert _extract_entry_ids([record]) == []

    def test_skips_missing_results_key(self) -> None:
        record = ToolCallRecord(
            tool_name="distillery_search",
            arguments={},
            response={"other": "data"},
            latency_ms=10.0,
        )
        assert _extract_entry_ids([record]) == []

    def test_empty_results_list(self) -> None:
        record = ToolCallRecord(
            tool_name="distillery_search",
            arguments={},
            response={"results": []},
            latency_ms=10.0,
        )
        assert _extract_entry_ids([record]) == []

    def test_concatenates_multiple_records(self) -> None:
        r1 = _make_search_record(["a", "b"])
        r2 = _make_search_record(["c", "d"])
        ids = _extract_entry_ids([r1, r2])
        assert ids == ["a", "b", "c", "d"]

    def test_skips_items_without_id(self) -> None:
        record = ToolCallRecord(
            tool_name="distillery_search",
            arguments={},
            response={"results": [{"score": 0.9}, {"id": "x"}]},
            latency_ms=10.0,
        )
        assert _extract_entry_ids([record]) == ["x"]


# ---------------------------------------------------------------------------
# _build_relevance_set
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildRelevanceSet:
    def test_includes_only_relevant(self) -> None:
        labels = [
            {"entry_id": "a", "relevant": True},
            {"entry_id": "b", "relevant": False},
            {"entry_id": "c", "relevant": True},
        ]
        assert _build_relevance_set(labels) == {"a", "c"}

    def test_empty_labels(self) -> None:
        assert _build_relevance_set([]) == set()

    def test_defaults_irrelevant_when_key_missing(self) -> None:
        labels = [{"entry_id": "a"}]
        assert _build_relevance_set(labels) == set()

    def test_all_irrelevant(self) -> None:
        labels = [{"entry_id": "a", "relevant": False}]
        assert _build_relevance_set(labels) == set()


# ---------------------------------------------------------------------------
# _precision_at_k
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPrecisionAtK:
    def test_perfect_precision(self) -> None:
        retrieved = ["a", "b", "c"]
        relevant = {"a", "b", "c"}
        assert _precision_at_k(retrieved, relevant, k=3) == pytest.approx(1.0)

    def test_zero_precision(self) -> None:
        retrieved = ["x", "y", "z"]
        relevant = {"a", "b"}
        assert _precision_at_k(retrieved, relevant, k=3) == pytest.approx(0.0)

    def test_partial_precision(self) -> None:
        retrieved = ["a", "x", "b", "y"]
        relevant = {"a", "b"}
        # top-4: 2/4 = 0.5
        assert _precision_at_k(retrieved, relevant, k=4) == pytest.approx(0.5)

    def test_k_limits_window(self) -> None:
        retrieved = ["x", "a", "b"]
        relevant = {"a", "b"}
        # top-1: 0/1 = 0.0
        assert _precision_at_k(retrieved, relevant, k=1) == pytest.approx(0.0)

    def test_k_larger_than_results(self) -> None:
        retrieved = ["a", "b"]
        relevant = {"a", "b"}
        # Only 2 results, k=10: 2/2 = 1.0
        assert _precision_at_k(retrieved, relevant, k=10) == pytest.approx(1.0)

    def test_empty_retrieved_returns_zero(self) -> None:
        assert _precision_at_k([], {"a"}, k=5) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _recall_at_k
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecallAtK:
    def test_perfect_recall(self) -> None:
        retrieved = ["a", "b", "c"]
        relevant = {"a", "b", "c"}
        assert _recall_at_k(retrieved, relevant, k=3) == pytest.approx(1.0)

    def test_zero_recall(self) -> None:
        retrieved = ["x", "y", "z"]
        relevant = {"a", "b"}
        assert _recall_at_k(retrieved, relevant, k=3) == pytest.approx(0.0)

    def test_partial_recall(self) -> None:
        retrieved = ["a", "x", "y"]
        relevant = {"a", "b", "c"}
        # 1 of 3 relevant in top-3
        assert _recall_at_k(retrieved, relevant, k=3) == pytest.approx(1.0 / 3.0)

    def test_no_relevant_items_returns_zero(self) -> None:
        assert _recall_at_k(["a", "b"], set(), k=5) == pytest.approx(0.0)

    def test_k_larger_than_results(self) -> None:
        retrieved = ["a"]
        relevant = {"a", "b"}
        # Only "a" retrieved; 1 of 2 relevant = 0.5
        assert _recall_at_k(retrieved, relevant, k=10) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _mrr
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMrr:
    def test_first_result_relevant(self) -> None:
        assert _mrr(["a", "b", "c"], {"a"}) == pytest.approx(1.0)

    def test_second_result_relevant(self) -> None:
        assert _mrr(["x", "a", "c"], {"a"}) == pytest.approx(0.5)

    def test_third_result_relevant(self) -> None:
        assert _mrr(["x", "y", "a"], {"a"}) == pytest.approx(1.0 / 3.0)

    def test_no_relevant_returns_zero(self) -> None:
        assert _mrr(["x", "y", "z"], {"a"}) == pytest.approx(0.0)

    def test_empty_retrieved_returns_zero(self) -> None:
        assert _mrr([], {"a"}) == pytest.approx(0.0)

    def test_multiple_relevant_uses_first(self) -> None:
        # First relevant is at position 2, so MRR = 0.5
        assert _mrr(["x", "a", "b"], {"a", "b"}) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# score_retrieval — integration of the public API
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScoreRetrieval:
    def test_perfect_retrieval(self) -> None:
        """All relevant docs ranked first gives precision=1.0, recall=1.0, MRR=1.0."""
        records = [_make_search_record(["a", "b", "c"])]
        golden = _make_golden(["a", "b", "c"], relevant_ids={"a", "b", "c"})
        metrics = score_retrieval(records, golden, k=3)

        assert isinstance(metrics, RetrievalMetrics)
        assert metrics.precision == pytest.approx(1.0)
        assert metrics.recall == pytest.approx(1.0)
        assert metrics.mrr == pytest.approx(1.0)
        assert metrics.faithfulness is None

    def test_partial_retrieval(self) -> None:
        """Some relevant docs in top-k: verify precision and recall."""
        # 5 results: a, x, b, y, c — only a, b, c are relevant
        records = [_make_search_record(["a", "x", "b", "y", "c"])]
        golden = _make_golden(["a", "x", "b", "y", "c"], relevant_ids={"a", "b", "c"})
        metrics = score_retrieval(records, golden, k=5)

        # precision@5: 3/5 = 0.6
        assert metrics.precision == pytest.approx(0.6)
        # recall@5: 3/3 = 1.0 (all 3 relevant found in top-5)
        assert metrics.recall == pytest.approx(1.0)

    def test_no_relevant_results(self) -> None:
        """All results irrelevant: precision=0.0, recall=0.0, MRR=0.0."""
        records = [_make_search_record(["x", "y", "z"])]
        golden = _make_golden(["x", "y", "z", "a"], relevant_ids={"a"})
        metrics = score_retrieval(records, golden, k=3)

        assert metrics.precision == pytest.approx(0.0)
        assert metrics.recall == pytest.approx(0.0)
        assert metrics.mrr == pytest.approx(0.0)

    def test_mrr_first_relevant_at_position_three(self) -> None:
        """First relevant at rank 3 → MRR=1/3 ≈ 0.333."""
        records = [_make_search_record(["x", "y", "a", "b"])]
        golden = _make_golden(["x", "y", "a", "b"], relevant_ids={"a", "b"})
        metrics = score_retrieval(records, golden, k=4)

        assert metrics.mrr == pytest.approx(1.0 / 3.0)

    def test_empty_results_with_relevant_items(self) -> None:
        """No search results but there are relevant items: all metrics are 0."""
        records: list[ToolCallRecord] = []
        golden = [{"entry_id": "a", "relevant": True}]
        metrics = score_retrieval(records, golden, k=5)

        assert metrics.precision == pytest.approx(0.0)
        assert metrics.recall == pytest.approx(0.0)
        assert metrics.mrr == pytest.approx(0.0)

    def test_empty_results_no_relevant_items(self) -> None:
        """No results and no relevant items: metrics are None (undefined)."""
        records: list[ToolCallRecord] = []
        golden: list[dict[str, Any]] = [{"entry_id": "a", "relevant": False}]
        metrics = score_retrieval(records, golden, k=5)

        # No results and no relevant items → undefined
        assert metrics.precision is None
        assert metrics.recall is None
        assert metrics.mrr is None

    def test_k_larger_than_result_set(self) -> None:
        """k larger than number of results still computes correct metrics."""
        records = [_make_search_record(["a", "b"])]
        golden = _make_golden(["a", "b"], relevant_ids={"a", "b"})
        metrics = score_retrieval(records, golden, k=100)

        assert metrics.precision == pytest.approx(1.0)
        assert metrics.recall == pytest.approx(1.0)

    def test_faithfulness_skipped_without_ragas(self) -> None:
        """Faithfulness is None when RAGAS is not installed."""
        records = [_make_search_record(["a"])]
        golden = [{"entry_id": "a", "relevant": True}]

        with patch("distillery.eval.retrieval_scorer.HAS_RAGAS", False):
            metrics = score_retrieval(
                records,
                golden,
                k=5,
                enable_faithfulness=True,
                query="test query",
                response_text="some response",
            )

        assert metrics.faithfulness is None

    def test_faithfulness_skipped_when_not_requested(self) -> None:
        """Faithfulness is None by default even when RAGAS is installed."""
        records = [_make_search_record(["a"])]
        golden = [{"entry_id": "a", "relevant": True}]
        metrics = score_retrieval(records, golden, k=5, enable_faithfulness=False)
        assert metrics.faithfulness is None

    def test_precision_at_k_equals_1(self) -> None:
        """Precision@1: only the top result matters."""
        records = [_make_search_record(["a", "x", "y", "z"])]
        golden = _make_golden(["a", "x", "y", "z"], relevant_ids={"a"})
        metrics = score_retrieval(records, golden, k=1)

        assert metrics.precision == pytest.approx(1.0)
        assert metrics.recall == pytest.approx(1.0)

    def test_partial_recall_at_k(self) -> None:
        """recall@k when only some relevant items fit in top-k."""
        # 4 relevant items, only 2 appear in top-3
        records = [_make_search_record(["a", "b", "x", "c", "d"])]
        golden = _make_golden(["a", "b", "x", "c", "d"], relevant_ids={"a", "b", "c", "d"})
        metrics = score_retrieval(records, golden, k=3)

        # top-3: a, b, x — 2 of 4 relevant = recall 0.5
        assert metrics.recall == pytest.approx(0.5)
        # precision@3: 2/3
        assert metrics.precision == pytest.approx(2.0 / 3.0)

    def test_response_uses_entry_id_key(self) -> None:
        """Results using ``entry_id`` key are treated the same as ``id``."""
        record = ToolCallRecord(
            tool_name="distillery_search",
            arguments={},
            response={"results": [{"entry_id": "r1"}, {"entry_id": "r2"}]},
            latency_ms=10.0,
        )
        golden = [
            {"entry_id": "r1", "relevant": True},
            {"entry_id": "r2", "relevant": True},
        ]
        metrics = score_retrieval([record], golden, k=5)
        assert metrics.precision == pytest.approx(1.0)
        assert metrics.recall == pytest.approx(1.0)
