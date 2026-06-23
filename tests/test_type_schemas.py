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

    def test_entity_valid(self) -> None:
        """Entity entry with required fields passes."""
        validate_metadata(
            "entity",
            {"canonical_name": "Cloudflare", "source_tag": "entity/cloudflare"},
        )

    def test_entity_valid_with_aliases(self) -> None:
        """Entity entry with required + optional aliases passes."""
        validate_metadata(
            "entity",
            {
                "canonical_name": "Cloudflare",
                "source_tag": "entity/cloudflare",
                "aliases": ["cf", "cloudflare-inc"],
            },
        )

    def test_entity_missing_canonical_name_raises(self) -> None:
        """Entity entry missing canonical_name raises ValueError."""
        with pytest.raises(ValueError, match="canonical_name"):
            validate_metadata("entity", {"source_tag": "entity/cloudflare"})

    def test_entity_missing_source_tag_raises(self) -> None:
        """Entity entry missing source_tag raises ValueError."""
        with pytest.raises(ValueError, match="source_tag"):
            validate_metadata("entity", {"canonical_name": "Cloudflare"})

    def test_entity_empty_metadata_raises(self) -> None:
        """Entity entry with empty metadata raises ValueError."""
        with pytest.raises(ValueError, match="canonical_name"):
            validate_metadata("entity", {})

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

    def test_all_typed_schemas_present(self) -> None:
        for et in ("person", "project", "digest", "github", "entity"):
            assert et in TYPE_METADATA_SCHEMAS, f"{et!r} not in TYPE_METADATA_SCHEMAS"

    def test_entity_schema_has_canonical_name_required(self) -> None:
        schema = TYPE_METADATA_SCHEMAS["entity"]
        assert "canonical_name" in schema["required"]
        assert schema["required"]["canonical_name"] == "str"

    def test_entity_schema_has_source_tag_required(self) -> None:
        schema = TYPE_METADATA_SCHEMAS["entity"]
        assert "source_tag" in schema["required"]
        assert schema["required"]["source_tag"] == "str"

    def test_entity_schema_has_aliases_optional(self) -> None:
        schema = TYPE_METADATA_SCHEMAS["entity"]
        assert "aliases" in schema["optional"]
        assert schema["optional"]["aliases"] == "list[str]"


# ---------------------------------------------------------------------------
# EntryType enum tests for new types
# ---------------------------------------------------------------------------


class TestNewEntryTypes:
    def test_new_entry_types_have_correct_values(self) -> None:
        assert EntryType.PERSON.value == "person"
        assert EntryType.PROJECT.value == "project"
        assert EntryType.DIGEST.value == "digest"
        assert EntryType.GITHUB.value == "github"
        assert EntryType.ENTITY.value == "entity"

    def test_new_entry_types_are_str_subclasses(self) -> None:
        assert isinstance(EntryType.PERSON, str)
        assert EntryType.PERSON == "person"
        assert isinstance(EntryType.ENTITY, str)
        assert EntryType.ENTITY == "entity"

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


# ---------------------------------------------------------------------------
# Issue #559: schema-validation ValueError must surface as INVALID_PARAMS
# (not masked as INTERNAL) with the original, actionable message.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStoreValidationErrorCode:
    async def test_store_person_without_expertise_is_invalid_params(self, store: Any) -> None:
        """person w/o metadata.expertise → INVALID_PARAMS naming 'expertise'."""
        from distillery.mcp.tools.crud import _handle_store

        content = await _handle_store(
            store=store,
            arguments={
                "content": "Mitchell Hashimoto — Ghostty author",
                "entry_type": "person",
                "author": "karl",
                "metadata": {"url": "https://mitchellh.com/"},
            },
        )
        data = json.loads(content[0].text)
        assert data.get("error") is True
        assert data["code"] == "INVALID_PARAMS"
        assert "expertise" in data["message"]

    async def test_store_project_without_repo_is_invalid_params(self, store: Any) -> None:
        """project w/o metadata.repo → INVALID_PARAMS naming 'repo'."""
        from distillery.mcp.tools.crud import _handle_store

        content = await _handle_store(
            store=store,
            arguments={
                "content": "Distillery knowledge base",
                "entry_type": "project",
                "author": "karl",
                "metadata": {"status": "active"},
            },
        )
        data = json.loads(content[0].text)
        assert data.get("error") is True
        assert data["code"] == "INVALID_PARAMS"
        assert "repo" in data["message"]

    async def test_store_feed_invalid_source_type_is_invalid_params(self, store: Any) -> None:
        """feed with source_type='webhook' → INVALID_PARAMS naming the constraint."""
        from distillery.mcp.tools.crud import _handle_store

        content = await _handle_store(
            store=store,
            arguments={
                "content": "A feed item",
                "entry_type": "feed",
                "author": "karl",
                "metadata": {
                    "source_url": "https://example.com/feed",
                    "source_type": "webhook",
                },
            },
        )
        data = json.loads(content[0].text)
        assert data.get("error") is True
        assert data["code"] == "INVALID_PARAMS"
        # Message names the offending field and the allowed values.
        assert "source_type" in data["message"]
        assert "rss" in data["message"]

    async def test_store_reference_arbitrary_metadata_succeeds(self, store: Any) -> None:
        """reference with arbitrary metadata still succeeds (no schema)."""
        from distillery.mcp.tools.crud import _handle_store

        content = await _handle_store(
            store=store,
            arguments={
                "content": "Some reference doc",
                "entry_type": "reference",
                "author": "karl",
                "metadata": {"url": "https://mitchellh.com/", "anything": "goes"},
            },
        )
        data = json.loads(content[0].text)
        assert not data.get("error")
        assert "entry_id" in data
        assert data["persisted"] is True

    async def test_store_batch_invalid_metadata_is_invalid_params(self, store: Any) -> None:
        """store_batch with a schema-invalid item → top-level INVALID_PARAMS."""
        from distillery.mcp.tools.crud import _handle_store_batch

        content = await _handle_store_batch(
            store=store,
            arguments={
                "entries": [
                    {
                        "content": "Alice the engineer",
                        "entry_type": "person",
                        "author": "karl",
                        "metadata": {"team": "backend"},
                    }
                ]
            },
        )
        data = json.loads(content[0].text)
        assert data.get("error") is True
        assert data["code"] == "INVALID_PARAMS"
        assert "expertise" in data["message"]

    async def test_update_to_invalid_metadata_is_invalid_params(self, store: Any) -> None:
        """update removing a required field → INVALID_PARAMS naming the field."""
        from distillery.mcp.tools.crud import _handle_store, _handle_update

        store_content = await _handle_store(
            store=store,
            arguments={
                "content": "Alice knows Python",
                "entry_type": "person",
                "author": "karl",
                "metadata": {"expertise": ["python"]},
            },
        )
        entry_id = json.loads(store_content[0].text)["entry_id"]

        content = await _handle_update(
            store=store,
            arguments={
                "entry_id": entry_id,
                "metadata": {"team": "backend"},
            },
        )
        data = json.loads(content[0].text)
        assert data.get("error") is True
        assert data["code"] == "INVALID_PARAMS"
        assert "expertise" in data["message"]

    def test_store_docstring_lists_required_metadata_types(self) -> None:
        """distillery_store docstring names the schema-validated entry types."""
        import inspect

        from distillery.mcp import server

        # The tool wrappers are defined inside create_server(); inspect the
        # source so the test does not depend on instantiating the server.
        source = inspect.getsource(server.create_server)
        store_doc = source[source.index("async def distillery_store(") :]
        store_doc = store_doc[: store_doc.index("async def distillery_store_batch(")]

        for entry_type in ("person", "project", "digest", "github", "feed"):
            assert entry_type in store_doc, f"{entry_type!r} not mentioned in store docstring"
        assert "expertise" in store_doc
        assert "repo" in store_doc
