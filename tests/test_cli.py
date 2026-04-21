"""Tests for distillery.cli: main(), status, health, export, import subcommands."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from distillery import __version__
from distillery.cli import (
    _check_health,
    _cmd_export,
    _cmd_health,
    _cmd_import,
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
        # Create an empty scenarios directory so the dir-exists check passes
        # but the skill filter produces zero matches.
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
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
