"""Feed tool handlers for the Distillery MCP server.

Implements the following tools:
  - distillery_watch: Manage feed sources (list, add, remove).
  - distillery_poll: Poll configured feed sources for new content.
  - distillery_rescore: Re-score existing feed entries against current knowledge.

Helper functions ``_normalise_watched_set`` and ``_derive_suggestions`` are used
by :mod:`distillery.mcp.tools.analytics` when ``distillery_interests`` is called
with ``suggest_sources=True``.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

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

        response_data: dict[str, Any] = {
            "added": added,
            "sources": db_sources,
        }

        # --- optional history sync for GitHub sources ----------------------
        # Note: sync_history bypasses MCP-level budget checks by design (same
        # as poll webhooks).  The GitHubSyncAdapter caps at 1000 items and
        # uses store.store() per entry which respects store-level constraints.
        sync_history = arguments.get("sync_history", False)
        if sync_history and source_type == "github":
            try:
                from distillery.feeds.github_sync import GitHubSyncAdapter

                adapter = GitHubSyncAdapter(
                    store=store,
                    url=url,
                    token=os.environ.get("GITHUB_TOKEN"),
                )
                sync_result = await adapter.sync()
                response_data["sync"] = {
                    "created": sync_result.created,
                    "updated": sync_result.updated,
                    "relations": sync_result.relations_created,
                }
            except Exception as exc:  # noqa: BLE001
                logger.exception("distillery_watch: sync_history failed for %s", url)
                response_data["sync_error"] = str(exc)

        return success_response(response_data)

    # action == "remove"
    url = str(arguments.get("url", "")).strip()
    if not url:
        return error_response("INVALID_PARAMS", "url is required for action='remove'")

    purge = bool(arguments.get("purge", False))

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
