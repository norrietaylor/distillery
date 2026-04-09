"""Tests for extended EntrySource provenance values (inference, documentation, external)."""

from __future__ import annotations

import pytest

from distillery.models import Entry, EntrySource, EntryType


@pytest.mark.unit
class TestEntrySourceExtension:
    """Test that new source values are properly defined and accessible."""

    def test_new_source_values_exist(self) -> None:
        """Verify all new source values are defined in the enum."""
        assert hasattr(EntrySource, "INFERENCE")
        assert hasattr(EntrySource, "DOCUMENTATION")
        assert hasattr(EntrySource, "EXTERNAL")

    def test_new_source_string_values(self) -> None:
        """Verify new source values have correct string representations."""
        assert EntrySource.INFERENCE.value == "inference"
        assert EntrySource.DOCUMENTATION.value == "documentation"
        assert EntrySource.EXTERNAL.value == "external"

    def test_new_sources_are_str_enum(self) -> None:
        """Verify new sources behave as StrEnum members."""
        assert isinstance(EntrySource.INFERENCE, str)
        assert isinstance(EntrySource.DOCUMENTATION, str)
        assert isinstance(EntrySource.EXTERNAL, str)

    def test_construct_from_string(self) -> None:
        """Verify new sources can be constructed from string values."""
        assert EntrySource("inference") is EntrySource.INFERENCE
        assert EntrySource("documentation") is EntrySource.DOCUMENTATION
        assert EntrySource("external") is EntrySource.EXTERNAL

    def test_invalid_source_raises(self) -> None:
        """Verify invalid source values raise ValueError."""
        with pytest.raises(ValueError):
            EntrySource("made-up-source")


@pytest.mark.unit
class TestEntryWithNewSources:
    """Test Entry creation and serialization with new source values."""

    def test_create_entry_with_inference_source(self) -> None:
        """Create an entry with inference source."""
        entry = Entry(
            content="auto-extracted: function X does Y",
            entry_type=EntryType.REFERENCE,
            source=EntrySource.INFERENCE,
            author="hook",
        )
        assert entry.source is EntrySource.INFERENCE
        assert entry.source.value == "inference"

    def test_create_entry_with_documentation_source(self) -> None:
        """Create an entry with documentation source."""
        entry = Entry(
            content="from README: install with pip",
            entry_type=EntryType.REFERENCE,
            source=EntrySource.DOCUMENTATION,
            author="scraper",
        )
        assert entry.source is EntrySource.DOCUMENTATION
        assert entry.source.value == "documentation"

    def test_create_entry_with_external_source(self) -> None:
        """Create an entry with external source."""
        entry = Entry(
            content="from Stack Overflow: use async await",
            entry_type=EntryType.REFERENCE,
            source=EntrySource.EXTERNAL,
            author="web-crawl",
        )
        assert entry.source is EntrySource.EXTERNAL
        assert entry.source.value == "external"

    def test_serialize_with_new_source(self) -> None:
        """Verify to_dict() serializes new source values correctly."""
        entry = Entry(
            content="test content",
            entry_type=EntryType.REFERENCE,
            source=EntrySource.INFERENCE,
            author="test",
        )
        as_dict = entry.to_dict()
        assert as_dict["source"] == "inference"

    def test_deserialize_with_new_source(self) -> None:
        """Verify from_dict() deserializes new source values correctly."""
        data = {
            "id": "test-id",
            "content": "test content",
            "entry_type": "reference",
            "source": "documentation",
            "author": "test",
            "created_at": "2026-04-08T00:00:00+00:00",
            "updated_at": "2026-04-08T00:00:00+00:00",
        }
        entry = Entry.from_dict(data)
        assert entry.source is EntrySource.DOCUMENTATION
        assert entry.source.value == "documentation"

    def test_roundtrip_with_new_source(self) -> None:
        """Verify to_dict() -> from_dict() preserves new source values."""
        original = Entry(
            content="test",
            entry_type=EntryType.REFERENCE,
            source=EntrySource.EXTERNAL,
            author="test",
        )
        as_dict = original.to_dict()
        restored = Entry.from_dict(as_dict)
        assert restored.source is EntrySource.EXTERNAL
        assert restored == original


@pytest.mark.unit
class TestExistingSourcesBackwardCompatibility:
    """Verify that existing source values continue to work unchanged."""

    def test_existing_sources_still_work(self) -> None:
        """Verify existing sources are still defined."""
        assert EntrySource.CLAUDE_CODE.value == "claude-code"
        assert EntrySource.MANUAL.value == "manual"
        assert EntrySource.IMPORT.value == "import"

    def test_create_with_existing_sources(self) -> None:
        """Verify entries can still be created with existing source values."""
        for source in [EntrySource.CLAUDE_CODE, EntrySource.MANUAL, EntrySource.IMPORT]:
            entry = Entry(
                content="test",
                entry_type=EntryType.INBOX,
                source=source,
                author="test",
            )
            assert entry.source is source

    def test_serialize_existing_sources(self) -> None:
        """Verify to_dict() still works for existing sources."""
        entry = Entry(
            content="test",
            entry_type=EntryType.INBOX,
            source=EntrySource.MANUAL,
            author="test",
        )
        as_dict = entry.to_dict()
        assert as_dict["source"] == "manual"

    def test_deserialize_existing_sources(self) -> None:
        """Verify from_dict() still works for existing sources."""
        data = {
            "id": "test-id",
            "content": "test",
            "entry_type": "inbox",
            "source": "claude-code",
            "author": "test",
            "created_at": "2026-04-08T00:00:00+00:00",
            "updated_at": "2026-04-08T00:00:00+00:00",
        }
        entry = Entry.from_dict(data)
        assert entry.source is EntrySource.CLAUDE_CODE


# Integration tests with store
@pytest.mark.integration
class TestStoreWithNewSources:
    """Integration tests for storing and filtering entries with new sources."""

    async def test_store_entry_with_inference_source(self, store: any) -> None:
        """Store an entry with inference source and verify retrieval."""
        entry = Entry(
            content="auto-extracted content",
            entry_type=EntryType.REFERENCE,
            source=EntrySource.INFERENCE,
            author="hook",
        )
        entry_id = await store.store(entry)
        assert entry_id == entry.id

        retrieved = await store.get(entry_id)
        assert retrieved is not None
        assert retrieved.source is EntrySource.INFERENCE

    async def test_store_entry_with_documentation_source(self, store: any) -> None:
        """Store an entry with documentation source and verify retrieval."""
        entry = Entry(
            content="documentation extracted content",
            entry_type=EntryType.REFERENCE,
            source=EntrySource.DOCUMENTATION,
            author="doc-crawler",
        )
        entry_id = await store.store(entry)
        retrieved = await store.get(entry_id)
        assert retrieved is not None
        assert retrieved.source is EntrySource.DOCUMENTATION

    async def test_store_entry_with_external_source(self, store: any) -> None:
        """Store an entry with external source and verify retrieval."""
        entry = Entry(
            content="external content from web",
            entry_type=EntryType.REFERENCE,
            source=EntrySource.EXTERNAL,
            author="web-crawler",
        )
        entry_id = await store.store(entry)
        retrieved = await store.get(entry_id)
        assert retrieved is not None
        assert retrieved.source is EntrySource.EXTERNAL

    async def test_filter_entries_by_source(self, store: any) -> None:
        """Test filtering entries by source value."""
        # Create entries with different sources
        inference_entry = Entry(
            content="inference content",
            entry_type=EntryType.REFERENCE,
            source=EntrySource.INFERENCE,
            author="hook",
        )
        doc_entry = Entry(
            content="documentation content",
            entry_type=EntryType.REFERENCE,
            source=EntrySource.DOCUMENTATION,
            author="crawler",
        )
        manual_entry = Entry(
            content="manual content",
            entry_type=EntryType.REFERENCE,
            source=EntrySource.MANUAL,
            author="user",
        )

        await store.store(inference_entry)
        await store.store(doc_entry)
        await store.store(manual_entry)

        # Filter by inference source
        results = await store.list_entries(filters={"source": "inference"}, limit=100, offset=0)
        assert len(results) == 1
        assert results[0].source is EntrySource.INFERENCE

        # Filter by documentation source
        results = await store.list_entries(filters={"source": "documentation"}, limit=100, offset=0)
        assert len(results) == 1
        assert results[0].source is EntrySource.DOCUMENTATION

        # Filter by manual source (existing)
        results = await store.list_entries(filters={"source": "manual"}, limit=100, offset=0)
        assert len(results) == 1
        assert results[0].source is EntrySource.MANUAL

    async def test_search_entries_with_source_filter(self, store: any) -> None:
        """Test semantic search with source filtering."""
        # Create entries with different sources
        doc_entry = Entry(
            content="install python with pip package manager",
            entry_type=EntryType.REFERENCE,
            source=EntrySource.DOCUMENTATION,
            author="docs",
        )
        external_entry = Entry(
            content="install python with pip from stack overflow",
            entry_type=EntryType.REFERENCE,
            source=EntrySource.EXTERNAL,
            author="web",
        )

        await store.store(doc_entry)
        await store.store(external_entry)

        # Search for "install" with documentation source filter
        results = await store.search("install", filters={"source": "documentation"}, limit=10)
        assert len(results) > 0
        # All results should have documentation source
        for result in results:
            assert result.entry.source is EntrySource.DOCUMENTATION

    async def test_aggregate_by_source(self, store: any) -> None:
        """Test aggregating entries grouped by source."""
        # Create entries with different sources
        sources_and_counts = {
            EntrySource.INFERENCE: 2,
            EntrySource.DOCUMENTATION: 3,
            EntrySource.EXTERNAL: 1,
            EntrySource.MANUAL: 2,
        }

        for source, count in sources_and_counts.items():
            for i in range(count):
                entry = Entry(
                    content=f"{source.value} content {i}",
                    entry_type=EntryType.REFERENCE,
                    source=source,
                    author="test",
                )
                await store.store(entry)

        # Aggregate by source
        results = await store.aggregate_entries(group_by="source", filters=None, limit=100)
        assert results is not None
        assert "groups" in results

        # Verify that all source values appear in results
        source_groups = {g["value"] for g in results["groups"]}
        assert "inference" in source_groups
        assert "documentation" in source_groups
        assert "external" in source_groups
        assert "manual" in source_groups
