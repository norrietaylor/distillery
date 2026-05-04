"""Spec-as-test for ``distillery.eval.scoring``.

The 12-row table below *is* the spec for the textbook DCG / NDCG /
``evaluate_retrieval`` implementation. Each row pins a specific
behaviour (perfect ranking, worst ranking, partial match, oversized k,
etc.) and is asserted with a hand-computed expected value derived from
the textbook formula::

    DCG@k = sum_{i=0..min(k, len)-1} rel_i / log2(i + 2)
    NDCG@k = DCG@k / IDCG@k                     # 0.0 if IDCG@k == 0
    recall_any  = 1.0 if any correct id in top-k else 0.0
    recall_all  = 1.0 if all correct ids in top-k else 0.0

The test table is the regression contract; no behavioural change to the
module ships without updating this table.
"""

from __future__ import annotations

import math

import pytest

from distillery.eval.scoring import dcg, evaluate_retrieval, ndcg

# ---------------------------------------------------------------------------
# Hand-computed dcg(...) reference rows
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDcg:
    """Direct tests of the ``dcg`` primitive — log-base discount sanity."""

    def test_dcg_log_base_two_rows(self) -> None:
        """``dcg([1, 1], 2) == 1.0 + 1.0/log2(3)`` — pin the discount base."""
        # rel_0 / log2(2) = 1.0 / 1.0  = 1.0
        # rel_1 / log2(3) = 1.0 / 1.5849625... ≈ 0.6309297...
        expected = 1.0 + 1.0 / math.log2(3)
        assert dcg([1.0, 1.0], 2) == pytest.approx(expected)

    def test_dcg_empty_relevances_is_zero(self) -> None:
        assert dcg([], 5) == 0.0

    def test_dcg_zero_k_is_zero(self) -> None:
        assert dcg([1.0, 1.0, 1.0], 0) == 0.0

    def test_dcg_truncates_at_k(self) -> None:
        # k=1 → only rel_0 / log2(2) = 1.0 contributes.
        assert dcg([1.0, 1.0, 1.0], 1) == pytest.approx(1.0)

    def test_dcg_k_larger_than_relevances(self) -> None:
        """k larger than the list must not raise — just stop at the end."""
        # Two perfect items at k=10: 1.0 + 1.0/log2(3)
        expected = 1.0 + 1.0 / math.log2(3)
        assert dcg([1.0, 1.0], 10) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 12-row test table — the spec for ndcg + evaluate_retrieval
# ---------------------------------------------------------------------------


# Each row: (label, rankings, correct_ids, corpus_ids, k,
#            expected_recall_any, expected_recall_all, expected_ndcg)
# The expected_ndcg values below are hand-computed from the textbook
# formula and rounded only via pytest.approx tolerance.
_LOG2_3 = math.log2(3)  # ≈ 1.5849625007211562
_LOG2_4 = math.log2(4)  # 2.0


SCORING_TABLE: list[tuple[str, list[int], set[str], list[str], int, float, float, float]] = [
    # 1. Empty rankings → all zeros, regardless of correct_ids.
    ("empty_rankings_k5", [], {"a"}, ["a", "b", "c"], 5, 0.0, 0.0, 0.0),
    # 2. Perfect ranking, single correct id at position 0, k=1.
    #    DCG=1/log2(2)=1.0, IDCG=1.0 → NDCG=1.0; recall_any=recall_all=1.0.
    ("perfect_k1", [0], {"a"}, ["a", "b", "c"], 1, 1.0, 1.0, 1.0),
    # 3. Worst ranking — single correct id at position 4 (last) with k=5.
    #    DCG = 1/log2(6); IDCG = 1.0 → NDCG = 1/log2(6).
    (
        "worst_within_k5",
        [1, 2, 3, 4, 0],
        {"a"},
        ["a", "b", "c", "d", "e"],
        5,
        1.0,
        1.0,
        1.0 / math.log2(6),
    ),
    # 4. Correct id beyond k — completely missed at k=3 even though present in rankings.
    ("missed_beyond_k3", [1, 2, 3, 0], {"a"}, ["a", "b", "c", "d"], 3, 0.0, 0.0, 0.0),
    # 5. Multiple correct ids, partial match at k=2 (one of two found at rank 0).
    #    DCG = 1/log2(2) = 1.0; IDCG@2 = 1/log2(2) + 1/log2(3) = 1 + 1/log2(3).
    #    recall_any=1.0, recall_all=0.0.
    (
        "partial_match_k2",
        [0, 2],
        {"a", "b"},
        ["a", "b", "c", "d"],
        2,
        1.0,
        0.0,
        1.0 / (1.0 + 1.0 / _LOG2_3),
    ),
    # 6. All correct ids in top-k — recall_all=1.0; NDCG=1.0 because the two
    #    relevant docs occupy the first two ranks.
    (
        "all_correct_k5",
        [0, 1, 2, 3, 4],
        {"a", "b"},
        ["a", "b", "c", "d", "e"],
        5,
        1.0,
        1.0,
        1.0,
    ),
    # 7. k larger than rankings length — must not raise.
    #    Single correct at rank 0; DCG=1.0; IDCG=1.0 → NDCG=1.0.
    ("k_oversized_k10", [0, 1], {"a"}, ["a", "b"], 10, 1.0, 1.0, 1.0),
    # 8. Empty correct_ids — IDCG=0 → NDCG=0; recall_any=recall_all=0.
    ("empty_correct_ids", [0, 1, 2], set(), ["a", "b", "c"], 5, 0.0, 0.0, 0.0),
    # 9. k=1, correct doc at rank 1 (just outside) → all zeros.
    ("near_miss_k1", [1, 0], {"a"}, ["a", "b"], 1, 0.0, 0.0, 0.0),
    # 10. k=10 with three correct docs spread across ranks 0, 4, 9.
    #     Relevances at positions 0,4,9 = 1.0; others 0.0.
    #     DCG = 1/log2(2) + 1/log2(6) + 1/log2(11)
    #     IDCG@10 = 1/log2(2) + 1/log2(3) + 1/log2(4)
    (
        "spread_k10",
        [0, 5, 6, 7, 1, 8, 9, 4, 3, 2],
        {"a", "b", "c"},
        ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
        10,
        1.0,
        1.0,
        (1.0 / math.log2(2) + 1.0 / math.log2(6) + 1.0 / math.log2(11))
        / (1.0 / math.log2(2) + 1.0 / _LOG2_3 + 1.0 / _LOG2_4),
    ),
    # 11. k=5, two correct of three found in top-5 (recall_any=1, recall_all=0).
    #     correct = {a, b, c} at corpus indices 0, 1, 2.
    #     rankings top-5: [0, 3, 1, 4, 5] → relevances [1, 0, 1, 0, 0].
    #     DCG = 1/log2(2) + 1/log2(4) = 1.0 + 0.5 = 1.5
    #     IDCG@5 = 1/log2(2) + 1/log2(3) + 1/log2(4)
    (
        "two_of_three_k5",
        [0, 3, 1, 4, 5, 2],
        {"a", "b", "c"},
        ["a", "b", "c", "d", "e", "f"],
        5,
        1.0,
        0.0,
        (1.0 + 0.5) / (1.0 + 1.0 / _LOG2_3 + 0.5),
    ),
    # 12. k=10 with correct doc at the very last position (rank 9 → log2(11)).
    #     DCG = 1/log2(11); IDCG = 1.0 → NDCG = 1/log2(11).
    (
        "last_rank_k10",
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 0],
        {"a"},
        ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
        10,
        1.0,
        1.0,
        1.0 / math.log2(11),
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize(
    (
        "label",
        "rankings",
        "correct_ids",
        "corpus_ids",
        "k",
        "expected_recall_any",
        "expected_recall_all",
        "expected_ndcg",
    ),
    SCORING_TABLE,
    ids=[row[0] for row in SCORING_TABLE],
)
def test_scoring_table(
    label: str,
    rankings: list[int],
    correct_ids: set[str],
    corpus_ids: list[str],
    k: int,
    expected_recall_any: float,
    expected_recall_all: float,
    expected_ndcg: float,
) -> None:
    """Spec table — every behavioural property of ``evaluate_retrieval``."""
    recall_any, recall_all, ndcg_score = evaluate_retrieval(rankings, correct_ids, corpus_ids, k)
    assert recall_any == pytest.approx(expected_recall_any), f"recall_any failed: {label}"
    assert recall_all == pytest.approx(expected_recall_all), f"recall_all failed: {label}"
    assert ndcg_score == pytest.approx(expected_ndcg), f"ndcg failed: {label}"

    # Cross-check that the standalone ``ndcg`` matches what the wrapper returned.
    direct_ndcg = ndcg(rankings, correct_ids, corpus_ids, k)
    assert direct_ndcg == pytest.approx(expected_ndcg), f"direct ndcg drift: {label}"


# ---------------------------------------------------------------------------
# Property-style guards beyond the table
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNdcgBoundary:
    """Defensive checks that don't fit cleanly in the parametrised table."""

    def test_ndcg_zero_k_is_zero(self) -> None:
        assert ndcg([0, 1], {"a"}, ["a", "b"], 0) == 0.0

    def test_ndcg_negative_index_treated_as_irrelevant(self) -> None:
        """Out-of-range indices contribute 0.0 and do not raise."""
        # Index -1 / 99 should be treated as "not in correct_ids" and
        # contribute zero relevance, not an IndexError.
        result = ndcg([99, 0], {"a"}, ["a"], 2)
        # rel = [0.0, 1.0] → DCG = 0 + 1/log2(3); IDCG = 1/log2(2) = 1.0
        assert result == pytest.approx(1.0 / math.log2(3))

    def test_evaluate_retrieval_returns_tuple_of_three(self) -> None:
        result = evaluate_retrieval([0], {"a"}, ["a"], 1)
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert all(isinstance(x, float) for x in result)


# ---------------------------------------------------------------------------
# Additional tests: edge cases beyond the 12-row table
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDcgGradedRelevance:
    """DCG is defined for any non-negative float, not just binary (0/1)."""

    def test_graded_first_rank(self) -> None:
        # rel_0 = 2.0 → DCG@1 = 2.0 / log2(2) = 2.0
        assert dcg([2.0], 1) == pytest.approx(2.0)

    def test_graded_two_ranks(self) -> None:
        # rel_0=3.0, rel_1=1.5 → DCG@2 = 3.0/log2(2) + 1.5/log2(3)
        expected = 3.0 / math.log2(2) + 1.5 / math.log2(3)
        assert dcg([3.0, 1.5], 2) == pytest.approx(expected)

    def test_zero_relevances_give_zero(self) -> None:
        assert dcg([0.0, 0.0, 0.0], 3) == 0.0

    def test_single_item_at_rank_1(self) -> None:
        # DCG@1 for a single item with rel=1.0: 1.0 / log2(2) = 1.0
        assert dcg([1.0], 1) == pytest.approx(1.0)


@pytest.mark.unit
class TestEvaluateRetrievalEdgeCases:
    """Edge cases for evaluate_retrieval not covered by the 12-row table."""

    def test_negative_k_returns_zeros(self) -> None:
        recall_any, recall_all, ndcg_score = evaluate_retrieval([0, 1], {"a"}, ["a", "b"], -1)
        assert recall_any == 0.0
        assert recall_all == 0.0
        assert ndcg_score == 0.0

    def test_single_correct_single_retrieved_hit(self) -> None:
        recall_any, recall_all, ndcg_score = evaluate_retrieval([0], {"a"}, ["a"], 1)
        assert recall_any == 1.0
        assert recall_all == 1.0
        assert ndcg_score == pytest.approx(1.0)

    def test_single_correct_single_retrieved_miss(self) -> None:
        recall_any, recall_all, ndcg_score = evaluate_retrieval([1], {"a"}, ["a", "b"], 1)
        assert recall_any == 0.0
        assert recall_all == 0.0
        # corpus_ids[1] = "b" which is not in correct_ids {"a"} → NDCG=0.
        assert ndcg_score == 0.0

    def test_out_of_range_ranking_index_does_not_raise(self) -> None:
        """Rankings containing indices beyond corpus_ids must not raise."""
        result = evaluate_retrieval([999, 0], {"a"}, ["a", "b"], 2)
        # Index 999 is out of range, treated as irrelevant.
        recall_any, recall_all, ndcg_score = result
        assert isinstance(recall_any, float)
        assert isinstance(recall_all, float)
        assert isinstance(ndcg_score, float)

    def test_all_rankings_miss_correct_ids_not_in_corpus(self) -> None:
        """correct_ids whose values are not present in corpus_ids → 0% recall."""
        recall_any, recall_all, ndcg_score = evaluate_retrieval(
            [0, 1, 2],
            {"phantom_id"},
            ["sess_a", "sess_b", "sess_c"],
            3,
        )
        assert recall_any == 0.0
        assert recall_all == 0.0
        # NDCG is 0 because IDCG would be 0 (no correct docs in corpus).
        assert ndcg_score == 0.0

    def test_recall_all_requires_all_gold_ids_in_top_k(self) -> None:
        """recall_all is 0 if only a subset of gold ids hits top-k."""
        # Gold = {a, b, c}; top-3 contains a and b but not c.
        corpus = ["a", "b", "c", "d", "e"]
        rankings = [0, 1, 3]  # a, b, d — c is missing
        recall_any, recall_all, _ = evaluate_retrieval(rankings, {"a", "b", "c"}, corpus, 3)
        assert recall_any == 1.0  # at least one hit
        assert recall_all == 0.0  # not all three

    def test_k_equals_one_with_correct_at_rank_zero(self) -> None:
        corpus = ["a", "b", "c"]
        recall_any, recall_all, ndcg_score = evaluate_retrieval([0], {"a"}, corpus, 1)
        assert recall_any == 1.0
        assert recall_all == 1.0
        assert ndcg_score == pytest.approx(1.0)


@pytest.mark.unit
class TestNdcgCorrectIdsNotInCorpus:
    """ndcg handles cases where correct_ids contains IDs not in corpus_ids."""

    def test_correct_id_not_in_corpus_means_zero_idcg(self) -> None:
        # correct_ids contains "phantom" which is not in corpus_ids.
        # IDCG is 0 because the ideal ranking can't contain anything.
        # Since IDCG = 0, result is 0.0.
        result = ndcg([0, 1], {"phantom"}, ["a", "b"], 2)
        assert result == 0.0

    def test_mixed_corpus_and_non_corpus_correct_ids(self) -> None:
        # "a" is in corpus; "phantom" is not.
        # n_correct for IDCG = min(|correct_ids|=2, k=2) = 2
        # IDCG@2 = 1/log2(2) + 1/log2(3)
        # Actual ranking [0] → rel=[1.0, (padding to k=2)] → DCG = 1.0
        result = ndcg([0], {"a", "phantom"}, ["a", "b"], 2)
        # DCG = 1.0; IDCG = 1.0 + 1/log2(3)
        expected = 1.0 / (1.0 + 1.0 / math.log2(3))
        assert result == pytest.approx(expected)
