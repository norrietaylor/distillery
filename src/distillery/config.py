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
class DefaultsConfig:
    """Handler-level defaults configuration.

    These are operational defaults used by MCP handlers, distinct from
    ClassificationConfig which contains classification engine thresholds.

    Attributes:
        dedup_threshold: Default similarity threshold for deduplication checks
            in MCP handlers. Default ``0.92``.
        dedup_limit: Default maximum number of similar entries to retrieve
            during deduplication checks. Default ``3``.
        stale_days: Default number of days without access after which an entry
            is considered stale. Default ``30``.
        hybrid_search: Whether to enable hybrid BM25 + vector search with RRF
            fusion. Default ``True``.
        rrf_k: Reciprocal Rank Fusion constant controlling rank influence.
            Higher values reduce the impact of top-ranked results. Default
            ``60``.
        recency_window_days: Number of days defining the recency window for
            recency-weighted scoring. Default ``90``.
        recency_min_weight: Minimum weight applied to entries outside the
            recency window. Must be in range [0.0, 1.0]. Default ``0.5``.
    """

    dedup_threshold: float = 0.92
    dedup_limit: int = 3
    stale_days: int = 30
    hybrid_search: bool = True
    rrf_k: int = 60
    recency_window_days: int = 90
    recency_min_weight: float = 0.5


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
        mode: Classification mode — ``"llm"`` for LLM-based classification
            or ``"heuristic"`` for embedding centroid-based classification.
            Default ``"llm"``.
    """

    confidence_threshold: float = 0.6
    dedup_skip_threshold: float = 0.95
    dedup_merge_threshold: float = 0.80
    dedup_link_threshold: float = 0.60
    dedup_limit: int = 5
    feedback_window_minutes: int = 5
    stale_days: int = 30
    conflict_threshold: float = 0.60
    mode: str = "llm"


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
class FeedSourceConfig:
    """Configuration for a single monitored feed source.

    Attributes:
        url: The URL of the feed (e.g. RSS feed URL or GitHub repo URL).
        source_type: Adapter type.  One of ``'rss'`` or ``'github'``.
        label: Optional human-readable label for the source.
        poll_interval_minutes: How often to poll this source.  Defaults to
            ``60`` minutes.
        trust_weight: Relevance trust multiplier in the range ``[0.0, 1.0]``.
            Higher values amplify relevance scores from this source.  Defaults
            to ``1.0``.
    """

    url: str = ""
    source_type: str = "rss"
    label: str = ""
    poll_interval_minutes: int = 60
    trust_weight: float = 1.0


@dataclass
class FeedsThresholdsConfig:
    """Relevance thresholds used when scoring incoming feed items.

    Attributes:
        alert: Cosine similarity score at or above which a feed item triggers
            an immediate alert.  Default ``0.85``.
        digest: Cosine similarity score at or above which (but below *alert*)
            a feed item is included in the next digest.  Default ``0.60``.
    """

    alert: float = 0.85
    digest: float = 0.60


@dataclass
class FeedsConfig:
    """Ambient feed monitoring configuration.

    Attributes:
        sources: Ordered list of feed sources to monitor.
        thresholds: Relevance score thresholds for alert vs. digest inclusion.
    """

    sources: list[FeedSourceConfig] = field(default_factory=list)
    thresholds: FeedsThresholdsConfig = field(default_factory=FeedsThresholdsConfig)


@dataclass
class RateLimitConfig:
    """Rate limiting and resource budget configuration.

    Attributes:
        embedding_budget_daily: Maximum embedding API calls per calendar day.
            Set to ``0`` to disable the budget (unlimited).  Default ``500``.
        max_db_size_mb: Maximum database file size in megabytes before new
            writes are rejected.  Set to ``0`` to disable.  Default ``900``
            (leaves ~100 MB headroom on a 1 GB Fly volume).
        warn_db_size_pct: Percentage of *max_db_size_mb* at which a warning is
            surfaced in ``distillery_status``.  Default ``80``.
    """

    embedding_budget_daily: int = 500
    max_db_size_mb: int = 900
    warn_db_size_pct: int = 80
    search_logging_enabled: bool = True
    search_log_retention_days: int = 90


@dataclass
class ServerAuthConfig:
    """Server authentication configuration.

    Attributes:
        provider: Authentication provider. One of ``'github'`` or ``'none'``.
        client_id_env: Name of the environment variable holding the OAuth
            client ID.
        client_secret_env: Name of the environment variable holding the OAuth
            client secret.
        allowed_orgs: GitHub organisation login names (slugs) whose members
            are permitted to access the server.  Empty list (default) means
            any GitHub user can authenticate (open-access mode).  Can also be
            set via the ``DISTILLERY_ALLOWED_ORGS`` environment variable
            (comma-separated); env values are merged with YAML values.
        membership_cache_ttl_seconds: How long to cache org-membership results
            in seconds.  Default is 3600 (1 hour).  Set to a smaller value if
            you need revoked memberships to take effect sooner.
    """

    provider: str = "none"
    client_id_env: str = "GITHUB_CLIENT_ID"
    client_secret_env: str = "GITHUB_CLIENT_SECRET"
    allowed_orgs: list[str] = field(default_factory=list)
    membership_cache_ttl_seconds: int = 3600


@dataclass
class HttpRateLimitConfig:
    """HTTP transport rate limiting configuration.

    Attributes:
        requests_per_minute: Maximum requests per IP per minute.
        requests_per_hour: Maximum requests per IP per hour.
        max_body_bytes: Maximum request body size in bytes.
        trust_proxy: When ``True``, prefer ``X-Forwarded-For`` for client IP
            extraction.  Enable when running behind a reverse proxy (Fly.io,
            nginx, Cloudflare).
        loopback_exempt: When ``True`` (default), skip rate limiting for
            requests from loopback addresses (``127.0.0.1``, ``::1``,
            ``localhost``).  This prevents local concurrent workflows from
            being starved by the shared per-IP bucket.
    """

    requests_per_minute: int = 60
    requests_per_hour: int = 600
    max_body_bytes: int = 1_048_576  # 1 MB
    trust_proxy: bool = False
    loopback_exempt: bool = True
    cors_allowed_origins: list[str] = field(default_factory=list)


@dataclass
class WebhookConfig:
    """Webhook endpoint configuration.

    Attributes:
        enabled: Whether to enable webhook endpoints. Defaults to ``True``.
        secret_env: Name of the environment variable holding the webhook
            bearer token secret. Defaults to ``'DISTILLERY_WEBHOOK_SECRET'``.
    """

    enabled: bool = True
    secret_env: str = "DISTILLERY_WEBHOOK_SECRET"


@dataclass
class ServerConfig:
    """Server configuration.

    Attributes:
        auth: Authentication settings for HTTP transport.
        http_rate_limit: HTTP transport rate limiting settings.
        webhooks: Webhook endpoint settings.
    """

    auth: ServerAuthConfig = field(default_factory=ServerAuthConfig)
    http_rate_limit: HttpRateLimitConfig = field(default_factory=HttpRateLimitConfig)
    webhooks: WebhookConfig = field(default_factory=WebhookConfig)


@dataclass
class DistilleryConfig:
    """Top-level configuration container for a Distillery deployment.

    Attributes:
        storage: Storage backend settings.
        embedding: Embedding provider settings.
        team: Team-level metadata settings.
        defaults: Handler-level operational defaults.
        classification: Classification threshold settings.
        tags: Tag namespace enforcement settings.
        feeds: Ambient feed monitoring settings.
        rate_limit: Rate limiting and resource budget settings.
        server: Server (HTTP transport) settings.
    """

    storage: StorageConfig = field(default_factory=StorageConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    team: TeamConfig = field(default_factory=TeamConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
    tags: TagsConfig = field(default_factory=TagsConfig)
    feeds: FeedsConfig = field(default_factory=FeedsConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    server: ServerConfig = field(default_factory=ServerConfig)


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


def _parse_defaults(raw: dict[str, Any]) -> DefaultsConfig:
    dedup_threshold = _parse_float_field(raw, "dedup_threshold", 0.92, "defaults.dedup_threshold")

    dedup_limit_raw = raw.get("dedup_limit", 3)
    try:
        dedup_limit = int(dedup_limit_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"defaults.dedup_limit must be an integer, got: {dedup_limit_raw!r}"
        ) from exc

    stale_days_raw = raw.get("stale_days", 30)
    stale_days = _parse_strict_int(stale_days_raw, "defaults.stale_days")

    hybrid_search_raw = raw.get("hybrid_search", True)
    if not isinstance(hybrid_search_raw, bool):
        raise ValueError(f"defaults.hybrid_search must be a boolean, got: {hybrid_search_raw!r}")
    hybrid_search = hybrid_search_raw

    rrf_k_raw = raw.get("rrf_k", 60)
    rrf_k = _parse_strict_int(rrf_k_raw, "defaults.rrf_k")
    if rrf_k <= 0:
        raise ValueError(f"defaults.rrf_k must be a positive integer, got: {rrf_k}")

    recency_window_days_raw = raw.get("recency_window_days", 90)
    recency_window_days = _parse_strict_int(recency_window_days_raw, "defaults.recency_window_days")
    if recency_window_days <= 0:
        raise ValueError(
            f"defaults.recency_window_days must be a positive integer, got: {recency_window_days}"
        )

    recency_min_weight = _parse_float_field(
        raw, "recency_min_weight", 0.5, "defaults.recency_min_weight"
    )
    if not (0.0 <= recency_min_weight <= 1.0):
        raise ValueError(
            f"defaults.recency_min_weight must be between 0.0 and 1.0, got: {recency_min_weight}"
        )

    return DefaultsConfig(
        dedup_threshold=dedup_threshold,
        dedup_limit=dedup_limit,
        stale_days=stale_days,
        hybrid_search=hybrid_search,
        rrf_k=rrf_k,
        recency_window_days=recency_window_days,
        recency_min_weight=recency_min_weight,
    )


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

    mode_raw = raw.get("mode", "llm")
    mode = str(mode_raw)
    if mode not in ("llm", "heuristic"):
        raise ValueError(f"classification.mode must be 'llm' or 'heuristic', got: {mode!r}")

    return ClassificationConfig(
        confidence_threshold=threshold,
        dedup_skip_threshold=skip,
        dedup_merge_threshold=merge,
        dedup_link_threshold=link,
        dedup_limit=limit,
        feedback_window_minutes=feedback_window_minutes,
        stale_days=stale_days,
        conflict_threshold=conflict_threshold,
        mode=mode,
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


def _parse_feed_source(raw: dict[str, Any], index: int) -> FeedSourceConfig:
    """Parse a single feed source entry from a raw YAML mapping.

    Args:
        raw: Mapping describing one feed source.
        index: Zero-based position in the sources list (used in error messages).

    Returns:
        A populated :class:`FeedSourceConfig` instance.

    Raises:
        ValueError: If ``url`` is missing, ``source_type`` is not a valid
            adapter type, ``poll_interval_minutes`` is not a positive integer,
            or ``trust_weight`` is not in ``[0.0, 1.0]``.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            f"feeds.sources[{index}] must be a YAML mapping, got: {type(raw).__name__}"
        )

    url = str(raw.get("url", "")).strip()
    if not url:
        raise ValueError(f"feeds.sources[{index}].url is required and must be non-empty")

    valid_source_types = {"rss", "github"}
    source_type = str(raw.get("source_type", "rss"))
    if source_type not in valid_source_types:
        raise ValueError(
            f"feeds.sources[{index}].source_type must be one of "
            f"{sorted(valid_source_types)}, got: {source_type!r}"
        )

    label = str(raw.get("label", ""))

    poll_interval_raw = raw.get("poll_interval_minutes", 60)
    poll_interval = _parse_strict_int(
        poll_interval_raw, f"feeds.sources[{index}].poll_interval_minutes"
    )
    if poll_interval <= 0:
        raise ValueError(
            f"feeds.sources[{index}].poll_interval_minutes must be a positive integer, "
            f"got: {poll_interval}"
        )

    trust_weight_raw = raw.get("trust_weight", 1.0)
    try:
        trust_weight = float(trust_weight_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"feeds.sources[{index}].trust_weight must be a float, got: {trust_weight_raw!r}"
        ) from exc
    if not (0.0 <= trust_weight <= 1.0):
        raise ValueError(
            f"feeds.sources[{index}].trust_weight must be between 0.0 and 1.0, got: {trust_weight}"
        )

    return FeedSourceConfig(
        url=url,
        source_type=source_type,
        label=label,
        poll_interval_minutes=poll_interval,
        trust_weight=trust_weight,
    )


def _parse_feeds(raw: dict[str, Any]) -> FeedsConfig:
    """Parse the ``feeds`` section from a raw YAML mapping.

    Args:
        raw: Mapping (typically from YAML) containing any of the following keys:
            - ``sources`` (list of feed source mappings, default ``[]``)
            - ``thresholds`` (mapping with ``alert`` and ``digest`` keys)

    Returns:
        A populated :class:`FeedsConfig` instance.

    Raises:
        ValueError: If ``sources`` is not a list, any source entry is invalid,
            or threshold values are out of range.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"feeds must be a YAML mapping, got: {type(raw).__name__}")

    sources_raw = raw.get("sources", [])
    if not isinstance(sources_raw, list):
        raise ValueError(f"feeds.sources must be a list, got: {type(sources_raw).__name__}")
    sources = [_parse_feed_source(s, i) for i, s in enumerate(sources_raw)]

    thresholds_raw = raw.get("thresholds", {}) or {}
    if not isinstance(thresholds_raw, dict):
        raise ValueError(
            f"feeds.thresholds must be a YAML mapping, got: {type(thresholds_raw).__name__}"
        )

    alert = _parse_float_field(thresholds_raw, "alert", 0.85, "feeds.thresholds.alert")
    digest = _parse_float_field(thresholds_raw, "digest", 0.60, "feeds.thresholds.digest")

    return FeedsConfig(
        sources=sources,
        thresholds=FeedsThresholdsConfig(alert=alert, digest=digest),
    )


def _parse_rate_limit(raw: dict[str, Any]) -> RateLimitConfig:
    """Parse the ``rate_limit`` section from a raw YAML mapping.

    Args:
        raw: Mapping containing optional keys ``embedding_budget_daily``,
            ``max_db_size_mb``, ``warn_db_size_pct``.

    Returns:
        A populated :class:`RateLimitConfig` instance.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"rate_limit must be a YAML mapping, got: {type(raw).__name__}")

    search_logging_enabled_raw = raw.get("search_logging_enabled", True)
    if not isinstance(search_logging_enabled_raw, bool):
        raise ValueError(
            "rate_limit.search_logging_enabled must be a boolean, "
            f"got: {search_logging_enabled_raw!r}"
        )

    return RateLimitConfig(
        embedding_budget_daily=_parse_strict_int(
            raw.get("embedding_budget_daily", 500),
            "rate_limit.embedding_budget_daily",
        ),
        max_db_size_mb=_parse_strict_int(
            raw.get("max_db_size_mb", 900),
            "rate_limit.max_db_size_mb",
        ),
        warn_db_size_pct=_parse_strict_int(
            raw.get("warn_db_size_pct", 80),
            "rate_limit.warn_db_size_pct",
        ),
        search_logging_enabled=search_logging_enabled_raw,
        search_log_retention_days=_parse_strict_int(
            raw.get("search_log_retention_days", 90),
            "rate_limit.search_log_retention_days",
        ),
    )


def _parse_http_rate_limit(rl_raw: dict[str, Any]) -> HttpRateLimitConfig:
    """Parse ``server.http_rate_limit`` with strict boolean validation."""
    trust_proxy_raw = rl_raw.get("trust_proxy", False)
    if not isinstance(trust_proxy_raw, bool):
        raise ValueError(
            f"server.http_rate_limit.trust_proxy must be a boolean, got: {trust_proxy_raw!r}"
        )

    loopback_exempt_raw = rl_raw.get("loopback_exempt", True)
    if not isinstance(loopback_exempt_raw, bool):
        raise ValueError(
            f"server.http_rate_limit.loopback_exempt must be a boolean, got: {loopback_exempt_raw!r}"
        )

    requests_per_minute = _parse_strict_int(
        rl_raw.get("requests_per_minute", 60),
        "server.http_rate_limit.requests_per_minute",
    )
    if requests_per_minute <= 0:
        raise ValueError(
            f"server.http_rate_limit.requests_per_minute must be > 0, got: {requests_per_minute}"
        )

    requests_per_hour = _parse_strict_int(
        rl_raw.get("requests_per_hour", 600),
        "server.http_rate_limit.requests_per_hour",
    )
    if requests_per_hour <= 0:
        raise ValueError(
            f"server.http_rate_limit.requests_per_hour must be > 0, got: {requests_per_hour}"
        )

    max_body_bytes = _parse_strict_int(
        rl_raw.get("max_body_bytes", 1_048_576),
        "server.http_rate_limit.max_body_bytes",
    )
    if max_body_bytes <= 0:
        raise ValueError(
            f"server.http_rate_limit.max_body_bytes must be > 0, got: {max_body_bytes}"
        )

    cors_origins_raw = rl_raw.get("cors_allowed_origins", []) or []
    if not isinstance(cors_origins_raw, list):
        raise ValueError("server.http_rate_limit.cors_allowed_origins must be a YAML list")
    cors_allowed_origins = [str(o).strip() for o in cors_origins_raw if str(o).strip()]

    return HttpRateLimitConfig(
        requests_per_minute=requests_per_minute,
        requests_per_hour=requests_per_hour,
        max_body_bytes=max_body_bytes,
        trust_proxy=trust_proxy_raw,
        loopback_exempt=loopback_exempt_raw,
        cors_allowed_origins=cors_allowed_origins,
    )


def _parse_webhooks(webhooks_raw: dict[str, Any]) -> WebhookConfig:
    """Parse ``server.webhooks`` with strict boolean validation."""
    enabled_raw = webhooks_raw.get("enabled", True)
    if not isinstance(enabled_raw, bool):
        raise ValueError(f"server.webhooks.enabled must be a boolean, got: {enabled_raw!r}")

    return WebhookConfig(
        enabled=enabled_raw,
        secret_env=str(webhooks_raw.get("secret_env", "DISTILLERY_WEBHOOK_SECRET")),
    )


def _parse_server(raw: dict[str, Any]) -> ServerConfig:
    """Parse the ``server`` section from a raw YAML mapping.

    Args:
        raw: Mapping (typically from YAML) containing:
            - ``auth`` (mapping with ``provider``, ``client_id_env``,
              ``client_secret_env``)
            - ``http_rate_limit`` (mapping with rate limit settings)
            - ``webhooks`` (mapping with webhook settings)

    Returns:
        A populated :class:`ServerConfig` instance.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"server must be a YAML mapping, got: {type(raw).__name__}")

    auth_raw = raw.get("auth", {})
    if auth_raw is None:
        auth_raw = {}
    if not isinstance(auth_raw, dict):
        raise ValueError(f"server.auth must be a YAML mapping, got: {type(auth_raw).__name__}")

    rl_raw = raw.get("http_rate_limit", {})
    if rl_raw is None:
        rl_raw = {}
    if not isinstance(rl_raw, dict):
        raise ValueError(
            f"server.http_rate_limit must be a YAML mapping, got: {type(rl_raw).__name__}"
        )

    webhooks_raw = raw.get("webhooks", {})
    if webhooks_raw is None:
        webhooks_raw = {}
    if not isinstance(webhooks_raw, dict):
        raise ValueError(
            f"server.webhooks must be a YAML mapping, got: {type(webhooks_raw).__name__}"
        )

    allowed_orgs_raw = auth_raw.get("allowed_orgs", []) or []
    if not isinstance(allowed_orgs_raw, list):
        raise ValueError("server.auth.allowed_orgs must be a YAML list")
    allowed_orgs = [str(o).strip() for o in allowed_orgs_raw if str(o).strip()]

    ttl_raw = auth_raw.get("membership_cache_ttl_seconds", 3600)
    membership_cache_ttl_seconds = _parse_strict_int(
        ttl_raw, "server.auth.membership_cache_ttl_seconds"
    )

    return ServerConfig(
        auth=ServerAuthConfig(
            provider=str(auth_raw.get("provider", "none")),
            client_id_env=str(auth_raw.get("client_id_env", "GITHUB_CLIENT_ID")),
            client_secret_env=str(auth_raw.get("client_secret_env", "GITHUB_CLIENT_SECRET")),
            allowed_orgs=allowed_orgs,
            membership_cache_ttl_seconds=membership_cache_ttl_seconds,
        ),
        http_rate_limit=_parse_http_rate_limit(rl_raw),
        webhooks=_parse_webhooks(webhooks_raw),
    )


def parse_env_allowed_orgs() -> list[str]:
    """Parse ``DISTILLERY_ALLOWED_ORGS`` env var into a list of org slugs.

    Shared by :func:`_validate` and
    :func:`~distillery.mcp.auth.build_org_checker` to avoid duplicating
    the parsing logic.
    """
    return [
        org.strip()
        for org in os.environ.get("DISTILLERY_ALLOWED_ORGS", "").split(",")
        if org.strip()
    ]


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
            - feeds.thresholds.alert is not between 0.0 and 1.0.
            - feeds.thresholds.digest is not between 0.0 and 1.0.
            - feeds.thresholds.digest exceeds feeds.thresholds.alert.
    """
    valid_backends = {"duckdb", "motherduck"}
    if config.storage.backend not in valid_backends:
        raise ValueError(
            f"storage.backend must be one of {sorted(valid_backends)}, "
            f"got: {config.storage.backend!r}"
        )

    if config.storage.backend == "motherduck":
        if not config.storage.database_path.startswith("md:"):
            raise ValueError(
                "storage.database_path must start with 'md:' when backend is 'motherduck', "
                f"got: {config.storage.database_path!r}"
            )
        token_env = config.storage.motherduck_token_env
        if not os.environ.get(token_env):
            raise ValueError(
                f"MotherDuck token env var {token_env!r} is not set. "
                "Set the environment variable before starting the server."
            )

    valid_providers = {"jina", "openai", "mock"}
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

    # Validate feeds thresholds.
    alert = config.feeds.thresholds.alert
    digest = config.feeds.thresholds.digest
    if not (0.0 <= alert <= 1.0):
        raise ValueError(f"feeds.thresholds.alert must be between 0.0 and 1.0, got: {alert}")
    if not (0.0 <= digest <= 1.0):
        raise ValueError(f"feeds.thresholds.digest must be between 0.0 and 1.0, got: {digest}")
    if digest > alert:
        raise ValueError(
            f"feeds.thresholds.digest ({digest}) must not exceed feeds.thresholds.alert ({alert})"
        )

    # Validate rate_limit settings.
    rl = config.rate_limit
    if rl.embedding_budget_daily < 0:
        raise ValueError(
            "rate_limit.embedding_budget_daily must be >= 0 (0 = unlimited), "
            f"got: {rl.embedding_budget_daily}"
        )
    if rl.max_db_size_mb < 0:
        raise ValueError(
            f"rate_limit.max_db_size_mb must be >= 0 (0 = unlimited), got: {rl.max_db_size_mb}"
        )
    if not (0 <= rl.warn_db_size_pct <= 100):
        raise ValueError(
            f"rate_limit.warn_db_size_pct must be between 0 and 100, got: {rl.warn_db_size_pct}"
        )

    # Validate server.auth.provider
    valid_auth_providers = {"github", "none"}
    if config.server.auth.provider not in valid_auth_providers:
        raise ValueError(
            f"server.auth.provider must be one of {sorted(valid_auth_providers)}, "
            f"got: {config.server.auth.provider!r}"
        )

    # Validate allowed_orgs: non-empty list requires GitHub auth provider.
    if (
        config.server.auth.allowed_orgs or parse_env_allowed_orgs()
    ) and config.server.auth.provider != "github":
        raise ValueError(
            "server.auth.allowed_orgs requires server.auth.provider = 'github', "
            f"got: {config.server.auth.provider!r}"
        )

    if config.server.auth.membership_cache_ttl_seconds <= 0:
        raise ValueError(
            "server.auth.membership_cache_ttl_seconds must be a positive integer, "
            f"got: {config.server.auth.membership_cache_ttl_seconds}"
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
    defaults_raw = raw.get("defaults", {}) or {}
    classification_raw = raw.get("classification", {}) or {}
    tags_raw = raw.get("tags", {}) or {}
    feeds_raw = raw.get("feeds", {}) or {}
    rate_limit_raw = raw.get("rate_limit", {}) or {}
    server_raw = raw.get("server", {})
    if server_raw is None:
        server_raw = {}

    config = DistilleryConfig(
        storage=_parse_storage(storage_raw),
        embedding=_parse_embedding(embedding_raw),
        team=_parse_team(team_raw),
        defaults=_parse_defaults(defaults_raw),
        classification=_parse_classification(classification_raw),
        tags=_parse_tags(tags_raw),
        feeds=_parse_feeds(feeds_raw),
        rate_limit=_parse_rate_limit(rate_limit_raw),
        server=_parse_server(server_raw),
    )

    _validate(config)
    return config
