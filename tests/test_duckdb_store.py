"""Comprehensive tests for DuckDBStore against a real in-memory DuckDB instance.

All tests use an in-memory database (``:memory:``) and a mock embedding
provider that returns deterministic vectors.  This keeps tests fast and
deterministic while exercising the real DuckDB query paths.
"""

from __future__ import annotations

import contextlib
import math
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from distillery.models import Entry, EntrySource, EntryStatus, EntryType
from distillery.store.duckdb import _FORCE_CHECKPOINT_AFTER_FAILURES, DuckDBStore
from distillery.store.protocol import SearchResult
from tests.conftest import make_entry

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestInitialization:
    async def test_initialize_is_idempotent(self, mock_embedding_provider) -> None:
        """Calling initialize() twice must not raise."""
        s = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        await s.initialize()
        await s.initialize()  # should be a no-op
        await s.close()

    async def test_initialize_survives_unsupported_chmod(
        self, mock_embedding_provider, tmp_path, monkeypatch
    ) -> None:
        """A filesystem that rejects chmod (e.g. GCS FUSE) must not abort startup."""

        def _refuse_chmod(*_args, **_kwargs) -> None:
            raise OSError(1, "Operation not permitted")

        monkeypatch.setattr("os.chmod", _refuse_chmod)

        db_path = tmp_path / "distillery.db"
        s = DuckDBStore(db_path=str(db_path), embedding_provider=mock_embedding_provider)
        await s.initialize()
        assert s.connection is not None
        await s.close()

    async def test_connection_raises_before_initialize(self, mock_embedding_provider) -> None:
        s = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        with pytest.raises(RuntimeError, match="initialize"):
            _ = s.connection

    async def test_connection_available_after_initialize(self, store: DuckDBStore) -> None:
        conn = store.connection
        assert conn is not None

    async def test_embedding_provider_accessible(self, store: DuckDBStore) -> None:
        assert store.embedding_provider is not None
        assert store.embedding_provider.dimensions == 4


# ---------------------------------------------------------------------------
# store()
# ---------------------------------------------------------------------------


class TestStore:
    async def test_store_returns_entry_id(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Hello world")
        returned_id = await store.store(entry)
        assert returned_id == entry.id

    async def test_store_id_is_string(self, store: DuckDBStore) -> None:
        entry = make_entry()
        returned_id = await store.store(entry)
        assert isinstance(returned_id, str)

    async def test_store_multiple_entries(self, store: DuckDBStore) -> None:
        e1 = make_entry(content="First entry")
        e2 = make_entry(content="Second entry")
        id1 = await store.store(e1)
        id2 = await store.store(e2)
        assert id1 != id2

    async def test_store_with_tags(self, store: DuckDBStore) -> None:
        entry = make_entry(tags=["alpha", "beta"])
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert set(fetched.tags) == {"alpha", "beta"}

    async def test_store_with_metadata(self, store: DuckDBStore) -> None:
        entry = make_entry(
            entry_type=EntryType.BOOKMARK,
            metadata={"url": "https://example.com", "summary": "An example"},
        )
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.metadata["url"] == "https://example.com"
        assert fetched.metadata["summary"] == "An example"

    async def test_store_with_project(self, store: DuckDBStore) -> None:
        entry = make_entry(project="distillery")
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.project == "distillery"

    async def test_store_preserves_author(self, store: DuckDBStore) -> None:
        entry = make_entry(author="alice")
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.author == "alice"


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


class TestGet:
    async def test_get_returns_entry(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Retrieve me")
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.content == "Retrieve me"

    async def test_get_missing_returns_none(self, store: DuckDBStore) -> None:
        result = await store.get("nonexistent-id")
        assert result is None

    async def test_get_preserves_entry_type(self, store: DuckDBStore) -> None:
        entry = make_entry(entry_type=EntryType.SESSION)
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.entry_type is EntryType.SESSION

    async def test_get_preserves_source(self, store: DuckDBStore) -> None:
        entry = make_entry(source=EntrySource.CLAUDE_CODE)
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.source is EntrySource.CLAUDE_CODE

    async def test_get_preserves_version(self, store: DuckDBStore) -> None:
        entry = make_entry()
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.version == 1

    async def test_get_roundtrip_entry_type_bookmark(self, store: DuckDBStore) -> None:
        entry = make_entry(entry_type=EntryType.BOOKMARK)
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.entry_type is EntryType.BOOKMARK

    async def test_get_returns_entry_with_correct_id(self, store: DuckDBStore) -> None:
        entry = make_entry()
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.id == entry.id


# ---------------------------------------------------------------------------
# update()
# ---------------------------------------------------------------------------


class TestUpdate:
    async def test_update_content(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Original")
        await store.store(entry)
        updated = await store.update(entry.id, {"content": "Updated"})
        assert updated.content == "Updated"

    async def test_update_increments_version(self, store: DuckDBStore) -> None:
        entry = make_entry()
        await store.store(entry)
        updated = await store.update(entry.id, {"content": "New content"})
        assert updated.version == 2

    async def test_update_refreshes_updated_at(self, store: DuckDBStore) -> None:
        """update() must set updated_at to a datetime (not None)."""
        entry = make_entry()
        await store.store(entry)
        updated = await store.update(entry.id, {"content": "Changed"})
        # updated_at must be a datetime object after the update.
        assert isinstance(updated.updated_at, datetime)

    async def test_update_tags(self, store: DuckDBStore) -> None:
        entry = make_entry(tags=["old"])
        await store.store(entry)
        updated = await store.update(entry.id, {"tags": ["new", "tags"]})
        assert set(updated.tags) == {"new", "tags"}

    async def test_update_status(self, store: DuckDBStore) -> None:
        entry = make_entry()
        await store.store(entry)
        updated = await store.update(entry.id, {"status": EntryStatus.PENDING_REVIEW})
        assert updated.status is EntryStatus.PENDING_REVIEW

    async def test_update_project(self, store: DuckDBStore) -> None:
        entry = make_entry()
        await store.store(entry)
        updated = await store.update(entry.id, {"project": "new-project"})
        assert updated.project == "new-project"

    async def test_update_metadata(self, store: DuckDBStore) -> None:
        entry = make_entry()
        await store.store(entry)
        updated = await store.update(entry.id, {"metadata": {"key": "value"}})
        assert updated.metadata["key"] == "value"

    async def test_update_rejects_id_field(self, store: DuckDBStore) -> None:
        entry = make_entry()
        await store.store(entry)
        with pytest.raises(ValueError, match="id"):
            await store.update(entry.id, {"id": "new-id"})

    async def test_update_rejects_created_at_field(self, store: DuckDBStore) -> None:
        entry = make_entry()
        await store.store(entry)
        with pytest.raises(ValueError, match="created_at"):
            await store.update(entry.id, {"created_at": datetime.now(tz=UTC)})

    async def test_update_rejects_source_field(self, store: DuckDBStore) -> None:
        entry = make_entry()
        await store.store(entry)
        with pytest.raises(ValueError, match="source"):
            await store.update(entry.id, {"source": EntrySource.IMPORT})

    async def test_update_raises_key_error_for_missing_entry(self, store: DuckDBStore) -> None:
        with pytest.raises(KeyError):
            await store.update("no-such-id", {"content": "x"})

    async def test_update_second_update_increments_version_to_three(
        self, store: DuckDBStore
    ) -> None:
        entry = make_entry()
        await store.store(entry)
        await store.update(entry.id, {"content": "Step 2"})
        updated2 = await store.update(entry.id, {"content": "Step 3"})
        assert updated2.version == 3

    async def test_update_persisted_to_get(self, store: DuckDBStore) -> None:
        """get() after update() should reflect new values."""
        entry = make_entry(content="Before")
        await store.store(entry)
        await store.update(entry.id, {"content": "After"})
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.content == "After"


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------


class TestDelete:
    async def test_delete_returns_true_for_existing_entry(self, store: DuckDBStore) -> None:
        entry = make_entry()
        await store.store(entry)
        result = await store.delete(entry.id)
        assert result is True

    async def test_delete_returns_false_for_missing_entry(self, store: DuckDBStore) -> None:
        result = await store.delete("nonexistent-id")
        assert result is False

    async def test_delete_soft_deletes_entry(self, store: DuckDBStore) -> None:
        """Deleted entry is still in DB but status = archived."""
        entry = make_entry()
        await store.store(entry)
        await store.delete(entry.id)
        # get() returns None for archived entries -- but we can check via list_entries
        # with explicit status filter.
        entries = await store.list_entries(filters={"status": "archived"}, limit=10, offset=0)
        ids = [e.id for e in entries]
        assert entry.id in ids

    async def test_delete_entry_not_returned_by_get(self, store: DuckDBStore) -> None:
        """get() must return None for archived (soft-deleted) entries.

        The protocol contract (store/protocol.py) requires get() to return None
        for entries whose status is ARCHIVED. Regression test for #468.
        """
        entry = make_entry()
        await store.store(entry)
        await store.delete(entry.id)
        fetched = await store.get(entry.id)
        assert fetched is None

    async def test_get_returns_none_after_archive_via_update(self, store: DuckDBStore) -> None:
        """get() must return None when an entry's status is set to ARCHIVED via update()."""
        entry = make_entry()
        await store.store(entry)
        await store.update(entry.id, {"status": EntryStatus.ARCHIVED})
        fetched = await store.get(entry.id)
        assert fetched is None

    async def test_delete_twice_still_returns_true(self, store: DuckDBStore) -> None:
        """Deleting an already-archived entry sets it to archived again -> True."""
        entry = make_entry()
        await store.store(entry)
        await store.delete(entry.id)
        result2 = await store.delete(entry.id)
        # Still finds the row (already archived), so returns True.
        assert result2 is True


# ---------------------------------------------------------------------------
# search() with filters
# ---------------------------------------------------------------------------


class TestSearch:
    async def test_search_returns_list(self, store: DuckDBStore) -> None:
        entry = make_entry(content="test content")
        await store.store(entry)
        results = await store.search("test content", filters=None, limit=10)
        assert isinstance(results, list)

    async def test_search_returns_search_result_objects(self, store: DuckDBStore) -> None:
        entry = make_entry(content="some text")
        await store.store(entry)
        results = await store.search("some text", filters=None, limit=10)
        assert len(results) >= 1
        assert isinstance(results[0], SearchResult)

    async def test_search_result_has_entry_and_score(self, store: DuckDBStore) -> None:
        entry = make_entry(content="hello distillery")
        await store.store(entry)
        results = await store.search("hello distillery", filters=None, limit=5)
        assert len(results) >= 1
        result = results[0]
        assert hasattr(result, "entry")
        assert hasattr(result, "score")
        assert isinstance(result.score, float)

    async def test_search_respects_limit(self, store: DuckDBStore) -> None:
        for i in range(5):
            await store.store(make_entry(content=f"entry {i}"))
        results = await store.search("entry", filters=None, limit=3)
        assert len(results) <= 3

    async def test_search_filter_by_entry_type(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="bookmark entry", entry_type=EntryType.BOOKMARK))
        await store.store(make_entry(content="session entry", entry_type=EntryType.SESSION))
        results = await store.search(
            "entry",
            filters={"entry_type": "bookmark"},
            limit=10,
        )
        for r in results:
            assert r.entry.entry_type is EntryType.BOOKMARK

    async def test_search_filter_by_entry_type_list(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="idea entry", entry_type=EntryType.IDEA))
        await store.store(make_entry(content="inbox entry", entry_type=EntryType.INBOX))
        await store.store(make_entry(content="session entry", entry_type=EntryType.SESSION))
        results = await store.search(
            "entry",
            filters={"entry_type": ["idea", "inbox"]},
            limit=10,
        )
        for r in results:
            assert r.entry.entry_type in (EntryType.IDEA, EntryType.INBOX)

    async def test_search_filter_by_author(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="alice entry", author="alice"))
        await store.store(make_entry(content="bob entry", author="bob"))
        results = await store.search("entry", filters={"author": "alice"}, limit=10)
        for r in results:
            assert r.entry.author == "alice"

    async def test_search_filter_by_project(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="proj entry", project="my-project"))
        await store.store(make_entry(content="other entry", project="other"))
        results = await store.search("entry", filters={"project": "my-project"}, limit=10)
        for r in results:
            assert r.entry.project == "my-project"

    async def test_search_filter_by_tags(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="tagged entry", tags=["important"]))
        await store.store(make_entry(content="plain entry", tags=[]))
        results = await store.search("entry", filters={"tags": ["important"]}, limit=10)
        for r in results:
            assert "important" in r.entry.tags

    async def test_search_filter_by_multiple_tags_is_intersection(
        self, store: DuckDBStore
    ) -> None:
        """Multi-tag search ANDs the tags: only entries with *both* match (#626)."""
        await store.store(make_entry(content="entry only a", tags=["tag-a"]))
        await store.store(make_entry(content="entry only b", tags=["tag-b"]))
        await store.store(make_entry(content="entry both", tags=["tag-a", "tag-b"]))
        results = await store.search("entry", filters={"tags": ["tag-a", "tag-b"]}, limit=10)
        # Per-tag counts are 2 (tag-a) and 2 (tag-b); AND must return <= min == 2,
        # and specifically only the single entry carrying both tags.
        assert len(results) == 1
        for r in results:
            assert "tag-a" in r.entry.tags
            assert "tag-b" in r.entry.tags

    async def test_search_filter_by_status(self, store: DuckDBStore) -> None:
        active_entry = make_entry(content="active entry", status=EntryStatus.ACTIVE)
        pending_entry = make_entry(content="pending entry", status=EntryStatus.PENDING_REVIEW)
        await store.store(active_entry)
        await store.store(pending_entry)
        results = await store.search("entry", filters={"status": "active"}, limit=10)
        for r in results:
            assert r.entry.status is EntryStatus.ACTIVE

    async def test_search_no_results_empty_list(self, store: DuckDBStore) -> None:
        """Filter that matches nothing returns []."""
        await store.store(make_entry(content="content", author="alice"))
        results = await store.search("content", filters={"author": "nobody"}, limit=10)
        assert results == []

    async def test_search_with_date_from_filter(self, store: DuckDBStore) -> None:
        entry = make_entry(content="dated content")
        await store.store(entry)
        # Use a date in the past so our entry is included.
        from datetime import timedelta

        past = datetime.now(tz=UTC) - timedelta(hours=1)
        results = await store.search(
            "dated content",
            filters={"date_from": past.isoformat()},
            limit=10,
        )
        ids = [r.entry.id for r in results]
        assert entry.id in ids


# ---------------------------------------------------------------------------
# find_similar() with threshold
# ---------------------------------------------------------------------------


class TestFindSimilar:
    async def test_find_similar_returns_list(self, store: DuckDBStore) -> None:
        entry = make_entry(content="unique content abc")
        await store.store(entry)
        results = await store.find_similar("unique content abc", threshold=0.0, limit=10)
        assert isinstance(results, list)

    async def test_find_similar_returns_search_result_objects(self, store: DuckDBStore) -> None:
        entry = make_entry(content="similar text xyz")
        await store.store(entry)
        results = await store.find_similar("similar text xyz", threshold=0.0, limit=10)
        if results:
            assert isinstance(results[0], SearchResult)

    async def test_find_similar_scores_meet_threshold(self, store: DuckDBStore) -> None:
        """Every returned score must be >= threshold."""
        entry = make_entry(content="test threshold content")
        await store.store(entry)
        threshold = 0.5
        results = await store.find_similar("test threshold content", threshold=threshold, limit=10)
        for r in results:
            assert r.score >= threshold

    async def test_find_similar_high_threshold_fewer_results(self, store: DuckDBStore) -> None:
        """A very high threshold (0.99) should return fewer results than 0.0."""
        for i in range(5):
            await store.store(make_entry(content=f"varied text content number {i}"))
        results_low = await store.find_similar("varied text", threshold=0.0, limit=10)
        results_high = await store.find_similar("varied text", threshold=0.99, limit=10)
        assert len(results_high) <= len(results_low)

    async def test_find_similar_respects_limit(self, store: DuckDBStore) -> None:
        for i in range(5):
            await store.store(make_entry(content=f"content sample {i}"))
        results = await store.find_similar("content sample", threshold=0.0, limit=2)
        assert len(results) <= 2

    async def test_find_similar_score_is_float(self, store: DuckDBStore) -> None:
        """Any returned SearchResult must have a float score."""
        entry = make_entry(content="some content to embed")
        await store.store(entry)
        # Threshold 0.0 means include everything with score >= 0.
        results = await store.find_similar("some content to embed", threshold=0.0, limit=5)
        for r in results:
            assert isinstance(r.score, float)

    async def test_find_similar_empty_store_returns_empty(self, store: DuckDBStore) -> None:
        results = await store.find_similar("anything", threshold=0.0, limit=10)
        assert results == []


# ---------------------------------------------------------------------------
# list_entries() with pagination
# ---------------------------------------------------------------------------


class TestListEntries:
    async def test_list_entries_returns_list(self, store: DuckDBStore) -> None:
        result = await store.list_entries(filters=None, limit=10, offset=0)
        assert isinstance(result, list)

    async def test_list_entries_empty_store(self, store: DuckDBStore) -> None:
        result = await store.list_entries(filters=None, limit=10, offset=0)
        assert result == []

    async def test_list_entries_returns_stored_entries(self, store: DuckDBStore) -> None:
        entry = make_entry(content="list me please")
        await store.store(entry)
        result = await store.list_entries(filters=None, limit=10, offset=0)
        ids = [e.id for e in result]
        assert entry.id in ids

    async def test_list_entries_respects_limit(self, store: DuckDBStore) -> None:
        for i in range(5):
            await store.store(make_entry(content=f"entry {i}"))
        result = await store.list_entries(filters=None, limit=3, offset=0)
        assert len(result) <= 3

    async def test_list_entries_pagination_offset(self, store: DuckDBStore) -> None:
        for i in range(5):
            await store.store(make_entry(content=f"paginate entry {i}"))
        page1 = await store.list_entries(filters=None, limit=3, offset=0)
        page2 = await store.list_entries(filters=None, limit=3, offset=3)
        ids1 = {e.id for e in page1}
        ids2 = {e.id for e in page2}
        assert ids1.isdisjoint(ids2)

    async def test_list_entries_filter_by_entry_type(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="bookmark one", entry_type=EntryType.BOOKMARK))
        await store.store(make_entry(content="idea one", entry_type=EntryType.IDEA))
        result = await store.list_entries(filters={"entry_type": "bookmark"}, limit=10, offset=0)
        for e in result:
            assert e.entry_type is EntryType.BOOKMARK

    async def test_list_entries_filter_by_author(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="alice content", author="alice"))
        await store.store(make_entry(content="bob content", author="bob"))
        result = await store.list_entries(filters={"author": "bob"}, limit=10, offset=0)
        for e in result:
            assert e.author == "bob"

    async def test_list_entries_filter_by_project(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="proj content", project="alpha"))
        await store.store(make_entry(content="other content", project="beta"))
        result = await store.list_entries(filters={"project": "alpha"}, limit=10, offset=0)
        for e in result:
            assert e.project == "alpha"

    async def test_list_entries_filter_by_tags(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="tagged", tags=["critical"]))
        await store.store(make_entry(content="plain"))
        result = await store.list_entries(filters={"tags": ["critical"]}, limit=10, offset=0)
        for e in result:
            assert "critical" in e.tags

    async def test_list_entries_filter_by_multiple_tags_is_intersection(
        self, store: DuckDBStore
    ) -> None:
        """Multi-tag list ANDs the tags: only entries with *both* match (#626)."""
        await store.store(make_entry(content="only a", tags=["tag-a"]))
        await store.store(make_entry(content="only a too", tags=["tag-a"]))
        await store.store(make_entry(content="only b", tags=["tag-b"]))
        await store.store(make_entry(content="both", tags=["tag-a", "tag-b"]))
        result = await store.list_entries(
            filters={"tags": ["tag-a", "tag-b"]}, limit=10, offset=0
        )
        # Per-tag counts: tag-a == 3, tag-b == 2; AND must return <= min == 2 and
        # in fact only the single entry carrying both tags (proves intersection,
        # not the union of 4 that the old list_has_any produced).
        assert len(result) == 1
        for e in result:
            assert "tag-a" in e.tags
            assert "tag-b" in e.tags

    async def test_list_entries_tags_filter_rejects_non_list(self, store: DuckDBStore) -> None:
        """A bare string tags filter must raise rather than iterate characters (#626)."""
        with pytest.raises(ValueError, match="tags filter must be a list"):
            await store.list_entries(filters={"tags": "tag-a"}, limit=10, offset=0)

    async def test_list_entries_filter_by_status(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="active", status=EntryStatus.ACTIVE))
        pending = make_entry(content="pending", status=EntryStatus.PENDING_REVIEW)
        await store.store(pending)
        result = await store.list_entries(filters={"status": "pending_review"}, limit=10, offset=0)
        for e in result:
            assert e.status is EntryStatus.PENDING_REVIEW

    async def test_list_entries_ordered_newest_first(self, store: DuckDBStore) -> None:
        """Results are ordered by created_at descending."""
        e1 = make_entry(content="first stored")
        e2 = make_entry(content="second stored")
        await store.store(e1)
        await store.store(e2)
        result = await store.list_entries(filters=None, limit=10, offset=0)
        assert len(result) >= 2
        # Timestamps should be non-increasing.
        for i in range(len(result) - 1):
            assert result[i].created_at >= result[i + 1].created_at

    async def test_list_entries_offset_beyond_total_returns_empty(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="only one"))
        result = await store.list_entries(filters=None, limit=10, offset=100)
        assert result == []

    async def test_list_entries_returns_entry_objects(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="an entry"))
        result = await store.list_entries(filters=None, limit=5, offset=0)
        for e in result:
            assert isinstance(e, Entry)


# ---------------------------------------------------------------------------
# accessed_at tracking
# ---------------------------------------------------------------------------


class TestAccessedAt:
    async def test_new_entry_accessed_at_is_none(self, store: DuckDBStore) -> None:
        """A freshly stored entry has accessed_at = None before any access."""
        entry = make_entry(content="brand new")
        await store.store(entry)
        # Directly query the DB to confirm accessed_at is NULL before get().
        row = store.connection.execute(
            "SELECT accessed_at FROM entries WHERE id = ?", [entry.id]
        ).fetchone()
        assert row is not None
        assert row[0] is None

    async def test_get_sets_accessed_at(self, store: DuckDBStore) -> None:
        """get() must set accessed_at to a non-None timestamp."""
        entry = make_entry(content="fetch me")
        await store.store(entry)
        fetched = await store.get(entry.id)
        assert fetched is not None
        # accessed_at should be set in the DB after get().
        row = store.connection.execute(
            "SELECT accessed_at FROM entries WHERE id = ?", [entry.id]
        ).fetchone()
        assert row is not None
        assert row[0] is not None
        assert isinstance(row[0], datetime)

    async def test_get_missing_entry_does_not_set_accessed_at(self, store: DuckDBStore) -> None:
        """get() on a non-existent ID returns None without error."""
        result = await store.get("no-such-id")
        assert result is None

    async def test_search_sets_accessed_at(self, store: DuckDBStore) -> None:
        """search() must update accessed_at for all returned entries."""
        entry = make_entry(content="searchable content")
        await store.store(entry)
        results = await store.search(query="searchable content", filters=None, limit=10)
        assert len(results) >= 1
        returned_ids = [r.entry.id for r in results]
        assert entry.id in returned_ids
        row = store.connection.execute(
            "SELECT accessed_at FROM entries WHERE id = ?", [entry.id]
        ).fetchone()
        assert row is not None
        assert row[0] is not None
        assert isinstance(row[0], datetime)

    async def test_update_sets_accessed_at(self, store: DuckDBStore) -> None:
        """update() must set accessed_at on the updated entry."""
        entry = make_entry(content="initial")
        await store.store(entry)
        updated = await store.update(entry.id, {"content": "modified"})
        assert updated.accessed_at is not None
        assert isinstance(updated.accessed_at, datetime)

    async def test_accessed_at_populated_in_returned_entry(self, store: DuckDBStore) -> None:
        """Entry returned by get() after access should have accessed_at populated."""
        entry = make_entry(content="check returned value")
        await store.store(entry)
        await store.get(entry.id)  # triggers accessed_at update
        # Second get() should return the entry with accessed_at set.
        fetched = await store.get(entry.id)
        assert fetched is not None
        assert fetched.accessed_at is not None
        assert isinstance(fetched.accessed_at, datetime)


class TestClose:
    """DuckDBStore.close() checkpoints the WAL and releases the connection."""

    async def test_close_checkpoints_wal(self, deterministic_embedding_provider: object) -> None:
        """After close(), tables created in-session are persisted to the DB file."""
        import tempfile
        from pathlib import Path

        import duckdb

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "test.db")
            store = DuckDBStore(
                db_path=db_path,
                embedding_provider=deterministic_embedding_provider,
            )
            await store.initialize()
            # feed_sources table should exist in the live connection.
            assert store.connection.execute("SELECT count(*) FROM feed_sources").fetchone() == (0,)
            await store.close()

            # Re-open read-only to verify the table was checkpointed to disk.
            conn = duckdb.connect(db_path, read_only=True)
            assert conn.execute("SELECT count(*) FROM feed_sources").fetchone() == (0,)
            conn.close()

    async def test_close_is_idempotent(self, store: DuckDBStore) -> None:
        """Calling close() twice does not raise."""
        await store.close()
        await store.close()  # should be a no-op


class TestFeedSourceLiveness:
    """DuckDBStore surfaces liveness metadata alongside feed sources."""

    async def test_list_includes_liveness_fields_defaults(self, store: DuckDBStore) -> None:
        await store.add_feed_source(
            url="https://example.com/rss",
            source_type="rss",
            poll_interval_minutes=30,
        )
        sources = await store.list_feed_sources()
        assert len(sources) == 1
        src = sources[0]
        assert src["last_polled_at"] is None
        assert src["last_item_count"] == 0
        assert src["last_error"] is None
        assert src["next_poll_at"] is None

    async def test_record_poll_status_updates_fields(self, store: DuckDBStore) -> None:
        await store.add_feed_source(
            url="https://example.com/rss",
            source_type="rss",
            poll_interval_minutes=60,
        )
        polled_at = datetime(2026, 4, 16, 12, 0, tzinfo=UTC)
        updated = await store.record_poll_status(
            "https://example.com/rss",
            polled_at=polled_at,
            item_count=5,
            error=None,
        )
        assert updated is True

        sources = await store.list_feed_sources()
        src = sources[0]
        assert src["last_polled_at"] is not None
        assert src["last_item_count"] == 5
        assert src["last_error"] is None
        assert src["next_poll_at"] is not None

    async def test_record_poll_status_surfaces_error(self, store: DuckDBStore) -> None:
        await store.add_feed_source(
            url="https://example.com/rss",
            source_type="rss",
        )
        polled_at = datetime(2026, 4, 16, 12, 0, tzinfo=UTC)
        long_error = "A" * 500
        await store.record_poll_status(
            "https://example.com/rss",
            polled_at=polled_at,
            item_count=0,
            error=long_error,
        )
        src = (await store.list_feed_sources())[0]
        assert src["last_error"] is not None
        # Truncated to 200 chars with ellipsis suffix.
        assert len(src["last_error"]) == 200
        assert src["last_error"].endswith("\u2026")
        assert src["last_item_count"] == 0

    async def test_record_poll_status_unknown_url_returns_false(self, store: DuckDBStore) -> None:
        result = await store.record_poll_status(
            "https://not-there.example/rss",
            polled_at=datetime.now(tz=UTC),
            item_count=0,
            error=None,
        )
        assert result is False

    async def test_record_poll_status_accepts_tz_aware_datetime(self, store: DuckDBStore) -> None:
        """A tz-aware UTC datetime must round-trip via ``list_feed_sources``.

        Regression test for issue #334: DuckDB's naive ``TIMESTAMP`` column
        previously silently rejected or coerced tz-aware values which made
        ``last_polled_at`` stay ``NULL`` despite successful poll writes.
        """
        await store.add_feed_source(
            url="https://example.com/rss",
            source_type="rss",
            poll_interval_minutes=60,
        )
        polled_at = datetime(2026, 4, 18, 9, 30, tzinfo=UTC)
        updated = await store.record_poll_status(
            "https://example.com/rss",
            polled_at=polled_at,
            item_count=12,
            error=None,
        )
        assert updated is True

        src = (await store.list_feed_sources())[0]
        assert src["last_polled_at"] is not None
        # The stored value reattaches UTC on read — must equal the tz-aware
        # input exactly (no drift, no None).
        assert src["last_polled_at"] == polled_at.isoformat()
        assert src["last_item_count"] == 12
        assert src["next_poll_at"] == "2026-04-18T10:30:00+00:00"


# ---------------------------------------------------------------------------
# WAL / FTS replay hardening (issue #349)
# ---------------------------------------------------------------------------


class TestWalFtsReplayHardening:
    """Regression coverage for the FTS WAL-replay failure described in #349.

    DuckDB's WAL replay has been observed to fail with
    ``Cannot drop entry "fts_main_entries"`` when a process is killed
    between an FTS index rebuild and the next checkpoint (e.g. Fly.io
    scale-to-zero with SIGKILL).  The mitigations exercised here are:

    1. ``_rebuild_fts_index`` issues a ``CHECKPOINT`` after each rebuild
       so FTS DDL never lingers in the WAL across process boundaries.
    2. The WAL recovery path preserves (rather than deletes) the WAL so
       operators can manually inspect uncommitted data.
    3. The rebuild PRAGMA uses ``overwrite=1`` — the FTS extension's own
       atomic drop/create — instead of emitting a separate DROP SCHEMA.
    """

    async def test_wal_checkpointed_after_store(
        self, deterministic_embedding_provider: object
    ) -> None:
        """After a write + FTS rebuild, the WAL file should be empty/absent.

        The fix forces a ``CHECKPOINT`` after every FTS rebuild so the
        rebuild's DDL is persisted to the main DB file rather than the WAL.
        If the process is hard-killed between writes, there is no FTS DDL
        in the WAL to mis-replay.
        """
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "wal_check.db")
            store = DuckDBStore(
                db_path=db_path,
                embedding_provider=deterministic_embedding_provider,
                hybrid_search=True,
            )
            await store.initialize()
            assert store._fts_available is True  # noqa: SLF001
            await store.store(make_entry(content="hello world from distillery"))

            wal_path = Path(db_path + ".wal")
            # DuckDB may or may not delete the sidecar after CHECKPOINT,
            # but it must not still contain unflushed FTS DDL.  An empty
            # file or absent file satisfies the invariant.
            if wal_path.exists():
                assert wal_path.stat().st_size == 0, (
                    f"WAL still has {wal_path.stat().st_size} bytes after "
                    "CHECKPOINT; FTS DDL may linger across process death."
                )
            await store.close()

    async def test_rebuild_fts_uses_overwrite_pragma(self, hybrid_store: DuckDBStore) -> None:
        """The rebuild should use the FTS extension's atomic overwrite path.

        Instead of emitting a manual ``DROP SCHEMA ... CASCADE`` +
        ``PRAGMA create_fts_index`` (which puts ordering-sensitive DDL into
        the WAL), the rebuild delegates the drop to the FTS extension via
        ``overwrite=1``.  Verified here by passing a fake connection to
        ``_rebuild_fts_index`` and capturing the SQL statements it emits.
        """

        class RecordingConn:
            def __init__(self) -> None:
                self.queries: list[str] = []

            def execute(self, query: str, *args: object, **kwargs: object) -> object:
                self.queries.append(query)
                return self

            def fetchone(self) -> tuple[object, ...] | None:
                return None

        spy_conn = RecordingConn()
        hybrid_store._rebuild_fts_index(spy_conn)  # type: ignore[arg-type]  # noqa: SLF001
        joined = "\n".join(spy_conn.queries)

        assert "DROP SCHEMA" not in joined, (
            "_rebuild_fts_index must not execute a manual DROP SCHEMA — #349."
        )
        assert "overwrite=1" in joined, (
            "PRAGMA create_fts_index must use overwrite=1 so the drop/create "
            "is handled atomically inside the FTS extension"
        )
        assert "CHECKPOINT" in joined, (
            "_rebuild_fts_index must CHECKPOINT to flush FTS DDL out of the WAL"
        )

    async def test_recovery_preserves_wal_as_backup(
        self, deterministic_embedding_provider: object
    ) -> None:
        """On FTS WAL replay failure, the WAL must be preserved (not deleted).

        Simulates the failure by constructing a fake WAL file, then calls
        the recovery helper directly with a synthetic FTS-related error.
        The recovery must rename the WAL to a ``.corrupt.<ts>`` sidecar so
        operators can inspect uncommitted data.
        """
        import tempfile
        from pathlib import Path

        import duckdb

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "recover.db")
            # Create a live DB file so _open_connection can succeed after
            # the WAL is moved aside.
            conn = duckdb.connect(db_path)
            conn.close()

            # Plant a fake WAL file (content does not matter — the recovery
            # helper only moves the file aside).
            wal_path = Path(db_path + ".wal")
            wal_path.write_bytes(b"pretend-wal-data")
            assert wal_path.exists()

            store = DuckDBStore(
                db_path=db_path,
                embedding_provider=deterministic_embedding_provider,
                hybrid_search=False,  # FTS not required for recovery path itself
            )
            fake_error = duckdb.Error(
                "Dependency Error: Failure while replaying WAL file: Cannot drop "
                'entry "fts_main_entries" because there are entries that depend on it.'
            )
            recovered = store._recover_from_wal_replay_failure(fake_error)  # noqa: SLF001
            try:
                # Original WAL should no longer exist.
                assert not wal_path.exists(), "WAL should have been moved aside"
                # Exactly one backup sibling should exist.
                backups = list(wal_path.parent.glob("*.wal.corrupt.*"))
                assert len(backups) == 1, f"expected 1 backup, got {backups}"
                # And the backup should contain the original WAL bytes.
                assert backups[0].read_bytes() == b"pretend-wal-data"
            finally:
                recovered.close()

    async def test_recovery_ignores_unrelated_errors(
        self, deterministic_embedding_provider: object
    ) -> None:
        """Non-WAL/FTS errors should re-raise, not silently move WAL aside."""
        import tempfile
        from pathlib import Path

        import duckdb

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "unrelated.db")
            store = DuckDBStore(
                db_path=db_path,
                embedding_provider=deterministic_embedding_provider,
            )
            unrelated = duckdb.Error("some totally unrelated failure")
            with pytest.raises(duckdb.Error, match="unrelated"):
                store._recover_from_wal_replay_failure(unrelated)  # noqa: SLF001

    async def test_reopen_after_many_writes_survives(
        self, deterministic_embedding_provider: object
    ) -> None:
        """Reopening a file-backed DB after many FTS rebuilds must succeed.

        Writes trigger ``_rebuild_fts_index`` on every call.  Before the
        fix this left a trail of FTS DDL in the WAL; a subsequent open
        could fail replay.  With the post-rebuild CHECKPOINT the WAL
        stays clean and reopen is a simple read of the main file.
        """
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "reopen.db")

            # Session 1 — write a handful of entries, close cleanly.
            s1 = DuckDBStore(
                db_path=db_path,
                embedding_provider=deterministic_embedding_provider,
                hybrid_search=True,
            )
            await s1.initialize()
            for i in range(5):
                await s1.store(make_entry(content=f"entry number {i} talks about duckdb"))
            await s1.close()

            # Session 2 — same file, must open without WAL replay issues
            # and find the previously-stored rows.
            s2 = DuckDBStore(
                db_path=db_path,
                embedding_provider=deterministic_embedding_provider,
                hybrid_search=True,
            )
            await s2.initialize()
            try:
                count = s2.connection.execute("SELECT COUNT(*) FROM entries").fetchone()
                assert count is not None
                assert count[0] == 5
                # And FTS must still function after reopen.
                results = s2._bm25_search("duckdb", limit=10)  # noqa: SLF001
                assert len(results) >= 1
            finally:
                await s2.close()

    def test_ungraceful_shutdown_survives_fts_replay(self) -> None:
        """SIGKILL mid-write must NOT leave the DB unopenable.

        This is the exact Fly.io scale-to-zero scenario from issue #349:
        a producer process writes entries and is killed hard before any
        close-time CHECKPOINT runs.  A subsequent open must succeed
        without the ``Cannot drop entry "fts_main_entries"`` replay
        error.

        Implemented via subprocess so the hard-kill (``os.kill(..., SIGKILL)``)
        does not affect the test runner.  Runs synchronously — subprocess
        APIs are blocking — but the subprocess itself drives asyncio.
        """
        import os
        import signal
        import subprocess
        import sys
        import tempfile
        import textwrap
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "sigkill.db")

            # Writer subprocess: init store, write one entry, then SIGKILL
            # itself before the normal close()/CHECKPOINT can run.
            writer = textwrap.dedent(
                f"""
                import asyncio, os, signal, sys
                from distillery.store.duckdb import DuckDBStore

                class DetEmb:
                    model_name = "test"
                    dimensions = 4
                    def embed(self, text):
                        return [0.1, 0.2, 0.3, 0.4]
                    def embed_batch(self, texts):
                        return [self.embed(t) for t in texts]

                async def main():
                    store = DuckDBStore(
                        db_path={db_path!r},
                        embedding_provider=DetEmb(),
                        hybrid_search=True,
                    )
                    await store.initialize()
                    from distillery.models import (
                        Entry, EntrySource, EntryStatus, EntryType,
                    )
                    import uuid
                    from datetime import datetime, UTC
                    entry = Entry(
                        id=str(uuid.uuid4()),
                        content="sigkill survivor entry",
                        entry_type=EntryType.REFERENCE,
                        source=EntrySource.CLAUDE_CODE,
                        author="test",
                        project=None,
                        tags=[],
                        status=EntryStatus.ACTIVE,
                        metadata={{}},
                        created_at=datetime.now(tz=UTC),
                        updated_at=datetime.now(tz=UTC),
                        version=1,
                    )
                    await store.store(entry)
                    # DO NOT close.  SIGKILL ourselves — Fly.io scale-to-zero
                    # hard-stop simulation.
                    os.kill(os.getpid(), signal.SIGKILL)

                asyncio.run(main())
                """
            )
            # Use PYTHONPATH so the subprocess uses the same source tree.
            env = os.environ.copy()
            src_root = str(Path(__file__).resolve().parent.parent / "src")
            env["PYTHONPATH"] = src_root + os.pathsep + env.get("PYTHONPATH", "")

            proc = subprocess.run(
                [sys.executable, "-c", writer],
                env=env,
                capture_output=True,
                timeout=60,
            )
            # The writer should have been terminated by SIGKILL (exit code -9).
            assert proc.returncode == -signal.SIGKILL or proc.returncode < 0, (
                f"writer did not SIGKILL itself (rc={proc.returncode}); "
                f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
            )

            # Reader subprocess: open the same file; must not raise.
            reader = textwrap.dedent(
                f"""
                import asyncio
                from distillery.store.duckdb import DuckDBStore

                class DetEmb:
                    model_name = "test"
                    dimensions = 4
                    def embed(self, text):
                        return [0.1, 0.2, 0.3, 0.4]
                    def embed_batch(self, texts):
                        return [self.embed(t) for t in texts]

                async def main():
                    store = DuckDBStore(
                        db_path={db_path!r},
                        embedding_provider=DetEmb(),
                        hybrid_search=True,
                    )
                    await store.initialize()
                    row = store.connection.execute(
                        "SELECT COUNT(*) FROM entries"
                    ).fetchone()
                    print("COUNT=" + str(row[0]))
                    await store.close()

                asyncio.run(main())
                """
            )
            r_proc = subprocess.run(
                [sys.executable, "-c", reader],
                env=env,
                capture_output=True,
                timeout=60,
                check=False,
            )
            assert r_proc.returncode == 0, (
                f"reader failed to open DB after SIGKILL: rc={r_proc.returncode} "
                f"stdout={r_proc.stdout!r} stderr={r_proc.stderr!r}"
            )
            # Count may be 0 (if write wasn't checkpointed) or 1 (if it was).
            # Either outcome is acceptable; what matters is that the DB is
            # openable at all — before the fix, it was not.
            assert b"COUNT=" in r_proc.stdout


# ---------------------------------------------------------------------------
# Corrupt / truncated WAL quarantine (issue #647)
# ---------------------------------------------------------------------------


class TestCorruptWalQuarantine:
    """An un-replayable WAL must never permanently brick startup (#647).

    Before the fix, ``_recover_from_wal_replay_failure`` only quarantined
    the WAL for the FTS-schema-DDL replay failure (#349); every other
    replay failure re-raised, so a truncated/corrupt WAL (e.g. a full
    volume truncating the WAL mid-write) crash-looped the process forever.
    The fix quarantines ANY un-replayable WAL — rename it aside, reopen the
    last-checkpointed main DB without it, and log a loud warning.
    """

    @staticmethod
    def _plant_corrupt_wal(db_path: str) -> Path:
        """Leave a real, un-replayable WAL on disk next to ``db_path``.

        Writes uncheckpointed rows so the WAL has genuine content, abandons
        the connection (with checkpoint-on-shutdown disabled) so the WAL
        survives, then overwrites a span in the middle with garbage to
        corrupt a record's checksum.  Reopening DuckDB then fails replay
        with a ``Failure while replaying WAL file`` error that is NOT the
        FTS-DDL signature — exactly the production #647 case.
        """
        import gc
        import uuid

        conn = duckdb.connect(db_path)
        conn.execute("PRAGMA disable_checkpoint_on_shutdown")
        # Insert directly into the existing ``entries`` table so the WAL
        # carries real, replayable records.
        for _ in range(500):
            conn.execute(
                "INSERT INTO entries (id, content, embedding, entry_type, "
                "source, author, project, tags, status, metadata, "
                "created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    str(uuid.uuid4()),
                    "x" * 1000,
                    [0.1, 0.2, 0.3, 0.4],
                    "reference",
                    "claude_code",
                    "wal-bloat",
                    None,
                    [],
                    "active",
                    "{}",
                    datetime.now(tz=UTC),
                    datetime.now(tz=UTC),
                    1,
                ],
            )
        # Abandon the connection without an explicit checkpoint so the WAL
        # is left on disk (close()/GC would otherwise flush it).
        del conn
        gc.collect()

        wal_path = Path(db_path + ".wal")
        size = wal_path.stat().st_size
        assert size > 0, "expected a non-empty WAL to corrupt"
        with open(wal_path, "r+b") as fh:
            fh.seek(size // 3)
            fh.write(b"\xff\xff\xff\xff" * 256)
        return wal_path

    async def test_corrupt_wal_quarantined_and_boots(
        self,
        deterministic_embedding_provider: object,
        tmp_path,
        caplog,
    ) -> None:
        """A corrupt WAL must boot on the last checkpoint, not crash-loop.

        Acceptance for #647: create a store + checkpointed entry (so a main
        DB exists), corrupt the ``.wal`` on disk, then reopen.  The store
        must boot on the last-checkpointed main DB, the WAL must be moved
        aside to a ``*.wal.corrupt.*`` sidecar (and the original ``.wal``
        gone), a WARNING must be logged, and NO exception may be raised.
        """
        import uuid as _uuid

        db_path = str(tmp_path / "distillery.db")

        # 1. Create a store and write a checkpointed entry — main DB exists.
        s1 = DuckDBStore(
            db_path=db_path,
            embedding_provider=deterministic_embedding_provider,
        )
        await s1.initialize()
        keep_id = str(_uuid.uuid4())
        await s1.store(make_entry(id=keep_id, content="this entry is checkpointed"))
        await s1.close()

        # 2. Corrupt/truncate the WAL on disk.
        wal_path = self._plant_corrupt_wal(db_path)
        assert wal_path.exists()

        # 3. Reopen — must boot without raising and quarantine the WAL.
        s2 = DuckDBStore(
            db_path=db_path,
            embedding_provider=deterministic_embedding_provider,
        )
        with caplog.at_level("WARNING"):
            await s2.initialize()
        try:
            # Booted on the last-checkpointed main DB: the one checkpointed
            # entry is present; the 500 un-checkpointed WAL rows are gone.
            count = s2.connection.execute("SELECT COUNT(*) FROM entries").fetchone()
            assert count is not None and count[0] == 1
            kept = await s2.get(keep_id)
            assert kept is not None
        finally:
            await s2.close()

        # The original WAL was moved aside, not left in place.
        assert not wal_path.exists(), "corrupt WAL should have been quarantined"
        backups = list(tmp_path.glob("*.wal.corrupt.*"))
        assert len(backups) == 1, f"expected one quarantine sidecar, got {backups}"

        # A loud WARNING names the dropped path and the data-loss risk.
        warnings = [
            r.getMessage()
            for r in caplog.records
            if r.levelname == "WARNING" and "un-replayable" in r.getMessage()
        ]
        assert warnings, "expected a WARNING about the un-replayable WAL"
        assert str(backups[0]) in warnings[0]
        assert "LOST" in warnings[0]

    async def test_fts_ddl_recovery_path_untouched(
        self,
        deterministic_embedding_provider: object,
        tmp_path,
        caplog,
    ) -> None:
        """The FTS-DDL recovery branch (#349) must not regress.

        Drives the recovery helper directly with the exact FTS replay
        signature and asserts it still quarantines the WAL and emits its
        tailored "(FTS-related)" warning rather than the generic message.
        """
        db_path = str(tmp_path / "fts.db")
        # Create a live DB file so reopening after quarantine succeeds.
        conn = duckdb.connect(db_path)
        conn.close()

        wal_path = Path(db_path + ".wal")
        wal_path.write_bytes(b"pretend-fts-wal")

        store = DuckDBStore(
            db_path=db_path,
            embedding_provider=deterministic_embedding_provider,
            hybrid_search=False,
        )
        fts_error = duckdb.Error(
            "Dependency Error: Failure while replaying WAL file: Cannot drop "
            'entry "fts_main_entries" because there are entries that depend on it.'
        )
        with caplog.at_level("WARNING"):
            recovered = store._recover_from_wal_replay_failure(fts_error)  # noqa: SLF001
        try:
            assert not wal_path.exists()
            backups = list(tmp_path.glob("*.wal.corrupt.*"))
            assert len(backups) == 1
            assert backups[0].read_bytes() == b"pretend-fts-wal"
            messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
            assert any("FTS-related" in m for m in messages), (
                "FTS-DDL recovery must keep its tailored warning (#349)"
            )
        finally:
            recovered.close()

    async def test_reopen_failure_surfaces_when_wal_restore_also_fails(
        self,
        deterministic_embedding_provider: object,
        tmp_path,
        monkeypatch,
        caplog,
    ) -> None:
        """If reopen fails AND the WAL restore fails, surface — never swallow.

        Normal reopen-failure behaviour restores the quarantined WAL and
        re-raises the original replay error so the real failure surfaces.
        But if that restore ``rename`` ALSO fails, suppressing the OSError
        would leave the WAL missing — a later startup could then proceed
        WITHOUT the unreplayed bytes (silent data loss).  This drives both
        failures and asserts the original error surfaces (chaining the
        restore error) and the quarantine sidecar is left in place for
        manual recovery.
        """
        db_path = str(tmp_path / "restore_fail.db")
        conn = duckdb.connect(db_path)
        conn.close()

        wal_path = Path(db_path + ".wal")
        wal_path.write_bytes(b"unreplayed-bytes")

        store = DuckDBStore(
            db_path=db_path,
            embedding_provider=deterministic_embedding_provider,
            hybrid_search=False,
        )

        # Force reopen-after-quarantine to fail so we enter the restore branch.
        def _fail_reopen() -> object:
            raise duckdb.Error("reopen still fails")

        monkeypatch.setattr(store, "_open_connection", _fail_reopen)

        # Let the quarantine rename (wal -> *.corrupt.*) succeed via the real
        # implementation, but make the restore rename (*.corrupt.* -> wal) fail.
        real_rename = Path.rename

        def _rename(self: Path, target):  # type: ignore[no-untyped-def]
            if self.name.endswith(".wal"):
                return real_rename(self, target)
            raise OSError("restore rename refused")

        monkeypatch.setattr(Path, "rename", _rename)

        replay_error = duckdb.Error(
            "Failure while replaying WAL file: serialization error"
        )
        with caplog.at_level("ERROR"):  # noqa: SIM117
            with pytest.raises(duckdb.Error, match="replaying WAL"):
                store._recover_from_wal_replay_failure(replay_error)  # noqa: SLF001

        # The quarantine sidecar must remain — it now holds the only copy of
        # the unreplayed bytes — and the original WAL must NOT be back.
        backups = list(tmp_path.glob("*.wal.corrupt.*"))
        assert len(backups) == 1, f"quarantine sidecar must remain, got {backups}"
        assert backups[0].read_bytes() == b"unreplayed-bytes"
        assert not wal_path.exists(), "WAL must not be silently restored"

        # A loud ERROR points the operator at the surviving sidecar.
        errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert any("WAL restore FAILED" in m for m in errors), (
            "a restore failure must log a loud ERROR, not be swallowed"
        )
        assert any(str(backups[0]) in m for m in errors)


# ---------------------------------------------------------------------------
# Hybrid search (BM25 + vector RRF fusion with recency decay)
# ---------------------------------------------------------------------------


@pytest.fixture
async def hybrid_store(mock_embedding_provider):
    """Initialised in-memory DuckDBStore with hybrid search enabled."""
    s = DuckDBStore(
        db_path=":memory:",
        embedding_provider=mock_embedding_provider,
        hybrid_search=True,
        rrf_k=60,
        recency_window_days=90,
        recency_min_weight=0.5,
    )
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
async def vector_only_store(mock_embedding_provider):
    """Initialised in-memory DuckDBStore with hybrid search disabled."""
    s = DuckDBStore(
        db_path=":memory:",
        embedding_provider=mock_embedding_provider,
        hybrid_search=False,
    )
    await s.initialize()
    yield s
    await s.close()


class TestHybridSearchInit:
    """Verify hybrid / vector-only initialization flags."""

    async def test_hybrid_search_sets_fts_available(self, hybrid_store: DuckDBStore) -> None:
        """When hybrid_search=True the FTS extension should be loaded."""
        assert hybrid_store._fts_available is True  # noqa: SLF001

    async def test_vector_only_fts_not_loaded(self, vector_only_store: DuckDBStore) -> None:
        """When hybrid_search=False the FTS extension should not be loaded."""
        assert vector_only_store._fts_available is False  # noqa: SLF001

    async def test_hybrid_search_flag_persisted(self, hybrid_store: DuckDBStore) -> None:
        """The _hybrid_search flag matches constructor argument."""
        assert hybrid_store._hybrid_search is True  # noqa: SLF001

    async def test_rrf_k_persisted(self, hybrid_store: DuckDBStore) -> None:
        assert hybrid_store._rrf_k == 60  # noqa: SLF001

    async def test_recency_window_persisted(self, hybrid_store: DuckDBStore) -> None:
        assert hybrid_store._recency_window_days == 90  # noqa: SLF001

    async def test_recency_min_weight_persisted(self, hybrid_store: DuckDBStore) -> None:
        assert hybrid_store._recency_min_weight == 0.5  # noqa: SLF001


class TestBM25Search:
    """Tests for the private _bm25_search method."""

    async def test_bm25_returns_empty_when_fts_unavailable(
        self, vector_only_store: DuckDBStore
    ) -> None:
        """BM25 search returns [] when FTS is not loaded."""
        result = vector_only_store._bm25_search("anything", limit=10)  # noqa: SLF001
        assert result == []

    async def test_bm25_returns_matching_entries(self, hybrid_store: DuckDBStore) -> None:
        """BM25 search returns ranked results for matching content."""
        await hybrid_store.store(make_entry(content="The quick brown fox jumps over the lazy dog"))
        await hybrid_store.store(make_entry(content="A slow red cat sleeps under a busy table"))
        results = hybrid_store._bm25_search("quick fox", limit=10)  # noqa: SLF001
        assert len(results) >= 1
        # First result should be rank 1.
        assert results[0][1] == 1

    async def test_bm25_respects_limit(self, hybrid_store: DuckDBStore) -> None:
        """BM25 should return at most `limit` results."""
        for i in range(5):
            await hybrid_store.store(
                make_entry(content=f"Document number {i} about machine learning algorithms")
            )
        results = hybrid_store._bm25_search("machine learning", limit=2)  # noqa: SLF001
        assert len(results) <= 2

    async def test_bm25_returns_empty_for_no_match(self, hybrid_store: DuckDBStore) -> None:
        """BM25 returns [] when no content matches the query."""
        await hybrid_store.store(make_entry(content="The quick brown fox jumps over the lazy dog"))
        results = hybrid_store._bm25_search("xylophone", limit=10)  # noqa: SLF001
        assert results == []


class TestHybridSearch:
    """End-to-end tests for hybrid search (BM25 + vector RRF)."""

    async def test_hybrid_search_returns_results(self, hybrid_store: DuckDBStore) -> None:
        """Hybrid search returns non-empty results for matching content."""
        await hybrid_store.store(
            make_entry(content="Python programming language best practices guide")
        )
        results = await hybrid_store.search("Python programming", filters=None, limit=10)
        assert len(results) >= 1
        assert isinstance(results[0], SearchResult)

    async def test_hybrid_scores_normalised_zero_to_one(self, hybrid_store: DuckDBStore) -> None:
        """All hybrid search scores should be in [0, 1]."""
        await hybrid_store.store(
            make_entry(content="Database query optimisation techniques for performance")
        )
        await hybrid_store.store(make_entry(content="Web application security testing methodology"))
        results = await hybrid_store.search("database optimisation", filters=None, limit=10)
        for r in results:
            assert 0.0 <= r.score <= 1.0

    async def test_hybrid_search_top_score_reflects_cosine(self, hybrid_store: DuckDBStore) -> None:
        """The top result's score should reflect raw cosine similarity in [0, 1].

        After issue #370 the displayed score is no longer min-max rescaled to
        1.0 within the candidate set; it is the raw cosine similarity (mapped
        to [0, 1]) so values remain comparable across metadata filters.
        """
        await hybrid_store.store(
            make_entry(content="Artificial intelligence and machine learning overview")
        )
        results = await hybrid_store.search(
            "artificial intelligence machine learning", filters=None, limit=10
        )
        assert len(results) >= 1
        assert 0.0 <= results[0].score <= 1.0

    async def test_hybrid_search_respects_limit(self, hybrid_store: DuckDBStore) -> None:
        """Hybrid search should respect the limit parameter."""
        for i in range(10):
            await hybrid_store.store(
                make_entry(content=f"Document {i} about software engineering practices")
            )
        results = await hybrid_store.search("software engineering", filters=None, limit=3)
        assert len(results) <= 3

    async def test_hybrid_search_applies_filters(self, hybrid_store: DuckDBStore) -> None:
        """Hybrid search should respect metadata filters."""
        await hybrid_store.store(
            make_entry(
                content="Python web framework comparison guide",
                author="alice",
            )
        )
        await hybrid_store.store(
            make_entry(
                content="Python data science libraries overview",
                author="bob",
            )
        )
        results = await hybrid_store.search("Python", filters={"author": "alice"}, limit=10)
        for r in results:
            assert r.entry.author == "alice"

    async def test_hybrid_search_empty_for_no_match(self, hybrid_store: DuckDBStore) -> None:
        """Hybrid search returns [] when filters exclude everything."""
        await hybrid_store.store(make_entry(content="content", author="alice"))
        results = await hybrid_store.search("content", filters={"author": "nobody"}, limit=10)
        assert results == []


class TestVectorOnlySearch:
    """Tests for vector-only fallback when hybrid is disabled."""

    async def test_vector_only_returns_results(self, vector_only_store: DuckDBStore) -> None:
        """Vector-only search still returns results."""
        await vector_only_store.store(make_entry(content="test content for search"))
        results = await vector_only_store.search("test content", filters=None, limit=10)
        assert len(results) >= 1

    async def test_vector_only_scores_normalised(self, vector_only_store: DuckDBStore) -> None:
        """Vector-only search scores should be in [0, 1]."""
        await vector_only_store.store(make_entry(content="normalisation test"))
        results = await vector_only_store.search("normalisation", filters=None, limit=10)
        for r in results:
            assert 0.0 <= r.score <= 1.0

    async def test_vector_only_applies_filters(self, vector_only_store: DuckDBStore) -> None:
        """Vector-only search should respect metadata filters."""
        await vector_only_store.store(make_entry(content="alpha entry", author="alice"))
        await vector_only_store.store(make_entry(content="beta entry", author="bob"))
        results = await vector_only_store.search("entry", filters={"author": "alice"}, limit=10)
        for r in results:
            assert r.entry.author == "alice"


class TestProjectFilterDoesNotRescaleScore:
    """Regression tests for issue #370.

    When a metadata filter (e.g. ``project``) shrinks the candidate set, the
    returned ``score`` must remain raw cosine similarity — not rescaled to
    1.0 for the per-scope top hit.  Otherwise callers that threshold on
    relevance accept irrelevant results inside a project filter.
    """

    @pytest.fixture
    async def projects_store(self, deterministic_embedding_provider):  # type: ignore[no-untyped-def]
        """Hybrid-mode store with two disjoint projects seeded with controlled
        embeddings.  ``alpha`` and projA entries share a near-identical vector;
        projB entries point in an orthogonal direction so cosine similarity to
        ``alpha`` is roughly 0 (mapped to ~0.5 in [0, 1]).
        """
        provider = deterministic_embedding_provider
        # Two near-orthogonal directions in 4D.
        provider.register("alpha", [1.0, 0.0, 0.0, 0.0])
        provider.register("projA entry 1: alpha", [1.0, 0.0, 0.0, 0.0])
        provider.register("projA entry 2: beta", [0.95, 0.05, 0.0, 0.0])
        provider.register("projA entry 3: gamma", [0.9, 0.1, 0.0, 0.0])
        provider.register("projB entry 1: delta", [0.0, 1.0, 0.0, 0.0])
        provider.register("projB entry 2: epsilon", [0.0, 0.95, 0.05, 0.0])
        provider.register("projB entry 3: zeta", [0.0, 0.9, 0.1, 0.0])

        s = DuckDBStore(
            db_path=":memory:",
            embedding_provider=provider,
            hybrid_search=True,
        )
        await s.initialize()
        for content, project in [
            ("projA entry 1: alpha", "projA"),
            ("projA entry 2: beta", "projA"),
            ("projA entry 3: gamma", "projA"),
            ("projB entry 1: delta", "projB"),
            ("projB entry 2: epsilon", "projB"),
            ("projB entry 3: zeta", "projB"),
        ]:
            await s.store(make_entry(content=content, project=project))
        yield s
        await s.close()

    async def test_project_filtered_top_score_is_not_rescaled(
        self, projects_store: DuckDBStore
    ) -> None:
        """Top hit inside a project that is unrelated to the query must not
        be rescaled to 1.0.  ``projB`` entries are orthogonal to ``alpha``,
        so cosine similarity is ~0 and the displayed score must reflect that
        (well below 0.6, the dedup ``link`` threshold).
        """
        results = await projects_store.search("alpha", filters={"project": "projB"}, limit=10)
        assert len(results) >= 1
        # Issue #370: top score must NOT be rescaled to 1.0 just because it
        # is the in-scope best.  The actual cosine similarity is ~0, mapped
        # to ~0.5 in [0, 1] by the (cos+1)/2 transform.
        assert results[0].score < 0.6
        # All scores stay in [0, 1].
        for r in results:
            assert 0.0 <= r.score <= 1.0

    async def test_project_filtered_score_matches_unfiltered(
        self, projects_store: DuckDBStore
    ) -> None:
        """For an entry that is in the unfiltered top-K, its score should be
        identical whether or not a project filter narrows the candidate set.
        """
        unfiltered = await projects_store.search("alpha", filters=None, limit=20)
        filtered = await projects_store.search("alpha", filters={"project": "projB"}, limit=10)
        # Build a {id: score} map from the unfiltered result for comparison.
        unfiltered_scores = {r.entry.id: r.score for r in unfiltered}
        for r in filtered:
            assert r.entry.id in unfiltered_scores, (
                "filtered result should also appear in the unfiltered top-K"
            )
            assert r.score == pytest.approx(unfiltered_scores[r.entry.id], abs=1e-6)


class TestRecencyWeight:
    """Tests for _recency_weight calculation."""

    async def test_recent_entry_weight_is_one(self, hybrid_store: DuckDBStore) -> None:
        """An entry created now should have recency weight 1.0."""
        now = datetime.now(tz=UTC)
        weight = hybrid_store._recency_weight(now)  # noqa: SLF001
        assert weight == 1.0

    async def test_old_entry_weight_at_minimum(self, hybrid_store: DuckDBStore) -> None:
        """A very old entry should have weight at recency_min_weight."""
        from datetime import timedelta

        old = datetime.now(tz=UTC) - timedelta(days=365 * 10)
        weight = hybrid_store._recency_weight(old)  # noqa: SLF001
        assert weight == pytest.approx(0.5)

    async def test_entry_within_window_weight_is_one(self, hybrid_store: DuckDBStore) -> None:
        """An entry created within recency_window_days gets weight 1.0."""
        from datetime import timedelta

        within = datetime.now(tz=UTC) - timedelta(days=45)
        weight = hybrid_store._recency_weight(within)  # noqa: SLF001
        assert weight == 1.0

    async def test_entry_just_outside_window_decays(self, hybrid_store: DuckDBStore) -> None:
        """An entry just past the window should have weight < 1.0 but > min."""
        from datetime import timedelta

        just_past = datetime.now(tz=UTC) - timedelta(days=100)
        weight = hybrid_store._recency_weight(just_past)  # noqa: SLF001
        assert 0.5 < weight < 1.0

    async def test_naive_datetime_handled(self, hybrid_store: DuckDBStore) -> None:
        """Timezone-naive datetimes (from DuckDB) should not raise."""
        naive = datetime(2026, 1, 1)  # noqa: DTZ001
        weight = hybrid_store._recency_weight(naive)  # noqa: SLF001
        assert 0.0 < weight <= 1.0


class TestFTSRebuildOnMutation:
    """Verify that FTS index is rebuilt on content-changing mutations."""

    async def test_new_entry_searchable_via_bm25(self, hybrid_store: DuckDBStore) -> None:
        """After storing an entry, it should be findable via BM25."""
        await hybrid_store.store(
            make_entry(content="Kubernetes container orchestration platform overview")
        )
        results = hybrid_store._bm25_search("kubernetes container", limit=10)  # noqa: SLF001
        assert len(results) >= 1

    async def test_updated_content_searchable_via_bm25(self, hybrid_store: DuckDBStore) -> None:
        """After updating content, the new text should be BM25-searchable."""
        entry = make_entry(content="Original placeholder text here")
        await hybrid_store.store(entry)
        await hybrid_store.update(
            entry.id, {"content": "Terraform infrastructure provisioning automation"}
        )
        results = hybrid_store._bm25_search("terraform infrastructure", limit=10)  # noqa: SLF001
        assert len(results) >= 1
        # The updated entry should be in the results.
        result_ids = [eid for eid, _rank in results]
        assert entry.id in result_ids


class TestConnectionLockSerialization:
    """Issue #416: ``_run_sync`` must serialize concurrent connection access.

    DuckDB's ``DuckDBPyConnection`` is not thread-safe.  Without a lock,
    parallel ``asyncio.gather`` callers (e.g. ``FeedPoller`` polling 60+
    sources) end up touching the shared connection from multiple
    ``asyncio.to_thread`` workers concurrently, which intermittently
    corrupts the glibc heap and wedges the process.
    """

    async def test_run_sync_holds_lock_for_duration(self, store: DuckDBStore) -> None:
        """A second ``_run_sync`` cannot enter while the first is running.

        Forces real contention by blocking inside the first ``_run_sync``'s
        worker thread on a ``threading.Event`` until after the second
        ``_run_sync`` call has been queued.  Without the lock, the second
        call's ``asyncio.to_thread`` would race the first worker thread
        and ``second-enter`` could land before ``first-mid``.  With the
        lock, the second call must wait for the first to return.
        """
        import asyncio
        import threading

        order: list[str] = []
        thread_inside = threading.Event()
        thread_release = threading.Event()

        def _slow() -> str:
            order.append("first-enter")
            # Signal the test that the worker holds ``_conn_lock``.
            thread_inside.set()
            # Block the worker thread until the test releases it, after
            # the second ``_run_sync`` has been queued behind the lock.
            thread_release.wait(timeout=5)
            order.append("first-mid")
            return "first"

        async def _first() -> None:
            await store._run_sync(_slow)  # noqa: SLF001
            order.append("first-exit")

        async def _second() -> None:
            # Wait until the worker is inside ``_slow`` (lock held) before
            # attempting the second call so contention is guaranteed.
            await asyncio.to_thread(thread_inside.wait, 5)
            order.append("second-attempt")
            # Without the lock, ``_run_sync`` would race ``_slow``.
            # With the lock, this awaits until ``_slow`` returns.
            await store._run_sync(  # noqa: SLF001
                lambda: order.append("second-enter") or "second"
            )
            order.append("second-exit")

        async def _release_after_second_queued() -> None:
            await asyncio.to_thread(thread_inside.wait, 5)
            # Yield long enough for ``_second``'s ``_run_sync`` to queue
            # behind ``_conn_lock`` before releasing the worker.
            await asyncio.sleep(0.1)
            thread_release.set()

        await asyncio.gather(_first(), _second(), _release_after_second_queued())
        # The lock guarantees ``second-enter`` cannot land before
        # ``first-mid`` (which is reached only after the worker holding
        # the lock unblocks).
        assert order.index("second-enter") > order.index("first-mid"), (
            f"second entered while first was running: {order!r}"
        )
        assert order.index("first-mid") > order.index("first-enter")

    async def test_run_sync_releases_lock_on_exception(self, store: DuckDBStore) -> None:
        """A raise inside ``_run_sync`` must not deadlock subsequent callers."""

        def _boom() -> None:
            raise RuntimeError("simulated failure")

        with pytest.raises(RuntimeError, match="simulated failure"):
            await store._run_sync(_boom)  # noqa: SLF001

        # If the lock leaked, this call would hang forever.  pytest's
        # default per-test timeout is sufficient to catch a deadlock,
        # but the assertion makes the intent explicit.
        result = await store._run_sync(lambda: "ok")  # noqa: SLF001
        assert result == "ok"

    async def test_lock_lazy_initialized_on_first_use(self, mock_embedding_provider) -> None:
        """``_conn_lock`` is created on first ``_run_sync`` call, not in ``__init__``."""
        s = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        assert s._conn_lock is None  # noqa: SLF001
        await s.initialize()
        # ``initialize`` does not go through ``_run_sync`` so lock is still None.
        assert s._conn_lock is None  # noqa: SLF001
        await s.list_entries(filters=None, limit=1, offset=0)
        assert s._conn_lock is not None  # noqa: SLF001
        await s.close()


class _SlowEmbeddingProvider:
    """Embedding provider whose ``embed``/``embed_batch`` sleep ``delay`` seconds.

    Models a slow embedding HTTP backend (e.g. Jina under load) so tests can
    assert that ``distillery_status`` health probes stay responsive and that
    concurrent stores overlap their embedding round-trips (issue #558).  The
    sleep happens in the worker thread ``asyncio.to_thread`` runs ``embed`` on,
    so multiple stores can sleep concurrently.
    """

    _DIMS = 4

    def __init__(self, delay: float) -> None:
        self._delay = delay

    def _vector_for(self, text: str) -> list[float]:
        import time

        time.sleep(self._delay)
        h = hash(text) & 0xFFFFFFFF
        parts = [(h >> (8 * i)) & 0xFF for i in range(self._DIMS)]
        floats = [float(p) + 1.0 for p in parts]
        magnitude = math.sqrt(sum(x * x for x in floats))
        return [x / magnitude for x in floats]

    def embed(self, text: str) -> list[float]:
        return self._vector_for(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # One sleep per text so a batch of N costs N*delay, mirroring a real
        # provider's per-item cost.
        return [self._vector_for(t) for t in texts]

    @property
    def dimensions(self) -> int:
        return self._DIMS

    @property
    def model_name(self) -> str:
        return "slow-stub-4d"


class TestStatusStaysResponsiveUnderWriteContention:
    """Issue #558: health probes must not queue behind embedding-bound writes.

    ``distillery_status`` calls ``count_entries`` / ``list_feed_sources`` /
    ``probe_readiness``, which now run against an independent read handle that
    bypasses ``_conn_lock``.  Stage 2 also moves embedding off the critical
    section so parallel stores overlap their network round-trips.
    """

    async def test_status_probes_respond_while_writes_are_in_flight(self) -> None:
        """count/feeds/probe answer in <1s while 10 slow writes hold the pool.

        Acceptance: ``distillery_status`` returns within 1s while 10 concurrent
        embedding-bound writes (500ms/embed) are in flight.
        """
        import asyncio

        provider = _SlowEmbeddingProvider(delay=0.5)
        store = DuckDBStore(db_path=":memory:", embedding_provider=provider)
        await store.initialize()
        try:
            # Fire 10 embedding-bound writes; each holds a worker for ~500ms.
            writers = [
                asyncio.create_task(store.store(make_entry(content=f"slow write {i}")))
                for i in range(10)
            ]
            # Give the writers a moment to start embedding off-thread.
            await asyncio.sleep(0.05)

            async def _status() -> None:
                # The three operations ``distillery_status`` performs.
                await store.count_entries(filters=None)
                await store.list_feed_sources()
                ready, _ = await store.probe_readiness()
                assert ready is True

            start = asyncio.get_event_loop().time()
            await asyncio.wait_for(_status(), timeout=2.0)
            elapsed = asyncio.get_event_loop().time() - start
            assert elapsed < 1.0, f"status probes took {elapsed:.3f}s under write load"

            await asyncio.gather(*writers)
        finally:
            await store.close()

    async def test_concurrent_stores_overlap_embedding_calls(self) -> None:
        """20 stores with a 500ms/embed stub finish in well under 20*500ms.

        Acceptance: spawn 20 concurrent stores backed by a provider that sleeps
        500ms per embed; assert total wall-time < 20 * 500ms (i.e. the embedding
        round-trips overlap instead of serialising on ``_conn_lock``).
        """
        import asyncio

        provider = _SlowEmbeddingProvider(delay=0.5)
        store = DuckDBStore(db_path=":memory:", embedding_provider=provider)
        await store.initialize()
        try:
            start = asyncio.get_event_loop().time()
            await asyncio.gather(
                *(store.store(make_entry(content=f"parallel {i}")) for i in range(20))
            )
            elapsed = asyncio.get_event_loop().time() - start
            serial = 20 * 0.5
            # Generous bound (well under serial) so the test is robust to a
            # bounded default thread-pool while still failing if embedding ran
            # under the lock (which would force ~10s of serial sleeps).
            assert elapsed < serial * 0.5, (
                f"20 stores took {elapsed:.2f}s; expected overlap (<{serial * 0.5:.1f}s)"
            )

            entries = await store.list_entries(filters=None, limit=100, offset=0)
            assert len(entries) == 20
        finally:
            await store.close()

    async def test_concurrent_status_probes_do_not_race_read_handle(
        self, store: DuckDBStore
    ) -> None:
        """Many overlapping status probes are safe on the shared read handle.

        The read handle is a single ``DuckDBPyConnection`` and is therefore not
        thread-safe for concurrent use; ``_run_read`` serialises it with a
        dedicated ``_read_lock``.  Without that lock, overlapping probes would
        race two ``asyncio.to_thread`` workers on one connection (the issue #416
        hazard, observed as a SIGSEGV).  This drives heavy contention to assert
        the reads stay correct and never crash.
        """
        import asyncio

        for i in range(10):
            await store.store(make_entry(content=f"seed {i}"))

        async def _probe() -> None:
            for _ in range(20):
                assert await store.count_entries(filters=None) == 10
                await store.list_feed_sources()
                ready, _ = await store.probe_readiness()
                assert ready is True

        await asyncio.gather(*(_probe() for _ in range(8)))

    async def test_close_does_not_race_in_flight_status_probes(self) -> None:
        """``close()`` serialises the read-handle close with ``_read_lock``.

        The read handle is a single ``DuckDBPyConnection``; closing it on the
        shutdown task while a ``_run_read`` probe is still touching it on a
        worker thread is the same two-threads-on-one-connection hazard that
        ``_read_lock`` otherwise guards (issue #416 / #558).  ``close()`` now
        takes ``_read_lock`` around the read-handle close, so an in-flight
        probe always completes (or fails gracefully) before the handle is
        torn down — never a SIGSEGV.  This drives many overlapping probes and
        closes the store underneath them, asserting a clean shutdown.
        """
        import asyncio

        provider = _SlowEmbeddingProvider(delay=0.0)
        store = DuckDBStore(db_path=":memory:", embedding_provider=provider)
        await store.initialize()
        for i in range(10):
            await store.store(make_entry(content=f"seed {i}"))

        async def _probe_until_closed() -> None:
            # Hammer the read handle until ``close()`` has torn it down.  A
            # probe that captured the handle just before close completes may
            # see a graceful ``duckdb`` "Connection already closed" or, once
            # ``_read_conn`` is ``None``, a ``RuntimeError`` "not initialized".
            # Both are acceptable — the point is the process never crashes from
            # two threads touching one connection (the issue #416 SIGSEGV).
            while store._read_conn is not None:
                with contextlib.suppress(RuntimeError, duckdb.Error):
                    await store.count_entries(filters=None)
                    await store.probe_readiness()

        probers = [asyncio.create_task(_probe_until_closed()) for _ in range(8)]
        # Let the probers ramp up, then close underneath them.
        await asyncio.sleep(0.01)
        await store.close()

        # All probers terminate cleanly; the process did not crash.
        await asyncio.gather(*probers)
        assert store._read_conn is None
        ready, reason = await store.probe_readiness()
        assert ready is False
        assert reason == "store not initialized"


class TestFTSRebuildRollback:
    """Issue #414: a failed FTS rebuild must leave the connection usable.

    Before the fix, ``_rebuild_fts_index`` swallowed the ``duckdb.Error``
    from a failing ``PRAGMA create_fts_index`` and returned without
    rolling back, leaving the connection in an aborted-transaction state.
    Subsequent statements then failed with ``TransactionContext Error:
    Current transaction is aborted (please ROLLBACK)``, which silently
    disabled ``FeedPoller._has_external_id`` (it caught the error and
    returned ``False``) and caused duplicate feed entries to accumulate.
    """

    async def test_fts_rebuild_failure_invokes_rollback(self, hybrid_store: DuckDBStore) -> None:
        """A failed PRAGMA must trigger ``conn.rollback()`` before returning.

        DuckDB ``DuckDBPyConnection.execute`` is a read-only attribute on
        the real object, so we simulate the PRAGMA failure with a mock
        connection that mimics the surface area used by
        ``_rebuild_fts_index``.  The assertion is that ``rollback()`` is
        invoked on the failure path — which is what restores the shared
        connection to a usable state in production.
        """
        from unittest.mock import MagicMock

        import duckdb

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = duckdb.Error("simulated PRAGMA failure")

        hybrid_store._fts_available = True  # noqa: SLF001 — force the rebuild path
        hybrid_store._rebuild_fts_index(mock_conn)  # noqa: SLF001

        assert hybrid_store._fts_available is False  # noqa: SLF001 — failure recorded
        mock_conn.rollback.assert_called_once()


class TestHybridGracefulFallback:
    """Verify graceful fallback to vector-only when FTS is unavailable."""

    async def test_search_works_when_hybrid_disabled(self, vector_only_store: DuckDBStore) -> None:
        """Search should work normally when hybrid_search=False."""
        await vector_only_store.store(make_entry(content="fallback test content"))
        results = await vector_only_store.search("fallback test", filters=None, limit=10)
        assert len(results) >= 1

    async def test_fts_flag_false_when_hybrid_disabled(
        self, vector_only_store: DuckDBStore
    ) -> None:
        """_fts_available should be False when hybrid_search is disabled."""
        assert vector_only_store._fts_available is False  # noqa: SLF001


class TestCheckpointBackpressure:
    """CHECKPOINT starvation guards: FORCE CHECKPOINT + disk backpressure (issue #648).

    Plain ``CHECKPOINT`` after each write fails under concurrent write
    transactions ("there are other write transactions active"); left
    uncorrected the WAL grows without bound and fills the volume.  These
    tests drive the *mechanism* (a mock connection whose ``CHECKPOINT``
    raises that error; a monkeypatched ``os.statvfs``) rather than real
    concurrency / a real full disk.  A file-backed DB under ``tmp_path``
    is used wherever a real local path is required.
    """

    @staticmethod
    def _file_store(tmp_path, mock_embedding_provider) -> DuckDBStore:
        return DuckDBStore(
            db_path=str(tmp_path / "distillery.db"),
            embedding_provider=mock_embedding_provider,
        )

    async def test_force_checkpoint_issued_after_failure_streak(
        self, tmp_path, mock_embedding_provider
    ) -> None:
        """Once the streak crosses the threshold, FORCE CHECKPOINT is issued."""
        from unittest.mock import MagicMock, call

        s = self._file_store(tmp_path, mock_embedding_provider)

        active = duckdb.Error(
            "Cannot CHECKPOINT: there are other write transactions active. "
            "Try using FORCE CHECKPOINT"
        )

        def _execute(sql: str) -> None:
            if sql == "CHECKPOINT":
                raise active
            # FORCE CHECKPOINT succeeds.

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = _execute

        # Below the threshold: only plain CHECKPOINT is attempted, no force.
        for _ in range(_FORCE_CHECKPOINT_AFTER_FAILURES - 1):
            s._checkpoint_after_write(mock_conn)  # noqa: SLF001
        assert call("FORCE CHECKPOINT") not in mock_conn.execute.call_args_list
        assert s._checkpoint_failures == _FORCE_CHECKPOINT_AFTER_FAILURES - 1  # noqa: SLF001

        # Crossing the threshold issues FORCE CHECKPOINT, which succeeds and
        # resets the streak to 0.
        s._checkpoint_after_write(mock_conn)  # noqa: SLF001
        assert call("FORCE CHECKPOINT") in mock_conn.execute.call_args_list
        assert s._checkpoint_failures == 0  # noqa: SLF001

    async def test_force_checkpoint_own_failure_keeps_streak(
        self, tmp_path, mock_embedding_provider
    ) -> None:
        """If FORCE CHECKPOINT also fails, the streak is preserved (not reset)."""
        from unittest.mock import MagicMock

        s = self._file_store(tmp_path, mock_embedding_provider)
        mock_conn = MagicMock()
        # Both plain and forced checkpoints fail.  The plain CHECKPOINT must
        # raise the writer-contention error so FORCE CHECKPOINT is attempted.
        mock_conn.execute.side_effect = duckdb.Error(
            "Cannot CHECKPOINT: there are other write transactions active. "
            "Try using FORCE CHECKPOINT"
        )

        for _ in range(_FORCE_CHECKPOINT_AFTER_FAILURES):
            s._checkpoint_after_write(mock_conn)  # noqa: SLF001

        # FORCE CHECKPOINT was attempted on the threshold-crossing call ...
        assert any(
            c.args == ("FORCE CHECKPOINT",) for c in mock_conn.execute.call_args_list
        )
        # ... but since it also failed the streak is NOT reset.
        assert s._checkpoint_failures == _FORCE_CHECKPOINT_AFTER_FAILURES  # noqa: SLF001

    async def test_non_contention_failure_does_not_force_checkpoint(
        self, tmp_path, mock_embedding_provider
    ) -> None:
        """A generic (non-contention) failure past the threshold never forces.

        FORCE CHECKPOINT aborts active write transactions, so it is reserved
        for the writer-contention case (issue #648).  An unrelated failure
        (disk-full, permissions) must not escalate to FORCE CHECKPOINT even
        once the streak crosses the threshold.
        """
        from unittest.mock import MagicMock, call

        s = self._file_store(tmp_path, mock_embedding_provider)
        mock_conn = MagicMock()
        # A non-contention failure (e.g. disk-full / permissions) on every
        # plain CHECKPOINT.
        mock_conn.execute.side_effect = duckdb.Error("IO Error: No space left on device")

        for _ in range(_FORCE_CHECKPOINT_AFTER_FAILURES + 1):
            s._checkpoint_after_write(mock_conn)  # noqa: SLF001

        # FORCE CHECKPOINT must never be issued for a non-contention failure,
        # even though the streak has crossed the threshold.
        assert call("FORCE CHECKPOINT") not in mock_conn.execute.call_args_list
        assert (
            s._checkpoint_failures == _FORCE_CHECKPOINT_AFTER_FAILURES + 1  # noqa: SLF001
        )

    async def test_disk_backpressure_warns_when_free_space_low(
        self, tmp_path, mock_embedding_provider, monkeypatch, caplog
    ) -> None:
        """A low-free-space statvfs report emits a WARNING for a file-backed DB."""
        import os as _os

        s = self._file_store(tmp_path, mock_embedding_provider)

        class _Stat:
            f_bavail = 1
            f_frsize = 4096  # ~4 KB free — well below the threshold.

        monkeypatch.setattr(_os, "statvfs", lambda _path: _Stat())

        with caplog.at_level("WARNING", logger="distillery.store.duckdb"):
            s._check_disk_backpressure()  # noqa: SLF001

        assert any("Low free space" in r.message for r in caplog.records)

    async def test_disk_backpressure_silent_when_space_ample(
        self, tmp_path, mock_embedding_provider, monkeypatch, caplog
    ) -> None:
        """Ample free space produces no WARNING."""
        import os as _os

        s = self._file_store(tmp_path, mock_embedding_provider)

        class _Stat:
            f_bavail = 10_000_000
            f_frsize = 4096  # ~40 GB free.

        monkeypatch.setattr(_os, "statvfs", lambda _path: _Stat())

        with caplog.at_level("WARNING", logger="distillery.store.duckdb"):
            s._check_disk_backpressure()  # noqa: SLF001

        assert not any("Low free space" in r.message for r in caplog.records)

    async def test_disk_backpressure_skipped_for_in_memory(
        self, mock_embedding_provider, monkeypatch, caplog
    ) -> None:
        """In-memory DBs have no local path — the statvfs guard is skipped."""
        import os as _os

        s = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)

        def _fail(_path):
            raise AssertionError("statvfs must not be called for in-memory DB")

        monkeypatch.setattr(_os, "statvfs", _fail)

        with caplog.at_level("WARNING", logger="distillery.store.duckdb"):
            s._check_disk_backpressure()  # noqa: SLF001  — must not raise

        assert not any("Low free space" in r.message for r in caplog.records)

    async def test_disk_backpressure_skipped_when_statvfs_unavailable(
        self, tmp_path, mock_embedding_provider, monkeypatch, caplog
    ) -> None:
        """Platforms without ``os.statvfs`` (e.g. Windows) skip the guard cleanly."""
        import os as _os

        s = self._file_store(tmp_path, mock_embedding_provider)
        monkeypatch.delattr(_os, "statvfs", raising=False)

        with caplog.at_level("WARNING", logger="distillery.store.duckdb"):
            s._check_disk_backpressure()  # noqa: SLF001  — must not raise

        assert not any("Low free space" in r.message for r in caplog.records)

    async def test_disk_backpressure_skipped_when_statvfs_errors(
        self, tmp_path, mock_embedding_provider, monkeypatch, caplog
    ) -> None:
        """A statvfs OSError is swallowed (no WARNING, no raise)."""
        import os as _os

        s = self._file_store(tmp_path, mock_embedding_provider)

        def _raise(_path):
            raise OSError("unsupported")

        monkeypatch.setattr(_os, "statvfs", _raise)

        with caplog.at_level("WARNING", logger="distillery.store.duckdb"):
            s._check_disk_backpressure()  # noqa: SLF001  — must not raise

        assert not any("Low free space" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _sanitise_last_error helper
#
# Pure-helper unit tests now live in ``tests/test_duckdb_sanitise_last_error.py``
# so they are marked ``unit`` only — this module applies
# ``pytestmark = pytest.mark.integration`` at the top, and double-marking
# makes marker-based selection unreliable.
# ---------------------------------------------------------------------------
