"""Tests for the ``distillery bench longmemeval`` CLI subcommand.

These tests cover the wiring layer only — argparse plumbing, output-dir
resolution, the headline summary line. The runner itself is exercised by
``tests/eval/test_longmemeval_runner.py``.

The integration smoke test loads the bundled mini fixture and patches the
runner's embedding-provider factory with a deterministic keyword stub so
no fastembed weights are downloaded during the test run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from distillery.cli import main

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "longmemeval_mini.json"


# ---------------------------------------------------------------------------
# Help-only test (unit) — does not need the bench dependencies installed.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBenchLongmemevalHelp:
    def test_help_exits_zero_and_lists_all_flags(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``distillery bench longmemeval --help`` lists every documented flag.

        Guards against argparse regressions and against silently dropping a
        flag from the parser builder.
        """
        with pytest.raises(SystemExit) as exc:
            main(["bench", "longmemeval", "--help"])
        assert exc.value.code == 0

        captured = capsys.readouterr()
        out = captured.out

        assert "longmemeval" in out.lower()

        # Each user-facing flag must appear in --help.
        for flag in (
            "--retrieval",
            "--granularity",
            "--recency",
            "--embed-model",
            "--limit",
            "--seeds",
            "--output-dir",
            "--quiet",
        ):
            assert flag in out, f"missing {flag} from --help"

        # Choices for each enum flag must show up too.
        for choice in ("raw", "hybrid", "session", "turn", "bge-small", "jina"):
            assert choice in out, f"missing choice {choice!r} from --help"

    def test_bench_no_subcommand_errors(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``distillery bench`` without a sub-subcommand should error out."""
        with pytest.raises(SystemExit) as exc:
            main(["bench"])
        # argparse.error exits with code 2; our handler errors with non-zero.
        assert exc.value.code != 0


# ---------------------------------------------------------------------------
# Integration smoke test — runs the full pipeline against the mini fixture.
# ---------------------------------------------------------------------------


def _load_fixture() -> list[dict[str, Any]]:
    with FIXTURE_PATH.open() as f:
        data: list[dict[str, Any]] = json.load(f)
    return data


class _KeywordEmbedder:
    """Deterministic keyword embedder used to avoid fastembed downloads.

    Mirrors the stub in ``tests/eval/test_longmemeval_runner.py`` so the
    fixture's hand-crafted "easy" question is solvable.
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
        return "keyword-stub-cli-test"


@pytest.mark.integration
class TestBenchLongmemevalRun:
    def test_smoke_run_writes_jsonl_and_prints_summary(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Smoke: ``distillery bench longmemeval --limit 1`` writes JSONL.

        Patches both:
          * the runner's embedding-provider factory with the keyword stub,
            so no weights are downloaded.
          * the dataset loader so the mini fixture stands in for the real
            HuggingFace download.
        """
        # Patch the embedding factory used inside the runner.
        from distillery.eval import longmemeval as bench_module

        def _stub_provider(_model: str) -> _KeywordEmbedder:
            return _KeywordEmbedder()

        monkeypatch.setattr(bench_module, "_build_embedding_provider", _stub_provider)

        # Replace the dataset loader to return the bundled fixture so the
        # CLI path does not hit HuggingFace from a CI runner. The runner
        # awaits ``load_longmemeval()`` so the stub must return an awaitable.
        fixture = _load_fixture()

        async def _stub_loader() -> list[dict[str, Any]]:
            return fixture

        monkeypatch.setattr(bench_module, "load_longmemeval", _stub_loader)

        out_dir = tmp_path / "results"

        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "bench",
                    "longmemeval",
                    "--limit",
                    "1",
                    "--output-dir",
                    str(out_dir),
                    "--quiet",
                ]
            )
        assert exc.value.code == 0, "CLI exit code should be 0 on success"

        # Output directory must exist and contain at least one JSONL + one
        # summary file.
        assert out_dir.is_dir()
        jsonl_files = list(out_dir.glob("results_longmemeval_*.jsonl"))
        summary_files = list(out_dir.glob("summary_longmemeval_*.json"))
        assert len(jsonl_files) == 1, f"expected one JSONL, got {jsonl_files!r}"
        assert len(summary_files) == 1, f"expected one summary, got {summary_files!r}"

        # Each JSONL line must carry the SHA panel under ``_meta``.
        with jsonl_files[0].open() as f:
            records = [json.loads(line) for line in f if line.strip()]
        assert records, "JSONL must contain at least one record"
        for rec in records:
            assert "_meta" in rec, "missing _meta block (SHA panel)"
            meta = rec["_meta"]
            for key in (
                "git_sha",
                "dataset_revision_sha",
                "dataset_file_sha256",
                "embed_model_sha",
                "python_version",
                "seed",
                "timestamp_utc",
            ):
                assert key in meta, f"missing {key} from _meta"

        # The headline summary line must appear on stdout in the exact
        # ``R@5=... R@10=... NDCG@10=... (n=...) -> <path>`` shape.
        captured = capsys.readouterr()
        summary_line = captured.out.strip().splitlines()[-1]
        match = re.match(
            r"^R@5=\d+\.\d{3} R@10=\d+\.\d{3} NDCG@10=\d+\.\d{3} \(n=\d+\) -> .+\.jsonl$",
            summary_line,
        )
        assert match is not None, f"unexpected summary line: {summary_line!r}"
        assert str(jsonl_files[0]) in summary_line

    def test_smoke_run_format_json_emits_parseable_envelope(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--format json`` must emit a single JSON object on stdout.

        The scripted-automation contract is JSON, so this catches stray
        prints and key-shape regressions on the most automation-sensitive
        path.
        """
        from distillery.eval import longmemeval as bench_module

        def _stub_provider(_model: str) -> _KeywordEmbedder:
            return _KeywordEmbedder()

        async def _stub_loader() -> list[dict[str, Any]]:
            return _load_fixture()

        monkeypatch.setattr(bench_module, "_build_embedding_provider", _stub_provider)
        monkeypatch.setattr(bench_module, "load_longmemeval", _stub_loader)

        out_dir = tmp_path / "results-json"

        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "--format",
                    "json",
                    "bench",
                    "longmemeval",
                    "--limit",
                    "1",
                    "--output-dir",
                    str(out_dir),
                    "--quiet",
                ]
            )
        assert exc.value.code == 0, "CLI exit code should be 0 on success"

        captured = capsys.readouterr()
        # Stdout must be exactly one JSON object — no banner, no trailing
        # text. A clean parse + key check is sufficient.
        payload = json.loads(captured.out.strip())
        assert isinstance(payload, dict)
        for key in (
            "n_questions",
            "recall_at_5",
            "recall_at_10",
            "ndcg_at_10",
            "jsonl_path",
            "summary_path",
        ):
            assert key in payload, f"missing {key} from JSON envelope"
        assert payload["jsonl_path"] is not None
        assert payload["jsonl_path"].endswith(".jsonl")

    def test_invalid_output_dir_errors(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """If output dir cannot be created, the CLI exits non-zero."""
        # Make a path under a regular file so mkdir fails with NotADirectoryError.
        blocker = tmp_path / "blocker"
        blocker.write_text("nope")
        bad_path = blocker / "results"

        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "bench",
                    "longmemeval",
                    "--limit",
                    "1",
                    "--output-dir",
                    str(bad_path),
                    "--quiet",
                ]
            )
        assert exc.value.code != 0
        captured = capsys.readouterr()
        assert "cannot create output directory" in captured.err.lower()


@pytest.mark.unit
class TestBenchLongmemevalArgValidation:
    """argparse-time validation of ``--limit`` / ``--seeds``.

    Both flags must be ``> 0`` so the bench cannot silently produce an
    empty (and falsely successful) run. Validation happens at parse time
    so the failure is surfaced before any heavy bench import.
    """

    @pytest.mark.parametrize(
        "flag,value",
        [
            ("--limit", "0"),
            ("--limit", "-1"),
            ("--seeds", "0"),
            ("--seeds", "-3"),
        ],
    )
    def test_non_positive_int_rejected(
        self,
        flag: str,
        value: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["bench", "longmemeval", flag, value])
        # argparse always exits 2 on a bad type/value.
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "must be > 0" in captured.err

    @pytest.mark.parametrize("value", ["-1", "-5"])
    def test_negative_seed_offset_rejected(
        self,
        value: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--seed-offset`` rejects negative values but accepts ``0``.

        The variance-gate matrix dispatches offsets ``0..4``, so ``0``
        must remain valid (unlike ``--seeds`` / ``--limit`` which must
        be ``> 0``).  Only negative values are nonsense.
        """
        with pytest.raises(SystemExit) as exc:
            main(["bench", "longmemeval", "--seed-offset", value])
        assert exc.value.code == 2
        captured = capsys.readouterr()
        assert "must be >= 0" in captured.err

    def test_zero_seed_offset_accepted(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--seed-offset 0 --help`` parses cleanly (no argparse error)."""
        # Use --help to short-circuit before any heavy imports / network.
        with pytest.raises(SystemExit) as exc:
            main(["bench", "longmemeval", "--seed-offset", "0", "--help"])
        # --help exits 0; only argparse type errors exit 2.
        assert exc.value.code == 0


@pytest.mark.unit
class TestBenchLongmemevalSeedOffsetFlag:
    """``--seed-offset`` is documented and round-trips through argparse."""

    def test_seed_offset_appears_in_help(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--help`` lists ``--seed-offset`` so the variance-gate workflow
        and any external CI matrix can discover the flag without reading
        source.
        """
        with pytest.raises(SystemExit) as exc:
            main(["bench", "longmemeval", "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "--seed-offset" in out

    def test_seed_offset_round_trips_to_runner(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--seed-offset N`` reaches ``run_longmemeval_bench`` unchanged.

        We don't run the bench end-to-end here — we monkeypatch the
        runner with a recording stub so the unit test stays fast and
        does not depend on fastembed weights.
        """
        from distillery import cli as cli_module

        captured_kwargs: dict[str, Any] = {}

        async def _stub_runner(**kwargs: Any) -> Any:
            captured_kwargs.update(kwargs)
            from distillery.eval.longmemeval import BenchReport

            return BenchReport(
                summary={
                    "n_questions": 0,
                    "overall": {
                        "recall_at_5": 0.0,
                        "recall_at_10": 0.0,
                        "ndcg_at_10": 0.0,
                    },
                },
                per_question=[],
                jsonl_path=None,
                summary_path=None,
            )

        monkeypatch.setattr(
            "distillery.eval.longmemeval.run_longmemeval_bench",
            _stub_runner,
        )
        # The CLI's lazy import binds the symbol into a local name; force
        # the lazy import path to re-resolve from the module so the patch
        # is observed.
        if hasattr(cli_module, "run_longmemeval_bench"):  # pragma: no cover - defensive
            monkeypatch.setattr(
                cli_module,
                "run_longmemeval_bench",
                _stub_runner,
                raising=False,
            )

        out_dir = tmp_path / "results"
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "bench",
                    "longmemeval",
                    "--seed-offset",
                    "3",
                    "--seeds",
                    "1",
                    "--output-dir",
                    str(out_dir),
                    "--quiet",
                ]
            )
        assert exc.value.code == 0
        assert captured_kwargs.get("seed_offset") == 3
        assert captured_kwargs.get("seeds") == 1
