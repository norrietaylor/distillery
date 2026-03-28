"""Tests for entry type schemas and metadata validation (T02).

Covers:
  - TYPE_METADATA_SCHEMAS registry contents
  - validate_metadata() function
  - DuckDBStore.store() / update() enforcement
  - distillery_type_schemas MCP tool
  - distillery_store / distillery_update MCP error reporting
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from distillery.models import (
    TYPE_METADATA_SCHEMAS,
    EntryType,
    validate_metadata,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# validate_metadata unit tests
# ---------------------------------------------------------------------------


class TestValidateMetadata:
    def test_person_valid(self) -> None:
        """Person entry with required expertise field passes."""
        validate_metadata("person", {"expertise": ["python", "duckdb"]})

    def test_person_valid_with_optional(self) -> None:
        """Person entry with required + optional fields passes."""
        validate_metadata(
            "person",
            {"expertise": ["python"], "github_username": "dev1", "team": "backend"},
        )

    def test_person_missing_expertise_raises(self) -> None:
        """Person entry missing expertise raises ValueError."""
        with pytest.raises(ValueError, match="expertise"):
            validate_metadata("person", {"github_username": "dev1"})

    def test_person_empty_metadata_raises(self) -> None:
        """Person entry with empty metadata raises ValueError."""
        with pytest.raises(ValueError, match="expertise"):
            validate_metadata("person", {})

    def test_project_valid(self) -> None:
        """Project entry with required repo field passes."""
        validate_metadata("project", {"repo": "org/repo", "status": "active"})

    def test_project_missing_repo_raises(self) -> None:
        """Project entry missing repo raises ValueError."""
        with pytest.raises(ValueError, match="repo"):
            validate_metadata("project", {"status": "active"})

    def test_digest_valid(self) -> None:
        """Digest entry with both date fields passes."""
        validate_metadata("digest", {"period_start": "2026-03-01", "period_end": "2026-03-07"})

    def test_digest_missing_period_start_raises(self) -> None:
        """Digest entry missing period_start raises ValueError."""
        with pytest.raises(ValueError, match="period_start"):
            validate_metadata("digest", {"period_end": "2026-03-07"})

    def test_digest_missing_period_end_raises(self) -> None:
        """Digest entry missing period_end raises ValueError."""
        with pytest.raises(ValueError, match="period_end"):
            validate_metadata("digest", {"period_start": "2026-03-01"})

    def test_github_valid(self) -> None:
        """GitHub entry with all required fields and valid ref_type passes."""
        validate_metadata("github", {"repo": "org/repo", "ref_type": "pr", "ref_number": 42})

    def test_github_valid_issue(self) -> None:
        validate_metadata("github", {"repo": "org/repo", "ref_type": "issue", "ref_number": 1})

    def test_github_valid_discussion(self) -> None:
        validate_metadata("github", {"repo": "org/repo", "ref_type": "discussion", "ref_number": 5})

    def test_github_valid_release(self) -> None:
        validate_metadata("github", {"repo": "org/repo", "ref_type": "release", "ref_number": 10})

    def test_github_missing_repo_raises(self) -> None:
        with pytest.raises(ValueError, match="repo"):
            validate_metadata("github", {"ref_type": "pr", "ref_number": 1})

    def test_github_missing_ref_type_raises(self) -> None:
        with pytest.raises(ValueError, match="ref_type"):
            validate_metadata("github", {"repo": "org/repo", "ref_number": 1})

    def test_github_missing_ref_number_raises(self) -> None:
        with pytest.raises(ValueError, match="ref_number"):
            validate_metadata("github", {"repo": "org/repo", "ref_type": "pr"})

    def test_github_invalid_ref_type_raises(self) -> None:
        """GitHub entry with invalid ref_type raises ValueError with allowed values."""
        with pytest.raises(ValueError, match="ref_type"):
            validate_metadata(
                "github",
                {"repo": "org/repo", "ref_type": "commit", "ref_number": 1},
            )
        # Verify the error message names the allowed values.
        with pytest.raises(ValueError, match="issue"):
            validate_metadata(
                "github",
                {"repo": "org/repo", "ref_type": "invalid", "ref_number": 1},
            )

    def test_legacy_types_accept_any_metadata(self) -> None:
        """Session, bookmark, etc. accept arbitrary metadata without error."""
        validate_metadata("session", {"arbitrary_key": "any_value"})
        validate_metadata("bookmark", {})
        validate_metadata("minutes", {"foo": "bar", "baz": 123})
        validate_metadata("meeting", {})
        validate_metadata("reference", {"custom": True})
        validate_metadata("idea", {})
        validate_metadata("inbox", {"nested": {"key": "val"}})

    def test_unknown_type_accepts_any_metadata(self) -> None:
        """An unrecognised entry_type string is treated as no-schema."""
        validate_metadata("unknown_future_type", {"anything": "goes"})


# ---------------------------------------------------------------------------
# TYPE_METADATA_SCHEMAS registry content tests
# ---------------------------------------------------------------------------


class TestTypeMetadataSchemasRegistry:
    def test_person_schema_has_expertise_required(self) -> None:
        schema = TYPE_METADATA_SCHEMAS["person"]
        assert "expertise" in schema["required"]
        assert schema["required"]["expertise"] == "list[str]"

    def test_github_schema_has_all_required_fields(self) -> None:
        schema = TYPE_METADATA_SCHEMAS["github"]
        required = schema["required"]
        assert "repo" in required
        assert "ref_type" in required
        assert "ref_number" in required

    def test_github_schema_has_constraints(self) -> None:
        schema = TYPE_METADATA_SCHEMAS["github"]
        assert "constraints" in schema
        allowed = schema["constraints"]["ref_type"]
        assert set(allowed) == {"issue", "pr", "discussion", "release"}

    def test_project_schema_has_repo_required(self) -> None:
        schema = TYPE_METADATA_SCHEMAS["project"]
        assert "repo" in schema["required"]

    def test_digest_schema_has_date_fields_required(self) -> None:
        schema = TYPE_METADATA_SCHEMAS["digest"]
        assert "period_start" in schema["required"]
        assert "period_end" in schema["required"]

    def test_all_four_typed_schemas_present(self) -> None:
        for et in ("person", "project", "digest", "github"):
            assert et in TYPE_METADATA_SCHEMAS, f"{et!r} not in TYPE_METADATA_SCHEMAS"


# ---------------------------------------------------------------------------
# EntryType enum tests for new types
# ---------------------------------------------------------------------------


class TestNewEntryTypes:
    def test_new_entry_types_have_correct_values(self) -> None:
        assert EntryType.PERSON.value == "person"
        assert EntryType.PROJECT.value == "project"
        assert EntryType.DIGEST.value == "digest"
        assert EntryType.GITHUB.value == "github"

    def test_new_entry_types_are_str_subclasses(self) -> None:
        assert isinstance(EntryType.PERSON, str)
        assert EntryType.PERSON == "person"

    def test_new_entry_types_constructible_from_string(self) -> None:
        assert EntryType("person") is EntryType.PERSON
        assert EntryType("github") is EntryType.GITHUB


# ---------------------------------------------------------------------------
# DuckDBStore integration tests (store + update validation)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDuckDBStoreValidation:
    async def test_person_valid_metadata_stored(self, store: Any) -> None:
        """Person entry with valid metadata is stored successfully."""
        from tests.conftest import make_entry

        entry = make_entry(
            entry_type=EntryType.PERSON,
            metadata={"expertise": ["python", "duckdb"], "github_username": "dev1"},
        )
        entry_id = await store.store(entry)
        assert entry_id is not None
        stored = await store.get(entry_id)
        assert stored is not None
        assert stored.metadata["expertise"] == ["python", "duckdb"]

    async def test_person_missing_expertise_rejected(self, store: Any) -> None:
        """Person entry without expertise raises ValueError on store."""
        from tests.conftest import make_entry

        entry = make_entry(
            entry_type=EntryType.PERSON,
            metadata={"github_username": "dev1"},
        )
        with pytest.raises(ValueError, match="expertise"):
            await store.store(entry)

    async def test_github_valid_metadata_stored(self, store: Any) -> None:
        """GitHub entry with valid metadata is stored successfully."""
        from tests.conftest import make_entry

        entry = make_entry(
            entry_type=EntryType.GITHUB,
            metadata={"repo": "org/repo", "ref_type": "pr", "ref_number": 42},
        )
        entry_id = await store.store(entry)
        stored = await store.get(entry_id)
        assert stored is not None
        assert stored.metadata["repo"] == "org/repo"

    async def test_github_invalid_ref_type_rejected(self, store: Any) -> None:
        """GitHub entry with invalid ref_type raises ValueError on store."""
        from tests.conftest import make_entry

        entry = make_entry(
            entry_type=EntryType.GITHUB,
            metadata={"repo": "org/repo", "ref_type": "commit", "ref_number": 1},
        )
        with pytest.raises(ValueError, match="ref_type"):
            await store.store(entry)

    async def test_project_missing_repo_rejected(self, store: Any) -> None:
        """Project entry without repo raises ValueError on store."""
        from tests.conftest import make_entry

        entry = make_entry(
            entry_type=EntryType.PROJECT,
            metadata={"status": "active"},
        )
        with pytest.raises(ValueError, match="repo"):
            await store.store(entry)

    async def test_digest_valid_stored(self, store: Any) -> None:
        """Digest entry with both date fields is stored successfully."""
        from tests.conftest import make_entry

        entry = make_entry(
            entry_type=EntryType.DIGEST,
            metadata={"period_start": "2026-03-01", "period_end": "2026-03-07"},
        )
        entry_id = await store.store(entry)
        assert entry_id is not None

    async def test_session_arbitrary_metadata_accepted(self, store: Any) -> None:
        """Session entries accept any metadata without validation error."""
        from tests.conftest import make_entry

        entry = make_entry(
            entry_type=EntryType.SESSION,
            metadata={"arbitrary_key": "any_value"},
        )
        entry_id = await store.store(entry)
        assert entry_id is not None

    async def test_bookmark_empty_metadata_accepted(self, store: Any) -> None:
        """Bookmark entries with empty metadata are accepted."""
        from tests.conftest import make_entry

        entry = make_entry(
            entry_type=EntryType.BOOKMARK,
            metadata={},
        )
        entry_id = await store.store(entry)
        assert entry_id is not None

    async def test_update_revalidates_metadata(self, store: Any) -> None:
        """Updating metadata on a person entry to remove expertise raises ValueError."""
        from tests.conftest import make_entry

        entry = make_entry(
            entry_type=EntryType.PERSON,
            metadata={"expertise": ["python"]},
        )
        entry_id = await store.store(entry)

        # Now update with invalid metadata (missing expertise).
        with pytest.raises(ValueError, match="expertise"):
            await store.update(entry_id, {"metadata": {"github_username": "dev1"}})

        # Verify the original entry is unchanged.
        original = await store.get(entry_id)
        assert original is not None
        assert original.metadata["expertise"] == ["python"]


# ---------------------------------------------------------------------------
# MCP tool tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDistilleryTypeSchemasMCPTool:
    async def test_type_schemas_returns_all_typed_schemas(self) -> None:
        """distillery_type_schemas returns schemas for all four typed entry types."""
        from distillery.mcp.server import _handle_type_schemas

        content = await _handle_type_schemas()
        assert len(content) == 1
        data = json.loads(content[0].text)
        schemas = data["schemas"]

        for et in ("person", "project", "digest", "github"):
            assert et in schemas, f"{et!r} missing from schemas"

    async def test_person_schema_has_expertise_required(self) -> None:
        from distillery.mcp.server import _handle_type_schemas

        content = await _handle_type_schemas()
        data = json.loads(content[0].text)
        person_schema = data["schemas"]["person"]
        assert "expertise" in person_schema["required"]
        assert person_schema["required"]["expertise"] == "list[str]"

    async def test_github_schema_has_required_fields(self) -> None:
        from distillery.mcp.server import _handle_type_schemas

        content = await _handle_type_schemas()
        data = json.loads(content[0].text)
        github_schema = data["schemas"]["github"]
        for field in ("repo", "ref_type", "ref_number"):
            assert field in github_schema["required"], f"{field!r} not in github required"

    async def test_session_type_has_no_required_fields(self) -> None:
        """Legacy types like session have empty required dict."""
        from distillery.mcp.server import _handle_type_schemas

        content = await _handle_type_schemas()
        data = json.loads(content[0].text)
        session_schema = data["schemas"]["session"]
        assert session_schema["required"] == {}

    async def test_all_entry_types_present(self) -> None:
        """All EntryType enum members appear in the schema response."""
        from distillery.mcp.server import _handle_type_schemas

        content = await _handle_type_schemas()
        data = json.loads(content[0].text)
        for et in EntryType:
            assert et.value in data["schemas"], f"{et.value!r} missing"


@pytest.mark.unit
class TestDistilleryStoreMCPValidation:
    async def test_store_person_missing_expertise_returns_error(self) -> None:
        """distillery_store returns error when person metadata is invalid."""
        from distillery.mcp.server import _handle_store

        mock_store = AsyncMock()
        # store() should not be called at all because validation happens first.
        # But the Entry is constructed first, then validate_metadata is called
        # inside _sync_store. Since we mock at a higher level, we simulate the
        # ValueError propagating from store.store().
        mock_store.store.side_effect = ValueError(
            "Metadata for entry_type='person' is missing required field 'expertise'"
        )

        content = await _handle_store(
            store=mock_store,
            arguments={
                "content": "Alice is an engineer.",
                "entry_type": "person",
                "author": "test",
                "metadata": {"team": "backend"},
            },
        )

        data = json.loads(content[0].text)
        assert data.get("error") is True
        # The error should mention the store failure.

    async def test_store_person_valid_returns_entry_id(self) -> None:
        """distillery_store with valid person metadata returns entry_id."""
        from distillery.mcp.server import _handle_store

        mock_store = AsyncMock()
        mock_store.store.return_value = "test-uuid-1234"
        mock_store.find_similar.return_value = []

        content = await _handle_store(
            store=mock_store,
            arguments={
                "content": "Alice knows Python.",
                "entry_type": "person",
                "author": "test",
                "metadata": {"expertise": ["python"]},
            },
        )

        data = json.loads(content[0].text)
        assert "entry_id" in data
        assert data["entry_id"] == "test-uuid-1234"
        assert not data.get("error")

    async def test_store_invalid_entry_type_returns_error(self) -> None:
        """distillery_store with unrecognised entry_type returns error."""
        from distillery.mcp.server import _handle_store

        mock_store = AsyncMock()
        content = await _handle_store(
            store=mock_store,
            arguments={
                "content": "Some content.",
                "entry_type": "nonexistent_type",
                "author": "test",
            },
        )
        data = json.loads(content[0].text)
        assert data.get("error") is True