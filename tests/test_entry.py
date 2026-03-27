"""Tests for distillery.models: Entry, enums, and SearchResult."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from distillery.models import (
    Entry,
    EntrySource,
    EntryStatus,
    EntryType,
    SearchResult,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


class TestEntryTypeEnum:
    def test_all_values(self) -> None:
        assert EntryType.SESSION.value == "session"
        assert EntryType.BOOKMARK.value == "bookmark"
        assert EntryType.MINUTES.value == "minutes"
        assert EntryType.MEETING.value == "meeting"
        assert EntryType.REFERENCE.value == "reference"
        assert EntryType.IDEA.value == "idea"
        assert EntryType.INBOX.value == "inbox"

    def test_is_str_subclass(self) -> None:
        assert isinstance(EntryType.SESSION, str)
        assert EntryType.SESSION == "session"

    def test_from_string(self) -> None:
        assert EntryType("bookmark") is EntryType.BOOKMARK

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError):
            EntryType("unknown")


class TestEntrySourceEnum:
    def test_all_values(self) -> None:
        assert EntrySource.CLAUDE_CODE.value == "claude-code"
        assert EntrySource.MANUAL.value == "manual"
        assert EntrySource.IMPORT.value == "import"

    def test_is_str_subclass(self) -> None:
        assert isinstance(EntrySource.MANUAL, str)

    def test_from_string(self) -> None:
        assert EntrySource("manual") is EntrySource.MANUAL


class TestEntryStatusEnum:
    def test_all_values(self) -> None:
        assert EntryStatus.ACTIVE.value == "active"
        assert EntryStatus.PENDING_REVIEW.value == "pending_review"
        assert EntryStatus.ARCHIVED.value == "archived"

    def test_is_str_subclass(self) -> None:
        assert isinstance(EntryStatus.ACTIVE, str)

    def test_from_string(self) -> None:
        assert EntryStatus("archived") is EntryStatus.ARCHIVED


# ---------------------------------------------------------------------------
# Entry creation and defaults
# ---------------------------------------------------------------------------


def make_entry(**kwargs) -> Entry:
    """Return a minimal valid Entry, optionally overriding fields."""
    defaults = {
        "content": "Test content",
        "entry_type": EntryType.INBOX,
        "source": EntrySource.MANUAL,
        "author": "tester",
    }
    defaults.update(kwargs)
    return Entry(**defaults)


class TestEntryCreation:
    def test_required_fields(self) -> None:
        e = make_entry()
        assert e.content == "Test content"
        assert e.entry_type is EntryType.INBOX
        assert e.source is EntrySource.MANUAL
        assert e.author == "tester"

    def test_id_is_valid_uuid(self) -> None:
        e = make_entry()
        parsed = uuid.UUID(e.id)
        assert str(parsed) == e.id

    def test_id_auto_generated_unique(self) -> None:
        e1 = make_entry()
        e2 = make_entry()
        assert e1.id != e2.id

    def test_created_at_is_utc_datetime(self) -> None:
        e = make_entry()
        assert isinstance(e.created_at, datetime)
        assert e.created_at.tzinfo is not None
        assert e.created_at.tzinfo == UTC

    def test_updated_at_is_utc_datetime(self) -> None:
        e = make_entry()
        assert isinstance(e.updated_at, datetime)
        assert e.updated_at.tzinfo is not None

    def test_version_default_is_one(self) -> None:
        e = make_entry()
        assert e.version == 1

    def test_status_default_is_active(self) -> None:
        e = make_entry()
        assert e.status is EntryStatus.ACTIVE

    def test_tags_default_is_empty_list(self) -> None:
        e = make_entry()
        assert e.tags == []

    def test_metadata_default_is_empty_dict(self) -> None:
        e = make_entry()
        assert e.metadata == {}

    def test_project_default_is_none(self) -> None:
        e = make_entry()
        assert e.project is None

    def test_tags_not_shared_between_instances(self) -> None:
        e1 = make_entry()
        e2 = make_entry()
        e1.tags.append("x")
        assert e2.tags == []

    def test_metadata_not_shared_between_instances(self) -> None:
        e1 = make_entry()
        e2 = make_entry()
        e1.metadata["k"] = "v"
        assert e2.metadata == {}


# ---------------------------------------------------------------------------
# Type-specific metadata
# ---------------------------------------------------------------------------


class TestTypeSpecificMetadata:
    def test_session_metadata_fields(self) -> None:
        e = make_entry(
            entry_type=EntryType.SESSION,
            metadata={"session_id": "s-123", "session_type": "work"},
        )
        assert e.metadata["session_id"] == "s-123"
        assert e.metadata["session_type"] == "work"

    def test_session_metadata_cowork(self) -> None:
        e = make_entry(
            entry_type=EntryType.SESSION,
            metadata={"session_type": "cowork"},
        )
        assert e.metadata["session_type"] == "cowork"

    def test_bookmark_metadata_fields(self) -> None:
        e = make_entry(
            entry_type=EntryType.BOOKMARK,
            metadata={"url": "https://example.com", "summary": "Example site"},
        )
        assert e.metadata["url"] == "https://example.com"
        assert e.metadata["summary"] == "Example site"

    def test_minutes_metadata_fields(self) -> None:
        e = make_entry(
            entry_type=EntryType.MINUTES,
            metadata={"meeting_id": "mtg-456"},
        )
        assert e.metadata["meeting_id"] == "mtg-456"


# ---------------------------------------------------------------------------
# Serialisation: to_dict
# ---------------------------------------------------------------------------


class TestEntryToDict:
    def test_to_dict_returns_dict(self) -> None:
        e = make_entry()
        d = e.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_enum_values_are_strings(self) -> None:
        e = make_entry(
            entry_type=EntryType.BOOKMARK,
            source=EntrySource.CLAUDE_CODE,
            status=EntryStatus.ARCHIVED,
        )
        d = e.to_dict()
        assert d["entry_type"] == "bookmark"
        assert d["source"] == "claude-code"
        assert d["status"] == "archived"

    def test_to_dict_contains_all_keys(self) -> None:
        e = make_entry()
        d = e.to_dict()
        expected_keys = {
            "id", "content", "entry_type", "source", "author",
            "project", "tags", "status", "created_at", "updated_at",
            "version", "metadata", "accessed_at",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_datetime_is_isoformat_string(self) -> None:
        e = make_entry()
        d = e.to_dict()
        assert isinstance(d["created_at"], str)
        assert isinstance(d["updated_at"], str)
        # Should be parseable as ISO
        parsed = datetime.fromisoformat(d["created_at"])
        assert parsed == e.created_at

    def test_accessed_at_roundtrip(self) -> None:
        accessed = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        e = make_entry(accessed_at=accessed)
        d = e.to_dict()
        assert d["accessed_at"] == accessed.isoformat()
        restored = Entry.from_dict(d)
        assert restored.accessed_at == accessed

    def test_to_dict_tags_is_list_copy(self) -> None:
        e = make_entry(tags=["a", "b"])
        d = e.to_dict()
        d["tags"].append("c")
        assert e.tags == ["a", "b"]

    def test_to_dict_metadata_is_dict_copy(self) -> None:
        e = make_entry(metadata={"k": "v"})
        d = e.to_dict()
        d["metadata"]["extra"] = "x"
        assert e.metadata == {"k": "v"}

    def test_to_dict_project_none(self) -> None:
        e = make_entry()
        d = e.to_dict()
        assert d["project"] is None

    def test_to_dict_version(self) -> None:
        e = make_entry()
        e.version = 3
        assert e.to_dict()["version"] == 3


# ---------------------------------------------------------------------------
# Deserialisation: from_dict
# ---------------------------------------------------------------------------


class TestEntryFromDict:
    def test_roundtrip(self) -> None:
        e = make_entry(
            entry_type=EntryType.SESSION,
            source=EntrySource.CLAUDE_CODE,
            project="my-project",
            tags=["foo"],
            status=EntryStatus.PENDING_REVIEW,
            metadata={"session_id": "abc"},
        )
        restored = Entry.from_dict(e.to_dict())
        assert restored == e

    def test_from_dict_parses_enums(self) -> None:
        e = make_entry()
        d = e.to_dict()
        restored = Entry.from_dict(d)
        assert restored.entry_type is EntryType.INBOX
        assert restored.source is EntrySource.MANUAL
        assert restored.status is EntryStatus.ACTIVE

    def test_from_dict_parses_datetime_string(self) -> None:
        e = make_entry()
        d = e.to_dict()
        restored = Entry.from_dict(d)
        assert restored.created_at == e.created_at
        assert restored.updated_at == e.updated_at

    def test_from_dict_naive_datetime_gets_utc(self) -> None:
        e = make_entry()
        d = e.to_dict()
        # Strip timezone offset to simulate naive datetime string
        d["created_at"] = e.created_at.replace(tzinfo=None).isoformat()
        d["updated_at"] = e.updated_at.replace(tzinfo=None).isoformat()
        restored = Entry.from_dict(d)
        assert restored.created_at.tzinfo is not None

    def test_from_dict_missing_required_key_raises(self) -> None:
        e = make_entry()
        d = e.to_dict()
        del d["content"]
        with pytest.raises(KeyError):
            Entry.from_dict(d)

    def test_from_dict_invalid_enum_raises(self) -> None:
        e = make_entry()
        d = e.to_dict()
        d["entry_type"] = "nonexistent"
        with pytest.raises(ValueError):
            Entry.from_dict(d)

    def test_from_dict_optional_tags_defaults_to_empty(self) -> None:
        e = make_entry()
        d = e.to_dict()
        del d["tags"]
        restored = Entry.from_dict(d)
        assert restored.tags == []

    def test_from_dict_optional_metadata_defaults_to_empty(self) -> None:
        e = make_entry()
        d = e.to_dict()
        del d["metadata"]
        restored = Entry.from_dict(d)
        assert restored.metadata == {}

    def test_from_dict_optional_version_defaults_to_one(self) -> None:
        e = make_entry()
        d = e.to_dict()
        del d["version"]
        restored = Entry.from_dict(d)
        assert restored.version == 1

    def test_from_dict_accepts_datetime_object(self) -> None:
        e = make_entry()
        d = e.to_dict()
        # Pass actual datetime objects instead of strings
        d["created_at"] = e.created_at
        d["updated_at"] = e.updated_at
        restored = Entry.from_dict(d)
        assert restored.created_at == e.created_at


# ---------------------------------------------------------------------------
# All entry types round-trip
# ---------------------------------------------------------------------------


class TestAllEntryTypesRoundTrip:
    @pytest.mark.parametrize("entry_type", list(EntryType))
    def test_entry_type_roundtrip(self, entry_type: EntryType) -> None:
        e = make_entry(entry_type=entry_type)
        assert Entry.from_dict(e.to_dict()).entry_type is entry_type

    @pytest.mark.parametrize("source", list(EntrySource))
    def test_source_roundtrip(self, source: EntrySource) -> None:
        e = make_entry(source=source)
        assert Entry.from_dict(e.to_dict()).source is source

    @pytest.mark.parametrize("status", list(EntryStatus))
    def test_status_roundtrip(self, status: EntryStatus) -> None:
        e = make_entry(status=status)
        assert Entry.from_dict(e.to_dict()).status is status


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------


class TestSearchResult:
    def test_creation(self) -> None:
        e = make_entry()
        sr = SearchResult(entry=e, score=0.95)
        assert sr.entry is e
        assert sr.score == 0.95

    def test_score_zero(self) -> None:
        e = make_entry()
        sr = SearchResult(entry=e, score=0.0)
        assert sr.score == 0.0

    def test_score_one(self) -> None:
        e = make_entry()
        sr = SearchResult(entry=e, score=1.0)
        assert sr.score == 1.0

    def test_entry_accessible(self) -> None:
        e = make_entry(content="hello world", author="bob")
        sr = SearchResult(entry=e, score=0.7)
        assert sr.entry.content == "hello world"
        assert sr.entry.author == "bob"
