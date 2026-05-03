"""LongMemEval bench runner — public reproduction of Distillery retrieval.

This module is the heart of the LongMemEval bench: it constructs a fresh
in-memory :class:`~distillery.store.duckdb.DuckDBStore` per question, ingests
the question's ``haystack_sessions`` as :class:`~distillery.models.Entry`
rows, runs the configured query through ``store.search``, scores the result
against the question's ``answer_session_ids``, and emits a JSONL receipt
with full SHA provenance plus a JSON summary.

The runner is deliberately *receipt-first*. Every record carries the
git SHA, dataset revision, dataset file SHA-256, embed model identifier,
Python version, seed, and timestamp so anyone can re-run and diff.

Recency / hybrid trade-off (footgun documentation)
--------------------------------------------------

The W1-recency-toggle-probe audit (``bench/probes/recency-toggle.md`` on
branch ``bench/recency-toggle-probe``) confirmed:

* ``recency_min_weight`` is **construction-time only** on
  :class:`DuckDBStore`. There is no per-query toggle.
* ``hybrid_search`` is also construction-time only — there is no
  per-call kwarg to disable the BM25 leg.
* The vector-only fallback (``hybrid_search=False``) does **not** apply
  recency at all. Recency multiplication lives inside the RRF fusion
  branch only.

Consequences for this runner:

1. ``--recency on|off`` is implemented by varying
   ``recency_min_weight`` between ``0.5`` (default — decay applied) and
   ``1.0`` (decay neutralised). The store is **rebuilt per question**,
   which is cheap with ``:memory:`` and required because per-question
   ingest already drives the loop.
2. ``--retrieval raw`` requires ``hybrid_search=False``, which silently
   bypasses recency entirely. The runner enforces a coupling: when
   ``retrieval == "raw"`` the recency setting is **logged as
   force-bypassed**. The reported ``_meta.effective_recency`` field
   records what actually happened so receipts cannot be misread.
3. A separate dependent issue (filed in the PR body) tracks the
   underlying API ergonomics: a per-query ``recency`` kwarg would
   eliminate this coupling. Until it lands, ``raw + recency=on`` is a
   nonsensical cell and the runner refuses to pretend otherwise.

Filename schema
---------------

Output files include every axis in the filename so cross-axis
comparisons are technically prevented at the filesystem level
(no two cells ever share an output file)::

    bench/results/results_longmemeval_<retrieval>_<granularity>_<recency>_<embed>_<UTC>.jsonl
    bench/results/summary_<retrieval>_<granularity>_<recency>_<embed>_<UTC>.json

Discipline rules enforced here
------------------------------

* PRNG seeds are reset *before* every store rebuild
  (``random.seed`` + ``numpy.random.seed`` if numpy is importable).
* No expected scores are baked into the runner or its docstrings.
* No competitor comparison is constructed.
* Each JSONL record carries the full SHA panel (seven fields).
* Cross-granularity output files differ in name → comparing the two
  is a deliberate filesystem-level act, not an accident.

See the plan in ``/Users/norrie/.claude/plans/look-at-mempalace-hook-dynamic-mccarthy.md``
for the broader context (Wave 2, deliverable 2).
"""

from __future__ import annotations

import json
import logging
import random
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from distillery.embedding.fastembed import FastembedProvider
from distillery.eval.longmemeval_dataset import (
    DATASET_FILE_SHA256,
    DATASET_REVISION_SHA,
    load_longmemeval,
)
from distillery.eval.scoring import evaluate_retrieval
from distillery.models import Entry, EntrySource, EntryType
from distillery.store.duckdb import DuckDBStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type aliases for the public API axes
# ---------------------------------------------------------------------------

RetrievalMode = Literal["raw", "hybrid"]
GranularityMode = Literal["session", "turn"]
RecencyMode = Literal["on", "off"]
EmbedModel = Literal["bge-small", "bge-base", "bge-large", "jina"]


# Recall / NDCG cutoffs reported in the summary.  Per the plan these are the
# triplet R@5, R@10, NDCG@10 — never reported in isolation.
_RECALL_K_VALUES: tuple[int, ...] = (5, 10)
_NDCG_K: int = 10
_SEARCH_LIMIT: int = 50


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuestionRecord:
    """Per-question result emitted as one JSONL line.

    All fields are JSON-serialisable.  The ``_meta`` block carries the
    SHA panel for receipt provenance.
    """

    question_id: str
    question_type: str
    expected_session_ids: list[str]
    retrieved_session_ids: list[str]
    rankings: list[int]
    recall_at_5: float
    recall_all_at_5: float
    ndcg_at_5: float
    recall_at_10: float
    recall_all_at_10: float
    ndcg_at_10: float
    latency_ms: float
    n_corpus_entries: int
    meta: dict[str, Any]


@dataclass
class BenchReport:
    """Summary returned to in-process callers (CLI, tests).

    ``per_question`` keeps the raw records so callers can re-aggregate or
    feed them to a downstream tool.  ``summary`` is the same dict that is
    written to ``summary_<UTC>.json``.
    """

    summary: dict[str, Any]
    per_question: list[QuestionRecord] = field(default_factory=list)
    jsonl_path: Path | None = None
    summary_path: Path | None = None


# ---------------------------------------------------------------------------
# Provenance helpers (SHA panel)
# ---------------------------------------------------------------------------


def _git_sha() -> str:
    """Best-effort short-hand for ``git rev-parse HEAD``.

    Returns ``"unknown"`` when the runner is invoked outside a git
    checkout (e.g. installed wheel) so the SHA panel is always present
    even if one field is degraded.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _embed_model_sha(provider: FastembedProvider | Any) -> str:
    """Best-effort SHA / version identifier for the active embed provider.

    For :class:`FastembedProvider` we publish the resolved model name
    plus the installed fastembed package version — the model file
    weights live under ``~/.cache/fastembed/<name>`` and the file SHA
    isn't trivially stable across the provider's lazy loader, so the
    package version + model name pair is the practical receipt.

    For other providers (e.g. Jina remote API) we fall back to
    ``"<model_name>@unknown"`` since hosted services don't expose an
    immutable SHA.
    """
    model_name = getattr(provider, "model_name", "unknown")
    if isinstance(provider, FastembedProvider):
        try:
            from importlib.metadata import version as _pkg_version

            pkg_version = _pkg_version("fastembed")
        except Exception:  # pragma: no cover - import-metadata fallback
            pkg_version = "unknown"
        return f"fastembed=={pkg_version}/{model_name}"
    return f"{model_name}@unknown"


def _build_meta_panel(
    *,
    git_sha: str,
    embed_model_sha: str,
    seed: int,
    retrieval: RetrievalMode,
    granularity: GranularityMode,
    recency: RecencyMode,
    effective_recency: RecencyMode,
) -> dict[str, Any]:
    """Build the per-record SHA / provenance panel.

    All seven required fields are present unconditionally — receipts
    with a missing field would defeat the audit trail.
    """
    return {
        "git_sha": git_sha,
        "dataset_revision_sha": DATASET_REVISION_SHA,
        "dataset_file_sha256": DATASET_FILE_SHA256,
        "embed_model_sha": embed_model_sha,
        "python_version": sys.version,
        "seed": seed,
        "timestamp_utc": datetime.now(tz=UTC).isoformat(),
        # Mode echoes — useful when records from multiple cells are
        # accidentally concatenated for analysis.
        "retrieval": retrieval,
        "granularity": granularity,
        "recency_requested": recency,
        "effective_recency": effective_recency,
    }


# ---------------------------------------------------------------------------
# Embedding-provider construction
# ---------------------------------------------------------------------------


def _build_embedding_provider(model: EmbedModel) -> Any:
    """Return an :class:`EmbeddingProvider` for the chosen model.

    Args:
        model: One of ``"bge-small"``, ``"bge-base"``, ``"bge-large"``
            (all served by :class:`FastembedProvider`) or ``"jina"`` —
            which routes to the existing remote provider and requires
            ``JINA_API_KEY``.

    Raises:
        ImportError: If the requested provider's optional dependency is
            missing.  ``fastembed`` lives in ``[fastembed]``; the Jina
            provider depends only on the runtime ``httpx`` install.
    """
    if model == "jina":
        # Local import: avoids dragging the Jina module into the import
        # graph for the (much more common) fastembed bench cells.
        from distillery.embedding.jina import JinaEmbeddingProvider

        return JinaEmbeddingProvider()
    return FastembedProvider(model=model)


# ---------------------------------------------------------------------------
# Date parsing — LongMemEval's slightly weird format
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(
    r"^(?P<y>\d{4})/(?P<m>\d{2})/(?P<d>\d{2}).*?(?P<hh>\d{1,2}):(?P<mm>\d{2})\s*$"
)


def _parse_haystack_date(value: str) -> datetime:
    """Parse a LongMemEval haystack date like ``"2024/06/01 (Sat) 09:00"``.

    The dataset embeds a weekday in parentheses between the date and
    the time-of-day; we discard it.  Returns a UTC-aware datetime.
    Falls back to :func:`datetime.now` on parse failure so a single
    malformed date doesn't crash the whole bench.
    """
    if not isinstance(value, str):
        return datetime.now(tz=UTC)
    match = _DATE_RE.match(value.strip())
    if not match:
        return datetime.now(tz=UTC)
    return datetime(
        int(match["y"]),
        int(match["m"]),
        int(match["d"]),
        int(match["hh"]),
        int(match["mm"]),
        tzinfo=UTC,
    )


# ---------------------------------------------------------------------------
# Corpus construction — turn vs session granularity
# ---------------------------------------------------------------------------


def _flatten_session_text(turns: list[dict[str, Any]]) -> str:
    """Join all turns of a session into one ingest-ready text blob."""
    parts: list[str] = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if isinstance(content, str) and content:
            parts.append(f"{role}: {content}")
    return "\n".join(parts)


def _build_corpus(
    question: dict[str, Any],
    granularity: GranularityMode,
) -> tuple[list[Entry], list[str]]:
    """Build the corpus for a single question.

    Returns ``(entries, corpus_session_ids)`` where ``corpus_session_ids[i]``
    is the session id of ``entries[i]`` (used by the scorer).  For
    ``granularity == "turn"`` each user-role turn produces a separate
    entry whose synthetic id is ``f"{session_id}_turn_{turn_idx}"`` —
    the ``_turn_`` separator matches the mempalace convention so a
    downstream consumer can split it back to the source session id.
    """
    haystack_sessions: list[list[dict[str, Any]]] = question.get("haystack_sessions", [])
    haystack_session_ids: list[str] = question.get("haystack_session_ids", [])
    haystack_dates: list[str] = question.get("haystack_dates", [])

    entries: list[Entry] = []
    corpus_ids: list[str] = []

    for sess_idx, (turns, sess_id) in enumerate(
        zip(haystack_sessions, haystack_session_ids, strict=False)
    ):
        date_str = haystack_dates[sess_idx] if sess_idx < len(haystack_dates) else ""
        created_at = _parse_haystack_date(date_str)

        if granularity == "session":
            content = _flatten_session_text(turns)
            if not content:
                continue
            entries.append(
                Entry(
                    content=content,
                    entry_type=EntryType.SESSION,
                    source=EntrySource.IMPORT,
                    author="longmemeval",
                    created_at=created_at,
                    updated_at=created_at,
                    metadata={"session_id": sess_id, "haystack_date": date_str},
                )
            )
            corpus_ids.append(sess_id)
            continue

        # granularity == "turn": one entry per *user* turn so the index
        # space is predictable and matches LongMemEval's question framing
        # (the question targets user-side recall).
        for turn_idx, turn in enumerate(turns):
            if not isinstance(turn, dict) or turn.get("role") != "user":
                continue
            content = str(turn.get("content", "")).strip()
            if not content:
                continue
            turn_id = f"{sess_id}_turn_{turn_idx}"
            entries.append(
                Entry(
                    content=content,
                    entry_type=EntryType.SESSION,
                    source=EntrySource.IMPORT,
                    author="longmemeval",
                    created_at=created_at,
                    updated_at=created_at,
                    metadata={
                        "session_id": turn_id,
                        "source_session_id": sess_id,
                        "turn_index": turn_idx,
                        "haystack_date": date_str,
                    },
                )
            )
            corpus_ids.append(turn_id)

    return entries, corpus_ids


def _expected_id_set(
    question: dict[str, Any],
    granularity: GranularityMode,
    corpus_ids: list[str],
) -> set[str]:
    """Return the set of corpus ids considered correct for this question.

    Session-granularity: the gold ``answer_session_ids`` map directly
    to corpus ids.  Turn-granularity: any synthetic ``<sess>_turn_<i>``
    derived from a gold session id counts as correct.
    """
    answer_ids: list[str] = question.get("answer_session_ids", [])
    answers = set(answer_ids)
    if granularity == "session":
        return answers
    expected: set[str] = set()
    for corpus_id in corpus_ids:
        if "_turn_" in corpus_id:
            base = corpus_id.split("_turn_", 1)[0]
            if base in answers:
                expected.add(corpus_id)
    return expected


# ---------------------------------------------------------------------------
# Per-question seed handling
# ---------------------------------------------------------------------------


def _seed_prng(seed: int) -> None:
    """Set ``random`` and (best-effort) ``numpy.random`` seeds.

    Called *before* every store rebuild so HNSW insertion-order
    non-determinism is neutralised on a per-question basis.  numpy is
    optional — fastembed pulls it transitively but the runner doesn't
    require it, so we degrade gracefully if it isn't importable.
    """
    random.seed(seed)
    try:
        import numpy as np  # local import: numpy is optional at module level

        np.random.seed(seed)
    except ImportError:  # pragma: no cover - numpy absent
        logger.debug("numpy not importable; skipping numpy.random.seed")


# ---------------------------------------------------------------------------
# Per-question evaluation
# ---------------------------------------------------------------------------


async def _run_one_question(
    question: dict[str, Any],
    *,
    seed: int,
    retrieval: RetrievalMode,
    granularity: GranularityMode,
    recency: RecencyMode,
    embed_model: EmbedModel,
    git_sha: str,
) -> QuestionRecord:
    """Build a fresh store, ingest the haystack, search, and score.

    Returns a fully-populated :class:`QuestionRecord`.  The PRNG seed is
    set *before* the store is constructed so HNSW insertion-order
    non-determinism is bounded by the seed.
    """
    _seed_prng(seed)

    embedder = _build_embedding_provider(embed_model)

    # Decide effective hybrid + recency settings.  See the module
    # docstring for the rationale: raw retrieval implicitly disables
    # recency because the vector-only path does not multiply by
    # ``_recency_weight``.
    use_hybrid = retrieval == "hybrid"
    if retrieval == "raw":
        # Vector-only path bypasses recency entirely; any non-default
        # ``recency_min_weight`` is moot.  Record what actually happened.
        effective_recency: RecencyMode = "off"
        recency_min_weight = 1.0
    else:
        effective_recency = recency
        recency_min_weight = 1.0 if recency == "off" else 0.5

    store = DuckDBStore(
        db_path=":memory:",
        embedding_provider=embedder,
        hybrid_search=use_hybrid,
        recency_min_weight=recency_min_weight,
    )
    await store.initialize()

    try:
        entries, corpus_ids = _build_corpus(question, granularity)
        if entries:
            await store.store_batch(entries)

        question_text = str(question.get("question", ""))
        question_id = str(question.get("question_id", ""))
        question_type = str(question.get("question_type", "unknown"))

        start = time.perf_counter()
        results = await store.search(query=question_text, filters=None, limit=_SEARCH_LIMIT)
        latency_ms = (time.perf_counter() - start) * 1000.0

        # Map results back to corpus session ids.  Build a positional
        # lookup so ``rankings`` indexes into ``corpus_ids``.
        position_by_id: dict[str, int] = {sid: i for i, sid in enumerate(corpus_ids)}
        rankings: list[int] = []
        retrieved_session_ids: list[str] = []
        for result in results:
            sid = result.entry.metadata.get("session_id") if result.entry.metadata else None
            if not isinstance(sid, str):
                continue
            retrieved_session_ids.append(sid)
            if sid in position_by_id:
                rankings.append(position_by_id[sid])

        expected_ids = _expected_id_set(question, granularity, corpus_ids)
        # Compute (recall_any, recall_all, ndcg) at each k so we always
        # publish the triplet R@5, R@10, NDCG@10 (discipline rule 2).
        r5_any, r5_all, ndcg5 = evaluate_retrieval(rankings, expected_ids, corpus_ids, 5)
        r10_any, r10_all, ndcg10 = evaluate_retrieval(rankings, expected_ids, corpus_ids, _NDCG_K)

        meta = _build_meta_panel(
            git_sha=git_sha,
            embed_model_sha=_embed_model_sha(embedder),
            seed=seed,
            retrieval=retrieval,
            granularity=granularity,
            recency=recency,
            effective_recency=effective_recency,
        )

        return QuestionRecord(
            question_id=question_id,
            question_type=question_type,
            expected_session_ids=sorted(expected_ids),
            retrieved_session_ids=retrieved_session_ids,
            rankings=rankings,
            recall_at_5=r5_any,
            recall_all_at_5=r5_all,
            ndcg_at_5=ndcg5,
            recall_at_10=r10_any,
            recall_all_at_10=r10_all,
            ndcg_at_10=ndcg10,
            latency_ms=latency_ms,
            n_corpus_entries=len(entries),
            meta=meta,
        )
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# Aggregation — mean over questions, broken out per question_type
# ---------------------------------------------------------------------------


def _aggregate(records: list[QuestionRecord]) -> dict[str, Any]:
    """Build the summary dict shape written to ``summary_*.json``."""

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    overall_r5 = _mean([r.recall_at_5 for r in records])
    overall_r10 = _mean([r.recall_at_10 for r in records])
    overall_ndcg10 = _mean([r.ndcg_at_10 for r in records])

    by_type: dict[str, dict[str, Any]] = {}
    types_seen: set[str] = {r.question_type for r in records}
    for qtype in sorted(types_seen):
        bucket = [r for r in records if r.question_type == qtype]
        by_type[qtype] = {
            "n": len(bucket),
            "recall_at_5": _mean([r.recall_at_5 for r in bucket]),
            "recall_at_10": _mean([r.recall_at_10 for r in bucket]),
            "ndcg_at_10": _mean([r.ndcg_at_10 for r in bucket]),
        }

    return {
        "n_questions": len(records),
        "overall": {
            "recall_at_5": overall_r5,
            "recall_at_10": overall_r10,
            "ndcg_at_10": overall_ndcg10,
        },
        "per_question_type": by_type,
    }


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _utc_stamp() -> str:
    """Return a UTC timestamp suitable for filenames (no colons)."""
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def _record_to_jsonl_dict(record: QuestionRecord) -> dict[str, Any]:
    """Serialise a record to a JSONL-friendly dict."""
    payload = asdict(record)
    # asdict copies ``meta`` as-is; promote it to ``_meta`` for the
    # discipline-rule-(5) audit panel name used in the plan.
    payload["_meta"] = payload.pop("meta")
    return payload


def _write_outputs(
    records: list[QuestionRecord],
    summary: dict[str, Any],
    output_dir: Path,
    *,
    retrieval: RetrievalMode,
    granularity: GranularityMode,
    recency: RecencyMode,
    embed_model: EmbedModel,
    stamp: str,
) -> tuple[Path, Path]:
    """Write the JSONL + summary files; return ``(jsonl_path, summary_path)``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    base = f"longmemeval_{retrieval}_{granularity}_{recency}_{embed_model}_{stamp}"
    jsonl_path = output_dir / f"results_{base}.jsonl"
    summary_path = output_dir / f"summary_{base}.json"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(_record_to_jsonl_dict(record)) + "\n")

    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    return jsonl_path, summary_path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_longmemeval_bench(
    *,
    retrieval: RetrievalMode = "hybrid",
    granularity: GranularityMode = "session",
    recency: RecencyMode = "on",
    embed_model: EmbedModel = "bge-small",
    limit: int | None = None,
    seeds: int = 1,
    output_dir: Path | None = None,
    questions: list[dict[str, Any]] | None = None,
) -> BenchReport:
    """Run the LongMemEval bench end-to-end and return a :class:`BenchReport`.

    Parameters
    ----------
    retrieval:
        ``"hybrid"`` (BM25 + vector RRF, default) or ``"raw"``
        (vector-only).  ``"raw"`` implicitly forces ``recency=off``
        because the vector-only path in :class:`DuckDBStore` does not
        apply the recency multiplier — see the module docstring for the
        footgun documentation.
    granularity:
        ``"session"`` (one corpus entry per haystack session — the
        headline configuration) or ``"turn"`` (one entry per user-role
        turn).  Cross-granularity numbers are non-comparable.
    recency:
        ``"on"`` to use the default 90-day decay
        (``recency_min_weight=0.5``) or ``"off"`` to neutralise it
        (``recency_min_weight=1.0``).  Effective only when
        ``retrieval="hybrid"``.
    embed_model:
        ``"bge-small"`` (default), ``"bge-base"``, ``"bge-large"`` —
        all routed through :class:`FastembedProvider` — or ``"jina"``
        which uses the remote :class:`JinaEmbeddingProvider`.
    limit:
        Optional cap on the number of questions evaluated.  ``None``
        runs the full set.
    seeds:
        Number of seed values to sweep per question.  Each question is
        evaluated once per seed; the seed is the question index plus a
        per-seed offset so any divergence is attributable.  Defaults to
        ``1`` to keep the smoke-test path quick.
    output_dir:
        Directory to write JSONL + summary files into.  When ``None``,
        no files are written and the caller can read
        :attr:`BenchReport.per_question` directly.
    questions:
        Optional pre-loaded question list.  Provided for tests and
        callers that already have the dataset in memory; defaults to
        :func:`load_longmemeval` which downloads from HuggingFace under
        the pinned revision.

    Returns
    -------
    BenchReport
        ``BenchReport.summary`` is the aggregate dict; ``per_question``
        is the per-record list; ``jsonl_path`` and ``summary_path`` are
        populated when ``output_dir`` is set.

    Notes
    -----
    The runner makes **no** prediction about expected scores.  The
    discipline gate (variance characterisation) lives in W3 and is the
    first place an "expected to land near X" claim is permitted to
    appear.  This module never bakes one in.
    """
    if questions is None:
        questions = load_longmemeval()

    if limit is not None:
        questions = questions[:limit]

    git_sha = _git_sha()
    all_records: list[QuestionRecord] = []

    for seed_offset in range(max(1, seeds)):
        for q_idx, question in enumerate(questions):
            # Seed is question-index + seed-offset so two seeds for the
            # same question diverge predictably.
            seed = q_idx + seed_offset * 100_000
            record = await _run_one_question(
                question,
                seed=seed,
                retrieval=retrieval,
                granularity=granularity,
                recency=recency,
                embed_model=embed_model,
                git_sha=git_sha,
            )
            all_records.append(record)

    summary = _aggregate(all_records)
    summary["axes"] = {
        "retrieval": retrieval,
        "granularity": granularity,
        "recency": recency,
        "embed_model": embed_model,
        "seeds": max(1, seeds),
        "limit": limit,
    }
    summary["dataset"] = {
        "revision_sha": DATASET_REVISION_SHA,
        "file_sha256": DATASET_FILE_SHA256,
    }
    summary["git_sha"] = git_sha
    summary["timestamp_utc"] = datetime.now(tz=UTC).isoformat()

    jsonl_path: Path | None = None
    summary_path: Path | None = None
    if output_dir is not None:
        stamp = _utc_stamp()
        jsonl_path, summary_path = _write_outputs(
            all_records,
            summary,
            output_dir,
            retrieval=retrieval,
            granularity=granularity,
            recency=recency,
            embed_model=embed_model,
            stamp=stamp,
        )

    return BenchReport(
        summary=summary,
        per_question=all_records,
        jsonl_path=jsonl_path,
        summary_path=summary_path,
    )


__all__ = [
    "BenchReport",
    "EmbedModel",
    "GranularityMode",
    "QuestionRecord",
    "RecencyMode",
    "RetrievalMode",
    "run_longmemeval_bench",
]
