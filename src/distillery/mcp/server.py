"""MCP server implementation for Distillery.

Exposes storage operations as MCP tools using the stdio transport.
On startup, initializes DuckDBStore and EmbeddingProvider from distillery.yaml config.

Tools implemented here (T04.1):
  - distillery_status: Returns DB stats (total entries, by type, by status,
    database size, embedding model in use).

Tools added in T04.2:
  - distillery_store: Accept content, entry_type, author, project, tags,
    metadata; store in DB; run find_similar for dedup warnings; return entry
    ID and any warnings.
  - distillery_get: Accept entry_id; return full entry or structured error.
  - distillery_update: Accept entry_id and fields to update; return updated
    entry or structured error.

Tools added in T04.3:
  - distillery_search: Accept query string, optional filters, optional limit
    (default 10); returns entries with cosine similarity scores.
  - distillery_find_similar: Accept content string and optional threshold
    (default 0.8); returns similar entries with scores for deduplication.
  - distillery_list: Accept optional filters, limit, offset; returns entries
    without semantic ranking (newest first).

Tools added in T02 (classification extensions):
  - distillery_classify: Accept entry_id and pre-computed classification
    result fields; persist classification metadata onto the entry and update
    its status according to confidence threshold.
  - distillery_review_queue: Return pending_review entries sorted by
    created_at desc with id, content preview, entry_type, confidence, author,
    created_at, and classification_reasoning.
  - distillery_resolve_review: Accept entry_id and action
    (approve/reclassify/archive); update entry accordingly.

Tools added in T03.2 (conflict detection):
  - distillery_check_conflicts: Accept content and optional llm_responses
    mapping.  First pass (no llm_responses) returns conflict_candidates with
    prompts for LLM evaluation.  Second pass (with llm_responses) processes
    evaluated responses and returns has_conflicts + conflict list.
  - distillery_store also returns conflict_candidates on the response when
    similar entries exceed the conflict_threshold, enabling the calling LLM
    to evaluate conflicts without a separate tool call.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastmcp import Context, FastMCP  # noqa: F401  # Context used by tool wrappers added in T02
from mcp import types

from distillery.config import DistilleryConfig, load_config
from distillery.mcp.tools.analytics import (
    _handle_interests,
    _handle_metrics,
    _handle_quality,
    _handle_stale,
    _handle_tag_tree,
    _handle_type_schemas,
)
from distillery.mcp.tools.classify import (
    _handle_classify,
    _handle_resolve_review,
    _handle_review_queue,
)
from distillery.mcp.tools.crud import (
    _DEFAULT_DEDUP_LIMIT,
    _DEFAULT_DEDUP_THRESHOLD,
    _handle_get,
    _handle_list,
    _handle_status,
    _handle_store,
    _handle_update,
)
from distillery.mcp.tools.quality import (
    _handle_check_conflicts,
    _handle_check_dedup,
)
from distillery.mcp.tools.search import (
    _handle_aggregate,
    _handle_find_similar,
    _handle_search,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# User identity helpers
# ---------------------------------------------------------------------------

def _get_authenticated_user() -> str:  # pragma: no cover — requires live OAuth context
    """Return the authenticated GitHub username, or ``""`` if auth is not active.

    Uses FastMCP's ``get_access_token()`` to retrieve the current request's
    access token.  The GitHub username is extracted from the JWT claims
    (``login`` field populated by the GitHubProvider).

    Returns ``""`` only when no auth is configured (stdio transport or
    ``auth=None``).  When a token is present but identity cannot be
    resolved, raises ``RuntimeError`` to fail closed rather than silently
    treating an authenticated-but-unresolvable request as anonymous.
    """
    try:
        from fastmcp.server.dependencies import get_access_token
    except ImportError:
        return ""

    token = get_access_token()
    if token is None:
        return ""

    # Extract username from claims.  Validate type to avoid str(None) → "None".
    raw_login = token.claims.get("login")
    if isinstance(raw_login, str) and raw_login:
        return raw_login

    raw_sub = token.claims.get("sub")
    if isinstance(raw_sub, str) and raw_sub:
        return raw_sub

    # Token present but no valid identity claim — fail closed.
    raise RuntimeError(
        "Authenticated request has no 'login' or 'sub' claim in access token. "
        "Cannot determine user identity for ownership checks."
    )


# ---------------------------------------------------------------------------
# Error response helpers
# ---------------------------------------------------------------------------


def error_response(
    code: str, message: str, details: dict[str, Any] | None = None
) -> list[types.TextContent]:
    """Build a structured error response as MCP content.

    Args:
        code: Short machine-readable error code (e.g. ``"NOT_FOUND"``).
        message: Human-readable error description.
        details: Optional extra context dict.

    Returns:
        A single-element list of :class:`~mcp.types.TextContent` with a JSON payload.
    """
    from distillery.security import sanitize_error

    message = sanitize_error(message)
    payload: dict[str, Any] = {"error": True, "code": code, "message": message}
    if details:
        payload["details"] = details
    return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]


def success_response(data: dict[str, Any]) -> list[types.TextContent]:
    """Build a structured success response as MCP content.

    Args:
        data: Payload to serialise as JSON.

    Returns:
        A single-element list of :class:`~mcp.types.TextContent`.
    """
    return [types.TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------------------
# Storage path helpers
# ---------------------------------------------------------------------------


def _is_remote_db_path(path: str) -> bool:
    """Return True for S3 or MotherDuck URIs that should not be treated as local paths."""
    return path.startswith("s3://") or path.startswith("md:")


def _normalize_db_path(raw: str) -> str:
    """Expand ``~`` for local paths; leave cloud URIs (S3/MotherDuck) untouched."""
    if _is_remote_db_path(raw):
        return raw
    return os.path.expanduser(raw)


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------


def validate_required(arguments: dict[str, Any], *fields: str) -> str | None:
    """Return an error message if any required field is missing from *arguments*.

    Args:
        arguments: The tool argument dict.
        *fields: Field names that must be present and non-empty.

    Returns:
        An error message string if validation fails, or ``None`` if all fields
        are present.
    """
    missing = [f for f in fields if not arguments.get(f)]
    if missing:
        return f"Missing required fields: {', '.join(missing)}"
    return None


def validate_type(
    arguments: dict[str, Any], field: str, expected_type: type | tuple[type, ...], label: str
) -> str | None:
    """Return an error message if *field* is not of *expected_type*.

    Args:
        arguments: The tool argument dict.
        field: Key to check.
        expected_type: Python type that the value must satisfy.
        label: Human-readable type name for the error message.

    Returns:
        An error message string or ``None``.
    """
    value = arguments.get(field)
    if value is not None and not isinstance(value, expected_type):
        return f"Field '{field}' must be a {label}"
    return None


# ---------------------------------------------------------------------------
# Store & embedding factory helpers
# ---------------------------------------------------------------------------


def _create_embedding_provider(config: DistilleryConfig) -> Any:
    """Instantiate an EmbeddingProvider based on config.

    Args:
        config: Loaded :class:`~distillery.config.DistilleryConfig`.

    Returns:
        An object satisfying the ``EmbeddingProvider`` protocol.

    Raises:
        ValueError: If the configured provider is unsupported or the API key is
            missing.
    """
    provider_name = config.embedding.provider
    model = config.embedding.model
    dimensions = config.embedding.dimensions
    api_key_env = config.embedding.api_key_env

    api_key: str | None = None
    if api_key_env:
        api_key = os.environ.get(api_key_env)

    if provider_name == "jina":
        from distillery.embedding.jina import JinaEmbeddingProvider

        return JinaEmbeddingProvider(
            api_key=api_key,
            api_key_env=api_key_env or "JINA_API_KEY",
            model=model,
            dimensions=dimensions,
        )
    elif provider_name == "openai":
        from distillery.embedding.openai import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider(
            api_key=api_key,
            api_key_env=api_key_env or "OPENAI_API_KEY",
            model=model,
            dimensions=dimensions,
        )
    elif provider_name == "mock":
        # Hash-based mock provider -- deterministic, no API calls, functional
        # search via cosine similarity.  Used by eval scenarios and local dev.
        from distillery.mcp._stub_embedding import HashEmbeddingProvider

        return HashEmbeddingProvider(dimensions=dimensions)
    elif provider_name == "":
        # No provider configured -- return a lightweight stub used for testing
        # and status-only operations.
        from distillery.mcp._stub_embedding import StubEmbeddingProvider

        return StubEmbeddingProvider(dimensions=dimensions)
    else:
        raise ValueError(
            f"Unsupported embedding provider: {provider_name!r}. "
            "Must be one of: 'jina', 'openai', 'mock'."
        )


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_server(
    config: DistilleryConfig | None = None,
    auth: Any | None = None,
) -> FastMCP:
    """Build and return the configured :class:`~fastmcp.FastMCP` server.

    The server is stateless at construction time -- the store and embedding
    provider are initialised during the lifespan context manager when the
    stdio transport connects.

    Args:
        config: Pre-loaded configuration.  When ``None`` the config is loaded
            from the standard locations (``DISTILLERY_CONFIG`` env var, then
            ``distillery.yaml`` in the cwd).
        auth: Optional authentication provider (e.g. ``GitHubProvider``) to
            pass to ``FastMCP``.  When ``None`` no authentication is required.

    Returns:
        A fully decorated :class:`~fastmcp.FastMCP` instance ready to run.
    """
    if config is None:
        config = load_config()

    # Shared singleton state for the store, embedding provider, and recent
    # searches.  In stateless HTTP mode (FastMCP Cloud / Prefect Horizon)
    # every request spawns a new lifespan.  DuckDB does not allow multiple
    # connections to the same file from the same process, so we initialise
    # once and reuse across all sessions.
    _shared: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        """
        Manage the startup and shutdown lifecycle for the Distillery MCP server.

        On first invocation the store, embedding provider, and config are
        initialised and cached in ``_shared``.  Subsequent invocations (from
        stateless HTTP sessions) reuse the same objects so DuckDB doesn't
        raise file-handle conflicts.

        Yields:
            A lifespan context dict with:
              - "store": an initialized DuckDBStore instance.
              - "config": the Distillery configuration.
              - "embedding_provider": the embedding provider instance.
              - (implicit feedback correlation now uses search_log directly)
        """
        if not _shared:
            logger.info("Distillery MCP server starting up …")

            embedding_provider = _create_embedding_provider(config)
            db_path = _normalize_db_path(config.storage.database_path)

            # Apply MotherDuck token from the configured env var name if set.
            if db_path.startswith("md:"):
                token = os.environ.get(config.storage.motherduck_token_env)
                if token:
                    os.environ["MOTHERDUCK_TOKEN"] = token
                else:
                    logger.warning(
                        "motherduck_token_env is set to %r but the environment variable is not set",
                        config.storage.motherduck_token_env,
                    )

            from distillery.store.duckdb import DuckDBStore

            store = DuckDBStore(
                db_path=db_path,
                embedding_provider=embedding_provider,
                s3_region=config.storage.s3_region,
                s3_endpoint=config.storage.s3_endpoint,
            )
            await store.initialize()

            # Seed YAML feed sources into DB exactly once.  After the first
            # successful seed we write a persistent sentinel so restarts never
            # re-insert sources — even when the user has /watch-removed them
            # all and the feed_sources table is empty.
            if await store.get_metadata("feeds_seeded") != "true":
                for source in config.feeds.sources:
                    with contextlib.suppress(ValueError):
                        await store.add_feed_source(
                            url=source.url,
                            source_type=source.source_type,
                            label=source.label,
                            poll_interval_minutes=source.poll_interval_minutes,
                            trust_weight=source.trust_weight,
                        )
                await store.set_metadata("feeds_seeded", "true")

            _shared["store"] = store
            _shared["config"] = config
            _shared["embedding_provider"] = embedding_provider

            logger.info(
                "Distillery MCP server ready (db=%s, embedding=%s)",
                db_path,
                getattr(embedding_provider, "model_name", "unknown"),
            )
        else:
            logger.debug("Reusing existing Distillery store (stateless session)")

        try:
            yield dict(_shared)
        finally:
            # In stateless mode many sessions share the store — only the
            # process-level shutdown should close it.  For stdio mode (single
            # session) this runs once at exit and is fine.
            pass

    server = FastMCP("distillery", lifespan=lifespan, auth=auth)
    server._distillery_shared = _shared  # type: ignore[attr-defined]

    def _get_lifespan_context(ctx: Context) -> dict[str, Any]:
        """Extract the lifespan context dict from a FastMCP Context.

        Supports both FastMCP 3.x (``ctx.lifespan_context``) and 2.x
        (``ctx.request_context.lifespan_context``) attribute paths.
        """
        # FastMCP 3.x exposes a top-level property.
        try:
            lc = ctx.lifespan_context
            if isinstance(lc, dict):
                return lc
        except AttributeError:
            pass
        # FastMCP 2.x: traverse through request_context.
        rc = getattr(ctx, "request_context", None)
        if rc is not None:
            lc_v2 = getattr(rc, "lifespan_context", None)
            if lc_v2 is not None and isinstance(lc_v2, dict):
                return cast(dict[str, Any], lc_v2)
        raise RuntimeError("Cannot access lifespan context — verify FastMCP version compatibility.")

    # -----------------------------------------------------------------------
    # T02.1 tool wrappers: distillery_status, distillery_store,
    # distillery_get, distillery_update, distillery_list
    # -----------------------------------------------------------------------

    @server.tool
    async def distillery_status(ctx: Context) -> list[types.TextContent]:
        """
        Retrieve database and embedding model statistics for the Distillery store.

        Returns aggregate counts (total entries, counts by type and status), database file size (or `None` for in-memory DBs), and embedding model metadata (model name and dimensions).

        Returns:
            list[types.TextContent]: A single-element list containing a TextContent block with a JSON-serializable dictionary of statistics (e.g., `entries`, `entries_by_type`, `entries_by_status`, `db_size_bytes`, `embedding_model`, and `status`).
        """
        lc = _get_lifespan_context(ctx)
        return await _handle_status(
            store=lc["store"],
            embedding_provider=lc["embedding_provider"],
            config=lc["config"],
        )

    @server.tool
    async def distillery_store(  # noqa: PLR0913
        ctx: Context,
        content: str,
        entry_type: str,
        author: str,
        project: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        dedup_threshold: float = _DEFAULT_DEDUP_THRESHOLD,
        dedup_limit: int = _DEFAULT_DEDUP_LIMIT,
    ) -> list[types.TextContent]:
        """
        Store a new knowledge entry and return the created entry ID with optional deduplication and conflict information.

        Creates and persists an entry from the provided content and metadata, performs non-fatal deduplication and conflict checks, and returns a single MCP TextContent block containing a JSON-serializable response.

        Parameters:
            entry_type (str): One of: "session", "bookmark", "minutes", "meeting", "reference", "idea", "inbox".
            dedup_threshold (float): Similarity threshold (0.0–1.0) used to surface near-duplicate warnings.
            dedup_limit (int): Maximum number of deduplication warnings to include.

        Returns:
            list[types.TextContent]: A one-element list with a TextContent block whose JSON object contains:
                - On success: "entry_id" and optionally "warnings" (list), "warning_message", and conflict-related keys
                  such as "conflict_message" and "conflict_candidates".
                - On validation or persistence failures: an error object with "error", "code", and "message".
        """
        lc = _get_lifespan_context(ctx)
        arguments: dict[str, Any] = {
            "content": content,
            "entry_type": entry_type,
            "author": author,
        }
        if project is not None:
            arguments["project"] = project
        if tags is not None:
            arguments["tags"] = tags
        if metadata is not None:
            arguments["metadata"] = metadata
        arguments["dedup_threshold"] = dedup_threshold
        arguments["dedup_limit"] = dedup_limit
        user = _get_authenticated_user()
        result = await _handle_store(
            store=lc["store"],
            arguments=arguments,
            cfg=lc["config"],
            created_by=user,
        )
        # Audit log (best-effort, never masks the result).
        try:
            response_data = json.loads(result[0].text) if result else {}
            eid = response_data.get("entry_id", "")
            outcome = "error" if response_data.get("error") else "success"
            await lc["store"].write_audit_log(user, "distillery_store", eid, "store", outcome)
        except Exception:  # noqa: BLE001
            logger.debug("audit_log write failed for distillery_store (ignored)", exc_info=True)
        return result

    @server.tool
    async def distillery_get(
        ctx: Context,
        entry_id: str,
    ) -> list[types.TextContent]:
        """
        Retrieve a knowledge entry by ID.

        If the entry is found, returns a single TextContent block containing the entry's serialized dictionary. If this retrieval follows a recent search that returned the entry, an implicit positive feedback event is recorded. If no entry exists with the given ID, an error block with code "NOT_FOUND" is returned.

        Parameters:
            entry_id (str): The identifier of the entry to retrieve.

        Returns:
            list[types.TextContent]: A one-element list containing either the serialized entry dict on success or an error object with code `"NOT_FOUND"` if the entry is missing.
        """
        lc = _get_lifespan_context(ctx)
        return await _handle_get(
            store=lc["store"],
            arguments={"entry_id": entry_id},
            config=lc["config"],
        )

    @server.tool
    async def distillery_update(  # noqa: PLR0913
        ctx: Context,
        entry_id: str,
        content: str | None = None,
        entry_type: str | None = None,
        author: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[types.TextContent]:
        """Update one or more fields on an existing knowledge entry.

        At least one of content, entry_type, author, project, tags, status, or
        metadata must be supplied.  Immutable fields (id, created_at, source)
        are rejected.

        status must be one of: active, pending_review, archived.
        entry_type must be one of: session, bookmark, minutes, meeting,
        reference, idea, inbox.
        """
        lc = _get_lifespan_context(ctx)
        user = _get_authenticated_user()

        # Ownership check: if auth is active, verify the caller owns the entry.
        if user:
            try:
                existing = await lc["store"].get(entry_id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Ownership pre-check failed for entry %s", entry_id)
                return error_response("STORE_ERROR", f"Failed to read entry: {exc}")
            if existing is None:
                await lc["store"].write_audit_log(
                    user, "distillery_update", entry_id, "update", "not_found",
                )
                return error_response("NOT_FOUND", f"No entry found with id={entry_id!r}.")
            if existing.created_by and existing.created_by != user:
                await lc["store"].write_audit_log(
                    user, "distillery_update", entry_id, "update", "forbidden",
                )
                return error_response(
                    "FORBIDDEN",
                    f"User {user!r} cannot modify entry owned by {existing.created_by!r}.",
                )

        arguments: dict[str, Any] = {"entry_id": entry_id}
        if content is not None:
            arguments["content"] = content
        if entry_type is not None:
            arguments["entry_type"] = entry_type
        if author is not None:
            arguments["author"] = author
        if project is not None:
            arguments["project"] = project
        if tags is not None:
            arguments["tags"] = tags
        if status is not None:
            arguments["status"] = status
        if metadata is not None:
            arguments["metadata"] = metadata
        result = await _handle_update(
            store=lc["store"],
            arguments=arguments,
            last_modified_by=user,
        )
        # Audit log (best-effort).
        try:
            response_data = json.loads(result[0].text) if result else {}
            outcome = "error" if response_data.get("error") else "success"
            await lc["store"].write_audit_log(
                user, "distillery_update", entry_id, "update", outcome,
            )
        except Exception:  # noqa: BLE001
            logger.debug("audit_log write failed for distillery_update (ignored)", exc_info=True)
        return result

    @server.tool
    async def distillery_list(  # noqa: PLR0913
        ctx: Context,
        entry_type: str | None = None,
        author: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
        offset: int = 0,
        tag_prefix: str | None = None,
        output_mode: str = "full",
        content_max_length: int | None = None,
    ) -> list[types.TextContent]:
        """
        List knowledge entries with optional filters and pagination.

        Returns entries ordered by creation time (newest first). Filtering is exact-match for
        string fields; `tags` should be a list of tag strings. `date_from` and `date_to`
        accept ISO 8601 date strings (e.g. "2024-01-15") and are used to filter by
        creation date (inclusive).

        Parameters:
            date_from (str | None): ISO 8601 start date to include (inclusive).
            date_to (str | None): ISO 8601 end date to include (inclusive).
            tags (list[str] | None): List of tag strings to filter by.
            tag_prefix (str | None): Namespace prefix filter — returns only entries whose
                tags fall under this prefix (e.g. "source/bookmark" matches
                "source/bookmark/rss" but not "source/bookmark-old").
            output_mode (str): Controls how much data is returned per entry. One of:
                "full" (default) — all fields including content;
                "summary" — all fields except content (metadata, tags, timestamps);
                "ids" — id, entry_type, and created_at only.
            content_max_length (int | None): When output_mode is "full", truncates the
                content field to this many characters (appends "…" if truncated).
                Default None means no truncation.

        Returns:
            list[types.TextContent]: MCP TextContent blocks containing a JSON object with
            keys "entries" (list of entry dicts), "count" (total matching entries),
            "limit", and "offset".
        """
        lc = _get_lifespan_context(ctx)
        arguments: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "output_mode": output_mode,
        }
        if entry_type is not None:
            arguments["entry_type"] = entry_type
        if author is not None:
            arguments["author"] = author
        if project is not None:
            arguments["project"] = project
        if tags is not None:
            arguments["tags"] = tags
        if status is not None:
            arguments["status"] = status
        if date_from is not None:
            arguments["date_from"] = date_from
        if date_to is not None:
            arguments["date_to"] = date_to
        if tag_prefix is not None:
            arguments["tag_prefix"] = tag_prefix
        if content_max_length is not None:
            arguments["content_max_length"] = content_max_length
        return await _handle_list(
            store=lc["store"],
            arguments=arguments,
        )

    @server.tool
    async def distillery_aggregate(  # noqa: PLR0913
        ctx: Context,
        group_by: str,
        entry_type: str | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        tag_prefix: str | None = None,
        limit: int = 50,
    ) -> list[types.TextContent]:
        """
        Aggregate entry counts grouped by a field.

        Returns count-by-group results without fetching full entry payloads.
        Useful for answering "how many entries per source?" style questions.

        Parameters:
            group_by (str): Field to group by. Supported values:
                "entry_type", "status", "author", "project", "source",
                "metadata.source_url", "metadata.source_type".
            entry_type (str | None): Filter to a specific entry type.
            status (str | None): Filter to a specific status.
            date_from (str | None): ISO 8601 start date (inclusive).
            date_to (str | None): ISO 8601 end date (inclusive).
            tag_prefix (str | None): Filter to entries whose tags fall under this prefix.
            limit (int): Maximum number of groups to return (default 50).

        Returns:
            list[types.TextContent]: JSON with "group_by", "groups" (list of
            {value, count}), "total_entries", and "total_groups".
        """
        lc = _get_lifespan_context(ctx)
        arguments: dict[str, Any] = {"group_by": group_by, "limit": limit}
        if entry_type is not None:
            arguments["entry_type"] = entry_type
        if status is not None:
            arguments["status"] = status
        if date_from is not None:
            arguments["date_from"] = date_from
        if date_to is not None:
            arguments["date_to"] = date_to
        if tag_prefix is not None:
            arguments["tag_prefix"] = tag_prefix
        return await _handle_aggregate(
            store=lc["store"],
            arguments=arguments,
        )

    # -----------------------------------------------------------------------
    # T02.2 tool wrappers: distillery_search, distillery_find_similar,
    # distillery_classify, distillery_review_queue, distillery_resolve_review,
    # distillery_check_dedup, distillery_check_conflicts
    # -----------------------------------------------------------------------

    @server.tool
    async def distillery_search(  # noqa: PLR0913
        ctx: Context,
        query: str,
        entry_type: str | None = None,
        author: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
        tag_prefix: str | None = None,
    ) -> list[types.TextContent]:
        """Search the knowledge store using semantic similarity.

        Embeds the query and returns entries ranked by cosine similarity
        descending, with optional metadata filters applied.  After returning
        results the search event is logged for implicit feedback correlation.

        All filter parameters are optional.  date_from and date_to accept
        ISO 8601 date strings (e.g. "2024-01-15").
        limit must be between 1 and 200 (default 10).
        tag_prefix filters to entries whose tags fall under that namespace
        prefix (e.g. "domain/architecture" matches "domain/architecture/api"
        but not "domain/architecture-old").
        """
        lc = _get_lifespan_context(ctx)
        arguments: dict[str, Any] = {"query": query, "limit": limit}
        if entry_type is not None:
            arguments["entry_type"] = entry_type
        if author is not None:
            arguments["author"] = author
        if project is not None:
            arguments["project"] = project
        if tags is not None:
            arguments["tags"] = tags
        if status is not None:
            arguments["status"] = status
        if date_from is not None:
            arguments["date_from"] = date_from
        if date_to is not None:
            arguments["date_to"] = date_to
        if tag_prefix is not None:
            arguments["tag_prefix"] = tag_prefix
        return await _handle_search(
            store=lc["store"],
            arguments=arguments,
            cfg=lc["config"],
        )

    @server.tool
    async def distillery_find_similar(
        ctx: Context,
        content: str,
        threshold: float = 0.8,
        limit: int = 10,
    ) -> list[types.TextContent]:
        """
        Find stored entries whose content is similar to the provided text.

        Parameters:
            ctx (Context): MCP invocation context (provides lifespan state).
            content (str): Text to compare against stored entries.
            threshold (float): Similarity cutoff in the range 0.0 to 1.0 (default 0.8).
            limit (int): Maximum number of results to return, between 1 and 200 (default 10).

        Returns:
            list[types.TextContent]: A single MCP TextContent block containing a JSON object with keys:
                - `results`: list of `{score, entry}` objects (scores rounded, entries serialized),
                - `count`: total number of matches returned,
                - `threshold`: the similarity threshold used.
        """
        lc = _get_lifespan_context(ctx)
        return await _handle_find_similar(
            store=lc["store"],
            arguments={"content": content, "threshold": threshold, "limit": limit},
            cfg=lc["config"],
        )

    @server.tool
    async def distillery_classify(  # noqa: PLR0913
        ctx: Context,
        entry_id: str,
        entry_type: str,
        confidence: float,
        reasoning: str | None = None,
        suggested_tags: list[str] | None = None,
        suggested_project: str | None = None,
    ) -> list[types.TextContent]:
        """
        Apply a pre-computed classification to an existing entry and persist the resulting updates.

        Parameters:
            entry_type (str): New entry type; must be one of: "session", "bookmark", "minutes", "meeting", "reference", "idea", "inbox".
            confidence (float): Classification confidence between 0.0 and 1.0 inclusive; used to determine the updated entry status.

        Returns:
            list[types.TextContent]: A single MCP TextContent block containing the serialized updated entry or an error payload.
        """
        lc = _get_lifespan_context(ctx)
        arguments: dict[str, Any] = {
            "entry_id": entry_id,
            "entry_type": entry_type,
            "confidence": confidence,
        }
        if reasoning is not None:
            arguments["reasoning"] = reasoning
        if suggested_tags is not None:
            arguments["suggested_tags"] = suggested_tags
        if suggested_project is not None:
            arguments["suggested_project"] = suggested_project
        return await _handle_classify(
            store=lc["store"],
            config=lc["config"],
            arguments=arguments,
        )

    @server.tool
    async def distillery_review_queue(
        ctx: Context,
        entry_type: str | None = None,
        limit: int = 20,
    ) -> list[types.TextContent]:
        """
        List entries awaiting human review after classification.

        Parameters:
            entry_type (str | None): If provided, filter results to this entry type.
            limit (int): Maximum number of entries to return; must be between 1 and 500.

        Returns:
            list[types.TextContent]: A single-element MCP text content payload containing a JSON object with:
                - entries: list of review items each containing `id`, `content_preview` (first 200 chars),
                  `entry_type`, `confidence` (from metadata), `author`, `created_at` (ISO string),
                  and `classification_reasoning` (if present).
                - count: total number of entries returned.
        """
        lc = _get_lifespan_context(ctx)
        arguments: dict[str, Any] = {"limit": limit}
        if entry_type is not None:
            arguments["entry_type"] = entry_type
        return await _handle_review_queue(
            store=lc["store"],
            arguments=arguments,
        )

    @server.tool
    async def distillery_resolve_review(  # noqa: PLR0913
        ctx: Context,
        entry_id: str,
        action: str,
        new_entry_type: str | None = None,
        reviewer: str | None = None,
    ) -> list[types.TextContent]:
        """
        Resolve a pending-review entry by approving, reclassifying, or archiving.

        Performs one of three actions on the entry identified by `entry_id`:
        - "approve": sets status to active and records `reviewed_at` (and `reviewed_by` if `reviewer` provided) in metadata.
        - "reclassify": requires `new_entry_type`; updates the entry's type, records `reclassified_from` and `reviewed_at` (and `reviewed_by` if provided) in metadata.
        - "archive": sets status to archived and records archival metadata.

        Parameters:
            entry_id (str): ID of the entry to update.
            action (str): One of "approve", "reclassify", or "archive".
            new_entry_type (str | None): Required when `action` is "reclassify". Must be one of: "session", "bookmark", "minutes", "meeting", "reference", "idea", "inbox".
            reviewer (str | None): Optional identifier of the reviewer to record as `reviewed_by`.

        Returns:
            list[types.TextContent]: A one-element MCP TextContent list containing the updated entry as a JSON-serializable object on success, or an error payload on failure.
        """
        lc = _get_lifespan_context(ctx)
        user = _get_authenticated_user()

        # Ownership check: if auth is active, verify the caller owns the entry.
        if user:
            try:
                existing = await lc["store"].get(entry_id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Ownership pre-check failed for entry %s", entry_id)
                return error_response("STORE_ERROR", f"Failed to read entry: {exc}")
            if existing is None:
                await lc["store"].write_audit_log(
                    user, "distillery_resolve_review", entry_id, action, "not_found",
                )
                return error_response("NOT_FOUND", f"No entry found with id={entry_id!r}.")
            if existing.created_by and existing.created_by != user:
                await lc["store"].write_audit_log(
                    user, "distillery_resolve_review", entry_id, action, "forbidden",
                )
                return error_response(
                    "FORBIDDEN",
                    f"User {user!r} cannot modify entry owned by {existing.created_by!r}.",
                )

        arguments: dict[str, Any] = {"entry_id": entry_id, "action": action}
        if new_entry_type is not None:
            arguments["new_entry_type"] = new_entry_type
        # When auth is active, override caller-supplied reviewer with the
        # authenticated identity to prevent spoofing reviewed_by metadata.
        if user:
            arguments["reviewer"] = user
        elif reviewer is not None:
            arguments["reviewer"] = reviewer
        result = await _handle_resolve_review(
            store=lc["store"],
            arguments=arguments,
        )
        # Audit log (best-effort).
        try:
            response_data = json.loads(result[0].text) if result else {}
            outcome = "error" if response_data.get("error") else "success"
            await lc["store"].write_audit_log(
                user, "distillery_resolve_review", entry_id, action, outcome,
            )
        except Exception:  # noqa: BLE001
            logger.debug("audit_log write failed for resolve_review (ignored)", exc_info=True)
        return result

    @server.tool
    async def distillery_check_dedup(
        ctx: Context,
        content: str,
    ) -> list[types.TextContent]:
        """
        Perform a deduplication check of the given content against the store.

        Runs the configured deduplication logic and returns a serialized response describing the recommended action and matching entries.

        Parameters:
            content (str): The text to check for duplicates.

        Returns:
            list[types.TextContent]: A single-element list whose JSON payload contains:
                - action (str): One of `store`, `skip`, `merge`, or `link`.
                - highest_score (float): Highest similarity score found.
                - reasoning (str): Human-readable explanation for the chosen action.
                - similar_entries (list): List of matches; each item is a dict with
                  `id`, `score` (float), `content_preview` (str, up to 120 chars),
                  `entry_type`, `author`, `project`, and `created_at` (ISO string or None).
        """
        lc = _get_lifespan_context(ctx)
        return await _handle_check_dedup(
            store=lc["store"],
            config=lc["config"],
            arguments={"content": content},
        )

    @server.tool
    async def distillery_check_conflicts(
        ctx: Context,
        content: str,
        llm_responses: dict[str, Any] | None = None,
    ) -> list[types.TextContent]:
        """
        Check for potential conflicts between the provided content and existing knowledge-store entries.

        Supports a two-pass workflow:
        - First pass (no `llm_responses`): returns `conflict_candidates` with a `conflict_prompt` for each similar entry so an external LLM can evaluate whether it is a conflict.
        - Second pass (with `llm_responses`): accepts a mapping `{entry_id: {"is_conflict": bool, "reasoning": str}}` and returns `has_conflicts` plus a list of confirmed `conflicts` with reasoning.

        Parameters:
            content (str): The content to check for conflicts against stored entries.
            llm_responses (dict[str, Any] | None): Optional mapping of LLM evaluations for candidates (present only in the second pass).

        Returns:
            list[types.TextContent]: A single MCP `TextContent` block containing a JSON-serializable payload. In the first pass the payload includes `conflict_candidates` (and guidance); in the second pass it includes `has_conflicts` and `conflicts` (confirmed items with reasoning).
        """
        lc = _get_lifespan_context(ctx)
        arguments: dict[str, Any] = {"content": content}
        if llm_responses is not None:
            arguments["llm_responses"] = llm_responses
        return await _handle_check_conflicts(
            store=lc["store"],
            config=lc["config"],
            arguments=arguments,
        )

    # -----------------------------------------------------------------------
    # T02.3 tool wrappers: distillery_metrics, distillery_quality,
    # distillery_stale
    # -----------------------------------------------------------------------

    @server.tool
    async def distillery_metrics(
        ctx: Context,
        period_days: int = 30,
    ) -> list[types.TextContent]:
        """
        Provide usage metrics and statistics for the Distillery knowledge store.

        Aggregates entry counts, activity windows, search and feedback summaries, staleness and storage information for the past `period_days`.

        Parameters:
            period_days (int): Number of days to include in period-specific metrics; must be >= 1.

        Returns:
            list[types.TextContent]: A one-element list containing a TextContent block with a JSON-serializable dict of metrics (keys include `entries`, `activity`, `search`, `quality`, `staleness`, and `storage`).
        """
        lc = _get_lifespan_context(ctx)
        return await _handle_metrics(
            store=lc["store"],
            config=lc["config"],
            embedding_provider=lc["embedding_provider"],
            arguments={"period_days": period_days},
        )

    @server.tool
    async def distillery_quality(
        ctx: Context,
        entry_type: str | None = None,
    ) -> list[types.TextContent]:
        """
        Retrieve aggregated search-quality metrics from the Distillery store.

        Aggregates counts from `search_log` and `feedback_log` and computes totals and rates such as total searches, total feedback, positive feedback rate, and average result count. When `entry_type` is provided, metrics are filtered to that entry type if supported.

        Parameters:
            entry_type (str | None): Optional entry type to filter metrics by.

        Returns:
            list[types.TextContent]: A one-element MCP `TextContent` list containing a JSON-serializable object with metrics (totals, rates, and optional per-type breakdown).
        """
        lc = _get_lifespan_context(ctx)
        arguments: dict[str, Any] = {}
        if entry_type is not None:
            arguments["entry_type"] = entry_type
        return await _handle_quality(
            store=lc["store"],
            arguments=arguments,
        )

    @server.tool
    async def distillery_stale(
        ctx: Context,
        days: int | None = None,
        limit: int = 20,
        entry_type: str | None = None,
    ) -> list[types.TextContent]:
        """
        Return a list of entries that are considered stale based on last access time.

        If `days` is omitted, the server configuration's `classification.stale_days` is used. `limit` must be >= 1 and bounds the number of returned entries. When provided, `entry_type` restricts results to that entry type.

        Parameters:
            ctx (Context): MCP request context providing lifespan state.
            days (int | None): Age threshold in days; entries with COALESCE(accessed_at, updated_at) older than this are stale.
            limit (int): Maximum number of stale entries to return.
            entry_type (str | None): Optional entry type filter.

        Returns:
            list[types.TextContent]: A single TextContent block containing a JSON object with keys:
                - days_threshold: the days cutoff used
                - entry_type_filter: the entry_type filter or null
                - stale_count: total number of matching stale entries (may exceed returned list)
                - entries: array of stale entry summaries (id, content_preview, entry_type, author, project, last_accessed, days_since)
        """
        lc = _get_lifespan_context(ctx)
        arguments: dict[str, Any] = {"limit": limit}
        if days is not None:
            arguments["days"] = days
        if entry_type is not None:
            arguments["entry_type"] = entry_type
        return await _handle_stale(
            store=lc["store"],
            config=lc["config"],
            arguments=arguments,
        )

    @server.tool
    async def distillery_tag_tree(
        ctx: Context,
        prefix: str | None = None,
    ) -> list[types.TextContent]:
        """Return a nested tag hierarchy with entry counts.

        Scans all active entries and builds a tree from their slash-separated
        tags.  Each node in the tree has a ``count`` (number of entries whose
        tags fall under that node) and a ``children`` dict keyed by the next
        segment name.

        Parameters:
            prefix (str | None): When provided, only nodes under this namespace
                prefix are included in the response.  For example,
                ``prefix="project"`` returns only ``project/*`` subtrees.

        Returns:
            list[types.TextContent]: A single MCP TextContent block containing
            a JSON object with key ``tree`` (the nested dict) and ``prefix``
            (the filter applied, or null).
        """
        lc = _get_lifespan_context(ctx)
        return await _handle_tag_tree(
            store=lc["store"],
            arguments={"prefix": prefix},
        )

    @server.tool
    async def distillery_type_schemas(
        ctx: Context,  # noqa: ARG001
    ) -> list[types.TextContent]:
        """Return the metadata schemas for all structured entry types.

        Reports required and optional metadata fields for each entry type that
        has a defined schema (``person``, ``project``, ``digest``, ``github``).
        Legacy types (e.g. ``session``, ``bookmark``) are listed with empty
        required/optional dicts to indicate they accept any metadata.

        Returns:
            list[types.TextContent]: A single MCP TextContent block containing
            a JSON object with key ``schemas``, mapping each entry type name to
            its schema dict (``required``, ``optional``, and optionally
            ``constraints``).
        """
        return await _handle_type_schemas()

    @server.tool
    async def distillery_watch(  # noqa: PLR0913
        ctx: Context,
        action: str,
        url: str | None = None,
        source_type: str | None = None,
        label: str | None = None,
        poll_interval_minutes: int | None = None,
        trust_weight: float | None = None,
    ) -> list[types.TextContent]:
        """Manage monitored feed sources in the Distillery source registry.

        Supports three actions:

        - ``list``: Return all currently configured feed sources with their
          settings (url, source_type, label, poll_interval_minutes,
          trust_weight).
        - ``add``: Register a new feed source.  Requires ``url`` and
          ``source_type``.  Optional fields: ``label``,
          ``poll_interval_minutes`` (default 60), ``trust_weight``
          (default 1.0).  Accepted source types: ``rss``, ``github``.
        - ``remove``: Remove a feed source by exact URL match.  Requires
          ``url``.

        Changes made via ``add`` and ``remove`` are persisted to the database
        and survive server restarts.  YAML-configured sources are seeded into
        the database on first startup.

        Parameters:
            action (str): One of ``'list'``, ``'add'``, ``'remove'``.
            url (str | None): Source URL.  Required for ``add`` and ``remove``.
            source_type (str | None): Adapter type for ``add``.  One of
                ``'rss'``, ``'github'``.
            label (str | None): Human-readable label for the source (optional).
            poll_interval_minutes (int | None): Poll frequency in minutes for
                ``add``.  Defaults to ``60``.
            trust_weight (float | None): Trust multiplier in ``[0.0, 1.0]``
                for ``add``.  Defaults to ``1.0``.

        Returns:
            list[types.TextContent]: A single MCP TextContent block containing
            a JSON object.  On success the object contains:
              - For ``list``: ``sources`` (list of source dicts) and
                ``count`` (number of sources).
              - For ``add``: ``added`` (the new source dict) and
                ``sources`` (updated full list).
              - For ``remove``: ``removed_url``, ``removed`` (bool), and
                ``sources`` (updated full list).
            On error: ``error``, ``code``, and ``message``.
        """
        lc = _get_lifespan_context(ctx)
        arguments: dict[str, Any] = {"action": action}
        if url is not None:
            arguments["url"] = url
        if source_type is not None:
            arguments["source_type"] = source_type
        if label is not None:
            arguments["label"] = label
        if poll_interval_minutes is not None:
            arguments["poll_interval_minutes"] = poll_interval_minutes
        if trust_weight is not None:
            arguments["trust_weight"] = trust_weight
        return await _handle_watch(
            store=lc["store"],
            arguments=arguments,
        )

    @server.tool
    async def distillery_interests(
        ctx: Context,
        recency_days: int = 90,
        top_n: int = 20,
    ) -> list[types.TextContent]:
        """Extract an interest profile from the knowledge base.

        Mines all active entries to produce a weighted summary of the user's
        topics of interest.  The result includes top tags (recency-weighted),
        bookmark domains, tracked GitHub repositories, expertise areas, and
        the list of sources already being watched (for exclusion from new
        suggestions).

        Parameters:
            recency_days (int): Number of days used as the recency window.
                Entries within this window receive full weight; older entries
                decay linearly.  Default ``90``.
            top_n (int): Maximum number of tags to include in the response.
                Default ``20``.

        Returns:
            list[types.TextContent]: A single MCP TextContent block containing
            a JSON object with keys:
              - ``top_tags``: list of ``[tag, weight]`` pairs, descending.
              - ``bookmark_domains``: list of domain strings.
              - ``tracked_repos``: list of ``owner/repo`` strings.
              - ``expertise_areas``: list of topic strings.
              - ``watched_sources``: list of watched source URLs.
              - ``suggestion_context``: prose paragraph for LLM prompting.
              - ``entry_count``: number of entries analysed.
              - ``generated_at``: ISO 8601 timestamp.
            On error: ``error``, ``code``, and ``message``.
        """
        lc = _get_lifespan_context(ctx)
        return await _handle_interests(
            store=lc["store"],
            config=lc["config"],
            arguments={"recency_days": recency_days, "top_n": top_n},
        )

    @server.tool
    async def distillery_suggest_sources(  # noqa: PLR0913
        ctx: Context,
        max_suggestions: int = 5,
        source_types: list[str] | None = None,
        recency_days: int = 90,
        top_n: int = 20,
    ) -> list[types.TextContent]:
        """Suggest new feed sources to monitor based on the user's interests.

        Builds an :class:`~distillery.feeds.interests.InterestProfile` from
        the knowledge base and returns a structured prompt fragment plus a
        list of illustrative source suggestions inferred from the profile.
        The suggestions are heuristic (pattern-matched from tracked repos and
        bookmark domains) and are intended as a starting point; callers can
        pass ``suggestion_context`` to an LLM for richer recommendations.

        Parameters:
            max_suggestions (int): Maximum number of source suggestions to
                return.  Default ``5``.
            source_types (list[str] | None): Filter suggestions to these
                adapter types.  Accepted values: ``'rss'``, ``'github'``.
                ``None`` means no filter.
            recency_days (int): Recency window passed to
                :class:`~distillery.feeds.interests.InterestExtractor`.
                Default ``90``.
            top_n (int): Top-tags count passed to the extractor.  Default
                ``20``.

        Returns:
            list[types.TextContent]: A single MCP TextContent block containing
            a JSON object with keys:
              - ``suggestions``: list of dicts, each with ``url``,
                ``source_type``, ``label``, and ``rationale``.
              - ``suggestion_context``: full prose paragraph for LLM prompting.
              - ``watched_sources``: list of currently-watched source URLs
                (already excluded from suggestions).
              - ``entry_count``: number of entries analysed.
            On error: ``error``, ``code``, and ``message``.
        """
        lc = _get_lifespan_context(ctx)
        arguments: dict[str, Any] = {
            "max_suggestions": max_suggestions,
            "recency_days": recency_days,
            "top_n": top_n,
        }
        if source_types is not None:
            arguments["source_types"] = source_types
        return await _handle_suggest_sources(
            store=lc["store"],
            config=lc["config"],
            arguments=arguments,
        )

    @server.tool
    async def distillery_poll(
        ctx: Context,
        source_url: str | None = None,
    ) -> list[types.TextContent]:
        """Poll configured feed sources and store relevant items.

        Runs a poll cycle over all (or one) configured feed sources.  For
        each source, the appropriate adapter is called to fetch new items.
        Each item is scored against the knowledge base via cosine similarity;
        items that are near-duplicates of existing entries are skipped, and
        items whose relevance score meets the configured digest threshold are
        stored as ``feed`` entries.

        Parameters:
            source_url (str | None): When provided, poll only the source
                whose URL matches this value exactly.  When ``None`` (the
                default), all configured sources are polled.

        Returns:
            list[types.TextContent]: A single MCP TextContent block containing
            a JSON object with keys:
              - ``sources_polled``: number of sources processed.
              - ``sources_errored``: number of sources that reported errors.
              - ``total_fetched``: total number of raw items fetched.
              - ``total_stored``: number of items stored in the knowledge base.
              - ``total_skipped_dedup``: items skipped as near-duplicates.
              - ``total_below_threshold``: items below the relevance threshold.
              - ``results``: per-source breakdown (see :class:`PollResult`).
              - ``started_at``: ISO 8601 timestamp.
              - ``finished_at``: ISO 8601 timestamp.
            On error: ``error``, ``code``, and ``message``.
        """
        lc = _get_lifespan_context(ctx)
        arguments: dict[str, Any] = {}
        if source_url is not None:
            arguments["source_url"] = source_url
        return await _handle_poll(
            store=lc["store"],
            config=lc["config"],
            arguments=arguments,
        )

    @server.tool
    async def distillery_rescore(
        ctx: Context,
        limit: int = 100,
    ) -> list[types.TextContent]:
        """Re-score existing feed entries against the current knowledge base.

        Recomputes relevance scores for stored feed entries using the
        current store state.  Useful after adding new knowledge entries
        that change the interest profile, so previously low-scoring feed
        items can be re-evaluated.

        Parameters:
            limit (int): Maximum number of feed entries to re-score.
                Default ``100``.

        Returns:
            list[types.TextContent]: A single MCP TextContent block containing
            a JSON object with keys:
              - ``rescored``: number of entries re-scored.
              - ``upgraded``: entries whose score increased.
              - ``downgraded``: entries whose score decreased.
              - ``archived``: entries archived for falling below threshold.
              - ``errors``: number of entries that failed to re-score.
            On error: ``error``, ``code``, and ``message``.
        """
        lc = _get_lifespan_context(ctx)
        from distillery.feeds.poller import FeedPoller

        poller = FeedPoller(store=lc["store"], config=lc["config"])
        try:
            stats = await poller.rescore(limit=limit)
            return success_response(stats)
        except Exception as exc:  # noqa: BLE001
            logger.exception("distillery_rescore: unexpected error")
            return error_response("RESCORE_ERROR", f"Rescore failed: {exc}")

    return server


def __getattr__(name: str) -> FastMCP:
    """Lazy module-level attribute for FastMCP auto-discovery.

    ``fastmcp run src/distillery/mcp/server.py`` looks for a top-level
    variable named ``mcp``, ``server``, or ``app``.  Because tool handler
    closures reference module-level constants defined below
    ``create_server``, we cannot call it at import time.  Instead we use
    the module ``__getattr__`` hook (PEP 562) to build the server on first
    access and cache it in the module globals for subsequent lookups.
    """
    if name in ("mcp", "server", "app"):
        instance = create_server()
        globals()[name] = instance
        return instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Tool handlers (CRUD handlers imported from tools/crud.py;
# search handlers imported from tools/search.py)
# ---------------------------------------------------------------------------
# _handle_status, _handle_store, _handle_get, _handle_update, _handle_list
# are imported at the top of this module from distillery.mcp.tools.crud.
# _handle_search, _handle_find_similar, _handle_aggregate, _AGGREGATE_GROUP_BY_MAP
# are imported at the top of this module from distillery.mcp.tools.search.


# _handle_tag_tree, _handle_type_schemas, _DEFAULT_STALE_DAYS, _handle_metrics,
# _handle_quality, _handle_stale are imported at the top of this module from
# distillery.mcp.tools.analytics.


# ---------------------------------------------------------------------------
# distillery_watch handler
# ---------------------------------------------------------------------------

_VALID_SOURCE_TYPES = {"rss", "github"}


async def _handle_watch(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Handle the ``distillery_watch`` tool.

    Supports ``list``, ``add``, and ``remove`` actions against the database-backed
    feed sources table.

    Args:
        store: An initialised storage backend with feed source methods.
        arguments: Parsed tool arguments dict.

    Returns:
        A structured MCP success or error response.
    """
    action_raw = arguments.get("action")
    if action_raw is None or not isinstance(action_raw, str):
        return error_response(
            "INVALID_ACTION",
            f"action must be a non-null string, got: {action_raw!r}",
        )
    action = action_raw.strip().lower()

    if action not in ("list", "add", "remove"):
        return error_response(
            "INVALID_ACTION",
            f"action must be one of 'list', 'add', 'remove'; got: {action!r}",
        )

    if action == "list":
        try:
            db_sources = await store.list_feed_sources()
        except Exception as exc:  # noqa: BLE001
            logger.exception("distillery_watch: failed to list feed sources")
            return error_response("WATCH_ERROR", f"Failed to list feed sources: {exc}")
        return success_response(
            {
                "sources": db_sources,
                "count": len(db_sources),
            }
        )

    if action == "add":
        url_raw = arguments.get("url")
        if url_raw is not None and not isinstance(url_raw, str):
            return error_response(
                "INVALID_FIELD", f"url must be a string, got: {type(url_raw).__name__}"
            )
        url = str(url_raw or "").strip()
        if not url:
            return error_response("MISSING_FIELD", "url is required for action='add'")

        source_type_raw = arguments.get("source_type")
        if source_type_raw is not None and not isinstance(source_type_raw, str):
            return error_response(
                "INVALID_FIELD",
                f"source_type must be a string, got: {type(source_type_raw).__name__}",
            )
        source_type = str(source_type_raw or "").strip()
        if not source_type:
            return error_response("MISSING_FIELD", "source_type is required for action='add'")
        if source_type not in _VALID_SOURCE_TYPES:
            return error_response(
                "INVALID_SOURCE_TYPE",
                f"source_type must be one of {sorted(_VALID_SOURCE_TYPES)}, got: {source_type!r}",
            )

        label = str(arguments.get("label", ""))

        poll_interval_raw = arguments.get("poll_interval_minutes", 60)
        try:
            poll_interval = int(poll_interval_raw)
        except (TypeError, ValueError):
            return error_response(
                "INVALID_FIELD",
                f"poll_interval_minutes must be an integer, got: {poll_interval_raw!r}",
            )
        if poll_interval <= 0:
            return error_response(
                "INVALID_FIELD",
                f"poll_interval_minutes must be a positive integer, got: {poll_interval}",
            )

        trust_weight_raw = arguments.get("trust_weight", 1.0)
        try:
            trust_weight = float(trust_weight_raw)
        except (TypeError, ValueError):
            return error_response(
                "INVALID_FIELD",
                f"trust_weight must be a float, got: {trust_weight_raw!r}",
            )
        if not (0.0 <= trust_weight <= 1.0):
            return error_response(
                "INVALID_FIELD",
                f"trust_weight must be between 0.0 and 1.0, got: {trust_weight}",
            )

        try:
            added = await store.add_feed_source(
                url=url,
                source_type=source_type,
                label=label,
                poll_interval_minutes=poll_interval,
                trust_weight=trust_weight,
            )
            db_sources = await store.list_feed_sources()
        except ValueError:
            return error_response(
                "DUPLICATE_SOURCE",
                f"Source with URL {url!r} is already registered.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("distillery_watch: failed to add feed source")
            return error_response("WATCH_ERROR", f"Failed to add feed source: {exc}")

        return success_response(
            {
                "added": added,
                "sources": db_sources,
            }
        )

    # action == "remove"
    url = str(arguments.get("url", "")).strip()
    if not url:
        return error_response("MISSING_FIELD", "url is required for action='remove'")

    try:
        removed = await store.remove_feed_source(url)
        db_sources = await store.list_feed_sources()
    except Exception as exc:  # noqa: BLE001
        logger.exception("distillery_watch: failed to remove feed source")
        return error_response("WATCH_ERROR", f"Failed to remove feed source: {exc}")
    return success_response(
        {
            "removed_url": url,
            "removed": removed,
            "sources": db_sources,
        }
    )


# _handle_interests is imported at the top of this module from
# distillery.mcp.tools.analytics.


# ---------------------------------------------------------------------------
# distillery_suggest_sources handler
# ---------------------------------------------------------------------------

_VALID_SUGGEST_SOURCE_TYPES = {"rss", "github"}


async def _handle_suggest_sources(
    store: Any,
    config: DistilleryConfig,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Handle the ``distillery_suggest_sources`` tool.

    Extracts an interest profile from the store and derives heuristic source
    suggestions from tracked repos and bookmark domains.  The ``suggestion_context``
    field in the response can be forwarded to an LLM for richer recommendations.

    Args:
        store: An initialised storage backend.
        config: The current :class:`~distillery.config.DistilleryConfig`.
        arguments: Parsed tool arguments dict (``max_suggestions``,
            ``source_types``, ``recency_days``, ``top_n``).

    Returns:
        A structured MCP success or error response.
    """
    from distillery.feeds.interests import InterestExtractor

    max_suggestions_raw = arguments.get("max_suggestions", 5)
    try:
        max_suggestions = int(max_suggestions_raw)
    except (TypeError, ValueError):
        return error_response(
            "INVALID_FIELD",
            f"max_suggestions must be an integer, got: {max_suggestions_raw!r}",
        )
    if max_suggestions <= 0:
        return error_response(
            "INVALID_FIELD",
            f"max_suggestions must be a positive integer, got: {max_suggestions}",
        )

    source_types_raw = arguments.get("source_types")
    source_type_filter: set[str] | None = None
    if source_types_raw is not None:
        if not isinstance(source_types_raw, list):
            return error_response(
                "INVALID_FIELD",
                f"source_types must be a list, got: {type(source_types_raw).__name__}",
            )
        invalid = [t for t in source_types_raw if t not in _VALID_SUGGEST_SOURCE_TYPES]
        if invalid:
            return error_response(
                "INVALID_SOURCE_TYPE",
                f"Invalid source_types: {invalid}. "
                f"Must be one of {sorted(_VALID_SUGGEST_SOURCE_TYPES)}.",
            )
        source_type_filter = set(source_types_raw)

    recency_days_raw = arguments.get("recency_days", 90)
    try:
        recency_days = int(recency_days_raw)
    except (TypeError, ValueError):
        return error_response(
            "INVALID_FIELD",
            f"recency_days must be an integer, got: {recency_days_raw!r}",
        )
    if recency_days <= 0:
        return error_response(
            "INVALID_FIELD",
            f"recency_days must be a positive integer, got: {recency_days}",
        )

    top_n_raw = arguments.get("top_n", 20)
    try:
        top_n = int(top_n_raw)
    except (TypeError, ValueError):
        return error_response(
            "INVALID_FIELD",
            f"top_n must be an integer, got: {top_n_raw!r}",
        )
    if top_n <= 0:
        return error_response(
            "INVALID_FIELD",
            f"top_n must be a positive integer, got: {top_n}",
        )

    extractor = InterestExtractor(
        store=store,
        recency_days=recency_days,
        top_n=top_n,
    )
    try:
        profile = await extractor.extract()
    except Exception as exc:  # noqa: BLE001
        logger.exception("distillery_suggest_sources: extraction failed")
        return error_response("EXTRACTION_ERROR", f"Interest extraction failed: {exc}")

    watched_set = _normalise_watched_set(profile.watched_sources)
    suggestions = _derive_suggestions(
        profile=profile,
        watched_set=watched_set,
        source_type_filter=source_type_filter,
        max_suggestions=max_suggestions,
    )

    return success_response(
        {
            "suggestions": suggestions,
            "suggestion_context": profile.suggestion_context,
            "watched_sources": profile.watched_sources,
            "entry_count": profile.entry_count,
        }
    )


def _normalise_watched_set(watched_sources: list[str]) -> set[str]:
    """Build a normalised set of watched source identifiers.

    For each URL, also includes the ``owner/repo`` slug when the URL
    points to GitHub.  This ensures that a GitHub source stored as
    ``https://github.com/owner/repo`` is matched against a suggestion
    that uses the short ``owner/repo`` form.

    Args:
        watched_sources: Raw list of watched source URLs from the profile.

    Returns:
        A set of normalised identifiers for exclusion checks.
    """
    import re

    normalised: set[str] = set()
    for url in watched_sources:
        normalised.add(url)
        # Extract owner/repo slug from GitHub URLs
        match = re.search(r"github\.com/([a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+)", url)
        if match:
            normalised.add(match.group(1))
        # Also handle bare owner/repo slugs
        stripped = url.strip().rstrip("/")
        if re.match(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$", stripped):
            normalised.add(f"https://github.com/{stripped}")
    return normalised


def _derive_suggestions(
    profile: Any,
    watched_set: set[str],
    source_type_filter: set[str] | None,
    max_suggestions: int,
) -> list[dict[str, Any]]:
    """Build heuristic source suggestions from a profile.

    Derives candidate sources from tracked repositories (GitHub releases/
    activity feeds) and bookmark domains (RSS feeds), filtering out sources
    already in *watched_set* and applying *source_type_filter*.

    Args:
        profile: An :class:`~distillery.feeds.interests.InterestProfile`.
        watched_set: Set of already-watched source URLs.
        source_type_filter: When non-None, only include suggestions of these
            source types.
        max_suggestions: Maximum number of suggestions to return.

    Returns:
        A list of suggestion dicts, each with ``url``, ``source_type``,
        ``label``, and ``rationale``.
    """
    candidates: list[dict[str, Any]] = []

    # GitHub suggestions from tracked repos
    if source_type_filter is None or "github" in source_type_filter:
        for repo in profile.tracked_repos:
            candidate_url = repo  # owner/repo slug used by GitHub adapter
            if candidate_url not in watched_set:
                candidates.append(
                    {
                        "url": candidate_url,
                        "source_type": "github",
                        "label": repo,
                        "rationale": (
                            f"You have referenced the {repo!r} repository in your "
                            "knowledge base. Monitoring it will surface new releases, "
                            "issues, and pull requests."
                        ),
                    }
                )

    # RSS suggestions from bookmark domains
    if source_type_filter is None or "rss" in source_type_filter:
        for domain in profile.bookmark_domains:
            candidate_url = f"https://{domain}/rss"
            if candidate_url not in watched_set and len(domain) > 3 and "." in domain:
                candidates.append(
                    {
                        "url": candidate_url,
                        "source_type": "rss",
                        "label": domain,
                        "rationale": (
                            f"You frequently bookmark content from {domain!r}. "
                            "An RSS feed from this domain would surface new content "
                            "automatically."
                        ),
                    }
                )

    return candidates[:max_suggestions]


# ---------------------------------------------------------------------------
# distillery_poll handler
# ---------------------------------------------------------------------------


def _poll_result_to_dict(result: Any) -> dict[str, Any]:
    """Serialise a :class:`~distillery.feeds.poller.PollResult` to a plain dict."""
    return {
        "source_url": result.source_url,
        "source_type": result.source_type,
        "items_fetched": result.items_fetched,
        "items_stored": result.items_stored,
        "items_skipped_dedup": result.items_skipped_dedup,
        "items_below_threshold": result.items_below_threshold,
        "errors": result.errors,
        "polled_at": result.polled_at.isoformat(),
    }


async def _handle_poll(
    store: Any,
    config: DistilleryConfig,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Handle the ``distillery_poll`` tool.

    Creates a :class:`~distillery.feeds.poller.FeedPoller`, optionally filters
    to a single source, and runs a poll cycle.

    Args:
        store: An initialised storage backend.
        config: The current :class:`~distillery.config.DistilleryConfig`.
        arguments: Parsed tool arguments dict (``source_url`` optional).

    Returns:
        A structured MCP success or error response.
    """
    from distillery.feeds.poller import FeedPoller

    source_url: str | None = arguments.get("source_url")

    try:
        # When a specific source_url is requested, verify it exists in DB.
        if source_url is not None:
            db_sources = await store.list_feed_sources()
            matching = [s for s in db_sources if s["url"] == source_url]
            if not matching:
                return error_response(
                    "NOT_FOUND",
                    f"No configured source found with url {source_url!r}. "
                    "Use distillery_watch(action='list') to see available sources.",
                )

        poller = FeedPoller(store=store, config=config)
        summary = await poller.poll(source_url=source_url)
    except Exception as exc:  # noqa: BLE001
        logger.exception("distillery_poll: unexpected error during poll cycle")
        return error_response("POLL_ERROR", f"Poll cycle failed: {exc}")

    return success_response(
        {
            "sources_polled": summary.sources_polled,
            "sources_errored": summary.sources_errored,
            "total_fetched": summary.total_fetched,
            "total_stored": summary.total_stored,
            "total_skipped_dedup": summary.total_skipped_dedup,
            "total_below_threshold": summary.total_below_threshold,
            "results": [_poll_result_to_dict(r) for r in summary.results],
            "started_at": summary.started_at.isoformat(),
            "finished_at": summary.finished_at.isoformat(),
        }
    )
