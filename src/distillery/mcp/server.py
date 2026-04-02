"""MCP server for Distillery — 22 tools over stdio or HTTP.

Handlers live in ``src/distillery/mcp/tools/`` (crud, search, classify, quality,
analytics, feeds, meta). This module owns: FastMCP app creation, lifespan,
shared-state init, tool registration wrappers, and middleware composition.
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
    _normalize_db_path,  # re-exported for webhooks.py backward compat
)
from distillery.mcp.tools.feeds import (
    _handle_poll,
    _handle_rescore,
    _handle_suggest_sources,
    _handle_watch,
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

# Explicit re-exports for mypy --strict (no_implicit_reexport).
__all__ = [
    "create_server", "error_response", "success_response",
    "_get_authenticated_user", "_normalize_db_path", "_create_embedding_provider",
    "_handle_status", "_handle_store", "_handle_get", "_handle_update", "_handle_list",
    "_handle_search", "_handle_find_similar", "_handle_aggregate",
    "_handle_classify", "_handle_review_queue", "_handle_resolve_review",
    "_handle_check_dedup", "_handle_check_conflicts",
    "_handle_metrics", "_handle_quality", "_handle_stale",
    "_handle_tag_tree", "_handle_interests", "_handle_type_schemas",
    "_handle_watch", "_handle_poll", "_handle_rescore", "_handle_suggest_sources",
]


def _omit_none(**kw: Any) -> dict[str, Any]:
    """Return kwargs with None values removed."""
    return {k: v for k, v in kw.items() if v is not None}


def _create_embedding_provider(config: DistilleryConfig) -> Any:
    """Instantiate an EmbeddingProvider from config."""
    n, m, d, e = config.embedding.provider, config.embedding.model, config.embedding.dimensions, config.embedding.api_key_env
    key = os.environ.get(e) if e else None
    if n == "jina":
        from distillery.embedding.jina import JinaEmbeddingProvider
        return JinaEmbeddingProvider(api_key=key, api_key_env=e or "JINA_API_KEY", model=m, dimensions=d)
    if n == "openai":
        from distillery.embedding.openai import OpenAIEmbeddingProvider
        return OpenAIEmbeddingProvider(api_key=key, api_key_env=e or "OPENAI_API_KEY", model=m, dimensions=d)
    if n == "mock":
        from distillery.mcp._stub_embedding import HashEmbeddingProvider
        return HashEmbeddingProvider(dimensions=d)
    if n == "":
        from distillery.mcp._stub_embedding import StubEmbeddingProvider
        return StubEmbeddingProvider(dimensions=d)
    raise ValueError(f"Unsupported embedding provider: {n!r}. Must be one of: 'jina', 'openai', 'mock'.")


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
                    logger.warning("motherduck_token_env %r not set in environment",
                                   config.storage.motherduck_token_env)
            from distillery.store.duckdb import DuckDBStore
            store = DuckDBStore(db_path=db, embedding_provider=ep,
                                s3_region=config.storage.s3_region,
                                s3_endpoint=config.storage.s3_endpoint)
            await store.initialize()
            if await store.get_metadata("feeds_seeded") != "true":
                for src in config.feeds.sources:
                    with contextlib.suppress(ValueError):
                        await store.add_feed_source(
                            url=src.url, source_type=src.source_type, label=src.label,
                            poll_interval_minutes=src.poll_interval_minutes,
                            trust_weight=src.trust_weight)
                await store.set_metadata("feeds_seeded", "true")
            _shared.update(store=store, config=config, embedding_provider=ep)
            logger.info("Distillery MCP server ready (db=%s, embedding=%s)", db,
                        getattr(ep, "model_name", "unknown"))
        else:
            logger.debug("Reusing existing Distillery store (stateless session)")
        try:
            yield dict(_shared)
        finally:
            pass

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

    async def _own(lc: dict[str, Any], user: str, eid: str, op: str) -> list[types.TextContent] | None:
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
            return error_response("FORBIDDEN", f"User {user!r} cannot modify entry owned by {existing.created_by!r}.")
        return None

    async def _audit(lc: dict[str, Any], user: str, op: str, eid: str, action: str,
                     result: list[types.TextContent]) -> None:
        """Write audit log entry (best-effort)."""
        try:
            rd = json.loads(result[0].text) if result else {}
            await lc["store"].write_audit_log(user, op, eid, action, "error" if rd.get("error") else "success")
        except Exception:  # noqa: BLE001
            logger.debug("audit_log write failed for %s (ignored)", op, exc_info=True)

    @server.tool
    async def distillery_status(ctx: Context) -> list[types.TextContent]:
        """Return database and embedding model statistics for the Distillery store."""
        c = _lc(ctx)
        return await _handle_status(store=c["store"], embedding_provider=c["embedding_provider"], config=c["config"])

    @server.tool
    async def distillery_store(  # noqa: PLR0913
        ctx: Context, content: str, entry_type: str, author: str,
        project: str | None = None, tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        dedup_threshold: float = _DEFAULT_DEDUP_THRESHOLD,
        dedup_limit: int = _DEFAULT_DEDUP_LIMIT,
    ) -> list[types.TextContent]:
        """Store a new knowledge entry and return its ID with dedup/conflict information.

        entry_type must be one of: session, bookmark, minutes, meeting, reference,
        idea, inbox. dedup_threshold (0–1) controls near-duplicate warnings.
        """
        c = _lc(ctx)
        user = _get_authenticated_user()
        args: dict[str, Any] = dict(content=content, entry_type=entry_type, author=author,
                                    dedup_threshold=dedup_threshold, dedup_limit=dedup_limit,
                                    **_omit_none(project=project, tags=tags, metadata=metadata))
        result = await _handle_store(store=c["store"], arguments=args, cfg=c["config"], created_by=user)
        rd = json.loads(result[0].text) if result else {}
        await _audit(c, user, "distillery_store", rd.get("entry_id", ""), "store", result)
        return result

    @server.tool
    async def distillery_get(ctx: Context, entry_id: str) -> list[types.TextContent]:
        """Retrieve a knowledge entry by ID; returns NOT_FOUND error if missing."""
        c = _lc(ctx)
        return await _handle_get(store=c["store"], arguments={"entry_id": entry_id}, config=c["config"])

    @server.tool
    async def distillery_update(  # noqa: PLR0913
        ctx: Context, entry_id: str, content: str | None = None,
        entry_type: str | None = None, author: str | None = None,
        project: str | None = None, tags: list[str] | None = None,
        status: str | None = None, metadata: dict[str, Any] | None = None,
    ) -> list[types.TextContent]:
        """Update one or more fields on an existing knowledge entry.

        At least one field must be provided. status: active, pending_review, or archived.
        entry_type: session, bookmark, minutes, meeting, reference, idea, or inbox.
        """
        c = _lc(ctx)
        user = _get_authenticated_user()
        err = await _own(c, user, entry_id, "distillery_update")
        if err:
            return err
        args: dict[str, Any] = dict(entry_id=entry_id, **_omit_none(
            content=content, entry_type=entry_type, author=author,
            project=project, tags=tags, status=status, metadata=metadata))
        result = await _handle_update(store=c["store"], arguments=args, last_modified_by=user)
        await _audit(c, user, "distillery_update", entry_id, "update", result)
        return result

    @server.tool
    async def distillery_list(  # noqa: PLR0913
        ctx: Context, entry_type: str | None = None, author: str | None = None,
        project: str | None = None, tags: list[str] | None = None,
        status: str | None = None, date_from: str | None = None,
        date_to: str | None = None, limit: int = 20, offset: int = 0,
        tag_prefix: str | None = None, output_mode: str = "full",
        content_max_length: int | None = None,
    ) -> list[types.TextContent]:
        """List knowledge entries with optional filters and pagination (newest first).

        date_from/date_to accept ISO 8601. output_mode: "full" (default), "summary", "ids".
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(limit=limit, offset=offset, output_mode=output_mode,
                                    **_omit_none(entry_type=entry_type, author=author,
                                                 project=project, tags=tags, status=status,
                                                 date_from=date_from, date_to=date_to,
                                                 tag_prefix=tag_prefix,
                                                 content_max_length=content_max_length))
        return await _handle_list(store=c["store"], arguments=args)

    @server.tool
    async def distillery_aggregate(  # noqa: PLR0913
        ctx: Context, group_by: str, entry_type: str | None = None,
        status: str | None = None, date_from: str | None = None,
        date_to: str | None = None, tag_prefix: str | None = None, limit: int = 50,
    ) -> list[types.TextContent]:
        """Aggregate entry counts grouped by a field (entry_type, status, author, project, source, etc.)."""
        c = _lc(ctx)
        args: dict[str, Any] = dict(group_by=group_by, limit=limit, **_omit_none(
            entry_type=entry_type, status=status, date_from=date_from,
            date_to=date_to, tag_prefix=tag_prefix))
        return await _handle_aggregate(store=c["store"], arguments=args)

    @server.tool
    async def distillery_search(  # noqa: PLR0913
        ctx: Context, query: str, entry_type: str | None = None,
        author: str | None = None, project: str | None = None,
        tags: list[str] | None = None, status: str | None = None,
        date_from: str | None = None, date_to: str | None = None,
        limit: int = 10, tag_prefix: str | None = None,
    ) -> list[types.TextContent]:
        """Search the knowledge store using semantic similarity (cosine, ranked descending).

        limit 1–200. date_from/date_to accept ISO 8601. tag_prefix filters by namespace.
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(query=query, limit=limit, **_omit_none(
            entry_type=entry_type, author=author, project=project, tags=tags,
            status=status, date_from=date_from, date_to=date_to, tag_prefix=tag_prefix))
        return await _handle_search(store=c["store"], arguments=args, cfg=c["config"])

    @server.tool
    async def distillery_find_similar(
        ctx: Context, content: str, threshold: float = 0.8, limit: int = 10,
    ) -> list[types.TextContent]:
        """Find stored entries similar to the given text. threshold: cosine cutoff (0–1). limit 1–200."""
        c = _lc(ctx)
        return await _handle_find_similar(store=c["store"], cfg=c["config"],
                                          arguments={"content": content, "threshold": threshold, "limit": limit})

    @server.tool
    async def distillery_classify(  # noqa: PLR0913
        ctx: Context, entry_id: str, entry_type: str, confidence: float,
        reasoning: str | None = None, suggested_tags: list[str] | None = None,
        suggested_project: str | None = None,
    ) -> list[types.TextContent]:
        """Apply a pre-computed classification to an existing entry.

        entry_type: session, bookmark, minutes, meeting, reference, idea, or inbox.
        confidence (0–1) determines the updated entry status.
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(entry_id=entry_id, entry_type=entry_type, confidence=confidence,
                                    **_omit_none(reasoning=reasoning, suggested_tags=suggested_tags,
                                                 suggested_project=suggested_project))
        return await _handle_classify(store=c["store"], config=c["config"], arguments=args)

    @server.tool
    async def distillery_review_queue(
        ctx: Context, entry_type: str | None = None, limit: int = 20,
    ) -> list[types.TextContent]:
        """List entries awaiting human review after classification. limit 1–500."""
        c = _lc(ctx)
        return await _handle_review_queue(store=c["store"],
                                          arguments=dict(limit=limit, **_omit_none(entry_type=entry_type)))

    @server.tool
    async def distillery_resolve_review(  # noqa: PLR0913
        ctx: Context, entry_id: str, action: str,
        new_entry_type: str | None = None, reviewer: str | None = None,
    ) -> list[types.TextContent]:
        """Resolve a pending-review entry: action is "approve", "reclassify", or "archive".

        new_entry_type required when action is "reclassify".
        """
        c = _lc(ctx)
        user = _get_authenticated_user()
        err = await _own(c, user, entry_id, "distillery_resolve_review")
        if err:
            return err
        args: dict[str, Any] = dict(entry_id=entry_id, action=action,
                                    **_omit_none(new_entry_type=new_entry_type))
        eff_reviewer = user or reviewer
        if eff_reviewer is not None:
            args["reviewer"] = eff_reviewer
        result = await _handle_resolve_review(store=c["store"], arguments=args)
        await _audit(c, user, "distillery_resolve_review", entry_id, action, result)
        return result

    @server.tool
    async def distillery_check_dedup(ctx: Context, content: str) -> list[types.TextContent]:
        """Check content for duplicates; returns recommended action + similar entries."""
        c = _lc(ctx)
        return await _handle_check_dedup(store=c["store"], config=c["config"], arguments={"content": content})

    @server.tool
    async def distillery_check_conflicts(
        ctx: Context, content: str, llm_responses: dict[str, Any] | None = None,
    ) -> list[types.TextContent]:
        """Check for conflicts between content and existing entries (two-pass workflow).

        First pass: returns conflict_candidates with prompts for LLM evaluation.
        Second pass (with llm_responses {entry_id: {is_conflict, reasoning}}): returns has_conflicts.
        """
        c = _lc(ctx)
        return await _handle_check_conflicts(store=c["store"], config=c["config"],
                                             arguments=dict(content=content, **_omit_none(llm_responses=llm_responses)))

    @server.tool
    async def distillery_metrics(ctx: Context, period_days: int = 30) -> list[types.TextContent]:
        """Return usage metrics and statistics for the knowledge store. period_days >= 1."""
        c = _lc(ctx)
        return await _handle_metrics(store=c["store"], config=c["config"],
                                     embedding_provider=c["embedding_provider"],
                                     arguments={"period_days": period_days})

    @server.tool
    async def distillery_quality(ctx: Context, entry_type: str | None = None) -> list[types.TextContent]:
        """Return aggregated search-quality metrics (search counts, feedback rates)."""
        c = _lc(ctx)
        return await _handle_quality(store=c["store"], arguments=_omit_none(entry_type=entry_type))

    @server.tool
    async def distillery_stale(
        ctx: Context, days: int | None = None, limit: int = 20, entry_type: str | None = None,
    ) -> list[types.TextContent]:
        """Return stale entries based on last-access time. days defaults to config stale_days."""
        c = _lc(ctx)
        return await _handle_stale(store=c["store"], config=c["config"],
                                   arguments=dict(limit=limit, **_omit_none(days=days, entry_type=entry_type)))

    @server.tool
    async def distillery_tag_tree(ctx: Context, prefix: str | None = None) -> list[types.TextContent]:
        """Return a nested tag hierarchy with entry counts. prefix filters by namespace."""
        c = _lc(ctx)
        return await _handle_tag_tree(store=c["store"], arguments={"prefix": prefix})

    @server.tool
    async def distillery_type_schemas(ctx: Context) -> list[types.TextContent]:  # noqa: ARG001
        """Return the metadata schemas for all structured entry types."""
        return await _handle_type_schemas()

    @server.tool
    async def distillery_watch(  # noqa: PLR0913
        ctx: Context, action: str, url: str | None = None, source_type: str | None = None,
        label: str | None = None, poll_interval_minutes: int | None = None,
        trust_weight: float | None = None,
    ) -> list[types.TextContent]:
        """Manage monitored feed sources: action is "list", "add", or "remove".

        add requires url and source_type (rss or github). remove requires url.
        """
        c = _lc(ctx)
        return await _handle_watch(store=c["store"], arguments=dict(action=action, **_omit_none(
            url=url, source_type=source_type, label=label,
            poll_interval_minutes=poll_interval_minutes, trust_weight=trust_weight)))

    @server.tool
    async def distillery_interests(
        ctx: Context, recency_days: int = 90, top_n: int = 20,
    ) -> list[types.TextContent]:
        """Extract an interest profile (top tags, bookmark domains, tracked repos) from the knowledge base."""
        c = _lc(ctx)
        return await _handle_interests(store=c["store"], config=c["config"],
                                       arguments={"recency_days": recency_days, "top_n": top_n})

    @server.tool
    async def distillery_suggest_sources(  # noqa: PLR0913
        ctx: Context, max_suggestions: int = 5, source_types: list[str] | None = None,
        recency_days: int = 90, top_n: int = 20,
    ) -> list[types.TextContent]:
        """Suggest new feed sources to monitor based on the user's interest profile.

        Returns suggestions with rationales and a suggestion_context for LLM prompting.
        source_types filters by adapter type: rss or github.
        """
        c = _lc(ctx)
        return await _handle_suggest_sources(store=c["store"], config=c["config"],
                                             arguments=dict(max_suggestions=max_suggestions,
                                                            recency_days=recency_days, top_n=top_n,
                                                            **_omit_none(source_types=source_types)))

    @server.tool
    async def distillery_poll(ctx: Context, source_url: str | None = None) -> list[types.TextContent]:
        """Poll configured feed sources and store relevant items. source_url polls one; None polls all."""
        c = _lc(ctx)
        return await _handle_poll(store=c["store"], config=c["config"],
                                  arguments=_omit_none(source_url=source_url))

    @server.tool
    async def distillery_rescore(ctx: Context, limit: int = 100) -> list[types.TextContent]:
        """Re-score existing feed entries against the current knowledge base."""
        c = _lc(ctx)
        return await _handle_rescore(store=c["store"], config=c["config"], arguments={"limit": limit})

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
