"""Tests for ``distillery_search`` output_mode shaping (issue #631).

``_handle_search`` gained an ``output_mode`` param mirroring the
``distillery_list`` precedent (#78):

  - "summary" (default): score + compact entry (id/title/~200-char
    content_preview, NO full content body)
  - "full": score + full entry (pre-#631 behaviour, back-compat escape hatch)
  - "ids": score + id only

These tests exercise ``_handle_search`` directly against the shared in-memory
``store`` fixture (hash-based embeddings — every stored entry is an
unthresholded candidate, which is sufficient since we assert on shaping, not
ranking).
"""

from __future__ import annotations

import json

import pytest

from distillery.mcp.tools.search import _handle_search
from distillery.models import EntryType
from tests.conftest import make_entry, parse_mcp_response

pytestmark = pytest.mark.unit


# A body comfortably longer than the 200-char summary preview so we can assert
# the preview is truncated and the full body is omitted in summary mode.
_LONG_BODY = "Distillery output mode body sentence. " * 30


async def _store_long_entry(store, content: str = _LONG_BODY) -> str:
    entry = make_entry(content=content, entry_type=EntryType.INBOX)
    await store.store(entry)
    return entry.id


def _payload_size(response) -> int:  # type: ignore[no-untyped-def]
    """Serialised byte size of the MCP text payload (proxy for token cost)."""
    return len(response[0].text)


# ---------------------------------------------------------------------------
# Default (summary) shape
# ---------------------------------------------------------------------------


async def test_default_output_mode_is_summary(store) -> None:  # type: ignore[no-untyped-def]
    """Default search returns id/title/preview/score and NOT full content."""
    await _store_long_entry(store)

    response = await _handle_search(store, {"query": "anything"})
    data = parse_mcp_response(response)

    assert data["count"] >= 1
    hit = data["results"][0]

    # score present on the hit
    assert "score" in hit
    # compact entry: id + title + content_preview, NO full content body
    entry = hit["entry"]
    assert "id" in entry
    assert "title" in entry
    assert "content_preview" in entry
    assert "content" not in entry
    # preview is truncated to ~200 chars (+ ellipsis) — strictly shorter than body
    assert len(entry["content_preview"]) <= 201
    assert len(entry["content_preview"]) < len(_LONG_BODY)


# ---------------------------------------------------------------------------
# full mode == pre-#631 behaviour
# ---------------------------------------------------------------------------


async def test_output_mode_full_returns_full_content(store) -> None:  # type: ignore[no-untyped-def]
    """output_mode=full reproduces the current behaviour: full content per hit."""
    await _store_long_entry(store)

    response = await _handle_search(store, {"query": "anything", "output_mode": "full"})
    data = parse_mcp_response(response)

    hit = data["results"][0]
    entry = hit["entry"]
    # full mode carries the complete content body verbatim
    assert entry["content"] == _LONG_BODY
    # and is shaped exactly like the legacy {score, entry: to_dict()} pair
    assert set(hit.keys()) == {"score", "entry"}


# ---------------------------------------------------------------------------
# ids mode
# ---------------------------------------------------------------------------


async def test_output_mode_ids_returns_id_and_score_only(store) -> None:  # type: ignore[no-untyped-def]
    """output_mode=ids returns id + score only (no entry body)."""
    entry_id = await _store_long_entry(store)

    response = await _handle_search(store, {"query": "anything", "output_mode": "ids"})
    data = parse_mcp_response(response)

    hit = data["results"][0]
    assert set(hit.keys()) == {"score", "id"}
    assert hit["id"] == entry_id
    assert "entry" not in hit


# ---------------------------------------------------------------------------
# token reduction: summary payload is materially smaller than full
# ---------------------------------------------------------------------------


async def test_summary_payload_smaller_than_full(store) -> None:  # type: ignore[no-untyped-def]
    """A multi-hit summary search is materially smaller than the full payload."""
    for _ in range(5):
        await _store_long_entry(store)

    summary_resp = await _handle_search(store, {"query": "anything", "output_mode": "summary"})
    full_resp = await _handle_search(store, {"query": "anything", "output_mode": "full"})

    summary_data = parse_mcp_response(summary_resp)
    full_data = parse_mcp_response(full_resp)

    # Same number of hits in both modes (ranking unchanged).
    assert summary_data["count"] == full_data["count"] >= 5
    # Summary mode returns materially fewer characters than full mode.
    assert _payload_size(summary_resp) < _payload_size(full_resp)


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


async def test_invalid_output_mode_rejected(store) -> None:  # type: ignore[no-untyped-def]
    """An unknown output_mode value yields INVALID_PARAMS."""
    response = await _handle_search(store, {"query": "anything", "output_mode": "bogus"})
    payload = json.loads(response[0].text)
    assert payload["error"] is True
    assert payload["code"] == "INVALID_PARAMS"


async def test_output_mode_review_rejected(store) -> None:  # type: ignore[no-untyped-def]
    """``review`` is a list-only mode and is rejected for search."""
    response = await _handle_search(store, {"query": "anything", "output_mode": "review"})
    payload = json.loads(response[0].text)
    assert payload["error"] is True
    assert payload["code"] == "INVALID_PARAMS"
