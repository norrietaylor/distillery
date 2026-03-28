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

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastmcp import Context, FastMCP  # noqa: F401  # Context used by tool wrappers added in T02
from mcp import types

from distillery.config import DistilleryConfig, load_config

logger = logging.getLogger(__name__)

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
    elif provider_name == "":
        # No provider configured -- return a lightweight stub used for testing
        # and status-only operations.
        from distillery.mcp._stub_embedding import StubEmbeddingProvider

        return StubEmbeddingProvider(dimensions=dimensions)
    else:
        raise ValueError(
            f"Unsupported embedding provider: {provider_name!r}. Must be one of: 'jina', 'openai'."
        )


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_server(config: DistilleryConfig | None = None) -> FastMCP:
    """Build and return the configured :class:`~fastmcp.FastMCP` server.

    The server is stateless at construction time -- the store and embedding
    provider are initialised during the lifespan context manager when the
    stdio transport connects.

    Args:
        config: Pre-loaded configuration.  When ``None`` the config is loaded
            from the standard locations (``DISTILLERY_CONFIG`` env var, then
            ``distillery.yaml`` in the cwd).

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
              - "recent_searches": an in-memory list for implicit feedback.
        """
        if not _shared:
            logger.info("Distillery MCP server starting up …")

            embedding_provider = _create_embedding_provider(config)
            raw_db_path = config.storage.database_path
            # Expand ~ only for local filesystem paths; leave S3/MotherDuck URIs intact.
            if raw_db_path.startswith("s3://") or raw_db_path.startswith("md:"):
                db_path = raw_db_path
            else:
                db_path = os.path.expanduser(raw_db_path)

            # Apply MotherDuck token from the configured env var name if set.
            if config.storage.motherduck_token_env:
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

            _shared["store"] = store
            _shared["config"] = config
            _shared["embedding_provider"] = embedding_provider
            _shared["recent_searches"] = []

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

    server = FastMCP("distillery", lifespan=lifespan)

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
        return await _handle_store(
            store=lc["store"],
            arguments=arguments,
            cfg=lc["config"],
        )

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
            recent_searches=lc["recent_searches"],
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
        return await _handle_update(
            store=lc["store"],
            arguments=arguments,
        )

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

        Returns:
            list[types.TextContent]: MCP TextContent blocks containing a JSON object with
            keys "entries" (list of entry dicts), "count" (total matching entries),
            "limit", and "offset".
        """
        lc = _get_lifespan_context(ctx)
        arguments: dict[str, Any] = {"limit": limit, "offset": offset}
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
        return await _handle_list(
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
            recent_searches=lc["recent_searches"],
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
        arguments: dict[str, Any] = {"entry_id": entry_id, "action": action}
        if new_entry_type is not None:
            arguments["new_entry_type"] = new_entry_type
        if reviewer is not None:
            arguments["reviewer"] = reviewer
        return await _handle_resolve_review(
            store=lc["store"],
            arguments=arguments,
        )

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
# Tool handlers
# ---------------------------------------------------------------------------


async def _handle_status(
    store: Any,
    embedding_provider: Any,
    config: DistilleryConfig,
) -> list[types.TextContent]:
    """Implement the ``distillery_status`` tool.

    Queries the DuckDB store for aggregate statistics and returns them as a
    JSON payload.

    Args:
        store: Initialised :class:`~distillery.store.duckdb.DuckDBStore`.
        embedding_provider: The active embedding provider instance.
        config: The loaded Distillery configuration.

    Returns:
        MCP content list with a single JSON ``TextContent`` block.
    """
    try:
        stats = await asyncio.to_thread(_sync_gather_stats, store, embedding_provider, config)
        return success_response(stats)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error gathering status stats")
        return error_response("STATUS_ERROR", f"Failed to gather status: {exc}")


def _sync_gather_stats(
    store: Any,
    embedding_provider: Any,
    config: DistilleryConfig,
) -> dict[str, Any]:
    """Synchronous helper that queries DuckDB for status statistics.

    Runs inside ``asyncio.to_thread`` so that blocking DuckDB calls do not
    stall the event loop.

    Args:
        store: Initialised ``DuckDBStore`` whose ``connection`` property is
            available.
        embedding_provider: Active embedding provider (for model metadata).
        config: Loaded ``DistilleryConfig``.

    Returns:
        A dict suitable for JSON serialisation.
    """
    conn = store.connection

    # Total entry count (all statuses).
    total_row = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
    total_entries: int = total_row[0] if total_row else 0

    # Counts grouped by entry_type.
    type_rows = conn.execute(
        "SELECT entry_type, COUNT(*) AS cnt FROM entries GROUP BY entry_type ORDER BY cnt DESC"
    ).fetchall()
    entries_by_type = {row[0]: row[1] for row in type_rows}

    # Counts grouped by status.
    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM entries GROUP BY status ORDER BY cnt DESC"
    ).fetchall()
    entries_by_status = {row[0]: row[1] for row in status_rows}

    # Database file size.
    _raw_db_path = config.storage.database_path
    if _raw_db_path.startswith("s3://") or _raw_db_path.startswith("md:"):
        db_path = _raw_db_path
    else:
        db_path = os.path.expanduser(_raw_db_path)
    database_size_bytes: int | None = None
    if db_path != ":memory:" and not db_path.startswith("s3://") and not db_path.startswith("md:"):
        try:
            database_size_bytes = Path(db_path).stat().st_size
        except OSError:
            database_size_bytes = None

    # Embedding model info.
    model_name = getattr(embedding_provider, "model_name", "unknown")
    embedding_dimensions = getattr(embedding_provider, "dimensions", None)

    return {
        "status": "ok",
        "total_entries": total_entries,
        "entries_by_type": entries_by_type,
        "entries_by_status": entries_by_status,
        "database_size_bytes": database_size_bytes,
        "embedding_model": model_name,
        "embedding_dimensions": embedding_dimensions,
        "database_path": db_path,
    }


# ---------------------------------------------------------------------------
# T04.2 tool handlers: store, get, update
# ---------------------------------------------------------------------------

# Valid entry_type values (mirrors EntryType enum).
_VALID_ENTRY_TYPES = {
    "session",
    "bookmark",
    "minutes",
    "meeting",
    "reference",
    "idea",
    "inbox",
    "person",
    "project",
    "digest",
    "github",
}

# Valid status values (mirrors EntryStatus enum).
_VALID_STATUSES = {"active", "pending_review", "archived"}

# Fields that callers may never overwrite via distillery_update.
_IMMUTABLE_FIELDS = {"id", "created_at", "source"}

# Default similarity threshold for deduplication warnings.
_DEFAULT_DEDUP_THRESHOLD = 0.92
_DEFAULT_DEDUP_LIMIT = 3


async def _handle_store(
    store: Any,
    arguments: dict[str, Any],
    cfg: DistilleryConfig | None = None,
) -> list[types.TextContent]:
    """
    Create and persist a new Entry from the provided arguments, run deduplication and a non-fatal conflict check, and return the stored entry id along with any warnings or conflict candidates.

    Parameters:
        arguments (dict): MCP tool arguments. Required keys: `content`, `entry_type`, `author`. Optional keys: `project`, `tags` (list), `metadata` (dict), `dedup_threshold` (number), `dedup_limit` (int).
        cfg (DistilleryConfig | None): Optional configuration used to derive classification/conflict thresholds; when omitted a default conflict threshold of 0.60 is used.

    Returns:
        list[types.TextContent]: MCP content list containing a JSON-serializable object with at least `entry_id`. May also include:
          - `warnings`: list of similar-entry summaries (id, score, content_preview) when near-duplicates were found,
          - `warning_message`: human-readable summary of warnings,
          - `conflicts`: list of conflict candidate objects (entry_id, content_preview, similarity_score, conflict_reasoning),
          - `conflict_message`: guidance message when conflict candidates are returned.
    """
    from distillery.models import Entry, EntrySource, EntryType

    # --- input validation ---------------------------------------------------
    err = validate_required(arguments, "content", "entry_type", "author")
    if err:
        return error_response("INVALID_INPUT", err)

    entry_type_str = arguments["entry_type"]
    if entry_type_str not in _VALID_ENTRY_TYPES:
        return error_response(
            "INVALID_INPUT",
            f"Invalid entry_type {entry_type_str!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_ENTRY_TYPES))}.",
        )

    tags_err = validate_type(arguments, "tags", list, "list of strings")
    if tags_err:
        return error_response("INVALID_INPUT", tags_err)

    metadata_err = validate_type(arguments, "metadata", dict, "object")
    if metadata_err:
        return error_response("INVALID_INPUT", metadata_err)

    dedup_threshold = arguments.get("dedup_threshold", _DEFAULT_DEDUP_THRESHOLD)
    dedup_limit = arguments.get("dedup_limit", _DEFAULT_DEDUP_LIMIT)

    if not isinstance(dedup_threshold, (int, float)):
        return error_response("INVALID_INPUT", "Field 'dedup_threshold' must be a number")
    if not isinstance(dedup_limit, int):
        return error_response("INVALID_INPUT", "Field 'dedup_limit' must be an integer")

    # --- reserved prefix enforcement ----------------------------------------
    # Sources that are permitted to use tags under reserved top-level prefixes.
    _reserved_allowed_sources: set[str] = {EntrySource.IMPORT.value}
    entry_source_str: str = str(arguments.get("source", EntrySource.CLAUDE_CODE.value))
    if cfg is not None and cfg.tags.reserved_prefixes:
        tags_raw = list(arguments.get("tags") or [])
        for tag in tags_raw:
            if not isinstance(tag, str):
                return error_response(
                    "INVALID_INPUT", f"Each tag must be a string, got: {type(tag).__name__}"
                )
        tags_to_check: list[str] = tags_raw
        if entry_source_str not in _reserved_allowed_sources:
            for tag in tags_to_check:
                top = tag.split("/")[0]
                if top in cfg.tags.reserved_prefixes:
                    return error_response(
                        "RESERVED_PREFIX",
                        f"Tag {tag!r} uses reserved prefix {top!r}. "
                        "Only internal sources may use this namespace.",
                    )

    # --- build entry --------------------------------------------------------
    try:
        # Determine EntrySource from arguments.
        try:
            resolved_source = EntrySource(entry_source_str)
        except ValueError:
            resolved_source = EntrySource.CLAUDE_CODE

        entry = Entry(
            content=arguments["content"],
            entry_type=EntryType(entry_type_str),
            source=resolved_source,
            author=arguments["author"],
            project=arguments.get("project"),
            tags=list(arguments.get("tags") or []),
            metadata=dict(arguments.get("metadata") or {}),
        )
    except Exception as exc:  # noqa: BLE001
        return error_response("INVALID_INPUT", f"Failed to construct entry: {exc}")

    # --- persist ------------------------------------------------------------
    try:
        entry_id = await store.store(entry)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error storing entry")
        return error_response("STORE_ERROR", f"Failed to store entry: {exc}")

    # --- deduplication check ------------------------------------------------
    warnings: list[dict[str, Any]] = []
    try:
        similar = await store.find_similar(
            content=entry.content,
            threshold=float(dedup_threshold),
            limit=dedup_limit + 1,  # +1 because the new entry itself may appear
        )
        for result in similar:
            if result.entry.id != entry_id:
                warnings.append(
                    {
                        "similar_entry_id": result.entry.id,
                        "score": round(result.score, 4),
                        "content_preview": result.entry.content[:120],
                    }
                )
                if len(warnings) >= dedup_limit:
                    break
    except Exception as exc:  # noqa: BLE001
        logger.warning("find_similar failed during dedup check: %s", exc)
        # Non-fatal: still return the stored entry_id.

    # --- conflict check -------------------------------------------------------
    # Non-fatal: wrap in try/except so a conflict-checker failure never blocks
    # the store operation.  We return conflict_candidates (similar entries with
    # their content) so the calling LLM can evaluate them without us making an
    # LLM call ourselves.
    try:
        from distillery.classification.conflict import ConflictChecker

        conflict_threshold = float(
            cfg.classification.conflict_threshold if cfg is not None else 0.60
        )
        conflict_checker = ConflictChecker(store=store, threshold=conflict_threshold)
        conflict_similar = await store.find_similar(
            content=entry.content,
            threshold=conflict_threshold,
            limit=5,
        )
        if conflict_similar:
            conflicts = []
            for result in conflict_similar:
                if result.entry.id == entry_id:
                    continue
                lines = result.entry.content.splitlines()
                preview = lines[0][:120] if lines else result.entry.content[:120]
                prompt = conflict_checker.build_prompt(entry.content, result.entry.content)
                conflicts.append(
                    {
                        "entry_id": result.entry.id,
                        "content_preview": preview,
                        "similarity_score": round(result.score, 4),
                        "conflict_reasoning": prompt,
                    }
                )
            if conflicts:
                response_data: dict[str, Any] = {"entry_id": entry_id}
                if warnings:
                    response_data["warnings"] = warnings
                    response_data["warning_message"] = (
                        f"Found {len(warnings)} similar existing "
                        f"{'entry' if len(warnings) == 1 else 'entries'}. "
                        "Review before storing to avoid duplicates."
                    )
                response_data["conflicts"] = conflicts
                response_data["conflict_message"] = (
                    f"Found {len(conflicts)} potential conflict "
                    f"{'candidate' if len(conflicts) == 1 else 'candidates'}. "
                    "Use distillery_check_conflicts with LLM responses to confirm conflicts."
                )
                return success_response(response_data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Conflict check failed during store: %s", exc)
        # Non-fatal: fall through and return the entry_id without conflict info.

    response: dict[str, Any] = {"entry_id": entry_id}
    if warnings:
        response["warnings"] = warnings
        response["warning_message"] = (
            f"Found {len(warnings)} similar existing "
            f"{'entry' if len(warnings) == 1 else 'entries'}. "
            "Review before storing to avoid duplicates."
        )
    return success_response(response)


async def _handle_get(
    store: Any,
    arguments: dict[str, Any],
    recent_searches: list[dict[str, Any]] | None = None,
    config: DistilleryConfig | None = None,
) -> list[types.TextContent]:
    """
    Retrieve an entry by its ID and, when applicable, record implicit positive feedback.

    Validates presence of `entry_id`, fetches the entry from `store`, and returns the serialized entry. If `recent_searches` is provided, prunes expired search records (based on `config.classification.feedback_window_minutes`, or 5 minutes when `config` is None) and logs a single implicit positive feedback event per (search_id, entry_id) pair for any recent search that included this entry. Failures to log feedback are caught and do not prevent returning the entry.

    Parameters:
        recent_searches (list[dict]): Optional shared in-memory list of recent search events; each element must contain `search_id` (str), `entry_ids` (set[str]), and `timestamp` (datetime). When `None`, implicit feedback recording is skipped.
        config (DistilleryConfig | None): Optional configuration used to read `classification.feedback_window_minutes`; defaults to 5 minutes when `None`.

    Returns:
        list[types.TextContent]: MCP content list containing the serialized entry on success, or an error response (e.g., `NOT_FOUND`, `INVALID_INPUT`, `STORE_ERROR`).
    """
    err = validate_required(arguments, "entry_id")
    if err:
        return error_response("INVALID_INPUT", err)

    entry_id: str = arguments["entry_id"]

    try:
        entry = await store.get(entry_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error fetching entry id=%s", entry_id)
        return error_response("STORE_ERROR", f"Failed to retrieve entry: {exc}")

    if entry is None:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={entry_id!r}.",
            details={"entry_id": entry_id},
        )

    # Implicit feedback: if this get follows a recent search that returned this
    # entry, record a positive feedback signal.
    if recent_searches is not None:
        feedback_window_minutes: int = 5
        if config is not None:
            feedback_window_minutes = config.classification.feedback_window_minutes

        now = datetime.now(UTC)
        cutoff_seconds = feedback_window_minutes * 60

        # Prune expired entries and collect matching searches in a single pass.
        alive: list[dict[str, Any]] = []
        logged_pairs: set[tuple[str, str]] = set()
        for record in recent_searches:
            age_seconds = (now - record["timestamp"]).total_seconds()
            if age_seconds <= cutoff_seconds:
                alive.append(record)
                pair = (record["search_id"], entry_id)
                if entry_id in record["entry_ids"] and pair not in logged_pairs:
                    try:
                        await store.log_feedback(
                            search_id=record["search_id"],
                            entry_id=entry_id,
                            signal="positive",
                        )
                        logged_pairs.add(pair)
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "Failed to log implicit feedback for entry_id=%s search_id=%s",
                            entry_id,
                            record["search_id"],
                        )

        # Replace the list contents in-place so callers sharing the reference
        # also see the pruned version.
        recent_searches[:] = alive

    return success_response(entry.to_dict())


async def _handle_update(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_update`` tool.

    Args:
        store: Initialised ``DuckDBStore``.
        arguments: Raw MCP tool arguments dict (must contain ``entry_id`` plus
            at least one updatable field).

    Returns:
        MCP content list with the serialised updated entry or an error.
    """
    from distillery.models import EntryStatus, EntryType

    err = validate_required(arguments, "entry_id")
    if err:
        return error_response("INVALID_INPUT", err)

    entry_id: str = arguments["entry_id"]

    # Build the updates dict from all keys except entry_id.
    updatable_keys = {"content", "entry_type", "author", "project", "tags", "status", "metadata"}
    updates: dict[str, Any] = {}
    for key in updatable_keys:
        if key in arguments:
            updates[key] = arguments[key]

    # Reject attempts to modify immutable fields.
    bad_keys = _IMMUTABLE_FIELDS & (set(arguments.keys()) - {"entry_id"})
    if bad_keys:
        return error_response(
            "INVALID_INPUT",
            f"Cannot update immutable field(s): {', '.join(sorted(bad_keys))}.",
        )

    if not updates:
        return error_response(
            "INVALID_INPUT",
            "No updatable fields provided. Supply at least one of: "
            + ", ".join(sorted(updatable_keys))
            + ".",
        )

    # --- validate individual fields ----------------------------------------
    if "entry_type" in updates:
        et_str = updates["entry_type"]
        if et_str not in _VALID_ENTRY_TYPES:
            return error_response(
                "INVALID_INPUT",
                f"Invalid entry_type {et_str!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_ENTRY_TYPES))}.",
            )
        updates["entry_type"] = EntryType(et_str)

    if "status" in updates:
        st_str = updates["status"]
        if st_str not in _VALID_STATUSES:
            return error_response(
                "INVALID_INPUT",
                f"Invalid status {st_str!r}. Must be one of: {', '.join(sorted(_VALID_STATUSES))}.",
            )
        updates["status"] = EntryStatus(st_str)

    tags_err = validate_type(updates, "tags", list, "list of strings")
    if tags_err:
        return error_response("INVALID_INPUT", tags_err)

    metadata_err = validate_type(updates, "metadata", dict, "object")
    if metadata_err:
        return error_response("INVALID_INPUT", metadata_err)

    # --- persist ------------------------------------------------------------
    try:
        updated_entry = await store.update(entry_id, updates)
    except KeyError:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={entry_id!r}.",
            details={"entry_id": entry_id},
        )
    except ValueError as exc:
        return error_response("INVALID_INPUT", str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error updating entry id=%s", entry_id)
        return error_response("STORE_ERROR", f"Failed to update entry: {exc}")

    return success_response(updated_entry.to_dict())


# ---------------------------------------------------------------------------
# T04.3 tool handlers: search, find_similar, list
# ---------------------------------------------------------------------------


def _build_filters_from_arguments(arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Extract known filter keys from *arguments* into a filters dict.

    Keys extracted: ``entry_type``, ``author``, ``project``, ``tags``,
    ``status``, ``date_from``, ``date_to``.

    Args:
        arguments: The tool argument dict.

    Returns:
        A dict of filters, or ``None`` if no filter keys are present.
    """
    filter_keys = (
        "entry_type",
        "author",
        "project",
        "tags",
        "status",
        "date_from",
        "date_to",
        "tag_prefix",
    )
    filters: dict[str, Any] = {}
    for key in filter_keys:
        if key in arguments and arguments[key] is not None:
            filters[key] = arguments[key]
    return filters if filters else None


async def _handle_search(
    store: Any,
    arguments: dict[str, Any],
    recent_searches: list[dict[str, Any]] | None = None,
) -> list[types.TextContent]:
    """
    Search stored entries for a text query and return matching entries ranked by similarity.

    Performs validation on `query` and `limit`, applies optional filters from `arguments`, and returns search hits ordered by descending similarity. When `recent_searches` is provided and results are non-empty, logs the search via the store and appends a compact record to `recent_searches` for later implicit-feedback correlation; failures to log do not affect the returned results.

    Parameters:
        arguments: Dictionary containing at minimum the key `query` (str). May include optional filter keys (e.g., `entry_type`, `author`, `project`, `tags`, `status`, `date_from`, `date_to`) and `limit` (int).
        recent_searches: Optional shared in-memory list used for implicit feedback correlation. When provided, a record with keys `search_id` (str), `entry_ids` (set[str]), and `timestamp` (datetime) will be appended for logged searches. If `None`, search logging and in-memory tracking are skipped.

    Returns:
        MCP content list containing a single JSON object with `results` (list of objects each with `score` and `entry`) and `count` (int) describing the number of results returned.
    """
    err = validate_required(arguments, "query")
    if err:
        return error_response("VALIDATION_ERROR", err)

    query: str = arguments["query"]

    limit_raw = arguments.get("limit", 10)
    err_limit = validate_type(arguments, "limit", int, "integer")
    if err_limit:
        return error_response("VALIDATION_ERROR", err_limit)
    limit = int(limit_raw) if limit_raw is not None else 10
    if limit < 1:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be >= 1")
    if limit > 200:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be <= 200")

    filters = _build_filters_from_arguments(arguments)

    try:
        search_results = await store.search(query=query, filters=filters, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error in distillery_search")
        return error_response("SEARCH_ERROR", f"Search failed: {exc}")

    results = [{"score": round(sr.score, 6), "entry": sr.entry.to_dict()} for sr in search_results]

    # Log the search event and record it for implicit feedback correlation.
    if recent_searches is not None and search_results:
        result_entry_ids = [sr.entry.id for sr in search_results]
        result_scores = [sr.score for sr in search_results]
        try:
            search_id = await store.log_search(
                query=query,
                result_entry_ids=result_entry_ids,
                result_scores=result_scores,
            )
            recent_searches.append(
                {
                    "search_id": search_id,
                    "entry_ids": set(result_entry_ids),
                    "timestamp": datetime.now(UTC),
                }
            )
            # Cap the in-memory list to prevent unbounded growth.
            recent_searches_max = 1000
            if len(recent_searches) > recent_searches_max:
                recent_searches[:] = recent_searches[-recent_searches_max:]
        except Exception:  # noqa: BLE001
            logger.exception("Failed to log search event; continuing without feedback tracking")

    return success_response({"results": results, "count": len(results)})


async def _handle_find_similar(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_find_similar`` tool.

    Embeds *content* and returns stored entries whose cosine similarity
    exceeds *threshold*, sorted by descending similarity.

    Args:
        store: Initialised :class:`~distillery.store.duckdb.DuckDBStore`.
        arguments: Tool argument dict containing at minimum ``content``.

    Returns:
        MCP content list with a JSON payload of ``results`` and ``count``.
    """
    err = validate_required(arguments, "content")
    if err:
        return error_response("VALIDATION_ERROR", err)

    content: str = arguments["content"]

    threshold_raw = arguments.get("threshold", 0.8)
    err_threshold = validate_type(arguments, "threshold", (int, float), "number")
    if err_threshold:
        return error_response("VALIDATION_ERROR", err_threshold)
    threshold = float(threshold_raw) if threshold_raw is not None else 0.8
    if not (0.0 <= threshold <= 1.0):
        return error_response("VALIDATION_ERROR", "Field 'threshold' must be in [0.0, 1.0]")

    limit_raw = arguments.get("limit", 10)
    err_limit = validate_type(arguments, "limit", int, "integer")
    if err_limit:
        return error_response("VALIDATION_ERROR", err_limit)
    limit = int(limit_raw) if limit_raw is not None else 10
    if limit < 1:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be >= 1")
    if limit > 200:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be <= 200")

    try:
        search_results = await store.find_similar(content=content, threshold=threshold, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error in distillery_find_similar")
        return error_response("FIND_SIMILAR_ERROR", f"find_similar failed: {exc}")

    results = [{"score": round(sr.score, 6), "entry": sr.entry.to_dict()} for sr in search_results]
    return success_response({"results": results, "count": len(results), "threshold": threshold})


async def _handle_list(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_list`` tool.

    Returns entries with optional metadata filtering and pagination.  Unlike
    ``distillery_search``, no semantic ranking is performed -- results are
    ordered by ``created_at`` descending (newest first).

    Args:
        store: Initialised :class:`~distillery.store.duckdb.DuckDBStore`.
        arguments: Tool argument dict (all fields optional).

    Returns:
        MCP content list with a JSON payload of ``entries`` and ``count``.
    """
    limit_raw = arguments.get("limit", 20)
    err_limit = validate_type(arguments, "limit", int, "integer")
    if err_limit:
        return error_response("VALIDATION_ERROR", err_limit)
    limit = int(limit_raw) if limit_raw is not None else 20
    if limit < 1:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be >= 1")
    if limit > 500:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be <= 500")

    offset_raw = arguments.get("offset", 0)
    err_offset = validate_type(arguments, "offset", int, "integer")
    if err_offset:
        return error_response("VALIDATION_ERROR", err_offset)
    offset = int(offset_raw) if offset_raw is not None else 0
    if offset < 0:
        return error_response("VALIDATION_ERROR", "Field 'offset' must be >= 0")

    filters = _build_filters_from_arguments(arguments)

    try:
        entries = await store.list_entries(filters=filters, limit=limit, offset=offset)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error in distillery_list")
        return error_response("LIST_ERROR", f"list_entries failed: {exc}")

    return success_response(
        {
            "entries": [entry.to_dict() for entry in entries],
            "count": len(entries),
            "limit": limit,
            "offset": offset,
        }
    )


async def _handle_tag_tree(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_tag_tree`` tool.

    Fetches all tags from active entries and builds a nested dict tree.
    Each node has a ``count`` (entries whose tags fall under that subtree)
    and a ``children`` dict.

    Args:
        store: Initialised ``DuckDBStore``.
        arguments: Dict with optional key ``prefix`` (str | None).

    Returns:
        MCP content list with a JSON payload containing ``tree`` and ``prefix``.
    """
    prefix: str | None = arguments.get("prefix")

    def _sync_build_tree() -> dict[str, Any]:
        """Query all tags and build the nested hierarchy synchronously."""
        conn = store.connection
        # Only include active entries to avoid noise from archived ones.
        result = conn.execute("SELECT tags FROM entries WHERE status != 'archived'")
        rows = result.fetchall()

        # Collect all individual tag strings paired with a row index so we
        # can count distinct entries (not tag occurrences) per tree node.
        all_tags: list[tuple[str, int]] = []
        for idx, (tags_col,) in enumerate(rows):
            if tags_col:
                for t in tags_col:
                    all_tags.append((t, idx))

        # Filter by prefix when requested.  A tag matches a prefix when it
        # either equals the prefix exactly or starts with "prefix/".
        if prefix is not None:
            prefix_slash = prefix + "/"
            all_tags = [
                (t, idx) for t, idx in all_tags if t == prefix or t.startswith(prefix_slash)
            ]
            # Strip the prefix (and its trailing slash) from the remaining tags
            # so that the returned tree is rooted at the prefix.
            stripped: list[tuple[str, int]] = []
            for t, idx in all_tags:
                if t == prefix:
                    # The tag is exactly the prefix -- represents the root node.
                    stripped.append(("", idx))
                else:
                    stripped.append((t[len(prefix_slash) :], idx))
            all_tags = stripped

        # Build the tree from path segments.
        # Each node: {"count": int, "children": {segment: node}, "_entry_ids": set}
        # _entry_ids tracks distinct entries to avoid overcounting when one
        # entry has multiple tags under the same namespace.
        root: dict[str, Any] = {"count": 0, "children": {}, "_entry_ids": set()}

        for tag, idx in all_tags:
            if not tag:
                # This tag exactly matched the prefix — count it at the root.
                root["_entry_ids"].add(idx)
                continue
            segments = tag.split("/")
            node = root
            for seg in segments:
                if seg not in node["children"]:
                    node["children"][seg] = {"count": 0, "children": {}, "_entry_ids": set()}
                node = node["children"][seg]
                node["_entry_ids"].add(idx)

        # Convert _entry_ids sets to counts and strip the internal sets.
        def _finalize(n: dict[str, Any]) -> None:
            n["count"] = len(n.pop("_entry_ids"))
            for child in n["children"].values():
                _finalize(child)

        _finalize(root)

        return root

    try:
        tree = await asyncio.to_thread(_sync_build_tree)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error in distillery_tag_tree")
        return error_response("TAG_TREE_ERROR", f"Failed to build tag tree: {exc}")

    return success_response({"tree": tree, "prefix": prefix})


# ---------------------------------------------------------------------------
# distillery_type_schemas tool handler
# ---------------------------------------------------------------------------


async def _handle_type_schemas() -> list[types.TextContent]:
    """Implement the ``distillery_type_schemas`` tool.

    Returns the full metadata schema registry for all known entry types.
    Types with structured schemas (``person``, ``project``, ``digest``,
    ``github``) include their required/optional/constraints definitions.
    Legacy types are reported with empty required/optional dicts.

    Returns:
        MCP content list with a JSON payload containing a ``schemas`` dict.
    """
    from distillery.models import TYPE_METADATA_SCHEMAS, EntryType

    all_schemas: dict[str, Any] = {}

    # For each known entry type, include its schema (or empty dicts for legacy).
    for et in EntryType:
        schema = TYPE_METADATA_SCHEMAS.get(et.value, {})
        all_schemas[et.value] = {
            "required": schema.get("required", {}),
            "optional": schema.get("optional", {}),
        }
        if "constraints" in schema:
            all_schemas[et.value]["constraints"] = schema["constraints"]

    return success_response({"schemas": all_schemas})


# ---------------------------------------------------------------------------
# T02 tool handlers: classify, review_queue, resolve_review
# ---------------------------------------------------------------------------

# Valid resolve-review actions.
_VALID_REVIEW_ACTIONS = {"approve", "reclassify", "archive"}


async def _handle_classify(
    store: Any,
    config: DistilleryConfig,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_classify`` tool.

    Stores a pre-computed classification result onto an existing entry.
    Updates the entry's type, status, and classification metadata fields.
    Handles reclassification of already-classified entries.

    Args:
        store: Initialised ``DuckDBStore``.
        config: The loaded Distillery configuration (for confidence threshold).
        arguments: Raw MCP tool arguments dict.

    Returns:
        MCP content list with the serialised updated entry or an error.
    """
    from datetime import datetime

    from distillery.models import EntryStatus, EntryType, validate_tag

    # --- input validation ---------------------------------------------------
    err = validate_required(arguments, "entry_id", "entry_type", "confidence")
    if err:
        return error_response("INVALID_INPUT", err)

    entry_id: str = arguments["entry_id"]
    entry_type_str: str = arguments["entry_type"]
    confidence_raw = arguments["confidence"]

    if entry_type_str not in _VALID_ENTRY_TYPES:
        return error_response(
            "INVALID_INPUT",
            f"Invalid entry_type {entry_type_str!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_ENTRY_TYPES))}.",
        )

    if not isinstance(confidence_raw, (int, float)):
        return error_response("INVALID_INPUT", "Field 'confidence' must be a number")
    confidence = float(confidence_raw)
    if not (0.0 <= confidence <= 1.0):
        return error_response("INVALID_INPUT", "Field 'confidence' must be in [0.0, 1.0]")

    tags_err = validate_type(arguments, "suggested_tags", list, "list of strings")
    if tags_err:
        return error_response("INVALID_INPUT", tags_err)

    # --- retrieve existing entry --------------------------------------------
    try:
        entry = await store.get(entry_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error fetching entry id=%s for classify", entry_id)
        return error_response("STORE_ERROR", f"Failed to retrieve entry: {exc}")

    if entry is None:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={entry_id!r}.",
            details={"entry_id": entry_id},
        )

    # --- build updates ------------------------------------------------------
    threshold = config.classification.confidence_threshold
    new_status = EntryStatus.ACTIVE if confidence >= threshold else EntryStatus.PENDING_REVIEW

    # Merge suggested tags with existing tags (de-duplicate, preserve order).
    # Filter out invalid tags from LLM suggestions to prevent validation failures.
    suggested_tags_raw = list(arguments.get("suggested_tags") or [])
    suggested_tags: list[str] = []
    for t in suggested_tags_raw:
        if not isinstance(t, str):
            logger.warning("Dropping non-string LLM-suggested tag: %r", t)
            continue
        try:
            validate_tag(t)
            suggested_tags.append(t)
        except ValueError:
            logger.warning("Dropping invalid LLM-suggested tag: %r", t)
    merged_tags = list(entry.tags) + [t for t in suggested_tags if t not in entry.tags]

    # Build updated metadata -- preserve existing metadata, add classification fields.
    new_metadata: dict[str, Any] = dict(entry.metadata)

    # If this entry was already classified, record the previous type.
    if "classified_at" in new_metadata:
        new_metadata["reclassified_from"] = entry.entry_type.value

    classified_at = datetime.now(tz=UTC).isoformat()
    new_metadata["confidence"] = confidence
    new_metadata["classified_at"] = classified_at
    if "reasoning" in arguments:
        new_metadata["classification_reasoning"] = arguments["reasoning"]

    suggested_project: str | None = arguments.get("suggested_project")

    updates: dict[str, Any] = {
        "entry_type": EntryType(entry_type_str),
        "status": new_status,
        "tags": merged_tags,
        "metadata": new_metadata,
    }
    if suggested_project and entry.project is None:
        updates["project"] = suggested_project

    # --- persist ------------------------------------------------------------
    try:
        updated_entry = await store.update(entry_id, updates)
    except KeyError:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={entry_id!r}.",
            details={"entry_id": entry_id},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error updating entry id=%s during classify", entry_id)
        return error_response("STORE_ERROR", f"Failed to update entry: {exc}")

    return success_response(updated_entry.to_dict())


async def _handle_review_queue(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_review_queue`` tool.

    Returns ``pending_review`` entries sorted by ``created_at`` descending
    with a content preview and classification metadata fields.

    Args:
        store: Initialised ``DuckDBStore``.
        arguments: Tool argument dict (all fields optional).

    Returns:
        MCP content list with a JSON payload of ``entries`` and ``count``.
    """
    limit_raw = arguments.get("limit", 20)
    err_limit = validate_type(arguments, "limit", int, "integer")
    if err_limit:
        return error_response("VALIDATION_ERROR", err_limit)
    limit = int(limit_raw) if limit_raw is not None else 20
    if limit < 1:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be >= 1")
    if limit > 500:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be <= 500")

    filters: dict[str, Any] = {"status": "pending_review"}
    if "entry_type" in arguments and arguments["entry_type"] is not None:
        entry_type_str = arguments["entry_type"]
        if entry_type_str not in _VALID_ENTRY_TYPES:
            return error_response(
                "INVALID_INPUT",
                f"Invalid entry_type {entry_type_str!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_ENTRY_TYPES))}.",
            )
        filters["entry_type"] = entry_type_str

    try:
        entries = await store.list_entries(filters=filters, limit=limit, offset=0)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error in distillery_review_queue")
        return error_response("LIST_ERROR", f"list_entries failed: {exc}")

    # Project each entry to the review-queue summary shape.
    items = []
    for entry in entries:
        items.append(
            {
                "id": entry.id,
                "content_preview": entry.content[:200],
                "entry_type": entry.entry_type.value,
                "confidence": entry.metadata.get("confidence"),
                "author": entry.author,
                "created_at": entry.created_at.isoformat(),
                "classification_reasoning": entry.metadata.get("classification_reasoning"),
            }
        )

    return success_response({"entries": items, "count": len(items)})


async def _handle_resolve_review(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_resolve_review`` tool.

    Resolves a pending-review entry by approving, reclassifying, or archiving
    it.

    * **approve**: sets ``status=active`` and records ``reviewed_at`` /
      ``reviewed_by`` in metadata.
    * **reclassify**: updates ``entry_type`` and sets ``reclassified_from`` in
      metadata.  Requires ``new_entry_type``.
    * **archive**: soft-deletes the entry by setting ``status=archived``.

    Args:
        store: Initialised ``DuckDBStore``.
        arguments: Raw MCP tool arguments dict.

    Returns:
        MCP content list with the serialised updated entry or an error.
    """
    from datetime import datetime

    from distillery.models import EntryStatus, EntryType

    # --- input validation ---------------------------------------------------
    err = validate_required(arguments, "entry_id", "action")
    if err:
        return error_response("INVALID_INPUT", err)

    entry_id: str = arguments["entry_id"]
    action: str = arguments["action"]

    if action not in _VALID_REVIEW_ACTIONS:
        return error_response(
            "INVALID_INPUT",
            f"Invalid action {action!r}. Must be one of: {', '.join(sorted(_VALID_REVIEW_ACTIONS))}.",
        )

    # --- retrieve existing entry --------------------------------------------
    try:
        entry = await store.get(entry_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error fetching entry id=%s for resolve_review", entry_id)
        return error_response("STORE_ERROR", f"Failed to retrieve entry: {exc}")

    if entry is None:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={entry_id!r}.",
            details={"entry_id": entry_id},
        )

    # --- build updates per action -------------------------------------------
    now = datetime.now(tz=UTC).isoformat()
    reviewer: str | None = arguments.get("reviewer")
    new_metadata: dict[str, Any] = dict(entry.metadata)

    updates: dict[str, Any] = {}

    if action == "approve":
        updates["status"] = EntryStatus.ACTIVE
        new_metadata["reviewed_at"] = now
        if reviewer:
            new_metadata["reviewed_by"] = reviewer
        updates["metadata"] = new_metadata

    elif action == "reclassify":
        new_type_str: str | None = arguments.get("new_entry_type")
        if not new_type_str:
            return error_response(
                "INVALID_INPUT",
                "Field 'new_entry_type' is required when action='reclassify'.",
            )
        if new_type_str not in _VALID_ENTRY_TYPES:
            return error_response(
                "INVALID_INPUT",
                f"Invalid new_entry_type {new_type_str!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_ENTRY_TYPES))}.",
            )
        new_metadata["reclassified_from"] = entry.entry_type.value
        new_metadata["reviewed_at"] = now
        if reviewer:
            new_metadata["reviewed_by"] = reviewer
        updates["entry_type"] = EntryType(new_type_str)
        updates["metadata"] = new_metadata

    elif action == "archive":
        updates["status"] = EntryStatus.ARCHIVED
        new_metadata["archived_at"] = now
        if reviewer:
            new_metadata["archived_by"] = reviewer
        updates["metadata"] = new_metadata

    # --- persist ------------------------------------------------------------
    try:
        updated_entry = await store.update(entry_id, updates)
    except KeyError:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={entry_id!r}.",
            details={"entry_id": entry_id},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error updating entry id=%s during resolve_review", entry_id)
        return error_response("STORE_ERROR", f"Failed to update entry: {exc}")

    return success_response(updated_entry.to_dict())


# ---------------------------------------------------------------------------
# T03 tool handler: check_dedup
# ---------------------------------------------------------------------------


async def _handle_check_dedup(
    store: Any,
    config: DistilleryConfig,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_check_dedup`` tool.

    Runs :class:`~distillery.classification.dedup.DeduplicationChecker` against
    the store using thresholds from *config* and returns the deduplication
    result as a JSON payload.

    Args:
        store: Initialised store with a ``find_similar`` method.
        config: Loaded :class:`~distillery.config.DistilleryConfig` (dedup
            thresholds are read from ``config.classification``).
        arguments: Tool argument dict. Must contain ``"content"`` (str).

    Returns:
        MCP content list with a single JSON ``TextContent`` block.
    """
    # --- validate input -----------------------------------------------------
    err = validate_required(arguments, "content")
    if err:
        return error_response("INVALID_INPUT", err)

    content = str(arguments["content"])

    # --- run dedup checker --------------------------------------------------
    from distillery.classification.dedup import DeduplicationChecker

    cls_cfg = config.classification
    checker = DeduplicationChecker(
        store=store,
        skip_threshold=cls_cfg.dedup_skip_threshold,
        merge_threshold=cls_cfg.dedup_merge_threshold,
        link_threshold=cls_cfg.dedup_link_threshold,
        dedup_limit=cls_cfg.dedup_limit,
    )

    try:
        result = await checker.check(content)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error running dedup check")
        return error_response("DEDUP_ERROR", f"Deduplication check failed: {exc}")

    # --- serialise result ---------------------------------------------------
    similar_entries_serialised = []
    for sr in result.similar_entries:
        similar_entries_serialised.append(
            {
                "entry_id": str(sr.entry.id),
                "score": sr.score,
                "content_preview": sr.entry.content[:120],
                "entry_type": sr.entry.entry_type.value,
                "author": sr.entry.author,
                "project": sr.entry.project,
                "created_at": sr.entry.created_at.isoformat() if sr.entry.created_at else None,
            }
        )

    return success_response(
        {
            "action": result.action.value,
            "highest_score": result.highest_score,
            "reasoning": result.reasoning,
            "similar_entries": similar_entries_serialised,
        }
    )


# ---------------------------------------------------------------------------
# T04.1 tool handler: metrics
# ---------------------------------------------------------------------------

# Default stale threshold: entries not accessed in this many days are "stale".
_DEFAULT_STALE_DAYS = 30


async def _handle_metrics(
    store: Any,
    config: DistilleryConfig,
    embedding_provider: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """
    Aggregate usage and quality metrics from the DuckDB store for the Distillery instance.

    Parameters:
        arguments (dict): Tool arguments; supports optional `period_days` (int) specifying the lookback window in days (must be >= 1). Other parameters are ignored.

    Returns:
        list[types.TextContent]: A single MCP `TextContent` block containing a JSON-serializable dict with aggregated metrics (entries, activity, search, quality, staleness, and storage sections).
    """
    # --- validate period_days -----------------------------------------------
    period_days_raw = arguments.get("period_days", 30)
    err_period = validate_type(arguments, "period_days", int, "integer")
    if err_period:
        return error_response("VALIDATION_ERROR", err_period)
    period_days = int(period_days_raw) if period_days_raw is not None else 30
    if period_days < 1:
        return error_response("VALIDATION_ERROR", "Field 'period_days' must be >= 1")

    try:
        metrics = await asyncio.to_thread(
            _sync_gather_metrics, store, config, embedding_provider, period_days
        )
        return success_response(metrics)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error gathering metrics")
        return error_response("METRICS_ERROR", f"Failed to gather metrics: {exc}")


def _sync_gather_metrics(
    store: Any,
    config: DistilleryConfig,
    embedding_provider: Any,
    period_days: int,
) -> dict[str, Any]:
    """
    Gather comprehensive DuckDB-backed metrics for Distillery.

    Collects entry counts, activity windows, search statistics (if available), feedback quality (if available), staleness estimates, and storage/embedding metadata; missing auxiliary tables yield zeroed metrics.

    Parameters:
        store: Initialized DuckDBStore exposing a live `connection`.
        config: Loaded DistilleryConfig (used for storage path resolution).
        embedding_provider: Active embedding provider (used to report model metadata).
        period_days: Number of days for the "recent" activity/search window.

    Returns:
        A JSON-serializable dict with keys: `entries`, `activity`, `search`, `quality`, `staleness`, and `storage`, each containing aggregated metrics described by their section names.
    """
    conn = store.connection

    # ------------------------------------------------------------------ #
    # entries section                                                      #
    # ------------------------------------------------------------------ #
    total_row = conn.execute("SELECT COUNT(*) FROM entries WHERE status != 'archived'").fetchone()
    total_entries: int = total_row[0] if total_row else 0

    type_rows = conn.execute(
        "SELECT entry_type, COUNT(*) AS cnt FROM entries "
        "WHERE status != 'archived' GROUP BY entry_type ORDER BY cnt DESC"
    ).fetchall()
    by_type = {row[0]: row[1] for row in type_rows}

    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM entries GROUP BY status ORDER BY cnt DESC"
    ).fetchall()
    by_status = {row[0]: row[1] for row in status_rows}

    source_rows = conn.execute(
        "SELECT source, COUNT(*) AS cnt FROM entries "
        "WHERE status != 'archived' GROUP BY source ORDER BY cnt DESC"
    ).fetchall()
    by_source = {row[0]: row[1] for row in source_rows}

    entries_section: dict[str, Any] = {
        "total": total_entries,
        "by_type": by_type,
        "by_status": by_status,
        "by_source": by_source,
    }

    # ------------------------------------------------------------------ #
    # activity section                                                     #
    # ------------------------------------------------------------------ #
    def _count_where(column: str, days: int) -> int:
        """
        Count entries in the `entries` table whose timestamp in the given column is within the past `days`.

        Parameters:
            column (str): Name of a datetime column in the `entries` table (for example `accessed_at`, `updated_at`, or `created_at`).
            days (int): Number of days for the lookback window; rows with `column > CURRENT_TIMESTAMP - days` are counted.

        Returns:
            int: The number of rows matching the condition.
        """
        row = conn.execute(
            f"SELECT COUNT(*) FROM entries "
            f"WHERE {column} > CURRENT_TIMESTAMP - (? * INTERVAL '1 day')",
            [days],
        ).fetchone()
        return row[0] if row else 0

    activity_section: dict[str, Any] = {
        "created_7d": _count_where("created_at", 7),
        "created_30d": _count_where("created_at", 30),
        "created_90d": _count_where("created_at", 90),
        "updated_7d": _count_where("updated_at", 7),
        "updated_30d": _count_where("updated_at", 30),
        "updated_90d": _count_where("updated_at", 90),
        f"created_{period_days}d": _count_where("created_at", period_days),
        f"updated_{period_days}d": _count_where("updated_at", period_days),
    }

    # ------------------------------------------------------------------ #
    # search section (search_log table may not exist yet)                 #
    # ------------------------------------------------------------------ #
    search_section: dict[str, Any] = {
        "total_searches": 0,
        "searches_7d": 0,
        "searches_30d": 0,
        f"searches_{period_days}d": 0,
        "avg_results_per_search": 0.0,
    }
    try:
        _table_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'search_log'"
        ).fetchone()
        if _table_exists and _table_exists[0] > 0:
            total_searches_row = conn.execute("SELECT COUNT(*) FROM search_log").fetchone()
            total_searches: int = total_searches_row[0] if total_searches_row else 0

            def _count_searches(days: int) -> int:
                """
                Count search log entries with timestamps within the last `days` days.

                Parameters:
                    days (int): Number of days to look back from the current time.

                Returns:
                    int: Number of search_log rows with timestamp > now - `days` days.
                """
                r = conn.execute(
                    f"SELECT COUNT(*) FROM search_log "
                    f"WHERE timestamp > CURRENT_TIMESTAMP - INTERVAL '{days} days'"
                ).fetchone()
                return r[0] if r else 0

            avg_row = conn.execute(
                "SELECT AVG(array_length(result_entry_ids)) FROM search_log"
            ).fetchone()
            avg_results = float(avg_row[0]) if avg_row and avg_row[0] is not None else 0.0

            search_section = {
                "total_searches": total_searches,
                "searches_7d": _count_searches(7),
                "searches_30d": _count_searches(30),
                f"searches_{period_days}d": _count_searches(period_days),
                "avg_results_per_search": round(avg_results, 4),
            }
    except Exception:  # noqa: BLE001
        # Table doesn't exist or is not accessible; return zeros.
        pass

    # ------------------------------------------------------------------ #
    # quality section (feedback_log table may not exist yet)              #
    # ------------------------------------------------------------------ #
    quality_section: dict[str, Any] = {
        "total_feedback": 0,
        "feedback_30d": 0,
        "positive_rate": 0.0,
    }
    try:
        _fb_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'feedback_log'"
        ).fetchone()
        if _fb_exists and _fb_exists[0] > 0:
            total_fb_row = conn.execute("SELECT COUNT(*) FROM feedback_log").fetchone()
            total_fb: int = total_fb_row[0] if total_fb_row else 0

            positive_row = conn.execute(
                "SELECT COUNT(*) FROM feedback_log WHERE signal = 'positive'"
            ).fetchone()
            positive_count: int = positive_row[0] if positive_row else 0

            fb_30d_row = conn.execute(
                "SELECT COUNT(*) FROM feedback_log "
                "WHERE timestamp > CURRENT_TIMESTAMP - INTERVAL '30 days'"
            ).fetchone()
            fb_30d: int = fb_30d_row[0] if fb_30d_row else 0

            positive_rate = (positive_count / total_fb) if total_fb > 0 else 0.0

            quality_section = {
                "total_feedback": total_fb,
                "feedback_30d": fb_30d,
                "positive_rate": round(positive_rate, 4),
            }
    except Exception:  # noqa: BLE001
        # Table doesn't exist or is not accessible; return zeros.
        pass

    # ------------------------------------------------------------------ #
    # staleness section                                                    #
    # ------------------------------------------------------------------ #
    stale_days = _DEFAULT_STALE_DAYS

    # accessed_at column may not exist yet (added by T02.1).
    # Fall back to updated_at if the column is absent.
    stale_count = 0
    stale_by_type: dict[str, int] = {}
    try:
        stale_row = conn.execute(
            f"SELECT COUNT(*) FROM entries "
            f"WHERE status != 'archived' "
            f"AND COALESCE(accessed_at, updated_at) < "
            f"CURRENT_TIMESTAMP - INTERVAL '{stale_days} days'"
        ).fetchone()
        stale_count = stale_row[0] if stale_row else 0

        stale_type_rows = conn.execute(
            f"SELECT entry_type, COUNT(*) AS cnt FROM entries "
            f"WHERE status != 'archived' "
            f"AND COALESCE(accessed_at, updated_at) < "
            f"CURRENT_TIMESTAMP - INTERVAL '{stale_days} days' "
            f"GROUP BY entry_type ORDER BY cnt DESC"
        ).fetchall()
        stale_by_type = {row[0]: row[1] for row in stale_type_rows}
    except Exception:  # noqa: BLE001
        # If accessed_at column doesn't exist, try without it.
        try:
            stale_row = conn.execute(
                f"SELECT COUNT(*) FROM entries "
                f"WHERE status != 'archived' "
                f"AND updated_at < CURRENT_TIMESTAMP - INTERVAL '{stale_days} days'"
            ).fetchone()
            stale_count = stale_row[0] if stale_row else 0

            stale_type_rows = conn.execute(
                f"SELECT entry_type, COUNT(*) AS cnt FROM entries "
                f"WHERE status != 'archived' "
                f"AND updated_at < CURRENT_TIMESTAMP - INTERVAL '{stale_days} days' "
                f"GROUP BY entry_type ORDER BY cnt DESC"
            ).fetchall()
            stale_by_type = {row[0]: row[1] for row in stale_type_rows}
        except Exception:  # noqa: BLE001
            pass

    staleness_section: dict[str, Any] = {
        "stale_count": stale_count,
        "stale_days": stale_days,
        "by_type": stale_by_type,
    }

    # ------------------------------------------------------------------ #
    # storage section                                                      #
    # ------------------------------------------------------------------ #
    _raw_db_path = config.storage.database_path
    if _raw_db_path.startswith("s3://") or _raw_db_path.startswith("md:"):
        db_path = _raw_db_path
    else:
        db_path = os.path.expanduser(_raw_db_path)
    db_file_size: int | None = None
    if db_path != ":memory:" and not db_path.startswith("s3://") and not db_path.startswith("md:"):
        try:
            db_file_size = Path(db_path).stat().st_size
        except OSError:
            db_file_size = None

    model_name = getattr(embedding_provider, "model_name", "unknown")
    embedding_dimensions = getattr(embedding_provider, "dimensions", None)

    storage_section: dict[str, Any] = {
        "db_file_size": db_file_size,
        "embedding_model": model_name,
        "embedding_dimensions": embedding_dimensions,
    }

    return {
        "entries": entries_section,
        "activity": activity_section,
        "search": search_section,
        "quality": quality_section,
        "staleness": staleness_section,
        "storage": storage_section,
    }


# ---------------------------------------------------------------------------
# T01.4 tool handler: distillery_quality
# ---------------------------------------------------------------------------


async def _handle_quality(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """
    Aggregate search and feedback metrics and produce a quality summary payload.

    Reads the read-only `search_log` and `feedback_log` tables and computes
    `total_searches`, `total_feedback`, `positive_rate`, `avg_result_count`,
    and an optional `per_type_breakdown`. If `entry_type` is provided in
    `arguments`, results are filtered to that entry type when possible.

    Parameters:
        store: Initialized DuckDBStore providing access to log tables.
        arguments (dict): Tool arguments; accepts optional `entry_type` (str) to filter results.

    Returns:
        list[types.TextContent]: MCP content list with a single JSON `TextContent`
        block containing the computed quality metrics.
    """
    entry_type_filter: str | None = arguments.get("entry_type")

    try:
        result = await asyncio.to_thread(_sync_gather_quality, store, entry_type_filter)
        return success_response(result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error gathering quality metrics")
        return error_response("QUALITY_ERROR", f"Failed to gather quality metrics: {exc}")


def _sync_gather_quality(
    store: Any,
    entry_type_filter: str | None,
) -> dict[str, Any]:
    """
    Compute aggregated quality metrics from the DuckDB-backed store.

    Handles missing `search_log` or `feedback_log` tables by returning zeroed metrics for the missing data.

    Parameters:
        store (DuckDBStore): Initialized store exposing a live `connection` to execute queries against.
        entry_type_filter (str | None): Optional entry-type to include a per-type feedback breakdown.

    Returns:
        dict: A dictionary containing:
            - total_searches (int): Total number of search events (0 if unavailable).
            - total_feedback (int): Total number of feedback records (0 if unavailable).
            - positive_rate (float): Fraction of feedback that is positive, rounded to 4 decimals.
            - avg_result_count (float): Average number of results returned per search, rounded to 4 decimals.
            - per_type_breakdown (dict): Mapping of the provided `entry_type_filter` to a dict with
                `total_feedback`, `positive_count`, and `positive_rate` (rounded to 4 decimals). Empty if no filter provided or data unavailable.
    """
    conn = store.connection

    total_searches = 0
    total_feedback = 0
    positive_count = 0
    avg_result_count = 0.0

    try:
        sl_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'search_log'"
        ).fetchone()
        if sl_exists and sl_exists[0] > 0:
            row = conn.execute("SELECT COUNT(*) FROM search_log").fetchone()
            total_searches = row[0] if row else 0

            avg_row = conn.execute(
                "SELECT AVG(array_length(result_entry_ids)) FROM search_log"
            ).fetchone()
            avg_result_count = float(avg_row[0]) if avg_row and avg_row[0] is not None else 0.0
    except Exception:  # noqa: BLE001
        pass

    try:
        fl_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'feedback_log'"
        ).fetchone()
        if fl_exists and fl_exists[0] > 0:
            row = conn.execute("SELECT COUNT(*) FROM feedback_log").fetchone()
            total_feedback = row[0] if row else 0

            pos_row = conn.execute(
                "SELECT COUNT(*) FROM feedback_log WHERE signal = 'positive'"
            ).fetchone()
            positive_count = pos_row[0] if pos_row else 0
    except Exception:  # noqa: BLE001
        pass

    positive_rate = (positive_count / total_feedback) if total_feedback > 0 else 0.0

    # Per-type breakdown: join feedback_log -> search_log -> entries
    per_type_breakdown: dict[str, Any] = {}
    if entry_type_filter is not None:
        try:
            sl_exists2 = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'search_log'"
            ).fetchone()
            fl_exists2 = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'feedback_log'"
            ).fetchone()
            if (sl_exists2 and sl_exists2[0] > 0) and (fl_exists2 and fl_exists2[0] > 0):
                type_fb_row = conn.execute(
                    "SELECT COUNT(*) FROM feedback_log fl "
                    "JOIN entries e ON fl.entry_id = e.id "
                    "WHERE e.entry_type = ?",
                    [entry_type_filter],
                ).fetchone()
                type_fb = type_fb_row[0] if type_fb_row else 0

                type_pos_row = conn.execute(
                    "SELECT COUNT(*) FROM feedback_log fl "
                    "JOIN entries e ON fl.entry_id = e.id "
                    "WHERE e.entry_type = ? AND fl.signal = 'positive'",
                    [entry_type_filter],
                ).fetchone()
                type_pos = type_pos_row[0] if type_pos_row else 0

                type_rate = (type_pos / type_fb) if type_fb > 0 else 0.0
                per_type_breakdown[entry_type_filter] = {
                    "total_feedback": type_fb,
                    "positive_count": type_pos,
                    "positive_rate": round(type_rate, 4),
                }
        except Exception:  # noqa: BLE001
            pass

    return {
        "total_searches": total_searches,
        "total_feedback": total_feedback,
        "positive_rate": round(positive_rate, 4),
        "avg_result_count": round(avg_result_count, 4),
        "per_type_breakdown": per_type_breakdown,
    }


# ---------------------------------------------------------------------------
# T03.2 tool handler: check_conflicts
# ---------------------------------------------------------------------------


async def _handle_check_conflicts(
    store: Any,
    config: DistilleryConfig,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_check_conflicts`` tool.

    Supports a two-pass workflow:

    **First pass** (``llm_responses`` absent or ``None``):
    - Calls :class:`~distillery.classification.conflict.ConflictChecker` with
      ``llm_responses=None`` to discover candidate entry IDs.
    - Returns ``conflict_candidates`` with a prompt for each candidate pair so
      the calling LLM can evaluate them.

    **Second pass** (``llm_responses`` provided):
    - Converts the supplied ``{entry_id: {is_conflict, reasoning}}`` dict to
      the ``(bool, str)`` tuple format expected by
      :meth:`~distillery.classification.conflict.ConflictChecker.check`.
    - Returns the serialised :class:`~distillery.classification.conflict.ConflictResult`.

    Args:
        store: Initialised store with a ``find_similar`` method.
        config: Loaded :class:`~distillery.config.DistilleryConfig` (conflict
            threshold is read from ``config.classification.conflict_threshold``).
        arguments: Tool argument dict.  Must contain ``"content"`` (str).
            Optionally contains ``"llm_responses"`` (dict).

    Returns:
        MCP content list with a single JSON ``TextContent`` block.
    """
    from distillery.classification.conflict import ConflictChecker

    # --- validate input -----------------------------------------------------
    err = validate_required(arguments, "content")
    if err:
        return error_response("INVALID_INPUT", err)

    content = str(arguments["content"])

    llm_responses_raw: dict[str, Any] | None = arguments.get("llm_responses")
    if llm_responses_raw is not None and not isinstance(llm_responses_raw, dict):
        return error_response("INVALID_INPUT", "Field 'llm_responses' must be an object")

    # --- build checker -------------------------------------------------------
    threshold = config.classification.conflict_threshold
    checker = ConflictChecker(store=store, threshold=threshold)

    # --- first pass: discover candidates (no llm_responses) ------------------
    if not llm_responses_raw:
        try:
            # Call check with no LLM responses to find similar entries.
            await checker.check(content, llm_responses=None)

            # Retrieve similar entries to build prompts for the caller.
            from distillery.classification.conflict import _DEFAULT_CONFLICT_LIMIT

            similar = await store.find_similar(
                content=content,
                threshold=threshold,
                limit=_DEFAULT_CONFLICT_LIMIT,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error during conflict discovery pass")
            return error_response("CONFLICT_ERROR", f"Conflict check failed: {exc}")

        if not similar:
            return success_response(
                {
                    "has_conflicts": False,
                    "conflicts": [],
                    "conflict_candidates": [],
                    "message": "No similar entries found above the conflict threshold.",
                }
            )

        candidates = []
        for result in similar:
            lines = result.entry.content.splitlines()
            preview = lines[0][:120] if lines else result.entry.content[:120]
            prompt = checker.build_prompt(content, result.entry.content)
            candidates.append(
                {
                    "entry_id": result.entry.id,
                    "content_preview": preview,
                    "similarity_score": round(result.score, 4),
                    "conflict_prompt": prompt,
                }
            )

        return success_response(
            {
                "has_conflicts": False,
                "conflicts": [],
                "conflict_candidates": candidates,
                "message": (
                    f"Found {len(candidates)} conflict "
                    f"{'candidate' if len(candidates) == 1 else 'candidates'}. "
                    "Evaluate each conflict_prompt with an LLM and call "
                    "distillery_check_conflicts again with llm_responses."
                ),
            }
        )

    # --- second pass: process LLM responses ----------------------------------
    # Convert {entry_id: {is_conflict: bool, reasoning: str}} ->
    #         {entry_id: (bool, str)}
    llm_responses: dict[str, tuple[bool, str]] = {}
    for entry_id, response_obj in llm_responses_raw.items():
        if not isinstance(response_obj, dict):
            return error_response(
                "INVALID_INPUT",
                f"llm_responses[{entry_id!r}] must be an object with 'is_conflict' and 'reasoning'.",
            )
        is_conflict_raw = response_obj.get("is_conflict")
        if is_conflict_raw is None:
            return error_response(
                "INVALID_INPUT",
                f"llm_responses[{entry_id!r}] is missing required field 'is_conflict'.",
            )
        reasoning = str(response_obj.get("reasoning", ""))
        llm_responses[str(entry_id)] = (bool(is_conflict_raw), reasoning)

    try:
        result = await checker.check(content, llm_responses=llm_responses)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error during conflict evaluation pass")
        return error_response("CONFLICT_ERROR", f"Conflict check failed: {exc}")

    # Serialise ConflictResult.
    conflicts_serialised = [
        {
            "entry_id": conflict.entry_id,
            "content_preview": conflict.content_preview,
            "similarity_score": round(conflict.similarity_score, 4),
            "conflict_reasoning": conflict.conflict_reasoning,
        }
        for conflict in result.conflicts
    ]

    return success_response(
        {
            "has_conflicts": result.has_conflicts,
            "conflicts": conflicts_serialised,
        }
    )


# ---------------------------------------------------------------------------
# T02.2 tool handler: distillery_stale
# ---------------------------------------------------------------------------


async def _handle_stale(
    store: Any,
    config: DistilleryConfig,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_stale`` tool.

    Returns entries that have not been accessed within the configured
    staleness window.  An entry's last access time is determined by
    ``COALESCE(accessed_at, updated_at)`` so that entries without an
    explicit access timestamp fall back to their last modification time.

    Args:
        store: Initialised :class:`~distillery.store.duckdb.DuckDBStore`.
        config: The loaded Distillery configuration.
        arguments: Tool argument dict.  Accepts optional ``days`` (int),
            ``limit`` (int), and ``entry_type`` (str).

    Returns:
        MCP content list with a single JSON ``TextContent`` block.
    """
    # --- validate days -------------------------------------------------------
    err_days = validate_type(arguments, "days", int, "integer")
    if err_days:
        return error_response("VALIDATION_ERROR", err_days)
    days_raw = arguments.get("days")
    days: int = int(days_raw) if days_raw is not None else config.classification.stale_days
    if days < 1:
        return error_response("VALIDATION_ERROR", "Field 'days' must be >= 1")

    # --- validate limit -------------------------------------------------------
    err_limit = validate_type(arguments, "limit", int, "integer")
    if err_limit:
        return error_response("VALIDATION_ERROR", err_limit)
    limit_raw = arguments.get("limit")
    limit: int = int(limit_raw) if limit_raw is not None else 20
    if limit < 1:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be >= 1")

    # --- validate entry_type -------------------------------------------------
    entry_type_filter: str | None = arguments.get("entry_type")
    if entry_type_filter is not None and not isinstance(entry_type_filter, str):
        return error_response("VALIDATION_ERROR", "Field 'entry_type' must be a string")

    try:
        stale_entries = await asyncio.to_thread(
            _sync_gather_stale, store, days, limit, entry_type_filter
        )
        return success_response(
            {
                "days_threshold": days,
                "entry_type_filter": entry_type_filter,
                "stale_count": len(stale_entries),
                "entries": stale_entries,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error gathering stale entries")
        return error_response("STALE_ERROR", f"Failed to gather stale entries: {exc}")


def _sync_gather_stale(
    store: Any,
    days: int,
    limit: int,
    entry_type_filter: str | None,
) -> list[dict[str, Any]]:
    """
    Return entries whose last access (accessed_at or updated_at) is older than the given number of days.

    Parameters:
        store (Any): Initialized DuckDBStore used to query entries.
        days (int): Staleness threshold in days; entries last accessed strictly earlier than now - days are returned.
        limit (int): Maximum number of entries to return.
        entry_type_filter (str | None): Optional entry_type value to restrict results to a single type.

    Returns:
        list[dict[str, Any]]: List of stale entry summaries ordered stalest-first. Each dict contains:
            - id: entry identifier
            - content_preview: first 200 characters of the content (empty string if content is None)
            - entry_type: entry type string
            - author: author string
            - project: project string or None
            - last_accessed: ISO 8601 timestamp string of the last access or None
            - days_since_access: integer days since last access or None
    """
    conn = store.connection

    params: list[Any] = [days]
    type_clause = ""
    if entry_type_filter is not None:
        type_clause = " AND entry_type = ?"
        params.append(entry_type_filter)
    params.append(limit)

    sql = f"""
        SELECT
            id,
            content,
            entry_type,
            author,
            project,
            COALESCE(accessed_at, updated_at) AS last_accessed
        FROM entries
        WHERE status != 'archived'
          AND COALESCE(accessed_at, updated_at) < NOW() - INTERVAL (CAST(? AS INT)) DAYS
          {type_clause}
        ORDER BY last_accessed ASC
        LIMIT ?
    """

    rows = conn.execute(sql, params).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        entry_id, content, entry_type, author, project, last_accessed = row
        content_preview = (content or "")[:200]
        # Calculate days since access
        if last_accessed is not None:
            from datetime import datetime

            if hasattr(last_accessed, "tzinfo") and last_accessed.tzinfo is None:
                last_accessed_aware = last_accessed.replace(tzinfo=UTC)
            else:
                last_accessed_aware = last_accessed
            now = datetime.now(UTC)
            days_since = (now - last_accessed_aware).days
            last_accessed_iso = last_accessed_aware.isoformat()
        else:
            days_since = None
            last_accessed_iso = None

        result.append(
            {
                "id": entry_id,
                "content_preview": content_preview,
                "entry_type": entry_type,
                "author": author,
                "project": project,
                "last_accessed": last_accessed_iso,
                "days_since_access": days_since,
            }
        )

    return result
