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
    # 13. correct_ids contains labels NOT in the corpus slice. IDCG must be
    #     sized from the *intersection* of correct_ids and corpus_ids — not
    #     from len(correct_ids) — otherwise NDCG is artificially depressed.
    #     Here corpus = ["x"], correct = {"x", "y"}: only "x" is reachable.
    #     rankings=[0] → relevance "x" found at rank 0 → DCG = 1.0.
    #     IDCG (post-fix) = 1.0 (one reachable correct doc), so NDCG = 1.0.
    #     Pre-fix this would have used n_correct=2 → IDCG = 1 + 1/log2(3),
    #     yielding NDCG ≈ 0.6131 instead of 1.0.
    #     recall_any=1.0 because "x" appears in top-k; recall_all=0.0 because
    #     "y" is required by ``evaluate_retrieval`` but absent from corpus.
    (
        "correct_id_outside_corpus_k1",
        [0],
        {"x", "y"},
        ["x"],
        1,
        1.0,
        0.0,
        1.0,
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
        """Out-of-range indices contribute 0.0 and do not raise.

        Python list indexing accepts negative integers (``corpus_ids[-1]`` is
        the last element), so the bounds guard ``0 <= idx < len(corpus_ids)``
        in ``ndcg`` is what prevents a negative index from silently sneaking
        through. Pass ``-1`` here (not the previous ``99``) to actually
        exercise the negative branch of that guard.
        """
        result = ndcg([-1, 0], {"a"}, ["a"], 2)
        # rel = [0.0, 1.0] → DCG = 0 + 1/log2(3); IDCG = 1/log2(2) = 1.0
        assert result == pytest.approx(1.0 / math.log2(3))

    def test_evaluate_retrieval_returns_tuple_of_three(self) -> None:
        result = evaluate_retrieval([0], {"a"}, ["a"], 1)
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert all(isinstance(x, float) for x in result)
