"""Tests for the expires_at feature.

Covers:
  - Store an entry with an expiry date
  - Update an entry's expiry date
  - Stale handler returns expired entries with reason="expired"
  - Non-expired entries are not flagged
  - Null expiry is ignored by the stale handler
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from distillery.config import (
    ClassificationConfig,
    DefaultsConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp.tools.analytics import _handle_stale
from distillery.mcp.tools.crud import _handle_store, _handle_update
from distillery.store.duckdb import DuckDBStore
from tests.conftest import MockEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(stale_days: int = 30) -> DistilleryConfig:
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="mock-hash-4d", dimensions=4),
        classification=ClassificationConfig(confidence_threshold=0.6),
        defaults=DefaultsConfig(stale_days=stale_days),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider() -> MockEmbeddingProvider:
    return MockEmbeddingProvider()


@pytest.fixture
async def store(embedding_provider: MockEmbeddingProvider) -> DuckDBStore:  # type: ignore[return]
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def config() -> DistilleryConfig:
    return _make_config()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStoreWithExpiry:
    """Store entries with expires_at set."""

    async def test_store_with_expiry(self, store: DuckDBStore) -> None:
        future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
        entry = make_entry(content="Expiring entry", expires_at=datetime.fromisoformat(future))
        entry_id = await store.store(entry)
        fetched = await store.get(entry_id)
        assert fetched is not None
        assert fetched.expires_at is not None

    async def test_store_without_expiry(self, store: DuckDBStore) -> None:
        entry = make_entry(content="No expiry entry")
        entry_id = await store.store(entry)
        fetched = await store.get(entry_id)
        assert fetched is not None
        assert fetched.expires_at is None

    async def test_store_via_mcp_handler(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        future = (datetime.now(UTC) + timedelta(days=7)).isoformat()
        result = await _handle_store(
            store=store,
            arguments={
                "content": "MCP expiry entry",
                "entry_type": "inbox",
                "author": "tester",
                "expires_at": future,
            },
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert "error" not in data
        assert "entry_id" in data
        fetched = await store.get(data["entry_id"])
        assert fetched is not None
        assert fetched.expires_at is not None


class TestUpdateExpiry:
    """Update expires_at on an existing entry."""

    async def test_update_expiry(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Update expiry test")
        await store.store(entry)

        new_expiry = datetime.now(UTC) + timedelta(days=14)
        updated = await store.update(entry.id, {"expires_at": new_expiry})
        assert updated.expires_at is not None

    async def test_update_expiry_via_mcp_handler(self, store: DuckDBStore) -> None:
        entry = make_entry(content="MCP update expiry")
        await store.store(entry)

        future = (datetime.now(UTC) + timedelta(days=14)).isoformat()
        result = await _handle_update(
            store=store,
            arguments={"entry_id": entry.id, "expires_at": future},
        )
        data = parse_mcp_response(result)
        assert "error" not in data
        assert data["expires_at"] is not None


class TestStaleHandlerExpired:
    """Stale handler should return expired entries with reason='expired'."""

    async def test_expired_entry_appears_in_stale(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        past = datetime.now(UTC) - timedelta(days=1)
        entry = make_entry(content="Already expired", expires_at=past)
        await store.store(entry)

        response = await _handle_stale(store, config, {"days": 30})
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["expired_count"] >= 1
        expired_ids = [e["id"] for e in data["entries"] if e.get("reason") == "expired"]
        assert entry.id in expired_ids

    async def test_non_expired_entry_not_flagged(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        future = datetime.now(UTC) + timedelta(days=30)
        entry = make_entry(content="Not yet expired", expires_at=future)
        await store.store(entry)

        response = await _handle_stale(store, config, {"days": 30})
        data = parse_mcp_response(response)
        expired_ids = [e["id"] for e in data["entries"] if e.get("reason") == "expired"]
        assert entry.id not in expired_ids

    async def test_null_expiry_ignored(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        entry = make_entry(content="No expiry set")
        await store.store(entry)

        response = await _handle_stale(store, config, {"days": 30})
        data = parse_mcp_response(response)
        expired_ids = [e["id"] for e in data["entries"] if e.get("reason") == "expired"]
        assert entry.id not in expired_ids

    async def test_stale_entries_have_reason_stale(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Old entry no expiry")
        await store.store(entry)
        # Force timestamps into the past
        conn = store.connection
        ts = (datetime.now(UTC) - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE entries SET updated_at = ?, accessed_at = ? WHERE id = ?",
            [ts, ts, entry.id],
        )

        response = await _handle_stale(store, config, {"days": 30})
        data = parse_mcp_response(response)
        stale_entries = [e for e in data["entries"] if e.get("reason") == "stale"]
        stale_ids = [e["id"] for e in stale_entries]
        assert entry.id in stale_ids


class TestEntryRoundtrip:
    """expires_at survives to_dict/from_dict roundtrip."""

    def test_expires_at_roundtrip(self) -> None:
        from distillery.models import Entry

        future = datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC)
        entry = make_entry(content="Roundtrip test", expires_at=future)
        d = entry.to_dict()
        assert d["expires_at"] == future.isoformat()
        restored = Entry.from_dict(d)
        assert restored.expires_at == future

    def test_expires_at_none_roundtrip(self) -> None:
        from distillery.models import Entry

        entry = make_entry(content="No expiry roundtrip")
        d = entry.to_dict()
        assert d["expires_at"] is None
        restored = Entry.from_dict(d)
        assert restored.expires_at is None
