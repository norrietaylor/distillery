"""Unit tests for the ``promote_entities`` action of ``distillery_relations``.

Covers:
  - happy path: returns entities_created, entities_reused, mentions_created, threshold
  - uses threshold from cfg when cfg is provided
  - falls back to default threshold (3) when cfg is None
  - INTERNAL error when store.promote_entities raises
  - action allow-list: unknown action still rejected correctly
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from distillery.mcp.tools.relations import _handle_relations
from tests.conftest import make_entry

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _store_entry(store, **kwargs):  # type: ignore[no-untyped-def]
    """Store a minimal entry and return its id."""
    entry = make_entry(**kwargs)
    await store.store(entry)
    return entry.id


def _parse(result: list) -> dict:  # type: ignore[type-arg]
    """Parse MCP TextContent list into a plain dict."""
    assert len(result) == 1
    return json.loads(result[0].text)  # type: ignore[no-any-return]


class _FakeTagsCfg:
    entity_promotion_threshold = 2
    reserved_prefixes = ["kind"]


class _FakeCfg:
    tags = _FakeTagsCfg()


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_promote_entities_happy_path(store) -> None:  # type: ignore[no-untyped-def]
    """promote_entities returns structured counts after creating nodes and edges."""
    for i in range(2):
        await _store_entry(store, content=f"e{i}", tags=["entity/acme"])

    result = await _handle_relations(
        store,
        {"action": "promote_entities"},
        cfg=_FakeCfg(),
    )
    data = _parse(result)

    assert data.get("error") is not True
    assert data["action"] == "promote_entities"
    assert data["entities_created"] == 1
    assert data["entities_reused"] == 0
    assert data["mentions_created"] == 2
    assert data["threshold"] == 2


async def test_promote_entities_uses_cfg_threshold(store) -> None:  # type: ignore[no-untyped-def]
    """The threshold read from cfg.tags.entity_promotion_threshold is used and echoed."""
    for i in range(2):
        await _store_entry(store, content=f"t{i}", tags=["tech/redis"])

    # threshold=2, so tech/redis (2 entries) should be promoted.
    result = await _handle_relations(
        store,
        {"action": "promote_entities"},
        cfg=_FakeCfg(),
    )
    data = _parse(result)

    assert data.get("error") is not True
    assert data["entities_created"] == 1
    assert data["threshold"] == 2  # echoes cfg value, not hardcoded 3


async def test_promote_entities_falls_back_to_default_threshold(store) -> None:  # type: ignore[no-untyped-def]
    """When cfg=None, threshold defaults to 3."""
    for i in range(3):
        await _store_entry(store, content=f"d{i}", tags=["entity/nomad"])

    result = await _handle_relations(
        store,
        {"action": "promote_entities"},
        cfg=None,
    )
    data = _parse(result)

    assert data.get("error") is not True
    assert data["threshold"] == 3
    assert data["entities_created"] == 1
    assert data["mentions_created"] == 3


async def test_promote_entities_idempotent(store) -> None:  # type: ignore[no-untyped-def]
    """A second run returns entities_reused>0 and mentions_created=0."""
    for i in range(2):
        await _store_entry(store, content=f"r{i}", tags=["entity/stripe"])

    await _handle_relations(store, {"action": "promote_entities"}, cfg=_FakeCfg())

    result = await _handle_relations(
        store,
        {"action": "promote_entities"},
        cfg=_FakeCfg(),
    )
    data = _parse(result)

    assert data.get("error") is not True
    assert data["entities_created"] == 0
    assert data["entities_reused"] == 1
    assert data["mentions_created"] == 0


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


async def test_promote_entities_internal_error(store) -> None:  # type: ignore[no-untyped-def]
    """An unexpected store error returns INTERNAL."""
    store.promote_entities = AsyncMock(side_effect=RuntimeError("boom"))

    result = await _handle_relations(
        store,
        {"action": "promote_entities"},
        cfg=None,
    )
    data = _parse(result)

    assert data["error"] is True
    assert data["code"] == "INTERNAL"


async def test_unknown_action_still_rejected() -> None:  # type: ignore[no-untyped-def]
    """An unrecognised action still returns INVALID_PARAMS (allow-list regression guard)."""
    result = await _handle_relations(
        None,  # store not needed — validation happens first
        {"action": "teleport"},
    )
    data = _parse(result)

    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "promote_entities" in data["message"]
