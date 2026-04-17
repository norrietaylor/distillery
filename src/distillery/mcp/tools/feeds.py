"""Feed tool handlers for the Distillery MCP server.

Implements the following tools:
  - distillery_watch: Manage feed sources (list, add, remove).
  - distillery_poll: Poll configured feed sources for new content.
  - distillery_rescore: Re-score existing feed entries against current knowledge.
  - distillery_gh_sync: Sync GitHub issues/PRs with batched pipeline.
  - distillery_store_batch: Store multiple entries in a single batched call.
  - distillery_sync_status: Check status of background sync jobs.

Helper functions ``_normalise_watched_set`` and ``_derive_suggestions`` are used
by :mod:`distillery.mcp.tools.analytics` when ``distillery_interests`` is called
with ``suggest_sources=True``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

from mcp import types

from distillery.config import DistilleryConfig
from distillery.mcp.tools._common import (
    error_response,
    success_response,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_SOURCE_TYPES = {"rss", "github"}

# Probe timeout for reachability checks (seconds). Kept short so that a slow
# host does not stall the MCP tool call.
_PROBE_TIMEOUT_SECONDS = 3.0

# GitHub owner/repo slug pattern — used by the GitHub adapter in place of a
# full URL. Accepts the same characters as GitHub (alphanumerics, hyphen,
# underscore, period).
_GITHUB_SLUG_RE = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")


def _validate_url_syntax(url: str, source_type: str) -> str | None:
    """Return an error message if *url* is not syntactically valid, else ``None``.

    For ``source_type == "github"`` a bare ``owner/repo`` slug is also accepted
    because the GitHub adapter uses slugs as source identifiers.

    Args:
        url: The candidate URL (pre-stripped).
        source_type: Either ``"rss"`` or ``"github"``.

    Returns:
        A human-readable error string, or ``None`` when validation passes.
    """
    if source_type == "github" and _GITHUB_SLUG_RE.match(url):
        return None

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return (
            f"url must use http or https scheme, got: {url!r}. "
            "Expected a URL like 'https://example.com/rss'."
        )
    if not parsed.netloc:
        return f"url is missing a host (netloc), got: {url!r}"
    return None


async def _probe_url(url: str) -> str | None:
    """Attempt a single lightweight reachability check against *url*.

    Tries ``HEAD`` first and falls back to ``GET`` when the server responds
    with 405 Method Not Allowed or 501 Not Implemented (some hosts reject
    HEAD) or when HEAD itself raises. Returns ``None`` on success (any
    non-5xx response counts as reachable), or a short **generic** error
    string describing the failure. Exception details are logged
    server-side and deliberately kept out of the returned value.

    Args:
        url: The URL to probe. Must already be syntactically valid.

    Returns:
        ``None`` if the probe succeeded, otherwise a generic error string.
    """
    import httpx

    try:
        async with httpx.AsyncClient(
            timeout=_PROBE_TIMEOUT_SECONDS, follow_redirects=True
        ) as client:
            try:
                response = await client.head(url)
            except httpx.HTTPError:
                logger.info("Probe HEAD %s raised; falling back to GET", url, exc_info=True)
                response = await client.get(url)
            else:
                # Some hosts return 405/501 on HEAD — fall back to GET.
                if response.status_code in (405, 501):
                    response = await client.get(url)
    except httpx.TimeoutException:
        logger.warning("Probe timed out for %s", url, exc_info=True)
        return f"Probe timed out after {_PROBE_TIMEOUT_SECONDS:.0f}s"
    except httpx.HTTPError:
        logger.warning("Probe failed for %s", url, exc_info=True)
        return "Probe failed"
    except Exception:  # noqa: BLE001 — defensive; httpx is strict but be safe
        logger.exception("Probe unexpectedly raised for %s", url)
        return "Probe failed"

    if response.status_code >= 500:
        return f"Probe returned server error: HTTP {response.status_code}"
    return None


def _parse_bool_arg(raw: Any, *, default: bool) -> bool:
    """Parse a boolean argument without silently accepting malformed input.

    Accepts real booleans, the canonical strings ``"true"``/``"false"`` /
    ``"1"``/``"0"`` (case-insensitive), and falls back to *default* for
    ``None``. Anything else raises ``ValueError`` so the caller can return
    a structured INVALID_PARAMS error rather than coercing via ``bool()``
    (which treats ``"false"``/``"0"`` as truthy).
    """
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise ValueError(f"Expected a boolean, got {raw!r}")


# ---------------------------------------------------------------------------
# distillery_watch handler
# ---------------------------------------------------------------------------


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
            "INVALID_PARAMS",
            f"action must be a non-null string, got: {action_raw!r}",
        )
    action = action_raw.strip().lower()

    if action not in ("list", "add", "remove"):
        return error_response(
            "INVALID_PARAMS",
            f"action must be one of 'list', 'add', 'remove'; got: {action!r}",
        )

    if action == "list":
        try:
            db_sources = await store.list_feed_sources()
        except Exception as exc:  # noqa: BLE001
            logger.exception("distillery_watch: failed to list feed sources")
            return error_response("INTERNAL", f"Failed to list feed sources: {exc}")
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
                "INVALID_PARAMS", f"url must be a string, got: {type(url_raw).__name__}"
            )
        url = str(url_raw or "").strip()
        if not url:
            return error_response("INVALID_PARAMS", "url is required for action='add'")

        source_type_raw = arguments.get("source_type")
        if source_type_raw is not None and not isinstance(source_type_raw, str):
            return error_response(
                "INVALID_PARAMS",
                f"source_type must be a string, got: {type(source_type_raw).__name__}",
            )
        source_type = str(source_type_raw or "").strip()
        if not source_type:
            return error_response("INVALID_PARAMS", "source_type is required for action='add'")
        if source_type not in _VALID_SOURCE_TYPES:
            return error_response(
                "INVALID_PARAMS",
                f"source_type must be one of {sorted(_VALID_SOURCE_TYPES)}, got: {source_type!r}",
            )

        label = str(arguments.get("label", ""))

        poll_interval_raw = arguments.get("poll_interval_minutes", 60)
        try:
            poll_interval = int(poll_interval_raw)
        except (TypeError, ValueError):
            return error_response(
                "INVALID_PARAMS",
                f"poll_interval_minutes must be an integer, got: {poll_interval_raw!r}",
            )
        if poll_interval <= 0:
            return error_response(
                "INVALID_PARAMS",
                f"poll_interval_minutes must be a positive integer, got: {poll_interval}",
            )

        trust_weight_raw = arguments.get("trust_weight", 1.0)
        try:
            trust_weight = float(trust_weight_raw)
        except (TypeError, ValueError):
            return error_response(
                "INVALID_PARAMS",
                f"trust_weight must be a float, got: {trust_weight_raw!r}",
            )
        if not (0.0 <= trust_weight <= 1.0):
            return error_response(
                "INVALID_PARAMS",
                f"trust_weight must be between 0.0 and 1.0, got: {trust_weight}",
            )

        try:
            sync_history = _parse_bool_arg(arguments.get("sync_history"), default=False)
        except ValueError as exc:
            return error_response("INVALID_PARAMS", str(exc))

        # ------------------------------------------------------------------
        # URL syntax validation.
        # ------------------------------------------------------------------
        syntax_error = _validate_url_syntax(url, source_type)
        if syntax_error is not None:
            return error_response("INVALID_URL", syntax_error)

        # ------------------------------------------------------------------
        # Optional reachability probe.
        # ``probe`` defaults to True so that unreachable URLs are caught at
        # registration time. ``force=True`` persists even when the probe
        # fails (useful for feeds that block HEAD/GET from unknown UAs).
        # GitHub owner/repo slugs are not probed because they are not URLs.
        # ------------------------------------------------------------------
        try:
            probe = _parse_bool_arg(arguments.get("probe"), default=True)
            force = _parse_bool_arg(arguments.get("force"), default=False)
        except ValueError as exc:
            return error_response("INVALID_PARAMS", str(exc))
        probe_is_url = not (source_type == "github" and _GITHUB_SLUG_RE.match(url))
        probe_error: str | None = None
        if probe and probe_is_url:
            probe_error = await _probe_url(url)
            if probe_error is not None and not force:
                return error_response(
                    "UNREACHABLE_URL",
                    (
                        f"URL {url!r} failed reachability probe: {probe_error}. "
                        "Re-run with force=True to persist anyway, "
                        "or probe=False to skip the probe."
                    ),
                    details={"last_error": probe_error, "url": url},
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
                "CONFLICT",
                f"Source with URL {url!r} is already registered.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("distillery_watch: failed to add feed source")
            return error_response("INTERNAL", f"Failed to add feed source: {exc}")

        # Surface probe failure context on forced adds so operators can see
        # why the probe was overridden.  Durable persistence onto the
        # ``feed_sources`` row is added by issue #310 (which introduces the
        # ``last_error`` column and ``record_poll_status`` API).
        if probe_error is not None and force:
            added = {**added, "probe_error": probe_error, "forced": True}

        response_data: dict[str, Any] = {
            "added": added,
            "sources": db_sources,
        }

        # --- optional history sync for GitHub sources ----------------------
        # Note: sync_history bypasses MCP-level budget checks by design (same
        # as poll webhooks).  The GitHubSyncAdapter caps at 1000 items and
        # uses store.store() per entry which respects store-level constraints.
        # Runs as an async background task so the MCP response returns immediately.
        if sync_history and source_type == "github":
            tracker = None
            job = None
            try:
                from distillery.feeds.github_sync import GitHubSyncAdapter
                from distillery.feeds.sync_jobs import get_tracker, run_sync_job_async

                adapter = GitHubSyncAdapter(
                    store=store,
                    url=url,
                    token=os.environ.get("GITHUB_TOKEN"),
                )
                tracker = get_tracker()
                job = tracker.create_job(source_url=url, source_type=source_type)

                def _on_page(page_num: int, created: int, updated: int) -> None:
                    job.pages_processed = page_num
                    job.entries_created += created
                    job.entries_updated += updated

                sync_coro = adapter.sync_batched(on_page=_on_page)
                asyncio.create_task(run_sync_job_async(job, tracker, sync_coro))
                response_data["sync_job"] = job.to_dict()
                response_data["message"] = (
                    "Feed source added. History sync started in background "
                    f"(job_id={job.job_id}). Use distillery_sync_status to check progress."
                )
            except Exception:  # noqa: BLE001
                logger.exception("distillery_watch: sync_history failed for %s", url)
                if tracker is not None and job is not None:
                    tracker.mark_failed(job.job_id, "History sync failed to start")
                response_data["sync_error"] = "History sync failed to start"

        return success_response(response_data)

    # action == "remove"
    url = str(arguments.get("url", "")).strip()
    if not url:
        return error_response("INVALID_PARAMS", "url is required for action='remove'")

    try:
        purge = _parse_bool_arg(arguments.get("purge"), default=False)
    except ValueError as exc:
        return error_response("INVALID_PARAMS", str(exc))

    try:
        removed = await store.remove_feed_source(url)
        db_sources = await store.list_feed_sources()
    except Exception as exc:  # noqa: BLE001
        logger.exception("distillery_watch: failed to remove feed source")
        return error_response("INTERNAL", f"Failed to remove feed source: {exc}")

    remove_data: dict[str, Any] = {
        "removed_url": url,
        "removed": removed,
        "sources": db_sources,
    }

    # When purge is requested, archive all entries from this source.
    if purge and removed:
        try:
            archived_count = await _purge_source_entries(store, url)
            remove_data["purged_entries"] = archived_count
        except Exception:  # noqa: BLE001
            logger.exception("distillery_watch: failed to purge entries for %s", url)
            remove_data["purge_error"] = "Failed to archive historic entries."

    return success_response(remove_data)


# ---------------------------------------------------------------------------
# Purge helper — archive entries from a removed feed source
# ---------------------------------------------------------------------------


async def _purge_source_entries(store: Any, source_url: str) -> int:
    """Archive all non-archived entries whose ``metadata.source_url`` matches *source_url*.

    Iterates through matching entries in batches and sets ``status="archived"``
    on each one via ``store.update()``.  Returns the total count of archived
    entries.

    Args:
        store: An initialised storage backend with ``list_entries`` and ``update``.
        source_url: The feed source URL whose entries should be archived.

    Returns:
        Number of entries that were archived.
    """
    archived = 0
    batch_size = 100
    offset = 0
    while True:
        entries = await store.list_entries(
            filters={"metadata.source_url": source_url},
            limit=batch_size,
            offset=offset,
        )
        if not entries:
            break
        for entry in entries:
            if getattr(entry, "status", None) != "archived":
                await store.update(entry.id, {"status": "archived"})
                archived += 1
        offset += batch_size
    return archived


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
        return error_response("INTERNAL", f"Poll cycle failed: {exc}")

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


# ---------------------------------------------------------------------------
# distillery_rescore handler
# ---------------------------------------------------------------------------


async def _handle_rescore(
    store: Any,
    config: DistilleryConfig,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Handle the ``distillery_rescore`` tool.

    Re-scores existing feed entries against the current knowledge base using
    :class:`~distillery.feeds.poller.FeedPoller`.

    Args:
        store: An initialised storage backend.
        config: The current :class:`~distillery.config.DistilleryConfig`.
        arguments: Parsed tool arguments dict (``limit`` optional, default 100).

    Returns:
        A structured MCP success or error response.
    """
    from distillery.feeds.poller import FeedPoller

    limit_raw = arguments.get("limit", 100)
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        return error_response(
            "INVALID_PARAMS",
            f"limit must be an integer, got: {limit_raw!r}",
        )

    poller = FeedPoller(store=store, config=config)
    try:
        stats = await poller.rescore(limit=limit)
        return success_response(stats)
    except Exception as exc:  # noqa: BLE001
        logger.exception("distillery_rescore: unexpected error")
        return error_response("INTERNAL", f"Rescore failed: {exc}")


# ---------------------------------------------------------------------------
# distillery_suggest_sources helpers
# ---------------------------------------------------------------------------


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
# distillery_gh_sync handler
# ---------------------------------------------------------------------------


async def _handle_gh_sync(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Handle the ``distillery_gh_sync`` tool.

    Synchronises GitHub issues and PRs into the knowledge base using the
    batched pipeline.  Supports both synchronous (blocking) and async
    (background job) modes.

    Args:
        store: An initialised storage backend.
        arguments: Parsed tool arguments dict.

    Returns:
        A structured MCP success or error response.
    """
    from distillery.feeds.github_sync import GitHubSyncAdapter

    url_raw = arguments.get("url")
    if url_raw is not None and not isinstance(url_raw, str):
        return error_response(
            "INVALID_FIELD", f"url must be a string, got: {type(url_raw).__name__}"
        )
    url = str(url_raw or "").strip()
    if not url:
        return error_response("MISSING_FIELD", "url is required (owner/repo or GitHub URL)")

    author = str(arguments.get("author", "gh-sync"))
    project = arguments.get("project")
    if project is not None:
        project = str(project)
    try:
        background = _parse_bool_arg(arguments.get("background"), default=False)
    except ValueError as exc:
        return error_response("INVALID_PARAMS", str(exc))

    adapter = GitHubSyncAdapter(
        store=store,
        url=url,
        author=author,
        project=project,
    )

    if background:
        from distillery.feeds.sync_jobs import get_tracker, run_sync_job_async

        tracker = get_tracker()
        job = tracker.create_job(source_url=url, source_type="github")

        def _on_page(page_num: int, created: int, updated: int) -> None:
            job.pages_processed = page_num
            job.entries_created += created
            job.entries_updated += updated

        sync_coro = adapter.sync_batched(on_page=_on_page)
        asyncio.create_task(run_sync_job_async(job, tracker, sync_coro))
        return success_response(
            {
                "sync_job": job.to_dict(),
                "message": (
                    f"GitHub sync for {url!r} started in background "
                    f"(job_id={job.job_id}). Use distillery_sync_status to check progress."
                ),
            }
        )

    try:
        result = await adapter.sync_batched()
    except Exception:  # noqa: BLE001
        logger.exception("distillery_gh_sync: sync failed for %s", url)
        return error_response("GH_SYNC_ERROR", "GitHub sync failed")

    return success_response(
        {
            "repo": result.repo,
            "created": result.created,
            "updated": result.updated,
            "relations_created": result.relations_created,
            "pages_processed": result.pages_processed,
            "errors": result.errors,
            "sync_timestamp": result.sync_timestamp.isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# distillery_store_batch handler
# ---------------------------------------------------------------------------


async def _handle_store_batch(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Handle the ``distillery_store_batch`` tool.

    Stores multiple entries in a single batched call.  Each entry is
    processed individually with error isolation so that a failure in one
    entry does not prevent storage of the others.

    Args:
        store: An initialised storage backend.
        arguments: Parsed tool arguments dict with an ``entries`` list.

    Returns:
        A structured MCP success or error response.
    """
    from distillery.models import Entry, EntrySource, EntryType

    entries_raw = arguments.get("entries")
    if not isinstance(entries_raw, list) or not entries_raw:
        return error_response(
            "INVALID_FIELD",
            "entries must be a non-empty list of entry dicts",
        )

    errors: list[dict[str, Any]] = []
    valid_entries: list[Entry] = []

    for idx, entry_data in enumerate(entries_raw):
        if not isinstance(entry_data, dict):
            errors.append({"index": idx, "error": "entry must be a dict"})
            continue

        content = entry_data.get("content")
        entry_type_raw = entry_data.get("entry_type")
        author = entry_data.get("author", "batch-import")

        if not content or not isinstance(content, str):
            errors.append({"index": idx, "error": "content is required and must be a string"})
            continue
        if not entry_type_raw or not isinstance(entry_type_raw, str):
            errors.append({"index": idx, "error": "entry_type is required and must be a string"})
            continue

        try:
            et = EntryType(entry_type_raw)
        except ValueError:
            errors.append(
                {
                    "index": idx,
                    "error": f"Invalid entry_type: {entry_type_raw!r}",
                }
            )
            continue

        source_raw = entry_data.get("source", "import")
        try:
            source = EntrySource(source_raw)
        except ValueError:
            source = EntrySource.IMPORT

        tags = entry_data.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        metadata = entry_data.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        project = entry_data.get("project")

        try:
            entry = Entry(
                content=content,
                entry_type=et,
                source=source,
                author=str(author),
                project=project,
                tags=tags,
                metadata=metadata,
            )
            valid_entries.append(entry)
        except Exception as exc:  # noqa: BLE001
            errors.append({"index": idx, "error": str(exc)})

    stored_ids: list[str] = []
    if valid_entries:
        try:
            stored_ids = await store.store_batch(valid_entries)
        except Exception as exc:  # noqa: BLE001
            errors.append({"index": -1, "error": f"Batch store failed: {exc}"})

    return success_response(
        {
            "stored_count": len(stored_ids),
            "stored_ids": stored_ids,
            "error_count": len(errors),
            "errors": errors,
        }
    )


# ---------------------------------------------------------------------------
# distillery_sync_status handler
# ---------------------------------------------------------------------------


async def _handle_sync_status(
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Handle the ``distillery_sync_status`` tool.

    Returns the status of background sync jobs.

    Args:
        arguments: Parsed tool arguments dict (``job_id`` or ``source_url``).

    Returns:
        A structured MCP success or error response.
    """
    from distillery.feeds.sync_jobs import get_tracker

    tracker = get_tracker()
    job_id = arguments.get("job_id")

    if job_id is not None:
        job = tracker.get_job(str(job_id))
        if job is None:
            return error_response("NOT_FOUND", f"No sync job found with id={job_id!r}")
        return success_response(job.to_dict())

    source_url = arguments.get("source_url")
    jobs = tracker.list_jobs(source_url=source_url)
    return success_response(
        {
            "jobs": [j.to_dict() for j in jobs[:20]],
            "count": len(jobs),
        }
    )
