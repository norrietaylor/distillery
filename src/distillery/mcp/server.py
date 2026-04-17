"""MCP server for Distillery — 16 tools over stdio or HTTP.

Handlers live in ``src/distillery/mcp/tools/`` (crud, search, classify, quality,
analytics, feeds, configure, meta). This module owns: FastMCP app creation,
lifespan, shared-state init, tool registration wrappers, and middleware
composition.

Feed-management tools (poll, rescore) have been moved to REST webhook
endpoints. Type schemas are exposed as an MCP resource.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast

from fastmcp import Context, FastMCP  # noqa: F401
from mcp import types

from distillery.config import DistilleryConfig, load_config
from distillery.mcp.tools._common import (
    _get_authenticated_user,
    error_response,
    success_response,  # noqa: F401 — re-exported for test_mcp_server.py
)
from distillery.mcp.tools.analytics import (
    _handle_type_schemas,
)
from distillery.mcp.tools.classify import (
    _handle_classify,
    _handle_resolve_review,
)
from distillery.mcp.tools.configure import _handle_configure
from distillery.mcp.tools.crud import (
    _handle_correct,
    _handle_get,
    _handle_list,
    _handle_store,
    _handle_update,
    _normalize_db_path,  # re-exported for webhooks.py backward compat
)
from distillery.mcp.tools.crud import (
    _handle_store_batch as _handle_crud_store_batch,
)
from distillery.mcp.tools.feeds import (
    _handle_gh_sync,
    _handle_poll,
    _handle_rescore,
    _handle_sync_status,
    _handle_watch,
)
from distillery.mcp.tools.feeds import (
    _handle_store_batch as _handle_feed_store_batch,
)
from distillery.mcp.tools.meta import _handle_status
from distillery.mcp.tools.quality import (
    run_conflict_discovery,
    run_conflict_evaluation,
    run_dedup_check,
)
from distillery.mcp.tools.relations import _handle_relations
from distillery.mcp.tools.search import (
    _handle_find_similar,
    _handle_search,
)

logger = logging.getLogger(__name__)

_UNSET: Any = object()

# Explicit re-exports for mypy --strict (no_implicit_reexport).
__all__ = [
    "create_server",
    "error_response",
    "success_response",
    "_get_authenticated_user",
    "_normalize_db_path",
    "_create_embedding_provider",
    "_handle_configure",
    "_handle_store",
    "_handle_get",
    "_handle_update",
    "_handle_correct",
    "_handle_list",
    "_handle_search",
    "_handle_find_similar",
    "_handle_classify",
    "_handle_resolve_review",
    "run_dedup_check",
    "run_conflict_discovery",
    "run_conflict_evaluation",
    "_handle_type_schemas",
    "_handle_watch",
    "_handle_poll",
    "_handle_rescore",
    "_handle_gh_sync",
    "_handle_crud_store_batch",
    "_handle_feed_store_batch",
    "_handle_sync_status",
    "_handle_relations",
    "_handle_status",
]


def _omit_none(**kw: Any) -> dict[str, Any]:
    """Return kwargs with None values removed."""
    return {k: v for k, v in kw.items() if v is not None}


def _create_embedding_provider(config: DistilleryConfig) -> Any:
    """Instantiate an EmbeddingProvider from config."""
    n, m, d, e = (
        config.embedding.provider,
        config.embedding.model,
        config.embedding.dimensions,
        config.embedding.api_key_env,
    )
    key = os.environ.get(e) if e else None
    if n == "jina":
        from distillery.embedding.jina import JinaEmbeddingProvider

        return JinaEmbeddingProvider(
            api_key=key, api_key_env=e or "JINA_API_KEY", model=m, dimensions=d
        )
    if n == "openai":
        from distillery.embedding.openai import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider(
            api_key=key, api_key_env=e or "OPENAI_API_KEY", model=m, dimensions=d
        )
    if n == "mock":
        from distillery.mcp._stub_embedding import HashEmbeddingProvider

        return HashEmbeddingProvider(dimensions=d)
    if n == "":
        from distillery.mcp._stub_embedding import StubEmbeddingProvider

        return StubEmbeddingProvider(dimensions=d)
    raise ValueError(
        f"Unsupported embedding provider: {n!r}. Must be one of: 'jina', 'openai', 'mock'."
    )


def create_server(config: DistilleryConfig | None = None, auth: Any | None = None) -> FastMCP:
    """Build and return the configured FastMCP server instance.

    Args:
        config: Pre-loaded configuration; ``None`` loads from standard locations.
        auth: Optional authentication provider (e.g. ``GitHubProvider``).

    Returns:
        A fully decorated :class:`~fastmcp.FastMCP` instance ready to run.
    """
    if config is None:
        config = load_config()
    _shared: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        if not _shared:
            logger.info("Distillery MCP server starting up …")
            ep = _create_embedding_provider(config)
            raw = config.storage.database_path
            db = raw if raw.startswith(("s3://", "md:")) else os.path.expanduser(raw)
            if db.startswith("md:"):
                tok = os.environ.get(config.storage.motherduck_token_env)
                if tok:
                    os.environ["MOTHERDUCK_TOKEN"] = tok
                else:
                    logger.warning(
                        "motherduck_token_env %r not set in environment",
                        config.storage.motherduck_token_env,
                    )
            from distillery.store.duckdb import DuckDBStore

            store = DuckDBStore(
                db_path=db,
                embedding_provider=ep,
                s3_region=config.storage.s3_region,
                s3_endpoint=config.storage.s3_endpoint,
            )
            await store.initialize()
            if await store.get_metadata("feeds_seeded") != "true":
                for src in config.feeds.sources:
                    with contextlib.suppress(ValueError):
                        await store.add_feed_source(
                            url=src.url,
                            source_type=src.source_type,
                            label=src.label,
                            poll_interval_minutes=src.poll_interval_minutes,
                            trust_weight=src.trust_weight,
                        )
                await store.set_metadata("feeds_seeded", "true")
            _shared.update(store=store, config=config, embedding_provider=ep)
            # Record startup timestamp for distillery_status uptime reporting.
            # Stored in shared state (not replaced on subsequent lifespan entries
            # for stateless HTTP sessions).
            if "started_at" not in _shared:
                _shared["started_at"] = datetime.now(UTC)
            logger.info(
                "Distillery MCP server ready (db=%s, embedding=%s)",
                db,
                getattr(ep, "model_name", "unknown"),
            )
        else:
            logger.debug("Reusing existing Distillery store (stateless session)")
        try:
            yield dict(_shared)
        finally:
            _store = _shared.get("store")
            if _store is not None and hasattr(_store, "close"):
                logger.info("Shutting down — closing DuckDB (WAL checkpoint) …")
                await _store.close()
                logger.info("DuckDB closed cleanly")

    server = FastMCP("distillery", lifespan=lifespan, auth=auth)
    server._distillery_shared = _shared  # type: ignore[attr-defined]

    def _lc(ctx: Context) -> dict[str, Any]:
        """Extract the lifespan context dict from a FastMCP Context."""
        try:
            lc = ctx.lifespan_context
            if isinstance(lc, dict):
                return lc
        except AttributeError:
            pass
        rc = getattr(ctx, "request_context", None)
        if rc is not None:
            lc_v2 = getattr(rc, "lifespan_context", None)
            if lc_v2 is not None and isinstance(lc_v2, dict):
                return cast(dict[str, Any], lc_v2)
        raise RuntimeError("Cannot access lifespan context — verify FastMCP version compatibility.")

    async def _own(
        lc: dict[str, Any], user: str, eid: str, op: str
    ) -> list[types.TextContent] | None:
        """Ownership guard — returns error response on violation, None on pass."""
        if not user:
            return None
        try:
            existing = await lc["store"].get(eid)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ownership pre-check failed for entry %s", eid)
            return error_response("INTERNAL", f"Failed to read entry: {exc}")
        if existing is None:
            await lc["store"].write_audit_log(user, op, eid, op, "not_found")
            return error_response("NOT_FOUND", f"No entry found with id={eid!r}.")
        if existing.created_by and existing.created_by != user:
            await lc["store"].write_audit_log(user, op, eid, op, "forbidden")
            return error_response(
                "FORBIDDEN", f"User {user!r} cannot modify entry owned by {existing.created_by!r}."
            )
        return None

    async def _audit(
        lc: dict[str, Any],
        user: str,
        op: str,
        eid: str,
        action: str,
        result: list[types.TextContent],
    ) -> None:
        """Write audit log entry (best-effort)."""
        try:
            rd = json.loads(result[0].text) if result else {}
            await lc["store"].write_audit_log(
                user, op, eid, action, "error" if rd.get("error") else "success"
            )
        except Exception:  # noqa: BLE001
            logger.debug("audit_log write failed for %s (ignored)", op, exc_info=True)

    @server.tool
    async def distillery_store(  # noqa: PLR0913
        ctx: Context,
        content: str,
        entry_type: str,
        author: str,
        project: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        source: str | None = None,
        session_id: str | None = None,
        dedup_threshold: float | None = None,
        dedup_limit: int | None = None,
        verification: str | None = None,
        expires_at: str | None = _UNSET,
        output_mode: str | None = None,
    ) -> list[types.TextContent]:
        """Store a new knowledge entry and return its ID with dedup/conflict information.

        USE WHEN: capturing a new piece of knowledge (session notes, bookmarks,
        meeting minutes, ideas, etc.) into the Distillery store.

        PARAMS:
          - content (str, required): The knowledge content to store.
          - entry_type (str, required): Entry classification. Valid: [session, bookmark,
            minutes, meeting, reference, idea, inbox, github, person, project, digest, feed].
          - author (str, required): Who authored this entry.
          - project (str, optional): Project scope for the entry.
          - tags (list[str], optional): Tags for categorisation; supports namespaced tags (e.g. "topic/ai").
          - metadata (dict, optional): Arbitrary key-value metadata.
          - source (str, optional, default="claude-code"): Origin of the entry.
            Valid: [claude-code, manual, import, inference, documentation, external].
          - session_id (str, optional): Opaque session identifier for grouping related entries.
          - dedup_threshold (float, optional, default=config): Cosine similarity threshold (0-1)
            for near-duplicate warnings.
          - dedup_limit (int, optional, default=config): Max duplicates to report.
          - verification (str, optional, default="unverified"): Verification status.
            Valid: [unverified, testing, verified].
          - expires_at (str, optional): ISO 8601 datetime; entries past expiry appear in stale results.
          - output_mode (str, optional, default="full"): Response verbosity.
            Valid: [full, summary]. Use "summary" for bulk imports to skip dedup/conflict checks.

        RETURNS (success): { entry_id: str, warnings?: list, conflict_candidates?: list }
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "BUDGET_EXCEEDED" | "INTERNAL", message: "..." }

        RELATED: distillery_find_similar (for pre-store dedup checks),
        distillery_correct (to supersede an existing entry)
        """
        c = _lc(ctx)
        user = _get_authenticated_user()
        args: dict[str, Any] = dict(
            content=content,
            entry_type=entry_type,
            author=author,
            **_omit_none(
                project=project,
                tags=tags,
                metadata=metadata,
                source=source,
                session_id=session_id,
                dedup_threshold=dedup_threshold,
                dedup_limit=dedup_limit,
                verification=verification,
                output_mode=output_mode,
            ),
        )
        if expires_at is not _UNSET:
            args["expires_at"] = expires_at
        result = await _handle_store(
            store=c["store"], arguments=args, cfg=c["config"], created_by=user
        )
        rd = json.loads(result[0].text) if result else {}
        await _audit(c, user, "distillery_store", rd.get("entry_id", ""), "store", result)
        return result

    @server.tool
    async def distillery_store_batch(
        ctx: Context,
        entries: list[dict[str, Any]],
        project: str | None = None,
    ) -> list[types.TextContent]:
        """Batch-store multiple knowledge entries in one call (no dedup/conflict checks).

        USE WHEN: bulk-importing entries (e.g. GitHub history sync, migration,
        backfill) where per-entry dedup is unnecessary and throughput matters.

        PARAMS:
          - entries (list[dict], required): List of entry dicts. Each must have:
              - content (str, required): The knowledge content.
              - author (str, required): Who authored this entry.
              - entry_type (str, optional, default="inbox"): Entry classification.
                Valid: [session, bookmark, minutes, meeting, reference, idea,
                inbox, github, person, project, digest, feed].
              - tags (list[str], optional): Tags for categorisation.
              - metadata (dict, optional): Arbitrary key-value metadata.
              - source (str, optional, default="claude-code"): Origin of the entry.
              - project (str, optional): Per-entry project override.
          - project (str, optional): Default project applied to entries lacking one.

        RETURNS (success): { entry_ids: list[str], count: int }
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "BUDGET_EXCEEDED" | "INTERNAL", message: "..." }

        RELATED: distillery_store (single entry with dedup/conflict checks),
        distillery_watch (add feed sources with optional history sync)
        """
        c = _lc(ctx)
        user = _get_authenticated_user()
        args: dict[str, Any] = {"entries": entries}
        if project is not None:
            args["project"] = project
        result = await _handle_crud_store_batch(
            store=c["store"], arguments=args, cfg=c["config"], created_by=user
        )
        # Mirror the attribution/audit pattern used by other mutating wrappers
        # (distillery_store, distillery_update, distillery_correct,
        # distillery_resolve_review) so batch imports are not unaudited.
        rd = json.loads(result[0].text) if result else {}
        entry_ids = rd.get("entry_ids", []) or []
        if entry_ids:
            for entry_id in entry_ids:
                await _audit(c, user, "distillery_store_batch", entry_id, "store", result)
        else:
            await _audit(c, user, "distillery_store_batch", "", "store", result)
        return result

    @server.tool
    async def distillery_get(ctx: Context, entry_id: str) -> list[types.TextContent]:
        """Retrieve a single knowledge entry by its unique ID.

        USE WHEN: fetching the full content and metadata of a specific entry
        (e.g. after finding its ID via search or list).

        PARAMS:
          - entry_id (str, required): UUID of the entry to retrieve.

        RETURNS (success): { id: str, content: str, entry_type: str, ... }
        RETURNS (error): { error: true, code: "NOT_FOUND" | "INTERNAL", message: "..." }

        RELATED: distillery_search (to find entries by content),
        distillery_list (to browse entries by filters)
        """
        c = _lc(ctx)
        return await _handle_get(
            store=c["store"], arguments={"entry_id": entry_id}, config=c["config"]
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
        verification: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        expires_at: str | None = _UNSET,
    ) -> list[types.TextContent]:
        """Update one or more fields on an existing knowledge entry.

        USE WHEN: modifying an entry's content, type, tags, status, or other
        mutable fields. At least one updatable field must be provided.

        PARAMS:
          - entry_id (str, required): UUID of the entry to update.
          - content (str, optional): Replacement content.
          - entry_type (str, optional): New type. Valid: [session, bookmark, minutes,
            meeting, reference, idea, inbox, github, person, project, digest, feed].
          - author (str, optional): New author.
          - project (str, optional): New project scope.
          - tags (list[str], optional): Replacement tag list.
          - status (str, optional): New status. Valid: [active, pending_review, archived].
          - verification (str, optional): New verification. Valid: [unverified, testing, verified].
          - metadata (dict, optional): Replacement metadata dict.
          - session_id (str, optional): Session identifier for grouping.
          - expires_at (str, optional): ISO 8601 datetime; pass null to clear.

        RETURNS (success): { id: str, content: str, entry_type: str, ... } (full updated entry)
        RETURNS (error): { error: true, code: "NOT_FOUND" | "INVALID_PARAMS" | "FORBIDDEN" | "INTERNAL", message: "..." }

        RELATED: distillery_correct (to supersede rather than edit),
        distillery_get (to read before updating)
        """
        c = _lc(ctx)
        user = _get_authenticated_user()
        err = await _own(c, user, entry_id, "distillery_update")
        if err:
            return err
        args: dict[str, Any] = dict(
            entry_id=entry_id,
            **_omit_none(
                content=content,
                entry_type=entry_type,
                author=author,
                project=project,
                tags=tags,
                status=status,
                verification=verification,
                metadata=metadata,
                session_id=session_id,
            ),
        )
        if expires_at is not _UNSET:
            args["expires_at"] = expires_at
        result = await _handle_update(store=c["store"], arguments=args, last_modified_by=user)
        await _audit(c, user, "distillery_update", entry_id, "update", result)
        return result

    @server.tool
    async def distillery_correct(  # noqa: PLR0913
        ctx: Context,
        wrong_entry_id: str,
        content: str,
        entry_type: str | None = None,
        author: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[types.TextContent]:
        """Store a correction that supersedes an existing entry.

        USE WHEN: an existing entry contains wrong information and you want to
        replace it with corrected content while preserving the audit trail.

        PARAMS:
          - wrong_entry_id (str, required): UUID of the entry being corrected.
          - content (str, required): The corrected content.
          - entry_type (str, optional): Override type; inherited from original if omitted.
            Valid: [session, bookmark, minutes, meeting, reference, idea, inbox,
            github, person, project, digest, feed].
          - author (str, optional): Override author; inherited from original if omitted.
          - project (str, optional): Override project; inherited from original if omitted.
          - tags (list[str], optional): Override tags; inherited from original if omitted.
          - metadata (dict, optional): Additional metadata for the correction entry.

        RETURNS (success): { correction_entry_id: str, archived_entry_id: str }
        RETURNS (error): { error: true, code: "NOT_FOUND" | "INVALID_PARAMS" | "FORBIDDEN" | "INTERNAL", message: "..." }

        RELATED: distillery_update (for non-breaking edits),
        distillery_relations (to view the 'corrects' relation)
        """
        c = _lc(ctx)
        user = _get_authenticated_user()
        err = await _own(c, user, wrong_entry_id, "distillery_correct")
        if err:
            return err
        args: dict[str, Any] = dict(
            wrong_entry_id=wrong_entry_id,
            content=content,
            **_omit_none(
                entry_type=entry_type,
                author=author,
                project=project,
                tags=tags,
                metadata=metadata,
            ),
        )
        result = await _handle_correct(
            store=c["store"], arguments=args, cfg=c["config"], created_by=user
        )
        rd = json.loads(result[0].text) if result else {}
        await _audit(
            c,
            user,
            "distillery_correct",
            rd.get("correction_entry_id", ""),
            "correct",
            result,
        )
        return result

    @server.tool
    async def distillery_list(  # noqa: PLR0913
        ctx: Context,
        entry_type: str | None = None,
        author: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        verification: str | None = None,
        source: str | None = None,
        session_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
        offset: int = 0,
        tag_prefix: str | None = None,
        output_mode: str = "summary",
        content_max_length: int | None = None,
        stale_days: int | None = None,
        group_by: str | None = None,
        output: str | None = None,
        feed_url: str | None = None,
        include_archived: bool = False,
    ) -> list[types.TextContent]:
        """List knowledge entries with optional filters and pagination (newest first).

        USE WHEN: browsing or filtering entries without a semantic query.
        Use distillery_search instead when you have a natural-language question.

        By default, only entries with status in (active, pending_review) are
        returned — archived entries are hidden. Pass ``status="archived"`` to
        list only archived entries, ``status="any"`` to include every status,
        or ``include_archived=true`` to add archived entries to the default view.

        PARAMS:
          - entry_type (str, optional): Filter by type. Valid: [session, bookmark, minutes,
            meeting, reference, idea, inbox, github, person, project, digest, feed].
          - author (str, optional): Filter by author.
          - project (str, optional): Filter by project scope.
          - tags (list[str], optional): Filter by tags (AND match).
          - status (str, optional): Filter by status. Valid: [active, pending_review,
            archived, any]. Default hides archived; use "any" to include all.
          - verification (str, optional): Filter by verification. Valid: [unverified, testing, verified].
          - source (str, optional): Filter by origin. Valid: [claude-code, manual, import,
            inference, documentation, external].
          - session_id (str, optional): Filter by session identifier.
          - date_from (str, optional): ISO 8601 lower bound on created_at.
          - date_to (str, optional): ISO 8601 upper bound on created_at.
          - limit (int, optional, default=20): Max entries to return (1-500).
          - offset (int, optional, default=0): Pagination offset.
          - tag_prefix (str, optional): Filter tags by namespace prefix.
          - output_mode (str, optional, default="summary"): Response shape.
            Valid: [full, summary, ids, review]. "summary" returns id/title/tags/project/
            author/created_at plus a ~200-char content_preview (default — keeps responses
            small to conserve context). "full" returns entire content body. "ids" returns
            id/entry_type/created_at only. "review" filters to pending_review and enriches
            with confidence/classification_reasoning.
          - content_max_length (int, optional): Truncate content to N chars (full mode only).
          - stale_days (int, optional): Restrict to entries not accessed in N days (>= 1).
          - group_by (str, optional): Return grouped counts instead of entries.
            Valid: [entry_type, status, author, project, source, tags].
            Mutually exclusive with output="stats".
          - output (str, optional): Set to "stats" for aggregate statistics.
            Mutually exclusive with group_by.
          - feed_url (str, optional): Filter to entries ingested from a registered feed
            source URL (matches metadata.source_url written by the poller). Use this to
            retrieve all items polled from e.g. "https://hnrss.org/frontpage".
          - include_archived (bool, optional, default=False): Include archived entries
            in the default view (same effect as status="any" when status is unset).

        RETURNS (success): { entries: list, count: int, total_count: int, limit: int, offset: int }
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "INTERNAL", message: "..." }

        RELATED: distillery_search (for semantic search),
        distillery_status (for lightweight server health/metadata)
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(
            limit=limit,
            offset=offset,
            output_mode=output_mode,
            include_archived=include_archived,
            **_omit_none(
                entry_type=entry_type,
                author=author,
                project=project,
                tags=tags,
                status=status,
                verification=verification,
                source=source,
                session_id=session_id,
                date_from=date_from,
                date_to=date_to,
                tag_prefix=tag_prefix,
                content_max_length=content_max_length,
                stale_days=stale_days,
                group_by=group_by,
                output=output,
                feed_url=feed_url,
            ),
        )
        return await _handle_list(store=c["store"], arguments=args)

    @server.tool
    async def distillery_search(  # noqa: PLR0913
        ctx: Context,
        query: str,
        entry_type: str | None = None,
        author: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        source: str | None = None,
        session_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
        tag_prefix: str | None = None,
        include_archived: bool = False,
    ) -> list[types.TextContent]:
        """Search knowledge entries using semantic similarity (cosine distance, ranked descending).

        USE WHEN: finding entries that match a natural-language question or topic.
        Each result includes a similarity score (0-1, higher is more relevant).

        By default, only entries with status in (active, pending_review) are
        considered — archived entries are hidden. Pass ``status="archived"``
        to search only archived entries, ``status="any"`` to include every
        status, or ``include_archived=true`` to add archived entries to the
        default candidate set.

        PARAMS:
          - query (str, required): Natural-language search query.
          - entry_type (str, optional): Filter by type.
          - author (str, optional): Filter by author.
          - project (str, optional): Filter by project scope.
          - tags (list[str], optional): Filter by tags (AND match).
          - status (str, optional): Filter by status.
          - source (str, optional): Filter by origin.
          - session_id (str, optional): Filter by session identifier.
          - date_from (str, optional): ISO 8601 lower bound.
          - date_to (str, optional): ISO 8601 upper bound.
          - limit (int, optional, default=10): Max results (1-200).
          - tag_prefix (str, optional): Filter tags by namespace prefix.
          - include_archived (bool, optional, default=False): Include archived entries
            in the candidate set.

        RETURNS (success): { results: [{ score: float, entry: {...} }], count: int }
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "BUDGET_EXCEEDED" | "INTERNAL", message: "..." }

        RELATED: distillery_list (for filter-based browsing without semantic ranking),
        distillery_find_similar (to compare against arbitrary text)
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(
            query=query,
            limit=limit,
            include_archived=include_archived,
            **_omit_none(
                entry_type=entry_type,
                author=author,
                project=project,
                tags=tags,
                status=status,
                source=source,
                session_id=session_id,
                date_from=date_from,
                date_to=date_to,
                tag_prefix=tag_prefix,
            ),
        )
        return await _handle_search(store=c["store"], arguments=args, cfg=c["config"])

    @server.tool
    async def distillery_find_similar(  # noqa: PLR0913
        ctx: Context,
        content: str,
        threshold: float = 0.8,
        limit: int = 10,
        dedup_action: bool = False,
        conflict_check: bool = False,
        llm_responses: list[dict[str, Any]] | None = None,
    ) -> list[types.TextContent]:
        """Find stored entries similar to the given text (cosine similarity).

        USE WHEN: checking for duplicates or conflicts before storing, or finding
        entries related to arbitrary text. Supports progressive disclosure modes.

        PARAMS:
          - content (str, required): Text to compare against stored entries.
          - threshold (float, optional, default=0.8): Cosine similarity cutoff (0-1).
          - limit (int, optional, default=10): Max results (1-200).
          - dedup_action (bool, optional, default=false): When true, includes dedup
            check with recommended action (create/skip/merge/link).
          - conflict_check (bool, optional, default=false): When true, includes
            conflict candidates with LLM evaluation prompts.
          - llm_responses (list[dict], optional): With conflict_check=true, evaluates
            LLM conflict verdicts. Each item: { entry_id: str, is_conflict: bool, reasoning: str }.

        RETURNS (success): { results: [{ score: float, entry: {...} }], count: int, threshold: float,
          dedup?: { action: str, similar_entries: list },
          conflict_candidates?: list, conflict_evaluation?: dict }
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "BUDGET_EXCEEDED" | "INTERNAL", message: "..." }

        RELATED: distillery_store (stores with automatic dedup/conflict checks),
        distillery_search (for natural-language queries)
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(
            content=content,
            threshold=threshold,
            limit=limit,
            dedup_action=dedup_action,
            conflict_check=conflict_check,
            **_omit_none(llm_responses=llm_responses),
        )
        return await _handle_find_similar(store=c["store"], cfg=c["config"], arguments=args)

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
        """Apply a pre-computed classification to an existing entry.

        USE WHEN: you have determined an entry's type and confidence via LLM
        or heuristic analysis and want to persist the classification result.

        PARAMS:
          - entry_id (str, required): UUID of the entry to classify.
          - entry_type (str, required): Assigned type. Valid: [session, bookmark, minutes,
            meeting, reference, idea, inbox, github, person, project, digest, feed].
          - confidence (float, required): Classification confidence (0-1). Entries below
            the configured threshold (default 0.6) go to pending_review.
          - reasoning (str, optional): Explanation of the classification decision.
          - suggested_tags (list[str], optional): Tags to merge onto the entry.
          - suggested_project (str, optional): Project to assign if entry has none.

        RETURNS (success): { id: str, entry_type: str, status: str, ... } (full updated entry)
        RETURNS (error): { error: true, code: "NOT_FOUND" | "INVALID_PARAMS" | "INTERNAL", message: "..." }

        RELATED: distillery_resolve_review (to act on pending_review entries),
        distillery_list (with output_mode="review" to see the review queue)
        """
        c = _lc(ctx)
        user = _get_authenticated_user()
        err = await _own(c, user, entry_id, "distillery_classify")
        if err:
            return err
        args: dict[str, Any] = dict(
            entry_id=entry_id,
            entry_type=entry_type,
            confidence=confidence,
            **_omit_none(
                reasoning=reasoning,
                suggested_tags=suggested_tags,
                suggested_project=suggested_project,
            ),
        )
        return await _handle_classify(store=c["store"], config=c["config"], arguments=args)

    @server.tool
    async def distillery_resolve_review(  # noqa: PLR0913
        ctx: Context,
        entry_id: str,
        action: str,
        new_entry_type: str | None = None,
        reviewer: str | None = None,
    ) -> list[types.TextContent]:
        """Resolve a pending-review entry by approving, reclassifying, or archiving it.

        USE WHEN: acting on entries in the review queue (entries with
        status=pending_review from low-confidence classifications).

        PARAMS:
          - entry_id (str, required): UUID of the pending-review entry.
          - action (str, required): Resolution action. Valid: [approve, reclassify, archive].
          - new_entry_type (str, optional): Required when action="reclassify".
            Valid: [session, bookmark, minutes, meeting, reference, idea, inbox,
            github, person, project, digest, feed].
          - reviewer (str, optional): Reviewer identity for audit metadata.

        RETURNS (success): { id: str, status: str, ... } (full updated entry)
        RETURNS (error): { error: true, code: "NOT_FOUND" | "INVALID_PARAMS" | "FORBIDDEN" | "INTERNAL", message: "..." }

        RELATED: distillery_classify (to classify entries),
        distillery_list (with output_mode="review" to see the queue)
        """
        c = _lc(ctx)
        user = _get_authenticated_user()
        err = await _own(c, user, entry_id, "distillery_resolve_review")
        if err:
            return err
        args: dict[str, Any] = dict(
            entry_id=entry_id, action=action, **_omit_none(new_entry_type=new_entry_type)
        )
        # Pass actor (server identity) and reviewer (client-supplied) as
        # distinct fields so the handler can record both ``reviewed_by`` and
        # ``on_behalf_of`` when they differ (issue #315).
        if user:
            args["actor"] = user
        if reviewer is not None:
            args["reviewer"] = reviewer
        result = await _handle_resolve_review(store=c["store"], arguments=args)
        await _audit(c, user, "distillery_resolve_review", entry_id, action, result)
        return result

    @server.tool
    async def distillery_watch(  # noqa: PLR0913
        ctx: Context,
        action: str,
        url: str | None = None,
        source_type: str | None = None,
        label: str | None = None,
        poll_interval_minutes: int | None = None,
        trust_weight: float | None = None,
        sync_history: bool = False,
        purge: bool = False,
        probe: bool = True,
        force: bool = False,
    ) -> list[types.TextContent]:
        """Manage monitored feed sources for ambient intelligence.

        USE WHEN: listing, adding, or removing RSS/GitHub feed sources
        that Distillery polls for new content.

        PARAMS:
          - action (str, required): Operation to perform. Valid: [list, add, remove].
          - url (str, required for add/remove): Feed URL or GitHub owner/repo slug.
          - source_type (str, required for add): Feed type. Valid: [rss, github].
          - label (str, optional): Human-readable label for the source.
          - poll_interval_minutes (int, optional, default=60): Polling frequency in minutes.
          - trust_weight (float, optional, default=1.0): Source trust weight (0-1).
          - sync_history (bool, optional, default=false): When true and source_type is
            "github", kicks off an async background import of historical issues/PRs
            (returns immediately with job_id; use distillery_sync_status to check progress).
          - purge (bool, optional, default=false): When true and action is "remove",
            archives all entries from the removed source (soft-delete). Returns the
            count of archived entries in purged_entries.
          - probe (bool, optional, default=true): When adding, lightly probe the URL
            for reachability (HEAD with GET fallback, short timeout). Returns an
            UNREACHABLE_URL error if the probe fails.
          - force (bool, optional, default=false): When adding, persist the source
            even if the reachability probe fails (useful for sites that block HEAD
            but work via the poller).

        RETURNS (success): { sources: list, count: int } (list) or
          { added: dict, sources: list, sync_job?: dict } (add) or
          { removed_url: str, removed: bool, sources: list, purged_entries?: int } (remove)
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "CONFLICT" | "INVALID_URL"
          | "UNREACHABLE_URL" | "INTERNAL", message: "..." }

        RELATED: distillery_configure (to adjust feed thresholds),
        distillery_store_batch (for bulk entry ingestion)
        """
        c = _lc(ctx)
        return await _handle_watch(
            store=c["store"],
            arguments=dict(
                action=action,
                probe=probe,
                force=force,
                **_omit_none(
                    url=url,
                    source_type=source_type,
                    label=label,
                    poll_interval_minutes=poll_interval_minutes,
                    trust_weight=trust_weight,
                    sync_history=sync_history or None,
                    purge=purge or None,
                ),
            ),
        )

    @server.tool
    async def distillery_relations(  # noqa: PLR0913
        ctx: Context,
        action: str,
        from_id: str | None = None,
        to_id: str | None = None,
        relation_type: str | None = None,
        entry_id: str | None = None,
        direction: str = "both",
        relation_id: str | None = None,
    ) -> list[types.TextContent]:
        """Manage typed relations between knowledge entries.

        USE WHEN: linking entries together (e.g. marking one as blocking another,
        citing a reference, or flagging duplicates).

        PARAMS:
          - action (str, required): Operation. Valid: [add, get, remove].
          - from_id (str, required for add): Source entry UUID.
          - to_id (str, required for add): Target entry UUID.
          - relation_type (str, required for add, optional for get): Relation type.
            Valid: [link, corrects, supersedes, related, blocks, depends_on, citation, duplicate].
          - entry_id (str, required for get): Entry UUID to query relations for.
          - direction (str, optional for get, default="both"): Filter direction.
            Valid: [outgoing, incoming, both].
          - relation_id (str, required for remove): UUID of the relation to delete.

        RETURNS (success): { relation_id: str, from_id: str, to_id: str, relation_type: str } (add) or
          { entry_id: str, relations: list, count: int } (get) or
          { relation_id: str, removed: bool } (remove)
        RETURNS (error): { error: true, code: "NOT_FOUND" | "INVALID_PARAMS" | "INTERNAL", message: "..." }

        RELATED: distillery_correct (creates 'corrects' relations automatically),
        distillery_find_similar (to discover related entries)
        """
        c = _lc(ctx)
        return await _handle_relations(
            store=c["store"],
            arguments=dict(
                action=action,
                **_omit_none(
                    from_id=from_id,
                    to_id=to_id,
                    relation_type=relation_type,
                    entry_id=entry_id,
                    direction=direction,
                    relation_id=relation_id,
                ),
            ),
        )

    @server.tool
    async def distillery_gh_sync(
        ctx: Context,
        url: str,
        author: str = "gh-sync",
        project: str | None = None,
        background: bool = False,
    ) -> list[types.TextContent]:
        """Sync GitHub issues and PRs into the knowledge base using a batched pipeline.

        url: repository slug (owner/repo) or full GitHub URL.
        author: author field for created entries (default: gh-sync).
        project: optional project name to scope entries.
        background: when true, runs async and returns a job_id immediately.
        """
        c = _lc(ctx)
        return await _handle_gh_sync(
            store=c["store"],
            arguments=dict(
                url=url, author=author, **_omit_none(project=project, background=background or None)
            ),
        )

    @server.tool
    async def distillery_sync_status(
        ctx: Context,
        job_id: str | None = None,
        source_url: str | None = None,
    ) -> list[types.TextContent]:
        """Check the status of background sync jobs.

        job_id: look up a specific job by ID.
        source_url: list jobs for a specific source URL.
        If neither is provided, lists all recent jobs.
        """
        return await _handle_sync_status(arguments=_omit_none(job_id=job_id, source_url=source_url))

    @server.tool
    async def distillery_configure(
        ctx: Context,
        section: str,
        key: str,
        value: str | int | float | None = None,
    ) -> list[types.TextContent]:
        """Read or update a runtime configuration value.

        USE WHEN: reading current thresholds/settings, or adjusting them
        at runtime without editing the config file directly.

        PARAMS:
          - section (str, required): Config section path (dotted notation).
            Valid: [feeds.thresholds, defaults, classification].
          - key (str, required): Config key within the section.
            Valid keys by section: feeds.thresholds: [alert, digest];
            defaults: [dedup_threshold, dedup_limit, stale_days];
            classification: [confidence_threshold, mode].
          - value (str | int | float | None, optional): New value. Omit to read
            the current value. When provided, must satisfy type and range
            constraints for the given key.

        RETURNS (read): { section: str, key: str, value: any, message: str }
        RETURNS (write): { changed: bool, section: str, key: str, previous_value: any,
          new_value: any, disk_written: bool, message: str }
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "INTERNAL", message: "..." }

        RELATED: distillery_watch (to manage feed sources),
        distillery_status (to review current system state)
        """
        c = _lc(ctx)
        return await _handle_configure(
            config=c["config"],
            arguments={"section": section, "key": key, "value": value},
        )

    @server.tool
    async def distillery_status(ctx: Context) -> list[types.TextContent]:
        """Return a lightweight in-protocol health/metadata probe.

        USE WHEN: verifying MCP connectivity (e.g. from the ``/setup`` wizard)
        without relying on the HTTP-only ``/health`` endpoint. Works uniformly
        on stdio and HTTP transports.

        PARAMS: (none)

        RETURNS (success): {
            status: "ok",
            version: str,                 # distillery package version
            build_sha: str,               # git SHA (or "dev")
            transport: "stdio" | "http" | "unknown",
            tool_count: int,              # number of registered MCP tools
            store: { entry_count: int | null, db_size_bytes: int | null },
            embedding_provider: str,      # model name or provider class name
            last_feed_poll: { source_count: int, last_poll_at: str | null },
            uptime_seconds?: int          # seconds since server startup
        }

        RELATED: distillery_list (for entry counts, filtering, and
        per-group aggregates),
        distillery_configure (to inspect/adjust runtime configuration)
        """
        c = _lc(ctx)
        try:
            tools = await server.list_tools()
            tool_count = len(tools)
        except Exception:  # noqa: BLE001
            logger.debug("distillery_status: server.list_tools() failed", exc_info=True)
            tool_count = 0
        # Read transport from _shared (set by __main__.py post-construction);
        # fall back to the lifespan-scoped copy if present.
        transport = _shared.get("transport") or c.get("transport")
        started_at = _shared.get("started_at") or c.get("started_at")
        return await _handle_status(
            store=c["store"],
            config=c["config"],
            embedding_provider=c["embedding_provider"],
            tool_count=tool_count,
            transport=transport,
            started_at=started_at,
        )

    @server.resource("distillery://schemas/entry-types")
    async def entry_type_schemas() -> str:
        """Return the metadata schemas for all structured entry types as a JSON resource.

        Replaces the former ``distillery_type_schemas`` tool.  Clients read this
        resource to discover the required/optional metadata fields and constraints
        for each entry type (session, bookmark, minutes, meeting, reference, idea,
        inbox, plus any structured types with richer schemas).
        """
        result = await _handle_type_schemas()
        return result[0].text if result else "{}"

    return server


def __getattr__(name: str) -> FastMCP:
    """Lazy module-level attribute for FastMCP auto-discovery (PEP 562).

    ``fastmcp run src/distillery/mcp/server.py`` looks for ``mcp``, ``server``, or ``app``.
    """
    if name in ("mcp", "server", "app"):
        instance = create_server()
        globals()[name] = instance
        return instance
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
