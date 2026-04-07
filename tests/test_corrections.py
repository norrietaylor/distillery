"""Tests for the corrections chain feature.

Covers:
  - Correct an entry: new entry created, original archived
  - Correction chain (corrects_id linkage)
  - get_corrections returns corrections for an entry
  - Chain of 3: correct a correction
  - Non-existent wrong_entry_id returns error
"""

from __future__ import annotations

import pytest

from distillery.config import (
    ClassificationConfig,
    DefaultsConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp.tools.crud import _handle_correct
from distillery.models import EntryStatus
from distillery.store.duckdb import DuckDBStore
from tests.conftest import MockEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config() -> DistilleryConfig:
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="mock-hash-4d", dimensions=4),
        classification=ClassificationConfig(confidence_threshold=0.6),
        defaults=DefaultsConfig(),
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


class TestCorrectEntry:
    """Correct an entry: new entry created, original archived."""

    async def test_correct_creates_new_and_archives_original(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        original = make_entry(content="Wrong information")
        await store.store(original)

        result = await _handle_correct(
            store=store,
            arguments={
                "wrong_entry_id": original.id,
                "content": "Corrected information",
            },
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert "error" not in data
        assert "new_entry_id" in data
        assert data["archived_entry_id"] == original.id
        assert data["corrects_id"] == original.id

        # Verify original is archived (check DB directly since get() may
        # skip archived entries depending on implementation).
        conn = store.connection
        row = conn.execute("SELECT status FROM entries WHERE id = ?", [original.id]).fetchone()
        assert row is not None
        assert row[0] == "archived"

        # Verify new entry exists and has corrects_id.
        new_entry = await store.get(data["new_entry_id"])
        assert new_entry is not None
        assert new_entry.corrects_id == original.id
        assert new_entry.content == "Corrected information"

    async def test_correct_inherits_fields(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        original = make_entry(
            content="Old info",
            author="alice",
            project="my-project",
            tags=["knowledge"],
        )
        await store.store(original)

        result = await _handle_correct(
            store=store,
            arguments={
                "wrong_entry_id": original.id,
                "content": "New info",
            },
            cfg=config,
        )
        data = parse_mcp_response(result)
        new_entry = await store.get(data["new_entry_id"])
        assert new_entry is not None
        assert new_entry.author == "alice"
        assert new_entry.project == "my-project"
        assert new_entry.tags == ["knowledge"]


class TestCorrectNonExistent:
    """Correcting a non-existent entry returns NOT_FOUND."""

    async def test_wrong_entry_not_found(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        result = await _handle_correct(
            store=store,
            arguments={
                "wrong_entry_id": "00000000-0000-0000-0000-000000000000",
                "content": "Correction for nothing",
            },
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert data.get("error") is True
        assert "NOT_FOUND" in data["code"]


class TestGetCorrections:
    """get_corrections returns all corrections for an entry."""

    async def test_get_corrections(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        original = make_entry(content="Original fact")
        await store.store(original)

        result = await _handle_correct(
            store=store,
            arguments={
                "wrong_entry_id": original.id,
                "content": "First correction",
            },
            cfg=config,
        )
        data = parse_mcp_response(result)
        new_id_1 = data["new_entry_id"]

        corrections = await store.get_corrections(original.id)
        assert len(corrections) == 1
        assert corrections[0].id == new_id_1

    async def test_no_corrections(self, store: DuckDBStore) -> None:
        entry = make_entry(content="No corrections")
        await store.store(entry)
        corrections = await store.get_corrections(entry.id)
        assert corrections == []


class TestCorrectionChain:
    """Chain of 3: original -> correction1 -> correction2."""

    async def test_chain_of_three(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        # Original entry
        original = make_entry(content="Wrong v1")
        await store.store(original)

        # First correction
        r1 = await _handle_correct(
            store=store,
            arguments={
                "wrong_entry_id": original.id,
                "content": "Better but still wrong v2",
            },
            cfg=config,
        )
        d1 = parse_mcp_response(r1)
        assert "error" not in d1
        correction1_id = d1["new_entry_id"]

        # Second correction (corrects the first correction)
        r2 = await _handle_correct(
            store=store,
            arguments={
                "wrong_entry_id": correction1_id,
                "content": "Final correct version v3",
            },
            cfg=config,
        )
        d2 = parse_mcp_response(r2)
        assert "error" not in d2
        correction2_id = d2["new_entry_id"]

        # Verify chain linkage — correction1 was archived by the second correction
        conn = store.connection
        row = conn.execute(
            "SELECT status, corrects_id FROM entries WHERE id = ?",
            [correction1_id],
        ).fetchone()
        assert row is not None
        assert row[0] == "archived"
        assert row[1] == original.id

        c2 = await store.get(correction2_id)
        assert c2 is not None
        assert c2.corrects_id == correction1_id
        assert c2.status is EntryStatus.ACTIVE

        # Original also archived
        row_orig = conn.execute("SELECT status FROM entries WHERE id = ?", [original.id]).fetchone()
        assert row_orig is not None
        assert row_orig[0] == "archived"


class TestEntryRoundtrip:
    """corrects_id survives to_dict/from_dict roundtrip."""

    def test_corrects_id_roundtrip(self) -> None:
        from distillery.models import Entry

        entry = make_entry(content="Correction", corrects_id="some-uuid")
        d = entry.to_dict()
        assert d["corrects_id"] == "some-uuid"
        restored = Entry.from_dict(d)
        assert restored.corrects_id == "some-uuid"

    def test_corrects_id_none_roundtrip(self) -> None:
        from distillery.models import Entry

        entry = make_entry(content="No correction")
        d = entry.to_dict()
        assert d["corrects_id"] is None
        restored = Entry.from_dict(d)
        assert restored.corrects_id is None
