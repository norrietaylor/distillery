"""Tests for distillery.config: load_config and helper functions."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from distillery.config import (
    CONFIG_ENV_VAR,
    DistilleryConfig,
    FeedsConfig,
    FeedSourceConfig,
    FeedsThresholdsConfig,
    ServerAuthConfig,
    ServerConfig,
    TagsConfig,
    WebhookConfig,
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

    def test_defaults_defaults(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert cfg.defaults.dedup_threshold == pytest.approx(0.92)
        assert cfg.defaults.dedup_limit == 3
        assert cfg.defaults.stale_days == 30
        assert cfg.defaults.hybrid_search is True
        assert cfg.defaults.rrf_k == 60
        assert cfg.defaults.recency_window_days == 90
        assert cfg.defaults.recency_min_weight == pytest.approx(0.5)


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

        defaults:
          dedup_threshold: 0.85
          dedup_limit: 5
          stale_days: 45

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

    def test_loads_defaults(self, tmp_path: Path) -> None:
        p = write_yaml(tmp_path, self.FULL_YAML)
        cfg = load_config(str(p))
        assert cfg.defaults.dedup_threshold == pytest.approx(0.85)
        assert cfg.defaults.dedup_limit == 5
        assert cfg.defaults.stale_days == 45

    def test_hybrid_search_defaults(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Hybrid search fields use sensible defaults when absent from config."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert cfg.defaults.hybrid_search is True
        assert cfg.defaults.rrf_k == 60
        assert cfg.defaults.recency_window_days == 90
        assert cfg.defaults.recency_min_weight == pytest.approx(0.5)

    def test_hybrid_search_overrides(self, tmp_path: Path) -> None:
        """Hybrid search fields can be overridden via YAML config."""
        yaml_content = """\
            defaults:
              hybrid_search: false
              rrf_k: 100
              recency_window_days: 30
              recency_min_weight: 0.3
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.defaults.hybrid_search is False
        assert cfg.defaults.rrf_k == 100
        assert cfg.defaults.recency_window_days == 30
        assert cfg.defaults.recency_min_weight == pytest.approx(0.3)

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
        assert cfg.defaults.dedup_threshold == pytest.approx(0.92)
        assert cfg.defaults.dedup_limit == 3
        assert cfg.defaults.stale_days == 30


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

    def test_malformed_yaml_raises_value_error(self, tmp_path: Path) -> None:
        """Malformed YAML surfaces as ValueError (not a raw yaml.YAMLError)."""
        p = tmp_path / "distillery.yaml"
        p.write_text("storage:\n  database_path: [unterminated\n")
        with pytest.raises(ValueError, match="Invalid YAML syntax"):
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
        assert "system" in cfg.tags.reserved_prefixes


# ---------------------------------------------------------------------------
# FeedsConfig: dataclass defaults and loading
# ---------------------------------------------------------------------------


class TestFeedsConfigDefaults:
    def test_feeds_defaults_no_sources(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert isinstance(cfg.feeds, FeedsConfig)
        assert cfg.feeds.sources == []

    def test_feeds_thresholds_defaults(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert cfg.feeds.thresholds.alert == pytest.approx(0.85)
        assert cfg.feeds.thresholds.digest == pytest.approx(0.60)

    def test_feeds_source_config_defaults(self) -> None:
        src = FeedSourceConfig(url="https://example.com/rss", source_type="rss")
        assert src.label == ""
        assert src.poll_interval_minutes == 60
        assert src.trust_weight == pytest.approx(1.0)


class TestFeedsConfigYAML:
    def test_loads_feeds_section_with_sources(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              thresholds:
                alert: 0.90
                digest: 0.65
              sources:
                - url: https://news.ycombinator.com/rss
                  source_type: rss
                  label: Hacker News
                  poll_interval_minutes: 30
                  trust_weight: 0.8
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert len(cfg.feeds.sources) == 1
        src = cfg.feeds.sources[0]
        assert src.url == "https://news.ycombinator.com/rss"
        assert src.source_type == "rss"
        assert src.label == "Hacker News"
        assert src.poll_interval_minutes == 30
        assert src.trust_weight == pytest.approx(0.8)

    def test_loads_feeds_thresholds(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              thresholds:
                alert: 0.90
                digest: 0.70
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.feeds.thresholds.alert == pytest.approx(0.90)
        assert cfg.feeds.thresholds.digest == pytest.approx(0.70)

    def test_empty_feeds_section_uses_defaults(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds: {}
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.feeds.sources == []
        assert cfg.feeds.thresholds.alert == pytest.approx(0.85)

    def test_multiple_sources_loaded(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              sources:
                - url: https://example.com/rss
                  source_type: rss
                - url: org/repo
                  source_type: github
                  label: Example Repo
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert len(cfg.feeds.sources) == 2
        assert cfg.feeds.sources[0].source_type == "rss"
        assert cfg.feeds.sources[1].source_type == "github"

    def test_github_source_type_accepted(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              sources:
                - url: org/repo
                  source_type: github
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.feeds.sources[0].source_type == "github"

    def test_invalid_source_type_raises(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              sources:
                - url: https://example.com
                  source_type: invalid-type
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="source_type"):
            load_config(str(p))

    def test_reader_config_defaults(self, tmp_path: Path) -> None:
        """ReaderConfig defaults are applied when no feeds.reader block exists."""
        yaml_content = """\
            feeds: {}
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.feeds.reader.enabled is False
        assert cfg.feeds.reader.api_key_env == "JINA_API_KEY"
        assert cfg.feeds.reader.min_content_chars == 500
        assert cfg.feeds.reader.timeout_seconds == pytest.approx(30.0)
        assert cfg.feeds.reader.max_retries == 2
        assert cfg.feeds.reader.concurrency == 5

    def test_reader_config_loaded(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              reader:
                enabled: true
                api_key_env: MY_JINA_KEY
                min_content_chars: 200
                timeout_seconds: 10
                max_retries: 3
                concurrency: 8
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.feeds.reader.enabled is True
        assert cfg.feeds.reader.api_key_env == "MY_JINA_KEY"
        assert cfg.feeds.reader.min_content_chars == 200
        assert cfg.feeds.reader.timeout_seconds == pytest.approx(10.0)
        assert cfg.feeds.reader.max_retries == 3
        assert cfg.feeds.reader.concurrency == 8

    def test_reader_config_negative_min_chars_raises(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              reader:
                enabled: true
                min_content_chars: -1
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="min_content_chars"):
            load_config(str(p))

    def test_reader_config_zero_concurrency_raises(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              reader:
                enabled: true
                concurrency: 0
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="concurrency"):
            load_config(str(p))

    def test_reader_config_zero_timeout_raises(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              reader:
                enabled: true
                timeout_seconds: 0
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="timeout_seconds"):
            load_config(str(p))

    def test_reader_config_negative_max_retries_raises(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              reader:
                enabled: true
                max_retries: -1
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="max_retries"):
            load_config(str(p))

    def test_reader_config_non_bool_enabled_raises(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              reader:
                enabled: "yes"
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="enabled"):
            load_config(str(p))

    def test_missing_url_raises(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              sources:
                - source_type: rss
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="url"):
            load_config(str(p))

    def test_negative_poll_interval_raises(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              sources:
                - url: https://example.com/rss
                  source_type: rss
                  poll_interval_minutes: -1
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="poll_interval_minutes"):
            load_config(str(p))

    def test_trust_weight_out_of_range_raises(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              sources:
                - url: https://example.com/rss
                  source_type: rss
                  trust_weight: 1.5
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="trust_weight"):
            load_config(str(p))

    def test_feeds_alert_below_digest_raises(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              thresholds:
                alert: 0.50
                digest: 0.80
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="digest.*alert|alert.*digest"):
            load_config(str(p))

    def test_feeds_alert_out_of_range_raises(self, tmp_path: Path) -> None:
        yaml_content = """\
            feeds:
              thresholds:
                alert: 1.5
                digest: 0.60
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="feeds.thresholds.alert"):
            load_config(str(p))


# ---------------------------------------------------------------------------
# FeedsThresholdsConfig dataclass
# ---------------------------------------------------------------------------


class TestFeedsThresholdsConfig:
    def test_dataclass_defaults(self) -> None:
        t = FeedsThresholdsConfig()
        assert t.alert == pytest.approx(0.85)
        assert t.digest == pytest.approx(0.60)


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

    def test_server_auth_defaults(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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

    def test_server_as_list_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


class TestWebhookConfigDefaults:
    """Tests for WebhookConfig dataclass defaults."""

    def test_webhook_config_dataclass_defaults(self) -> None:
        """WebhookConfig has correct defaults."""
        wc = WebhookConfig()
        assert wc.enabled is True
        assert wc.secret_env == "DISTILLERY_WEBHOOK_SECRET"

    def test_webhook_config_enabled_true(self) -> None:
        """WebhookConfig can be created with enabled=True."""
        wc = WebhookConfig(enabled=True)
        assert wc.enabled is True

    def test_webhook_config_enabled_false(self) -> None:
        """WebhookConfig can be created with enabled=False."""
        wc = WebhookConfig(enabled=False)
        assert wc.enabled is False

    def test_webhook_config_custom_secret_env(self) -> None:
        """WebhookConfig can have a custom secret_env."""
        wc = WebhookConfig(secret_env="MY_WEBHOOK_SECRET")
        assert wc.secret_env == "MY_WEBHOOK_SECRET"


class TestWebhookConfigParsing:
    """Tests for webhook config parsing in _parse_server."""

    def test_webhooks_defaults_when_section_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When no webhooks section is present, defaults are applied."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        cfg = load_config()
        assert cfg.server.webhooks.enabled is True
        assert cfg.server.webhooks.secret_env == "DISTILLERY_WEBHOOK_SECRET"

    def test_webhooks_enabled_true(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Webhooks can be explicitly enabled."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        yaml_content = """\
            server:
              webhooks:
                enabled: true
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.server.webhooks.enabled is True

    def test_webhooks_enabled_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Webhooks can be disabled."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        yaml_content = """\
            server:
              webhooks:
                enabled: false
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.server.webhooks.enabled is False

    def test_webhooks_custom_secret_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Webhooks can have a custom secret_env."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        yaml_content = """\
            server:
              webhooks:
                secret_env: MY_CUSTOM_WEBHOOK_SECRET
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.server.webhooks.secret_env == "MY_CUSTOM_WEBHOOK_SECRET"

    def test_webhooks_all_fields(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """All webhook fields can be configured together."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        yaml_content = """\
            server:
              webhooks:
                enabled: false
                secret_env: CUSTOM_SECRET_ENV
        """
        p = write_yaml(tmp_path, yaml_content)
        cfg = load_config(str(p))
        assert cfg.server.webhooks.enabled is False
        assert cfg.server.webhooks.secret_env == "CUSTOM_SECRET_ENV"

    def test_server_webhooks_as_list_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Webhooks section must be a mapping, not a list."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
        yaml_content = """\
            server:
              webhooks: []
        """
        p = write_yaml(tmp_path, yaml_content)
        with pytest.raises(ValueError, match="server.webhooks must be a YAML mapping"):
            load_config(str(p))
