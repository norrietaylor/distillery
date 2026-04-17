"""Tests for the MCP classification tools (T02).

Tests cover classification tools via direct handler calls with a mock
store and mocked classification engine:

  distillery_classify -> distillery_list(output_mode="review") -> distillery_resolve_review

The test harness exercises the server handlers directly without requiring a
running stdio transport.  All handlers are async functions that accept a
store object and an arguments dict -- this is the natural unit-test seam.
"""

from __future__ import annotations

import pytest

from distillery.config import (
    ClassificationConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp.tools.classify import (
    _handle_classify,
    _handle_resolve_review,
)
from distillery.mcp.tools.crud import _handle_list
from distillery.models import EntrySource, EntryStatus, EntryType, VerificationStatus
from distillery.store.duckdb import DuckDBStore
from tests.conftest import make_entry, parse_mcp_response

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store(deterministic_embedding_provider) -> DuckDBStore:  # type: ignore[return]
    """Initialised in-memory DuckDBStore, closed after each test."""
    s = DuckDBStore(db_path=":memory:", embedding_provider=deterministic_embedding_provider)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def config() -> DistilleryConfig:
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
        classification=ClassificationConfig(confidence_threshold=0.6),
    )


# ---------------------------------------------------------------------------
# distillery_classify tests
# ---------------------------------------------------------------------------


class TestClassifyTool:
    async def test_classify_updates_entry_type_and_status_above_threshold(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """High confidence -> status=active."""
        entry = make_entry(content="Today I explored the auth module deeply.")
        entry_id = await store.store(entry)

        response = await _handle_classify(
            store,
            config,
            {
                "entry_id": entry_id,
                "entry_type": "session",
                "confidence": 0.9,
                "reasoning": "Looks like a session entry",
            },
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["entry_type"] == "session"
        assert data["status"] == "active"
        assert data["metadata"]["confidence"] == 0.9
        assert data["metadata"]["classified_at"]
        assert data["metadata"]["classification_reasoning"] == "Looks like a session entry"

    async def test_classify_sets_pending_review_below_threshold(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Low confidence -> status=pending_review."""
        entry = make_entry(content="Some ambiguous content here.")
        entry_id = await store.store(entry)

        response = await _handle_classify(
            store,
            config,
            {
                "entry_id": entry_id,
                "entry_type": "inbox",
                "confidence": 0.3,
            },
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["status"] == "pending_review"
        assert data["metadata"]["confidence"] == 0.3

    async def test_classify_merges_suggested_tags(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Suggested tags are merged with existing tags, no duplicates."""
        entry = make_entry(content="Auth exploration", tags=["auth", "security"])
        entry_id = await store.store(entry)

        response = await _handle_classify(
            store,
            config,
            {
                "entry_id": entry_id,
                "entry_type": "session",
                "confidence": 0.8,
                "suggested_tags": ["security", "oauth2"],
            },
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert "auth" in data["tags"]
        assert "security" in data["tags"]
        assert "oauth2" in data["tags"]
        # security should not appear twice
        assert data["tags"].count("security") == 1

    async def test_classify_sets_suggested_project_when_entry_has_none(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Feature work for the API", project=None)
        entry_id = await store.store(entry)

        response = await _handle_classify(
            store,
            config,
            {
                "entry_id": entry_id,
                "entry_type": "reference",
                "confidence": 0.75,
                "suggested_project": "api-refactor",
            },
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["project"] == "api-refactor"

    async def test_classify_does_not_overwrite_existing_project(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Session notes", project="existing-project")
        entry_id = await store.store(entry)

        response = await _handle_classify(
            store,
            config,
            {
                "entry_id": entry_id,
                "entry_type": "session",
                "confidence": 0.8,
                "suggested_project": "new-project",
            },
        )
        data = parse_mcp_response(response)
        assert data["project"] == "existing-project"

    async def test_classify_records_reclassified_from_on_second_classify(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Second classification stores previous type in reclassified_from."""
        entry = make_entry(content="Meeting about Q1 planning.")
        entry_id = await store.store(entry)

        # First classification
        await _handle_classify(
            store,
            config,
            {"entry_id": entry_id, "entry_type": "inbox", "confidence": 0.4},
        )
        # Second classification (reclassify)
        response = await _handle_classify(
            store,
            config,
            {"entry_id": entry_id, "entry_type": "minutes", "confidence": 0.85},
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["metadata"]["reclassified_from"] == "inbox"

    async def test_classify_returns_not_found_for_missing_entry(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_classify(
            store,
            config,
            {
                "entry_id": "00000000-0000-0000-0000-000000000000",
                "entry_type": "session",
                "confidence": 0.8,
            },
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"

    async def test_classify_validates_missing_required_fields(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_classify(store, config, {"entry_id": "abc"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_classify_validates_invalid_entry_type(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Test content")
        entry_id = await store.store(entry)

        response = await _handle_classify(
            store,
            config,
            {"entry_id": entry_id, "entry_type": "bogus_type", "confidence": 0.9},
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_classify_validates_confidence_out_of_range(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Test content")
        entry_id = await store.store(entry)

        response = await _handle_classify(
            store,
            config,
            {"entry_id": entry_id, "entry_type": "session", "confidence": 1.5},
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# distillery_review_queue tests
# ---------------------------------------------------------------------------


class TestReviewQueueTool:
    async def test_review_queue_returns_pending_entries(self, store: DuckDBStore) -> None:
        """Returns only pending_review entries via distillery_list(output_mode='review')."""
        pending = make_entry(content="Needs review", status=EntryStatus.PENDING_REVIEW)
        active = make_entry(content="Already active", status=EntryStatus.ACTIVE)
        await store.store(pending)
        await store.store(active)

        response = await _handle_list(store, {"output_mode": "review"})
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["count"] == 1
        assert data["entries"][0]["id"] == pending.id

    async def test_review_queue_entry_shape(self, store: DuckDBStore) -> None:
        """Each entry contains required fields."""
        entry = make_entry(
            content="A" * 300,
            status=EntryStatus.PENDING_REVIEW,
            metadata={"confidence": 0.4, "classification_reasoning": "Unclear"},
        )
        await store.store(entry)

        response = await _handle_list(store, {"output_mode": "review"})
        data = parse_mcp_response(response)
        item = data["entries"][0]

        assert "id" in item
        assert "content_preview" in item
        assert len(item["content_preview"]) <= 200
        assert "entry_type" in item
        assert "confidence" in item
        assert item["confidence"] == 0.4
        assert "author" in item
        assert "created_at" in item
        assert item["classification_reasoning"] == "Unclear"

    async def test_review_queue_filters_by_entry_type(self, store: DuckDBStore) -> None:
        session = make_entry(
            content="A session entry",
            entry_type=EntryType.SESSION,
            status=EntryStatus.PENDING_REVIEW,
        )
        inbox = make_entry(
            content="An inbox entry",
            entry_type=EntryType.INBOX,
            status=EntryStatus.PENDING_REVIEW,
        )
        await store.store(session)
        await store.store(inbox)

        response = await _handle_list(store, {"output_mode": "review", "entry_type": "session"})
        data = parse_mcp_response(response)
        assert data["count"] == 1
        assert data["entries"][0]["entry_type"] == "session"

    async def test_review_queue_respects_limit(self, store: DuckDBStore) -> None:
        for i in range(5):
            e = make_entry(content=f"Entry {i}", status=EntryStatus.PENDING_REVIEW)
            await store.store(e)

        response = await _handle_list(store, {"output_mode": "review", "limit": 3})
        data = parse_mcp_response(response)
        assert data["count"] == 3

    async def test_review_queue_returns_empty_when_none_pending(self, store: DuckDBStore) -> None:
        entry = make_entry(status=EntryStatus.ACTIVE)
        await store.store(entry)

        response = await _handle_list(store, {"output_mode": "review"})
        data = parse_mcp_response(response)
        assert data["count"] == 0
        assert data["entries"] == []

    async def test_review_queue_validates_bad_limit(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"output_mode": "review", "limit": 0})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_review_queue_invalid_entry_type_returns_empty(self, store: DuckDBStore) -> None:
        """An unrecognised entry_type passes through as a filter, returning empty results."""
        response = await _handle_list(store, {"output_mode": "review", "entry_type": "not_a_type"})
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["count"] == 0

    async def test_review_queue_filters_by_project(self, store: DuckDBStore) -> None:
        """project parameter filters results to matching project only."""
        alpha = make_entry(
            content="Entry for project alpha",
            status=EntryStatus.PENDING_REVIEW,
            project="alpha",
        )
        beta = make_entry(
            content="Entry for project beta",
            status=EntryStatus.PENDING_REVIEW,
            project="beta",
        )
        no_project = make_entry(
            content="Entry with no project",
            status=EntryStatus.PENDING_REVIEW,
        )
        await store.store(alpha)
        await store.store(beta)
        await store.store(no_project)

        response = await _handle_list(store, {"output_mode": "review", "project": "alpha"})
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["count"] == 1
        assert data["entries"][0]["id"] == alpha.id


# ---------------------------------------------------------------------------
# distillery_resolve_review tests
# ---------------------------------------------------------------------------


class TestResolveReviewTool:
    async def test_resolve_approve_sets_status_active(self, store: DuckDBStore) -> None:
        entry = make_entry(status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)

        response = await _handle_resolve_review(
            store, {"entry_id": entry_id, "action": "approve", "reviewer": "bob"}
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["status"] == "active"
        assert data["metadata"]["reviewed_at"]
        assert data["metadata"]["reviewed_by"] == "bob"

    async def test_resolve_archive_sets_status_archived(self, store: DuckDBStore) -> None:
        entry = make_entry(status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)

        response = await _handle_resolve_review(store, {"entry_id": entry_id, "action": "archive"})
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["status"] == "archived"
        assert data["metadata"]["archived_at"]

    async def test_resolve_reclassify_updates_entry_type(self, store: DuckDBStore) -> None:
        entry = make_entry(entry_type=EntryType.INBOX, status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)

        response = await _handle_resolve_review(
            store,
            {
                "entry_id": entry_id,
                "action": "reclassify",
                "new_entry_type": "meeting",
                "reviewer": "alice",
            },
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["entry_type"] == "meeting"
        assert data["metadata"]["reclassified_from"] == "inbox"
        assert data["metadata"]["reviewed_at"]
        assert data["metadata"]["reviewed_by"] == "alice"

    async def test_resolve_reclassify_requires_new_entry_type(self, store: DuckDBStore) -> None:
        entry = make_entry(status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)

        response = await _handle_resolve_review(
            store, {"entry_id": entry_id, "action": "reclassify"}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_resolve_reclassify_validates_new_entry_type(self, store: DuckDBStore) -> None:
        entry = make_entry(status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)

        response = await _handle_resolve_review(
            store,
            {
                "entry_id": entry_id,
                "action": "reclassify",
                "new_entry_type": "invalid_type",
            },
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_resolve_returns_not_found_for_missing_entry(self, store: DuckDBStore) -> None:
        response = await _handle_resolve_review(
            store,
            {
                "entry_id": "00000000-0000-0000-0000-000000000000",
                "action": "approve",
            },
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"

    async def test_resolve_validates_missing_required_fields(self, store: DuckDBStore) -> None:
        response = await _handle_resolve_review(store, {"entry_id": "abc"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_resolve_validates_invalid_action(self, store: DuckDBStore) -> None:
        entry = make_entry(status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)

        response = await _handle_resolve_review(store, {"entry_id": entry_id, "action": "reject"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_resolve_approve_without_reviewer(self, store: DuckDBStore) -> None:
        """Reviewer field is optional."""
        entry = make_entry(status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)

        response = await _handle_resolve_review(store, {"entry_id": entry_id, "action": "approve"})
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["status"] == "active"
        assert "reviewed_by" not in data["metadata"]


# ---------------------------------------------------------------------------
# End-to-end classification flow
# ---------------------------------------------------------------------------


class TestClassificationEndToEnd:
    """Full lifecycle: classify -> review_queue -> resolve."""

    async def test_full_classify_review_resolve_flow(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        # Step 1: Create an entry
        entry = make_entry(content="We discussed the Q1 roadmap in today's meeting.")
        entry_id = await store.store(entry)

        # Step 2: Classify it (low confidence -> pending_review)
        classify_response = await _handle_classify(
            store,
            config,
            {
                "entry_id": entry_id,
                "entry_type": "minutes",
                "confidence": 0.4,
                "reasoning": "Looks like meeting notes but not sure",
                "suggested_tags": ["planning", "q1"],
            },
        )
        classify_data = parse_mcp_response(classify_response)
        assert classify_data["status"] == "pending_review"
        assert classify_data["entry_type"] == "minutes"

        # Step 3: Check it appears in the review queue
        queue_response = await _handle_list(store, {"output_mode": "review"})
        queue_data = parse_mcp_response(queue_response)
        assert queue_data["count"] >= 1
        queue_ids = [e["id"] for e in queue_data["entries"]]
        assert entry_id in queue_ids

        # Step 4: Resolve by approving
        resolve_response = await _handle_resolve_review(
            store,
            {"entry_id": entry_id, "action": "approve", "reviewer": "reviewer-alice"},
        )
        resolve_data = parse_mcp_response(resolve_response)
        assert resolve_data["status"] == "active"
        assert resolve_data["metadata"]["reviewed_by"] == "reviewer-alice"

        # Step 5: Verify it's no longer in the review queue
        queue_response2 = await _handle_list(store, {"output_mode": "review"})
        queue_data2 = parse_mcp_response(queue_response2)
        queue_ids2 = [e["id"] for e in queue_data2["entries"]]
        assert entry_id not in queue_ids2


# ---------------------------------------------------------------------------
# Batch classification filter tests (issue #301)
# ---------------------------------------------------------------------------


class TestBatchClassificationFilters:
    """Tests for --batch mode composable filters.

    The --batch mode uses distillery_list with flexible filters to retrieve
    entries for bulk classification. These tests verify that the filter
    combinations work correctly via the _handle_list handler.
    """

    async def test_batch_filter_by_entry_type_github(self, store: DuckDBStore) -> None:
        """--batch --entry-type github returns only github entries."""
        github_entry = make_entry(
            content="PR #42 merged",
            entry_type=EntryType.GITHUB,
            source=EntrySource.EXTERNAL,
            metadata={"repo": "org/repo", "ref_type": "pr", "ref_number": 42},
        )
        inbox_entry = make_entry(content="Random inbox item", entry_type=EntryType.INBOX)
        await store.store(github_entry)
        await store.store(inbox_entry)

        response = await _handle_list(
            store,
            {"entry_type": "github", "limit": 50, "output_mode": "full", "content_max_length": 300},
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["count"] == 1
        assert data["entries"][0]["entry_type"] == "github"

    async def test_batch_filter_by_entry_type_feed(self, store: DuckDBStore) -> None:
        """--batch --entry-type feed returns only feed entries."""
        feed_entry = make_entry(
            content="New RSS article about AI",
            entry_type=EntryType.FEED,
            source=EntrySource.EXTERNAL,
            metadata={"source_url": "https://example.com/feed", "source_type": "rss"},
        )
        inbox_entry = make_entry(content="Inbox item", entry_type=EntryType.INBOX)
        await store.store(feed_entry)
        await store.store(inbox_entry)

        response = await _handle_list(
            store,
            {"entry_type": "feed", "limit": 50, "output_mode": "full", "content_max_length": 300},
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["count"] == 1
        assert data["entries"][0]["entry_type"] == "feed"

    async def test_batch_filter_by_source(self, store: DuckDBStore) -> None:
        """--batch --source external returns only entries from external source."""
        external = make_entry(
            content="External feed item",
            entry_type=EntryType.FEED,
            source=EntrySource.EXTERNAL,
            metadata={"source_url": "https://example.com/feed", "source_type": "rss"},
        )
        manual = make_entry(
            content="Manual entry",
            entry_type=EntryType.INBOX,
            source=EntrySource.MANUAL,
        )
        await store.store(external)
        await store.store(manual)

        response = await _handle_list(
            store,
            {"source": "external", "limit": 50, "output_mode": "full", "content_max_length": 300},
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["count"] == 1
        assert data["entries"][0]["id"] == external.id

    async def test_batch_filter_by_author(self, store: DuckDBStore) -> None:
        """--batch --author filters entries by author."""
        alice = make_entry(content="Alice's entry", author="alice")
        bob = make_entry(content="Bob's entry", author="bob")
        await store.store(alice)
        await store.store(bob)

        response = await _handle_list(
            store,
            {"author": "alice", "limit": 50, "output_mode": "full"},
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["count"] == 1
        assert data["entries"][0]["id"] == alice.id

    async def test_batch_filter_composable_and_semantics(self, store: DuckDBStore) -> None:
        """Multiple filters compose with AND semantics."""
        gh_meta = {"repo": "org/repo", "ref_type": "issue", "ref_number": 1}
        feed_meta = {"source_url": "https://example.com/feed", "source_type": "rss"}
        match = make_entry(
            content="GitHub item from external",
            entry_type=EntryType.GITHUB,
            source=EntrySource.EXTERNAL,
            author="alice",
            metadata=gh_meta,
        )
        wrong_type = make_entry(
            content="Feed item from external",
            entry_type=EntryType.FEED,
            source=EntrySource.EXTERNAL,
            author="alice",
            metadata=feed_meta,
        )
        wrong_source = make_entry(
            content="GitHub item from manual",
            entry_type=EntryType.GITHUB,
            source=EntrySource.MANUAL,
            author="alice",
            metadata={**gh_meta, "ref_number": 2},
        )
        wrong_author = make_entry(
            content="GitHub item from bob",
            entry_type=EntryType.GITHUB,
            source=EntrySource.EXTERNAL,
            author="bob",
            metadata={**gh_meta, "ref_number": 3},
        )
        await store.store(match)
        await store.store(wrong_type)
        await store.store(wrong_source)
        await store.store(wrong_author)

        response = await _handle_list(
            store,
            {
                "entry_type": "github",
                "source": "external",
                "author": "alice",
                "limit": 50,
                "output_mode": "full",
            },
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["count"] == 1
        assert data["entries"][0]["id"] == match.id

    async def test_batch_filter_unclassified(self, store: DuckDBStore) -> None:
        """--unclassified resolves to verification=unverified; empty tags checked post-fetch."""
        gh_meta = {"repo": "org/repo", "ref_type": "issue", "ref_number": 10}
        unclassified = make_entry(
            content="Unclassified github entry",
            entry_type=EntryType.GITHUB,
            tags=[],
            verification=VerificationStatus.UNVERIFIED,
            metadata={**gh_meta},
        )
        has_tags = make_entry(
            content="Classified github entry",
            entry_type=EntryType.GITHUB,
            tags=["classified"],
            verification=VerificationStatus.UNVERIFIED,
            metadata={**gh_meta, "ref_number": 11},
        )
        verified = make_entry(
            content="Verified github entry",
            entry_type=EntryType.GITHUB,
            tags=[],
            verification=VerificationStatus.VERIFIED,
            metadata={**gh_meta, "ref_number": 12},
        )
        await store.store(unclassified)
        await store.store(has_tags)
        await store.store(verified)

        # Step 1: distillery_list with verification=unverified (store-level filter)
        response = await _handle_list(
            store,
            {
                "entry_type": "github",
                "verification": "unverified",
                "limit": 50,
                "output_mode": "full",
            },
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        # Both unclassified and has_tags are unverified
        assert data["count"] == 2

        # Step 2: Post-fetch filter to empty tags (done by the skill, not the tool)
        entries_with_empty_tags = [e for e in data["entries"] if e.get("tags") == []]
        assert len(entries_with_empty_tags) == 1
        assert entries_with_empty_tags[0]["id"] == unclassified.id

    async def test_batch_filter_by_project(self, store: DuckDBStore) -> None:
        """--batch --project filters entries by project name."""
        proj_a = make_entry(
            content="Entry for project A",
            entry_type=EntryType.GITHUB,
            project="project-a",
            metadata={"repo": "org/repo-a", "ref_type": "issue", "ref_number": 1},
        )
        proj_b = make_entry(
            content="Entry for project B",
            entry_type=EntryType.GITHUB,
            project="project-b",
            metadata={"repo": "org/repo-b", "ref_type": "issue", "ref_number": 2},
        )
        await store.store(proj_a)
        await store.store(proj_b)

        response = await _handle_list(
            store,
            {
                "entry_type": "github",
                "project": "project-a",
                "limit": 50,
                "output_mode": "full",
            },
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["count"] == 1
        assert data["entries"][0]["id"] == proj_a.id

    async def test_batch_filter_by_tag_prefix(self, store: DuckDBStore) -> None:
        """--batch --tag-prefix filters by tag namespace."""
        feed_meta = {"source_url": "https://example.com/feed", "source_type": "rss"}
        tagged = make_entry(
            content="Tagged entry",
            entry_type=EntryType.FEED,
            tags=["topic/ai", "source/rss"],
            metadata={**feed_meta},
        )
        other = make_entry(
            content="Other entry",
            entry_type=EntryType.FEED,
            tags=["unrelated"],
            metadata={**feed_meta, "source_url": "https://other.com/feed"},
        )
        await store.store(tagged)
        await store.store(other)

        response = await _handle_list(
            store,
            {
                "entry_type": "feed",
                "tag_prefix": "topic",
                "limit": 50,
                "output_mode": "full",
            },
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["count"] == 1
        assert data["entries"][0]["id"] == tagged.id

    async def test_batch_respects_limit_cap(self, store: DuckDBStore) -> None:
        """Batch mode caps at 50 entries per invocation."""
        for i in range(55):
            entry = make_entry(
                content=f"Feed entry {i}",
                entry_type=EntryType.FEED,
                metadata={
                    "source_url": f"https://example.com/feed/{i}",
                    "source_type": "rss",
                },
            )
            await store.store(entry)

        response = await _handle_list(
            store,
            {"entry_type": "feed", "limit": 50, "output_mode": "full", "content_max_length": 300},
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["count"] == 50
        assert data["total_count"] == 55

    async def test_inbox_alias_still_works(self, store: DuckDBStore) -> None:
        """--inbox (Mode B) continues to work as before (no regression)."""
        inbox = make_entry(content="Inbox item", entry_type=EntryType.INBOX)
        github = make_entry(
            content="Github item",
            entry_type=EntryType.GITHUB,
            metadata={"repo": "org/repo", "ref_type": "pr", "ref_number": 99},
        )
        await store.store(inbox)
        await store.store(github)

        response = await _handle_list(
            store,
            {"entry_type": "inbox", "limit": 50, "output_mode": "full", "content_max_length": 300},
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["count"] == 1
        assert data["entries"][0]["entry_type"] == "inbox"
