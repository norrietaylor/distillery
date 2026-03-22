"""Tests for the MCP classification tools (T02).

Tests cover all 3 classification tools via direct handler calls with a mock
store and mocked classification engine:

  distillery_classify -> distillery_review_queue -> distillery_resolve_review

The test harness exercises the server handlers directly without requiring a
running stdio transport.  All handlers are async functions that accept a
store object and an arguments dict -- this is the natural unit-test seam.
"""

from __future__ import annotations

import json
import math

import pytest

from distillery.config import (
    ClassificationConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp.server import (
    _handle_classify,
    _handle_resolve_review,
    _handle_review_queue,
)
from distillery.models import Entry, EntrySource, EntryStatus, EntryType
from distillery.store.duckdb import DuckDBStore


# ---------------------------------------------------------------------------
# Mock embedding provider
# ---------------------------------------------------------------------------


class _DeterministicEmbeddingProvider:
    """4-dimensional deterministic embedding provider for tests."""

    _DIMS = 4

    def __init__(self) -> None:
        self._registry: dict[str, list[float]] = {}

    def _vector_for(self, text: str) -> list[float]:
        if text in self._registry:
            return self._registry[text]
        h = hash(text) & 0xFFFFFFFF
        parts = [(h >> (8 * i)) & 0xFF for i in range(self._DIMS)]
        floats = [float(p) + 1.0 for p in parts]
        magnitude = math.sqrt(sum(x * x for x in floats))
        return [x / magnitude for x in floats]

    def embed(self, text: str) -> list[float]:
        return self._vector_for(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for(t) for t in texts]

    @property
    def dimensions(self) -> int:
        return self._DIMS

    @property
    def model_name(self) -> str:
        return "deterministic-4d"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider() -> _DeterministicEmbeddingProvider:
    return _DeterministicEmbeddingProvider()


@pytest.fixture
async def store(
    embedding_provider: _DeterministicEmbeddingProvider,
) -> DuckDBStore:
    """Initialised in-memory DuckDBStore, closed after each test."""
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
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


def _make_entry(**kwargs) -> Entry:
    """Return a minimal valid Entry with optional overrides."""
    defaults = dict(
        content="Default test content",
        entry_type=EntryType.INBOX,
        source=EntrySource.MANUAL,
        author="test-author",
    )
    defaults.update(kwargs)
    return Entry(**defaults)


def _parse_response(content: list) -> dict:
    """Parse the JSON text from an MCP tool response."""
    assert len(content) == 1, f"Expected 1 content item, got {len(content)}"
    return json.loads(content[0].text)


# ---------------------------------------------------------------------------
# distillery_classify tests
# ---------------------------------------------------------------------------


class TestClassifyTool:
    async def test_classify_updates_entry_type_and_status_above_threshold(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """High confidence -> status=active."""
        entry = _make_entry(content="Today I explored the auth module deeply.")
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
        data = _parse_response(response)
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
        entry = _make_entry(content="Some ambiguous content here.")
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
        data = _parse_response(response)
        assert "error" not in data
        assert data["status"] == "pending_review"
        assert data["metadata"]["confidence"] == 0.3

    async def test_classify_merges_suggested_tags(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Suggested tags are merged with existing tags, no duplicates."""
        entry = _make_entry(content="Auth exploration", tags=["auth", "security"])
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
        data = _parse_response(response)
        assert "error" not in data
        assert "auth" in data["tags"]
        assert "security" in data["tags"]
        assert "oauth2" in data["tags"]
        # security should not appear twice
        assert data["tags"].count("security") == 1

    async def test_classify_sets_suggested_project_when_entry_has_none(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = _make_entry(content="Feature work for the API", project=None)
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
        data = _parse_response(response)
        assert "error" not in data
        assert data["project"] == "api-refactor"

    async def test_classify_does_not_overwrite_existing_project(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = _make_entry(content="Session notes", project="existing-project")
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
        data = _parse_response(response)
        assert data["project"] == "existing-project"

    async def test_classify_records_reclassified_from_on_second_classify(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Second classification stores previous type in reclassified_from."""
        entry = _make_entry(content="Meeting about Q1 planning.")
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
        data = _parse_response(response)
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
        data = _parse_response(response)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"

    async def test_classify_validates_missing_required_fields(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_classify(store, config, {"entry_id": "abc"})
        data = _parse_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_INPUT"

    async def test_classify_validates_invalid_entry_type(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = _make_entry(content="Test content")
        entry_id = await store.store(entry)

        response = await _handle_classify(
            store,
            config,
            {"entry_id": entry_id, "entry_type": "bogus_type", "confidence": 0.9},
        )
        data = _parse_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_INPUT"

    async def test_classify_validates_confidence_out_of_range(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = _make_entry(content="Test content")
        entry_id = await store.store(entry)

        response = await _handle_classify(
            store,
            config,
            {"entry_id": entry_id, "entry_type": "session", "confidence": 1.5},
        )
        data = _parse_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# distillery_review_queue tests
# ---------------------------------------------------------------------------


class TestReviewQueueTool:
    async def test_review_queue_returns_pending_entries(
        self, store: DuckDBStore
    ) -> None:
        """Returns only pending_review entries."""
        pending = _make_entry(content="Needs review", status=EntryStatus.PENDING_REVIEW)
        active = _make_entry(content="Already active", status=EntryStatus.ACTIVE)
        await store.store(pending)
        await store.store(active)

        response = await _handle_review_queue(store, {})
        data = _parse_response(response)
        assert "error" not in data
        assert data["count"] == 1
        assert data["entries"][0]["id"] == pending.id

    async def test_review_queue_entry_shape(self, store: DuckDBStore) -> None:
        """Each entry contains required fields."""
        entry = _make_entry(
            content="A" * 300,
            status=EntryStatus.PENDING_REVIEW,
            metadata={"confidence": 0.4, "classification_reasoning": "Unclear"},
        )
        await store.store(entry)

        response = await _handle_review_queue(store, {})
        data = _parse_response(response)
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

    async def test_review_queue_filters_by_entry_type(
        self, store: DuckDBStore
    ) -> None:
        session = _make_entry(
            content="A session entry", entry_type=EntryType.SESSION,
            status=EntryStatus.PENDING_REVIEW,
        )
        inbox = _make_entry(
            content="An inbox entry", entry_type=EntryType.INBOX,
            status=EntryStatus.PENDING_REVIEW,
        )
        await store.store(session)
        await store.store(inbox)

        response = await _handle_review_queue(store, {"entry_type": "session"})
        data = _parse_response(response)
        assert data["count"] == 1
        assert data["entries"][0]["entry_type"] == "session"

    async def test_review_queue_respects_limit(self, store: DuckDBStore) -> None:
        for i in range(5):
            e = _make_entry(content=f"Entry {i}", status=EntryStatus.PENDING_REVIEW)
            await store.store(e)

        response = await _handle_review_queue(store, {"limit": 3})
        data = _parse_response(response)
        assert data["count"] == 3

    async def test_review_queue_returns_empty_when_none_pending(
        self, store: DuckDBStore
    ) -> None:
        entry = _make_entry(status=EntryStatus.ACTIVE)
        await store.store(entry)

        response = await _handle_review_queue(store, {})
        data = _parse_response(response)
        assert data["count"] == 0
        assert data["entries"] == []

    async def test_review_queue_validates_bad_limit(
        self, store: DuckDBStore
    ) -> None:
        response = await _handle_review_queue(store, {"limit": 0})
        data = _parse_response(response)
        assert data["error"] is True
        assert data["code"] == "VALIDATION_ERROR"

    async def test_review_queue_validates_invalid_entry_type(
        self, store: DuckDBStore
    ) -> None:
        response = await _handle_review_queue(store, {"entry_type": "not_a_type"})
        data = _parse_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# distillery_resolve_review tests
# ---------------------------------------------------------------------------


class TestResolveReviewTool:
    async def test_resolve_approve_sets_status_active(
        self, store: DuckDBStore
    ) -> None:
        entry = _make_entry(status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)

        response = await _handle_resolve_review(
            store, {"entry_id": entry_id, "action": "approve", "reviewer": "bob"}
        )
        data = _parse_response(response)
        assert "error" not in data
        assert data["status"] == "active"
        assert data["metadata"]["reviewed_at"]
        assert data["metadata"]["reviewed_by"] == "bob"

    async def test_resolve_archive_sets_status_archived(
        self, store: DuckDBStore
    ) -> None:
        entry = _make_entry(status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)

        response = await _handle_resolve_review(
            store, {"entry_id": entry_id, "action": "archive"}
        )
        data = _parse_response(response)
        assert "error" not in data
        assert data["status"] == "archived"
        assert data["metadata"]["archived_at"]

    async def test_resolve_reclassify_updates_entry_type(
        self, store: DuckDBStore
    ) -> None:
        entry = _make_entry(entry_type=EntryType.INBOX, status=EntryStatus.PENDING_REVIEW)
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
        data = _parse_response(response)
        assert "error" not in data
        assert data["entry_type"] == "meeting"
        assert data["metadata"]["reclassified_from"] == "inbox"
        assert data["metadata"]["reviewed_at"]
        assert data["metadata"]["reviewed_by"] == "alice"

    async def test_resolve_reclassify_requires_new_entry_type(
        self, store: DuckDBStore
    ) -> None:
        entry = _make_entry(status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)

        response = await _handle_resolve_review(
            store, {"entry_id": entry_id, "action": "reclassify"}
        )
        data = _parse_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_INPUT"

    async def test_resolve_reclassify_validates_new_entry_type(
        self, store: DuckDBStore
    ) -> None:
        entry = _make_entry(status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)

        response = await _handle_resolve_review(
            store,
            {
                "entry_id": entry_id,
                "action": "reclassify",
                "new_entry_type": "invalid_type",
            },
        )
        data = _parse_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_INPUT"

    async def test_resolve_returns_not_found_for_missing_entry(
        self, store: DuckDBStore
    ) -> None:
        response = await _handle_resolve_review(
            store,
            {
                "entry_id": "00000000-0000-0000-0000-000000000000",
                "action": "approve",
            },
        )
        data = _parse_response(response)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"

    async def test_resolve_validates_missing_required_fields(
        self, store: DuckDBStore
    ) -> None:
        response = await _handle_resolve_review(store, {"entry_id": "abc"})
        data = _parse_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_INPUT"

    async def test_resolve_validates_invalid_action(
        self, store: DuckDBStore
    ) -> None:
        entry = _make_entry(status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)

        response = await _handle_resolve_review(
            store, {"entry_id": entry_id, "action": "reject"}
        )
        data = _parse_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_INPUT"

    async def test_resolve_approve_without_reviewer(
        self, store: DuckDBStore
    ) -> None:
        """Reviewer field is optional."""
        entry = _make_entry(status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)

        response = await _handle_resolve_review(
            store, {"entry_id": entry_id, "action": "approve"}
        )
        data = _parse_response(response)
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
        entry = _make_entry(content="We discussed the Q1 roadmap in today's meeting.")
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
        classify_data = _parse_response(classify_response)
        assert classify_data["status"] == "pending_review"
        assert classify_data["entry_type"] == "minutes"

        # Step 3: Check it appears in the review queue
        queue_response = await _handle_review_queue(store, {})
        queue_data = _parse_response(queue_response)
        assert queue_data["count"] >= 1
        queue_ids = [e["id"] for e in queue_data["entries"]]
        assert entry_id in queue_ids

        # Step 4: Resolve by approving
        resolve_response = await _handle_resolve_review(
            store,
            {"entry_id": entry_id, "action": "approve", "reviewer": "reviewer-alice"},
        )
        resolve_data = _parse_response(resolve_response)
        assert resolve_data["status"] == "active"
        assert resolve_data["metadata"]["reviewed_by"] == "reviewer-alice"

        # Step 5: Verify it's no longer in the review queue
        queue_response2 = await _handle_review_queue(store, {})
        queue_data2 = _parse_response(queue_response2)
        queue_ids2 = [e["id"] for e in queue_data2["entries"]]
        assert entry_id not in queue_ids2
