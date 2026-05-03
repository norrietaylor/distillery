"""Textbook information-retrieval scoring primitives.

Implements Discounted Cumulative Gain (DCG), Normalised DCG (NDCG), and a
small wrapper that bundles ``recall_any``, ``recall_all``, and ``NDCG@k``
for the LongMemEval bench.

The formulas are the textbook definitions used across the IR literature:

    DCG@k = sum_{i=1..k} rel_i / log2(i + 1)            # 1-indexed
    NDCG@k = DCG@k / IDCG@k                             # 0.0 if IDCG@k == 0

where ``rel_i`` is the graded relevance of the document at rank ``i``.
This module uses binary relevance (1.0 if the document at that rank is in
``correct_ids``, else 0.0), which is sufficient for the LongMemEval
``answer_session_ids`` evaluation regime.

References:
    * Manning, Raghavan & Schütze, *Introduction to Information Retrieval*
      (Cambridge University Press, 2008), §8.4 "Evaluation of ranked
      retrieval results", which defines DCG and NDCG in their canonical
      form.
    * Wikipedia, "Discounted cumulative gain"
      (https://en.wikipedia.org/wiki/Discounted_cumulative_gain) — the
      ``log2(i + 1)`` discount with 1-indexed ranks is the variant used
      here, equivalent to ``log2(i + 2)`` with 0-indexed positions.

This module deliberately avoids any external IR library (no
``pytrec_eval`` — its C extension breaks ``uvx distillery-mcp`` installs
on toolchain-less hosts) and is not lifted from any other project. The
math is small enough that the accompanying 12-row test table fully
specifies behaviour.
"""

from __future__ import annotations

import math


def dcg(relevances: list[float], k: int) -> float:
    """Compute Discounted Cumulative Gain at rank *k*.

    Uses the standard textbook formula with 0-indexed positions:

        DCG@k = sum_{i=0..min(k, len)-1} rel_i / log2(i + 2)

    which is equivalent to the 1-indexed form
    ``sum_{i=1..k} rel_i / log2(i + 1)``.

    Args:
        relevances: Graded relevance scores in rank order (most relevant
            first). Binary relevance (0.0 / 1.0) is supported; any
            non-negative float is permitted.
        k: Truncation rank. Values larger than ``len(relevances)`` simply
            stop at the end of the list (no out-of-bounds access).

    Returns:
        The DCG value. Returns ``0.0`` when ``k <= 0`` or
        ``relevances`` is empty.
    """
    if k <= 0 or not relevances:
        return 0.0
    cutoff = min(k, len(relevances))
    total = 0.0
    for i in range(cutoff):
        total += relevances[i] / math.log2(i + 2)
    return total


def ndcg(
    rankings: list[int],
    correct_ids: set[str],
    corpus_ids: list[str],
    k: int,
) -> float:
    """Compute Normalised DCG at rank *k* against an ideal ranking.

    Each entry in ``rankings`` is an index into ``corpus_ids``. The
    relevance of the document at rank ``i`` is ``1.0`` if
    ``corpus_ids[rankings[i]]`` is in ``correct_ids``, else ``0.0``. The
    ideal ranking places all ``min(k, len(correct_ids))`` correct
    documents first.

    Args:
        rankings: Indices into ``corpus_ids`` in retrieved order
            (best-ranked first). May be shorter or longer than ``k``.
        correct_ids: Set of corpus IDs considered relevant.
        corpus_ids: The full corpus ID list; ``rankings`` indexes into
            this list.
        k: Truncation rank.

    Returns:
        ``DCG@k / IDCG@k``, or ``0.0`` if there are no correct documents
        (``IDCG@k == 0``).
    """
    if k <= 0 or not rankings:
        return 0.0

    # Build per-rank binary relevance for the predicted ranking.
    relevances: list[float] = []
    for idx in rankings:
        if 0 <= idx < len(corpus_ids) and corpus_ids[idx] in correct_ids:
            relevances.append(1.0)
        else:
            relevances.append(0.0)

    # Ideal ranking: as many 1.0s up front as there are correct docs (capped at k).
    n_correct = min(len(correct_ids), k)
    ideal = [1.0] * n_correct

    idcg = dcg(ideal, k)
    if idcg == 0.0:
        return 0.0
    return dcg(relevances, k) / idcg


def evaluate_retrieval(
    rankings: list[int],
    correct_ids: set[str],
    corpus_ids: list[str],
    k: int,
) -> tuple[float, float, float]:
    """Compute ``(recall_any, recall_all, ndcg@k)`` for a single query.

    ``recall_any`` is ``1.0`` if any correct id appears in the top-*k*
    of ``rankings``, else ``0.0``. ``recall_all`` is ``1.0`` only if
    every correct id appears in the top-*k*. Both are degenerate
    "recall" definitions used by LongMemEval and LongMemEval-style
    evaluations where the question of interest is "did the retriever
    surface the answer at all".

    Args:
        rankings: Indices into ``corpus_ids`` in retrieved order.
        correct_ids: Set of corpus IDs considered relevant.
        corpus_ids: The full corpus ID list.
        k: Truncation rank.

    Returns:
        ``(recall_any, recall_all, ndcg_score)`` as floats.
    """
    if k <= 0 or not rankings or not correct_ids:
        ndcg_score = ndcg(rankings, correct_ids, corpus_ids, k)
        return (0.0, 0.0, ndcg_score)

    top_k_ids: set[str] = set()
    for idx in rankings[:k]:
        if 0 <= idx < len(corpus_ids):
            top_k_ids.add(corpus_ids[idx])

    hits = top_k_ids & correct_ids
    recall_any = 1.0 if hits else 0.0
    recall_all = 1.0 if correct_ids.issubset(top_k_ids) else 0.0
    ndcg_score = ndcg(rankings, correct_ids, corpus_ids, k)
    return (recall_any, recall_all, ndcg_score)
