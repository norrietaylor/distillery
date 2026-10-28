"""Unit tests for the ``canonicalize_tags`` action of ``distillery_relations``.

Covers (issue #653, ontology #3):
  - happy path: rewrites stored tags through cfg.tags.aliases and returns counts
  - cfg=None: empty alias map -> no rewrites (no-op, safe default)
  - INTERNAL error when the store raises
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from distillery.mcp.tools.relations import _handle_relations
from tests.conftest import make_entry

pytestmark = pytest.mark.unit


async def _store_entry(store, **kwargs):  # type: ignore[no-untyped-def]
    entry = make_entry(**kwargs)
    await store.store(entry)
    return entry.id


def _parse(result: list) -> dict:  # type: ignore[type-arg]
    assert len(result) == 1
    return json.loads(result[0].text)  # type: ignore[no-any-return]


class _FakeTagsCfg:
    enforce_namespaces = False
    reserved_prefixes = ["kind"]
    aliases = {"domain/sandbox": "domain/build/sandboxing"}


class _FakeCfg:
    tags = _FakeTagsCfg()


async def test_canonicalize_tags_happy_path(store) -> None:  # type: ignore[no-untyped-def]
    """The backfill rewrites aliased tags and reports counts."""
    a = await _store_entry(store, content="frag", tags=["domain/sandbox", "tech/duckdb"])

    result = await _handle_relations(
        store,
        {"action": "canonicalize_tags"},
        cfg=_FakeCfg(),
    )
    data = _parse(result)

    assert data.get("error") is not True
    assert data["action"] == "canonicalize_tags"
    assert data["entries_scanned"] == 1
    assert data["entries_rewritten"] == 1
    assert data["tags_collapsed"] == 0

    entry = await store.get(a)
    assert set(entry.tags) == {"domain/build/sandboxing", "tech/duckdb"}


async def test_canonicalize_tags_no_aliases_is_noop(store) -> None:  # type: ignore[no-untyped-def]
    """With cfg=None (empty alias map), no entry is rewritten."""
    await _store_entry(store, content="x", tags=["domain/sandbox"])

    result = await _handle_relations(
        store,
        {"action": "canonicalize_tags"},
        cfg=None,
    )
    data = _parse(result)

    assert data.get("error") is not True
    assert data["entries_rewritten"] == 0


async def test_canonicalize_tags_internal_error(store) -> None:  # type: ignore[no-untyped-def]
    store.canonicalize_existing_tags = AsyncMock(side_effect=RuntimeError("boom"))

    result = await _handle_relations(
        store,
        {"action": "canonicalize_tags"},
        cfg=_FakeCfg(),
    )
    data = _parse(result)

    assert data["error"] is True
    assert data["code"] == "INTERNAL"
