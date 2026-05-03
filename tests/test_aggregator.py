"""Tests for ``scripts/bench/aggregate_results.py``.

These tests use hand-crafted ``summary_longmemeval_*.json`` files that
mimic the schema emitted by :mod:`distillery.eval.longmemeval` (see the
``_aggregate`` helper there for the canonical shape). The point is to
pin the contract:

* The headline cell is picked correctly when several cells coexist.
* Badge JSON conforms to the Shields.io endpoint schema.
* SUMMARY.md is generated and contains the headline row.
* The "unknown" fallback fires when no headline run is present —
  the non-negotiable honesty constraint from the plan.
* Non-headline cells appear in the matrix table but do not become the
  headline by accident.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

# The aggregator lives under scripts/bench/ which isn't on the default
# import path; insert the repo root so the module resolves cleanly under
# pytest without requiring an install step.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.bench.aggregate_results import (  # noqa: E402  — sys.path mutated above
    DEFAULT_HEADLINE_CONFIG,
    aggregate,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _summary_payload(
    *,
    retrieval: str,
    granularity: str,
    recency: str,
    embed_model: str,
    r5: float,
    r10: float,
    ndcg10: float,
    git_sha: str = "abc1234deadbeef",
    dataset_revision_sha: str = "feedface00112233",
) -> dict[str, Any]:
    """Return a summary.json-shaped dict matching the runner's schema."""
    return {
        "n_questions": 10,
        "overall": {
            "recall_at_5": r5,
            "recall_at_10": r10,
            "ndcg_at_10": ndcg10,
        },
        "per_question_type": {
            "single-session-user": {
                "n": 5,
                "recall_at_5": r5,
                "recall_at_10": r10,
                "ndcg_at_10": ndcg10,
            },
            "multi-session": {
                "n": 5,
                "recall_at_5": max(0.0, r5 - 0.1),
                "recall_at_10": max(0.0, r10 - 0.05),
                "ndcg_at_10": max(0.0, ndcg10 - 0.05),
            },
        },
        "axes": {
            "retrieval": retrieval,
            "granularity": granularity,
            "recency": recency,
            "embed_model": embed_model,
            "seeds": 1,
            "limit": None,
        },
        "dataset": {
            "revision_sha": dataset_revision_sha,
            "file_sha256": "deadbeef" * 8,
        },
        "git_sha": git_sha,
        "timestamp_utc": "2026-04-30T05:00:00+00:00",
    }


def _write_summary(
    results_dir: Path,
    *,
    retrieval: str,
    granularity: str,
    recency: str,
    embed_model: str,
    stamp: str,
    payload: dict[str, Any] | None = None,
) -> Path:
    """Write a summary.json with the runner's filename convention."""
    results_dir.mkdir(parents=True, exist_ok=True)
    name = f"summary_longmemeval_{retrieval}_{granularity}_{recency}_{embed_model}_{stamp}.json"
    path = results_dir / name
    if payload is None:
        payload = _summary_payload(
            retrieval=retrieval,
            granularity=granularity,
            recency=recency,
            embed_model=embed_model,
            r5=0.85,
            r10=0.92,
            ndcg10=0.88,
        )
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHeadlineSelection:
    """The headline must be picked unambiguously — and never substituted."""

    def test_headline_picked_when_present(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "out"

        # Headline cell — newer of two timestamps.
        _write_summary(
            results_dir,
            retrieval="hybrid",
            granularity="session",
            recency="on",
            embed_model="bge-small",
            stamp="20260430T050000Z",
        )
        # Headline cell, earlier — should be ignored.
        _write_summary(
            results_dir,
            retrieval="hybrid",
            granularity="session",
            recency="on",
            embed_model="bge-small",
            stamp="20260429T050000Z",
            payload=_summary_payload(
                retrieval="hybrid",
                granularity="session",
                recency="on",
                embed_model="bge-small",
                r5=0.50,
                r10=0.55,
                ndcg10=0.52,
            ),
        )
        # Non-headline cell.
        _write_summary(
            results_dir,
            retrieval="raw",
            granularity="session",
            recency="off",
            embed_model="bge-small",
            stamp="20260430T060000Z",
        )

        report = aggregate(results_dir, output_dir=output_dir)

        assert report.headline is not None
        # Picked the most recent headline cell, not the most recent run.
        assert report.headline.timestamp == datetime(2026, 4, 30, 5, 0, 0, tzinfo=UTC)
        assert report.headline.axes["retrieval"] == "hybrid"
        assert report.headline.axes["embed_model"] == "bge-small"

    def test_unknown_fallback_when_headline_missing(self, tmp_path: Path) -> None:
        """Honesty constraint: never substitute a non-headline cell."""
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "out"

        # Only a non-headline cell present.
        _write_summary(
            results_dir,
            retrieval="raw",
            granularity="session",
            recency="off",
            embed_model="bge-small",
            stamp="20260430T050000Z",
        )

        report = aggregate(results_dir, output_dir=output_dir)
        assert report.headline is None

        # Each badge must be the lightgrey "unknown" payload.
        for filename in ("badge_r5.json", "badge_r10.json", "badge_ndcg10.json"):
            badge_path = output_dir / filename
            assert badge_path.exists()
            payload = json.loads(badge_path.read_text())
            assert payload["schemaVersion"] == 1
            assert payload["message"] == "unknown"
            assert payload["color"] == "lightgrey"


@pytest.mark.unit
class TestBadgeSchema:
    """Badge files must match the Shields.io endpoint contract exactly."""

    def test_badge_files_have_endpoint_schema(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "out"
        _write_summary(
            results_dir,
            retrieval="hybrid",
            granularity="session",
            recency="on",
            embed_model="bge-small",
            stamp="20260430T050000Z",
            payload=_summary_payload(
                retrieval="hybrid",
                granularity="session",
                recency="on",
                embed_model="bge-small",
                r5=0.911,
                r10=0.951,
                ndcg10=0.842,
            ),
        )

        report = aggregate(results_dir, output_dir=output_dir)
        assert report.headline is not None

        r5_payload = json.loads((output_dir / "badge_r5.json").read_text())
        r10_payload = json.loads((output_dir / "badge_r10.json").read_text())
        ndcg_payload = json.loads((output_dir / "badge_ndcg10.json").read_text())

        for payload in (r5_payload, r10_payload, ndcg_payload):
            assert set(payload.keys()) == {"schemaVersion", "label", "message", "color"}
            assert payload["schemaVersion"] == 1
            # Three-decimal rendering.
            assert payload["message"].count(".") == 1

        # Colour bands: 0.911 → brightgreen, 0.842 → yellowgreen.
        assert r5_payload["color"] == "brightgreen"
        assert r10_payload["color"] == "brightgreen"
        assert ndcg_payload["color"] == "yellowgreen"

        # Labels include the metric so a reader can tell badges apart.
        assert "R@5" in r5_payload["label"]
        assert "R@10" in r10_payload["label"]
        assert "NDCG@10" in ndcg_payload["label"]


@pytest.mark.unit
class TestSummaryMarkdown:
    """SUMMARY.md must contain the headline, the matrix, and the footer."""

    def test_summary_contains_headline_row(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "out"
        _write_summary(
            results_dir,
            retrieval="hybrid",
            granularity="session",
            recency="on",
            embed_model="bge-small",
            stamp="20260430T050000Z",
            payload=_summary_payload(
                retrieval="hybrid",
                granularity="session",
                recency="on",
                embed_model="bge-small",
                r5=0.873,
                r10=0.921,
                ndcg10=0.892,
            ),
        )

        report = aggregate(results_dir, output_dir=output_dir)
        assert report.summary_path is not None
        body = report.summary_path.read_text()

        assert "# LongMemEval bench results" in body
        assert "## Latest headline run" in body
        # Headline triplet rendered.
        assert "0.873" in body
        assert "0.921" in body
        assert "0.892" in body
        # Matrix and per-type sections.
        assert "## Latest matrix" in body
        assert "## Per-question-type breakdown" in body
        assert "single-session-user" in body
        # Footer pointers.
        assert "bench/HEADLINE.md" in body
        assert "bench/LIMITATIONS.md" in body
        # Distillery-only discipline rule restated near the matrix.
        assert "Distillery configurations only" in body

    def test_non_headline_cells_in_matrix_not_in_headline(self, tmp_path: Path) -> None:
        """Non-headline cells must show up in the matrix but NOT as the headline."""
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "out"

        _write_summary(
            results_dir,
            retrieval="hybrid",
            granularity="session",
            recency="on",
            embed_model="bge-small",
            stamp="20260430T050000Z",
            payload=_summary_payload(
                retrieval="hybrid",
                granularity="session",
                recency="on",
                embed_model="bge-small",
                r5=0.871,
                r10=0.921,
                ndcg10=0.890,
            ),
        )
        _write_summary(
            results_dir,
            retrieval="raw",
            granularity="session",
            recency="off",
            embed_model="bge-small",
            stamp="20260430T060000Z",
            payload=_summary_payload(
                retrieval="raw",
                granularity="session",
                recency="off",
                embed_model="bge-small",
                r5=0.611,
                r10=0.711,
                ndcg10=0.654,
            ),
        )
        _write_summary(
            results_dir,
            retrieval="hybrid",
            granularity="turn",
            recency="on",
            embed_model="bge-small",
            stamp="20260430T070000Z",
            payload=_summary_payload(
                retrieval="hybrid",
                granularity="turn",
                recency="on",
                embed_model="bge-small",
                r5=0.512,
                r10=0.612,
                ndcg10=0.555,
            ),
        )

        report = aggregate(results_dir, output_dir=output_dir)
        assert report.headline is not None
        # Headline must be the hybrid/session/on/bge-small cell — not the raw or turn cells.
        assert report.headline.axes["retrieval"] == "hybrid"
        assert report.headline.axes["granularity"] == "session"
        assert report.headline.axes["recency"] == "on"

        # Matrix should contain all three cells.
        cell_keys = [
            (r.axes["retrieval"], r.axes["granularity"], r.axes["recency"], r.axes["embed_model"])
            for r in report.matrix
        ]
        assert ("hybrid", "session", "on", "bge-small") in cell_keys
        assert ("raw", "session", "off", "bge-small") in cell_keys
        assert ("hybrid", "turn", "on", "bge-small") in cell_keys

        body = report.summary_path.read_text() if report.summary_path else ""
        # All three cell signatures should appear in the matrix table.
        assert "hybrid/session/on/bge-small" in body
        assert "raw/session/off/bge-small" in body
        assert "hybrid/turn/on/bge-small" in body

        # The headline triplet should match the hybrid/session cell, not raw or turn.
        # Raw cell's R@5 is 0.611 — must not appear in the headline row.
        # Find the headline section text and check it references 0.871 not 0.611/0.512.
        latest_section = body.split("## Latest matrix")[0]
        assert "0.871" in latest_section
        assert "0.611" not in latest_section
        assert "0.512" not in latest_section


@pytest.mark.unit
class TestHistory:
    """The 7-day headline history table must respect the time window."""

    def test_history_window_excludes_old_runs(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "out"

        # In window — 2026-04-30.
        _write_summary(
            results_dir,
            retrieval="hybrid",
            granularity="session",
            recency="on",
            embed_model="bge-small",
            stamp="20260430T050000Z",
        )
        # Out of window — 2026-04-15 (15 days before "now"=2026-05-02).
        _write_summary(
            results_dir,
            retrieval="hybrid",
            granularity="session",
            recency="on",
            embed_model="bge-small",
            stamp="20260415T050000Z",
        )

        now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=UTC)
        report = aggregate(results_dir, output_dir=output_dir, now=now)

        assert len(report.history) == 1
        assert report.history[0].timestamp == datetime(2026, 4, 30, 5, 0, 0, tzinfo=UTC)


@pytest.mark.unit
class TestDefaultHeadlineConfig:
    """The plan pre-registers the headline; the default must match it."""

    def test_default_headline_config_matches_plan(self) -> None:
        assert DEFAULT_HEADLINE_CONFIG == {
            "retrieval": "hybrid",
            "granularity": "session",
            "recency": "on",
            "embed_model": "bge-small",
        }
