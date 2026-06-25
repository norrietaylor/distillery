"""MCP server for Distillery — consolidated tool surface over stdio or HTTP.

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
from collections.abc import AsyncIterator, Awaitable, Callable
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
    validate_classify_schema,
    validate_resolve_review_schema,
)
from distillery.mcp.tools.configure import _handle_configure
from distillery.mcp.tools.crud import (
    _handle_correct,
    _handle_get,
    _handle_ingest_doc,
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
    "_handle_ingest_doc",
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
    if n == "fastembed":
        from distillery.embedding.fastembed import FastembedProvider

        return FastembedProvider(model=m)
    if n == "":
        from distillery.mcp._stub_embedding import StubEmbeddingProvider

        return StubEmbeddingProvider(dimensions=d)
    raise ValueError(
        f"Unsupported embedding provider: {n!r}. "
        "Must be one of: 'jina', 'openai', 'mock', 'fastembed'."
    )


def _build_background_store_factory(
    config: DistilleryConfig,
) -> Callable[[], Awaitable[Any]]:
    """Return an async factory that opens a dedicated, initialised store.

    Used to give a detached background sync job (issue #588) a store handle
    decoupled from the request lifespan: under stateless HTTP the request
    store is closed when the response returns, so the job must own its own
    connection for its full lifetime. The factory mirrors the lifespan/webhook
    store construction (db-path normalisation, MotherDuck token, S3 settings)
    and returns a fresh :class:`DuckDBStore` the caller is responsible for
    closing.
    """

    async def _factory() -> Any:
        ep = _create_embedding_provider(config)
        db_path = _normalize_db_path(config.storage.database_path)
        if db_path.startswith("md:"):
            tok = os.environ.get(config.storage.motherduck_token_env)
            if tok:
                os.environ["MOTHERDUCK_TOKEN"] = tok
        from distillery.store.duckdb import DuckDBStore

        store = DuckDBStore(
            db_path=db_path,
            embedding_provider=ep,
            s3_region=config.storage.s3_region,
            s3_endpoint=config.storage.s3_endpoint,
            auto_link_enabled=config.auto_link.enabled,
            auto_link_threshold=config.auto_link.threshold,
            auto_link_max_links=config.auto_link.max_links,
        )
        await store.initialize()
        return store

    return _factory


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
        # Reuse the store only if it is still live. The previous "not _shared"
        # check fell through to the else branch when earlier lifespan exits had
        # closed the DuckDBStore but left stub entries (e.g. "transport",
        # "started_at") populated by ``__main__``, which would hand later
        # stateless HTTP sessions a closed connection.
        if "store" not in _shared:
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
                auto_link_enabled=config.auto_link.enabled,
                auto_link_threshold=config.auto_link.threshold,
                auto_link_max_links=config.auto_link.max_links,
            )
            await store.initialize()
            # Flush the WAL during quiet windows so it never grows unbounded
            # under continuous concurrent writers (poller + gh-sync) — the root
            # cause of read-latency degradation in issue #655.  Plain CHECKPOINT
            # only; skipped whenever the writer is busy, so it never blocks.
            start_idle = getattr(store, "start_idle_checkpoint", None)
            if callable(start_idle):
                start_idle()
            if await store.get_metadata("feeds_seeded") != "true":
                for src in config.feeds.sources:
                    with contextlib.suppress(ValueError):
                        await store.add_feed_source(
                            url=src.url,
                            source_type=src.source_type,
                            label=src.label,
                            poll_interval_minutes=src.poll_interval_minutes,
                            trust_weight=src.trust_weight,
                            threshold_alert=src.thresholds.alert,
                            threshold_digest=src.thresholds.digest,
                            mode=src.mode,
                        )
                await store.set_metadata("feeds_seeded", "true")
            # Wire the sync-job tracker to the store and reconcile any
            # background jobs interrupted by a prior restart.
            from distillery.feeds.sync_jobs import get_tracker

            tracker = get_tracker()
            tracker.attach_store(store)
            try:
                interrupted = await tracker.hydrate()
                if interrupted:
                    logger.info(
                        "Marked %d sync jobs as interrupted during startup hydration",
                        interrupted,
                    )
            except Exception:  # noqa: BLE001
                logger.exception("Sync-job tracker hydration failed (non-fatal)")

            # Sweep any stale webhook job pointers carried over from a
            # previous run.  In-memory state is normally empty on cold
            # start, but Fly autosuspend (issue #507) can resume a process
            # with the ``_active_job_by_endpoint`` dict still populated
            # from a poll that never reached a terminal state — leaving
            # every subsequent ``/api/poll`` permanently blocked on a 409.
            try:
                from distillery.mcp.webhooks import sweep_stale_jobs

                swept = await sweep_stale_jobs()
                if swept:
                    logger.info(
                        "Swept %d stale webhook job pointer(s) on startup "
                        "(issue #507 recovery path)",
                        swept,
                    )
            except Exception:  # noqa: BLE001
                logger.exception("Stale-job sweep failed (non-fatal)")
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
            # Invalidate the store/embedding references so that a subsequent
            # lifespan entry (e.g. the next stateless HTTP session) re-enters
            # the initialisation branch above rather than reusing a closed
            # DuckDBStore whose ``_conn`` has already been released. Other
            # entries like "transport" / "started_at" / "config" are kept so
            # that cross-session metadata (populated by ``__main__``) survives.
            _shared.pop("store", None)
            _shared.pop("embedding_provider", None)

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
        except Exception:  # noqa: BLE001
            logger.exception("Ownership pre-check failed for entry %s", eid)
            return error_response("INTERNAL", "Failed to read entry")
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
        include_conflict_prompt: bool = False,
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
          - metadata (dict, optional): Arbitrary key-value metadata. Some entry
            types REQUIRE specific metadata keys (TYPE_METADATA_SCHEMAS); omitting
            them returns INVALID_PARAMS naming the missing/invalid field:
              - person:  expertise (list[str])
              - project: repo (str)
              - digest:  period_start, period_end (str)
              - github:  repo, ref_type, ref_number; ref_type in
                [issue, pr, discussion, release]
              - feed:    source_url, source_type; source_type in [rss, github]
            Other types (session, bookmark, minutes, meeting, reference, idea,
            inbox) accept arbitrary metadata.
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
          - include_conflict_prompt (bool, optional, default=False): When true,
            each conflict candidate carries the ~1–2 KB ``conflict_prompt``
            LLM template required to round-trip through
            ``distillery_find_similar(conflict_check=true)``. Defaults to
            false to keep store responses small (issue #348).

        RETURNS (success): { entry_id: str, persisted: bool, dedup_action: str,
            conflicts?: list[{entry_id, content_preview, similarity_score,
            conflict_prompt?}], warnings?: list }
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
            include_conflict_prompt=include_conflict_prompt,
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

        RETURNS (success): {
            entry_ids: list[str | None],   # per-item ids; null for failed items
            count: int,                    # number actually persisted
            results: list[dict],           # per-item status preserving input order
        }
          - Successful items: { entry_id, persisted: true, dedup_action: "stored" }
          - Failed items:     { entry_id: null, persisted: false, error: { code, message, details? } }
        Validation failures on individual items no longer abort the batch —
        valid entries are persisted and failures are reported per item in
        ``results`` (issue #364).  Iterate ``results`` to discover failures.
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "BUDGET_EXCEEDED" | "INTERNAL", message: "..." }
          Top-level error is returned only for schema-level problems
          (``entries`` not a list, budget exhaustion, persistence failure).

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
        # Drive auditing off the per-item ``results`` list so invalid items
        # (whose ``entry_id`` is ``None``) are recorded as failures rather
        # than logged as successes with a null id (issue #364 follow-up).
        rd = json.loads(result[0].text) if result else {}
        if rd.get("error"):
            # Top-level failure (schema/budget/persistence) — record a single
            # failure row so the audit trail reflects the aborted call.
            await _audit(c, user, "distillery_store_batch", "", "store", result)
        else:
            per_item = rd.get("results") or []
            if not per_item:
                # Empty batch — still emit a single audit row for traceability.
                await _audit(c, user, "distillery_store_batch", "", "store", result)
            else:
                for item in per_item:
                    if item.get("persisted"):
                        eid = item.get("entry_id") or ""
                        try:
                            await c["store"].write_audit_log(
                                user,
                                "distillery_store_batch",
                                eid,
                                "store",
                                "success",
                            )
                        except Exception:  # noqa: BLE001
                            logger.debug(
                                "audit_log write failed for distillery_store_batch (ignored)",
                                exc_info=True,
                            )
                    else:
                        # Invalid item — surface as "store_failed" so the
                        # audit trail distinguishes validation rejects from
                        # persisted rows (matches the "not_found"/"forbidden"
                        # convention used by ``_own``).
                        try:
                            await c["store"].write_audit_log(
                                user,
                                "distillery_store_batch",
                                "",
                                "store_failed",
                                "error",
                            )
                        except Exception:  # noqa: BLE001
                            logger.debug(
                                "audit_log write failed for distillery_store_batch (ignored)",
                                exc_info=True,
                            )
        return result

    @server.tool
    async def distillery_ingest_doc(  # noqa: PLR0913
        ctx: Context,
        text: str,
        author: str,
        doctype: str | None = None,
        source: str | None = None,
        external_id: str | None = None,
        title: str | None = None,
        project: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[types.TextContent]:
        """Ingest an arbitrary document (ADR, spec, decision, customer feedback).

        USE WHEN: importing a standalone document — a markdown ADR/spec/RFC, a
        design decision, or a customer-feedback transcript/doc — so it becomes
        queryable knowledge with provenance. Distinct from distillery_store
        (single entry, semantic dedup) and from PreCompact transcripts: this
        chunks large text into multiple linked entries and deduplicates
        idempotently by content hash, so re-ingesting identical content adds
        no second entry.

        PARAMS:
          - text (str, required): The full document text. Large text is split
            into multiple linked entries (relation_type="chunk").
          - author (str, required): Who is ingesting / owns this document.
          - doctype (str, optional, default="doc"): Document kind. Valid:
            [adr, spec, decision, feedback, doc]. Applied as both a
            "doctype/<value>" tag and metadata.doctype for faceted retrieval.
          - source (str, optional): Provenance label (file path, Drive URL,
            etc.). Stored in metadata.source.
          - external_id (str, optional): Explicit dedup key. Defaults to the
            SHA-256 hash of text, making re-ingest idempotent.
          - title (str, optional): Human-readable title (stored in metadata.title).
          - project (str, optional): Project scope.
          - tags (list[str], optional): Extra namespaced tags.
          - metadata (dict, optional): Arbitrary extra metadata.

        RETURNS (success): { entry_ids: list[str], count: int, doctype: str,
            external_id: str, chunked: bool, persisted: bool,
            dedup_action: "stored" | "skipped" }
            On re-ingest of identical content, persisted=false,
            dedup_action="skipped", and entry_ids points at the existing entries.
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "INTERNAL", message: "..." }

        RELATED: distillery_store (single entry with semantic dedup),
        distillery_search (to retrieve ingested documents)
        """
        c = _lc(ctx)
        user = _get_authenticated_user()
        args: dict[str, Any] = dict(
            text=text,
            author=author,
            **_omit_none(
                doctype=doctype,
                source=source,
                external_id=external_id,
                title=title,
                project=project,
                tags=tags,
                metadata=metadata,
            ),
        )
        result = await _handle_ingest_doc(
            store=c["store"], arguments=args, cfg=c["config"], created_by=user
        )
        rd = json.loads(result[0].text) if result else {}
        ids = rd.get("entry_ids") or []
        await _audit(
            c, user, "distillery_ingest_doc", ids[0] if ids else "", "store", result
        )
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
        entry_type: str | list[str] | None = None,
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
        published_after: str | None = None,
        published_before: str | None = None,
        include_evergreen: bool = False,
        structural: list[str] | None = None,
    ) -> list[types.TextContent]:
        """List knowledge entries with optional filters and pagination (newest first).

        USE WHEN: browsing or filtering entries without a semantic query.
        Use distillery_search instead when you have a natural-language question.

        By default, only entries with status in (active, pending_review) are
        returned — archived entries are hidden. Pass ``status="archived"`` to
        list only archived entries, ``status="any"`` to include every status,
        or ``include_archived=true`` to add archived entries to the default view.

        PARAMS:
          - entry_type (str | list[str], optional): Filter by type, or a list of types
            matched with OR (e.g. ["session", "reference"]) — pair with group_by to
            aggregate across several types in one call. Valid: [session, bookmark, minutes,
            meeting, reference, idea, inbox, github, person, project, digest, feed].
          - author (str, optional): Filter by author.
          - project (str, optional): Filter by project scope.
          - tags (list[str], optional): Filter by tags (AND match).
          - status (str, optional): Filter by status. Valid: [active, pending_review,
            archived, any]. Default hides archived; use "any" to include all.
          - verification (str, optional): Filter by verification. Valid: [unverified, testing, verified].
          - source (str, optional): Filter by origin. Valid: [claude-code, manual, import,
            inference, documentation, external]. As a convenience, a URL-shaped value
            (starting with "http://" or "https://") is aliased to ``feed_url`` so
            ``source="https://hnrss.org/frontpage"`` matches feed items ingested from
            that source (same semantics as passing ``feed_url=...``).
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
          - published_after (str, optional): ISO 8601 inclusive lower bound on
            metadata.published_at (the feed-item publication timestamp written by the
            poller). Use this to bound the /radar candidate set by the digest window.
          - published_before (str, optional): ISO 8601 inclusive upper bound on
            metadata.published_at.
          - include_evergreen (bool, optional, default=False): When False (default) and
            published_after/published_before is set, also drops entries flagged
            metadata.backfill=true so first-poll backfill items don't surface as
            "new intelligence". Set to True to surface older / evergreen items
            explicitly. See issue #444.
          - structural (list[str], optional): Surface entries with specific graph
            anomalies relative to ``entry_relations``. Accepted values:
            ["orphans"] — entries that do not appear as either endpoint of any
            relation row. Unknown values yield INVALID_PARAMS. Combines (AND) with
            every other filter (project, tags, status, date range, stale_days,
            etc.) — orphans are first restricted by those filters, then the
            no-relations predicate is applied.

        RETURNS (success): { entries: list, count: int, total_count: int, limit: int,
          offset: int, output_mode: str } — when ``structural`` is set, the payload
          additionally includes ``structural_filter`` (comma-joined applied filters,
          e.g. "orphans"). Existing fields are unchanged.
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
            include_evergreen=include_evergreen,
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
                published_after=published_after,
                published_before=published_before,
                structural=structural,
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
        published_after: str | None = None,
        published_before: str | None = None,
        include_evergreen: bool = False,
        expand_graph: bool = False,
        expand_hops: int = 1,
        output_mode: str = "summary",
    ) -> list[types.TextContent]:
        """Search knowledge entries using semantic similarity (cosine distance, ranked descending).

        USE WHEN: finding entries that match a natural-language question or topic.
        Each result includes a similarity score (0-1, higher is more relevant).

        By default, only entries with status in (active, pending_review) are
        considered — archived entries are hidden. Pass ``status="archived"``
        to search only archived entries, ``status="any"`` to include every
        status, or ``include_archived=true`` to add archived entries to the
        default candidate set.

        When ``expand_graph=true``, after the semantic search returns its
        seed result set, the tool BFS-expands 1 or 2 hops via
        ``entry_relations`` to surface structurally connected entries.
        Graph entries are scored at ``parent_score * 0.5 ** depth``, marked
        with ``provenance="graph"``, and merged into the result list (sorted
        by descending score, truncated to ``limit``).  Seeds are tagged
        ``provenance="search"``.  The envelope gains a ``graph_expansion``
        summary.  When ``expand_graph=false`` (default), the existing
        envelope is unchanged — strictly additive.

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
          - published_after (str, optional): ISO 8601 inclusive lower bound on
            metadata.published_at (poller-recorded publication timestamp). Used by
            /radar to bound the candidate set by the configured digest window.
          - published_before (str, optional): ISO 8601 inclusive upper bound on
            metadata.published_at.
          - include_evergreen (bool, optional, default=False): When False (default) and
            published_after/published_before is set, also drops entries flagged
            metadata.backfill=true so first-poll backfill items don't surface as
            "new intelligence". Set to True to surface older / evergreen items
            explicitly. See issue #444.
          - expand_graph (bool, optional, default=False): When true, expand the seed
            result set via ``entry_relations`` and merge the neighbours into the
            results.
          - expand_hops (int, optional, default=1): Depth of graph expansion when
            ``expand_graph=true``.  Must be 1 or 2.
          - output_mode (str, optional, default="summary"): Response shape.
            Valid: [summary, full, ids]. "summary" returns score plus a compact entry
            (id/title/~200-char content_preview, no full body — default, keeps responses
            small to conserve context). "full" returns score plus the entire entry
            (pre-output_mode behaviour). "ids" returns score + id only.

        RETURNS (success): { results: [{ score: float, ... }], count: int }.
          Result shape follows ``output_mode``: "summary" (default) nests a compact
          ``entry`` (no full content); "full" nests the complete ``entry``; "ids"
          returns ``score`` + ``id`` only.
          When ``expand_graph=true`` each result also has ``provenance`` ("search" or
          "graph"); graph results additionally carry ``depth`` and ``parent_id``, and
          the envelope includes ``graph_expansion: { seed_count, expanded_count }``.
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "BUDGET_EXCEEDED" | "INTERNAL", message: "..." }

        RELATED: distillery_list (for filter-based browsing without semantic ranking),
        distillery_find_similar (to compare against arbitrary text)
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(
            query=query,
            limit=limit,
            include_archived=include_archived,
            include_evergreen=include_evergreen,
            expand_graph=expand_graph,
            expand_hops=expand_hops,
            output_mode=output_mode,
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
                published_after=published_after,
                published_before=published_before,
            ),
        )
        return await _handle_search(store=c["store"], arguments=args, cfg=c["config"])

    @server.tool
    async def distillery_find_similar(  # noqa: PLR0913
        ctx: Context,
        content: str | None = None,
        threshold: float = 0.8,
        limit: int = 10,
        dedup_action: bool = False,
        conflict_check: bool = False,
        llm_responses: list[dict[str, Any]] | None = None,
        source_entry_id: str | None = None,
        source_entry_ids: list[str] | None = None,
        exclude_linked: bool = False,
        accept_action: str | None = None,
    ) -> list[types.TextContent]:
        """Find stored entries similar to the given text (cosine similarity).

        USE WHEN: checking for duplicates or conflicts before storing, finding
        entries related to arbitrary text, or surfacing hidden connections to a
        known entry (entries that are similar but not yet linked via relations).
        Supports progressive disclosure modes.

        PARAMS:
          - content (str, optional): Text to compare against stored entries.
            Required unless source_entry_id is provided. When both are set,
            content wins as the similarity probe.
          - threshold (float, optional, default=0.8): Cosine similarity cutoff (0-1).
          - limit (int, optional, default=10): Max results (1-200).
          - dedup_action (bool, optional, default=false): When true, includes dedup
            check with recommended action (create/skip/merge/link).
          - conflict_check (bool, optional, default=false): When true, includes
            conflict candidates with LLM evaluation prompts.
          - llm_responses (list[dict], optional): With conflict_check=true, evaluates
            LLM conflict verdicts. Each item: { entry_id: str, is_conflict: bool, reasoning: str }.
          - source_entry_id (str, optional): Anchor entry whose content is used
            as the similarity probe when content is omitted, and whose id is
            self-excluded from results. Required when exclude_linked=true. When
            set without content/dedup/conflict/accept_action, reuses the entry's
            STORED embedding (no re-embed, no embedding-budget spend).
          - source_entry_ids (list[str], optional): BATCH mode. Up to 50 seed
            ids. Reuses each seed's STORED embedding (no re-embed, no
            embedding-budget spend) and runs all similarity queries in ONE
            round-trip. Standalone — cannot be combined with content,
            source_entry_id, dedup_action, conflict_check, accept_action, or
            llm_responses (INVALID_PARAMS). Honours threshold, limit, and
            exclude_linked per seed; each seed always self-excludes.
          - exclude_linked (bool, optional, default=false): When true, filters out
            entries already linked to source_entry_id (or, in batch mode, to each
            seed) via entry_relations (any direction, any relation_type).
            Surfaces hidden connections.
          - accept_action (str, optional): When set, persists an
            entry_relations row from source_entry_id to each result above
            threshold. Valid: ['link' → related, 'merge' → merge_source,
            'duplicate' → duplicate]. Requires source_entry_id. Idempotent via
            the unique (from_id, to_id, relation_type) index.

        RETURNS (success, single/content): { results: [{ score: float, entry: {...} }], count: int,
          threshold: float,
          dedup?: { action: str, similar_entries: list },
          conflict_candidates?: list, conflict_evaluation?: dict,
          excluded_linked_count?: int }
          Note: excluded_linked_count is present whenever source_entry_id is
          set or exclude_linked=true. It counts both linked-source exclusions
          (when exclude_linked=true) and the self-exclusion of source_entry_id
          itself (when source_entry_id == candidate); a non-zero value is
          therefore possible even with exclude_linked=false.
        RETURNS (success, batch / source_entry_ids):
          { results_by_seed: { "<seed_id>": { results: [{ score: float, entry: {...} }],
              count: int, excluded_count: int } },
            seed_count: int, threshold: float }
          A seed with no stored embedding maps to an empty results list (not an
          error). excluded_count is best-effort (reported as 0 in batch mode).
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "NOT_FOUND" | "BUDGET_EXCEEDED" | "INTERNAL", message: "..." }

        RELATED: distillery_store (stores with automatic dedup/conflict checks),
        distillery_search (for natural-language queries),
        distillery_relations (to inspect existing links between entries)
        """
        c = _lc(ctx)
        args: dict[str, Any] = dict(
            threshold=threshold,
            limit=limit,
            dedup_action=dedup_action,
            conflict_check=conflict_check,
            exclude_linked=exclude_linked,
            **_omit_none(
                content=content,
                llm_responses=llm_responses,
                source_entry_id=source_entry_id,
                source_entry_ids=source_entry_ids,
                accept_action=accept_action,
            ),
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
            Common intuitive aliases like ``"note"`` are NOT accepted but the
            error response includes a ``details.suggestion`` pointing to the
            canonical type (e.g. ``"note"`` -> ``"inbox"``).
          - confidence (float, required): Classification confidence (0-1). Entries below
            the configured threshold (default 0.6) go to pending_review.
          - reasoning (str, optional): Explanation of the classification decision.
          - suggested_tags (list[str], optional): Tags to merge onto the entry.
          - suggested_project (str, optional): Project to assign if entry has none.

        RETURNS (success): { id: str, entry_type: str, status: str, ... } (full updated entry)
        RETURNS (error): { error: true, code: "NOT_FOUND" | "INVALID_PARAMS" | "INTERNAL",
        message: "...", details?: { field, provided, allowed, suggestion? } }

        RELATED: distillery_resolve_review (to act on pending_review entries),
        distillery_list (with output_mode="review" to see the review queue)
        """
        c = _lc(ctx)
        user = _get_authenticated_user()
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
        # Validate schema-level params (entry_type, confidence range) BEFORE
        # the ownership pre-check so a single round-trip surfaces all bad
        # params — otherwise ``_own``'s NOT_FOUND short-circuits invalid
        # enum values (issue #372).
        schema_err = validate_classify_schema(args)
        if schema_err:
            return schema_err
        err = await _own(c, user, entry_id, "distillery_classify")
        if err:
            return err
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

        RETURNS (success): { id: str, status: str, ... } (full updated entry).
        When the requested action is a no-op (e.g. approve on an already-active
        entry), the response also includes { already_in_state: true } and the
        entry is returned unchanged (version is NOT bumped, reviewed_at /
        archived_at are NOT rewritten).
        RETURNS (error): { error: true, code: "NOT_FOUND" | "INVALID_PARAMS" | "FORBIDDEN" | "INTERNAL", message: "..." }

        RELATED: distillery_classify (to classify entries),
        distillery_list (with output_mode="review" to see the queue)
        """
        c = _lc(ctx)
        user = _get_authenticated_user()
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
        # Validate schema-level params (action enum, new_entry_type) BEFORE
        # the ownership pre-check so a single round-trip surfaces all bad
        # params — otherwise ``_own``'s NOT_FOUND short-circuits invalid
        # actions (issue #372).
        schema_err = validate_resolve_review_schema(args)
        if schema_err:
            return schema_err
        err = await _own(c, user, entry_id, "distillery_resolve_review")
        if err:
            return err
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
        thresholds: dict[str, float] | None = None,
        sync_history: bool = False,
        purge: bool = False,
        probe: bool = True,
        force: bool = False,
        mode: str | None = None,
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
          - thresholds (object, optional): Per-source overrides for the global
            ``feeds.thresholds`` values.  Mapping with optional float keys
            ``alert`` and/or ``digest`` in [0.0, 1.0] (when both set,
            ``digest <= alert``).  When omitted, the global cutoffs apply
            (pre-existing behaviour).  Use this to raise the bar for noisy
            aggregators (HN/Lobsters/Reddit) since ``trust_weight`` only
            attenuates downward.
          - sync_history (bool, optional, default=false): When true and source_type is
            "github", kicks off an async background import of historical issues/PRs
            (returns immediately with job_id; use distillery_sync_status to check progress).
          - purge (bool, optional, default=false): When true and action is "remove",
            archives all entries from the removed source (soft-delete). Returns the
            count of archived entries in purged_entries.
          - probe (bool, optional, default=true): When adding, lightly probe the URL
            for reachability (HEAD with GET fallback, short timeout). Returns an
            INVALID_PARAMS error (with details.probe_failed=true) if the probe fails.
          - force (bool, optional, default=false): When adding, persist the source
            even if the reachability probe fails (useful for sites that block HEAD
            but work via the poller).
          - mode (str, optional, github only): Which content-bearing surface to poll.
            Valid: [releases, events]. Defaults to "releases" (one body-bearing
            entry per release). "events" is the opt-in contentless firehose.

        RETURNS (success): { sources: list, count: int } (list) or
          { added: dict, sources: list, sync_job?: dict } (add) or
          { removed_url: str, removed: bool, sources: list, purged_entries?: int } (remove)
        RETURNS (error): { error: true, code: "INVALID_PARAMS" | "CONFLICT"
          | "INTERNAL", message: "..." }

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
                    thresholds=thresholds,
                    sync_history=sync_history or None,
                    purge=purge or None,
                    mode=mode,
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
        hops: int = 2,
        metric: str | None = None,
        scope: str = "global",
        limit: int = 10,
        project: str | None = None,
        tags: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        weight: float | None = None,
        valid_at: str | None = None,
        invalid_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        include_retired: bool = False,
    ) -> list[types.TextContent]:
        """Manage typed relations between knowledge entries.

        USE WHEN: linking entries together (e.g. marking one as blocking another,
        citing a reference, or flagging duplicates), walking the relation
        graph from a seed entry to surface multi-hop neighbours, or computing
        graph metrics (bridges, communities) on the relations subgraph.

        PARAMS:
          - action (str, required): Operation. Valid: [add, get, remove, traverse, metrics,
            reconcile, list_candidates, resolve_candidate, suggest_links, promote_entities,
            retire, revalidate]. ``retire`` soft-retires an edge (sets invalid_at; pass
            relation_id and optional invalid_at ISO 8601 — defaults to now); ``revalidate``
            clears invalid_at. ``get`` accepts include_retired (default false) to include
            soft-retired edges.
          - from_id (str, required for add): Source entry UUID.
          - to_id (str, required for add): Target entry UUID.
          - relation_type (str, required for add, optional for get/traverse): Relation type.
            Valid: [link, corrects, supersedes, related, blocks, depends_on, citation,
            duplicate, merge_source, sync_source, mentions, chunk].
          - weight (float, optional for add): Edge strength (e.g. interest/engagement
            magnitude). On a re-assert of an existing edge, supplied attributes are upserted.
          - valid_at / invalid_at (str ISO 8601, optional for add): Bi-temporal validity
            window — when the relationship became / stopped being true (invalid_at null = current).
          - metadata (object, optional for add): Arbitrary per-edge attributes (JSON).
          - entry_id (str, required for get/traverse, required for metrics scope='ego'):
            Entry UUID to query relations for (BFS root for traverse / ego-graph).
          - direction (str, optional for get/traverse, default="both"): Filter direction.
            Valid: [outgoing, incoming, both].
          - relation_id (str, required for remove): UUID of the relation to delete.
          - hops (int, optional for traverse, default=2): BFS depth, capped at [1, 3].
          - metric (str, required for metrics): Graph metric to compute.
            Valid: [bridges, communities, constraint, link_prediction, orphans].
            Requires the [graph] optional extra.
          - scope (str, optional for metrics, default="global"): Subgraph scope.
            Valid: [global, ego]. ``"ego"`` requires ``entry_id``.
          - limit (int, optional for metrics, default=10): top-k results.
            ``bridges`` = entries by betweenness centrality; ``communities`` = K
            largest communities; ``constraint`` = entries by lowest Burt constraint
            (strongest structural-hole brokers); ``link_prediction`` = top predicted
            edges by Adamic-Adar (pass ``entry_id`` to score adjacencies for one entry);
            ``orphans`` = sample (<=50) of entry IDs absent from the relations graph
            (unlinked entries — feeds a linking / gap-scan pass).
          - project / tags / date_from / date_to (optional, metrics global scope):
            restrict the entries whose relations participate in the graph.

        RETURNS (success): { relation_id: str, from_id: str, to_id: str, relation_type: str,
          weight: float | null, valid_at: str | null, invalid_at: str | null,
          metadata: object | null } (add) or
          { entry_id: str, relations: list, count: int } (get) or
          { relation_id: str, removed: bool } (remove) or
          { action: "traverse", root: str, hops: int, direction: str, relation_type: str | null,
            nodes: [{id: str, depth: int}], edges: [{from_id, to_id, relation_type}],
            node_count: int, edge_count: int } (traverse) or
          { action: "metrics", metric: str, scope: str, node_count: int, edge_count: int,
            total_entries: int, graph_node_count: int, orphan_rate: float,
            results: list, count: int, computed_at: str, cache_hit: bool } (metrics).
            ``orphan_rate`` = 1 - graph_node_count/total_entries (graph-health signal;
            0.0 when total_entries is 0). Or
          { action: "promote_entities", entities_created: int, entities_reused: int,
            mentions_created: int, threshold: int } (promote_entities).
            Scans ``entity/*`` and ``tech/*`` tags and promotes any canonical tag
            meeting the configured ``tags.entity_promotion_threshold`` to an ENTITY
            entry node, linking each tagged entry with a ``mentions`` edge. Idempotent.
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
                    hops=hops,
                    metric=metric,
                    scope=scope,
                    limit=limit,
                    project=project,
                    tags=tags,
                    date_from=date_from,
                    date_to=date_to,
                    weight=weight,
                    valid_at=valid_at,
                    invalid_at=invalid_at,
                    metadata=metadata,
                    include_retired=include_retired,
                ),
            ),
            cfg=c["config"],
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
        # In stateless HTTP mode each request gets its own lifespan, so the
        # shared ``store`` is closed as soon as the request returns. A
        # background=True task that captured that store would race
        # ``_store.close()`` and corrupt WAL/checkpoint state. To support
        # background sync over HTTP we hand the detached job a dedicated store
        # it owns for its full lifetime via ``store_factory`` — an own
        # connect/close decoupled from the request lifespan (issue #588).
        transport = _shared.get("transport") or c.get("transport")
        store_factory = _build_background_store_factory(config) if transport == "http" else None
        return await _handle_gh_sync(
            store=c["store"],
            arguments=dict(
                url=url, author=author, **_omit_none(project=project, background=background or None)
            ),
            store_factory=store_factory,
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
            Valid: [feeds, feeds.thresholds, defaults, classification].
          - key (str, required): Config key within the section.
            Valid keys by section: feeds: [user_agent];
            feeds.thresholds: [alert, digest];
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
