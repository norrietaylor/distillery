"""Guard test: ``metadata.session_id`` round-trips through ``DuckDBStore.search()``.

The LongMemEval bench stores haystack sessions as entries with
``metadata={"session_id": "<haystack_id>"}`` and then maps each
``SearchResult.entry.metadata["session_id"]`` back to the gold answer set.
If the store ever drops or renames that key during the JSON round-trip,
the bench will silently report 0% recall — every result's session_id will
be missing and no comparison will match.

This test pins the round-trip behaviour so a regression in the metadata
serialisation layer (``store/duckdb.py::_row_to_entry``) is caught locally
before it can poison the published numbers.
"""

from __future__ import annotations

import pytest

from tests.conftest import make_entry

pytestmark = pytest.mark.unit


async def test_metadata_session_id_round_trips_via_search(store) -> None:  # type: ignore[no-untyped-def]
    """Storing ``metadata={"session_id": X}`` returns ``X`` from search.

    Steps:
      1. Store an entry whose metadata carries a ``session_id`` key.
      2. Run a semantic search whose query embedding hits the entry.
      3. Confirm the returned ``Entry.metadata["session_id"]`` equals the
         exact value supplied at store time (no coercion, no drop).
    """
    expected_session_id = "haystack-session-abc-123"
    entry = make_entry(
        content="A unique sentence about quokkas and cheese.",
        metadata={"session_id": expected_session_id},
    )

    entry_id = await store.store(entry)

    # Use the same content as the query so the mock provider produces an
    # identical hash-based vector and the entry surfaces as the top result.
    results = await store.search(
        query="A unique sentence about quokkas and cheese.",
        filters=None,
        limit=5,
    )

    matching = [r for r in results if r.entry.id == entry_id]
    assert matching, (
        f"Stored entry {entry_id!r} did not appear in search results; "
        f"got {[r.entry.id for r in results]!r}"
    )

    returned_metadata = matching[0].entry.metadata
    assert "session_id" in returned_metadata, (
        f"metadata.session_id was dropped during round-trip; "
        f"returned metadata keys: {list(returned_metadata.keys())!r}"
    )
    assert returned_metadata["session_id"] == expected_session_id, (
        f"metadata.session_id was altered during round-trip; "
        f"expected {expected_session_id!r}, got {returned_metadata['session_id']!r}"
    )


async def test_metadata_session_id_round_trips_via_get(store) -> None:  # type: ignore[no-untyped-def]
    """Defence-in-depth: same key survives ``get(entry_id)`` too.

    ``search()`` and ``get()`` share ``_row_to_entry`` but exercise
    slightly different SQL paths.  Pinning both keeps the bench safe if a
    future refactor splits them.
    """
    expected_session_id = "haystack-session-xyz-789"
    entry = make_entry(
        content="Round-trip via get, not search.",
        metadata={"session_id": expected_session_id, "extra": "preserved"},
    )

    entry_id = await store.store(entry)

    fetched = await store.get(entry_id)
    assert fetched is not None, f"Stored entry {entry_id!r} could not be fetched"
    assert fetched.metadata.get("session_id") == expected_session_id
    assert fetched.metadata.get("extra") == "preserved"
