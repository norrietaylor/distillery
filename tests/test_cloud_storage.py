"""Tests for S3 and MotherDuck cloud storage backend support.

Covers:
- Path detection helpers (_is_s3_path, _is_motherduck_path)
- _ensure_parent_dir skips directory creation for cloud paths
- _open_connection skips chmod for cloud paths
- _setup_httpfs loads extension and configures credentials/region/endpoint
- _sync_initialize calls httpfs setup for S3 paths only
- StorageConfig parses s3_region, s3_endpoint, motherduck_token_env
- Config validation accepts 'duckdb' and 'motherduck' backends; rejects others
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from distillery.config import load_config
from distillery.store.duckdb import DuckDBStore, _sql_escape

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "distillery.yaml"
    p.write_text(textwrap.dedent(content))
    return p


def make_store(db_path: str = ":memory:", **kwargs) -> DuckDBStore:
    provider = MagicMock()
    provider.dimensions = 4
    provider.model_name = "test-model"
    return DuckDBStore(db_path=db_path, embedding_provider=provider, **kwargs)


# ---------------------------------------------------------------------------
# _sql_escape
# ---------------------------------------------------------------------------


class TestSqlEscape:
    def test_plain_string_unchanged(self) -> None:
        assert _sql_escape("us-east-1") == "us-east-1"

    def test_single_quote_doubled(self) -> None:
        assert _sql_escape("it's") == "it''s"

    def test_multiple_quotes(self) -> None:
        assert _sql_escape("a'b'c") == "a''b''c"


# ---------------------------------------------------------------------------
# Path detection
# ---------------------------------------------------------------------------


class TestIsS3Path:
    def test_s3_prefix(self) -> None:
        assert DuckDBStore._is_s3_path("s3://my-bucket/db.duckdb") is True

    def test_local_path(self) -> None:
        assert DuckDBStore._is_s3_path("/home/user/db.duckdb") is False

    def test_memory(self) -> None:
        assert DuckDBStore._is_s3_path(":memory:") is False

    def test_motherduck_path(self) -> None:
        assert DuckDBStore._is_s3_path("md:distillery") is False


class TestIsMotherDuckPath:
    def test_md_prefix(self) -> None:
        assert DuckDBStore._is_motherduck_path("md:distillery") is True

    def test_md_empty_database(self) -> None:
        assert DuckDBStore._is_motherduck_path("md:") is True

    def test_local_path(self) -> None:
        assert DuckDBStore._is_motherduck_path("/home/user/db.duckdb") is False

    def test_s3_path(self) -> None:
        assert DuckDBStore._is_motherduck_path("s3://bucket/db.duckdb") is False

    def test_memory(self) -> None:
        assert DuckDBStore._is_motherduck_path(":memory:") is False


# ---------------------------------------------------------------------------
# _ensure_parent_dir
# ---------------------------------------------------------------------------


class TestEnsureParentDir:
    def test_skips_for_s3_path(self) -> None:
        store = make_store(db_path="s3://bucket/path/db.duckdb")
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            store._ensure_parent_dir()
            mock_mkdir.assert_not_called()

    def test_skips_for_motherduck_path(self) -> None:
        store = make_store(db_path="md:distillery")
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            store._ensure_parent_dir()
            mock_mkdir.assert_not_called()

    def test_skips_for_memory(self) -> None:
        store = make_store(db_path=":memory:")
        with patch("pathlib.Path.mkdir") as mock_mkdir:
            store._ensure_parent_dir()
            mock_mkdir.assert_not_called()

    def test_creates_dir_for_local_path(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "subdir" / "db.duckdb")
        store = make_store(db_path=db_path)
        store._ensure_parent_dir()
        assert (tmp_path / "subdir").is_dir()


# ---------------------------------------------------------------------------
# _setup_httpfs
# ---------------------------------------------------------------------------


class TestSetupHttpfs:
    def _make_conn(self) -> MagicMock:
        return MagicMock()

    def test_installs_and_loads_httpfs(self) -> None:
        store = make_store()
        conn = self._make_conn()
        with patch.dict("os.environ", {}, clear=True):
            store._setup_httpfs(conn)
        conn.execute.assert_any_call("INSTALL httpfs;")
        conn.execute.assert_any_call("LOAD httpfs;")

    def test_sets_region_from_config(self) -> None:
        store = make_store(s3_region="eu-west-1")
        conn = self._make_conn()
        with patch.dict("os.environ", {}, clear=True):
            store._setup_httpfs(conn)
        conn.execute.assert_any_call("SET s3_region = 'eu-west-1';")

    def test_sets_region_from_aws_default_region_env(self) -> None:
        store = make_store()
        conn = self._make_conn()
        with patch.dict("os.environ", {"AWS_DEFAULT_REGION": "ap-southeast-2"}, clear=True):
            store._setup_httpfs(conn)
        conn.execute.assert_any_call("SET s3_region = 'ap-southeast-2';")

    def test_sets_region_from_aws_region_env_fallback(self) -> None:
        store = make_store()
        conn = self._make_conn()
        with patch.dict("os.environ", {"AWS_REGION": "us-west-2"}, clear=True):
            store._setup_httpfs(conn)
        conn.execute.assert_any_call("SET s3_region = 'us-west-2';")

    def test_config_region_takes_precedence_over_env(self) -> None:
        store = make_store(s3_region="us-east-1")
        conn = self._make_conn()
        with patch.dict("os.environ", {"AWS_DEFAULT_REGION": "eu-west-1"}, clear=True):
            store._setup_httpfs(conn)
        conn.execute.assert_any_call("SET s3_region = 'us-east-1';")
        calls = [str(c) for c in conn.execute.call_args_list]
        # Should only set region once
        assert sum("s3_region" in c for c in calls) == 1

    def test_skips_region_when_none(self) -> None:
        store = make_store()
        conn = self._make_conn()
        with patch.dict("os.environ", {}, clear=True):
            store._setup_httpfs(conn)
        calls = [str(c) for c in conn.execute.call_args_list]
        assert not any("s3_region" in c for c in calls)

    def test_sets_custom_endpoint_and_path_style(self) -> None:
        store = make_store(s3_endpoint="https://minio.example.com")
        conn = self._make_conn()
        with patch.dict("os.environ", {}, clear=True):
            store._setup_httpfs(conn)
        conn.execute.assert_any_call("SET s3_endpoint = 'https://minio.example.com';")
        conn.execute.assert_any_call("SET s3_url_style = 'path';")

    def test_skips_endpoint_when_not_set(self) -> None:
        store = make_store()
        conn = self._make_conn()
        with patch.dict("os.environ", {}, clear=True):
            store._setup_httpfs(conn)
        calls = [str(c) for c in conn.execute.call_args_list]
        assert not any("s3_endpoint" in c for c in calls)
        assert not any("s3_url_style" in c for c in calls)

    def test_sets_credentials_from_env(self) -> None:
        store = make_store()
        conn = self._make_conn()
        env = {
            "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
            "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        }
        with patch.dict("os.environ", env, clear=True):
            store._setup_httpfs(conn)
        conn.execute.assert_any_call(
            "SET s3_access_key_id = 'AKIAIOSFODNN7EXAMPLE';"
        )
        conn.execute.assert_any_call(
            "SET s3_secret_access_key = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY';"
        )

    def test_sets_session_token_from_env(self) -> None:
        store = make_store()
        conn = self._make_conn()
        env = {
            "AWS_ACCESS_KEY_ID": "KEY",
            "AWS_SECRET_ACCESS_KEY": "SECRET",
            "AWS_SESSION_TOKEN": "TOKEN123",
        }
        with patch.dict("os.environ", env, clear=True):
            store._setup_httpfs(conn)
        conn.execute.assert_any_call("SET s3_session_token = 'TOKEN123';")

    def test_skips_credentials_when_env_absent(self) -> None:
        store = make_store()
        conn = self._make_conn()
        with patch.dict("os.environ", {}, clear=True):
            store._setup_httpfs(conn)
        calls = [str(c) for c in conn.execute.call_args_list]
        assert not any("s3_access_key_id" in c for c in calls)
        assert not any("s3_secret_access_key" in c for c in calls)
        assert not any("s3_session_token" in c for c in calls)

    def test_escapes_single_quotes_in_values(self) -> None:
        store = make_store(s3_region="test")
        conn = self._make_conn()
        env = {"AWS_ACCESS_KEY_ID": "key'with'quotes"}
        with patch.dict("os.environ", env, clear=True):
            store._setup_httpfs(conn)
        conn.execute.assert_any_call("SET s3_access_key_id = 'key''with''quotes';")


# ---------------------------------------------------------------------------
# _sync_initialize calls httpfs for S3 paths only
# ---------------------------------------------------------------------------


class TestSyncInitializeHttpfs:
    def test_httpfs_called_for_s3_path(self) -> None:
        store = make_store(db_path="s3://bucket/db.duckdb")
        mock_conn = MagicMock()
        with (
            patch.object(store, "_open_connection", return_value=mock_conn),
            patch.object(store, "_setup_httpfs") as mock_httpfs,
            patch.object(store, "_setup_vss"),
            patch("distillery.store.duckdb.run_pending_migrations", return_value=6),
            patch.object(store, "_validate_or_record_meta"),
            patch.object(store, "_track_version_info"),
        ):
            store._sync_initialize()
            mock_httpfs.assert_called_once_with(mock_conn)

    def test_httpfs_not_called_for_local_path(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "db.duckdb")
        store = make_store(db_path=db_path)
        mock_conn = MagicMock()
        with (
            patch.object(store, "_open_connection", return_value=mock_conn),
            patch.object(store, "_setup_httpfs") as mock_httpfs,
            patch.object(store, "_setup_vss"),
            patch("distillery.store.duckdb.run_pending_migrations", return_value=6),
            patch.object(store, "_validate_or_record_meta"),
            patch.object(store, "_track_version_info"),
        ):
            store._sync_initialize()
            mock_httpfs.assert_not_called()

    def test_httpfs_not_called_for_memory(self) -> None:
        store = make_store(db_path=":memory:")
        mock_conn = MagicMock()
        with (
            patch.object(store, "_open_connection", return_value=mock_conn),
            patch.object(store, "_setup_httpfs") as mock_httpfs,
            patch.object(store, "_setup_vss"),
            patch("distillery.store.duckdb.run_pending_migrations", return_value=6),
            patch.object(store, "_validate_or_record_meta"),
            patch.object(store, "_track_version_info"),
        ):
            store._sync_initialize()
            mock_httpfs.assert_not_called()

    def test_httpfs_not_called_for_motherduck(self) -> None:
        store = make_store(db_path="md:distillery")
        mock_conn = MagicMock()
        with (
            patch.object(store, "_open_connection", return_value=mock_conn),
            patch.object(store, "_setup_httpfs") as mock_httpfs,
            patch.object(store, "_setup_vss"),
            patch("distillery.store.duckdb.run_pending_migrations", return_value=6),
            patch.object(store, "_validate_or_record_meta"),
            patch.object(store, "_track_version_info"),
        ):
            store._sync_initialize()
            mock_httpfs.assert_not_called()

    def test_httpfs_called_before_vss_for_s3(self) -> None:
        """httpfs must be loaded before vss when using S3."""
        store = make_store(db_path="s3://bucket/db.duckdb")
        call_order: list[str] = []
        mock_conn = MagicMock()

        def fake_httpfs(_conn: object) -> None:
            call_order.append("httpfs")

        def fake_vss(_conn: object) -> None:
            call_order.append("vss")

        with (
            patch.object(store, "_open_connection", return_value=mock_conn),
            patch.object(store, "_setup_httpfs", side_effect=fake_httpfs),
            patch.object(store, "_setup_vss", side_effect=fake_vss),
            patch("distillery.store.duckdb.run_pending_migrations", return_value=6),
            patch.object(store, "_validate_or_record_meta"),
            patch.object(store, "_track_version_info"),
        ):
            store._sync_initialize()

        assert call_order == ["httpfs", "vss"]


# ---------------------------------------------------------------------------
# StorageConfig parsing
# ---------------------------------------------------------------------------


class TestStorageConfigParsing:
    def test_s3_region_parsed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        write_yaml(
            tmp_path,
            """
            storage:
              backend: duckdb
              database_path: s3://bucket/db.duckdb
              s3_region: us-east-1
            """,
        )
        cfg = load_config()
        assert cfg.storage.s3_region == "us-east-1"

    def test_s3_endpoint_parsed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        write_yaml(
            tmp_path,
            """
            storage:
              backend: duckdb
              database_path: s3://bucket/db.duckdb
              s3_endpoint: https://minio.example.com
            """,
        )
        cfg = load_config()
        assert cfg.storage.s3_endpoint == "https://minio.example.com"

    def test_motherduck_token_env_parsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MY_MD_TOKEN", "dummy-token")
        write_yaml(
            tmp_path,
            """
            storage:
              backend: motherduck
              database_path: md:distillery
              motherduck_token_env: MY_MD_TOKEN
            """,
        )
        cfg = load_config()
        assert cfg.storage.motherduck_token_env == "MY_MD_TOKEN"

    def test_motherduck_backend_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MOTHERDUCK_TOKEN", "dummy-token")
        write_yaml(
            tmp_path,
            """
            storage:
              backend: motherduck
              database_path: md:distillery
            """,
        )
        cfg = load_config()
        assert cfg.storage.backend == "motherduck"

    def test_s3_fields_default_to_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        write_yaml(tmp_path, "storage:\n  backend: duckdb\n")
        cfg = load_config()
        assert cfg.storage.s3_region is None
        assert cfg.storage.s3_endpoint is None

    def test_motherduck_token_env_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        write_yaml(tmp_path, "storage:\n  backend: duckdb\n")
        cfg = load_config()
        assert cfg.storage.motherduck_token_env == "MOTHERDUCK_TOKEN"


# ---------------------------------------------------------------------------
# Config validation: backend
# ---------------------------------------------------------------------------


class TestBackendValidation:
    def test_duckdb_backend_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        write_yaml(tmp_path, "storage:\n  backend: duckdb\n")
        cfg = load_config()
        assert cfg.storage.backend == "duckdb"

    def test_unknown_backend_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        write_yaml(tmp_path, "storage:\n  backend: postgres\n")
        with pytest.raises(ValueError, match="storage.backend"):
            load_config()

    def test_default_backend_when_no_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        from distillery.config import CONFIG_ENV_VAR

        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert cfg.storage.backend == "duckdb"
