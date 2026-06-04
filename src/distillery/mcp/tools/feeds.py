"""Feed tool handlers for the Distillery MCP server.

Implements the following MCP tools:
  - distillery_watch: Manage feed sources (list, add, remove).
  - distillery_gh_sync: Sync GitHub issues/PRs with batched pipeline.
  - distillery_sync_status: Check status of background sync jobs.

Also implements shared feed handlers that are invoked by the REST webhook
layer (``/hooks/poll``, ``/hooks/rescore``) and the eval bridge — these are
NOT registered as MCP tools:
  - ``_handle_poll``: Poll configured feed sources for new content.
  - ``_handle_rescore``: Re-score existing feed entries against current
    knowledge.

Helper functions ``_normalise_watched_set`` and ``_derive_suggestions`` are used
by :mod:`distillery.mcp.tools.analytics` when ``distillery_interests`` is called
with ``suggest_sources=True``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from mcp import types

from distillery.config import DistilleryConfig
from distillery.feeds.url_guard import UnsafeURLError, validate_public_url
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

    # For GitHub sources, require the URL to point at github.com/<owner>/<repo>
    # (optionally with a trailing slash). Otherwise non-GitHub URLs can be
    # registered as GitHub sources and only fail later in the sync pipeline.
    if source_type == "github":
        host = parsed.netloc.lower()
        if host not in ("github.com", "www.github.com"):
            return (
                f"github url must point at github.com, got host {parsed.netloc!r}. "
                "Expected 'owner/repo' or 'https://github.com/<owner>/<repo>'."
            )
        path = parsed.path.rstrip("/")
        # Expect exactly "/owner/repo" after stripping a trailing slash.
        stripped = path.lstrip("/")
        if not _GITHUB_SLUG_RE.match(stripped):
            return (
                f"github url path must be '/owner/repo', got {parsed.path!r}. "
                "Expected 'owner/repo' or 'https://github.com/<owner>/<repo>'."
            )
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

    # Redirects are not followed here: a redirect target could resolve to a
    # non-public host. A 3xx response still counts as reachable below, and the
    # poller's own fetch path re-validates every redirect hop.
    try:
        async with httpx.AsyncClient(
            timeout=_PROBE_TIMEOUT_SECONDS, follow_redirects=False
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
    # Treat 404 (missing resource) and 410 (gone) as probe failures — a typoed
    # or deleted URL should not pass registration just because the server
    # answered at all. Other 4xx codes (401/403/429, etc.) are preserved as
    # "reachable" because they often indicate auth/rate-limit gates on
    # otherwise-valid endpoints.
    if response.status_code in (404, 410):
        return f"Probe returned client error: HTTP {response.status_code}"
    return None


def _parse_thresholds_arg(
    raw: Any,
) -> tuple[float | None, float | None]:
    """Parse the optional ``thresholds`` argument on ``distillery_watch add``.

    Accepts either ``None`` (no override) or a mapping with optional
    ``alert`` / ``digest`` keys.  Each value, when provided, must be a
    finite float in ``[0.0, 1.0]``.  When both are provided the
    ``digest <= alert`` invariant is enforced.

    Returns:
        ``(alert, digest)`` — either may be ``None`` when the operator
        only overrode the other tier.

    Raises:
        ValueError: With a structured message suitable for surfacing as
            ``INVALID_PARAMS`` when the input shape or values are wrong.
    """
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        raise ValueError(
            f"thresholds must be a mapping with optional 'alert'/'digest' keys, "
            f"got: {type(raw).__name__}"
        )
    valid_keys = {"alert", "digest"}
    extra = set(raw.keys()) - valid_keys
    if extra:
        raise ValueError(
            f"thresholds has unknown keys: {sorted(extra)}; expected any of {sorted(valid_keys)}"
        )

    def _parse_optional(field_name: str) -> float | None:
        if field_name not in raw:
            return None
        value_raw = raw[field_name]
        if value_raw is None:
            return None
        # Reject booleans explicitly: ``float(True)`` returns ``1.0`` so JSON
        # ``true``/``false`` would otherwise be silently accepted as numeric.
        if isinstance(value_raw, bool):
            raise ValueError(f"thresholds.{field_name} must be a float, got: {value_raw!r}")
        try:
            value = float(value_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"thresholds.{field_name} must be a float, got: {value_raw!r}"
            ) from exc
        if not (0.0 <= value <= 1.0):
            raise ValueError(f"thresholds.{field_name} must be between 0.0 and 1.0, got: {value}")
        return value

    alert = _parse_optional("alert")
    digest = _parse_optional("digest")
    if alert is not None and digest is not None and digest > alert:
        raise ValueError(f"thresholds.digest ({digest}) must be <= thresholds.alert ({alert})")
    return alert, digest


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
        except Exception:  # noqa: BLE001
            logger.exception("distillery_watch: failed to list feed sources")
            return error_response("INTERNAL", "Failed to list feed sources")
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

        thresholds_raw = arguments.get("thresholds")
        try:
            threshold_alert, threshold_digest = _parse_thresholds_arg(thresholds_raw)
        except ValueError as exc:
            return error_response("INVALID_PARAMS", str(exc))

        try:
            sync_history = _parse_bool_arg(arguments.get("sync_history"), default=False)
        except ValueError as exc:
            return error_response("INVALID_PARAMS", str(exc))

        # ------------------------------------------------------------------
        # URL syntax validation.
        # ------------------------------------------------------------------
        syntax_error = _validate_url_syntax(url, source_type)
        if syntax_error is not None:
            return error_response(
                "INVALID_PARAMS",
                syntax_error,
                details={"field": "url", "url": url, "syntax_error": syntax_error},
            )

        # ------------------------------------------------------------------
        # Outbound-fetch host validation (rss sources only).
        # The poller issues HTTP requests against this URL, so restrict it to
        # publicly-routable hosts before persisting. GitHub sources are exempt:
        # the GitHub adapter constructs api.github.com URLs itself.
        # ------------------------------------------------------------------
        if source_type == "rss":
            try:
                await asyncio.to_thread(validate_public_url, url)
            except UnsafeURLError:
                # Return a stable, client-facing message rather than echoing
                # raw exception text. This keeps the public contract decoupled
                # from the wording inside ``url_guard`` and avoids leaking
                # validation internals (e.g. resolver behaviour).
                return error_response(
                    "INVALID_PARAMS",
                    "url must resolve to a public http(s) host",
                    details={"field": "url", "url": url},
                )

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
                    "INVALID_PARAMS",
                    (
                        f"URL {url!r} failed reachability probe: {probe_error}. "
                        "Re-run with force=True to persist anyway, "
                        "or probe=False to skip the probe."
                    ),
                    details={
                        "field": "url",
                        "url": url,
                        "last_error": probe_error,
                        "probe_failed": True,
                    },
                )

        try:
            added = await store.add_feed_source(
                url=url,
                source_type=source_type,
                label=label,
                poll_interval_minutes=poll_interval,
                trust_weight=trust_weight,
                threshold_alert=threshold_alert,
                threshold_digest=threshold_digest,
            )
            db_sources = await store.list_feed_sources()
        except ValueError:
            return error_response(
                "CONFLICT",
                f"Source with URL {url!r} is already registered.",
            )
        except Exception:  # noqa: BLE001
            logger.exception("distillery_watch: failed to add feed source")
            return error_response("INTERNAL", "Failed to add feed source")

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
                    tracker.update_progress(job.job_id, page_num, created, updated)

                sync_coro = adapter.sync_batched(on_page=_on_page)
                # Pass ``store`` so ``run_sync_job_async`` can record liveness
                # metadata (``last_polled_at``/``last_item_count``/``last_error``)
                # once the bulk sync finishes — otherwise sources that only
                # ever backfilled via ``sync_history=True`` would surface as
                # "never polled" to ``distillery_watch(action='list')`` even
                # after thousands of entries were ingested (issue #334).
                asyncio.create_task(run_sync_job_async(job, tracker, sync_coro, store))
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
    url_raw = arguments.get("url")
    if url_raw is not None and not isinstance(url_raw, str):
        return error_response(
            "INVALID_PARAMS",
            f"url must be a string, got: {type(url_raw).__name__}",
        )
    url = str(url_raw or "").strip()
    if not url:
        return error_response("INVALID_PARAMS", "url is required for action='remove'")

    try:
        purge = _parse_bool_arg(arguments.get("purge"), default=False)
    except ValueError as exc:
        return error_response("INVALID_PARAMS", str(exc))

    try:
        removed = await store.remove_feed_source(url)
        db_sources = await store.list_feed_sources()
    except Exception:  # noqa: BLE001
        logger.exception("distillery_watch: failed to remove feed source")
        return error_response("INTERNAL", "Failed to remove feed source")

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
    # Always re-query from offset=0 using an explicit non-archived filter so
    # that archiving entries in one iteration does not cause later pages to be
    # skipped. The loop terminates when no more non-archived matches remain.
    while True:
        entries = await store.list_entries(
            filters={
                "metadata.source_url": source_url,
                "status": ["active", "pending_review"],
            },
            limit=batch_size,
            offset=0,
        )
        if not entries:
            break
        for entry in entries:
            await store.update(entry.id, {"status": "archived"})
            archived += 1
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
        "items_enriched": result.items_enriched,
        "enrichment_errors": result.enrichment_errors,
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
    from distillery.feeds.reader import build_reader_client

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

        reader_cfg = config.feeds.reader
        reader = (
            build_reader_client(
                api_key_env=reader_cfg.api_key_env,
                timeout_seconds=reader_cfg.timeout_seconds,
                max_retries=reader_cfg.max_retries,
                concurrency=reader_cfg.concurrency,
                user_agent=config.feeds.user_agent or None,
            )
            if reader_cfg.enabled
            else None
        )
        poller = FeedPoller(store=store, config=config, reader=reader)
        summary = await poller.poll(source_url=source_url)
    except Exception:  # noqa: BLE001
        logger.exception("distillery_poll: unexpected error during poll cycle")
        return error_response("INTERNAL", "Poll cycle failed")

    return success_response(
        {
            "sources_polled": summary.sources_polled,
            "sources_errored": summary.sources_errored,
            "total_fetched": summary.total_fetched,
            "total_stored": summary.total_stored,
            "total_skipped_dedup": summary.total_skipped_dedup,
            "total_below_threshold": summary.total_below_threshold,
            "total_items_enriched": summary.total_items_enriched,
            "total_enrichment_errors": summary.total_enrichment_errors,
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
    except Exception:  # noqa: BLE001
        logger.exception("distillery_rescore: unexpected error")
        return error_response("INTERNAL", "Rescore failed")


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
    store_factory: Callable[[], Awaitable[Any]] | None = None,
) -> list[types.TextContent]:
    """Handle the ``distillery_gh_sync`` tool.

    Synchronises GitHub issues and PRs into the knowledge base using the
    batched pipeline.  Supports both synchronous (blocking) and async
    (background job) modes.

    Args:
        store: An initialised storage backend used for the synchronous path.
        arguments: Parsed tool arguments dict.
        store_factory: Optional async factory that opens and initialises a
            **dedicated** store owned by the background job for its full
            lifetime.  When provided, ``background=True`` runs the sync
            against this decoupled connection (own connect/close) instead of
            the request-scoped ``store`` — required under stateless HTTP,
            where the request store is closed as soon as the response
            returns (issue #588).  When ``None`` (e.g. stdio mode), the
            background job uses the long-lived shared ``store``.

    Returns:
        A structured MCP success or error response.
    """
    from distillery.feeds.github_sync import GitHubSyncAdapter

    url_raw = arguments.get("url")
    if url_raw is not None and not isinstance(url_raw, str):
        return error_response(
            "INVALID_PARAMS",
            f"url must be a string, got: {type(url_raw).__name__}",
            details={"field": "url"},
        )
    url = str(url_raw or "").strip()
    if not url:
        return error_response(
            "INVALID_PARAMS",
            "url is required (owner/repo or GitHub URL)",
            details={"field": "url"},
        )

    author = str(arguments.get("author", "gh-sync"))
    project = arguments.get("project")
    if project is not None:
        project = str(project)
    try:
        background = _parse_bool_arg(arguments.get("background"), default=False)
    except ValueError as exc:
        return error_response("INVALID_PARAMS", str(exc))

    if background:
        from distillery.feeds.sync_jobs import get_tracker, run_sync_job_async

        tracker = get_tracker()
        job = tracker.create_job(source_url=url, source_type="github")

        if store_factory is None:
            # Shared-store path (e.g. stdio): the long-lived store outlives
            # the response, so the detached task may safely use it.
            def _on_page(page_num: int, created: int, updated: int) -> None:
                tracker.update_progress(job.job_id, page_num, created, updated)

            adapter = GitHubSyncAdapter(
                store=store,
                url=url,
                author=author,
                project=project,
            )
            sync_coro = adapter.sync_batched(on_page=_on_page)
            asyncio.create_task(run_sync_job_async(job, tracker, sync_coro, store))
        else:
            # Decoupled-store path (stateless HTTP): the request-scoped
            # ``store`` is closed when this response returns, so the detached
            # task must own a dedicated connection for its full lifetime
            # instead of racing ``_store.close()`` (issue #588). The store is
            # opened lazily inside the task and closed in a ``finally`` so its
            # WAL is checkpointed cleanly after the sync, regardless of the
            # request lifespan.
            asyncio.create_task(
                _run_decoupled_gh_sync(
                    job=job,
                    tracker=tracker,
                    store_factory=store_factory,
                    url=url,
                    author=author,
                    project=project,
                )
            )
        return success_response(
            {
                "sync_job": job.to_dict(),
                "message": (
                    f"GitHub sync for {url!r} started in background "
                    f"(job_id={job.job_id}). Use distillery_sync_status to check progress."
                ),
            }
        )

    adapter = GitHubSyncAdapter(
        store=store,
        url=url,
        author=author,
        project=project,
    )
    try:
        result = await adapter.sync_batched()
    except Exception:  # noqa: BLE001
        logger.exception("distillery_gh_sync: sync failed for %s", url)
        return error_response("INTERNAL", "GitHub sync failed")

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


async def _run_decoupled_gh_sync(
    *,
    job: Any,
    tracker: Any,
    store_factory: Callable[[], Awaitable[Any]],
    url: str,
    author: str,
    project: str | None,
) -> None:
    """Run a background GitHub sync against a dedicated, job-owned store.

    Used in stateless HTTP mode where the request-scoped store is closed
    when the tool response returns. The job opens its own store here, owns it
    for the full sync, and closes it in a ``finally`` so the WAL is
    checkpointed cleanly afterwards — there is no use-after-close on the
    request store and no race with ``_store.close()`` (issue #588).

    Persistence failures during setup are recorded on the job so
    ``distillery_sync_status`` reflects them rather than silently dropping
    the job.
    """
    from distillery.feeds.github_sync import GitHubSyncAdapter
    from distillery.feeds.sync_jobs import SyncJobTracker, run_sync_job_async

    try:
        owned_store = await store_factory()
    except Exception:  # noqa: BLE001
        logger.exception("distillery_gh_sync: failed to open dedicated store for %s", url)
        tracker.mark_failed(job.job_id, "Sync job failed")
        return

    # Drive state transitions through a tracker bound to the dedicated store so
    # snapshot persistence (``sync_jobs`` UPSERTs) targets the job-owned
    # connection rather than the request-scoped one that is already closing.
    # The job object is shared by reference, so the singleton ``tracker`` still
    # reflects progress for in-process ``distillery_sync_status`` reads, and the
    # rows land in the same database file for cross-session hydration.
    owned_tracker = SyncJobTracker(store=owned_store)
    owned_tracker.register_job(job)

    def _owned_on_page(page_num: int, created: int, updated: int) -> None:
        owned_tracker.update_progress(job.job_id, page_num, created, updated)

    try:
        adapter = GitHubSyncAdapter(
            store=owned_store,
            url=url,
            author=author,
            project=project,
        )
        sync_coro = adapter.sync_batched(on_page=_owned_on_page)
        await run_sync_job_async(job, owned_tracker, sync_coro, owned_store)
    finally:
        close = getattr(owned_store, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:  # noqa: BLE001
                logger.exception("distillery_gh_sync: failed to close dedicated store for %s", url)


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
    visible_jobs = jobs[:20]
    return success_response(
        {
            "jobs": [j.to_dict() for j in visible_jobs],
            "count": len(visible_jobs),
            "total_count": len(jobs),
        }
    )
