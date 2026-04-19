"""CRUD tool handlers for the Distillery MCP server.

Implements the following tools:
  - distillery_store: Create and persist a new entry
  - distillery_get: Retrieve an entry by ID
  - distillery_update: Update an existing entry
  - distillery_correct: Store a correction that supersedes an existing entry
  - distillery_list: List entries with optional filtering and pagination
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mcp import types

from distillery.config import DistilleryConfig
from distillery.embedding.errors import EmbeddingProviderError
from distillery.mcp.tools._common import (
    error_response,
    success_response,
    validate_required,
    validate_type,
)
from distillery.mcp.tools._errors import upstream_error_response, validate_limit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Storage path helpers (duplicated here to avoid circular imports with server)
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
# CRUD-related constants
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
    "feed",
}

# Valid status values (mirrors EntryStatus enum).
_VALID_STATUSES = {"active", "pending_review", "archived"}

# Valid verification values (mirrors VerificationStatus enum).
_VALID_VERIFICATIONS = {"unverified", "testing", "verified"}

# Valid source values (mirrors EntrySource enum).
_VALID_SOURCES = {
    "claude-code",
    "manual",
    "import",
    "inference",
    "documentation",
    "external",
}


def _parse_iso8601_utc(
    raw: Any,
    field_name: str = "expires_at",
) -> datetime | list[types.TextContent]:
    """Parse an ISO 8601 string and normalise to UTC.

    Returns a UTC ``datetime`` on success, or an ``error_response`` list on
    failure (caller should return it directly).
    """
    if not isinstance(raw, str):
        return error_response("INVALID_PARAMS", f"Field '{field_name}' must be an ISO 8601 string")
    if "T" not in raw and " " not in raw:
        return error_response(
            "INVALID_PARAMS",
            f"Field '{field_name}' must include date and time (ISO 8601 datetime)",
        )
    try:
        dt = datetime.fromisoformat(raw)
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    except (ValueError, TypeError):
        return error_response(
            "INVALID_PARAMS",
            f"Field '{field_name}' must be a valid ISO 8601 datetime string",
        )


# Fields that callers may never overwrite via distillery_update.
_IMMUTABLE_FIELDS = {"id", "created_at", "source"}


# ---------------------------------------------------------------------------
# _handle_store
# ---------------------------------------------------------------------------


async def _handle_store(
    store: Any,
    arguments: dict[str, Any],
    cfg: DistilleryConfig | None = None,
    created_by: str = "",
) -> list[types.TextContent]:
    """
    Create and persist a new Entry from the provided arguments, run deduplication and a non-fatal conflict check, and return the stored entry id along with any warnings or conflict candidates.

    Parameters:
        arguments (dict): MCP tool arguments. Required keys: `content`, `entry_type`, `author`. Optional keys: `project`, `tags` (list), `metadata` (dict), `dedup_threshold` (number), `dedup_limit` (int).
        cfg (DistilleryConfig | None): Optional configuration used to derive classification/conflict thresholds; when omitted a default conflict threshold of 0.60 is used.

    Returns:
        list[types.TextContent]: MCP content list containing a JSON-serializable object with at least:
          - ``entry_id`` (str): the id the caller should reference — either the
            newly persisted entry's id, or (when the call was auto-skipped due
            to a near-duplicate above the skip threshold) the existing entry's
            id.  Never a "ghost" id that cannot be retrieved.
          - ``persisted`` (bool): ``True`` if a new row was written, ``False``
            if the call was auto-skipped due to a near-duplicate.
          - ``dedup_action`` (str): one of ``"stored"`` or ``"skipped"``.
            ``"stored"`` means a new row was persisted (even if a similar
            entry exists above the merge or link threshold — the similarity
            is reported informationally via ``existing_entry_id`` and
            ``similarity``).  ``"skipped"`` means no new row was created and
            the caller is pointed at an existing near-duplicate.

            ``"merged"`` and ``"linked"`` are reserved for future behaviour
            where the server actually folds new content into an existing row
            or creates an explicit link without a new row; they are not
            returned by the current implementation because both outcomes
            persist the new entry independently.

        When a similar existing entry is found above the merge or link
        threshold (but below the skip threshold), the response also includes
        ``existing_entry_id`` (str) and ``similarity`` (float) as an
        informational hint.  ``dedup_action`` remains ``"stored"`` — callers
        who want to avoid independent duplicates should use
        ``distillery_find_similar(dedup_action=true)`` before storing.

        May also include:
          - `warnings`: list of similar-entry summaries (id, score, content_preview) when near-duplicates were found,
          - `warning_message`: human-readable summary of warnings,
          - `conflicts`: list of conflict candidate objects (entry_id, content_preview, similarity_score, conflict_reasoning),
          - `conflict_message`: guidance message when conflict candidates are returned.
    """
    from distillery.mcp.budget import EmbeddingBudgetError, record_and_check
    from distillery.models import Entry, EntrySource, EntryType, VerificationStatus

    # --- input validation ---------------------------------------------------
    err = validate_required(arguments, "content", "entry_type", "author")
    if err:
        return error_response("INVALID_PARAMS", err)

    output_mode = arguments.get("output_mode", "full")
    if not isinstance(output_mode, str):
        return error_response("INVALID_PARAMS", "Field 'output_mode' must be a string.")
    if output_mode not in ("full", "summary", "review", "ids"):
        return error_response(
            "INVALID_PARAMS",
            "Field 'output_mode' must be one of: 'full', 'ids', 'review', 'summary'.",
        )

    entry_type_str = arguments["entry_type"]
    if entry_type_str not in _VALID_ENTRY_TYPES:
        return error_response(
            "INVALID_PARAMS",
            f"Invalid entry_type {entry_type_str!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_ENTRY_TYPES))}.",
        )

    tags_err = validate_type(arguments, "tags", list, "list of strings")
    if tags_err:
        return error_response("INVALID_PARAMS", tags_err)

    metadata_err = validate_type(arguments, "metadata", dict, "object")
    if metadata_err:
        return error_response("INVALID_PARAMS", metadata_err)

    session_id_err = validate_type(arguments, "session_id", str, "string")
    if session_id_err:
        return error_response("INVALID_PARAMS", session_id_err)

    from distillery.config import DefaultsConfig

    _defaults = cfg.defaults if cfg is not None else DefaultsConfig()
    dedup_threshold = arguments.get("dedup_threshold", _defaults.dedup_threshold)
    dedup_limit = arguments.get("dedup_limit", _defaults.dedup_limit)

    if not isinstance(dedup_threshold, (int, float)):
        return error_response("INVALID_PARAMS", "Field 'dedup_threshold' must be a number")
    if not isinstance(dedup_limit, int):
        return error_response("INVALID_PARAMS", "Field 'dedup_limit' must be an integer")

    # --- reserved prefix enforcement ----------------------------------------
    # Sources that are permitted to use tags under reserved top-level prefixes.
    _reserved_allowed_sources: set[str] = {EntrySource.IMPORT.value}
    entry_source_str: str = str(arguments.get("source", EntrySource.CLAUDE_CODE.value))
    if cfg is not None and cfg.tags.reserved_prefixes:
        tags_raw = list(arguments.get("tags") or [])
        for tag in tags_raw:
            if not isinstance(tag, str):
                return error_response(
                    "INVALID_PARAMS", f"Each tag must be a string, got: {type(tag).__name__}"
                )
        tags_to_check: list[str] = tags_raw
        if entry_source_str not in _reserved_allowed_sources:
            for tag in tags_to_check:
                top = tag.split("/")[0]
                if top in cfg.tags.reserved_prefixes:
                    return error_response(
                        "INVALID_PARAMS",
                        f"Tag {tag!r} uses reserved prefix {top!r}. "
                        "Only internal sources may use this namespace.",
                    )

    # --- db size check (cheap, run first) ------------------------------------
    if cfg is not None and cfg.rate_limit.max_db_size_mb > 0:
        db_path = _normalize_db_path(cfg.storage.database_path)
        if db_path != ":memory:" and not _is_remote_db_path(db_path):
            try:
                size_mb = Path(db_path).stat().st_size / (1024 * 1024)
                if size_mb >= cfg.rate_limit.max_db_size_mb:
                    return error_response(
                        "BUDGET_EXCEEDED",
                        f"Database size ({size_mb:.1f} MB) exceeds limit "
                        f"({cfg.rate_limit.max_db_size_mb} MB). "
                        "Delete old entries or increase rate_limit.max_db_size_mb.",
                    )
            except OSError:
                pass  # can't stat, skip check

    # --- embedding budget check (store + dedup + conflict = 3 embeds) ------
    # summary mode skips dedup/conflict, so only 1 embed needed.
    embed_count = 1 if output_mode == "summary" else 3
    if cfg is not None:
        try:
            record_and_check(
                store.connection, cfg.rate_limit.embedding_budget_daily, count=embed_count
            )
        except EmbeddingBudgetError as exc:
            return error_response("BUDGET_EXCEEDED", str(exc))

    # --- parse verification ---------------------------------------------------
    verification_val = VerificationStatus.UNVERIFIED
    verification_raw = arguments.get("verification")
    if verification_raw is not None:
        if verification_raw not in _VALID_VERIFICATIONS:
            return error_response(
                "INVALID_PARAMS",
                f"Invalid verification {verification_raw!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_VERIFICATIONS))}.",
            )
        verification_val = VerificationStatus(verification_raw)

    # --- parse source --------------------------------------------------------
    if entry_source_str not in _VALID_SOURCES:
        return error_response(
            "INVALID_PARAMS",
            f"Invalid source {entry_source_str!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_SOURCES))}.",
        )

    # --- parse expires_at (ISO 8601 string → datetime) ----------------------
    expires_at_val: datetime | None = None
    expires_at_raw = arguments.get("expires_at")
    if expires_at_raw is not None:
        result = _parse_iso8601_utc(expires_at_raw)
        if not isinstance(result, datetime):
            return result
        expires_at_val = result

    # --- build entry --------------------------------------------------------
    try:
        # Determine EntrySource from arguments (already validated above).
        resolved_source = EntrySource(entry_source_str)

        entry = Entry(
            content=arguments["content"],
            entry_type=EntryType(entry_type_str),
            source=resolved_source,
            author=arguments["author"],
            project=arguments.get("project"),
            tags=list(arguments.get("tags") or []),
            metadata=dict(arguments.get("metadata") or {}),
            created_by=created_by,
            verification=verification_val,
            expires_at=expires_at_val,
            session_id=arguments.get("session_id") or None,
        )
    except Exception as exc:  # noqa: BLE001
        return error_response("INVALID_PARAMS", f"Failed to construct entry: {exc}")

    # --- pre-persist dedup check (summary mode skips this) ------------------
    # Run dedup BEFORE persistence so that near-duplicates (score >= skip
    # threshold) can be auto-skipped.  Auto-skip returns the existing entry's
    # id — never a "ghost" id that was never inserted — together with
    # ``persisted=False`` and ``dedup_action="skipped"`` so the caller knows
    # to pivot to the existing entry.
    skip_threshold: float | None = None
    merge_threshold: float | None = None
    link_threshold: float | None = None
    if cfg is not None:
        skip_threshold = cfg.classification.dedup_skip_threshold
        merge_threshold = cfg.classification.dedup_merge_threshold
        link_threshold = cfg.classification.dedup_link_threshold

    top_existing_id: str | None = None
    top_existing_score: float | None = None
    warnings: list[dict[str, Any]] = []

    if output_mode != "summary":
        try:
            similar = await store.find_similar(
                content=entry.content,
                threshold=float(dedup_threshold),
                limit=dedup_limit,
            )
            for result in similar:
                # At this point the new entry has not been inserted yet, so
                # every result is an existing entry.  Still guard against
                # degenerate cases where the store returns the same id.
                if result.entry.id == entry.id:
                    continue
                if top_existing_id is None:
                    top_existing_id = result.entry.id
                    top_existing_score = float(result.score)
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
            # Non-fatal: fall through with no warnings and persist normally.

    # --- auto-skip: near-duplicate, do NOT persist --------------------------
    if (
        skip_threshold is not None
        and top_existing_id is not None
        and top_existing_score is not None
        and top_existing_score >= skip_threshold
    ):
        skip_response: dict[str, Any] = {
            "entry_id": top_existing_id,
            "persisted": False,
            "dedup_action": "skipped",
            "existing_entry_id": top_existing_id,
            "similarity": round(top_existing_score, 4),
        }
        if warnings:
            skip_response["warnings"] = warnings
            skip_response["warning_message"] = (
                f"Skipped as near-duplicate (score={top_existing_score:.3f}) "
                f"of existing entry {top_existing_id!r}."
            )
        return success_response(skip_response)

    # --- persist ------------------------------------------------------------
    try:
        entry_id = await store.store(entry)
    except EmbeddingProviderError as exc:
        logger.warning(
            "Upstream embedding provider failed during store "
            "(provider=%s status=%s retry_after=%s): %s",
            exc.provider,
            exc.status_code,
            exc.retry_after,
            exc,
        )
        return upstream_error_response(exc)
    except Exception:  # noqa: BLE001
        logger.exception("Error storing entry")
        return error_response("INTERNAL", "Failed to store entry")

    # --- summary mode: skip conflict, return early --------------------------
    if output_mode == "summary":
        return success_response({"entry_id": entry_id, "persisted": True, "dedup_action": "stored"})

    # --- determine dedup_action for the persisted entry ---------------------
    # When a new row is persisted independently, ``dedup_action`` is always
    # ``"stored"`` — even if a similar entry exists above the merge/link
    # threshold.  ``"merged"`` / ``"linked"`` are reserved for true fold
    # cases (no separate row is created) and are not emitted by the current
    # implementation.  The similarity signal is still surfaced via
    # ``existing_entry_id`` + ``similarity`` when the top match crosses the
    # link threshold, so callers can follow up (e.g. issue a
    # ``distillery_find_similar(dedup_action=true)`` before future stores).
    # Only ``"skipped"`` (handled above) prevents persistence.
    dedup_action = "stored"
    has_similar_hint = (
        top_existing_id is not None
        and top_existing_score is not None
        and (
            (merge_threshold is not None and top_existing_score >= merge_threshold)
            or (link_threshold is not None and top_existing_score >= link_threshold)
        )
    )
    # ``merge_threshold`` / ``link_threshold`` only drive ``has_similar_hint``.
    # They no longer influence ``dedup_action``; see the reserved-semantics
    # note above.

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
                        "conflict_prompt": prompt,
                    }
                )
            if conflicts:
                response_data: dict[str, Any] = {
                    "entry_id": entry_id,
                    "persisted": True,
                    "dedup_action": dedup_action,
                }
                if has_similar_hint and top_existing_id is not None:
                    response_data["existing_entry_id"] = top_existing_id
                    if top_existing_score is not None:
                        response_data["similarity"] = round(top_existing_score, 4)
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
                    "Use distillery_find_similar(conflict_check=true) with llm_responses to confirm conflicts."
                )
                return success_response(response_data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Conflict check failed during store: %s", exc)
        # Non-fatal: fall through and return the entry_id without conflict info.

    response: dict[str, Any] = {
        "entry_id": entry_id,
        "persisted": True,
        "dedup_action": dedup_action,
    }
    if has_similar_hint and top_existing_id is not None:
        response["existing_entry_id"] = top_existing_id
        if top_existing_score is not None:
            response["similarity"] = round(top_existing_score, 4)
    if warnings:
        response["warnings"] = warnings
        response["warning_message"] = (
            f"Found {len(warnings)} similar existing "
            f"{'entry' if len(warnings) == 1 else 'entries'}. "
            "Review before storing to avoid duplicates."
        )
    return success_response(response)


# ---------------------------------------------------------------------------
# _handle_store_batch
# ---------------------------------------------------------------------------


async def _handle_store_batch(
    store: Any,
    arguments: dict[str, Any],
    cfg: DistilleryConfig | None = None,
    created_by: str = "",
) -> list[types.TextContent]:
    """Batch-store multiple entries without dedup or conflict checks.

    Args:
        store: An initialised storage backend.
        arguments: Parsed tool arguments dict.  Required key: ``entries``
            (list of dicts, each with ``content`` and ``author``).
            Optional key: ``project`` (applied to all entries lacking one).
        cfg: Optional config for embedding budget checks.
        created_by: Ownership identifier (from auth layer).

    Returns:
        A structured MCP success or error response.  On success the payload
        contains ``entry_ids`` (list[str], preserved for backward
        compatibility), ``count`` (int), and ``results`` — a per-entry list
        of ``{"entry_id", "persisted", "dedup_action"}`` dicts.  Because the
        batch path never runs deduplication, every entry is reported as
        ``persisted=True`` with ``dedup_action="stored"``.
    """
    from distillery.mcp.budget import EmbeddingBudgetError, record_and_check
    from distillery.models import Entry, EntrySource, EntryType

    entries_raw = arguments.get("entries")
    if not isinstance(entries_raw, list):
        return error_response("INVALID_PARAMS", "Field 'entries' must be a list of dicts.")

    project_default = arguments.get("project")

    # --- validate each entry dict -------------------------------------------
    built: list[Entry] = []
    for idx, item in enumerate(entries_raw):
        if not isinstance(item, dict):
            return error_response(
                "INVALID_PARAMS", f"entries[{idx}] must be a dict, got {type(item).__name__}."
            )
        if "content" not in item:
            return error_response(
                "INVALID_PARAMS", f"entries[{idx}] is missing required 'content'."
            )
        if "author" not in item:
            return error_response("INVALID_PARAMS", f"entries[{idx}] is missing required 'author'.")

        entry_type_str = item.get("entry_type", "inbox")
        if entry_type_str not in _VALID_ENTRY_TYPES:
            return error_response(
                "INVALID_PARAMS",
                f"entries[{idx}] has invalid entry_type {entry_type_str!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_ENTRY_TYPES))}.",
            )

        source_str = str(item.get("source", EntrySource.CLAUDE_CODE.value))
        if source_str not in _VALID_SOURCES:
            return error_response(
                "INVALID_PARAMS",
                f"entries[{idx}] has invalid source {source_str!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_SOURCES))}.",
            )

        # --- normalize tags (mirror _handle_store logic) ---
        tags_raw = item.get("tags")
        if tags_raw is None:
            tags_normalized = []
        elif isinstance(tags_raw, str):
            tags_normalized = [tags_raw]
        elif isinstance(tags_raw, list):
            tags_normalized = tags_raw
        else:
            return error_response(
                "INVALID_PARAMS",
                f"entries[{idx}] has invalid tags: must be a list or string, got {type(tags_raw).__name__}.",
            )

        # Validate each tag is a non-empty string
        final_tags: list[str] = []
        for tag in tags_normalized:
            if not isinstance(tag, str):
                return error_response(
                    "INVALID_PARAMS",
                    f"entries[{idx}]: each tag must be a string, got {type(tag).__name__}.",
                )
            tag_stripped = tag.strip()
            if tag_stripped:
                final_tags.append(tag_stripped)

        # --- reserved prefix enforcement (mirror _handle_store logic) ---
        _reserved_allowed_sources: set[str] = {EntrySource.IMPORT.value}
        if (
            cfg is not None
            and cfg.tags.reserved_prefixes
            and source_str not in _reserved_allowed_sources
        ):
            for tag in final_tags:
                top = tag.split("/")[0]
                if top in cfg.tags.reserved_prefixes:
                    return error_response(
                        "INVALID_PARAMS",
                        f"entries[{idx}]: tag {tag!r} uses reserved prefix {top!r}. "
                        "Only internal sources may use this namespace.",
                    )

        try:
            entry = Entry(
                content=item["content"],
                entry_type=EntryType(entry_type_str),
                source=EntrySource(source_str),
                author=item["author"],
                project=item.get("project", project_default),
                tags=final_tags,
                metadata=dict(item.get("metadata") or {}),
                created_by=created_by,
            )
        except Exception as exc:  # noqa: BLE001
            return error_response(
                "INVALID_PARAMS", f"entries[{idx}]: failed to construct entry: {exc}"
            )
        built.append(entry)

    if not built:
        return success_response({"entry_ids": [], "results": [], "count": 0})

    # --- db size check (same guard as _handle_store) -------------------------
    if cfg is not None and cfg.rate_limit.max_db_size_mb > 0:
        db_path = _normalize_db_path(cfg.storage.database_path)
        if db_path != ":memory:" and not _is_remote_db_path(db_path):
            try:
                size_mb = Path(db_path).stat().st_size / (1024 * 1024)
                if size_mb >= cfg.rate_limit.max_db_size_mb:
                    return error_response(
                        "BUDGET_EXCEEDED",
                        f"Database size ({size_mb:.1f} MB) exceeds limit "
                        f"({cfg.rate_limit.max_db_size_mb} MB). "
                        "Delete old entries or increase rate_limit.max_db_size_mb.",
                    )
            except OSError:
                pass  # can't stat, skip check

    # --- embedding budget check (1 embed per entry, no dedup) ---------------
    if cfg is not None:
        try:
            record_and_check(
                store.connection, cfg.rate_limit.embedding_budget_daily, count=len(built)
            )
        except EmbeddingBudgetError as exc:
            return error_response("BUDGET_EXCEEDED", str(exc))

    # --- persist ------------------------------------------------------------
    try:
        entry_ids = await store.store_batch(built)
    except EmbeddingProviderError as exc:
        logger.warning(
            "Upstream embedding provider failed during store_batch "
            "(provider=%s status=%s retry_after=%s): %s",
            exc.provider,
            exc.status_code,
            exc.retry_after,
            exc,
        )
        return upstream_error_response(exc)
    except Exception:  # noqa: BLE001
        logger.exception("Error in store_batch")
        return error_response("INTERNAL", "Failed to batch-store entries")

    # Batch-store does not run deduplication; every persisted entry is
    # reported with ``persisted=True`` and ``dedup_action="stored"``.  This
    # keeps the batch response shape aligned with the single-entry
    # ``distillery_store`` response so callers can rely on the same keys.
    results = [{"entry_id": eid, "persisted": True, "dedup_action": "stored"} for eid in entry_ids]
    return success_response({"entry_ids": entry_ids, "results": results, "count": len(entry_ids)})


# ---------------------------------------------------------------------------
# _handle_get
# ---------------------------------------------------------------------------


async def _handle_get(
    store: Any,
    arguments: dict[str, Any],
    config: DistilleryConfig | None = None,
) -> list[types.TextContent]:
    """
    Retrieve an entry by its ID and, when applicable, record implicit positive feedback.

    Validates presence of `entry_id`, fetches the entry from `store`, and returns the
    serialized entry. Queries ``search_log`` directly for any recent search within the
    feedback window that returned this entry, then logs a positive feedback event per
    matching search. Failures to log feedback are caught and do not prevent returning
    the entry.

    Parameters:
        config (DistilleryConfig | None): Optional configuration used to read
            `classification.feedback_window_minutes`; defaults to 5 minutes when `None`.

    Returns:
        list[types.TextContent]: MCP content list containing the serialized entry on
        success, or an error response (e.g., `NOT_FOUND`, `INVALID_PARAMS`, `STORE_ERROR`).
    """
    err = validate_required(arguments, "entry_id")
    if err:
        return error_response("INVALID_PARAMS", err)

    entry_id: str = arguments["entry_id"]

    try:
        entry = await store.get(entry_id)
    except Exception:  # noqa: BLE001
        logger.exception("Error fetching entry id=%s", entry_id)
        return error_response("INTERNAL", "Failed to retrieve entry")

    if entry is None:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={entry_id!r}.",
            details={"entry_id": entry_id},
        )

    # Implicit feedback: query search_log for any recent search that returned this
    # entry and record a positive feedback signal. Using the DB directly (rather than
    # an in-memory list) ensures correctness in stateless deployments such as Lambda.
    feedback_window_minutes: int = 5
    if config is not None:
        feedback_window_minutes = config.classification.feedback_window_minutes

    since = datetime.now(UTC) - timedelta(minutes=feedback_window_minutes)
    try:
        recent_search_ids = await store.get_searches_for_entry(entry_id, since)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to query recent searches for entry_id=%s", entry_id)
        recent_search_ids = []

    logged_search_ids: set[str] = set()
    for search_id in recent_search_ids:
        if search_id not in logged_search_ids:
            try:
                await store.log_feedback(
                    search_id=search_id,
                    entry_id=entry_id,
                    signal="positive",
                )
                logged_search_ids.add(search_id)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Failed to log implicit feedback for entry_id=%s search_id=%s",
                    entry_id,
                    search_id,
                )

    return success_response(entry.to_dict())


# ---------------------------------------------------------------------------
# _handle_update
# ---------------------------------------------------------------------------


async def _handle_update(
    store: Any,
    arguments: dict[str, Any],
    last_modified_by: str = "",
) -> list[types.TextContent]:
    """Implement the ``distillery_update`` tool.

    Args:
        store: Initialised ``DuckDBStore``.
        arguments: Raw MCP tool arguments dict (must contain ``entry_id`` plus
            at least one updatable field).

    Returns:
        MCP content list with the serialised updated entry or an error.
    """
    from distillery.models import EntryStatus, EntryType, VerificationStatus

    err = validate_required(arguments, "entry_id")
    if err:
        return error_response("INVALID_PARAMS", err)

    entry_id: str = arguments["entry_id"]

    # Build the updates dict from all keys except entry_id.
    updatable_keys = {
        "content",
        "entry_type",
        "author",
        "project",
        "tags",
        "status",
        "verification",
        "metadata",
        "expires_at",
        "session_id",
    }
    updates: dict[str, Any] = {}
    for key in updatable_keys:
        if key in arguments:
            updates[key] = arguments[key]

    # Reject attempts to modify immutable fields.
    bad_keys = _IMMUTABLE_FIELDS & (set(arguments.keys()) - {"entry_id"})
    if bad_keys:
        return error_response(
            "INVALID_PARAMS",
            f"Cannot update immutable field(s): {', '.join(sorted(bad_keys))}.",
        )

    if not updates:
        return error_response(
            "INVALID_PARAMS",
            "No updatable fields provided. Supply at least one of: "
            + ", ".join(sorted(updatable_keys))
            + ".",
        )

    # Inject last_modified_by *after* the emptiness check so auth metadata
    # alone cannot satisfy the "at least one field" requirement.
    if last_modified_by:
        updates["last_modified_by"] = last_modified_by

    # --- validate individual fields ----------------------------------------
    if "entry_type" in updates:
        et_str = updates["entry_type"]
        if et_str not in _VALID_ENTRY_TYPES:
            return error_response(
                "INVALID_PARAMS",
                f"Invalid entry_type {et_str!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_ENTRY_TYPES))}.",
            )
        updates["entry_type"] = EntryType(et_str)

    if "status" in updates:
        st_str = updates["status"]
        if st_str not in _VALID_STATUSES:
            return error_response(
                "INVALID_PARAMS",
                f"Invalid status {st_str!r}. Must be one of: {', '.join(sorted(_VALID_STATUSES))}.",
            )
        updates["status"] = EntryStatus(st_str)

    if "verification" in updates:
        vf_str = updates["verification"]
        if vf_str not in _VALID_VERIFICATIONS:
            return error_response(
                "INVALID_PARAMS",
                f"Invalid verification {vf_str!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_VERIFICATIONS))}.",
            )
        updates["verification"] = VerificationStatus(vf_str)

    # Parse expires_at from ISO 8601 string to datetime.
    if "expires_at" in updates:
        ea_raw = updates["expires_at"]
        if ea_raw is not None:
            result = _parse_iso8601_utc(ea_raw)
            if not isinstance(result, datetime):
                return result
            updates["expires_at"] = result

    tags_err = validate_type(updates, "tags", list, "list of strings")
    if tags_err:
        return error_response("INVALID_PARAMS", tags_err)

    metadata_err = validate_type(updates, "metadata", dict, "object")
    if metadata_err:
        return error_response("INVALID_PARAMS", metadata_err)

    session_id_err = validate_type(updates, "session_id", str, "string")
    if session_id_err:
        return error_response("INVALID_PARAMS", session_id_err)

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
        return error_response("INVALID_PARAMS", str(exc))
    except EmbeddingProviderError as exc:
        logger.warning(
            "Upstream embedding provider failed during update "
            "(provider=%s status=%s retry_after=%s): %s",
            exc.provider,
            exc.status_code,
            exc.retry_after,
            exc,
        )
        return upstream_error_response(exc)
    except Exception:  # noqa: BLE001
        logger.exception("Error updating entry id=%s", entry_id)
        return error_response("INTERNAL", "Failed to update entry")

    return success_response(updated_entry.to_dict())


# ---------------------------------------------------------------------------
# _handle_list and its helpers
# ---------------------------------------------------------------------------

_VALID_OUTPUT_MODES = frozenset({"full", "summary", "ids", "review"})
_VALID_GROUP_BY_VALUES = frozenset({"entry_type", "status", "author", "project", "source", "tags"})

# Summary-mode content preview length (characters).  Chosen to keep each
# entry ~300-500 bytes so a full ``distillery_list(limit=50)`` fits in a
# few tens of KB rather than hundreds.
_SUMMARY_CONTENT_PREVIEW_CHARS = 200

# Maximum character length for derived titles in summary mode.
_SUMMARY_TITLE_CHARS = 120

# Default statuses returned when the caller does not specify one.  Archived
# entries are excluded from default views so that deleted/superseded content
# does not leak into user-facing lists or searches.  Callers can opt back in
# via ``include_archived=True`` or the sentinel ``status="any"``.
_DEFAULT_VISIBLE_STATUSES: tuple[str, ...] = ("active", "pending_review")


def _derive_title(entry: Any) -> str:
    """Return a short title for *entry* — the ``title`` metadata key if present,
    otherwise the first non-empty line of ``content`` (trimmed to
    ``_SUMMARY_TITLE_CHARS`` characters)."""
    md_title = entry.metadata.get("title") if isinstance(entry.metadata, dict) else None
    if isinstance(md_title, str) and md_title.strip():
        return md_title.strip()[:_SUMMARY_TITLE_CHARS]
    content = getattr(entry, "content", "") or ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:_SUMMARY_TITLE_CHARS]
    return ""


def _entry_to_summary_dict(entry: Any) -> dict[str, Any]:
    """Serialise *entry* as a compact summary (no full ``content``).

    Always returns: ``id``, derived ``title``, ``entry_type``, ``tags``,
    ``project``, ``author``, ``created_at``, ``content_preview`` (truncated
    to ``_SUMMARY_CONTENT_PREVIEW_CHARS`` characters with an ellipsis when
    truncated), ``metadata``, and ``session_id``.
    """
    content: str = getattr(entry, "content", "") or ""
    if len(content) > _SUMMARY_CONTENT_PREVIEW_CHARS:
        preview = content[:_SUMMARY_CONTENT_PREVIEW_CHARS] + "…"
    else:
        preview = content

    summary: dict[str, Any] = {
        "id": entry.id,
        "title": _derive_title(entry),
        "entry_type": entry.entry_type.value,
        "tags": list(entry.tags),
        "project": entry.project,
        "author": entry.author,
        "created_at": entry.created_at.isoformat(),
        "content_preview": preview,
        # Metadata is retained (not the full content body) because callers frequently
        # need identifiers like ``external_id`` / ``source_url`` for dedup.  It is
        # typically <1 KB per entry.
        "metadata": dict(entry.metadata) if isinstance(entry.metadata, dict) else {},
        "session_id": entry.session_id,
    }
    return summary


def _entry_to_id_dict(entry: Any) -> dict[str, Any]:
    """Serialise *entry* as id/entry_type/created_at only (ids mode)."""
    result: dict[str, Any] = {
        "id": entry.id,
        "entry_type": entry.entry_type.value,
        "created_at": entry.created_at.isoformat(),
    }
    return result


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
    limit_result = validate_limit(arguments.get("limit", 20), min_val=1, max_val=500, default=20)
    if isinstance(limit_result, tuple):
        return error_response(*limit_result)
    limit = limit_result

    offset_raw = arguments.get("offset", 0)
    err_offset = validate_type(arguments, "offset", int, "integer")
    if err_offset:
        return error_response("INVALID_PARAMS", err_offset)
    offset = int(offset_raw) if offset_raw is not None else 0
    if offset < 0:
        return error_response("INVALID_PARAMS", "Field 'offset' must be >= 0")

    output_mode = arguments.get("output_mode", "summary")
    err_output_mode = validate_type(arguments, "output_mode", str, "string")
    if err_output_mode:
        return error_response("INVALID_PARAMS", err_output_mode)
    if output_mode not in _VALID_OUTPUT_MODES:
        return error_response(
            "INVALID_PARAMS",
            f"Field 'output_mode' must be one of: {', '.join(sorted(_VALID_OUTPUT_MODES))}",
        )

    content_max_length_raw = arguments.get("content_max_length")
    content_max_length: int | None = None
    if content_max_length_raw is not None:
        if not isinstance(content_max_length_raw, int):
            return error_response("INVALID_PARAMS", "Field 'content_max_length' must be an integer")
        if content_max_length_raw < 1:
            return error_response("INVALID_PARAMS", "Field 'content_max_length' must be >= 1")
        content_max_length = content_max_length_raw

    # --- validate stale_days -------------------------------------------------
    stale_days_raw = arguments.get("stale_days")
    stale_days: int | None = None
    if stale_days_raw is not None:
        if not isinstance(stale_days_raw, int):
            return error_response("INVALID_PARAMS", "Field 'stale_days' must be an integer")
        if stale_days_raw < 1:
            return error_response("INVALID_PARAMS", "Field 'stale_days' must be >= 1")
        stale_days = stale_days_raw

    # --- validate group_by ---------------------------------------------------
    group_by_raw = arguments.get("group_by")
    group_by: str | None = None
    if group_by_raw is not None:
        if not isinstance(group_by_raw, str):
            return error_response("INVALID_PARAMS", "Field 'group_by' must be a string")
        if group_by_raw not in _VALID_GROUP_BY_VALUES:
            return error_response(
                "INVALID_PARAMS",
                f"Field 'group_by' must be one of: {', '.join(sorted(_VALID_GROUP_BY_VALUES))}",
            )
        group_by = group_by_raw

    # --- validate output -----------------------------------------------------
    output_raw = arguments.get("output")
    output: str | None = None
    if output_raw is not None:
        if not isinstance(output_raw, str):
            return error_response("INVALID_PARAMS", "Field 'output' must be a string")
        if output_raw != "stats":
            return error_response("INVALID_PARAMS", "Field 'output' only accepts 'stats'")
        output = output_raw

    # --- mutual exclusivity: group_by and output="stats" ---------------------
    if group_by is not None and output == "stats":
        return error_response(
            "INVALID_PARAMS",
            "Fields 'group_by' and 'output' are mutually exclusive",
        )

    # --- source=<url> aliasing ----------------------------------------------
    # Issue #335: users often try `source="https://…/feed"` expecting it to
    # match feed-ingested entries.  The `source` column actually stores the
    # ingest origin (e.g. "import"), not the feed URL, so this silently
    # returned 0 results.  Treat a URL-shaped `source` value as an alias
    # for `feed_url` to remove the footgun.
    aliased = _alias_source_url_to_feed_url(arguments)
    if isinstance(aliased, list):
        return aliased  # error response
    arguments = aliased

    filters = _build_filters_from_arguments(arguments)

    # review mode implicitly filters to pending_review status (takes precedence
    # over any default/visible-status logic).
    if output_mode == "review":
        if filters is None:
            filters = {}
        filters["status"] = "pending_review"
    else:
        filter_result = _apply_default_status_filter(filters, arguments)
        if isinstance(filter_result, list):
            # Error response from validation.
            return filter_result
        filters = filter_result

    # batch_mode=True requires at least one real filter to prevent a
    # classify-all footgun. Run this guard AFTER status normalization so
    # status="any" (which is stripped by _apply_default_status_filter) can't
    # bypass the check, and so that the default status filter does not count
    # as a real filter on its own.
    if arguments.get("batch_mode") is True:
        real_filter_keys = {
            "source",
            "entry_type",
            "author",
            "tag_prefix",
            "project",
            "verification",
            "tags",
            "session_id",
            "feed_url",
            "date_from",
            "date_to",
            "metadata.source_url",
        }
        has_real_filter = bool(filters and any(key in filters for key in real_filter_keys))
        if not has_real_filter:
            return error_response(
                "INVALID_PARAMS",
                "At least one filter is required for --batch mode. "
                "Provide source, entry_type, author, tag_prefix, project, or verification.",
            )

    # --- group_by mode -------------------------------------------------------
    if group_by is not None:
        try:
            result = await store.list_entries(
                filters=filters,
                limit=limit,
                offset=offset,
                group_by=group_by,
                stale_days=stale_days,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Error in distillery_list (group_by mode)")
            return error_response("INTERNAL", "list_entries failed")
        return success_response(result)

    # --- stats mode ----------------------------------------------------------
    if output == "stats":
        try:
            result = await store.list_entries(
                filters=filters,
                limit=limit,
                offset=offset,
                stale_days=stale_days,
                output="stats",
            )
        except Exception:  # noqa: BLE001
            logger.exception("Error in distillery_list (stats mode)")
            return error_response("INTERNAL", "list_entries failed")
        return success_response(result)

    # --- default list mode ---------------------------------------------------
    try:
        entries = await store.list_entries(
            filters=filters,
            limit=limit,
            offset=offset,
            stale_days=stale_days,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Error in distillery_list")
        return error_response("INTERNAL", "list_entries failed")

    try:
        total_count = await store.count_entries(filters=filters, stale_days=stale_days)
    except Exception:  # noqa: BLE001
        logger.debug("count_entries failed, falling back to len(entries)", exc_info=True)
        total_count = len(entries)

    if output_mode == "summary":
        serialised = [_entry_to_summary_dict(e) for e in entries]
    elif output_mode == "ids":
        serialised = [_entry_to_id_dict(e) for e in entries]
    elif output_mode == "review":
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
        serialised = items
    else:
        if content_max_length is not None:
            result_dicts = []
            for e in entries:
                d = e.to_dict()
                if isinstance(d.get("content"), str) and len(d["content"]) > content_max_length:
                    d["content"] = d["content"][:content_max_length] + "…"
                result_dicts.append(d)
            serialised = result_dicts
        else:
            serialised = [e.to_dict() for e in entries]

    return success_response(
        {
            "entries": serialised,
            "count": len(entries),
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "output_mode": output_mode,
        }
    )


# ---------------------------------------------------------------------------
# Shared filter builder (used by _handle_list and search handlers)
# ---------------------------------------------------------------------------


def _apply_default_status_filter(
    filters: dict[str, Any] | None,
    arguments: dict[str, Any],
) -> dict[str, Any] | None | list[types.TextContent]:
    """Apply the default ``status`` filter that hides archived entries.

    Semantics:

    * If the caller passed ``include_archived=True``: no status filter is
      added (all statuses returned).
    * If the caller passed ``status="any"``: the sentinel is stripped and no
      status filter is added (all statuses returned).
    * If the caller passed any other explicit ``status`` value (including a
      list): it is left untouched.
    * Otherwise: the filter is populated with
      ``status IN ('active', 'pending_review')`` so archived entries are
      excluded from default views.

    Returns the (possibly mutated) filters dict, or an MCP error response
    list when ``include_archived`` has the wrong type.
    """
    include_archived_raw = arguments.get("include_archived")
    if include_archived_raw is not None and not isinstance(include_archived_raw, bool):
        return error_response("INVALID_PARAMS", "Field 'include_archived' must be a boolean")
    include_archived = bool(include_archived_raw) if include_archived_raw is not None else False

    # Detect the sentinel ``status="any"`` early; it overrides the default
    # archived-exclusion and means "return every status".
    if filters is not None and filters.get("status") == "any":
        remaining = {k: v for k, v in filters.items() if k != "status"}
        return remaining if remaining else None

    # If the caller has a specific status filter, leave it alone.
    if filters is not None and "status" in filters:
        return filters

    # If the caller opted out of the default filter, do nothing.
    if include_archived:
        return filters

    if filters is None:
        filters = {}
    filters["status"] = list(_DEFAULT_VISIBLE_STATUSES)
    return filters


def _looks_like_url(value: Any) -> bool:
    """Return True when *value* is a str that starts with ``http://`` or ``https://``.

    Used to detect when a caller has passed a feed URL into the ``source``
    parameter of ``distillery_list`` — a common footgun where ``source`` is
    the more discoverable name but only filters on the entry-origin column
    (e.g. ``"import"``).  See :func:`_alias_source_url_to_feed_url`.
    """
    if not isinstance(value, str):
        return False
    return value.startswith("http://") or value.startswith("https://")


def _alias_source_url_to_feed_url(
    arguments: dict[str, Any],
) -> dict[str, Any] | list[types.TextContent]:
    """Transparently route ``source=<url>`` to the ``feed_url`` filter.

    When the caller passes a URL-shaped value (``http://…`` or ``https://…``)
    as the ``source`` argument, treat it as an alias for ``feed_url``.  This
    removes a silent-zero footgun where users try ``source="https://…/feed"``
    expecting to see feed items but get an empty result because the
    ``source`` column stores ingest origin (``"import"``), not the feed URL.

    Returns a possibly-mutated copy of *arguments* when aliasing is needed.
    Returns the original dict when no aliasing applies.  Returns an MCP
    error response list when both ``source`` (URL-shaped) and ``feed_url``
    were provided with different values.

    The non-URL ``source`` behaviour is unchanged — strings like
    ``"import"`` / ``"claude-code"`` continue to filter on the ``source``
    column as before.
    """
    source = arguments.get("source")
    feed_url = arguments.get("feed_url")

    if not _looks_like_url(source):
        return arguments

    if feed_url is not None and feed_url != source:
        return error_response(
            "INVALID_PARAMS",
            "Field 'source' is a URL and 'feed_url' is also set to a different "
            "URL. Pass only one, or set both to the same value. "
            "(URL-shaped 'source' is aliased to 'feed_url'.)",
            details={"source": source, "feed_url": feed_url},
        )

    # Route URL-shaped source to feed_url and drop the original source value
    # so it isn't also translated to a (never-matching) source-column filter.
    aliased = dict(arguments)
    aliased["feed_url"] = source
    aliased.pop("source", None)
    return aliased


def _build_filters_from_arguments(arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Extract known filter keys from *arguments* into a filters dict.

    Keys extracted: ``entry_type``, ``author``, ``project``, ``tags``,
    ``status``, ``verification``, ``source``, ``date_from``, ``date_to``,
    ``tag_prefix``, ``session_id``, ``feed_url``.

    The ``feed_url`` key is translated to a ``metadata.source_url`` filter so
    callers can retrieve entries ingested from a registered feed source
    (poller writes ``metadata.source_url`` to match the registry URL, while
    the entry's ``source`` column is set to ``import``).  URL-shaped
    ``source`` values are routed to ``feed_url`` upstream by
    :func:`_alias_source_url_to_feed_url`.

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
        "verification",
        "source",
        "date_from",
        "date_to",
        "tag_prefix",
        "session_id",
    )
    filters: dict[str, Any] = {}
    for key in filter_keys:
        if key in arguments and arguments[key] is not None:
            filters[key] = arguments[key]

    # Translate feed_url → metadata.source_url (the field poller records).
    feed_url = arguments.get("feed_url")
    if feed_url is not None:
        filters["metadata.source_url"] = feed_url

    return filters if filters else None


# ---------------------------------------------------------------------------
# _handle_correct
# ---------------------------------------------------------------------------


async def _handle_correct(
    store: Any,
    arguments: dict[str, Any],
    cfg: DistilleryConfig | None = None,
    created_by: str = "",
) -> list[types.TextContent]:
    """Implement the ``distillery_correct`` tool.

    Stores a correction entry that supersedes an existing (wrong) entry.
    The original entry is archived and a ``corrects`` relation is created
    in the ``entry_relations`` table linking the new entry to the original.

    Fields (entry_type, author, project, tags) are inherited from the
    original when not provided.

    Args:
        store: Initialised ``DuckDBStore``.
        arguments: Raw MCP tool arguments dict.  Required keys:
            ``wrong_entry_id``, ``content``.  Optional keys:
            ``entry_type``, ``author``, ``project``, ``tags``,
            ``metadata``.
        cfg: Optional configuration (currently unused, accepted for
            handler signature consistency).
        created_by: Authenticated user identity to record on the new entry.

    Returns:
        MCP content list with the new and archived entry IDs, or an error.
    """
    from distillery.models import Entry, EntrySource, EntryStatus, EntryType

    # --- input validation ---------------------------------------------------
    err = validate_required(arguments, "wrong_entry_id", "content")
    if err:
        return error_response("INVALID_PARAMS", err)

    wrong_entry_id: str = arguments["wrong_entry_id"]

    # --- fetch original entry -----------------------------------------------
    try:
        original = await store.get(wrong_entry_id)
    except Exception:  # noqa: BLE001
        logger.exception("Error fetching entry id=%s for correction", wrong_entry_id)
        return error_response("INTERNAL", "Failed to retrieve original entry")

    if original is None:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={wrong_entry_id!r}.",
            details={"wrong_entry_id": wrong_entry_id},
        )

    if original.status == EntryStatus.ARCHIVED:
        return error_response(
            "INVALID_PARAMS",
            "Cannot correct an archived entry.",
            details={"wrong_entry_id": wrong_entry_id, "status": original.status.value},
        )

    # --- resolve fields (inherit from original if not provided) -------------
    entry_type_str = arguments.get("entry_type", original.entry_type.value)
    if entry_type_str not in _VALID_ENTRY_TYPES:
        return error_response(
            "INVALID_PARAMS",
            f"Invalid entry_type {entry_type_str!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_ENTRY_TYPES))}.",
        )

    author = arguments.get("author", original.author)
    project = arguments.get("project", original.project)

    tags_err = validate_type(arguments, "tags", list, "list of strings")
    if tags_err:
        return error_response("INVALID_PARAMS", tags_err)
    explicit_tags = "tags" in arguments
    tags = list(arguments["tags"]) if explicit_tags else list(original.tags)

    # --- reserved prefix enforcement (match distillery_store guard) ---------
    # Only validate when the caller explicitly supplied ``tags``: inherited
    # tags from the original entry (e.g. imported/internal sources carrying
    # reserved-prefix tags) must not block legitimate corrections when the
    # caller never touched the tag list.
    if cfg is not None and cfg.tags.reserved_prefixes and explicit_tags:
        for tag in tags:
            if not isinstance(tag, str):
                return error_response(
                    "INVALID_PARAMS", f"Each tag must be a string, got: {type(tag).__name__}"
                )
            top = tag.split("/")[0]
            if top in cfg.tags.reserved_prefixes:
                return error_response(
                    "INVALID_PARAMS",
                    f"Tag {tag!r} uses reserved prefix {top!r}. "
                    "Only internal sources may use this namespace.",
                )

    metadata_err = validate_type(arguments, "metadata", dict, "object")
    if metadata_err:
        return error_response("INVALID_PARAMS", metadata_err)

    user_metadata = dict(arguments.get("metadata") or {})

    # --- build new entry ----------------------------------------------------
    try:
        new_entry = Entry(
            content=arguments["content"],
            entry_type=EntryType(entry_type_str),
            source=EntrySource.MANUAL,
            author=author,
            project=project,
            tags=tags,
            metadata=user_metadata,
            created_by=created_by,
        )
    except Exception as exc:  # noqa: BLE001
        return error_response("INVALID_PARAMS", f"Failed to construct correction entry: {exc}")

    # --- db size / embedding budget checks (match distillery_store gates) ----
    if cfg is not None and cfg.rate_limit.max_db_size_mb > 0:
        db_path = _normalize_db_path(cfg.storage.database_path)
        if db_path != ":memory:" and not _is_remote_db_path(db_path):
            try:
                size_mb = Path(db_path).stat().st_size / (1024 * 1024)
                if size_mb >= cfg.rate_limit.max_db_size_mb:
                    return error_response(
                        "BUDGET_EXCEEDED",
                        f"Database size ({size_mb:.1f} MB) exceeds limit "
                        f"({cfg.rate_limit.max_db_size_mb} MB). "
                        "Delete old entries or increase rate_limit.max_db_size_mb.",
                    )
            except OSError:
                pass  # can't stat, skip check

    if cfg is not None:
        from distillery.mcp.budget import EmbeddingBudgetError, record_and_check

        try:
            record_and_check(store.connection, cfg.rate_limit.embedding_budget_daily, count=1)
        except EmbeddingBudgetError as exc:
            return error_response("BUDGET_EXCEEDED", str(exc))

    # --- atomically persist entry, relation, and archive original -----------
    try:
        new_entry_id = await store.apply_correction(new_entry, wrong_entry_id)
    except EmbeddingProviderError as exc:
        logger.warning(
            "Upstream embedding provider failed during apply_correction "
            "(provider=%s status=%s retry_after=%s): %s",
            exc.provider,
            exc.status_code,
            exc.retry_after,
            exc,
        )
        return upstream_error_response(exc)
    except Exception:  # noqa: BLE001
        logger.exception("Error applying correction for entry id=%s", wrong_entry_id)
        return error_response("INTERNAL", "Failed to apply correction")

    return success_response(
        {
            "correction_entry_id": new_entry_id,
            "archived_entry_id": wrong_entry_id,
        }
    )


__all__ = [
    "_handle_store",
    "_handle_store_batch",
    "_handle_get",
    "_handle_update",
    "_handle_correct",
    "_handle_list",
    "_build_filters_from_arguments",
    "_apply_default_status_filter",
    "_DEFAULT_VISIBLE_STATUSES",
    "_VALID_ENTRY_TYPES",
    "_VALID_STATUSES",
    "_VALID_VERIFICATIONS",
    "_VALID_SOURCES",
    "_IMMUTABLE_FIELDS",
    "_VALID_OUTPUT_MODES",
    "_entry_to_summary_dict",
    "_entry_to_id_dict",
    "_is_remote_db_path",
    "_normalize_db_path",
]
