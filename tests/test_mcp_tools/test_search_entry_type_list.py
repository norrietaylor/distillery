"""Tests for ``distillery_search`` ``entry_type`` list support.

``_handle_search`` now accepts ``entry_type`` as either a single type string or
a list of types matched with OR (the store's IN-clause).  This mirrors the
``distillery_list`` precedent (PR #674) and unblocks /pour Pass 1a, which passes
a curated list of types to ``distillery_search``.

These tests exercise ``_handle_search`` directly against the shared in-memory
``store`` fixture (hash-based embeddings — every stored entry is an
unthresholded candidate, so the assertions are about which *types* survive the
filter, not ranking).
"""

from __future__ import annotations

from typing import Any

import pytest

from distillery.mcp.tools.search import _handle_search
from distillery.models import EntryType
from tests.conftest import make_entry, parse_mcp_response


@pytest.fixture
async def store_with_mixed_types(store: Any) -> Any:  # type: ignore[return]
    """Store with one entry per curated type plus an excluded ``inbox`` entry.

    Curated (mined by /pour Pass 1a): session, reference, bookmark, idea,
    minutes.  The non-curated ``inbox`` entry must never appear when filtering
    by the curated list (proves the IN-clause excludes other types).
    """
    entries = [
        make_entry(content="s", entry_type=EntryType.SESSION),
        make_entry(content="r", entry_type=EntryType.REFERENCE),
        make_entry(content="b", entry_type=EntryType.BOOKMARK),
        make_entry(content="i", entry_type=EntryType.IDEA),
        make_entry(content="m", entry_type=EntryType.MINUTES),
        make_entry(content="x", entry_type=EntryType.INBOX),
    ]
    for e in entries:
        await store.store(e)
    return store


@pytest.mark.integration
class TestSearchEntryTypeList:
    async def test_entry_type_list_or_match(self, store_with_mixed_types: Any) -> None:
        """A list of entry_types matches entries of EITHER type (OR / IN-clause)."""
        result = await _handle_search(
            store=store_with_mixed_types,
            arguments={
                "query": "anything",
                "entry_type": ["session", "reference"],
                "limit": 50,
                "output_mode": "full",
            },
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        returned_types = {hit["entry"]["entry_type"] for hit in data["results"]}
        assert returned_types == {"session", "reference"}

    async def test_curated_list_excludes_other_types(self, store_with_mixed_types: Any) -> None:
        """The full curated /pour list returns only those types, never inbox."""
        result = await _handle_search(
            store=store_with_mixed_types,
            arguments={
                "query": "anything",
                "entry_type": ["session", "bookmark", "minutes", "reference", "idea"],
                "limit": 50,
                "output_mode": "full",
            },
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        returned_types = {hit["entry"]["entry_type"] for hit in data["results"]}
        assert returned_types == {"session", "bookmark", "minutes", "reference", "idea"}
        assert "inbox" not in returned_types

    async def test_single_string_entry_type_still_works(self, store_with_mixed_types: Any) -> None:
        """Backward compat: a plain string entry_type filters to that one type."""
        result = await _handle_search(
            store=store_with_mixed_types,
            arguments={
                "query": "anything",
                "entry_type": "session",
                "limit": 50,
                "output_mode": "full",
            },
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        returned_types = {hit["entry"]["entry_type"] for hit in data["results"]}
        assert returned_types == {"session"}


# Kept out of the integration-marked TestSearchEntryTypeList (uses the bare
# ``store`` fixture, no mixed-type data) so it carries a single ``unit`` marker
# rather than being double-selected by both ``-m unit`` and ``-m integration``.
@pytest.mark.unit
async def test_empty_entry_type_list_returns_error(store: Any) -> None:
    result = await _handle_search(
        store=store,
        arguments={"query": "anything", "entry_type": [], "limit": 50},
    )
    data = parse_mcp_response(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
