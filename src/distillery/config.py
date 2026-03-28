"""Configuration module for Distillery.

Loads settings from a YAML configuration file (distillery.yaml) with support
for path override via the DISTILLERY_CONFIG environment variable.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Default configuration file name looked up relative to cwd.
DEFAULT_CONFIG_FILENAME = "distillery.yaml"

# Environment variable that overrides the config file path.
CONFIG_ENV_VAR = "DISTILLERY_CONFIG"


@dataclass
class StorageConfig:
    """Storage backend configuration.

    Attributes:
        backend: Storage backend identifier. One of ``'duckdb'`` or ``'motherduck'``.
        database_path: Path to the DuckDB database file. Supports ``~`` expansion
            for local paths, ``s3://`` prefix for S3-backed storage, and ``md:``
            prefix for MotherDuck cloud databases.
        s3_region: AWS region for S3 storage (e.g. ``'us-east-1'``). Falls back to
            ``AWS_DEFAULT_REGION`` / ``AWS_REGION`` environment variables when
            ``None``.
        s3_endpoint: Custom S3-compatible endpoint URL for non-AWS services such as
            MinIO or Cloudflare R2 (e.g. ``'https://my-minio.example.com'``).
            When set, path-style URL access is enabled automatically.
        motherduck_token_env: Name of the environment variable that holds the
            MotherDuck token.  Defaults to ``'MOTHERDUCK_TOKEN'``.
    """

    backend: str = "duckdb"
    database_path: str = "~/.distillery/distillery.db"
    s3_region: str | None = None
    s3_endpoint: str | None = None
    motherduck_token_env: str = "MOTHERDUCK_TOKEN"


@dataclass
class EmbeddingConfig:
    """Embedding provider configuration.

    Attributes:
        provider: Embedding provider name. One of 'jina' or 'openai'.
        model: Embedding model identifier.
        dimensions: Dimensionality of embedding vectors.
        api_key_env: Name of the environment variable that holds the API key.
    """

    provider: str = ""
    model: str = "jina-embeddings-v3"
    dimensions: int = 1024
    api_key_env: str = ""


@dataclass
class TeamConfig:
    """Team configuration.

    Attributes:
        name: Human-readable team name used for labelling stored entries.
    """

    name: str = ""


@dataclass
class ClassificationConfig:
    """Classification configuration.

    Attributes:
        confidence_threshold: Minimum confidence score [0.0, 1.0] required
            before an auto-classification label is accepted.
        dedup_skip_threshold: Similarity score at or above which content is
            treated as a near-exact duplicate and should be skipped. Default
            ``0.95``.
        dedup_merge_threshold: Similarity score at or above which (but below
            *dedup_skip_threshold*) the content should be merged with the most
            similar entry. Default ``0.80``.
        dedup_link_threshold: Similarity score at or above which (but below
            *dedup_merge_threshold*) a new entry should be linked to similar
            entries. Default ``0.60``.
        dedup_limit: Maximum number of similar entries to retrieve from the
            store during deduplication checks. Default ``5``.
        feedback_window_minutes: Number of minutes after a search during which
            a retrieval action is attributed as implicit positive feedback.
            Default ``5``.
        stale_days: Number of days without access after which an entry is
            considered stale. Default ``30``.
        conflict_threshold: Similarity score at or above which two entries in
            different projects are flagged as potential conflicts. Default
            ``0.60``.
    """

    confidence_threshold: float = 0.6
    dedup_skip_threshold: float = 0.95
    dedup_merge_threshold: float = 0.80
    dedup_link_threshold: float = 0.60
    dedup_limit: int = 5
    feedback_window_minutes: int = 5
    stale_days: int = 30
    conflict_threshold: float = 0.60


@dataclass
class TagsConfig:
    """Tag namespace configuration.

    Attributes:
        enforce_namespaces: When ``True``, all new tags submitted to the store
            must contain at least one ``/`` separator.  Existing entries with
            flat tags are unaffected.  Defaults to ``False``.
        reserved_prefixes: Top-level namespace prefixes (e.g. ``["system"]``)
            that only specific internal sources may use.  Each entry must be a
            valid lowercase alphanumeric slug (same rules as a single tag
            segment).  Defaults to ``[]``.
    """

    enforce_namespaces: bool = False
    reserved_prefixes: list[str] = field(default_factory=list)


@dataclass
class DistilleryConfig:
    """Top-level configuration container for a Distillery deployment.

    Attributes:
        storage: Storage backend settings.
        embedding: Embedding provider settings.
        team: Team-level metadata settings.
        classification: Classification threshold settings.
        tags: Tag namespace enforcement settings.
    """

    storage: StorageConfig = field(default_factory=StorageConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    team: TeamConfig = field(default_factory=TeamConfig)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
    tags: TagsConfig = field(default_factory=TagsConfig)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def _find_config_path(override: str | None = None) -> Path | None:
    """Locate the configuration file.

    Resolution order:
    1. *override* argument (explicit path passed by caller)
    2. ``DISTILLERY_CONFIG`` environment variable
    3. ``distillery.yaml`` in the current working directory

    Args:
        override: Optional explicit path to a configuration file.

    Returns:
        The resolved :class:`~pathlib.Path` to the config file, or ``None``
        if no config file could be found.
    """
    candidates: list[str] = []

    if override:
        candidates.append(override)

    env_path = os.environ.get(CONFIG_ENV_VAR)
    if env_path:
        candidates.append(env_path)

    candidates.append(DEFAULT_CONFIG_FILENAME)

    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.exists():
            return path

    return None


def _parse_storage(raw: dict[str, Any]) -> StorageConfig:
    s3_region_raw = raw.get("s3_region")
    s3_endpoint_raw = raw.get("s3_endpoint")
    return StorageConfig(
        backend=str(raw.get("backend", "duckdb")),
        database_path=str(raw.get("database_path", "~/.distillery/distillery.db")),
        s3_region=str(s3_region_raw) if s3_region_raw is not None else None,
        s3_endpoint=str(s3_endpoint_raw) if s3_endpoint_raw is not None else None,
        motherduck_token_env=str(raw.get("motherduck_token_env", "MOTHERDUCK_TOKEN")),
    )


def _parse_embedding(raw: dict[str, Any]) -> EmbeddingConfig:
    provider = str(raw.get("provider", ""))
    model = str(raw.get("model", "jina-embeddings-v3"))

    dimensions_raw = raw.get("dimensions", 1024)
    try:
        dimensions = int(dimensions_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"embedding.dimensions must be an integer, got: {dimensions_raw!r}"
        ) from exc

    api_key_env = str(raw.get("api_key_env", ""))

    return EmbeddingConfig(
        provider=provider,
        model=model,
        dimensions=dimensions,
        api_key_env=api_key_env,
    )


def _parse_team(raw: dict[str, Any]) -> TeamConfig:
    return TeamConfig(name=str(raw.get("name", "")))


def _parse_float_field(raw: dict[str, Any], key: str, default: float, label: str) -> float:
    """
    Parse a field value from a mapping and convert it to a float.

    Parameters:
        raw (dict[str, Any]): Mapping containing the raw configuration values.
        key (str): Key to read from `raw`; uses `default` if key is missing.
        default (float): Value to use when the field is absent.
        label (str): Human-readable field name used in error messages.

    Returns:
        float: The parsed float value.

    Raises:
        ValueError: If the value cannot be converted to a float.
    """
    value_raw = raw.get(key, default)
    try:
        return float(value_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a float, got: {value_raw!r}") from exc


def _parse_strict_int(value: Any, label: str) -> int:
    """
    Parse and validate an integer value from a restrictive set of inputs.

    Accepts a native `int` (explicitly rejects `bool`) or a `str` that, after trimming, is an optional leading `-` followed by digits. On success returns the corresponding `int`; otherwise raises `ValueError` with `label` included in the message.

    Parameters:
        value (Any): The value to parse as an integer.
        label (str): Human-readable name used in the error message on failure.

    Returns:
        int: The parsed integer value.
    """
    if type(value) is int:  # noqa: E721 – reject bool subclass
        return value
    if isinstance(value, str):
        stripped = value.strip()
        candidate = stripped.lstrip("-")
        if candidate.isdigit() and (len(candidate) == len(stripped) or stripped.startswith("-")):
            return int(stripped)
    raise ValueError(f"{label} must be an integer, got: {value!r}")


def _parse_classification(raw: dict[str, Any]) -> ClassificationConfig:
    """
    Parse the classification section from a raw mapping and return a populated ClassificationConfig.

    Parameters:
        raw (dict[str, Any]): Mapping (typically from YAML) containing any of the following keys:
            - "confidence_threshold" (float, default 0.6)
            - "dedup_skip_threshold" (float, default 0.95)
            - "dedup_merge_threshold" (float, default 0.80)
            - "dedup_link_threshold" (float, default 0.60)
            - "dedup_limit" (int, default 5)
            - "feedback_window_minutes" (int or int-string, default 5)
            - "stale_days" (int or int-string, default 30)
            - "conflict_threshold" (float, default 0.60)

    Returns:
        ClassificationConfig: Configuration object with parsed and coerced values for classification settings.

    Raises:
        ValueError: If any numeric field cannot be parsed or does not meet expected type/format (e.g., invalid floats, non-integer dedup_limit, or strict-integer parsing failures for feedback_window_minutes/stale_days).
    """
    threshold = _parse_float_field(
        raw, "confidence_threshold", 0.6, "classification.confidence_threshold"
    )
    skip = _parse_float_field(
        raw, "dedup_skip_threshold", 0.95, "classification.dedup_skip_threshold"
    )
    merge = _parse_float_field(
        raw, "dedup_merge_threshold", 0.80, "classification.dedup_merge_threshold"
    )
    link = _parse_float_field(
        raw, "dedup_link_threshold", 0.60, "classification.dedup_link_threshold"
    )

    limit_raw = raw.get("dedup_limit", 5)
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"classification.dedup_limit must be an integer, got: {limit_raw!r}"
        ) from exc

    feedback_window_raw = raw.get("feedback_window_minutes", 5)
    feedback_window_minutes = _parse_strict_int(
        feedback_window_raw, "classification.feedback_window_minutes"
    )

    stale_days_raw = raw.get("stale_days", 30)
    stale_days = _parse_strict_int(stale_days_raw, "classification.stale_days")

    conflict_threshold = _parse_float_field(
        raw, "conflict_threshold", 0.60, "classification.conflict_threshold"
    )

    return ClassificationConfig(
        confidence_threshold=threshold,
        dedup_skip_threshold=skip,
        dedup_merge_threshold=merge,
        dedup_link_threshold=link,
        dedup_limit=limit,
        feedback_window_minutes=feedback_window_minutes,
        stale_days=stale_days,
        conflict_threshold=conflict_threshold,
    )


def _parse_tags(raw: dict[str, Any]) -> TagsConfig:
    """Parse the ``tags`` section from a raw YAML mapping.

    Args:
        raw: Mapping (typically from YAML) containing any of the following keys:
            - ``enforce_namespaces`` (bool, default ``False``)
            - ``reserved_prefixes`` (list[str], default ``[]``)

    Returns:
        A populated :class:`TagsConfig` instance.

    Raises:
        ValueError: If ``enforce_namespaces`` is not a boolean or
            ``reserved_prefixes`` is not a list.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"tags must be a YAML mapping, got: {type(raw).__name__}")

    enforce_raw = raw.get("enforce_namespaces", False)
    if not isinstance(enforce_raw, bool):
        raise ValueError(f"tags.enforce_namespaces must be a boolean, got: {enforce_raw!r}")

    prefixes_raw = raw.get("reserved_prefixes", [])
    if not isinstance(prefixes_raw, list):
        raise ValueError(
            f"tags.reserved_prefixes must be a list, got: {type(prefixes_raw).__name__}"
        )

    return TagsConfig(
        enforce_namespaces=enforce_raw,
        reserved_prefixes=[str(p) for p in prefixes_raw],
    )


def _validate(config: DistilleryConfig) -> None:
    """
    Validate a DistilleryConfig instance and raise a ValueError for any invalid setting.

    Args:
        config: Parsed DistilleryConfig to validate.

    Raises:
        ValueError: If any of the following conditions are violated:
            - embedding.provider is non-empty and not one of "jina" or "openai".
            - embedding.dimensions is not greater than 0.
            - classification.confidence_threshold is not between 0.0 and 1.0.
            - classification.dedup_link_threshold, classification.dedup_merge_threshold,
              or classification.dedup_skip_threshold is not between 0.0 and 1.0.
            - classification dedup thresholds do not satisfy
              dedup_link_threshold <= dedup_merge_threshold <= dedup_skip_threshold.
            - classification.dedup_limit is not greater than 0.
            - classification.feedback_window_minutes is not greater than 0.
            - classification.stale_days is not greater than 0.
            - classification.conflict_threshold is not between 0.0 and 1.0.
            - Any entry in tags.reserved_prefixes is not a valid tag segment.
    """
    valid_backends = {"duckdb", "motherduck"}
    if config.storage.backend not in valid_backends:
        raise ValueError(
            f"storage.backend must be one of {sorted(valid_backends)}, "
            f"got: {config.storage.backend!r}"
        )

    valid_providers = {"jina", "openai"}
    if config.embedding.provider and config.embedding.provider not in valid_providers:
        raise ValueError(
            f"embedding.provider must be one of {sorted(valid_providers)}, "
            f"got: {config.embedding.provider!r}"
        )

    if config.embedding.dimensions <= 0:
        raise ValueError(
            f"embedding.dimensions must be a positive integer, got: {config.embedding.dimensions}"
        )

    threshold = config.classification.confidence_threshold
    if not (0.0 <= threshold <= 1.0):
        raise ValueError(
            f"classification.confidence_threshold must be between 0.0 and 1.0, got: {threshold}"
        )

    link = config.classification.dedup_link_threshold
    merge = config.classification.dedup_merge_threshold
    skip = config.classification.dedup_skip_threshold

    for name, value in [
        ("dedup_link_threshold", link),
        ("dedup_merge_threshold", merge),
        ("dedup_skip_threshold", skip),
    ]:
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"classification.{name} must be between 0.0 and 1.0, got: {value}")

    if not (link <= merge <= skip):
        raise ValueError(
            "classification dedup thresholds must satisfy "
            f"dedup_link_threshold ({link}) <= dedup_merge_threshold ({merge}) "
            f"<= dedup_skip_threshold ({skip})"
        )

    if config.classification.dedup_limit <= 0:
        raise ValueError(
            "classification.dedup_limit must be a positive integer, "
            f"got: {config.classification.dedup_limit}"
        )

    if config.classification.feedback_window_minutes <= 0:
        raise ValueError(
            "classification.feedback_window_minutes must be a positive integer, "
            f"got: {config.classification.feedback_window_minutes}"
        )

    if config.classification.stale_days <= 0:
        raise ValueError(
            "classification.stale_days must be a positive integer, "
            f"got: {config.classification.stale_days}"
        )

    conflict = config.classification.conflict_threshold
    if not (0.0 <= conflict <= 1.0):
        raise ValueError(
            f"classification.conflict_threshold must be between 0.0 and 1.0, got: {conflict}"
        )

    # Validate reserved_prefixes: each must be a valid single tag segment.
    _segment_re = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
    for prefix in config.tags.reserved_prefixes:
        if not _segment_re.match(prefix):
            raise ValueError(
                f"tags.reserved_prefixes entry {prefix!r} is not a valid tag segment. "
                "Each prefix must match [a-z0-9][a-z0-9-]* "
                "(lowercase alphanumeric plus internal hyphens only)."
            )


def load_config(config_path: str | None = None) -> DistilleryConfig:
    """Load and validate configuration from a YAML file.

    If no configuration file is found the function returns a
    :class:`DistilleryConfig` with all defaults applied (i.e. running without
    any YAML file is valid for basic use-cases).

    Resolution order for the configuration file:
    1. *config_path* argument
    2. ``DISTILLERY_CONFIG`` environment variable
    3. ``distillery.yaml`` in the current working directory

    Args:
        config_path: Optional explicit path to a YAML configuration file.

    Returns:
        A fully populated :class:`DistilleryConfig` instance.

    Raises:
        FileNotFoundError: If *config_path* is given explicitly but the file
            does not exist.
        ValueError: If the configuration contains invalid values.
        yaml.YAMLError: If the YAML file cannot be parsed.
    """
    # If caller supplied an explicit path, it MUST exist.
    if config_path is not None:
        explicit = Path(config_path).expanduser()
        if not explicit.exists():
            raise FileNotFoundError(f"Configuration file not found: {explicit}")
        resolved: Path | None = explicit
    else:
        resolved = _find_config_path()

    if resolved is None:
        # No config file present – return defaults.
        config = DistilleryConfig()
        _validate(config)
        return config

    with open(resolved, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if raw is None:
        raw = {}

    if not isinstance(raw, dict):
        raise ValueError(f"Configuration file must be a YAML mapping, got: {type(raw).__name__}")

    storage_raw = raw.get("storage", {}) or {}
    embedding_raw = raw.get("embedding", {}) or {}
    team_raw = raw.get("team", {}) or {}
    classification_raw = raw.get("classification", {}) or {}
    tags_raw = raw.get("tags", {}) or {}

    config = DistilleryConfig(
        storage=_parse_storage(storage_raw),
        embedding=_parse_embedding(embedding_raw),
        team=_parse_team(team_raw),
        classification=_parse_classification(classification_raw),
        tags=_parse_tags(tags_raw),
    )

    _validate(config)
    return config
