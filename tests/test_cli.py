"""Tests for distillery.cli: main(), status, health subcommands."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from distillery import __version__
from distillery.cli import _check_health, _cmd_health, _cmd_status, _query_status, main

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

    def test_version_matches_package(self) -> None:
        from distillery import __version__ as ver
        assert ver == "0.1.0"


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

    def test_bad_path_raises_runtime_error(self, tmp_path: Path) -> None:
        bad = str(tmp_path / "no_dir" / "x.db")
        with pytest.raises(RuntimeError):
            _query_status(bad)


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

    def test_cmd_status_returns_one_for_bad_config(
        self, tmp_path: Path
    ) -> None:
        missing = str(tmp_path / "missing.yaml")
        rc = _cmd_status(missing, "text")
        assert rc == 1


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
