"""End-to-end skill flow tests with mocked data.

Each test class simulates the MCP tool call chain that a skill would execute,
validating the full round-trip through the handler layer with an in-memory
DuckDB store.

Skills covered:
  1. /distill  — store + check_dedup
  2. /bookmark — store + find_similar
  3. /minutes  — store, update, search, list
  4. /recall   — search with filters
  5. /pour     — multi-pass search
  6. /classify — get + classify, list + classify batch, review_queue + resolve_review
  7. /watch    — watch list/add/remove
  8. /radar    — list + suggest_sources + store
  9. /tune     — status (read thresholds)
  10. /setup   — status + watch list
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from distillery.config import (
    ClassificationConfig,
    DistilleryConfig,
    EmbeddingConfig,
    FeedsConfig,
    FeedsThresholdsConfig,
    RateLimitConfig,
    StorageConfig,
    TagsConfig,
)
from distillery.mcp._stub_embedding import HashEmbeddingProvider
from distillery.mcp.server import (
    _handle_check_dedup,
    _handle_classify,
    _handle_find_similar,
    _handle_get,
    _handle_list,
    _handle_review_queue,
    _handle_resolve_review,
    _handle_search,
    _handle_status,
    _handle_store,
    _handle_update,
    _handle_watch,
)
from distillery.store.duckdb import DuckDBStore
from tests.conftest import parse_mcp_response

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_config() -> DistilleryConfig:
    """Minimal in-memory config for skill flow tests."""
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="mock", model="mock-hash", dimensions=4),
        classification=ClassificationConfig(confidence_threshold=0.6),
        tags=TagsConfig(),
        feeds=FeedsConfig(
            thresholds=FeedsThresholdsConfig(alert=0.85, digest=0.60),
        ),
        rate_limit=RateLimitConfig(embedding_budget_daily=0),
    )


@pytest.fixture
async def skill_store() -> DuckDBStore:  # type: ignore[return]
    """In-memory DuckDBStore using HashEmbeddingProvider for functional search."""
    provider = HashEmbeddingProvider(dimensions=4)
    s = DuckDBStore(db_path=":memory:", embedding_provider=provider)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def config() -> DistilleryConfig:
    return _make_config()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _parse(response: list[Any]) -> dict[str, Any]:
    """Shorthand for parse_mcp_response."""
    return parse_mcp_response(response)


# ---------------------------------------------------------------------------
# 1. /distill — session knowledge capture
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDistillFlow:
    """Simulates the /distill skill: check_dedup -> store -> get."""

    async def test_distill_new_session(self, skill_store: DuckDBStore, config: DistilleryConfig) -> None:
        """Store a distilled session summary after dedup check returns 'create'."""
        content = (
            "## Session Summary\n\n"
            "Decided to use DuckDB for local storage due to embedded SQL support "
            "and zero-config deployment. Action item: benchmark write throughput."
        )

        # Step 5: check for duplicates (empty store -> action=create)
        dedup_resp = _parse(await _handle_check_dedup(skill_store, config, {"content": content}))
        assert dedup_resp["action"] == "create"
        assert dedup_resp["highest_score"] == 0.0

        # Step 7: store the entry
        store_resp = _parse(
            await _handle_store(
                skill_store,
                {
                    "content": content,
                    "entry_type": "session",
                    "author": "Alice",
                    "project": "distillery",
                    "tags": ["project/distillery/sessions", "domain/storage"],
                    "metadata": {"session_id": "sess-2026-04-03-abc1"},
                },
            )
        )
        assert "entry_id" in store_resp
        assert "error" not in store_resp
        entry_id = store_resp["entry_id"]

        # Step 8: verify the stored entry
        get_resp = _parse(await _handle_get(skill_store, {"entry_id": entry_id}))
        assert get_resp["content"] == content
        assert get_resp["entry_type"] == "session"
        assert get_resp["author"] == "Alice"
        assert get_resp["project"] == "distillery"
        assert "project/distillery/sessions" in get_resp["tags"]

    async def test_distill_duplicate_detected(
        self, skill_store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """When identical content exists, dedup check should not return 'create'."""
        content = "Decided to use DuckDB for vector search."

        # Seed the store
        await _handle_store(
            skill_store,
            {
                "content": content,
                "entry_type": "session",
                "author": "Alice",
                "project": "distillery",
            },
        )

        # Check dedup with same content
        dedup_resp = _parse(await _handle_check_dedup(skill_store, config, {"content": content}))
        # Exact same content should trigger skip (>= 0.95) or at least not 'create'
        assert dedup_resp["action"] in ("skip", "merge", "link")
        assert dedup_resp["highest_score"] > 0.0
        assert len(dedup_resp["similar_entries"]) > 0


# ---------------------------------------------------------------------------
# 2. /bookmark — URL knowledge capture
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBookmarkFlow:
    """Simulates the /bookmark skill: store + find_similar for dedup."""

    async def test_bookmark_new_url(self, skill_store: DuckDBStore) -> None:
        """Store a bookmark with summary and URL metadata."""
        summary = (
            "FastMCP is a Python framework for building MCP servers. "
            "Key points:\n- Decorator-based tool registration\n"
            "- Built-in stdio and HTTP transport\n- Type-safe handlers"
        )

        # Step 5: check for duplicates via find_similar (threshold 0.8)
        find_resp = _parse(
            await _handle_find_similar(
                skill_store, {"content": f"https://fastmcp.dev {summary}", "threshold": 0.8}
            )
        )
        assert find_resp["count"] == 0  # No duplicates in empty store

        # Step 8: store the bookmark
        store_resp = _parse(
            await _handle_store(
                skill_store,
                {
                    "content": summary,
                    "entry_type": "bookmark",
                    "author": "Bob",
                    "project": "distillery",
                    "tags": ["source/bookmark/fastmcp-dev", "domain/mcp"],
                    "metadata": {
                        "url": "https://fastmcp.dev",
                        "summary": "FastMCP is a Python framework for building MCP servers.",
                    },
                },
            )
        )
        assert "entry_id" in store_resp
        entry_id = store_resp["entry_id"]

        # Verify round-trip
        get_resp = _parse(await _handle_get(skill_store, {"entry_id": entry_id}))
        assert get_resp["entry_type"] == "bookmark"
        assert get_resp["metadata"]["url"] == "https://fastmcp.dev"

    async def test_bookmark_duplicate_url_detected(self, skill_store: DuckDBStore) -> None:
        """When same URL/summary exists, find_similar should return matches."""
        summary = "DuckDB is an in-process SQL OLAP database management system."

        # Seed
        await _handle_store(
            skill_store,
            {
                "content": summary,
                "entry_type": "bookmark",
                "author": "Bob",
                "metadata": {"url": "https://duckdb.org"},
            },
        )

        # Check with same content at threshold 0.0 to ensure results
        find_resp = _parse(
            await _handle_find_similar(skill_store, {"content": summary, "threshold": 0.0})
        )
        assert find_resp["count"] >= 1
        assert find_resp["results"][0]["score"] > 0.9


# ---------------------------------------------------------------------------
# 3. /minutes — meeting notes with updates
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMinutesFlow:
    """Simulates /minutes: new meeting, update, and list modes."""

    async def test_minutes_create_and_update(self, skill_store: DuckDBStore) -> None:
        """Create meeting notes, then append an update."""
        meeting_content = (
            "# Meeting: Architecture Review\n\n"
            "**Date:** 2026-04-03\n"
            "**Attendees:** Alice, Bob, Charlie\n"
            "**Meeting ID:** arch-review-2026-04-03\n\n"
            "## Discussion\n- Evaluated DuckDB vs SQLite for vector search\n\n"
            "## Decisions\n- Use DuckDB with HNSW index\n\n"
            "## Action Items\n- Alice: benchmark write throughput by Friday"
        )

        # Step 7a: store new meeting
        store_resp = _parse(
            await _handle_store(
                skill_store,
                {
                    "content": meeting_content,
                    "entry_type": "minutes",
                    "author": "Alice",
                    "project": "distillery",
                    "tags": ["project/distillery/meetings", "domain/architecture"],
                    "metadata": {
                        "meeting_id": "arch-review-2026-04-03",
                        "attendees": ["Alice", "Bob", "Charlie"],
                        "version": 1,
                    },
                },
            )
        )
        assert "entry_id" in store_resp
        entry_id = store_resp["entry_id"]

        # Step 3b (update mode): find existing meeting via search
        search_resp = _parse(
            await _handle_search(
                skill_store, {"query": "arch-review-2026-04-03", "entry_type": "minutes", "limit": 5}
            )
        )
        assert search_resp["count"] >= 1

        # Step 6b: append update
        updated_content = (
            meeting_content + "\n\n## Update — 2026-04-03 15:00:00 UTC\n"
            "- Bob completed initial benchmark: 50k writes/sec\n"
            "- Decision confirmed: DuckDB meets requirements"
        )
        update_resp = _parse(
            await _handle_update(
                skill_store,
                {
                    "entry_id": entry_id,
                    "content": updated_content,
                    "metadata": {
                        "meeting_id": "arch-review-2026-04-03",
                        "attendees": ["Alice", "Bob", "Charlie"],
                        "version": 2,
                    },
                },
            )
        )
        assert "error" not in update_resp
        assert update_resp["content"] == updated_content
        assert update_resp["metadata"]["version"] == 2

    async def test_minutes_list(self, skill_store: DuckDBStore) -> None:
        """List mode: /minutes --list returns recent meeting entries."""
        # Store two meetings
        for i, title in enumerate(["Sprint Planning", "Retro"]):
            await _handle_store(
                skill_store,
                {
                    "content": f"# Meeting: {title}\n\nNotes here.",
                    "entry_type": "minutes",
                    "author": "Alice",
                    "metadata": {"meeting_id": f"{title.lower().replace(' ', '-')}-2026-04-0{i + 1}"},
                },
            )

        # Step 3c: list meetings
        list_resp = _parse(
            await _handle_list(skill_store, {"entry_type": "minutes", "limit": 10})
        )
        assert list_resp["count"] == 2
        assert all(e["entry_type"] == "minutes" for e in list_resp["entries"])


# ---------------------------------------------------------------------------
# 4. /recall — semantic search
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRecallFlow:
    """Simulates /recall: search with optional filters."""

    async def test_recall_basic_search(self, skill_store: DuckDBStore) -> None:
        """Search returns ranked results with provenance."""
        # Seed knowledge
        for content, etype in [
            ("DuckDB uses columnar storage for analytics workloads", "session"),
            ("Jina embeddings provide multilingual vector representations", "bookmark"),
            ("Team decided to use HNSW index for similarity search", "session"),
        ]:
            await _handle_store(
                skill_store,
                {"content": content, "entry_type": etype, "author": "Alice", "project": "distillery"},
            )

        # Step 4: search
        search_resp = _parse(await _handle_search(skill_store, {"query": "vector similarity search"}))
        assert search_resp["count"] > 0
        for result in search_resp["results"]:
            assert "score" in result
            assert "entry" in result
            entry = result["entry"]
            assert "id" in entry
            assert "author" in entry
            assert "created_at" in entry

    async def test_recall_with_type_filter(self, skill_store: DuckDBStore) -> None:
        """Search filtered by entry_type."""
        await _handle_store(
            skill_store,
            {"content": "Bookmark about testing", "entry_type": "bookmark", "author": "Bob"},
        )
        await _handle_store(
            skill_store,
            {"content": "Session about testing", "entry_type": "session", "author": "Bob"},
        )

        search_resp = _parse(
            await _handle_search(skill_store, {"query": "testing", "entry_type": "bookmark"})
        )
        for result in search_resp["results"]:
            assert result["entry"]["entry_type"] == "bookmark"

    async def test_recall_with_author_filter(self, skill_store: DuckDBStore) -> None:
        """Search filtered by author."""
        await _handle_store(
            skill_store,
            {"content": "Alice's architecture notes", "entry_type": "session", "author": "Alice"},
        )
        await _handle_store(
            skill_store,
            {"content": "Bob's architecture notes", "entry_type": "session", "author": "Bob"},
        )

        search_resp = _parse(
            await _handle_search(
                skill_store, {"query": "architecture", "author": "Alice", "limit": 5}
            )
        )
        for result in search_resp["results"]:
            assert result["entry"]["author"] == "Alice"

    async def test_recall_no_results(self, skill_store: DuckDBStore) -> None:
        """Empty search returns count=0."""
        search_resp = _parse(
            await _handle_search(skill_store, {"query": "quantum computing"})
        )
        assert search_resp["count"] == 0
        assert search_resp["results"] == []


# ---------------------------------------------------------------------------
# 5. /pour — multi-pass synthesis
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPourFlow:
    """Simulates /pour: multi-pass retrieval across the knowledge base."""

    async def test_pour_multi_pass_retrieval(self, skill_store: DuckDBStore) -> None:
        """Multiple search passes collect unique entries for synthesis."""
        # Seed diverse content
        entries_data = [
            ("DuckDB was chosen for embedded SQL and zero-config deployment", "session"),
            ("HNSW index provides sub-linear search time for vector queries", "session"),
            ("Jina v3 embeddings support 1024 dimensions for multilingual text", "bookmark"),
            ("Architecture decision: separate store protocol from backend impl", "session"),
            ("VSS extension enables cosine similarity in DuckDB", "reference"),
        ]
        stored_ids: set[str] = set()
        for content, etype in entries_data:
            resp = _parse(
                await _handle_store(
                    skill_store,
                    {
                        "content": content,
                        "entry_type": etype,
                        "author": "Alice",
                        "project": "distillery",
                    },
                )
            )
            stored_ids.add(resp["entry_id"])

        # Pass 1: broad search
        pass1 = _parse(await _handle_search(skill_store, {"query": "DuckDB storage", "limit": 20}))
        pass1_ids = {r["entry"]["id"] for r in pass1["results"]}

        # Pass 2: follow-up search on related concepts
        pass2 = _parse(
            await _handle_search(skill_store, {"query": "vector similarity index", "limit": 20})
        )
        pass2_ids = {r["entry"]["id"] for r in pass2["results"]}

        # Pass 3: gap-filling
        pass3 = _parse(
            await _handle_search(skill_store, {"query": "embedding dimensions", "limit": 20})
        )
        pass3_ids = {r["entry"]["id"] for r in pass3["results"]}

        # Deduplicate by entry ID across passes
        all_ids = pass1_ids | pass2_ids | pass3_ids
        assert len(all_ids) >= 2, "Multi-pass should retrieve entries from the store"

    async def test_pour_insufficient_entries(self, skill_store: DuckDBStore) -> None:
        """When fewer than 2 entries exist, pour falls back to recall-style display."""
        await _handle_store(
            skill_store,
            {"content": "Single entry about auth", "entry_type": "session", "author": "Alice"},
        )

        search_resp = _parse(
            await _handle_search(skill_store, {"query": "authentication", "limit": 20})
        )
        # Skill should detect count < 2 and show recall-style output
        # Here we just validate the search returns at most 1 entry
        assert search_resp["count"] <= 1


# ---------------------------------------------------------------------------
# 6. /classify — classification and review queue
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClassifyFlow:
    """Simulates /classify: single entry, batch inbox, and review queue."""

    async def test_classify_single_entry(
        self, skill_store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Classify a specific entry by ID."""
        # Store an inbox entry
        store_resp = _parse(
            await _handle_store(
                skill_store,
                {"content": "Team standup notes from Monday", "entry_type": "inbox", "author": "Bob"},
            )
        )
        entry_id = store_resp["entry_id"]

        # Step A1: get entry then classify with high confidence
        get_resp = _parse(await _handle_get(skill_store, {"entry_id": entry_id}))
        assert get_resp["entry_type"] == "inbox"

        classify_resp = _parse(
            await _handle_classify(
                skill_store,
                config,
                {
                    "entry_id": entry_id,
                    "entry_type": "minutes",
                    "confidence": 0.85,
                    "reasoning": "Content describes team meeting notes",
                    "suggested_tags": ["domain/meetings"],
                },
            )
        )
        assert "error" not in classify_resp
        assert classify_resp["entry_type"] == "minutes"
        assert classify_resp["status"] == "active"  # 0.85 >= 0.6 threshold
        assert classify_resp["metadata"]["confidence"] == 0.85
        assert "domain/meetings" in classify_resp["tags"]

    async def test_classify_low_confidence_goes_to_review(
        self, skill_store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Low-confidence classification sends entry to review queue."""
        store_resp = _parse(
            await _handle_store(
                skill_store,
                {"content": "Some ambiguous content", "entry_type": "inbox", "author": "Alice"},
            )
        )
        entry_id = store_resp["entry_id"]

        # Classify with low confidence (below 0.6 threshold)
        classify_resp = _parse(
            await _handle_classify(
                skill_store,
                config,
                {
                    "entry_id": entry_id,
                    "entry_type": "reference",
                    "confidence": 0.45,
                    "reasoning": "Unclear if reference or session note",
                },
            )
        )
        assert classify_resp["status"] == "pending_review"

        # Step C1: fetch review queue
        queue_resp = _parse(await _handle_review_queue(skill_store, {"limit": 20}))
        assert queue_resp["count"] >= 1
        queued_ids = [e["id"] for e in queue_resp["entries"]]
        assert entry_id in queued_ids

    async def test_classify_batch_inbox(
        self, skill_store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Batch classify inbox entries."""
        # Seed inbox entries
        ids = []
        for i in range(3):
            resp = _parse(
                await _handle_store(
                    skill_store,
                    {"content": f"Inbox item {i}: unclassified content", "entry_type": "inbox", "author": "Bot"},
                )
            )
            ids.append(resp["entry_id"])

        # Step B1: list inbox entries
        list_resp = _parse(
            await _handle_list(
                skill_store,
                {"entry_type": "inbox", "limit": 50, "output_mode": "full", "content_max_length": 300},
            )
        )
        assert list_resp["count"] == 3

        # Step B2: classify each
        classified = 0
        review = 0
        for entry in list_resp["entries"]:
            classify_resp = _parse(
                await _handle_classify(
                    skill_store,
                    config,
                    {
                        "entry_id": entry["id"],
                        "entry_type": "idea",
                        "confidence": 0.75,
                        "reasoning": "Appears to be an idea or suggestion",
                    },
                )
            )
            if classify_resp["status"] == "active":
                classified += 1
            else:
                review += 1

        assert classified == 3  # 0.75 >= 0.6 threshold

    async def test_classify_review_queue_triage(
        self, skill_store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Triage the review queue: approve, reclassify, and archive."""
        # Create 3 entries and classify with low confidence
        entry_ids = []
        for i in range(3):
            resp = _parse(
                await _handle_store(
                    skill_store,
                    {"content": f"Review item {i}", "entry_type": "inbox", "author": "Alice"},
                )
            )
            eid = resp["entry_id"]
            entry_ids.append(eid)
            await _handle_classify(
                skill_store,
                config,
                {"entry_id": eid, "entry_type": "reference", "confidence": 0.3},
            )

        # Step C1: fetch review queue
        queue_resp = _parse(await _handle_review_queue(skill_store, {"limit": 20}))
        assert queue_resp["count"] == 3

        # Step C3: triage each entry
        # Entry 0: approve
        approve_resp = _parse(
            await _handle_resolve_review(
                skill_store,
                {"entry_id": entry_ids[0], "action": "approve", "reviewer": "Alice"},
            )
        )
        assert approve_resp["status"] == "active"
        assert approve_resp["metadata"]["reviewed_by"] == "Alice"

        # Entry 1: reclassify as session
        reclass_resp = _parse(
            await _handle_resolve_review(
                skill_store,
                {
                    "entry_id": entry_ids[1],
                    "action": "reclassify",
                    "new_entry_type": "session",
                    "reviewer": "Alice",
                },
            )
        )
        assert reclass_resp["entry_type"] == "session"
        assert reclass_resp["metadata"]["reclassified_from"] == "reference"

        # Entry 2: archive
        archive_resp = _parse(
            await _handle_resolve_review(
                skill_store,
                {"entry_id": entry_ids[2], "action": "archive", "reviewer": "Alice"},
            )
        )
        assert archive_resp["status"] == "archived"
        assert archive_resp["metadata"]["archived_by"] == "Alice"

        # Review queue should now be empty
        queue_resp = _parse(await _handle_review_queue(skill_store, {"limit": 20}))
        assert queue_resp["count"] == 0


# ---------------------------------------------------------------------------
# 7. /watch — feed source registry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWatchFlow:
    """Simulates /watch: list, add, and remove feed sources."""

    async def test_watch_list_empty(self, skill_store: DuckDBStore) -> None:
        """List returns empty when no sources configured."""
        resp = _parse(await _handle_watch(skill_store, {"action": "list"}))
        assert resp["count"] == 0
        assert resp["sources"] == []

    async def test_watch_add_source(self, skill_store: DuckDBStore) -> None:
        """Add an RSS feed source."""
        resp = _parse(
            await _handle_watch(
                skill_store,
                {
                    "action": "add",
                    "url": "https://blog.example.com/feed.xml",
                    "source_type": "rss",
                    "label": "Example Blog",
                    "poll_interval_minutes": 120,
                    "trust_weight": 0.8,
                },
            )
        )
        assert "error" not in resp
        assert resp["added"] is True
        assert len(resp["sources"]) == 1
        assert resp["sources"][0]["url"] == "https://blog.example.com/feed.xml"

    async def test_watch_add_github_source(self, skill_store: DuckDBStore) -> None:
        """Add a GitHub repo feed source."""
        resp = _parse(
            await _handle_watch(
                skill_store,
                {
                    "action": "add",
                    "url": "https://github.com/anthropics/claude-code",
                    "source_type": "github",
                    "label": "Claude Code",
                },
            )
        )
        assert "error" not in resp
        assert resp["added"] is True

    async def test_watch_add_duplicate_rejected(self, skill_store: DuckDBStore) -> None:
        """Adding the same URL twice returns a DUPLICATE_SOURCE error."""
        url = "https://blog.example.com/feed.xml"
        await _handle_watch(
            skill_store,
            {"action": "add", "url": url, "source_type": "rss"},
        )
        dup_resp = _parse(
            await _handle_watch(
                skill_store,
                {"action": "add", "url": url, "source_type": "rss"},
            )
        )
        assert dup_resp["error"] is True
        assert dup_resp["code"] == "DUPLICATE_SOURCE"

    async def test_watch_remove_source(self, skill_store: DuckDBStore) -> None:
        """Remove a registered feed source."""
        url = "https://blog.example.com/feed.xml"
        await _handle_watch(
            skill_store,
            {"action": "add", "url": url, "source_type": "rss"},
        )

        remove_resp = _parse(
            await _handle_watch(skill_store, {"action": "remove", "url": url})
        )
        assert remove_resp["removed"] is True

        # Verify empty
        list_resp = _parse(await _handle_watch(skill_store, {"action": "list"}))
        assert list_resp["count"] == 0

    async def test_watch_full_lifecycle(self, skill_store: DuckDBStore) -> None:
        """Add two sources, list, remove one, verify count."""
        urls = [
            ("https://feed1.example.com/rss", "rss", "Feed One"),
            ("https://github.com/org/repo", "github", "Org Repo"),
        ]
        for url, stype, label in urls:
            await _handle_watch(
                skill_store,
                {"action": "add", "url": url, "source_type": stype, "label": label},
            )

        list_resp = _parse(await _handle_watch(skill_store, {"action": "list"}))
        assert list_resp["count"] == 2

        # Remove first
        await _handle_watch(skill_store, {"action": "remove", "url": urls[0][0]})

        list_resp = _parse(await _handle_watch(skill_store, {"action": "list"}))
        assert list_resp["count"] == 1
        assert list_resp["sources"][0]["url"] == urls[1][0]


# ---------------------------------------------------------------------------
# 8. /radar — ambient intelligence digest
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRadarFlow:
    """Simulates /radar: list feed entries -> synthesize -> store digest."""

    async def test_radar_no_feed_entries(self, skill_store: DuckDBStore) -> None:
        """When no feed entries exist, radar shows empty message."""
        list_resp = _parse(
            await _handle_list(
                skill_store, {"entry_type": "feed", "limit": 20, "output_mode": "summary"}
            )
        )
        assert list_resp["count"] == 0

    async def test_radar_with_feed_entries(self, skill_store: DuckDBStore) -> None:
        """Radar lists feed entries and stores a digest."""
        # Seed feed entries (simulating polled items)
        feed_items = [
            "New release: DuckDB 1.2 adds improved HNSW performance",
            "GitHub trending: vector-search libraries gaining traction",
            "RSS: Claude Code now supports MCP server configuration",
        ]
        for content in feed_items:
            await _handle_store(
                skill_store,
                {
                    "content": content,
                    "entry_type": "feed",
                    "author": "feed-poller",
                    "tags": ["source/rss", "domain/technology"],
                },
            )

        # Step 3: retrieve recent feed entries
        list_resp = _parse(
            await _handle_list(
                skill_store, {"entry_type": "feed", "limit": 20, "output_mode": "summary"}
            )
        )
        assert list_resp["count"] == 3

        # Step 6: store digest
        digest_content = (
            "# Radar Digest — 2026-04-03\n\n"
            "3 feed entries from the last 7 days.\n\n"
            "## Technology\n"
            "DuckDB 1.2 improves HNSW performance. Vector search libraries trending. "
            "Claude Code adds MCP server configuration.\n\n"
            "## Overall Summary\n"
            "Active development in vector search and AI tooling ecosystems."
        )
        digest_resp = _parse(
            await _handle_store(
                skill_store,
                {
                    "content": digest_content,
                    "entry_type": "digest",
                    "author": "Alice",
                    "tags": ["digest", "radar", "ambient"],
                },
            )
        )
        assert "entry_id" in digest_resp

        # Verify digest stored
        get_resp = _parse(await _handle_get(skill_store, {"entry_id": digest_resp["entry_id"]}))
        assert get_resp["entry_type"] == "digest"
        assert "radar" in get_resp["tags"]


# ---------------------------------------------------------------------------
# 9. /tune — feed relevance thresholds
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTuneFlow:
    """Simulates /tune: read thresholds via status."""

    async def test_tune_read_thresholds(
        self, skill_store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Status returns feed threshold configuration."""
        provider = HashEmbeddingProvider(dimensions=4)
        status_resp = _parse(await _handle_status(skill_store, provider, config))
        assert status_resp["status"] == "ok"
        assert "total_entries" in status_resp
        assert "embedding_model" in status_resp
        # Thresholds are in the config object, not status response directly.
        # The skill reads config and displays them.
        assert config.feeds.thresholds.alert == 0.85
        assert config.feeds.thresholds.digest == 0.60

    async def test_tune_status_with_entries(
        self, skill_store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Status reflects correct entry counts after seeding data."""
        for i in range(5):
            await _handle_store(
                skill_store,
                {"content": f"Entry {i}", "entry_type": "session", "author": "Alice"},
            )

        provider = HashEmbeddingProvider(dimensions=4)
        status_resp = _parse(await _handle_status(skill_store, provider, config))
        assert status_resp["total_entries"] == 5
        assert status_resp["entries_by_type"]["session"] == 5


# ---------------------------------------------------------------------------
# 10. /setup — onboarding wizard
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSetupFlow:
    """Simulates /setup: status check + watch list + transport detection."""

    async def test_setup_mcp_connected(
        self, skill_store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Step 1: verify MCP connectivity via status."""
        provider = HashEmbeddingProvider(dimensions=4)
        status_resp = _parse(await _handle_status(skill_store, provider, config))
        assert status_resp["status"] == "ok"
        assert "total_entries" in status_resp
        assert "embedding_model" in status_resp
        assert "database_size_bytes" in status_resp

    async def test_setup_check_feed_sources(self, skill_store: DuckDBStore) -> None:
        """Step 3: check feed sources via watch list."""
        watch_resp = _parse(await _handle_watch(skill_store, {"action": "list"}))
        assert watch_resp["count"] == 0
        assert watch_resp["sources"] == []

    async def test_setup_full_flow(
        self, skill_store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Full setup: status -> watch list -> add source -> verify."""
        provider = HashEmbeddingProvider(dimensions=4)

        # Step 1: check MCP
        status_resp = _parse(await _handle_status(skill_store, provider, config))
        assert status_resp["status"] == "ok"

        # Step 3: check feed sources
        watch_resp = _parse(await _handle_watch(skill_store, {"action": "list"}))
        assert watch_resp["count"] == 0

        # User adds a source during setup
        add_resp = _parse(
            await _handle_watch(
                skill_store,
                {
                    "action": "add",
                    "url": "https://hnrss.org/newest?q=claude",
                    "source_type": "rss",
                    "label": "HN Claude",
                },
            )
        )
        assert add_resp["added"] is True

        # Verify final state
        final_watch = _parse(await _handle_watch(skill_store, {"action": "list"}))
        assert final_watch["count"] == 1

        final_status = _parse(await _handle_status(skill_store, provider, config))
        assert final_status["status"] == "ok"


# ---------------------------------------------------------------------------
# Cross-skill integration tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCrossSkillFlows:
    """Tests that span multiple skill flows."""

    async def test_distill_then_recall(
        self, skill_store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Distill a session, then recall it."""
        content = "Decided to implement rate limiting with a sliding window algorithm"
        dedup_resp = _parse(await _handle_check_dedup(skill_store, config, {"content": content}))
        assert dedup_resp["action"] == "create"

        store_resp = _parse(
            await _handle_store(
                skill_store,
                {
                    "content": content,
                    "entry_type": "session",
                    "author": "Alice",
                    "project": "api-gateway",
                    "tags": ["domain/rate-limiting"],
                },
            )
        )
        entry_id = store_resp["entry_id"]

        # Recall it
        search_resp = _parse(
            await _handle_search(skill_store, {"query": "rate limiting sliding window"})
        )
        assert search_resp["count"] >= 1
        found_ids = [r["entry"]["id"] for r in search_resp["results"]]
        assert entry_id in found_ids

    async def test_bookmark_then_classify(
        self, skill_store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Bookmark an inbox-type entry, then classify it."""
        store_resp = _parse(
            await _handle_store(
                skill_store,
                {
                    "content": "Article about distributed consensus algorithms",
                    "entry_type": "inbox",
                    "author": "Bob",
                    "metadata": {"url": "https://example.com/consensus"},
                },
            )
        )
        entry_id = store_resp["entry_id"]

        # Classify as bookmark
        classify_resp = _parse(
            await _handle_classify(
                skill_store,
                config,
                {
                    "entry_id": entry_id,
                    "entry_type": "bookmark",
                    "confidence": 0.9,
                    "reasoning": "URL in metadata indicates saved web content",
                    "suggested_tags": ["domain/distributed-systems"],
                },
            )
        )
        assert classify_resp["entry_type"] == "bookmark"
        assert classify_resp["status"] == "active"

    async def test_minutes_then_pour(self, skill_store: DuckDBStore) -> None:
        """Store meeting notes, then pour/synthesize across them."""
        meetings = [
            ("Auth design: decided on JWT with refresh tokens", "auth-design-2026-03-01"),
            ("Auth review: added rate limiting to token endpoint", "auth-review-2026-03-15"),
            ("Auth postmortem: token rotation bug in edge case", "auth-postmortem-2026-04-01"),
        ]
        for content, meeting_id in meetings:
            await _handle_store(
                skill_store,
                {
                    "content": content,
                    "entry_type": "minutes",
                    "author": "Alice",
                    "project": "api-gateway",
                    "tags": ["domain/auth"],
                    "metadata": {"meeting_id": meeting_id},
                },
            )

        # Pour: multi-pass search
        pass1 = _parse(
            await _handle_search(skill_store, {"query": "authentication JWT tokens", "limit": 20})
        )
        pass2 = _parse(
            await _handle_search(skill_store, {"query": "token rotation rate limiting", "limit": 20})
        )

        all_ids = {r["entry"]["id"] for r in pass1["results"]} | {
            r["entry"]["id"] for r in pass2["results"]
        }
        assert len(all_ids) >= 2

    async def test_watch_then_radar_then_tune(
        self, skill_store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Full ambient intelligence flow: add source, seed feeds, generate digest."""
        # /watch add
        await _handle_watch(
            skill_store,
            {
                "action": "add",
                "url": "https://blog.example.com/feed.xml",
                "source_type": "rss",
                "label": "Tech Blog",
            },
        )

        # Simulate polled feed entries
        for i in range(3):
            await _handle_store(
                skill_store,
                {
                    "content": f"Feed item {i}: latest developments in AI tooling",
                    "entry_type": "feed",
                    "author": "feed-poller",
                    "tags": ["source/rss"],
                },
            )

        # /radar: list feed entries
        feed_list = _parse(
            await _handle_list(skill_store, {"entry_type": "feed", "limit": 20})
        )
        assert feed_list["count"] == 3

        # Store digest
        digest_resp = _parse(
            await _handle_store(
                skill_store,
                {
                    "content": "Radar digest: 3 items about AI tooling",
                    "entry_type": "digest",
                    "author": "Alice",
                    "tags": ["digest", "radar", "ambient"],
                },
            )
        )
        assert "entry_id" in digest_resp

        # /tune: verify status
        provider = HashEmbeddingProvider(dimensions=4)
        status_resp = _parse(await _handle_status(skill_store, provider, config))
        assert status_resp["total_entries"] == 4  # 3 feed + 1 digest
        assert status_resp["entries_by_type"]["feed"] == 3
        assert status_resp["entries_by_type"]["digest"] == 1
