"""Tests for distillery.config: load_config and helper functions."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from distillery.config import (
    CONFIG_ENV_VAR,
    DistilleryConfig,
    ServerAuthConfig,
    ServerConfig,
    TagsConfig,
    load_config,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_yaml(tmp_path: Path, content: str, name: str = "distillery.yaml") -> Path:
    """Write *content* to *tmp_path/name* and return the Path."""
    p = tmp_path / name
    p.write_text(textwrap.dedent(content))
    return p


# ---------------------------------------------------------------------------
# Default values (no config file)
# ---------------------------------------------------------------------------


class TestDefaultConfig:
    def test_returns_distillery_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)  # No yaml present in tmp_path
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert isinstance(cfg, DistilleryConfig)

    def test_storage_defaults(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert cfg.storage.backend == "duckdb"
        assert cfg.storage.database_path == "~/.distillery/distillery.db"

    def test_embedding_defaults(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert cfg.embedding.model == "jina-embeddings-v3"
        assert cfg.embedding.dimensions == 1024
        assert cfg.embedding.provider == ""
        assert cfg.embedding.api_key_env == ""

    def test_team_defaults(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert cfg.team.name == ""

    def test_classification_defaults(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert cfg.classification.confidence_threshold == pytest.approx(0.6)

    def test_dedup_threshold_defaults(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert cfg.classification.dedup_skip_threshold == pytest.approx(0.95)
        assert cfg.classification.dedup_merge_threshold == pytest.approx(0.80)
        assert cfg.classification.dedup_link_threshold == pytest.approx(0.60)
        assert cfg.classification.dedup_limit == 5


# ---------------------------------------------------------------------------
# YAML loading: all fields
# ---------------------------------------------------------------------------


class TestYAMLLoading:
    FULL_YAML = """\
        storage:
          backend: duckdb
          database_path: /tmp/test.db

        embedding:
          provider: jina
          model: jina-embeddings-v3
          dimensions: 512
          api_key_env: MY_JINA_KEY

        team:
          name: Engineering

        classification:
          confidence_threshold: 0.75
          dedup_skip_threshold: 0.92
          dedup_merge_threshold: 0.78
          dedup_link_threshold: 0.55
          dedup_limit: 10
    """

    def test_loads_storage(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        p = write_yaml(tmp_path, self.FULL_YAML)
        cfg = load_config(str(p))
        assert cfg.storage.backend == "duckdb"
        assert cfg.storage.database_path == "/tmp/test.db"

    def test_loads_embedding(self, tmp_path: Path) -> None:
        p = write_yaml(tmp_path, self.FULL_YAML)
        cfg = load_config(str(p))
        assert cfg.embedding.provider == "jina"
        assert cfg.embedding.model == "jina-embeddings-v3"
        assert cfg.embedding.dimensions == 512
        assert cfg.embedding.api_key_env == "MY_JINA_KEY"

    def test_loads_team(self, tmp_path: Path) -> None:
        p = write_yaml(tmp_path, self.FULL_YAML)
        cfg = load_config(str(p))
        assert cfg.team.name == "Engineering"

    def test_loads_classification(self, tmp_path: Path) -> None:
        p = write_yaml(tmp_path, self.FULL_YAML)
        cfg = load_config(str(p))
        assert cfg.classification.confidence_threshold == pytest.approx(0.75)

    def test_loads_dedup_thresholds(self, tmp_path: Path) -> None:
        p = write_yaml(tmp_path, self.FULL_YAML)
        cfg = load_config(str(p))
        assert cfg.classification.dedup_skip_threshold == pytest.approx(0.92)
        assert cfg.classification.dedup_merge_threshold == pytest.approx(0.78)
        assert cfg.classification.dedup_link_threshold == pytest.approx(0.55)
        assert cfg.classification.dedup_limit == 10

    def test_openai_provider(self, tmp_path: Path) -> None:
        yaml_content = """\
            embedding:
              provider: openai
              model: text-embedding-3-small
              dimensions: 1536
              api_key_env: OPENAI_API_KEY
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.embedding.provider == "openai"
        assert cfg.embedding.model == "text-embedding-3-small"
        assert cfg.embedding.dimensions == 1536

    def test_partial_yaml_uses_defaults(self, tmp_path: Path) -> None:
        """A config with only storage section should fill rest with defaults."""
        yaml_content = """\
            storage:
              backend: duckdb
              database_path: /var/db.db
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.storage.database_path == "/var/db.db"
        assert cfg.embedding.model == "jina-embeddings-v3"
        assert cfg.team.name == ""
        assert cfg.classification.confidence_threshold == pytest.approx(0.6)

    def test_empty_yaml_file_uses_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "distillery.yaml"
        p.write_text("")
        cfg = load_config(str(p))
        assert isinstance(cfg, DistilleryConfig)
        assert cfg.storage.backend == "duckdb"


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


class TestValidationErrors:
    def test_invalid_provider_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            embedding:
              provider: unknown_provider
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="embedding.provider"):
            load_config(str(p))

    def test_negative_dimensions_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            embedding:
              provider: jina
              dimensions: -1
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="dimensions"):
            load_config(str(p))

    def test_zero_dimensions_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            embedding:
              provider: jina
              dimensions: 0
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="dimensions"):
            load_config(str(p))

    def test_non_integer_dimensions_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            embedding:
              dimensions: not_a_number
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError):
            load_config(str(p))

    def test_threshold_above_one_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            classification:
              confidence_threshold: 1.5
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="confidence_threshold"):
            load_config(str(p))

    def test_threshold_below_zero_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            classification:
              confidence_threshold: -0.1
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="confidence_threshold"):
            load_config(str(p))

    def test_non_numeric_threshold_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            classification:
              confidence_threshold: bad
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError):
            load_config(str(p))

    def test_dedup_skip_threshold_above_one_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            classification:
              dedup_skip_threshold: 1.5
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="dedup_skip_threshold"):
            load_config(str(p))

    def test_dedup_link_threshold_below_zero_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            classification:
              dedup_link_threshold: -0.1
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="dedup_link_threshold"):
            load_config(str(p))

    def test_dedup_threshold_ordering_violated_raises_value_error(self, tmp_path: Path) -> None:
        """link > merge violates the ordering constraint."""
        yaml_content = """\
            classification:
              dedup_link_threshold: 0.90
              dedup_merge_threshold: 0.80
              dedup_skip_threshold: 0.95
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="dedup_link_threshold"):
            load_config(str(p))

    def test_dedup_merge_above_skip_raises_value_error(self, tmp_path: Path) -> None:
        """merge > skip violates the ordering constraint."""
        yaml_content = """\
            classification:
              dedup_link_threshold: 0.50
              dedup_merge_threshold: 0.98
              dedup_skip_threshold: 0.90
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="dedup_merge_threshold"):
            load_config(str(p))

    def test_dedup_limit_zero_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            classification:
              dedup_limit: 0
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="dedup_limit"):
            load_config(str(p))

    def test_dedup_limit_non_integer_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            classification:
              dedup_limit: not_a_number
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError):
            load_config(str(p))

    def test_explicit_missing_path_raises_file_not_found(self, tmp_path: Path) -> None:
        missing = str(tmp_path / "no_such_file.yaml")
        with pytest.raises(FileNotFoundError):
            load_config(missing)

    def test_non_mapping_yaml_raises_value_error(self, tmp_path: Path) -> None:
        p = tmp_path / "distillery.yaml"
        p.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="mapping"):
            load_config(str(p))


# ---------------------------------------------------------------------------
# Config path override via environment variable
# ---------------------------------------------------------------------------


class TestEnvVarOverride:
    def test_env_var_points_to_custom_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        yaml_content = """\
            team:
              name: EnvVarTeam
        """
        p = write_yaml(tmp_path, yaml_content, name="custom.yaml")
        monkeypatch.setenv(CONFIG_ENV_VAR, str(p))
        # Change cwd so there's no default distillery.yaml
        monkeypatch.chdir(tmp_path)
        cfg = load_config()
        assert cfg.team.name == "EnvVarTeam"

    def test_explicit_path_takes_priority_over_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_yaml = write_yaml(tmp_path, "team:\n  name: FromEnv\n", name="env.yaml")
        explicit_yaml = write_yaml(tmp_path, "team:\n  name: FromExplicit\n", name="explicit.yaml")
        monkeypatch.setenv(CONFIG_ENV_VAR, str(env_yaml))
        cfg = load_config(str(explicit_yaml))
        assert cfg.team.name == "FromExplicit"

    def test_env_var_missing_file_falls_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If env var points to a non-existent file, fall through to default."""
        monkeypatch.setenv(CONFIG_ENV_VAR, str(tmp_path / "nonexistent.yaml"))
        monkeypatch.chdir(tmp_path)
        # Should return defaults (no yaml present in tmp_path either)
        cfg = load_config()
        assert isinstance(cfg, DistilleryConfig)


# ---------------------------------------------------------------------------
# Example config file validity
# ---------------------------------------------------------------------------


class TestExampleConfigFile:
    def test_example_config_is_valid(self) -> None:
        """The committed example config file must load without errors."""
        repo_root = Path(__file__).parent.parent
        example_path = repo_root / "distillery.yaml.example"
        assert example_path.exists(), f"Example config not found: {example_path}"
        cfg = load_config(str(example_path))
        assert isinstance(cfg, DistilleryConfig)

    def test_example_config_storage_backend(self) -> None:
        repo_root = Path(__file__).parent.parent
        example_path = repo_root / "distillery.yaml.example"
        cfg = load_config(str(example_path))
        assert cfg.storage.backend == "duckdb"

    def test_example_config_embedding_provider(self) -> None:
        repo_root = Path(__file__).parent.parent
        example_path = repo_root / "distillery.yaml.example"
        cfg = load_config(str(example_path))
        assert cfg.embedding.provider == "jina"

    def test_example_config_team_name(self) -> None:
        repo_root = Path(__file__).parent.parent
        example_path = repo_root / "distillery.yaml.example"
        cfg = load_config(str(example_path))
        assert cfg.team.name == "My Team"

    def test_example_config_classification_threshold(self) -> None:
        repo_root = Path(__file__).parent.parent
        example_path = repo_root / "distillery.yaml.example"
        cfg = load_config(str(example_path))
        assert cfg.classification.confidence_threshold == pytest.approx(0.6)

    def test_example_config_dedup_thresholds(self) -> None:
        repo_root = Path(__file__).parent.parent
        example_path = repo_root / "distillery.yaml.example"
        cfg = load_config(str(example_path))
        assert cfg.classification.dedup_skip_threshold == pytest.approx(0.95)
        assert cfg.classification.dedup_merge_threshold == pytest.approx(0.80)
        assert cfg.classification.dedup_link_threshold == pytest.approx(0.60)
        assert cfg.classification.dedup_limit == 5

    def test_example_config_tags_section(self) -> None:
        repo_root = Path(__file__).parent.parent
        example_path = repo_root / "distillery.yaml.example"
        cfg = load_config(str(example_path))
        assert isinstance(cfg.tags, TagsConfig)
        assert cfg.tags.enforce_namespaces is False
        assert cfg.tags.reserved_prefixes == []


# ---------------------------------------------------------------------------
# Tags config parsing and validation
# ---------------------------------------------------------------------------


class TestTagsConfig:
    def test_default_tags_config_when_section_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert isinstance(cfg.tags, TagsConfig)
        assert cfg.tags.enforce_namespaces is False
        assert cfg.tags.reserved_prefixes == []

    def test_tags_section_parsed_enforce_namespaces_true(self, tmp_path: Path) -> None:
        yaml_content = """\
            tags:
              enforce_namespaces: true
              reserved_prefixes: ["system"]
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.tags.enforce_namespaces is True
        assert "system" in cfg.tags.reserved_prefixes

    def test_tags_enforce_namespaces_false_is_default(self, tmp_path: Path) -> None:
        yaml_content = """\
            tags:
              enforce_namespaces: false
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.tags.enforce_namespaces is False

    def test_tags_reserved_prefixes_empty_list(self, tmp_path: Path) -> None:
        yaml_content = """\
            tags:
              reserved_prefixes: []
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.tags.reserved_prefixes == []

    def test_tags_multiple_reserved_prefixes(self, tmp_path: Path) -> None:
        yaml_content = """\
            tags:
              reserved_prefixes: ["system", "internal"]
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert set(cfg.tags.reserved_prefixes) == {"system", "internal"}

    def test_invalid_reserved_prefix_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            tags:
              reserved_prefixes: ["INVALID-PREFIX!"]
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="reserved_prefix"):
            load_config(str(p))

    def test_reserved_prefix_with_slash_raises_value_error(self, tmp_path: Path) -> None:
        """A prefix with a slash is not a valid single segment."""
        yaml_content = """\
            tags:
              reserved_prefixes: ["system/internal"]
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="reserved_prefix"):
            load_config(str(p))

    def test_reserved_prefix_uppercase_raises_value_error(self, tmp_path: Path) -> None:
        yaml_content = """\
            tags:
              reserved_prefixes: ["System"]
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="reserved_prefix"):
            load_config(str(p))

    def test_tags_section_without_enforce_namespaces_defaults_false(self, tmp_path: Path) -> None:
        yaml_content = """\
            tags:
              reserved_prefixes: ["system"]
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.tags.enforce_namespaces is False


# ---------------------------------------------------------------------------
# MotherDuck backend validation
# ---------------------------------------------------------------------------


class TestMotherDuckValidation:
    def test_motherduck_backend_requires_md_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Validation rejects non-md: path with motherduck backend."""
        monkeypatch.setenv("MOTHERDUCK_TOKEN", "dummy-token")
        yaml_content = """\
            storage:
              backend: motherduck
              database_path: my_database
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="md:"):
            load_config(str(p))

    def test_motherduck_backend_accepts_md_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Valid md: path with token passes validation."""
        monkeypatch.setenv("MOTHERDUCK_TOKEN", "dummy-token")
        yaml_content = """\
            storage:
              backend: motherduck
              database_path: md:my_database
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.storage.backend == "motherduck"
        assert cfg.storage.database_path == "md:my_database"

    def test_motherduck_missing_token_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing token env var raises ValueError at config validation time."""
        monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
        yaml_content = """\
            storage:
              backend: motherduck
              database_path: md:my_database
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="MOTHERDUCK_TOKEN"):
            load_config(str(p))

    def test_motherduck_custom_token_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Custom motherduck_token_env name is validated correctly."""
        monkeypatch.setenv("MY_MD_TOKEN", "custom-token")
        monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
        yaml_content = """\
            storage:
              backend: motherduck
              database_path: md:my_database
              motherduck_token_env: MY_MD_TOKEN
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.storage.motherduck_token_env == "MY_MD_TOKEN"

    def test_motherduck_missing_custom_token_env_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing custom token env var uses correct name in error message."""
        monkeypatch.delenv("MY_MD_TOKEN", raising=False)
        yaml_content = """\
            storage:
              backend: motherduck
              database_path: md:my_database
              motherduck_token_env: MY_MD_TOKEN
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="MY_MD_TOKEN"):
            load_config(str(p))

    def test_duckdb_backend_no_md_prefix_required(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-motherduck backends do not require md: prefix or token."""
        monkeypatch.delenv("MOTHERDUCK_TOKEN", raising=False)
        yaml_content = """\
            storage:
              backend: duckdb
              database_path: /tmp/test.db
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.storage.backend == "duckdb"


# ---------------------------------------------------------------------------
# Server auth configuration
# ---------------------------------------------------------------------------


class TestServerAuthConfigParsing:
    def test_server_auth_config_parsing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """YAML server.auth section parses correctly."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        yaml_content = """\
            server:
              auth:
                provider: github
                client_id_env: MY_GH_CLIENT_ID
                client_secret_env: MY_GH_CLIENT_SECRET
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.server.auth.provider == "github"
        assert cfg.server.auth.client_id_env == "MY_GH_CLIENT_ID"
        assert cfg.server.auth.client_secret_env == "MY_GH_CLIENT_SECRET"

    def test_server_auth_defaults(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When no server section is present, defaults are applied."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert cfg.server.auth.provider == "none"
        assert cfg.server.auth.client_id_env == "GITHUB_CLIENT_ID"
        assert cfg.server.auth.client_secret_env == "GITHUB_CLIENT_SECRET"

    def test_server_auth_provider_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """provider: none is valid."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        yaml_content = """\
            server:
              auth:
                provider: none
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.server.auth.provider == "none"

    def test_server_config_dataclass_defaults(self) -> None:
        """ServerConfig and ServerAuthConfig have correct defaults."""
        sc = ServerConfig()
        assert isinstance(sc.auth, ServerAuthConfig)
        assert sc.auth.provider == "none"
        assert sc.auth.client_id_env == "GITHUB_CLIENT_ID"
        assert sc.auth.client_secret_env == "GITHUB_CLIENT_SECRET"


class TestServerAuthInvalidProvider:
    def test_server_auth_invalid_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Invalid provider raises ValueError."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        yaml_content = """\
            server:
              auth:
                provider: google
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="server.auth.provider"):
            load_config(str(p))


class TestServerMalformedValues:
    """Malformed server/auth values must raise, not silently coerce to defaults."""

    def test_server_as_list_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        yaml_content = """\
            server: []
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="server must be a YAML mapping"):
            load_config(str(p))

    def test_server_auth_as_list_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        yaml_content = """\
            server:
              auth: []
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="server.auth must be a YAML mapping"):
            load_config(str(p))

    def test_server_auth_as_string_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        yaml_content = """\
            server:
              auth: "github"
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="server.auth must be a YAML mapping"):
            load_config(str(p))
