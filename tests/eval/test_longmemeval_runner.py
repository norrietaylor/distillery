"""Unit tests for the LongMemEval bench runner.

These tests pin the runner's contracts against the
``tests/fixtures/longmemeval_mini.json`` fixture (2 hand-crafted
questions) and the deterministic in-test embedding provider so we
verify behaviour without downloading the real 264 MB dataset or
loading the ~67 MB fastembed weights.

Coverage:

* **Happy path:** runs end-to-end against the fixture, returns a
  populated :class:`BenchReport`, and writes a JSONL + summary file.
* **session_id round-trip:** confirms an ingested session's id flows
  back into ``QuestionRecord.retrieved_session_ids`` (belt-and-braces
  alongside the W1 ``test_session_id_round_trip.py`` store-level test).
* **Granularity=turn produces more entries than session:** a sanity
  check that the ``_build_corpus`` branch is doing what its name says.
* **Recency=off vs on differ in result ordering:** confirms the
  ``--recency`` toggle propagates through to the actual ordering when
  date metadata is meaningful.
* **SHA panel populated:** every JSONL record must carry the seven
  fields from discipline rule 5 — ``git_sha``,
  ``dataset_revision_sha``, ``dataset_file_sha256``,
  ``embed_model_sha``, ``python_version``, ``seed``, ``timestamp_utc``.

The runner takes pre-loaded ``questions=`` so the fixture path skips
the HuggingFace download entirely.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from distillery.eval import longmemeval as bench
from distillery.eval.longmemeval import (
    BenchReport,
    QuestionRecord,
    _build_corpus,
    _expected_id_set,
    run_longmemeval_bench,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixture loader
# ---------------------------------------------------------------------------

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "longmemeval_mini.json"


def _load_fixture() -> list[dict[str, Any]]:
    """Read the bundled mini fixture (two hand-crafted questions)."""
    with FIXTURE_PATH.open() as f:
        data: list[dict[str, Any]] = json.load(f)
    return data


# ---------------------------------------------------------------------------
# Embedding provider stub — keyword-matching so we don't load real weights
# ---------------------------------------------------------------------------


class _KeywordEmbedder:
    """Tiny deterministic embedder: builds a unit vector from keyword hits.

    The vector dimensions are a fixed lexicon of words that appear in
    both the fixture questions and the haystack sessions.  Documents
    and queries are vectorised by counting occurrences of each lexicon
    word — so the cosine between a query and a relevant haystack
    session is high without any network or weights involved.
    """

    _LEXICON = (
        "lisbon",
        "moving",
        "city",
        "vacation",
        "packing",
        "cats",
        "cat",
        "mochi",
        "yuzu",
        "soba",
        "adopted",
        "third",
        "feline",
    )

    def __init__(self) -> None:
        self._dim = len(self._LEXICON)

    def _vec(self, text: str) -> list[float]:
        lowered = text.lower()
        raw = [float(lowered.count(word)) for word in self._LEXICON]
        # L2-normalise so cosine similarity is well-defined.
        magnitude = sum(x * x for x in raw) ** 0.5 or 1.0
        return [x / magnitude for x in raw]

    def embed(self, text: str) -> list[float]:
        return self._vec(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    @property
    def dimensions(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return "keyword-stub-test"


@pytest.fixture(autouse=True)
def _patch_embed_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the runner's embedder factory with the keyword stub.

    Applied autouse so every test in this module runs against the
    deterministic keyword embedder rather than fastembed (which would
    require downloading weights on first call).
    """

    def _stub(_model: str) -> _KeywordEmbedder:
        return _KeywordEmbedder()

    monkeypatch.setattr(bench, "_build_embedding_provider", _stub)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_happy_path_runs_against_fixture(tmp_path: Path) -> None:
    """End-to-end smoke test: returns a populated report with R@5 hit on q1.

    The first fixture question targets ``answer_session_alpha`` which
    contains the literal string "moving to Lisbon".  The keyword
    embedder gives that haystack session the highest cosine, so
    ``recall_at_5`` for that question must be exactly ``1.0``.
    """
    questions = _load_fixture()

    report = await run_longmemeval_bench(
        retrieval="hybrid",
        granularity="session",
        recency="on",
        embed_model="bge-small",
        questions=questions,
        output_dir=tmp_path,
    )

    assert isinstance(report, BenchReport)
    assert report.summary["n_questions"] == len(questions)
    assert report.jsonl_path is not None and report.jsonl_path.exists()
    assert report.summary_path is not None and report.summary_path.exists()

    # The first question is hand-crafted to be trivially solvable; recall
    # at 5 must hit.
    q1 = next(r for r in report.per_question if r.question_id == "fixture_q1")
    assert q1.recall_at_5 == 1.0, (
        f"Hand-crafted easy question should hit at 5; got {q1.recall_at_5} "
        f"(expected={q1.expected_session_ids}, got={q1.retrieved_session_ids})"
    )

    # Aggregate summary keys exist and are well-formed.
    assert "overall" in report.summary
    overall = report.summary["overall"]
    for key in ("recall_at_5", "recall_at_10", "ndcg_at_10"):
        assert key in overall
        assert 0.0 <= overall[key] <= 1.0

    # Per-question-type breakdown is keyed by the dataset's question_type
    # field — the fixture has both "single-session-user" and
    # "multi-session" so both keys are present.
    types = report.summary["per_question_type"]
    assert "single-session-user" in types
    assert "multi-session" in types


async def test_session_id_round_trips_through_runner() -> None:
    """The session_id we ingest comes back in ``retrieved_session_ids``.

    Belt-and-braces alongside ``tests/eval/test_session_id_round_trip.py``
    which pins the store-level contract.  Here we confirm the runner
    plumbing end-to-end: ingest with ``metadata.session_id=X``, search,
    and observe ``X`` in the result record.
    """
    questions = _load_fixture()

    report = await run_longmemeval_bench(
        retrieval="hybrid",
        granularity="session",
        recency="off",  # neutralise decay so the test isn't time-dependent
        embed_model="bge-small",
        questions=questions[:1],  # only the easy "Lisbon" question
    )

    record = report.per_question[0]
    assert record.retrieved_session_ids, "No session ids were retrieved"
    # The gold answer id must appear among retrieved ids.
    assert "answer_session_alpha" in record.retrieved_session_ids


async def test_granularity_turn_yields_more_entries_than_session() -> None:
    """``granularity=turn`` produces ≥ as many corpus entries per question.

    For the fixture, every haystack session has at least one user turn,
    so the turn-granularity corpus must be **strictly** larger than the
    session-granularity corpus for question 1 (3 sessions × ≥1 user
    turn each = 3 entries — same count, but the IDs differ).  We check
    the strict inequality on a question with multiple user turns per
    session — none in the fixture, so we synthesise a richer scenario
    inline.
    """
    questions = _load_fixture()

    # Augment q1 to have a session with multiple user turns so the
    # turn vs session entry counts diverge clearly.
    augmented = dict(questions[0])
    augmented["haystack_sessions"] = [
        [
            {"role": "user", "content": "user turn 1"},
            {"role": "assistant", "content": "asst reply"},
            {"role": "user", "content": "user turn 2"},
            {"role": "user", "content": "user turn 3"},
        ],
    ]
    augmented["haystack_session_ids"] = ["multi_turn_session"]
    augmented["haystack_dates"] = ["2024/06/01 (Sat) 09:00"]

    sess_entries, sess_ids = _build_corpus(augmented, "session")
    turn_entries, turn_ids = _build_corpus(augmented, "turn")

    assert len(sess_entries) == 1
    assert len(turn_entries) == 3, (
        f"Expected 3 user-turn entries; got {len(turn_entries)}: {turn_ids}"
    )
    # Synthetic ids carry the ``_turn_`` separator that mempalace uses
    # so per-turn results round-trip back to the source session id.
    assert all("_turn_" in tid for tid in turn_ids)

    # ``_expected_id_set`` should map gold ids to all matching turns.
    expected_session = _expected_id_set(augmented, "session", sess_ids)
    expected_turn = _expected_id_set(augmented, "turn", turn_ids)
    # Gold ids in the fixture (``answer_session_alpha``) don't match the
    # synthesised id ("multi_turn_session"), so both should be empty —
    # but the function must not crash and must return a set.
    assert isinstance(expected_session, set)
    assert isinstance(expected_turn, set)


async def test_recency_off_vs_on_changes_ordering() -> None:
    """The recency toggle changes the ordering for a date-sensitive case.

    Hand-craft a question with two haystack sessions that have **near
    identical lexical relevance** to the query but very different
    dates:

    * ``recent_session`` — same keyword content, dated *today*.
    * ``old_session`` — same keyword content, dated *3 years ago*.

    With ``recency=on`` the older session should be down-weighted via
    the linear decay; the recent session should rank above it.  With
    ``recency=off`` (``recency_min_weight=1.0``) the multiplier is
    neutralised and the two should tie — the order then depends on
    DuckDB's stable-but-unspecified tie-break.  We assert that at
    minimum the two orderings differ, *or* that the recent session
    wins under ``on`` and either is acceptable under ``off``.
    """
    today = datetime.now(tz=UTC)
    long_ago = today - timedelta(days=1100)  # ~3 years; far past 90-day window

    def _fmt(dt: datetime) -> str:
        return dt.strftime("%Y/%m/%d (Mon) %H:%M")

    question = {
        "question_id": "recency_probe",
        "question_type": "single-session-user",
        "question": "moving to Lisbon",
        "question_date": _fmt(today),
        # Both haystacks count toward the gold set so we focus on
        # ordering, not relevance.
        "answer_session_ids": ["recent_session", "old_session"],
        "haystack_session_ids": ["old_session", "recent_session"],
        "haystack_dates": [_fmt(long_ago), _fmt(today)],
        "haystack_sessions": [
            [{"role": "user", "content": "I am moving to Lisbon next month."}],
            [{"role": "user", "content": "I am moving to Lisbon next month."}],
        ],
    }

    report_on = await run_longmemeval_bench(
        retrieval="hybrid",
        granularity="session",
        recency="on",
        embed_model="bge-small",
        questions=[question],
    )
    report_off = await run_longmemeval_bench(
        retrieval="hybrid",
        granularity="session",
        recency="off",
        embed_model="bge-small",
        questions=[question],
    )

    on_order = report_on.per_question[0].retrieved_session_ids
    off_order = report_off.per_question[0].retrieved_session_ids

    assert on_order, "Recency=on produced no retrieved ids"
    assert off_order, "Recency=off produced no retrieved ids"

    # With ``recency=on`` and identical relevance, the recent session
    # must beat the 3-year-old one.  This is the proof that the
    # recency multiplier propagates from the runner's
    # ``recency_min_weight`` choice into the actual ranking.
    assert on_order[0] == "recent_session", (
        f"recency=on should rank the recent session first when relevance is tied; got {on_order}"
    )
    # And ``recency=off`` must yield a *different* top-1, *or* a
    # different overall ordering — otherwise the toggle was a no-op.
    assert off_order != on_order or off_order[0] == "old_session", (
        f"Recency toggle had no effect: on={on_order} off={off_order}. "
        f"Either the multiplier is not propagating or the test data "
        f"isn't date-sensitive enough."
    )


async def test_sha_panel_populated_in_every_record(tmp_path: Path) -> None:
    """Every JSONL record carries the seven discipline-rule-5 ``_meta`` keys.

    Required keys:

    * ``git_sha``
    * ``dataset_revision_sha``
    * ``dataset_file_sha256``
    * ``embed_model_sha``
    * ``python_version``
    * ``seed``
    * ``timestamp_utc``

    Without these, the receipts can't be audited and discipline rule 5
    is violated — "no SHAs ⇒ no claim".
    """
    questions = _load_fixture()

    report = await run_longmemeval_bench(
        retrieval="hybrid",
        granularity="session",
        recency="on",
        embed_model="bge-small",
        questions=questions,
        output_dir=tmp_path,
    )

    required = {
        "git_sha",
        "dataset_revision_sha",
        "dataset_file_sha256",
        "embed_model_sha",
        "python_version",
        "seed",
        "timestamp_utc",
    }

    # In-process records first.
    for record in report.per_question:
        missing = required - set(record.meta.keys())
        assert not missing, f"Record {record.question_id} missing meta keys: {missing}"

    # Now re-parse the JSONL so we also pin the on-disk shape.
    assert report.jsonl_path is not None
    lines = report.jsonl_path.read_text().splitlines()
    assert lines, "JSONL file is empty"
    for line in lines:
        payload = json.loads(line)
        meta = payload.get("_meta") or {}
        missing = required - set(meta.keys())
        assert not missing, f"On-disk record missing meta keys {missing}: {payload}"


async def test_raw_retrieval_records_effective_recency_off() -> None:
    """``retrieval=raw`` forces ``effective_recency=off`` in the meta panel.

    The vector-only fallback path in :class:`DuckDBStore` does not apply
    recency at all — see the runner's module docstring.  The runner
    must record this honestly so a reader of the JSONL can never
    mistakenly believe a raw-retrieval cell respects the requested
    recency setting.
    """
    questions = _load_fixture()

    report = await run_longmemeval_bench(
        retrieval="raw",
        granularity="session",
        recency="on",  # requested but bypassed
        embed_model="bge-small",
        questions=questions[:1],
    )

    record = report.per_question[0]
    assert record.meta["recency_requested"] == "on"
    assert record.meta["effective_recency"] == "off", (
        "raw retrieval must record effective_recency=off because the "
        "vector-only path bypasses the recency multiplier"
    )


def test_filename_schema_includes_every_axis(tmp_path: Path) -> None:
    """Output filenames must include every axis to prevent cross-axis confusion.

    Discipline rule: cross-granularity (and cross-anything) comparison
    should be a deliberate filesystem-level act, not an accident of two
    runs sharing a filename.  Pure naming check — no async needed.
    """
    from distillery.eval.longmemeval import _write_outputs

    record = QuestionRecord(
        question_id="x",
        question_type="t",
        expected_session_ids=[],
        retrieved_session_ids=[],
        rankings=[],
        recall_at_5=0.0,
        recall_all_at_5=0.0,
        ndcg_at_5=0.0,
        recall_at_10=0.0,
        recall_all_at_10=0.0,
        ndcg_at_10=0.0,
        latency_ms=1.0,
        n_corpus_entries=0,
        meta={},
    )
    jsonl, summary = _write_outputs(
        [record],
        {"n_questions": 1, "overall": {}, "per_question_type": {}},
        tmp_path,
        retrieval="hybrid",
        granularity="turn",
        recency="off",
        embed_model="bge-base",
        stamp="20260502T010203Z",
    )
    # Every axis appears in the filename so two distinct configurations
    # never collide on disk.
    for axis in ("hybrid", "turn", "off", "bge-base", "20260502T010203Z"):
        assert axis in jsonl.name, f"jsonl name missing axis {axis!r}: {jsonl.name}"
        assert axis in summary.name, f"summary name missing axis {axis!r}: {summary.name}"
