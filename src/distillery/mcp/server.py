"""MCP server for Distillery — 17 tools over stdio or HTTP.

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
    _handle_interests,
    _handle_metrics,
    _handle_stale,
    _handle_tag_tree,
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
from distillery.mcp.tools.feeds import (
    _handle_poll,
    _handle_rescore,
    _handle_watch,
)
from distillery.mcp.tools.quality import (
    run_conflict_discovery,
    run_conflict_evaluation,
    run_dedup_check,
)
from distillery.mcp.tools.relations import _handle_relations
from distillery.mcp.tools.search import (
    _handle_aggregate,
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
    "_handle_aggregate",
    "_handle_classify",
    "_handle_resolve_review",
    "run_dedup_check",
    "run_conflict_discovery",
    "run_conflict_evaluation",
    "_handle_metrics",
    "_handle_stale",
    "_handle_tag_tree",
    "_handle_interests",
    "_handle_type_schemas",
    "_handle_watch",
    "_handle_poll",
    "_handle_rescore",
    "_handle_relations",
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
            return error_response("STORE_ERROR", f"Failed to read entry: {exc}")
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
        output_mode: str = "full",
        content_max_length: int | None = None,
        stale_days: int | None = None,
        group_by: str | None = None,
        output: str | None = None,
    ) -> list[types.TextContent]:
        """List knowledge entries with optional filters and pagination (newest first).

        USE WHEN: browsing or filtering entries without a semantic query.
        Use distillery_search instead when you have a natural-language question.

        PARAMS:
          - entry_type (str, optional): Filter by type. Valid: [session, bookmark, minutes,
            meeting, reference, idea, inbox, github, person, project, digest, feed].
          - author (str, optional): Filter by author.
          - project (str, optional): Filter by project scope.
          - tags (list[str], optional): Filter by tags (AND match).
          - status (str, optional): Filter by status. Valid: [active, pending_review, archived].
          - verification (str, optional): Filter by verification. Valid: [unverified, testing, verified].
          - source (str, optional): Filter by origin. Valid: [claude-code, manual, import,
            inference, documentation, external].
          - session_id (str, optional): Filter by session identifier.
          - date_from (str, optional): ISO 8601 lower bound on created_at.
          - date_to (str, optional): ISO 8601 upper bound on created_at.
          - limit (int, optional, default=20): Max entries to return (1-500).
          - offset (int, optional, default=0): Pagination offset.
          - tag_prefix (str, optional): Filter tags by namespace prefix.
          - output_mode (str, optional, default="full"): Response shape.
            Valid: [full, summary, ids, review]. "review" filters to pending_review
            and enriches with confidence/classification_reasoning.
          - content_max_length (int, optional): Truncate content to N chars (full mode only).
          - stale_days (int, optional): Restrict to entries not accessed in N days (>= 1).
          - group_by (str, optional): Return grouped counts instead of entries.
            Valid: [entry_type, status, author, project, source, tags].
            Mutually exclusive with output="stats".
          - output (str, optional): Set to "stats" for aggregate statistics.
            Mutually exclusive with group_by.

        RETURNS (success): { entries: list, count: int, total_count: int, limit: int, offset: int }
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "INTERNAL", message: "..." }

        RELATED: distillery_search (for semantic search),
        distillery_aggregate (for count-by-group analytics)
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(
            limit=limit,
            offset=offset,
            output_mode=output_mode,
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
    ) -> list[types.TextContent]:
        """Search knowledge entries using semantic similarity (cosine distance, ranked descending).

        USE WHEN: finding entries that match a natural-language question or topic.
        Each result includes a similarity score (0-1, higher is more relevant).

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

        RETURNS (success): { results: [{ score: float, entry: {...} }], count: int }
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "BUDGET_EXCEEDED" | "INTERNAL", message: "..." }

        RELATED: distillery_list (for filter-based browsing without semantic ranking),
        distillery_find_similar (to compare against arbitrary text)
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(
            query=query,
            limit=limit,
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
        eff_reviewer = user or reviewer
        if eff_reviewer is not None:
            args["reviewer"] = eff_reviewer
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

        RETURNS (success): { sources: list, count: int } (list) or
          { added: dict, sources: list } (add) or
          { removed_url: str, removed: bool, sources: list } (remove)
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "CONFLICT" | "INTERNAL", message: "..." }

        RELATED: distillery_interests (to discover sources to watch),
        distillery_configure (to adjust feed thresholds)
        """
        c = _lc(ctx)
        return await _handle_watch(
            store=c["store"],
            arguments=dict(
                action=action,
                **_omit_none(
                    url=url,
                    source_type=source_type,
                    label=label,
                    poll_interval_minutes=poll_interval_minutes,
                    trust_weight=trust_weight,
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
    async def distillery_configure(
        ctx: Context,
        section: str,
        key: str,
        value: str | int | float,
    ) -> list[types.TextContent]:
        """Update a runtime configuration value and persist it to distillery.yaml.

        USE WHEN: adjusting thresholds, classification settings, or feed
        parameters at runtime without editing the config file directly.

        PARAMS:
          - section (str, required): Config section path (dotted notation).
            Valid: [feeds.thresholds, defaults, classification].
          - key (str, required): Config key within the section.
            Valid keys by section: feeds.thresholds: [alert, digest];
            defaults: [dedup_threshold, dedup_limit, stale_days];
            classification: [confidence_threshold, mode].
          - value (str | int | float, required): New value. Must satisfy type and
            range constraints for the given key.

        RETURNS (success): { changed: bool, section: str, key: str, previous_value: any,
          new_value: any, disk_written: bool, message: str }
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "INTERNAL", message: "..." }

        RELATED: distillery_watch (to manage feed sources),
        distillery_metrics (to review current system state)
        """
        c = _lc(ctx)
        return await _handle_configure(
            config=c["config"],
            arguments={"section": section, "key": key, "value": value},
        )

    @server.tool
    async def distillery_aggregate(
        ctx: Context,
        group_by: str,
        limit: int = 50,
        entry_type: str | None = None,
        author: str | None = None,
        project: str | None = None,
        status: str | None = None,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[types.TextContent]:
        """Count entries grouped by a field, without fetching full payloads.

        USE WHEN: getting a quick overview of how entries are distributed
        across types, statuses, authors, projects, or sources.

        PARAMS:
          - group_by (str, required): Field to group by.
            Valid: [entry_type, status, author, project, source,
            metadata.source_url, metadata.source_type].
          - limit (int, optional, default=50): Max groups to return (1-500).
          - entry_type (str, optional): Filter by type.
          - author (str, optional): Filter by author.
          - project (str, optional): Filter by project.
          - status (str, optional): Filter by status.
          - source (str, optional): Filter by origin.
          - date_from (str, optional): ISO 8601 lower bound.
          - date_to (str, optional): ISO 8601 upper bound.

        RETURNS (success): { group_by: str, groups: dict, total_entries: int, total_groups: int }
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "INTERNAL", message: "..." }

        RELATED: distillery_list (for entry-level browsing),
        distillery_metrics (for comprehensive system metrics)
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(
            group_by=group_by,
            limit=limit,
            **_omit_none(
                entry_type=entry_type,
                author=author,
                project=project,
                status=status,
                source=source,
                date_from=date_from,
                date_to=date_to,
            ),
        )
        return await _handle_aggregate(store=c["store"], arguments=args)

    @server.tool
    async def distillery_metrics(
        ctx: Context,
        scope: str = "full",
        period_days: int = 30,
        entry_type: str | None = None,
        date_from: str | None = None,
        user: str | None = None,
    ) -> list[types.TextContent]:
        """Aggregate usage, quality, and audit metrics from the Distillery instance.

        USE WHEN: reviewing system health, search quality, staleness, or
        audit trails. Supports scoped views for different use cases.

        PARAMS:
          - scope (str, optional, default="full"): Metrics view.
            Valid: [summary, full, search_quality, audit].
          - period_days (int, optional, default=30): Lookback window in days (>= 1, full scope only).
          - entry_type (str, optional): Filter by type (search_quality scope only).
          - date_from (str, optional): ISO 8601 lower bound (audit scope only).
          - user (str, optional): Filter by user (audit scope only).

        RETURNS (success): varies by scope — summary: counts + storage;
          full: entries + activity + search + quality + staleness + storage;
          search_quality: totals + feedback rates; audit: logins + operations.
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "INTERNAL", message: "..." }

        RELATED: distillery_aggregate (for count-by-group breakdowns),
        distillery_stale (for detailed stale entry listing)
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(
            scope=scope,
            period_days=period_days,
            **_omit_none(
                entry_type=entry_type,
                date_from=date_from,
                user=user,
            ),
        )
        return await _handle_metrics(
            store=c["store"],
            config=c["config"],
            embedding_provider=c["embedding_provider"],
            arguments=args,
        )

    @server.tool
    async def distillery_stale(
        ctx: Context,
        days: int | None = None,
        limit: int = 20,
        entry_type: str | None = None,
    ) -> list[types.TextContent]:
        """List entries not accessed within a staleness window, plus expired entries.

        USE WHEN: identifying knowledge that may need refreshing, archiving,
        or reviewing due to age or expiration.

        PARAMS:
          - days (int, optional, default=config.defaults.stale_days): Staleness
            threshold in days (>= 1).
          - limit (int, optional, default=20): Max entries to return.
          - entry_type (str, optional): Filter by type.

        RETURNS (success): { days_threshold: int, stale_count: int, expired_count: int,
          entries: [{ id: str, content_preview: str, reason: "stale" | "expired", ... }] }
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "INTERNAL", message: "..." }

        RELATED: distillery_metrics (for staleness aggregates),
        distillery_list (with stale_days filter)
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(
            limit=limit,
            **_omit_none(days=days, entry_type=entry_type),
        )
        return await _handle_stale(store=c["store"], config=c["config"], arguments=args)

    @server.tool
    async def distillery_tag_tree(
        ctx: Context,
        prefix: str | None = None,
    ) -> list[types.TextContent]:
        """Build a nested tag hierarchy from active entries.

        USE WHEN: exploring the tag namespace structure, understanding how
        entries are categorised, or discovering tag conventions.

        PARAMS:
          - prefix (str, optional): Root the tree at this tag prefix (e.g. "topic").

        RETURNS (success): { tree: { count: int, children: { ... } }, prefix: str | null }
        RETURNS (error): { error: true, code: "INTERNAL", message: "..." }

        RELATED: distillery_list (with tag_prefix filter),
        distillery_aggregate (for flat tag counts)
        """
        c = _lc(ctx)
        return await _handle_tag_tree(store=c["store"], arguments={"prefix": prefix})

    @server.tool
    async def distillery_interests(  # noqa: PLR0913
        ctx: Context,
        recency_days: int = 90,
        top_n: int = 20,
        suggest_sources: bool = False,
        max_suggestions: int = 5,
    ) -> list[types.TextContent]:
        """Build an interest profile from stored entries, optionally suggesting feed sources.

        USE WHEN: understanding what topics and repositories are tracked, or
        discovering new feed sources to watch based on existing knowledge.

        PARAMS:
          - recency_days (int, optional, default=90): How far back to look for entries.
          - top_n (int, optional, default=20): Max top tags to include in the profile.
          - suggest_sources (bool, optional, default=false): When true, includes
            heuristic feed source suggestions based on the profile.
          - max_suggestions (int, optional, default=5): Max suggestions to return.

        RETURNS (success): { top_tags: list, bookmark_domains: list, tracked_repos: list,
          expertise_areas: list, entry_count: int, suggestions?: list }
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "INTERNAL", message: "..." }

        RELATED: distillery_watch (to act on suggested sources),
        distillery_tag_tree (to explore tag structure)
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(
            recency_days=recency_days,
            top_n=top_n,
            suggest_sources=suggest_sources,
            max_suggestions=max_suggestions,
        )
        return await _handle_interests(store=c["store"], config=c["config"], arguments=args)

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
