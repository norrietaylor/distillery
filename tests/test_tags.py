"""Tests for hierarchical tag namespace (T01).

Covers:
- validate_tag: valid flat and hierarchical tags accepted, invalid rejected
- Entry.__post_init__: tag validation on construction
- DuckDBStore filter: tag_prefix filter returns matching namespace entries
- DuckDB store: tag_prefix partial-segment boundary is respected
- MCP distillery_tag_tree tool: nested tree with counts
- MCP distillery_search: tag_prefix parameter
- MCP distillery_list: tag_prefix parameter
"""

from __future__ import annotations

import json

import pytest

from distillery.models import validate_tag
from distillery.store.duckdb import DuckDBStore
from tests.conftest import (  # noqa: PLC0415
    MockEmbeddingProvider,
    make_entry,
)

# ---------------------------------------------------------------------------
# Unit tests: validate_tag
# ---------------------------------------------------------------------------

pytestmark_unit = pytest.mark.unit


@pytest.mark.unit
class TestValidateTag:
    """Unit tests for the validate_tag() helper."""

    def test_flat_tag_accepted(self) -> None:
        validate_tag("meeting-notes")  # should not raise

    def test_hierarchical_tag_three_segments_accepted(self) -> None:
        validate_tag("project/billing-v2/decisions")  # should not raise

    def test_hierarchical_tag_two_segments_accepted(self) -> None:
        validate_tag("team/backend")

    def test_single_letter_tag_accepted(self) -> None:
        validate_tag("a")

    def test_tag_with_numbers_accepted(self) -> None:
        validate_tag("release-v3")

    def test_tag_segment_starts_with_digit_accepted(self) -> None:
        validate_tag("2024/q1")

    def test_uppercase_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_tag("Project/Billing")

    def test_uppercase_single_segment_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_tag("MeetingNotes")

    def test_trailing_slash_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_tag("project/billing/")

    def test_empty_segment_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_tag("project//billing")

    def test_leading_slash_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_tag("/project/billing")

    def test_empty_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_tag("")

    def test_underscore_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_tag("my_tag")

    def test_space_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            validate_tag("my tag")


# ---------------------------------------------------------------------------
# Unit tests: Entry.__post_init__ validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEntryTagValidation:
    """Entry construction validates tags via __post_init__."""

    def test_valid_hierarchical_tag_on_creation(self) -> None:
        entry = make_entry(tags=["project/billing-v2/decisions"])
        assert "project/billing-v2/decisions" in entry.tags

    def test_valid_flat_tag_on_creation(self) -> None:
        entry = make_entry(tags=["meeting-notes"])
        assert "meeting-notes" in entry.tags

    def test_multiple_valid_tags_accepted(self) -> None:
        entry = make_entry(tags=["project/billing", "team/backend"])
        assert len(entry.tags) == 2

    def test_uppercase_tag_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError):
            make_entry(tags=["Project/Billing"])

    def test_trailing_slash_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError):
            make_entry(tags=["project/billing/"])

    def test_empty_segment_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError):
            make_entry(tags=["project//billing"])

    def test_no_tags_is_valid(self) -> None:
        entry = make_entry(tags=[])
        assert entry.tags == []


# ---------------------------------------------------------------------------
# Integration tests: DuckDBStore tag_prefix filter
# ---------------------------------------------------------------------------


@pytest.fixture
async def tag_store(mock_embedding_provider: MockEmbeddingProvider) -> DuckDBStore:
    """In-memory DuckDBStore for tag-prefix filter tests."""
    s = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.integration
class TestTagPrefixFilter:
    """Integration tests for the tag_prefix filter in list_entries/search."""

    async def test_prefix_returns_matching_entries(self, tag_store: DuckDBStore) -> None:
        """Entries tagged under 'project/billing-v2' are returned."""
        entries = [
            make_entry(content=f"content {i}", tags=[tag])
            for i, tag in enumerate(
                [
                    "project/billing-v2/decisions",
                    "project/billing-v2/api",
                    "project/billing-v3/api",
                    "project/payments/decisions",
                ]
            )
        ]
        for e in entries:
            await tag_store.store(e)

        results = await tag_store.list_entries(
            filters={"tag_prefix": "project/billing-v2"},
            limit=10,
            offset=0,
        )
        assert len(results) == 2
        for entry in results:
            matching = any(
                t == "project/billing-v2" or t.startswith("project/billing-v2/") for t in entry.tags
            )
            assert matching, f"Entry tags {entry.tags!r} did not match prefix"

    async def test_prefix_does_not_match_partial_segment(self, tag_store: DuckDBStore) -> None:
        """'project/billing' must not match 'project/billing-v2/api'."""
        e1 = make_entry(content="billing api", tags=["project/billing/api"])
        e2 = make_entry(content="billing v2 api", tags=["project/billing-v2/api"])
        await tag_store.store(e1)
        await tag_store.store(e2)

        results = await tag_store.list_entries(
            filters={"tag_prefix": "project/billing"},
            limit=10,
            offset=0,
        )
        assert len(results) == 1
        assert "project/billing/api" in results[0].tags

    async def test_prefix_with_no_matches_returns_empty(self, tag_store: DuckDBStore) -> None:
        e = make_entry(content="something", tags=["team/backend"])
        await tag_store.store(e)

        results = await tag_store.list_entries(
            filters={"tag_prefix": "project/billing"},
            limit=10,
            offset=0,
        )
        assert results == []

    async def test_prefix_matches_exact_tag(self, tag_store: DuckDBStore) -> None:
        """An exact match (no trailing slash) is also included."""
        e = make_entry(content="exact match", tags=["team/backend"])
        await tag_store.store(e)

        results = await tag_store.list_entries(
            filters={"tag_prefix": "team/backend"},
            limit=10,
            offset=0,
        )
        assert len(results) == 1

    async def test_search_with_tag_prefix_filter(self, tag_store: DuckDBStore) -> None:
        """search() also supports tag_prefix."""
        e1 = make_entry(content="arch document", tags=["domain/architecture"])
        e2 = make_entry(content="security document", tags=["domain/security"])
        await tag_store.store(e1)
        await tag_store.store(e2)

        results = await tag_store.search(
            query="arch document",
            filters={"tag_prefix": "domain/architecture"},
            limit=10,
        )
        assert len(results) == 1
        assert "domain/architecture" in results[0].entry.tags


# ---------------------------------------------------------------------------
# Integration tests: distillery_tag_tree MCP tool
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTagTreeMCPTool:
    """Tests for the _handle_tag_tree handler (through the MCP server layer)."""

    async def test_tag_tree_returns_nested_structure(self, tag_store: DuckDBStore) -> None:
        """Tag tree is nested with correct counts."""
        from distillery.mcp.server import _handle_tag_tree

        entries = [
            make_entry(content=f"c{i}", tags=[tag])
            for i, tag in enumerate(
                [
                    "project/billing-v2/decisions",
                    "project/billing-v2/api",
                    "project/payments/decisions",
                    "team/backend",
                ]
            )
        ]
        for e in entries:
            await tag_store.store(e)

        result = await _handle_tag_tree(
            store=tag_store,
            arguments={"prefix": None},
        )
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert "tree" in data
        tree = data["tree"]

        # Check "project" node exists and has correct children
        assert "project" in tree["children"]
        project_node = tree["children"]["project"]
        assert "billing-v2" in project_node["children"]
        assert "payments" in project_node["children"]

        # billing-v2 subtree has count 2
        billing_v2 = project_node["children"]["billing-v2"]
        assert billing_v2["count"] == 2

        # team/backend appears
        assert "team" in tree["children"]

    async def test_tag_tree_filters_by_prefix(self, tag_store: DuckDBStore) -> None:
        """When prefix='project', team nodes are excluded."""
        from distillery.mcp.server import _handle_tag_tree

        entries = [
            make_entry(content="billing decisions", tags=["project/billing-v2/decisions"]),
            make_entry(content="backend docs", tags=["team/backend"]),
        ]
        for e in entries:
            await tag_store.store(e)

        result = await _handle_tag_tree(
            store=tag_store,
            arguments={"prefix": "project"},
        )
        data = json.loads(result[0].text)
        tree = data["tree"]

        # The tree is rooted at project, so its children contain "billing-v2"
        assert "billing-v2" in tree["children"]
        # "team" should NOT appear
        assert "team" not in tree["children"]
        assert data["prefix"] == "project"

    async def test_tag_tree_empty_store_returns_empty_tree(self, tag_store: DuckDBStore) -> None:
        """Empty store produces an empty tree."""
        from distillery.mcp.server import _handle_tag_tree

        result = await _handle_tag_tree(
            store=tag_store,
            arguments={"prefix": None},
        )
        data = json.loads(result[0].text)
        assert data["tree"]["children"] == {}
        assert data["tree"]["count"] == 0
