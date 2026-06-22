"""Tests for ``distillery_ingest_doc`` — arbitrary document ingestion (issue #627).

Covers the acceptance criteria:

* A markdown ADR file and a customer-transcript file both become queryable
  entries carrying provenance (source metadata + doctype).
* Re-ingesting identical content is idempotent via the dedup key (content
  hash / external_id) — no second entry is created.
* Large text is chunked into multiple linked entries.
"""

from __future__ import annotations

import pytest

from distillery.mcp.tools.crud import (
    _DOC_CHUNK_CHARS,
    _content_hash,
    _handle_ingest_doc,
)
from distillery.store.duckdb import DuckDBStore
from tests.conftest import parse_mcp_response

pytestmark = pytest.mark.unit


_ADR = """# ADR 0007: Adopt DuckDB for the knowledge store

## Status
Accepted

## Context
We need an embedded analytical database with vector search support.

## Decision
Use DuckDB with the VSS extension for HNSW similarity search.
"""

_TRANSCRIPT = """Customer feedback call — Acme Corp, 2026-06-01

Acme wants faster onboarding and clearer error messages. They were confused
by the dedup warnings and asked for a way to bulk-import their existing specs.
"""


class TestIngestProvenance:
    async def test_adr_becomes_queryable_with_provenance(self, store: DuckDBStore) -> None:
        result = await _handle_ingest_doc(
            store=store,
            arguments={
                "text": _ADR,
                "author": "alice",
                "doctype": "adr",
                "source": "docs/adr/0007-duckdb.md",
                "title": "Adopt DuckDB",
                "project": "distillery",
            },
        )
        payload = parse_mcp_response(result)
        assert payload["persisted"] is True
        assert payload["dedup_action"] == "stored"
        assert payload["doctype"] == "adr"
        assert payload["count"] == 1

        entry_id = payload["entry_ids"][0]
        entry = await store.get(entry_id)
        assert entry is not None
        # Provenance: doctype tag + metadata carry source + doctype + title.
        assert "doctype/adr" in entry.tags
        assert entry.metadata["doctype"] == "adr"
        assert entry.metadata["source"] == "docs/adr/0007-duckdb.md"
        assert entry.metadata["title"] == "Adopt DuckDB"
        assert entry.project == "distillery"
        assert entry.metadata["external_id"] == _content_hash(_ADR)

        # Queryable via metadata filter and via list.
        listed = await store.list_entries(filters={"metadata.doctype": "adr"}, limit=10, offset=0)
        assert any(e.id == entry_id for e in listed)

    async def test_customer_transcript_becomes_queryable_feedback(
        self, store: DuckDBStore
    ) -> None:
        result = await _handle_ingest_doc(
            store=store,
            arguments={
                "text": _TRANSCRIPT,
                "author": "bob",
                "doctype": "feedback",
                "source": "drive://acme/2026-06-01-call.txt",
            },
        )
        payload = parse_mcp_response(result)
        assert payload["persisted"] is True
        assert payload["doctype"] == "feedback"

        entry = await store.get(payload["entry_ids"][0])
        assert entry is not None
        assert "doctype/feedback" in entry.tags
        assert entry.metadata["doctype"] == "feedback"
        assert entry.metadata["source"] == "drive://acme/2026-06-01-call.txt"

        # The feedback doc surfaces via semantic search.
        hits = await store.search(query="onboarding feedback", filters=None, limit=5)
        assert any(h.entry.id == entry.id for h in hits)


class TestIngestIdempotency:
    async def test_reingest_identical_content_is_idempotent(self, store: DuckDBStore) -> None:
        args = {
            "text": _ADR,
            "author": "alice",
            "doctype": "adr",
            "source": "docs/adr/0007-duckdb.md",
        }
        first = parse_mcp_response(await _handle_ingest_doc(store=store, arguments=dict(args)))
        assert first["persisted"] is True
        assert first["dedup_action"] == "stored"

        second = parse_mcp_response(await _handle_ingest_doc(store=store, arguments=dict(args)))
        assert second["persisted"] is False
        assert second["dedup_action"] == "skipped"
        # Same entry returned, no duplicate row created.
        assert second["entry_ids"] == first["entry_ids"]

        all_adrs = await store.list_entries(
            filters={"metadata.external_id": _content_hash(_ADR)}, limit=10, offset=0
        )
        assert len(all_adrs) == 1

    async def test_reingest_paginates_past_first_page(self, store: DuckDBStore) -> None:
        # A re-ingest of a doc that produced more chunks than one page must
        # return every existing entry_id, not just the first page's slice.
        from distillery.mcp.tools import crud as crud_mod
        from distillery.models import Entry, EntrySource, EntryType

        page_size = 500

        def _stub(idx: int) -> Entry:
            return Entry(
                content=f"chunk {idx}",
                entry_type=EntryType.REFERENCE,
                source=EntrySource.IMPORT,
                author="a",
                metadata={"external_id": "big-doc", "chunk_index": idx},
            )

        # Page 1: full (page_size rows) -> loop must request page 2.
        # Page 2: partial (1 row) -> loop stops, but only after accumulating it.
        all_entries = [_stub(i) for i in range(page_size + 1)]

        async def fake_list_entries(
            *, filters: object, limit: int, offset: int
        ) -> list[Entry]:
            return all_entries[offset : offset + limit]

        # type: ignore[method-assign] — monkeypatch the bound method for this test.
        store.list_entries = fake_list_entries  # type: ignore[assignment]

        payload = parse_mcp_response(
            await crud_mod._handle_ingest_doc(
                store=store,
                arguments={"text": "x", "author": "a", "external_id": "big-doc"},
            )
        )
        assert payload["persisted"] is False
        assert payload["count"] == page_size + 1
        assert len(payload["entry_ids"]) == page_size + 1

    async def test_explicit_external_id_dedups(self, store: DuckDBStore) -> None:
        # Different text but same external_id -> treated as same document.
        first = parse_mcp_response(
            await _handle_ingest_doc(
                store=store,
                arguments={"text": "version one", "author": "a", "external_id": "spec-42"},
            )
        )
        second = parse_mcp_response(
            await _handle_ingest_doc(
                store=store,
                arguments={"text": "version two", "author": "a", "external_id": "spec-42"},
            )
        )
        assert first["persisted"] is True
        assert second["persisted"] is False
        assert second["entry_ids"] == first["entry_ids"]


class TestIngestChunking:
    async def test_large_text_chunks_into_linked_entries(self, store: DuckDBStore) -> None:
        # Build text well over the chunk limit using paragraph boundaries.
        paragraph = "This is a paragraph about the design rationale. " * 30
        big_text = "\n\n".join(paragraph for _ in range(8))
        assert len(big_text) > _DOC_CHUNK_CHARS

        payload = parse_mcp_response(
            await _handle_ingest_doc(
                store=store,
                arguments={"text": big_text, "author": "alice", "doctype": "spec"},
            )
        )
        assert payload["chunked"] is True
        assert payload["count"] > 1
        ids = payload["entry_ids"]

        # Every chunk is a queryable entry carrying chunk provenance.
        for idx, eid in enumerate(ids):
            entry = await store.get(eid)
            assert entry is not None
            assert entry.metadata["chunk_index"] == idx
            assert entry.metadata["chunk_total"] == len(ids)
            assert "doctype/spec" in entry.tags

        # Chunks are linked from the head entry with relation_type="chunk".
        relations = await store.get_related(ids[0], direction="outgoing", relation_type="chunk")
        linked_ids = {r["to_id"] for r in relations}
        assert linked_ids == set(ids[1:])


class TestIngestValidation:
    async def test_missing_text_is_invalid(self, store: DuckDBStore) -> None:
        payload = parse_mcp_response(
            await _handle_ingest_doc(store=store, arguments={"author": "a"})
        )
        assert payload["error"] is True
        assert payload["code"] == "INVALID_PARAMS"

    async def test_empty_text_is_invalid(self, store: DuckDBStore) -> None:
        payload = parse_mcp_response(
            await _handle_ingest_doc(store=store, arguments={"text": "   ", "author": "a"})
        )
        assert payload["error"] is True
        assert payload["code"] == "INVALID_PARAMS"

    async def test_invalid_doctype_is_rejected(self, store: DuckDBStore) -> None:
        payload = parse_mcp_response(
            await _handle_ingest_doc(
                store=store,
                arguments={"text": "x", "author": "a", "doctype": "novel"},
            )
        )
        assert payload["error"] is True
        assert payload["code"] == "INVALID_PARAMS"
