"""Tests for distillery.cli: main(), status, health, export, import subcommands."""

from __future__ import annotations

import asyncio
import json
import os
import textwrap
from pathlib import Path
from typing import Any

import pytest

from distillery import __version__
from distillery.cli import (
    _build_parser,
    _check_health,
    _cmd_export,
    _cmd_gh_backfill,
    _cmd_health,
    _cmd_import,
    _cmd_maintenance_classify,
    _cmd_retag,
    _cmd_status,
    _query_status,
    main,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_yaml(tmp_path: Path, content: str, name: str = "distillery.yaml") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content))
    return p


def write_config(tmp_path: Path, db_path: str) -> Path:
    return write_yaml(
        tmp_path,
        f"""\
        storage:
          backend: duckdb
          database_path: "{db_path}"
        embedding:
          provider: ""
        """,
    )


# ---------------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------------


class TestVersion:
    def test_version_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert f"distillery {__version__}" in captured.out

    def test_version_matches_pyproject(self) -> None:
        """__version__ must match the version in pyproject.toml."""
        import tomllib
        from pathlib import Path

        from distillery import __version__ as ver

        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        with open(pyproject, "rb") as f:
            meta = tomllib.load(f)
        assert ver == meta["project"]["version"]


# ---------------------------------------------------------------------------
# No subcommand -> help
# ---------------------------------------------------------------------------


class TestNoSubcommand:
    def test_no_args_prints_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "usage" in captured.out.lower()

    def test_help_flag_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            main(["--help"])
        captured = capsys.readouterr()
        assert "usage" in captured.out.lower()


# ---------------------------------------------------------------------------
# Invalid subcommand
# ---------------------------------------------------------------------------


class TestInvalidSubcommand:
    def test_invalid_subcommand_exits_nonzero(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["frobnicate"])
        assert exc.value.code != 0


# ---------------------------------------------------------------------------
# health subcommand
# ---------------------------------------------------------------------------


class TestHealthCommand:
    def test_health_memory_db_ok(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit) as exc:
            main(["health", "--config", str(cfg_path)])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "OK" in captured.out

    def test_health_existing_parent_dir_ok(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db_path = tmp_path / "test.db"
        cfg_path = write_config(tmp_path, str(db_path))
        # The parent directory exists but the DB file doesn't yet -- should pass.
        with pytest.raises(SystemExit) as exc:
            main(["health", "--config", str(cfg_path)])
        assert exc.value.code == 0

    def test_health_bad_path_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Point DB at a non-existent parent directory.
        bad_path = str(tmp_path / "nonexistent" / "sub" / "test.db")
        cfg_path = write_config(tmp_path, bad_path)
        with pytest.raises(SystemExit) as exc:
            main(["health", "--config", str(cfg_path)])
        assert exc.value.code == 1

    def test_health_text_format_contains_ok(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit):
            main(["health", "--config", str(cfg_path), "--format", "text"])
        captured = capsys.readouterr()
        assert "status: OK" in captured.out

    def test_health_json_format(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit):
            main(["health", "--config", str(cfg_path), "--format", "json"])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "OK"
        assert "database_path" in data

    def test_health_missing_config_file_exits_one(
        self,
        tmp_path: Path,
    ) -> None:
        missing = str(tmp_path / "no_such.yaml")
        with pytest.raises(SystemExit) as exc:
            main(["health", "--config", missing])
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# status subcommand
# ---------------------------------------------------------------------------


class TestStatusCommand:
    def test_status_memory_db_exits_zero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit) as exc:
            main(["status", "--config", str(cfg_path)])
        assert exc.value.code == 0

    def test_status_output_contains_required_fields(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit):
            main(["status", "--config", str(cfg_path)])
        out = capsys.readouterr().out
        assert "total_entries" in out
        assert "entries_by_type" in out
        assert "entries_by_status" in out
        assert "database_path" in out
        assert "embedding_model" in out

    def test_status_json_format(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit):
            main(["status", "--config", str(cfg_path), "--format", "json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "total_entries" in data
        assert "entries_by_type" in data
        assert "entries_by_status" in data
        assert "database_path" in data
        assert "embedding_model" in data

    def test_status_shows_embedding_model(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit):
            main(["status", "--config", str(cfg_path), "--format", "json"])
        data = json.loads(capsys.readouterr().out)
        assert data["embedding_model"] == "jina-embeddings-v3"

    def test_status_missing_config_exits_one(
        self,
        tmp_path: Path,
    ) -> None:
        missing = str(tmp_path / "no_such.yaml")
        with pytest.raises(SystemExit) as exc:
            main(["status", "--config", missing])
        assert exc.value.code == 1

    def test_status_malformed_yaml_prints_friendly_error(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Malformed YAML should surface as a one-line error, not a traceback."""
        bad = tmp_path / "bad.yaml"
        bad.write_text("storage:\n  database_path: [unterminated\n")
        with pytest.raises(SystemExit) as exc:
            main(["status", "--config", str(bad)])
        assert exc.value.code == 1
        captured = capsys.readouterr()
        err = captured.err
        assert "Error loading configuration" in err
        assert "Invalid YAML syntax" in err
        # No Python traceback lines should leak to stderr.
        assert "Traceback" not in err
        assert "yaml.parser" not in err
        assert "yaml.scanner" not in err

    def test_status_fresh_db_file_reports_empty_state(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Regression for #375: status on a never-created DB file exits 0 with empty state.

        Mirrors ``health``'s tolerance — an operator running ``status`` on a
        fresh install/container should see a friendly empty-state summary
        rather than "database does not exist" with exit 1.
        """
        db_path = tmp_path / "fresh.db"
        cfg_path = write_config(tmp_path, str(db_path))
        with pytest.raises(SystemExit) as exc:
            main(["status", "--config", str(cfg_path), "--format", "json"])
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total_entries"] == 0
        assert data["entries_by_type"] == {}
        assert data["entries_by_status"] == {}
        # Status must not create the DB file as a side effect (parity with health).
        assert not db_path.exists()


# ---------------------------------------------------------------------------
# --config flag
# ---------------------------------------------------------------------------


class TestConfigFlag:
    def test_config_flag_loads_custom_file(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit) as exc:
            main(["status", "--config", str(cfg_path)])
        assert exc.value.code == 0

    def test_config_flag_with_nonexistent_file_exits_one(
        self,
        tmp_path: Path,
    ) -> None:
        missing = str(tmp_path / "ghost.yaml")
        with pytest.raises(SystemExit) as exc:
            main(["status", "--config", missing])
        assert exc.value.code == 1

    # --- Regression: #373 — top-level flags must survive the subparser -------

    def test_top_level_config_flag_before_subcommand_reaches_handler(
        self,
        tmp_path: Path,
    ) -> None:
        """``distillery --config X status`` must honour the top-level --config.

        Regression test for #373 — argparse used to let the subparser's default
        clobber the parent-parsed value, silently dropping the user's --config.
        """
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit) as exc:
            main(["--config", str(cfg_path), "status"])
        assert exc.value.code == 0

    def test_top_level_format_flag_before_subcommand_reaches_handler(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``distillery --format json status`` must emit JSON (regression for #373)."""
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit) as exc:
            main(["--config", str(cfg_path), "--format", "json", "status"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        # JSON output is a parseable object; text output is not.
        json.loads(captured.out)

    @pytest.mark.parametrize(
        "argv",
        [
            # Both orderings of --config: before and after the subcommand.
            ["--config", "/tmp/X.yaml", "status"],
            ["status", "--config", "/tmp/X.yaml"],
            # Both orderings of --format.
            ["--format", "json", "status"],
            ["status", "--format", "json"],
            # Combined — all flags before the subcommand.
            ["--config", "/tmp/X.yaml", "--format", "json", "status"],
            # Combined — all flags after the subcommand.
            ["status", "--config", "/tmp/X.yaml", "--format", "json"],
        ],
    )
    def test_flags_yield_same_namespace_regardless_of_position(
        self,
        argv: list[str],
    ) -> None:
        """The Namespace's ``config`` / ``format`` values must not depend on flag position.

        This is the core invariant #373 violated: argparse's subparser was
        overwriting parent-parsed values with its own default (None / "text").
        """
        parser = _build_parser()
        ns = parser.parse_args(argv)
        if "--config" in argv:
            assert ns.config == "/tmp/X.yaml"
        else:
            assert ns.config is None
        if "--format" in argv:
            assert ns.format == "json"
        else:
            assert ns.format == "text"

    def test_flags_on_nested_subcommand_work_in_every_position(self) -> None:
        """Regression for #373 extended to nested ``maintenance classify``."""
        parser = _build_parser()
        for argv in [
            ["--config", "X", "maintenance", "classify"],
            ["maintenance", "--config", "X", "classify"],
            ["maintenance", "classify", "--config", "X"],
        ]:
            ns = parser.parse_args(argv)
            assert ns.config == "X", f"--config dropped for argv={argv!r}"
            assert ns.command == "maintenance"
            assert ns.maintenance_command == "classify"


# ---------------------------------------------------------------------------
# Issue #369 regression tests — top-level flags must produce identical output
# regardless of position, and malformed configs must surface friendly errors.
# ---------------------------------------------------------------------------


class TestIssue369TopLevelFlagPropagation:
    """End-to-end regression suite for issue #369 rows L1.6, L1.7, L1.8, L1.11."""

    def test_status_json_identical_with_top_level_or_subcommand_format(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L1.6: ``distillery --format json status`` matches ``distillery status --format json``."""
        cfg_path = write_config(tmp_path, ":memory:")

        with pytest.raises(SystemExit):
            main(["--format", "json", "status", "--config", str(cfg_path)])
        out_top = capsys.readouterr().out

        with pytest.raises(SystemExit):
            main(["status", "--config", str(cfg_path), "--format", "json"])
        out_sub = capsys.readouterr().out

        # Both must be valid JSON and structurally identical.
        assert json.loads(out_top) == json.loads(out_sub)

    def test_health_json_identical_with_top_level_or_subcommand_format(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L1.7: same invariant for the ``health`` subcommand."""
        cfg_path = write_config(tmp_path, ":memory:")

        with pytest.raises(SystemExit):
            main(["--format", "json", "health", "--config", str(cfg_path)])
        out_top = capsys.readouterr().out

        with pytest.raises(SystemExit):
            main(["health", "--config", str(cfg_path), "--format", "json"])
        out_sub = capsys.readouterr().out

        assert json.loads(out_top) == json.loads(out_sub)

    def test_top_level_config_flag_uses_supplied_db_path(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L1.8: ``--config`` works at the top level AND after the subcommand, identically.

        Mirrors the L1.6/L1.7 dual-position pattern: running the CLI twice
        (once with ``--config`` before the subcommand, once after) must
        produce the same JSON output. Guards against a regression that flips
        propagation direction — i.e. only one position remaining wired up.
        """
        db_path = tmp_path / "explicit.db"
        cfg_path = write_config(tmp_path, str(db_path))

        with pytest.raises(SystemExit) as exc:
            main(["--config", str(cfg_path), "--format", "json", "status"])
        assert exc.value.code == 0
        data_top = json.loads(capsys.readouterr().out)

        with pytest.raises(SystemExit) as exc:
            main(["status", "--config", str(cfg_path), "--format", "json"])
        assert exc.value.code == 0
        data_sub = json.loads(capsys.readouterr().out)

        assert data_top["database_path"] == str(db_path)
        assert data_top == data_sub

    def test_malformed_yaml_no_traceback_subprocess(
        self,
        tmp_path: Path,
    ) -> None:
        """L1.11: malformed YAML exits nonzero and surfaces a readable error.

        Invoked as a subprocess to assert the *real* stderr a user would see
        — no Python traceback, the bad config path is named, and exit is
        nonzero. Mirrors the issue #369 reproduction harness.
        """
        import shutil
        import subprocess

        distillery_bin = shutil.which("distillery")
        if distillery_bin is None:
            if os.environ.get("CI"):
                pytest.fail(
                    "distillery console script missing from PATH in CI — packaging regression?"
                )
            pytest.skip(
                "distillery console script not installed on PATH (run `pip install -e .` locally)"
            )

        bad = tmp_path / "bad.yaml"
        # Truly malformed YAML (unterminated flow sequence).
        bad.write_text("storage:\n  database_path: [unterminated\n")

        result = subprocess.run(
            [distillery_bin, "--config", str(bad), "status"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode != 0
        # Friendly error mentions the file path.
        assert str(bad) in result.stderr
        # No Python traceback leaks to stderr.
        assert "Traceback" not in result.stderr
        assert "yaml.parser" not in result.stderr
        assert "yaml.scanner" not in result.stderr


# ---------------------------------------------------------------------------
# DISTILLERY_CONFIG environment variable
# ---------------------------------------------------------------------------


class TestEnvVarConfig:
    def test_env_var_respected(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        from distillery.config import CONFIG_ENV_VAR

        monkeypatch.setenv(CONFIG_ENV_VAR, str(cfg_path))
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc:
            main(["status"])
        assert exc.value.code == 0


# ---------------------------------------------------------------------------
# _check_health unit tests
# ---------------------------------------------------------------------------


class TestCheckHealth:
    def test_memory_db_always_healthy(self) -> None:
        assert _check_health(":memory:") is True

    def test_existing_parent_dir_healthy(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "fresh.db")
        assert _check_health(db_path) is True

    def test_missing_parent_dir_unhealthy(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "nonexistent" / "deep" / "db.db")
        assert _check_health(db_path) is False


# ---------------------------------------------------------------------------
# _query_status unit tests
# ---------------------------------------------------------------------------


class TestQueryStatus:
    def test_memory_db_empty(self) -> None:
        result = _query_status(":memory:")
        assert result["total_entries"] == 0
        assert result["entries_by_type"] == {}
        assert result["entries_by_status"] == {}

    def test_returns_expected_keys(self) -> None:
        result = _query_status(":memory:")
        assert "total_entries" in result
        assert "entries_by_type" in result
        assert "entries_by_status" in result
        assert "schema_version" in result
        assert "duckdb_version" in result

    def test_version_keys_none_on_uninitialised_db(self) -> None:
        """schema_version and duckdb_version are None when _meta table is absent."""
        result = _query_status(":memory:")
        assert result["schema_version"] is None
        assert result["duckdb_version"] is None

    def test_bad_path_raises_runtime_error(self, tmp_path: Path) -> None:
        bad = str(tmp_path / "no_dir" / "x.db")
        with pytest.raises(RuntimeError):
            _query_status(bad)

    def test_missing_db_file_with_existing_parent_reports_empty(self, tmp_path: Path) -> None:
        """A fresh/uninitialised DB file (parent dir exists) reports empty state (issue #375)."""
        db_path = str(tmp_path / "never-initialized.db")
        result = _query_status(db_path)
        assert result["total_entries"] == 0
        assert result["entries_by_type"] == {}
        assert result["entries_by_status"] == {}
        assert result["schema_version"] is None
        assert result["duckdb_version"] is None
        # The DB file must NOT have been created as a side effect.
        assert not Path(db_path).exists()


# ---------------------------------------------------------------------------
# _cmd_status / _cmd_health unit tests
# ---------------------------------------------------------------------------


class TestCmdStatusUnit:
    def test_cmd_status_returns_zero_for_memory(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        rc = _cmd_status(str(cfg_path), "text")
        assert rc == 0

    def test_cmd_status_returns_one_for_bad_config(self, tmp_path: Path) -> None:
        missing = str(tmp_path / "missing.yaml")
        rc = _cmd_status(missing, "text")
        assert rc == 1

    def test_cmd_status_returns_zero_for_missing_db_file(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Regression for #375: matches _cmd_health tolerance for uninitialised DB files."""
        db_path = tmp_path / "never-created.db"
        cfg_path = write_config(tmp_path, str(db_path))
        rc = _cmd_status(str(cfg_path), "text")
        assert rc == 0
        out = capsys.readouterr().out
        assert "total_entries:    0" in out

    def test_cmd_status_json_includes_version_keys(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """JSON output always includes schema_version and duckdb_version keys."""
        cfg_path = write_config(tmp_path, ":memory:")
        rc = _cmd_status(str(cfg_path), "json")
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "schema_version" in data
        assert "duckdb_version" in data

    def test_cmd_status_text_shows_version_when_available(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        """Text output includes schema_version/duckdb_version lines when the values are set."""
        import duckdb

        from distillery.store.duckdb import DuckDBStore

        class _FakeProvider:
            @property
            def dimensions(self) -> int:
                return 4

            @property
            def model_name(self) -> str:
                return "test-4d"

            def embed(self, text: str) -> list[float]:
                return [0.25, 0.25, 0.25, 0.25]

            def embed_batch(self, texts: list[str]) -> list[list[float]]:
                return [self.embed(t) for t in texts]

        import asyncio

        db_path = str(tmp_path / "version_test.db")
        provider = _FakeProvider()
        store = DuckDBStore(db_path=db_path, embedding_provider=provider)
        asyncio.run(store.initialize())
        asyncio.run(store.close())

        cfg_path = write_config(tmp_path, db_path)
        rc = _cmd_status(str(cfg_path), "text")
        assert rc == 0
        out = capsys.readouterr().out
        assert "schema_version:" in out
        assert "duckdb_version:" in out
        assert duckdb.__version__ in out


class TestCmdHealthUnit:
    def test_cmd_health_returns_zero_for_memory(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        rc = _cmd_health(str(cfg_path), "text")
        assert rc == 0

    def test_cmd_health_returns_one_for_bad_db_path(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path
    ) -> None:
        bad_path = str(tmp_path / "no_dir" / "sub" / "x.db")
        cfg_path = write_config(tmp_path, bad_path)
        rc = _cmd_health(str(cfg_path), "text")
        assert rc == 1


# ---------------------------------------------------------------------------
# export subcommand
# ---------------------------------------------------------------------------


class _DummyProvider:
    """Minimal embedding provider for test DB initialization."""

    @property
    def dimensions(self) -> int:
        return 4

    @property
    def model_name(self) -> str:
        return "test-4d"

    def embed(self, text: str) -> list[float]:
        return [0.25, 0.25, 0.25, 0.25]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def _init_test_db(db_path: str) -> None:
    """Create and initialize a test database so export can open it read-only."""
    import asyncio

    from distillery.store.duckdb import DuckDBStore

    store = DuckDBStore(db_path=db_path, embedding_provider=_DummyProvider())
    asyncio.run(store.initialize())
    asyncio.run(store.close())


class TestExportCommand:
    def test_export_creates_json_file(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db_path = str(tmp_path / "test.db")
        _init_test_db(db_path)
        cfg_path = write_config(tmp_path, db_path)
        out_path = str(tmp_path / "export.json")
        with pytest.raises(SystemExit) as exc:
            main(["export", "--config", str(cfg_path), "--output", out_path])
        assert exc.value.code == 0
        assert Path(out_path).exists()

    def test_export_json_structure(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db_path = str(tmp_path / "test.db")
        _init_test_db(db_path)
        cfg_path = write_config(tmp_path, db_path)
        out_path = str(tmp_path / "export.json")
        with pytest.raises(SystemExit):
            main(["export", "--config", str(cfg_path), "--output", out_path])
        data = json.loads(Path(out_path).read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert "exported_at" in data
        assert "meta" in data
        assert "entries" in data
        assert "feed_sources" in data

    def test_export_no_embedding_in_entries(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db_path = str(tmp_path / "test.db")
        _init_test_db(db_path)
        cfg_path = write_config(tmp_path, db_path)
        out_path = str(tmp_path / "export.json")
        with pytest.raises(SystemExit):
            main(["export", "--config", str(cfg_path), "--output", out_path])
        data = json.loads(Path(out_path).read_text(encoding="utf-8"))
        for entry in data["entries"]:
            assert "embedding" not in entry

    def test_export_stdout_message(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db_path = str(tmp_path / "test.db")
        _init_test_db(db_path)
        cfg_path = write_config(tmp_path, db_path)
        out_path = str(tmp_path / "export.json")
        with pytest.raises(SystemExit):
            main(["export", "--config", str(cfg_path), "--output", out_path])
        captured = capsys.readouterr()
        assert "Exported" in captured.out
        assert "entries" in captured.out
        assert "feed sources" in captured.out

    def test_export_missing_config_exits_one(
        self,
        tmp_path: Path,
    ) -> None:
        missing = str(tmp_path / "no_such.yaml")
        out_path = str(tmp_path / "export.json")
        with pytest.raises(SystemExit) as exc:
            main(["export", "--config", missing, "--output", out_path])
        assert exc.value.code == 1

    def test_export_output_required(
        self,
        tmp_path: Path,
    ) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit) as exc:
            main(["export", "--config", str(cfg_path)])
        assert exc.value.code != 0

    def test_cmd_export_returns_zero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db_path = str(tmp_path / "test.db")
        _init_test_db(db_path)
        cfg_path = write_config(tmp_path, db_path)
        out_path = str(tmp_path / "export.json")
        rc = _cmd_export(str(cfg_path), "text", out_path)
        assert rc == 0

    def test_cmd_export_bad_config_returns_one(
        self,
        tmp_path: Path,
    ) -> None:
        missing = str(tmp_path / "missing.yaml")
        out_path = str(tmp_path / "export.json")
        rc = _cmd_export(missing, "text", out_path)
        assert rc == 1


def _seed_export_db(db_path: str) -> None:
    """Populate a DB with mixed entries + feed sources for filter tests."""
    import asyncio

    from distillery.models import EntrySource, EntryType
    from distillery.store.duckdb import DuckDBStore
    from tests.conftest import make_entry

    async def _setup() -> None:
        from distillery.mcp._stub_embedding import StubEmbeddingProvider

        store = DuckDBStore(db_path=db_path, embedding_provider=StubEmbeddingProvider())
        await store.initialize()
        # Target row: session + both tags + claude-code origin.
        await store.store(
            make_entry(
                content="session match",
                entry_type=EntryType.SESSION,
                source=EntrySource.CLAUDE_CODE,
                tags=["domain/competitive", "team/eng"],
            )
        )
        # Session but missing one of the AND tags.
        await store.store(
            make_entry(
                content="session partial tags",
                entry_type=EntryType.SESSION,
                source=EntrySource.CLAUDE_CODE,
                tags=["domain/competitive"],
            )
        )
        # Right tags but wrong type.
        await store.store(
            make_entry(
                content="inbox wrong type",
                entry_type=EntryType.INBOX,
                source=EntrySource.MANUAL,
                tags=["domain/competitive", "team/eng"],
            )
        )
        # Feed entry attributed to a feed URL via metadata.source_url.
        await store.store(
            make_entry(
                content="feed item",
                entry_type=EntryType.FEED,
                source=EntrySource.MANUAL,
                tags=[],
                metadata={"source_type": "rss", "source_url": "https://eng.example.com/feed"},
            )
        )
        await store.add_feed_source(
            url="https://eng.example.com/feed", source_type="rss", label="eng"
        )
        await store.add_feed_source(
            url="https://mkt.example.com/feed", source_type="rss", label="mkt"
        )
        await store.close()

    asyncio.run(_setup())


class TestExportFilters:
    def test_type_and_tag_filter_keeps_only_matches(
        self,
        tmp_path: Path,
    ) -> None:
        """--type session --tag a --tag b exports only the row matching all."""
        db_path = str(tmp_path / "test.db")
        _seed_export_db(db_path)
        cfg_path = write_config(tmp_path, db_path)
        out_path = str(tmp_path / "eng.json")
        rc = _cmd_export(
            str(cfg_path),
            "text",
            out_path,
            entry_types=["session"],
            tags=["domain/competitive", "team/eng"],
        )
        assert rc == 0
        data = json.loads(Path(out_path).read_text(encoding="utf-8"))
        contents = [e["content"] for e in data["entries"]]
        assert contents == ["session match"]

    def test_no_filters_exports_whole_store(
        self,
        tmp_path: Path,
    ) -> None:
        """No filters reproduces the current whole-store output byte-for-byte."""
        db_path = str(tmp_path / "test.db")
        _seed_export_db(db_path)
        cfg_path = write_config(tmp_path, db_path)
        unfiltered = str(tmp_path / "all.json")
        defaulted = str(tmp_path / "all_defaults.json")
        rc1 = _cmd_export(str(cfg_path), "text", unfiltered)
        rc2 = _cmd_export(
            str(cfg_path),
            "text",
            defaulted,
            entry_types=None,
            tags=None,
            sources=None,
            status="any",
        )
        assert rc1 == 0
        assert rc2 == 0
        a = json.loads(Path(unfiltered).read_text(encoding="utf-8"))
        b = json.loads(Path(defaulted).read_text(encoding="utf-8"))
        # All four seeded entries and both feed sources present.
        assert len(a["entries"]) == 4
        assert len(a["feed_sources"]) == 2
        # Explicit defaults match the bare call's structure (ignoring timestamp).
        a.pop("exported_at")
        b.pop("exported_at")
        assert a == b

    def test_source_filters_entries_and_feed_sources(
        self,
        tmp_path: Path,
    ) -> None:
        """--source keeps matching entries and only the matching feed sources."""
        db_path = str(tmp_path / "test.db")
        _seed_export_db(db_path)
        cfg_path = write_config(tmp_path, db_path)
        out_path = str(tmp_path / "feed.json")
        rc = _cmd_export(
            str(cfg_path),
            "text",
            out_path,
            sources=["https://eng.example.com/feed"],
        )
        assert rc == 0
        data = json.loads(Path(out_path).read_text(encoding="utf-8"))
        # Only the feed entry whose metadata.source_url matches.
        assert [e["content"] for e in data["entries"]] == ["feed item"]
        # Feed-source export is limited to the selected URL.
        assert [f["url"] for f in data["feed_sources"]] == ["https://eng.example.com/feed"]

    def test_source_matches_origin_column(
        self,
        tmp_path: Path,
    ) -> None:
        """--source also matches the entry ``source`` (origin) column."""
        db_path = str(tmp_path / "test.db")
        _seed_export_db(db_path)
        cfg_path = write_config(tmp_path, db_path)
        out_path = str(tmp_path / "cc.json")
        rc = _cmd_export(str(cfg_path), "text", out_path, sources=["claude-code"])
        assert rc == 0
        data = json.loads(Path(out_path).read_text(encoding="utf-8"))
        contents = sorted(e["content"] for e in data["entries"])
        assert contents == ["session match", "session partial tags"]

    def test_status_filter_restricts_by_status(
        self,
        tmp_path: Path,
    ) -> None:
        """--status archived returns no rows when all seeded entries are active."""
        db_path = str(tmp_path / "test.db")
        _seed_export_db(db_path)
        cfg_path = write_config(tmp_path, db_path)
        out_path = str(tmp_path / "archived.json")
        rc = _cmd_export(str(cfg_path), "text", out_path, status="archived")
        assert rc == 0
        data = json.loads(Path(out_path).read_text(encoding="utf-8"))
        assert data["entries"] == []

    def test_main_passes_filter_flags(
        self,
        tmp_path: Path,
    ) -> None:
        """The argparse layer wires --type/--tag/--source through to the export."""
        db_path = str(tmp_path / "test.db")
        _seed_export_db(db_path)
        cfg_path = write_config(tmp_path, db_path)
        out_path = str(tmp_path / "via_main.json")
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "export",
                    "--config",
                    str(cfg_path),
                    "--output",
                    out_path,
                    "--type",
                    "session",
                    "--tag",
                    "domain/competitive",
                    "--tag",
                    "team/eng",
                ]
            )
        assert exc.value.code == 0
        data = json.loads(Path(out_path).read_text(encoding="utf-8"))
        assert [e["content"] for e in data["entries"]] == ["session match"]


# ---------------------------------------------------------------------------
# import subcommand
# ---------------------------------------------------------------------------

_VALID_PAYLOAD: dict = {
    "version": 1,
    "exported_at": "2026-01-01T00:00:00+00:00",
    "meta": {},
    "entries": [],
    "feed_sources": [],
}


class TestImportCommand:
    def test_import_input_required(self, tmp_path: Path) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit) as exc:
            main(["import", "--config", str(cfg_path)])
        assert exc.value.code != 0

    def test_import_missing_file_returns_one(self, tmp_path: Path) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        missing = str(tmp_path / "no_such.json")
        rc = _cmd_import(str(cfg_path), "text", missing, "merge", True)
        assert rc == 1

    def test_import_invalid_json_returns_one(self, tmp_path: Path) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json", encoding="utf-8")
        rc = _cmd_import(str(cfg_path), "text", str(bad_file), "merge", True)
        assert rc == 1

    def test_import_missing_keys_returns_one(self, tmp_path: Path) -> None:
        cfg_path = write_config(tmp_path, ":memory:")
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(json.dumps({"version": 1}), encoding="utf-8")
        rc = _cmd_import(str(cfg_path), "text", str(bad_file), "merge", True)
        assert rc == 1

    def test_import_empty_payload_succeeds(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db_path = str(tmp_path / "test.db")
        cfg_path = write_config(tmp_path, db_path)
        input_file = tmp_path / "export.json"
        input_file.write_text(json.dumps(_VALID_PAYLOAD), encoding="utf-8")
        rc = _cmd_import(str(cfg_path), "text", str(input_file), "merge", True)
        assert rc == 0
        captured = capsys.readouterr()
        assert "Imported" in captured.out
        assert "entries" in captured.out
        assert "feed sources" in captured.out

    def test_import_bad_config_returns_one(self, tmp_path: Path) -> None:
        missing_cfg = str(tmp_path / "missing.yaml")
        input_file = tmp_path / "export.json"
        input_file.write_text(json.dumps(_VALID_PAYLOAD), encoding="utf-8")
        rc = _cmd_import(missing_cfg, "text", str(input_file), "merge", True)
        assert rc == 1

    def test_import_merge_skips_existing(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Import same payload twice in merge mode — second run skips all entries."""
        db_path = str(tmp_path / "test.db")
        cfg_path = write_config(tmp_path, db_path)
        payload = dict(_VALID_PAYLOAD)
        payload["entries"] = [
            {
                "id": "aaaaaaaa-0000-0000-0000-000000000001",
                "content": "test entry content",
                "entry_type": "inbox",
                "source": "import",
                "author": "tester",
                "project": None,
                "tags": [],
                "status": "active",
                "metadata": {},
                "version": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "created_by": "",
                "last_modified_by": "",
            }
        ]
        input_file = tmp_path / "export.json"
        input_file.write_text(json.dumps(payload), encoding="utf-8")

        # First import.
        rc1 = _cmd_import(str(cfg_path), "text", str(input_file), "merge", True)
        assert rc1 == 0
        out1 = capsys.readouterr().out
        assert "Imported 1 entries" in out1

        # Second import (merge — should skip).
        rc2 = _cmd_import(str(cfg_path), "text", str(input_file), "merge", True)
        assert rc2 == 0
        out2 = capsys.readouterr().out
        assert "Imported 0 entries" in out2
        assert "1 skipped" in out2

    def test_import_replace_mode_deletes_existing(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Replace mode imports fresh — no skips even if ID already present."""
        db_path = str(tmp_path / "test.db")
        cfg_path = write_config(tmp_path, db_path)
        entry = {
            "id": "aaaaaaaa-0000-0000-0000-000000000002",
            "content": "another test entry",
            "entry_type": "inbox",
            "source": "import",
            "author": "tester",
            "project": None,
            "tags": [],
            "status": "active",
            "metadata": {},
            "version": 1,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "created_by": "",
            "last_modified_by": "",
        }
        payload = dict(_VALID_PAYLOAD)
        payload["entries"] = [entry]
        input_file = tmp_path / "export.json"
        input_file.write_text(json.dumps(payload), encoding="utf-8")

        # First import.
        rc1 = _cmd_import(str(cfg_path), "text", str(input_file), "merge", True)
        assert rc1 == 0

        # Replace import — --yes bypasses prompt.
        rc2 = _cmd_import(str(cfg_path), "text", str(input_file), "replace", True)
        assert rc2 == 0
        out = capsys.readouterr().out
        assert "Imported 1 entries" in out
        assert "0 skipped" in out

    def test_import_via_main_dispatches(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db_path = str(tmp_path / "test.db")
        cfg_path = write_config(tmp_path, db_path)
        input_file = tmp_path / "export.json"
        input_file.write_text(json.dumps(_VALID_PAYLOAD), encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "import",
                    "--config",
                    str(cfg_path),
                    "--input",
                    str(input_file),
                    "--yes",
                ]
            )
        assert exc.value.code == 0


# ---------------------------------------------------------------------------
# retag subcommand
# ---------------------------------------------------------------------------


class TestRetagCommand:
    """Tests for the ``distillery retag`` subcommand."""

    def _write_config(self, tmp_path: Path, db_path: str) -> Path:
        return write_config(tmp_path, db_path)

    def test_retag_dry_run_no_entries_exits_zero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Dry-run against empty DB reports 0 scanned and exits 0."""
        db_path = str(tmp_path / "test.db")
        cfg_path = self._write_config(tmp_path, db_path)
        rc = _cmd_retag(str(cfg_path), "text", dry_run=True, force=False)
        assert rc == 0
        out = capsys.readouterr().out
        assert "total_scanned: 0" in out

    def test_retag_dry_run_json_format(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """JSON output includes dry_run flag and counts."""
        db_path = str(tmp_path / "test.db")
        cfg_path = self._write_config(tmp_path, db_path)
        rc = _cmd_retag(str(cfg_path), "json", dry_run=True, force=False)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["dry_run"] is True
        assert data["total_scanned"] == 0
        assert data["total_updated"] == 0

    def test_retag_dry_run_does_not_modify_entries(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Dry-run with feed entries present does not persist tag changes."""
        import asyncio

        from distillery.models import EntrySource, EntryType
        from distillery.store.duckdb import DuckDBStore
        from tests.conftest import make_entry

        db_path = str(tmp_path / "test.db")
        cfg_path = self._write_config(tmp_path, db_path)

        async def _setup() -> None:
            from distillery.mcp._stub_embedding import StubEmbeddingProvider

            store = DuckDBStore(db_path=db_path, embedding_provider=StubEmbeddingProvider())
            await store.initialize()
            # Add vocabulary via a tagged inbox entry.
            seed = make_entry(
                content="seed",
                tags=["security"],
                entry_type=EntryType.INBOX,
                source=EntrySource.MANUAL,
            )
            await store.store(seed)
            # Feed entry without tags.
            feed_entry = make_entry(
                content="critical security vulnerability disclosed",
                entry_type=EntryType.FEED,
                source=EntrySource.MANUAL,
                tags=[],
                metadata={"source_type": "rss", "source_url": "https://example.com/feed"},
            )
            await store.store(feed_entry)
            await store.close()

        asyncio.run(_setup())

        rc = _cmd_retag(str(cfg_path), "text", dry_run=True, force=False)
        assert rc == 0

        async def _check() -> list[str]:
            from distillery.mcp._stub_embedding import StubEmbeddingProvider

            store = DuckDBStore(db_path=db_path, embedding_provider=StubEmbeddingProvider())
            await store.initialize()
            entries = await store.list_entries(filters={"entry_type": "feed"}, limit=10, offset=0)
            await store.close()
            return entries[0].tags if entries else []

        tags_after = asyncio.run(_check())
        # Tags must remain empty after dry-run.
        assert tags_after == []

    def test_retag_updates_untagged_entries(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Retag writes derived tags to entries that have none."""
        import asyncio

        from distillery.models import EntrySource, EntryType
        from distillery.store.duckdb import DuckDBStore
        from tests.conftest import make_entry

        db_path = str(tmp_path / "test.db")
        cfg_path = self._write_config(tmp_path, db_path)

        async def _setup() -> None:
            from distillery.mcp._stub_embedding import StubEmbeddingProvider

            store = DuckDBStore(db_path=db_path, embedding_provider=StubEmbeddingProvider())
            await store.initialize()
            # Seed vocabulary.
            seed = make_entry(
                content="seed",
                tags=["security"],
                entry_type=EntryType.INBOX,
                source=EntrySource.MANUAL,
            )
            await store.store(seed)
            # Feed entry without tags whose content mentions security.
            feed_entry = make_entry(
                content="critical security patch released",
                entry_type=EntryType.FEED,
                source=EntrySource.MANUAL,
                tags=[],
                metadata={"source_type": "rss", "source_url": "https://example.com/feed"},
            )
            await store.store(feed_entry)
            await store.close()

        asyncio.run(_setup())

        rc = _cmd_retag(str(cfg_path), "json", dry_run=False, force=False)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total_scanned"] >= 1

    def test_retag_force_retags_all_entries(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--force causes already-tagged feed entries to be re-evaluated."""
        import asyncio

        from distillery.models import EntrySource, EntryType
        from distillery.store.duckdb import DuckDBStore
        from tests.conftest import make_entry

        db_path = str(tmp_path / "test.db")
        cfg_path = self._write_config(tmp_path, db_path)

        async def _setup() -> None:
            from distillery.mcp._stub_embedding import StubEmbeddingProvider

            store = DuckDBStore(db_path=db_path, embedding_provider=StubEmbeddingProvider())
            await store.initialize()
            # Feed entry that already has a tag.
            feed_entry = make_entry(
                content="already tagged item",
                entry_type=EntryType.FEED,
                source=EntrySource.MANUAL,
                tags=["existing-tag"],
                metadata={"source_type": "rss", "source_url": "https://example.com/feed"},
            )
            await store.store(feed_entry)
            await store.close()

        asyncio.run(_setup())

        rc = _cmd_retag(str(cfg_path), "json", dry_run=False, force=True)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["total_scanned"] == 1

    def test_retag_skips_tagged_without_force(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Without --force, entries with existing tags are not retagged."""
        import asyncio

        from distillery.models import EntrySource, EntryType
        from distillery.store.duckdb import DuckDBStore
        from tests.conftest import make_entry

        db_path = str(tmp_path / "test.db")
        cfg_path = self._write_config(tmp_path, db_path)

        async def _setup() -> None:
            from distillery.mcp._stub_embedding import StubEmbeddingProvider

            store = DuckDBStore(db_path=db_path, embedding_provider=StubEmbeddingProvider())
            await store.initialize()
            tagged = make_entry(
                content="already has tags",
                entry_type=EntryType.FEED,
                source=EntrySource.MANUAL,
                tags=["keeps-tag"],
                metadata={"source_type": "rss", "source_url": "https://example.com/feed"},
            )
            await store.store(tagged)
            await store.close()

        asyncio.run(_setup())

        rc = _cmd_retag(str(cfg_path), "json", dry_run=False, force=False)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        # Entry was scanned but not updated (it already had tags).
        assert data["total_scanned"] == 1
        assert data["total_updated"] == 0

    def test_retag_missing_config_returns_one(self, tmp_path: Path) -> None:
        """Bad config path returns exit code 1."""
        missing = str(tmp_path / "no_such.yaml")
        rc = _cmd_retag(missing, "text", dry_run=True, force=False)
        assert rc == 1

    def test_retag_via_main_dispatches(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``distillery retag`` can be invoked via main()."""
        db_path = str(tmp_path / "test.db")
        cfg_path = write_config(tmp_path, db_path)
        with pytest.raises(SystemExit) as exc:
            main(["retag", "--config", str(cfg_path), "--dry-run"])
        assert exc.value.code == 0

    def test_retag_via_main_produces_text_output(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``distillery retag --dry-run`` produces visible output via main()."""
        db_path = str(tmp_path / "test.db")
        cfg_path = write_config(tmp_path, db_path)
        with pytest.raises(SystemExit) as exc:
            main(["retag", "--config", str(cfg_path), "--dry-run"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Retag complete" in captured.out
        assert "total_scanned" in captured.out

    def test_retag_via_main_produces_json_output(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``distillery retag --dry-run --format json`` produces JSON via main()."""
        db_path = str(tmp_path / "test.db")
        cfg_path = write_config(tmp_path, db_path)
        with pytest.raises(SystemExit) as exc:
            main(["retag", "--config", str(cfg_path), "--dry-run", "--format", "json"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["dry_run"] is True
        assert "total_scanned" in data


# ---------------------------------------------------------------------------
# maintenance classify subcommand
# ---------------------------------------------------------------------------


class TestMaintenanceClassifyCommand:
    def test_maintenance_classify_empty_inbox(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Empty inbox exits with 0 and shows 0 classified/pending_review/errors."""
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit) as exc:
            main(["maintenance", "classify", "--config", str(cfg_path)])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "classified" in captured.out.lower()
        assert "pending_review" in captured.out.lower()

    def test_maintenance_classify_json_format(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """JSON output format is correctly parsed."""
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit) as exc:
            main(["maintenance", "classify", "--config", str(cfg_path), "--format", "json"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "classified" in data
        assert "pending_review" in data
        assert "errors" in data
        assert "by_type" in data

    def test_maintenance_classify_missing_config(
        self,
        tmp_path: Path,
    ) -> None:
        """Missing config file returns exit code 1."""
        missing = str(tmp_path / "no_such.yaml")
        with pytest.raises(SystemExit) as exc:
            main(["maintenance", "classify", "--config", missing])
        assert exc.value.code == 1

    def test_maintenance_classify_with_type_option(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--type option is accepted."""
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit) as exc:
            main(["maintenance", "classify", "--config", str(cfg_path), "--type", "session"])
        assert exc.value.code == 0

    def test_maintenance_classify_with_mode_option(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--mode option is accepted."""
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit) as exc:
            main(["maintenance", "classify", "--config", str(cfg_path), "--mode", "heuristic"])
        assert exc.value.code == 0

    def test_maintenance_classify_help(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--help displays usage information."""
        with pytest.raises(SystemExit) as exc:
            main(["maintenance", "classify", "--help"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "usage" in captured.out.lower()
        assert "--type" in captured.out
        assert "--mode" in captured.out


# ---------------------------------------------------------------------------
# eval subcommand — JSON error-path contract (issue #376)
# ---------------------------------------------------------------------------


class TestEvalJsonErrorPaths:
    """``distillery eval --format json`` must emit valid JSON on every exit path.

    Consumers pipe the output to ``jq``; a plain-text error breaks the pipeline.
    """

    def test_eval_json_missing_scenarios_dir(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A nonexistent --scenarios-dir emits a JSON envelope on stdout."""
        missing = tmp_path / "does-not-exist"
        with pytest.raises(SystemExit) as exc:
            main(["eval", "--format", "json", "--scenarios-dir", str(missing)])
        assert exc.value.code == 1
        captured = capsys.readouterr()
        # stdout must be valid JSON — json.loads should not raise.
        data = json.loads(captured.out)
        assert data["status"] == "error"
        assert data["code"] == "scenarios_dir_not_found"
        assert str(missing) in data["message"]
        assert data["scenarios_dir"] == str(missing)

    def test_eval_json_unknown_skill_filter(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An unknown --skill filter yields an empty selection and JSON error envelope."""
        # Create a scenarios directory with one scenario for a *different* known
        # skill so the skill filter produces zero matches — rather than relying
        # on the empty-dir short-circuit to trigger no_scenarios_found.
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
        (scenarios_dir / "sample.yaml").write_text(
            "name: sample\nskill: recall\nprompt: test\n",
            encoding="utf-8",
        )
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "eval",
                    "--format",
                    "json",
                    "--scenarios-dir",
                    str(scenarios_dir),
                    "--skill",
                    "totally-not-a-skill",
                ]
            )
        assert exc.value.code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["status"] == "error"
        assert data["code"] == "no_scenarios_found"
        assert data["skill_filter"] == "totally-not-a-skill"

    def test_eval_text_missing_scenarios_dir_unchanged(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Text format retains the existing ``Error:`` stderr message."""
        missing = tmp_path / "does-not-exist"
        with pytest.raises(SystemExit) as exc:
            main(["eval", "--format", "text", "--scenarios-dir", str(missing)])
        assert exc.value.code == 1
        captured = capsys.readouterr()
        # Text path writes to stderr, not stdout.
        assert captured.out == ""
        assert "scenarios directory not found" in captured.err


# ---------------------------------------------------------------------------
# Issue #369 remaining rows — health edge cases, retag paths, gh-backfill,
# maintenance classify with pending entries, export/import lifecycle.
#
# Shared seeding helpers used by the test classes below.
# ---------------------------------------------------------------------------


#: Embedding dimensions used by the issue #369 seeding helpers.
#: Must match the default ``DistilleryConfig.embedding.dimensions`` so the
#: CLI's read path (``HashEmbeddingProvider(dimensions=cfg.embedding.dimensions)``
#: when ``provider: "mock"``) opens the seeded DB without a dimensions
#: mismatch. The default config value is 1024.
_ISSUE369_EMBED_DIMS = 1024


def _make_legacy_github_entry_raw(
    *,
    entry_id: str,
    owner: str = "acme",
    repo: str = "widgets",
    ref_type: str = "issue",
    number: int = 1,
    state: str = "open",
) -> dict[str, Any]:
    """Build a raw entry dict shaped like a pre-#312 GitHub sync entry.

    Used by L3.4/L3.5 to seed entries with ``project=None`` and ``tags=[]``
    so ``gh-backfill`` has work to do.
    """
    return {
        "id": entry_id,
        "content": f"# Legacy issue {number}",
        "entry_type": "github",
        "source": "import",
        "author": "",
        "project": None,
        "tags": [],
        "status": "active",
        "metadata": {
            "repo": f"{owner}/{repo}",
            "ref_type": ref_type,
            "ref_number": number,
            "title": f"Legacy issue {number}",
            "url": f"https://github.com/{owner}/{repo}/issues/{number}",
            "state": state,
            "labels": [],
            "assignees": [],
            "external_id": f"{owner}/{repo}#{ref_type}-{number}",
        },
        "version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "created_by": "",
        "last_modified_by": "",
    }


def _seed_entries(db_path: str, entries: list[dict[str, Any]]) -> None:
    """Initialise a DuckDBStore at *db_path* and INSERT raw rows.

    Mirrors the helper in ``tests/test_cli_export_import.py`` but lives
    here so the issue #369 tests can import it without cross-file
    dependencies. Uses ``HashEmbeddingProvider`` at the default
    embedding dimensions (1024) so the CLI's ``provider: "mock"`` read
    path opens the seeded DB without a dimensions mismatch.
    """
    import json as _json
    from datetime import UTC, datetime

    from distillery.mcp._stub_embedding import HashEmbeddingProvider
    from distillery.store.duckdb import DuckDBStore

    async def _run() -> None:
        provider = HashEmbeddingProvider(dimensions=_ISSUE369_EMBED_DIMS)
        store = DuckDBStore(db_path=db_path, embedding_provider=provider)
        await store.initialize()
        conn = store._conn  # type: ignore[attr-defined]
        assert conn is not None

        def _parse_dt(val: Any) -> datetime:
            if isinstance(val, datetime):
                return val if val.tzinfo is not None else val.replace(tzinfo=UTC)
            dt = datetime.fromisoformat(str(val))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

        for raw in entries:
            embedding = provider.embed(raw.get("content", ""))
            conn.execute(
                "INSERT INTO entries "
                "(id, content, entry_type, source, author, project, tags, status, "
                " metadata, created_at, updated_at, version, embedding, "
                " created_by, last_modified_by, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    raw["id"],
                    raw["content"],
                    raw.get("entry_type", "inbox"),
                    raw.get("source", "manual"),
                    raw.get("author", ""),
                    raw.get("project"),
                    list(raw.get("tags") or []),
                    raw.get("status", "active"),
                    _json.dumps(raw.get("metadata") or {}),
                    _parse_dt(raw["created_at"]),
                    _parse_dt(raw["updated_at"]),
                    int(raw.get("version", 1)),
                    embedding,
                    raw.get("created_by", ""),
                    raw.get("last_modified_by", ""),
                    None,
                ],
            )
        await store.close()

    asyncio.run(_run())


def _write_mock_config(tmp_path: Path, db_path: str, name: str = "distillery.yaml") -> Path:
    """Write a config that uses the ``mock`` HashEmbeddingProvider.

    Required when seeding via :func:`_seed_entries` (which uses the same
    provider) so the CLI's read path opens the database with a matching
    embedding model. Mirrors the helper in ``test_cli_export_import``.
    """
    cfg = tmp_path / name
    cfg.write_text(
        textwrap.dedent(
            f"""\
            storage:
              backend: duckdb
              database_path: "{db_path}"
            embedding:
              provider: "mock"
            """
        )
    )
    return cfg


async def _async_get_entry(db_path: str, entry_id: str) -> Any:
    """Fetch a single entry by ID using a fresh store handle."""
    from distillery.mcp._stub_embedding import HashEmbeddingProvider
    from distillery.store.duckdb import DuckDBStore

    provider = HashEmbeddingProvider(dimensions=_ISSUE369_EMBED_DIMS)
    store = DuckDBStore(db_path=db_path, embedding_provider=provider)
    await store.initialize()
    try:
        return await store.get(entry_id)
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# Group L2 — health edge cases (L2.5 corrupt DB, L2.6 health JSON shape)
# ---------------------------------------------------------------------------


class TestIssue369HealthEdgeCases:
    """L2.5 — corrupt DB file must surface a structured error, not a traceback.

    L2.6 — ``distillery --format json health`` against a healthy DB must
    emit valid JSON with a ``status`` field.
    """

    def test_health_corrupt_db_no_traceback_subprocess(
        self,
        tmp_path: Path,
    ) -> None:
        """L2.5: writing 12 bytes of garbage to the DB file must not leak a traceback.

        Invoked as a subprocess (mirrors the L1.11 pattern) so the test
        observes the real stderr a user would see. Skips when the
        ``distillery`` console script is not installed on PATH.
        """
        import shutil
        import subprocess

        distillery_bin = shutil.which("distillery")
        if distillery_bin is None:
            pytest.skip("distillery console script not installed on PATH")

        bad_db = tmp_path / "corrupt.db"
        # 12 bytes of garbage — not a valid DuckDB header.
        bad_db.write_bytes(b"NOT A DB!!!\x00")
        cfg_path = write_config(tmp_path, str(bad_db))

        result = subprocess.run(
            [distillery_bin, "--config", str(cfg_path), "health"],
            capture_output=True,
            text=True,
            check=False,
        )

        # The exact exit code may vary, but it must be nonzero AND no
        # raw Python traceback should leak to stderr.
        assert result.returncode != 0, (
            f"Expected nonzero exit on corrupt DB, got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "Traceback" not in result.stderr, (
            f"Corrupt DB leaked a Python traceback to stderr: {result.stderr!r}"
        )

    def test_health_json_format_healthy_db_emits_status(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L2.6: ``distillery --format json health`` emits parseable JSON with ``status``.

        Duplicates ``TestHealthCommand.test_health_json_format`` for
        clarity in the issue #369 coverage matrix; trivially cheap and
        keeps the row's PASS evidence anchored to a single test name.
        """
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit) as exc:
            main(["--format", "json", "health", "--config", str(cfg_path)])
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out)
        assert "status" in data
        assert data["status"] == "OK"


# ---------------------------------------------------------------------------
# Group L3 — Retag paths (L3.1 dry-run, L3.2 actual + idempotent, L3.3 --force)
# ---------------------------------------------------------------------------


class TestIssue369RetagPaths:
    """Tests for L3.1, L3.2, L3.3 — retag dry-run, actual write, --force re-run."""

    def _seed_feed_entries(self, db_path: str, count: int) -> list[str]:
        """Seed *count* feed entries with empty tags + an inbox seed for vocabulary."""
        from distillery.mcp._stub_embedding import HashEmbeddingProvider
        from distillery.models import EntrySource, EntryType
        from distillery.store.duckdb import DuckDBStore

        ids: list[str] = []

        async def _seed() -> None:
            provider = HashEmbeddingProvider(dimensions=_ISSUE369_EMBED_DIMS)
            store = DuckDBStore(db_path=db_path, embedding_provider=provider)
            await store.initialize()
            # Vocabulary seed — gives derive_all_tags a non-empty tag corpus.
            from tests.conftest import make_entry

            seed = make_entry(
                content="security advisory seed",
                tags=["security"],
                entry_type=EntryType.INBOX,
                source=EntrySource.MANUAL,
            )
            await store.store(seed)
            for i in range(count):
                feed = make_entry(
                    content=f"critical security patch released for item {i}",
                    entry_type=EntryType.FEED,
                    source=EntrySource.MANUAL,
                    tags=[],
                    metadata={
                        "source_type": "rss",
                        "source_url": f"https://example.com/feed/{i}",
                    },
                )
                fid = await store.store(feed)
                ids.append(fid)
            await store.close()

        asyncio.run(_seed())
        return ids

    def _read_tags(self, db_path: str, entry_ids: list[str]) -> dict[str, list[str]]:
        """Return ``{id: tags}`` for the given entry IDs."""
        from distillery.mcp._stub_embedding import HashEmbeddingProvider
        from distillery.store.duckdb import DuckDBStore

        async def _read() -> dict[str, list[str]]:
            provider = HashEmbeddingProvider(dimensions=_ISSUE369_EMBED_DIMS)
            store = DuckDBStore(db_path=db_path, embedding_provider=provider)
            await store.initialize()
            result: dict[str, list[str]] = {}
            try:
                for eid in entry_ids:
                    entry = await store.get(eid)
                    result[eid] = list(entry.tags) if entry is not None else []
            finally:
                await store.close()
            return result

        return asyncio.run(_read())

    def test_retag_dry_run_preserves_tags(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L3.1: ``retag --dry-run`` reports counts but does not persist tag changes."""
        db_path = str(tmp_path / "test.db")
        cfg_path = _write_mock_config(tmp_path, db_path)

        ids = self._seed_feed_entries(db_path, count=3)
        tags_before = self._read_tags(db_path, ids)

        rc = _cmd_retag(str(cfg_path), "json", dry_run=True, force=False)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["dry_run"] is True

        tags_after = self._read_tags(db_path, ids)
        # Tags must be identical pre and post.
        assert tags_before == tags_after, (
            f"Dry-run mutated DB:\n  before={tags_before}\n  after ={tags_after}"
        )

    def test_retag_actual_writes_and_is_idempotent(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L3.2: real retag writes tags; second run reports 0 updates (idempotent)."""
        db_path = str(tmp_path / "test.db")
        cfg_path = _write_mock_config(tmp_path, db_path)

        self._seed_feed_entries(db_path, count=3)

        # First run — should update some entries.
        rc1 = _cmd_retag(str(cfg_path), "json", dry_run=False, force=False)
        assert rc1 == 0
        data1 = json.loads(capsys.readouterr().out)
        assert data1["dry_run"] is False
        first_updated = data1["total_updated"]

        # Second run — without --force, entries that now have tags should
        # be skipped; updated count must be 0.
        rc2 = _cmd_retag(str(cfg_path), "json", dry_run=False, force=False)
        assert rc2 == 0
        data2 = json.loads(capsys.readouterr().out)
        assert data2["total_updated"] == 0, (
            f"Retag is not idempotent — second run updated {data2['total_updated']} "
            f"entries (first run updated {first_updated})."
        )

    def test_retag_force_reprocesses_all(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L3.3: ``--force`` rescans every feed entry, ignoring the no-empty-tags gate."""
        db_path = str(tmp_path / "test.db")
        cfg_path = _write_mock_config(tmp_path, db_path)

        self._seed_feed_entries(db_path, count=3)

        # First, do a real retag so the entries acquire tags.
        rc1 = _cmd_retag(str(cfg_path), "json", dry_run=False, force=False)
        assert rc1 == 0
        capsys.readouterr()

        # Now run with --force; total_scanned must include all feed entries
        # regardless of their tag state.
        rc2 = _cmd_retag(str(cfg_path), "json", dry_run=False, force=True)
        assert rc2 == 0
        data = json.loads(capsys.readouterr().out)
        # 3 feed entries were seeded — --force scans them all.
        assert data["total_scanned"] == 3, (
            f"--force should scan all 3 feed entries; got total_scanned={data['total_scanned']}"
        )


# ---------------------------------------------------------------------------
# Group L3 — gh-backfill (L3.4 dry-run, L3.5 actual + idempotent, L3.6 empty DB)
# ---------------------------------------------------------------------------


class TestIssue369GhBackfillPaths:
    """Tests for L3.4, L3.5, L3.6 — gh-backfill dry-run, actual write, empty DB."""

    def test_gh_backfill_dry_run_preserves_entries(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L3.4: ``gh-backfill --dry-run`` reports work but does not write."""
        db_path = str(tmp_path / "test.db")
        cfg_path = _write_mock_config(tmp_path, db_path)

        seeded = [
            _make_legacy_github_entry_raw(
                entry_id=f"deadbeef-0000-0000-0000-0000000000{i:02d}", number=i
            )
            for i in (1, 2)
        ]
        _seed_entries(db_path, seeded)

        rc = _cmd_gh_backfill(str(cfg_path), "json", dry_run=True)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["dry_run"] is True
        # Both legacy entries should be flagged as needing an update.
        assert data["entries_updated"] == 2

        # Verify DB state unchanged: project still None, tags still empty.
        for seed in seeded:
            entry = asyncio.run(_async_get_entry(db_path, seed["id"]))
            assert entry is not None
            assert entry.project is None
            assert list(entry.tags) == []

    def test_gh_backfill_actual_writes_and_is_idempotent(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L3.5: real backfill populates project + canonical tags; re-running updates 0."""
        db_path = str(tmp_path / "test.db")
        cfg_path = _write_mock_config(tmp_path, db_path)

        seeded = [
            _make_legacy_github_entry_raw(
                entry_id=f"feedface-0000-0000-0000-0000000000{i:02d}", number=i
            )
            for i in (1, 2)
        ]
        _seed_entries(db_path, seeded)

        # First run — writes.
        rc1 = _cmd_gh_backfill(str(cfg_path), "json", dry_run=False)
        assert rc1 == 0
        data1 = json.loads(capsys.readouterr().out)
        assert data1["entries_updated"] == 2

        # Verify entries now have ``project`` + canonical tags.
        for seed in seeded:
            entry = asyncio.run(_async_get_entry(db_path, seed["id"]))
            assert entry is not None
            assert entry.project == "widgets", f"project missing on {seed['id']}"
            assert "source/github" in entry.tags
            assert "repo/widgets" in entry.tags

        # Second run — idempotent.
        rc2 = _cmd_gh_backfill(str(cfg_path), "json", dry_run=False)
        assert rc2 == 0
        data2 = json.loads(capsys.readouterr().out)
        assert data2["entries_updated"] == 0, (
            f"gh-backfill is not idempotent — re-run updated {data2['entries_updated']} entries"
        )

    def test_gh_backfill_empty_db_exits_zero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L3.6: ``gh-backfill`` against an empty DB exits 0 with 0 candidates."""
        db_path = str(tmp_path / "empty.db")
        cfg_path = _write_mock_config(tmp_path, db_path)
        # No seeding — initialise the store so the table exists.
        _seed_entries(db_path, [])

        rc = _cmd_gh_backfill(str(cfg_path), "json", dry_run=False)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["entries_updated"] == 0


# ---------------------------------------------------------------------------
# Group L3 — maintenance classify (L3.7 empty, L3.8 with pending, L3.9 JSON shape)
# ---------------------------------------------------------------------------


class TestIssue369MaintenanceClassify:
    """Tests for L3.7, L3.8, L3.9 — empty inbox, pending entries, JSON shape."""

    def _seed_pending_inbox(self, db_path: str, count: int = 3) -> list[str]:
        """Seed *count* inbox entries already in ``pending_review`` status."""
        from distillery.mcp._stub_embedding import HashEmbeddingProvider
        from distillery.models import EntrySource, EntryStatus, EntryType
        from distillery.store.duckdb import DuckDBStore
        from tests.conftest import make_entry

        ids: list[str] = []

        async def _seed() -> None:
            provider = HashEmbeddingProvider(dimensions=_ISSUE369_EMBED_DIMS)
            store = DuckDBStore(db_path=db_path, embedding_provider=provider)
            await store.initialize()
            # Give the heuristic classifier a non-trivial active corpus so
            # ``compute_centroids`` returns something. Without active inbox
            # entries the centroid table is empty and classify_batch will
            # return ``pending_review`` for every entry with confidence 0.0.
            active_seed = make_entry(
                content="active inbox baseline note about logging",
                tags=["operations"],
                entry_type=EntryType.INBOX,
                source=EntrySource.MANUAL,
                status=EntryStatus.ACTIVE,
            )
            await store.store(active_seed)
            for i in range(count):
                pending = make_entry(
                    content=f"obscure unrelated topic alpha {i}",
                    entry_type=EntryType.INBOX,
                    source=EntrySource.MANUAL,
                    status=EntryStatus.PENDING_REVIEW,
                )
                pid = await store.store(pending)
                ids.append(pid)
            await store.close()

        asyncio.run(_seed())
        return ids

    def test_maintenance_classify_no_entries_text(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L3.7: classify against an empty DB exits 0 with 0 processed."""
        db_path = str(tmp_path / "empty.db")
        cfg_path = _write_mock_config(tmp_path, db_path)
        _seed_entries(db_path, [])  # initialise tables

        rc = _cmd_maintenance_classify(
            str(cfg_path),
            "text",
            entry_type="inbox",
            mode="heuristic",
        )
        assert rc == 0
        out = capsys.readouterr().out
        # All three counters should be zero.
        assert "classified:" in out
        assert "pending_review:" in out
        assert "errors:" in out

    def test_maintenance_classify_processes_pending_entries(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L3.8: ``maintenance classify`` visits all seeded ``pending_review`` entries.

        Seeds 3 ``PENDING_REVIEW`` inbox entries and asserts the
        per-disposition counts sum to 3 (``classified`` + still
        ``pending_review`` + ``errors``). Uses ``--mode heuristic`` so
        the test does not require an LLM client. Heuristic outcomes are
        centroid-similarity dependent, so the test deliberately does
        NOT pin any specific entry to ``classified`` vs left in review
        — only that all 3 were visited (the behavioural invariant from
        the issue #369 row).
        """
        db_path = str(tmp_path / "with_pending.db")
        cfg_path = _write_mock_config(tmp_path, db_path)
        self._seed_pending_inbox(db_path, count=3)

        rc = _cmd_maintenance_classify(
            str(cfg_path),
            "json",
            entry_type="inbox",
            mode="heuristic",
        )
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        # Each seeded pending entry must end up in exactly one of the
        # three buckets (classified / pending_review / errors).
        total = data["classified"] + data["pending_review"] + data["errors"]
        assert total == 3, (
            f"Expected 3 entries processed (3 seeded pending_review); got total={total}, "
            f"data={data!r}"
        )
        assert data["errors"] == 0

    def test_maintenance_classify_json_shape(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L3.9: JSON shape includes the four documented top-level keys.

        Per the webhook contract: ``{"classified", "pending_review",
        "errors", "by_type"}``. Confirms the per-disposition counts are
        always present (even when zero).
        """
        cfg_path = write_config(tmp_path, ":memory:")
        with pytest.raises(SystemExit) as exc:
            main(["maintenance", "classify", "--config", str(cfg_path), "--format", "json"])
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out)
        assert set(data.keys()) >= {"classified", "pending_review", "errors", "by_type"}
        assert isinstance(data["by_type"], dict)


# ---------------------------------------------------------------------------
# Group L4 — export / import lifecycle (L4.1–L4.7)
# ---------------------------------------------------------------------------


class TestIssue369ExportImportLifecycle:
    """End-to-end export/import lifecycle tests for rows L4.1 through L4.7."""

    def _seed_entries_and_sources(
        self,
        db_path: str,
        n_entries: int = 5,
        n_sources: int = 2,
    ) -> None:
        """Seed *n_entries* entries plus *n_sources* feed sources."""
        from distillery.mcp._stub_embedding import HashEmbeddingProvider
        from distillery.store.duckdb import DuckDBStore

        entries = [
            {
                "id": f"01abcdef-0000-0000-0000-0000000000{i:02d}",
                "content": f"Entry number {i} body content",
                "entry_type": "inbox",
                "source": "manual",
                "author": "tester",
                "project": None,
                "tags": ["sample"],
                "status": "active",
                "metadata": {},
                "version": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "created_by": "tester",
                "last_modified_by": "tester",
            }
            for i in range(n_entries)
        ]
        _seed_entries(db_path, entries)

        async def _add_sources() -> None:
            provider = HashEmbeddingProvider(dimensions=_ISSUE369_EMBED_DIMS)
            store = DuckDBStore(db_path=db_path, embedding_provider=provider)
            await store.initialize()
            try:
                for i in range(n_sources):
                    await store.add_feed_source(
                        url=f"https://example.com/feed-{i}.rss",
                        source_type="rss",
                        label=f"Example {i}",
                        poll_interval_minutes=60 + i,
                        trust_weight=1.0 - 0.1 * i,
                    )
            finally:
                await store.close()

        asyncio.run(_add_sources())

    def test_export_no_embedding_vectors(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L4.1: export schema must omit embedding vectors as a regression guard.

        The current export schema strips the ``embedding`` column at the
        SQL level (``SELECT id, content, ...`` does not include it).
        This test pins that invariant — if a future refactor adds the
        column back into the SELECT, this test fails.
        """
        db_path = str(tmp_path / "src.db")
        cfg_path = _write_mock_config(tmp_path, db_path)
        self._seed_entries_and_sources(db_path, n_entries=5, n_sources=2)

        out_path = tmp_path / "dump.json"
        rc = _cmd_export(str(cfg_path), "text", str(out_path))
        assert rc == 0
        capsys.readouterr()

        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert "entries" in data and isinstance(data["entries"], list)
        assert "feed_sources" in data and isinstance(data["feed_sources"], list)
        assert len(data["entries"]) == 5
        assert len(data["feed_sources"]) == 2

        for entry in data["entries"]:
            assert "embedding" not in entry, (
                f"Export leaked embedding vector for entry {entry.get('id')!r} — "
                f"keys: {sorted(entry.keys())}"
            )

    def test_export_overwrite_is_clean(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L4.2: re-running export to the same path overwrites cleanly, not appends.

        Asserts the file parses as a single JSON object on both runs and that
        the second parse has the same entry count as the first. A byte-length
        equality check would be brittle to additive payload schema changes
        (e.g., a new variable-length field) and would not detect a truncated
        but identically-sized regression — the structural check catches both
        truncation and append regressions without that fragility.
        """
        db_path = str(tmp_path / "src.db")
        cfg_path = _write_mock_config(tmp_path, db_path)
        self._seed_entries_and_sources(db_path, n_entries=2, n_sources=0)

        out_path = tmp_path / "dump.json"
        rc1 = _cmd_export(str(cfg_path), "text", str(out_path))
        assert rc1 == 0
        payload_first = json.loads(out_path.read_text(encoding="utf-8"))
        capsys.readouterr()

        rc2 = _cmd_export(str(cfg_path), "text", str(out_path))
        assert rc2 == 0
        payload_second = json.loads(out_path.read_text(encoding="utf-8"))
        capsys.readouterr()

        # Structural: file is still a single object (not concatenated runs)
        # and entry count matches the seed count on both runs.
        assert isinstance(payload_second, dict)
        assert len(payload_second["entries"]) == len(payload_first["entries"])
        assert len(payload_second["entries"]) == 2

    def test_import_merge_to_fresh_db_matches_entry_count(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L4.3: merge import into a fresh DB produces a count matching the dump."""
        src_db = str(tmp_path / "src.db")
        cfg_src = _write_mock_config(tmp_path, src_db, name="src.yaml")
        self._seed_entries_and_sources(src_db, n_entries=4, n_sources=0)

        dump = tmp_path / "dump.json"
        rc_export = _cmd_export(str(cfg_src), "text", str(dump))
        assert rc_export == 0
        capsys.readouterr()
        n_entries_in_dump = len(json.loads(dump.read_text(encoding="utf-8"))["entries"])
        assert n_entries_in_dump == 4

        dst_db = str(tmp_path / "dst.db")
        cfg_dst = _write_mock_config(tmp_path, dst_db, name="dst.yaml")
        rc_import = _cmd_import(str(cfg_dst), "text", str(dump), "merge", True)
        assert rc_import == 0
        out = capsys.readouterr().out
        assert f"Imported {n_entries_in_dump} entries" in out

    def test_import_merge_skips_existing(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L4.4: re-importing the same payload in merge mode reports N skipped."""
        src_db = str(tmp_path / "src.db")
        cfg_src = _write_mock_config(tmp_path, src_db, name="src.yaml")
        self._seed_entries_and_sources(src_db, n_entries=3, n_sources=0)

        dump = tmp_path / "dump.json"
        rc_export = _cmd_export(str(cfg_src), "text", str(dump))
        assert rc_export == 0
        capsys.readouterr()

        dst_db = str(tmp_path / "dst.db")
        cfg_dst = _write_mock_config(tmp_path, dst_db, name="dst.yaml")

        # First import: 3 in.
        rc1 = _cmd_import(str(cfg_dst), "text", str(dump), "merge", True)
        assert rc1 == 0
        out1 = capsys.readouterr().out
        assert "Imported 3 entries" in out1

        # Second import: all 3 skipped.
        rc2 = _cmd_import(str(cfg_dst), "text", str(dump), "merge", True)
        assert rc2 == 0
        out2 = capsys.readouterr().out
        assert "Imported 0 entries" in out2
        assert "3 skipped" in out2

    def test_import_replace_with_yes_succeeds(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """L4.5: ``--mode replace --yes`` performs the destructive import cleanly."""
        src_db = str(tmp_path / "src.db")
        cfg_src = _write_mock_config(tmp_path, src_db, name="src.yaml")
        self._seed_entries_and_sources(src_db, n_entries=2, n_sources=0)

        dump = tmp_path / "dump.json"
        rc_export = _cmd_export(str(cfg_src), "text", str(dump))
        assert rc_export == 0
        capsys.readouterr()

        # Pre-populate destination DB with one different entry so we can
        # verify replace truly clears it.
        dst_db = str(tmp_path / "dst.db")
        cfg_dst = _write_mock_config(tmp_path, dst_db, name="dst.yaml")
        _seed_entries(
            dst_db,
            [
                {
                    "id": "ffffffff-0000-0000-0000-000000000001",
                    "content": "pre-existing in dst",
                    "entry_type": "inbox",
                    "source": "manual",
                    "author": "x",
                    "project": None,
                    "tags": [],
                    "status": "active",
                    "metadata": {},
                    "version": 1,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                    "created_by": "x",
                    "last_modified_by": "x",
                }
            ],
        )

        rc = _cmd_import(str(cfg_dst), "text", str(dump), "replace", True)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Imported 2 entries" in out

        # The pre-existing entry must be gone.
        gone = asyncio.run(_async_get_entry(dst_db, "ffffffff-0000-0000-0000-000000000001"))
        assert gone is None, "Replace mode did not clear pre-existing entries"

    def test_import_replace_without_yes_in_non_interactive_cancels(
        self,
        tmp_path: Path,
    ) -> None:
        """L4.6: replace mode without ``--yes`` requires confirmation.

        The current behaviour (per ``_cmd_import``): in replace mode
        without ``--yes`` the CLI calls ``input(...)`` for a y/N prompt;
        on ``EOFError`` (e.g. piped/empty stdin) the import is cancelled
        with exit code 1. This test pins that behaviour. The issue #369
        plan text suggested either a prompt or a hard rejection — both
        are acceptable here as long as the import is *not* silently
        executed. We verify the non-interactive EOF path returns 1.
        """
        import unittest.mock as mock

        db_path = str(tmp_path / "dst.db")
        cfg_path = _write_mock_config(tmp_path, db_path)
        dump = tmp_path / "dump.json"
        dump.write_text(
            json.dumps(
                {
                    "version": 1,
                    "exported_at": "2026-01-01T00:00:00+00:00",
                    "meta": {},
                    "entries": [],
                    "feed_sources": [],
                }
            ),
            encoding="utf-8",
        )

        with mock.patch("builtins.input", side_effect=EOFError):
            rc = _cmd_import(str(cfg_path), "text", str(dump), "replace", False)
        # Non-interactive replace must NOT execute silently; it must
        # exit nonzero.
        assert rc == 1

    def test_import_malformed_json_subprocess_no_traceback(
        self,
        tmp_path: Path,
    ) -> None:
        """L4.7: malformed import JSON exits nonzero with a readable, traceback-free error.

        Invoked as a subprocess (mirrors the L1.11 / L2.5 pattern) so we
        observe the real stderr. Skips when the ``distillery`` console
        script is not installed on PATH.
        """
        import shutil
        import subprocess

        distillery_bin = shutil.which("distillery")
        if distillery_bin is None:
            pytest.skip("distillery console script not installed on PATH")

        bad = tmp_path / "bad.json"
        # Truncated JSON object.
        bad.write_text('{"version": 1, "entries":', encoding="utf-8")
        cfg_path = _write_mock_config(tmp_path, str(tmp_path / "dst.db"))

        result = subprocess.run(
            [
                distillery_bin,
                "--config",
                str(cfg_path),
                "import",
                "--input",
                str(bad),
                "--yes",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, (
            f"Expected nonzero exit for malformed JSON; got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        # Friendly error mentions the parse failure on stderr.
        assert (
            "invalid JSON" in result.stderr
            or "parse" in result.stderr.lower()
            or "JSON" in result.stderr
        ), f"Expected a JSON parse error on stderr; got: {result.stderr!r}"
        # No Python traceback leak.
        assert "Traceback" not in result.stderr, (
            f"Malformed JSON leaked a Python traceback: {result.stderr!r}"
        )
        assert "json.decoder.JSONDecodeError" not in result.stderr
