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


# ---------------------------------------------------------------------------
# Additional tests: helpers, edge cases, CLI
# ---------------------------------------------------------------------------

from scripts.bench.aggregate_results import (  # noqa: E402
    _colour_for,
    _format_score,
    _format_stamp,
    _format_axes,
    _load_summaries,
    _matches_headline,
    _normalise_headline_keys,
    _parse_filename_timestamp,
    _safe_float,
    main,
)


@pytest.mark.unit
class TestColourFor:
    """_colour_for selects the correct Shields.io colour name by score band."""

    def test_above_0_90_is_brightgreen(self) -> None:
        assert _colour_for(0.95) == "brightgreen"
        assert _colour_for(1.0) == "brightgreen"
        assert _colour_for(0.901) == "brightgreen"

    def test_exactly_0_90_is_brightgreen(self) -> None:
        # Threshold is >=0.90 → brightgreen.
        assert _colour_for(0.90) == "brightgreen"

    def test_just_below_0_90_is_yellowgreen(self) -> None:
        assert _colour_for(0.899) == "yellowgreen"
        assert _colour_for(0.85) == "yellowgreen"

    def test_exactly_0_80_is_yellowgreen(self) -> None:
        assert _colour_for(0.80) == "yellowgreen"

    def test_just_below_0_80_is_yellow(self) -> None:
        assert _colour_for(0.799) == "yellow"
        assert _colour_for(0.75) == "yellow"

    def test_exactly_0_70_is_yellow(self) -> None:
        assert _colour_for(0.70) == "yellow"

    def test_just_below_0_70_is_orange(self) -> None:
        assert _colour_for(0.699) == "orange"
        assert _colour_for(0.5) == "orange"

    def test_zero_is_orange(self) -> None:
        assert _colour_for(0.0) == "orange"

    def test_very_small_positive_is_orange(self) -> None:
        assert _colour_for(0.001) == "orange"


@pytest.mark.unit
class TestNormaliseHeadlineKeys:
    """_normalise_headline_keys handles both 'embed' and 'embed_model' spellings."""

    def test_embed_model_key_passes_through(self) -> None:
        config = {
            "retrieval": "hybrid",
            "granularity": "session",
            "recency": "on",
            "embed_model": "bge-small",
        }
        result = _normalise_headline_keys(config)
        assert result["embed_model"] == "bge-small"
        assert result["retrieval"] == "hybrid"
        assert result["granularity"] == "session"
        assert result["recency"] == "on"

    def test_embed_alias_key_normalised_to_embed_model(self) -> None:
        config = {
            "retrieval": "raw",
            "granularity": "turn",
            "recency": "off",
            "embed": "bge-base",
        }
        result = _normalise_headline_keys(config)
        assert result["embed_model"] == "bge-base"
        assert "embed" not in result

    def test_embed_model_wins_over_embed_when_both_present(self) -> None:
        config = {
            "retrieval": "hybrid",
            "granularity": "session",
            "recency": "on",
            "embed_model": "bge-large",
            "embed": "bge-small",  # should be ignored
        }
        result = _normalise_headline_keys(config)
        assert result["embed_model"] == "bge-large"

    def test_missing_all_embed_keys_uses_question_mark(self) -> None:
        config = {"retrieval": "hybrid"}
        result = _normalise_headline_keys(config)
        assert result["embed_model"] == "?"
        assert result["granularity"] == "?"
        assert result["recency"] == "?"


@pytest.mark.unit
class TestFormatScore:
    """_format_score renders numeric values to three decimals; '—' otherwise."""

    def test_float_renders_to_three_decimals(self) -> None:
        assert _format_score(0.873) == "0.873"
        assert _format_score(1.0) == "1.000"
        assert _format_score(0.0) == "0.000"

    def test_int_rendered_as_float(self) -> None:
        assert _format_score(1) == "1.000"
        assert _format_score(0) == "0.000"

    def test_none_returns_dash(self) -> None:
        assert _format_score(None) == "—"

    def test_string_returns_dash(self) -> None:
        assert _format_score("not-a-number") == "—"

    def test_list_returns_dash(self) -> None:
        assert _format_score([0.5]) == "—"

    def test_rounds_correctly(self) -> None:
        # 0.9999 → 1.000 (standard rounding)
        assert _format_score(0.9999) == "1.000"
        # 0.12345 → 0.123 (truncation at 3 decimals)
        assert _format_score(0.12345) == "0.123"


@pytest.mark.unit
class TestFormatStamp:
    """_format_stamp renders UTC datetimes in the SUMMARY.md table format."""

    def test_formats_to_iso_style(self) -> None:
        from datetime import UTC, datetime

        ts = datetime(2026, 4, 30, 5, 0, 0, tzinfo=UTC)
        assert _format_stamp(ts) == "2026-04-30T05:00:00Z"

    def test_pads_single_digit_months_and_days(self) -> None:
        from datetime import UTC, datetime

        ts = datetime(2026, 1, 3, 9, 7, 2, tzinfo=UTC)
        assert _format_stamp(ts) == "2026-01-03T09:07:02Z"


@pytest.mark.unit
class TestFormatAxes:
    """_format_axes produces a slash-separated cell string."""

    def test_four_axes_joined(self) -> None:
        axes = {"retrieval": "hybrid", "granularity": "session", "recency": "on", "embed_model": "bge-small"}
        assert _format_axes(axes) == "hybrid/session/on/bge-small"

    def test_missing_keys_become_question_marks(self) -> None:
        result = _format_axes({})
        assert result == "?/?/?/?"

    def test_partial_axes(self) -> None:
        axes = {"retrieval": "raw", "granularity": "turn"}
        result = _format_axes(axes)
        assert result.startswith("raw/turn")


@pytest.mark.unit
class TestParseFilenameTimestamp:
    """_parse_filename_timestamp parses the compact UTC stamp from filenames."""

    def test_parses_correctly(self) -> None:
        from datetime import UTC, datetime

        ts = _parse_filename_timestamp("20260430T050000Z")
        assert ts == datetime(2026, 4, 30, 5, 0, 0, tzinfo=UTC)

    def test_parsed_is_utc(self) -> None:
        from datetime import UTC

        ts = _parse_filename_timestamp("20260101T120000Z")
        assert ts.tzinfo is UTC or str(ts.tzinfo) == "UTC"


@pytest.mark.unit
class TestSafeFloat:
    """_safe_float converts numeric values; returns None for others."""

    def test_float_returns_float(self) -> None:
        result = _safe_float(0.85)
        assert result == 0.85
        assert isinstance(result, float)

    def test_int_returns_float(self) -> None:
        result = _safe_float(1)
        assert result == 1.0
        assert isinstance(result, float)

    def test_none_returns_none(self) -> None:
        assert _safe_float(None) is None

    def test_string_returns_none(self) -> None:
        assert _safe_float("0.85") is None

    def test_list_returns_none(self) -> None:
        assert _safe_float([0.85]) is None

    def test_zero_returns_float_zero(self) -> None:
        assert _safe_float(0) == 0.0
        assert _safe_float(0.0) == 0.0


@pytest.mark.unit
class TestMatchesHeadline:
    """_matches_headline compares axes dicts correctly."""

    def test_exact_match_returns_true(self) -> None:
        axes = {"retrieval": "hybrid", "granularity": "session", "recency": "on", "embed_model": "bge-small"}
        headline = {"retrieval": "hybrid", "granularity": "session", "recency": "on", "embed_model": "bge-small"}
        assert _matches_headline(axes, headline) is True

    def test_partial_headline_matches_superset_axes(self) -> None:
        axes = {"retrieval": "hybrid", "granularity": "session", "recency": "on", "embed_model": "bge-small"}
        headline = {"retrieval": "hybrid"}  # subset of axes
        assert _matches_headline(axes, headline) is True

    def test_mismatched_single_key_returns_false(self) -> None:
        axes = {"retrieval": "hybrid", "granularity": "session", "recency": "on", "embed_model": "bge-small"}
        headline = {"retrieval": "raw", "granularity": "session", "recency": "on", "embed_model": "bge-small"}
        assert _matches_headline(axes, headline) is False

    def test_empty_headline_matches_anything(self) -> None:
        axes = {"retrieval": "hybrid"}
        assert _matches_headline(axes, {}) is True


@pytest.mark.unit
class TestLoadSummaries:
    """_load_summaries gracefully handles various filesystem scenarios."""

    def test_nonexistent_dir_returns_empty_list(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist"
        result = _load_summaries(missing)
        assert result == []

    def test_empty_dir_returns_empty_list(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        result = _load_summaries(results_dir)
        assert result == []

    def test_corrupt_json_skipped(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        # Write a valid summary + a corrupt one.
        valid_path = results_dir / "summary_longmemeval_hybrid_session_on_bge-small_20260430T050000Z.json"
        valid_path.write_text('{"axes": {"retrieval": "hybrid", "granularity": "session", "recency": "on", "embed_model": "bge-small"}}')
        corrupt_path = results_dir / "summary_longmemeval_raw_session_off_bge-small_20260430T060000Z.json"
        corrupt_path.write_bytes(b"NOT_VALID_JSON{{{{")

        records = _load_summaries(results_dir)
        # Only the valid file should be loaded.
        assert len(records) == 1
        assert records[0].axes["retrieval"] == "hybrid"

    def test_filename_mismatch_skipped(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        # Write a file that doesn't match the naming pattern.
        bad_name = results_dir / "not_a_summary_file.json"
        bad_name.write_text('{"axes": {}}')
        # Valid file alongside it.
        good = results_dir / "summary_longmemeval_hybrid_session_on_bge-small_20260430T050000Z.json"
        good.write_text('{"axes": {"retrieval": "hybrid", "granularity": "session", "recency": "on", "embed_model": "bge-small"}}')

        records = _load_summaries(results_dir)
        assert len(records) == 1

    def test_missing_axes_block_falls_back_to_filename(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        # A valid file WITHOUT an axes block — should parse axes from filename.
        path = results_dir / "summary_longmemeval_raw_turn_off_bge-base_20260501T120000Z.json"
        path.write_text('{"overall": {"recall_at_5": 0.5}}')

        records = _load_summaries(results_dir)
        assert len(records) == 1
        rec = records[0]
        assert rec.axes["retrieval"] == "raw"
        assert rec.axes["granularity"] == "turn"
        assert rec.axes["recency"] == "off"
        assert rec.axes["embed_model"] == "bge-base"

    def test_in_file_axes_override_filename_axes(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        # File has axes block with different embed_model than filename.
        path = results_dir / "summary_longmemeval_hybrid_session_on_bge-small_20260430T050000Z.json"
        path.write_text(
            '{"axes": {"retrieval": "hybrid", "granularity": "session", "recency": "on", "embed_model": "bge-large"}}'
        )

        records = _load_summaries(results_dir)
        assert len(records) == 1
        # In-file embed_model wins over filename's bge-small.
        assert records[0].axes["embed_model"] == "bge-large"

    def test_timestamp_parsed_from_filename(self, tmp_path: Path) -> None:
        from datetime import UTC, datetime

        results_dir = tmp_path / "results"
        results_dir.mkdir()
        path = results_dir / "summary_longmemeval_hybrid_session_on_bge-small_20260502T153045Z.json"
        path.write_text('{}')

        records = _load_summaries(results_dir)
        assert len(records) == 1
        assert records[0].timestamp == datetime(2026, 5, 2, 15, 30, 45, tzinfo=UTC)


@pytest.mark.unit
class TestAggregateEdgeCases:
    """Edge cases for the high-level aggregate() function."""

    def test_aggregate_with_empty_results_dir(self, tmp_path: Path) -> None:
        """Empty results directory → no headline, unknown badges, empty matrix."""
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        output_dir = tmp_path / "out"

        report = aggregate(results_dir, output_dir=output_dir)

        assert report.headline is None
        assert report.matrix == []
        assert report.history == []

        # All three badge files must exist with "unknown" messages.
        for filename in ("badge_r5.json", "badge_r10.json", "badge_ndcg10.json"):
            badge_path = output_dir / filename
            assert badge_path.exists(), f"Badge {filename} not written"
            payload = json.loads(badge_path.read_text())
            assert payload["message"] == "unknown"
            assert payload["color"] == "lightgrey"

    def test_aggregate_with_embed_key_in_headline_config(self, tmp_path: Path) -> None:
        """headline_config with 'embed' key (not 'embed_model') is normalised correctly."""
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "out"

        _write_summary(
            results_dir,
            retrieval="hybrid",
            granularity="session",
            recency="on",
            embed_model="bge-small",
            stamp="20260430T050000Z",
        )

        # Pass headline config using the 'embed' key alias.
        report = aggregate(
            results_dir,
            headline_config={
                "retrieval": "hybrid",
                "granularity": "session",
                "recency": "on",
                "embed": "bge-small",  # 'embed' alias, not 'embed_model'
            },
            output_dir=output_dir,
        )

        assert report.headline is not None
        assert report.headline.axes["retrieval"] == "hybrid"

    def test_aggregate_nonexistent_results_dir_creates_output(self, tmp_path: Path) -> None:
        """Nonexistent results_dir → unknown badges, SUMMARY.md created."""
        results_dir = tmp_path / "nonexistent"
        output_dir = tmp_path / "out"

        report = aggregate(results_dir, output_dir=output_dir)

        assert report.headline is None
        assert report.summary_path is not None
        # SUMMARY.md gets written even when results_dir didn't exist.
        assert report.summary_path.exists()
        body = report.summary_path.read_text()
        assert "No headline run found" in body

    def test_summary_md_with_no_headline_mentions_unknown(self, tmp_path: Path) -> None:
        """SUMMARY.md must say 'unknown' when headline is absent."""
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "out"
        _write_summary(
            results_dir,
            retrieval="raw",
            granularity="turn",
            recency="off",
            embed_model="bge-base",
            stamp="20260430T050000Z",
        )

        report = aggregate(results_dir, output_dir=output_dir)
        body = report.summary_path.read_text()  # type: ignore[union-attr]
        assert "No headline run found" in body

    def test_summary_md_history_section_present(self, tmp_path: Path) -> None:
        """SUMMARY.md always contains the history section header."""
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "out"

        report = aggregate(results_dir, output_dir=output_dir)
        body = report.summary_path.read_text()  # type: ignore[union-attr]
        assert "## History (last 7 days" in body

    def test_summary_md_no_bench_runs_in_matrix(self, tmp_path: Path) -> None:
        """With no results, the matrix section says '_No bench runs found._'."""
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        output_dir = tmp_path / "out"

        report = aggregate(results_dir, output_dir=output_dir)
        body = report.summary_path.read_text()  # type: ignore[union-attr]
        assert "_No bench runs found._" in body


@pytest.mark.unit
class TestCliMain:
    """main() CLI entrypoint returns exit code 0 and handles args."""

    def test_main_returns_zero_with_empty_dir(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        exit_code = main([
            "--results-dir", str(results_dir),
            "--output-dir", str(output_dir),
        ])
        assert exit_code == 0

    def test_main_returns_zero_with_headline_present(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "out"
        _write_summary(
            results_dir,
            retrieval="hybrid",
            granularity="session",
            recency="on",
            embed_model="bge-small",
            stamp="20260430T050000Z",
        )

        exit_code = main([
            "--results-dir", str(results_dir),
            "--output-dir", str(output_dir),
        ])
        assert exit_code == 0
        # Badge files should exist.
        assert (output_dir / "badge_r5.json").exists()
        assert (output_dir / "badge_r10.json").exists()
        assert (output_dir / "badge_ndcg10.json").exists()

    def test_main_headline_override_args(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        output_dir = tmp_path / "out"
        # Write a non-default headline cell.
        _write_summary(
            results_dir,
            retrieval="raw",
            granularity="turn",
            recency="off",
            embed_model="bge-base",
            stamp="20260430T050000Z",
        )

        exit_code = main([
            "--results-dir", str(results_dir),
            "--output-dir", str(output_dir),
            "--headline-retrieval", "raw",
            "--headline-granularity", "turn",
            "--headline-recency", "off",
            "--headline-embed", "bge-base",
        ])
        assert exit_code == 0
        # The non-default headline should be found and the badge should not be 'unknown'.
        badge = json.loads((output_dir / "badge_r5.json").read_text())
        assert badge["message"] != "unknown"

    def test_main_verbose_flag_accepted(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        output_dir = tmp_path / "out"
        output_dir.mkdir()
        # --verbose should not cause an error.
        exit_code = main([
            "--results-dir", str(results_dir),
            "--output-dir", str(output_dir),
            "--verbose",
        ])
        assert exit_code == 0
