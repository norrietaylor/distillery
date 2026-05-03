"""Aggregate LongMemEval bench results into badge JSON + SUMMARY.md.

This script is the publication step in the bench pipeline. It scans
``bench/results/`` for ``summary_longmemeval_<retrieval>_<granularity>_<recency>_<embed>_<UTC>.json``
files emitted by :mod:`distillery.eval.longmemeval`, identifies the
*headline* cell (pre-registered in ``bench/HEADLINE.md`` —
``retrieval=hybrid, granularity=session, recency=on, embed=bge-small``),
and writes:

* ``bench/badge_r5.json``, ``bench/badge_r10.json``,
  ``bench/badge_ndcg10.json`` — Shields.io endpoint-format files. The
  README points each badge URL at one of these files. Three files (not
  one composite) keeps the URL parametrisation simple.

* ``bench/results/SUMMARY.md`` — auto-updated table with the headline
  triplet, a Distillery-only matrix of recent runs, the per-question-type
  breakdown for the headline cell, and a 7-day history of headline R@5.

Honesty constraint
------------------

If no headline run is present in ``results_dir``, the badges are written
with ``message="unknown"`` and ``color="lightgrey"`` rather than falling
back to a non-headline cell. Surfacing that the headline didn't run is
strictly better than silently substituting a different configuration —
the latter is the publication failure mode mempalace's #875 was about.

CLI
---

    python scripts/bench/aggregate_results.py \\
        --results-dir bench/results/ \\
        --output-dir bench/

The ``--output-dir`` controls where the three badge files land.
``SUMMARY.md`` is always written into ``<results_dir>/SUMMARY.md``
because it documents the runs in that directory.

See the plan in ``/Users/norrie/.claude/plans/look-at-mempalace-hook-dynamic-mccarthy.md``
(Wave 2, deliverable 3 — "Nightly automation" — and deliverable 4 —
"Publication") for the broader publication discipline this script
enforces.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Headline configuration — pinned to bench/HEADLINE.md
# ---------------------------------------------------------------------------

# These four axis values define "the" headline cell. Anything else is an
# auxiliary matrix cell. The runner (`src/distillery/eval/longmemeval.py`)
# emits these same axis values into ``summary["axes"]``, so equality
# matching is exact.
DEFAULT_HEADLINE_CONFIG: dict[str, str] = {
    "retrieval": "hybrid",
    "granularity": "session",
    "recency": "on",
    "embed_model": "bge-small",
}

# The summary.json filename convention from longmemeval.py is:
#   summary_longmemeval_<retrieval>_<granularity>_<recency>_<embed>_<UTC>.json
_SUMMARY_FILENAME_RE = re.compile(
    r"^summary_longmemeval_"
    r"(?P<retrieval>[^_]+)_"
    r"(?P<granularity>[^_]+)_"
    r"(?P<recency>[^_]+)_"
    r"(?P<embed>[^_]+(?:-[^_]+)*)_"  # embed names contain hyphens (bge-small etc.)
    r"(?P<stamp>\d{8}T\d{6}Z)\.json$"
)


# ---------------------------------------------------------------------------
# Badge colour bands (subjective; documented inline)
# ---------------------------------------------------------------------------
#
# These thresholds are *not* claims about "good" or "bad" retrieval — they
# are a colour-coding choice for the badge so a reader can spot regressions
# at a glance. They sit within the sensible Shields.io palette and do not
# imply leaderboard ordering. Update only with an ADR.
_COLOUR_BANDS: tuple[tuple[float, str], ...] = (
    (0.90, "brightgreen"),
    (0.80, "yellowgreen"),
    (0.70, "yellow"),
    (0.0, "orange"),
)


def _colour_for(score: float) -> str:
    """Pick a Shields.io colour name for ``score`` in ``[0, 1]``.

    Scores above 0.90 → ``brightgreen``; 0.80–0.90 → ``yellowgreen``;
    0.70–0.80 → ``yellow``; below 0.70 → ``orange``. The bands are
    intentionally coarse — fine-grained colour shifts would imply more
    precision than the underlying noise band warrants (see W3 variance
    characterisation).
    """
    for threshold, colour in _COLOUR_BANDS:
        if score >= threshold:
            return colour
    return "orange"


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


@dataclass
class SummaryRecord:
    """One parsed ``summary_*.json`` file plus its filesystem provenance.

    ``axes`` is the four-key dict that identifies the cell. ``data`` is
    the full parsed JSON (so callers can read overall metrics, per-type
    breakdowns, and the SHA panel without re-reading the file).
    ``timestamp`` is the parsed UTC timestamp from the filename
    (preferred over the in-file ``timestamp_utc`` because filename order
    is what the writer guarantees uniqueness on).
    """

    path: Path
    axes: dict[str, str]
    data: dict[str, Any]
    timestamp: datetime


def _parse_filename_timestamp(stamp: str) -> datetime:
    """Parse the ``YYYYMMDDTHHMMSSZ`` filename stamp to a UTC datetime."""
    return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def _load_summaries(results_dir: Path) -> list[SummaryRecord]:
    """Load every ``summary_longmemeval_*.json`` in ``results_dir``.

    Files that fail to parse (corrupt JSON, unreadable, filename pattern
    mismatch) are skipped with a warning rather than aborting the whole
    aggregation. The discipline rule is "no headline ⇒ unknown badges",
    which only triggers if *zero* matching headline summaries are
    findable; one corrupt file shouldn't kill the run.
    """
    if not results_dir.exists():
        return []

    records: list[SummaryRecord] = []
    for path in sorted(results_dir.glob("summary_longmemeval_*.json")):
        match = _SUMMARY_FILENAME_RE.match(path.name)
        if match is None:
            logger.warning("Skipping summary with non-matching filename: %s", path.name)
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read %s: %s", path.name, exc)
            continue

        # Prefer the in-file ``axes`` dict (it's authoritative — the
        # filename was derived from it) but fall back to filename parsing
        # if the file lacks the axes block.
        axes_payload = data.get("axes") if isinstance(data, dict) else None
        if isinstance(axes_payload, dict):
            axes = {
                "retrieval": str(axes_payload.get("retrieval", match["retrieval"])),
                "granularity": str(axes_payload.get("granularity", match["granularity"])),
                "recency": str(axes_payload.get("recency", match["recency"])),
                "embed_model": str(axes_payload.get("embed_model", match["embed"])),
            }
        else:
            axes = {
                "retrieval": match["retrieval"],
                "granularity": match["granularity"],
                "recency": match["recency"],
                "embed_model": match["embed"],
            }

        records.append(
            SummaryRecord(
                path=path,
                axes=axes,
                data=data if isinstance(data, dict) else {},
                timestamp=_parse_filename_timestamp(match["stamp"]),
            )
        )
    return records


def _matches_headline(axes: dict[str, str], headline: dict[str, str]) -> bool:
    """Return True iff every axis in ``headline`` matches ``axes``."""
    return all(axes.get(key) == value for key, value in headline.items())


# ---------------------------------------------------------------------------
# Badge emission (Shields.io endpoint format)
# ---------------------------------------------------------------------------


def _badge_payload(label: str, score: float | None) -> dict[str, Any]:
    """Return a Shields.io endpoint-schema dict for one metric.

    ``score=None`` → ``message="unknown"``, ``color="lightgrey"`` (the
    honesty fallback). Otherwise the score is rendered to three decimal
    places — matches the precision the runner reports without implying
    bench precision beyond the noise band.
    """
    if score is None:
        return {
            "schemaVersion": 1,
            "label": label,
            "message": "unknown",
            "color": "lightgrey",
        }
    return {
        "schemaVersion": 1,
        "label": label,
        "message": f"{score:.3f}",
        "color": _colour_for(score),
    }


def _write_badges(
    output_dir: Path,
    *,
    r5: float | None,
    r10: float | None,
    ndcg10: float | None,
) -> dict[str, Path]:
    """Write the three Shields.io badge JSON files. Returns the paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    badges: dict[str, tuple[str, float | None]] = {
        "badge_r5.json": ("LongMemEval R@5", r5),
        "badge_r10.json": ("LongMemEval R@10", r10),
        "badge_ndcg10.json": ("LongMemEval NDCG@10", ndcg10),
    }
    written: dict[str, Path] = {}
    for filename, (label, score) in badges.items():
        path = output_dir / filename
        with path.open("w", encoding="utf-8") as f:
            json.dump(_badge_payload(label, score), f, indent=2)
            f.write("\n")
        written[filename] = path
    return written


# ---------------------------------------------------------------------------
# SUMMARY.md generation
# ---------------------------------------------------------------------------


def _format_score(value: Any) -> str:
    """Render a metric value to three decimals; ``"—"`` if missing."""
    if not isinstance(value, int | float):
        return "—"
    return f"{float(value):.3f}"


def _format_stamp(ts: datetime) -> str:
    """Render a UTC timestamp as ``YYYY-MM-DDTHH:MM:SSZ`` for tables."""
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_axes(axes: dict[str, str]) -> str:
    """Render an axes dict as ``retrieval/granularity/recency/embed``."""
    return "/".join(
        [
            axes.get("retrieval", "?"),
            axes.get("granularity", "?"),
            axes.get("recency", "?"),
            axes.get("embed_model", "?"),
        ]
    )


def _latest_per_cell(records: list[SummaryRecord]) -> list[SummaryRecord]:
    """Reduce ``records`` to one entry per ``(axes...)`` tuple — the latest.

    Sorted ascending by axes string then by timestamp descending so the
    output table reads stably across runs.
    """
    by_cell: dict[tuple[str, str, str, str], SummaryRecord] = {}
    for rec in records:
        key = (
            rec.axes["retrieval"],
            rec.axes["granularity"],
            rec.axes["recency"],
            rec.axes["embed_model"],
        )
        existing = by_cell.get(key)
        if existing is None or rec.timestamp > existing.timestamp:
            by_cell[key] = rec
    return sorted(by_cell.values(), key=lambda r: (_format_axes(r.axes), -r.timestamp.timestamp()))


def _headline_history(
    records: list[SummaryRecord],
    headline: dict[str, str],
    *,
    days: int = 7,
    now: datetime | None = None,
) -> list[SummaryRecord]:
    """Return headline runs in the last ``days`` days, newest first."""
    reference = now if now is not None else datetime.now(tz=UTC)
    cutoff = reference - timedelta(days=days)
    matched = [
        rec for rec in records if _matches_headline(rec.axes, headline) and rec.timestamp >= cutoff
    ]
    return sorted(matched, key=lambda r: r.timestamp, reverse=True)


def _render_summary_md(
    *,
    headline: SummaryRecord | None,
    headline_config: dict[str, str],
    matrix: list[SummaryRecord],
    history: list[SummaryRecord],
) -> str:
    """Render the full SUMMARY.md body as a string.

    Section order matches the plan:
      1. Latest headline run
      2. Latest matrix (Distillery configurations only)
      3. Per-question-type breakdown for the headline cell only
      4. History (last 7 days)
      5. Footer with pointers to bench/HEADLINE.md and bench/LIMITATIONS.md
    """
    lines: list[str] = []
    lines.append("# LongMemEval bench results")
    lines.append("")
    lines.append("_This file is auto-generated by `scripts/bench/aggregate_results.py`._")
    lines.append("_Do not edit by hand — your changes will be overwritten._")
    lines.append("")

    # ------------------------------------------------------------------
    # Section 1 — Latest headline run
    # ------------------------------------------------------------------
    lines.append("## Latest headline run")
    lines.append("")
    headline_axes_str = _format_axes(_normalise_headline_keys(headline_config))
    lines.append(f"Headline cell: `{headline_axes_str}` (pre-registered in `bench/HEADLINE.md`).")
    lines.append("")
    if headline is None:
        lines.append(
            "**No headline run found in this results directory.** Badges are reporting "
            "`unknown` until the next nightly produces a headline cell."
        )
        lines.append("")
    else:
        overall = headline.data.get("overall", {}) if isinstance(headline.data, dict) else {}
        lines.append("| Date (UTC) | git_sha | dataset_revision_sha | R@5 | R@10 | NDCG@10 |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: |")
        dataset_sha = (
            headline.data.get("dataset", {}).get("revision_sha", "—")
            if isinstance(headline.data, dict)
            else "—"
        )
        git_sha_value = (
            headline.data.get("git_sha", "—") if isinstance(headline.data, dict) else "—"
        )
        lines.append(
            "| {date} | `{git}` | `{ds}` | {r5} | {r10} | {nd} |".format(
                date=_format_stamp(headline.timestamp),
                git=str(git_sha_value)[:12],
                ds=str(dataset_sha)[:12],
                r5=_format_score(overall.get("recall_at_5")),
                r10=_format_score(overall.get("recall_at_10")),
                nd=_format_score(overall.get("ndcg_at_10")),
            )
        )
        lines.append("")

    # ------------------------------------------------------------------
    # Section 2 — Latest matrix (Distillery configurations only)
    # ------------------------------------------------------------------
    lines.append("## Latest matrix")
    lines.append("")
    lines.append(
        "Distillery configurations only. Cross-system comparisons are forbidden by "
        "discipline rule (3) — see `bench/LIMITATIONS.md`."
    )
    lines.append("")
    if not matrix:
        lines.append("_No bench runs found._")
        lines.append("")
    else:
        lines.append("| Cell | R@5 | R@10 | NDCG@10 | UTC |")
        lines.append("| --- | ---: | ---: | ---: | --- |")
        for rec in matrix:
            overall = rec.data.get("overall", {}) if isinstance(rec.data, dict) else {}
            lines.append(
                "| `{cell}` | {r5} | {r10} | {nd} | {ts} |".format(
                    cell=_format_axes(rec.axes),
                    r5=_format_score(overall.get("recall_at_5")),
                    r10=_format_score(overall.get("recall_at_10")),
                    nd=_format_score(overall.get("ndcg_at_10")),
                    ts=_format_stamp(rec.timestamp),
                )
            )
        lines.append("")

    # ------------------------------------------------------------------
    # Section 3 — Per-question-type breakdown (headline cell only)
    # ------------------------------------------------------------------
    lines.append("## Per-question-type breakdown (headline cell)")
    lines.append("")
    if headline is None:
        lines.append("_No headline run available._")
        lines.append("")
    else:
        per_type = (
            headline.data.get("per_question_type", {}) if isinstance(headline.data, dict) else {}
        )
        if not per_type:
            lines.append("_No per-question-type data in headline summary._")
            lines.append("")
        else:
            lines.append("| Question type | n | R@5 | R@10 | NDCG@10 |")
            lines.append("| --- | ---: | ---: | ---: | ---: |")
            for qtype in sorted(per_type.keys()):
                bucket = per_type[qtype] if isinstance(per_type[qtype], dict) else {}
                lines.append(
                    "| `{q}` | {n} | {r5} | {r10} | {nd} |".format(
                        q=qtype,
                        n=bucket.get("n", "—"),
                        r5=_format_score(bucket.get("recall_at_5")),
                        r10=_format_score(bucket.get("recall_at_10")),
                        nd=_format_score(bucket.get("ndcg_at_10")),
                    )
                )
            lines.append("")

    # ------------------------------------------------------------------
    # Section 4 — History (last 7 days)
    # ------------------------------------------------------------------
    lines.append("## History (last 7 days, headline cell)")
    lines.append("")
    if not history:
        lines.append("_No headline runs in the last 7 days._")
        lines.append("")
    else:
        lines.append("| UTC | R@5 |")
        lines.append("| --- | ---: |")
        for rec in history:
            overall = rec.data.get("overall", {}) if isinstance(rec.data, dict) else {}
            lines.append(
                "| {ts} | {r5} |".format(
                    ts=_format_stamp(rec.timestamp),
                    r5=_format_score(overall.get("recall_at_5")),
                )
            )
        lines.append("")

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------
    lines.append("---")
    lines.append("")
    lines.append(
        "See `bench/HEADLINE.md` for the pre-registered headline configuration and "
        "`bench/LIMITATIONS.md` for what these numbers do and do not claim."
    )
    lines.append("")
    return "\n".join(lines)


def _normalise_headline_keys(config: dict[str, str]) -> dict[str, str]:
    """Map a user-supplied headline config to the canonical axes dict.

    The plan describes the headline keys as
    ``{"retrieval", "granularity", "recency", "embed"}`` whereas the
    runner emits ``embed_model``. We accept either spelling on input
    and normalise to ``embed_model`` so axis comparison is consistent.
    """
    normalised = {
        "retrieval": config.get("retrieval", "?"),
        "granularity": config.get("granularity", "?"),
        "recency": config.get("recency", "?"),
    }
    embed = config.get("embed_model", config.get("embed", "?"))
    normalised["embed_model"] = embed
    return normalised


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class AggregateReport:
    """Returned by :func:`aggregate` for in-process callers / tests.

    ``headline`` is ``None`` when no run matches the headline config —
    this is the trigger for the "unknown" badge fallback.
    """

    headline: SummaryRecord | None
    matrix: list[SummaryRecord]
    history: list[SummaryRecord] = field(default_factory=list)
    badge_paths: dict[str, Path] = field(default_factory=dict)
    summary_path: Path | None = None


def aggregate(
    results_dir: Path,
    *,
    headline_config: dict[str, str] | None = None,
    output_dir: Path,
    now: datetime | None = None,
) -> AggregateReport:
    """Aggregate bench results, write badges and SUMMARY.md.

    Parameters
    ----------
    results_dir:
        Directory containing ``summary_longmemeval_*.json`` files.
    headline_config:
        Override for the pre-registered headline cell. ``None`` →
        :data:`DEFAULT_HEADLINE_CONFIG`. Keys may be ``embed`` or
        ``embed_model`` — both are normalised internally.
    output_dir:
        Where the three ``badge_*.json`` files are written. The
        ``SUMMARY.md`` always lands in ``results_dir`` because it
        documents the runs there.
    now:
        Optional override for "current time" — used by tests so the
        7-day history window is deterministic.

    Returns
    -------
    AggregateReport
        Structured handle for tests and callers; the same data is
        written to disk.
    """
    headline_axes = _normalise_headline_keys(headline_config or DEFAULT_HEADLINE_CONFIG)
    records = _load_summaries(results_dir)

    headline_runs = [r for r in records if _matches_headline(r.axes, headline_axes)]
    headline = max(headline_runs, key=lambda r: r.timestamp) if headline_runs else None

    matrix = _latest_per_cell(records)
    history = _headline_history(records, headline_axes, now=now)

    if headline is None:
        badge_paths = _write_badges(output_dir, r5=None, r10=None, ndcg10=None)
    else:
        overall = headline.data.get("overall", {}) if isinstance(headline.data, dict) else {}
        badge_paths = _write_badges(
            output_dir,
            r5=_safe_float(overall.get("recall_at_5")),
            r10=_safe_float(overall.get("recall_at_10")),
            ndcg10=_safe_float(overall.get("ndcg_at_10")),
        )

    summary_md = _render_summary_md(
        headline=headline,
        headline_config=headline_axes,
        matrix=matrix,
        history=history,
    )
    results_dir.mkdir(parents=True, exist_ok=True)
    summary_path = results_dir / "SUMMARY.md"
    with summary_path.open("w", encoding="utf-8") as f:
        f.write(summary_md)

    return AggregateReport(
        headline=headline,
        matrix=matrix,
        history=history,
        badge_paths=badge_paths,
        summary_path=summary_path,
    )


def _safe_float(value: Any) -> float | None:
    """Convert ``value`` to a float if numeric; ``None`` otherwise."""
    if isinstance(value, int | float):
        return float(value)
    return None


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="aggregate_results",
        description=(
            "Aggregate LongMemEval bench summaries into Shields.io badge JSON "
            "files and a SUMMARY.md table."
        ),
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("bench/results"),
        help="Directory containing summary_longmemeval_*.json files (default: bench/results).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("bench"),
        help="Directory to write badge_*.json into (default: bench).",
    )
    parser.add_argument(
        "--headline-retrieval",
        default=DEFAULT_HEADLINE_CONFIG["retrieval"],
        help="Override headline retrieval axis.",
    )
    parser.add_argument(
        "--headline-granularity",
        default=DEFAULT_HEADLINE_CONFIG["granularity"],
        help="Override headline granularity axis.",
    )
    parser.add_argument(
        "--headline-recency",
        default=DEFAULT_HEADLINE_CONFIG["recency"],
        help="Override headline recency axis.",
    )
    parser.add_argument(
        "--headline-embed",
        default=DEFAULT_HEADLINE_CONFIG["embed_model"],
        help="Override headline embed-model axis.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable INFO-level logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint. Returns a process exit code."""
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    headline_config = {
        "retrieval": args.headline_retrieval,
        "granularity": args.headline_granularity,
        "recency": args.headline_recency,
        "embed_model": args.headline_embed,
    }

    report = aggregate(
        args.results_dir,
        headline_config=headline_config,
        output_dir=args.output_dir,
    )

    if report.headline is None:
        logger.warning(
            "No headline run found in %s — badges set to 'unknown'.",
            args.results_dir,
        )
    else:
        overall = (
            report.headline.data.get("overall", {})
            if isinstance(report.headline.data, dict)
            else {}
        )
        logger.info(
            "Headline: R@5=%s R@10=%s NDCG@10=%s (from %s)",
            overall.get("recall_at_5"),
            overall.get("recall_at_10"),
            overall.get("ndcg_at_10"),
            report.headline.path.name,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "DEFAULT_HEADLINE_CONFIG",
    "AggregateReport",
    "SummaryRecord",
    "aggregate",
    "main",
]
