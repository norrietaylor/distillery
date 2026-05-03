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
        # CLI path does not hit HuggingFace from a CI runner.
        fixture = _load_fixture()
        monkeypatch.setattr(bench_module, "load_longmemeval", lambda: fixture)

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
