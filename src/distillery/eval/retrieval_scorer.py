"""Retrieval quality scoring for eval scenarios.

Computes precision@k, recall@k, and MRR (mean reciprocal rank) by comparing
MCP tool-call search results against golden relevance labels.  Optionally
computes faithfulness when the ``ragas`` package and an LLM judge API key are
available.

The module is importable without ``ragas`` installed -- all RAGAS-dependent
logic is gated behind :data:`HAS_RAGAS`.

Usage::

    from distillery.eval.retrieval_scorer import score_retrieval

    metrics = score_retrieval(
        results=tool_call_records,
        golden_labels=[{"entry_id": "abc", "relevant": True}, ...],
        k=5,
    )
    print(metrics.precision, metrics.recall, metrics.mrr)
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from distillery.eval.models import ToolCallRecord

# ---------------------------------------------------------------------------
# Graceful RAGAS import
# ---------------------------------------------------------------------------

HAS_RAGAS: bool
"""True when the ``ragas`` package is importable."""

try:
    import ragas as _ragas  # noqa: F401

    HAS_RAGAS = True
except ImportError:
    HAS_RAGAS = False


# ---------------------------------------------------------------------------
# RetrievalMetrics
# ---------------------------------------------------------------------------


@dataclass
class RetrievalMetrics:
    """Quality metrics for a single retrieval scenario.

    Attributes:
        precision: Precision at *k* (fraction of top-k results that are relevant).
        recall: Recall at *k* (fraction of relevant items found in top-k).
        mrr: Mean reciprocal rank (1 / rank of first relevant result, or 0).
        faithfulness: Optional LLM-judge faithfulness score from RAGAS.
    """

    precision: float | None = None
    recall: float | None = None
    mrr: float | None = None
    faithfulness: float | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_entry_ids(results: Sequence[ToolCallRecord]) -> list[str]:
    """Extract entry IDs from search tool-call responses.

    The scorer inspects each :class:`ToolCallRecord` response payload for a
    ``results`` list (as returned by ``distillery_search``).  Each element is
    expected to have an ``"id"`` or ``"entry_id"`` key.
    """
    entry_ids: list[str] = []
    for record in results:
        response_results: Any = record.response.get("results", [])
        if not isinstance(response_results, list):
            continue
        for item in response_results:
            if not isinstance(item, dict):
                continue
            eid = item.get("id") or item.get("entry_id")
            if isinstance(eid, str):
                entry_ids.append(eid)
    return entry_ids


def _build_relevance_set(golden_labels: Sequence[dict[str, Any]]) -> set[str]:
    """Return the set of entry IDs marked as relevant in the golden labels.

    Each label dict is expected to have ``"entry_id"`` (str) and ``"relevant"``
    (bool) keys.
    """
    return {str(label["entry_id"]) for label in golden_labels if label.get("relevant", False)}


def _precision_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    """Compute precision at *k*."""
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    relevant_in_top_k = sum(1 for eid in top_k if eid in relevant)
    return relevant_in_top_k / len(top_k)


def _recall_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    """Compute recall at *k*."""
    if not relevant:
        return 0.0
    top_k = retrieved[:k]
    relevant_in_top_k = sum(1 for eid in top_k if eid in relevant)
    return relevant_in_top_k / len(relevant)


def _mrr(retrieved: Sequence[str], relevant: set[str]) -> float:
    """Compute mean reciprocal rank (reciprocal rank of the first relevant result)."""
    for rank, eid in enumerate(retrieved, start=1):
        if eid in relevant:
            return 1.0 / rank
    return 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_retrieval(
    results: list[ToolCallRecord],
    golden_labels: list[dict[str, Any]],
    k: int = 5,
    *,
    enable_faithfulness: bool = False,
    query: str | None = None,
    response_text: str | None = None,
) -> RetrievalMetrics:
    """Score retrieval quality against golden relevance labels.

    Args:
        results: Tool-call records from a retrieval scenario run (typically
            from calls to ``distillery_search``).
        golden_labels: List of dicts, each with ``"entry_id"`` (str) and
            ``"relevant"`` (bool) indicating whether the entry is relevant to
            the query.
        k: The cutoff for precision and recall computation.
        enable_faithfulness: When ``True`` and ``ragas`` is installed, compute
            faithfulness using an LLM judge.  Requires the ``OPENAI_API_KEY``
            environment variable to be set.
        query: The retrieval query text (required for faithfulness scoring).
        response_text: The final response text (required for faithfulness
            scoring).

    Returns:
        :class:`RetrievalMetrics` with computed metrics.  Fields are ``None``
        only when they cannot be computed (e.g. no results at all).
    """
    retrieved_ids = _extract_entry_ids(results)
    relevant_set = _build_relevance_set(golden_labels)

    # Core metrics -- always computable if we have results
    precision: float | None = None
    recall: float | None = None
    mrr_val: float | None = None

    if retrieved_ids:
        precision = _precision_at_k(retrieved_ids, relevant_set, k)
        recall = _recall_at_k(retrieved_ids, relevant_set, k)
        mrr_val = _mrr(retrieved_ids, relevant_set)
    elif not retrieved_ids and relevant_set:
        # No results but there are relevant items -- all metrics are 0
        precision = 0.0
        recall = 0.0
        mrr_val = 0.0

    faithfulness: float | None = None
    if enable_faithfulness and HAS_RAGAS and query and response_text:
        faithfulness = _compute_faithfulness(query, response_text, results)

    return RetrievalMetrics(
        precision=precision,
        recall=recall,
        mrr=mrr_val,
        faithfulness=faithfulness,
    )


def _compute_faithfulness(
    query: str,
    response_text: str,
    results: list[ToolCallRecord],
) -> float | None:
    """Compute RAGAS faithfulness if API key is available.

    Returns ``None`` when the required API key is missing or when RAGAS
    evaluation raises an exception.
    """
    if not HAS_RAGAS:
        return None

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from ragas import evaluate  # noqa: I001
        from ragas.metrics import faithfulness as faithfulness_metric

        # Build contexts from tool call responses
        contexts: list[str] = []
        for record in results:
            response_results: Any = record.response.get("results", [])
            if isinstance(response_results, list):
                for item in response_results:
                    if isinstance(item, dict):
                        content = item.get("content", "")
                        if isinstance(content, str) and content:
                            contexts.append(content)

        if not contexts:
            return None

        # RAGAS evaluate expects a Dataset-like input
        from datasets import Dataset

        eval_dataset = Dataset.from_dict(
            {
                "question": [query],
                "answer": [response_text],
                "contexts": [contexts],
            }
        )

        result = evaluate(eval_dataset, metrics=[faithfulness_metric])
        score: Any = result.get("faithfulness")
        if isinstance(score, (int, float)):
            return float(score)
        return None
    except Exception:
        return None
