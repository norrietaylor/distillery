"""Tests for the typed relation schema (issue #653, ontology #1).

Covers the pure validator in ``distillery.relations.schema`` plus its
integration into the store's ``add_relation`` write path and the read-only
``audit_relation_schema`` / MCP ``audit_schema`` action.
"""

from __future__ import annotations

import json

import pytest

from distillery.models import EntryType
from distillery.relations.schema import (
    VALID_RELATION_TYPES,
    RelationSchemaError,
    triple_allowed,
    validate_relation_triple,
)
from tests.conftest import make_entry

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Pure validator
# ---------------------------------------------------------------------------


def test_exact_triple_allowed() -> None:
    assert triple_allowed("github", "depends_on", "github") is True


def test_wildcard_from_match() -> None:
    # (*, mentions, entity) covers any from-type.
    assert triple_allowed("session", "mentions", "entity") is True


def test_wildcard_to_match() -> None:
    # (*, chunk, *) covers any endpoints.
    assert triple_allowed("session", "chunk", "reference") is True


def test_illegal_triple_rejected_in_strict() -> None:
    """depends_on is constrained to github->github; session->session is illegal."""
    with pytest.raises(RelationSchemaError):
        validate_relation_triple("session", "depends_on", "session", enforce=True)


def test_mentions_to_non_entity_rejected_in_strict() -> None:
    with pytest.raises(RelationSchemaError):
        validate_relation_triple("session", "mentions", "session", enforce=True)


def test_unknown_relation_type_always_raises() -> None:
    """An unknown relation_type is a hard error even in warn-only mode."""
    with pytest.raises(RelationSchemaError):
        validate_relation_triple("session", "teleports_to", "session", enforce=False)


def test_warn_mode_allows_illegal_triple(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with caplog.at_level(logging.WARNING):
        # Must not raise.
        validate_relation_triple("session", "depends_on", "session", enforce=False)
    assert any("schema violation" in r.message.lower() for r in caplog.records)


def test_valid_relation_types_shared_identity() -> None:
    """The store and MCP layers must reference the one schema vocabulary."""
    from distillery.mcp.tools import relations as mcp_rel
    from distillery.store import duckdb as store_mod

    assert mcp_rel._VALID_RELATION_TYPES is VALID_RELATION_TYPES
    assert store_mod._VALID_RELATION_TYPES is VALID_RELATION_TYPES


# ---------------------------------------------------------------------------
# Store integration: add_relation enforcement
# ---------------------------------------------------------------------------


async def _store_entry(store, **kwargs):  # type: ignore[no-untyped-def]
    entry = make_entry(**kwargs)
    await store.store(entry)
    return entry.id


async def test_add_relation_warn_mode_allows_illegal(store) -> None:  # type: ignore[no-untyped-def]
    """Default (warn-only) store inserts an illegal triple and logs."""
    a = await _store_entry(store, content="a")  # inbox
    b = await _store_entry(store, content="b")  # inbox
    rid = await store.add_relation(a, b, "depends_on")  # (inbox, depends_on, inbox) illegal
    assert rid
    related = await store.get_related(a, relation_type="depends_on")
    assert len(related) == 1


async def test_add_relation_strict_rejects_illegal(store) -> None:  # type: ignore[no-untyped-def]
    """With enforce on, an illegal triple raises and inserts nothing."""
    store._enforce_relation_schema = True
    a = await _store_entry(store, content="a")
    b = await _store_entry(store, content="b")
    with pytest.raises(ValueError):
        await store.add_relation(a, b, "depends_on")
    related = await store.get_related(a, relation_type="depends_on")
    assert related == []


async def test_add_relation_strict_allows_legal(store) -> None:  # type: ignore[no-untyped-def]
    """A legal triple inserts cleanly under strict enforcement."""
    store._enforce_relation_schema = True
    a = await _store_entry(
        store,
        content="pr",
        entry_type=EntryType.GITHUB,
        metadata={"repo": "o/r", "ref_type": "pr", "ref_number": 1},
    )
    b = await _store_entry(
        store,
        content="issue",
        entry_type=EntryType.GITHUB,
        metadata={"repo": "o/r", "ref_type": "issue", "ref_number": 2},
    )
    rid = await store.add_relation(a, b, "depends_on")  # github->depends_on->github
    assert rid


async def test_reassert_of_illegal_edge_skips_validation(store) -> None:  # type: ignore[no-untyped-def]
    """An edge created in warn mode can be re-asserted (attribute upsert) under
    strict mode without raising — only NEW inserts are validated."""
    a = await _store_entry(store, content="a")
    b = await _store_entry(store, content="b")
    rid = await store.add_relation(a, b, "depends_on")  # warn mode: inserted

    store._enforce_relation_schema = True
    # Re-assert with a fresh attribute — must NOT raise despite the illegal triple.
    rid2 = await store.add_relation(a, b, "depends_on", weight=0.5)
    assert rid2 == rid


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


async def test_audit_relation_schema_reports_violations(store) -> None:  # type: ignore[no-untyped-def]
    """The audit surfaces existing illegal edges grouped with counts."""
    a = await _store_entry(store, content="a")  # inbox
    b = await _store_entry(store, content="b")  # inbox
    await store.add_relation(a, b, "depends_on")  # illegal (inbox->inbox)

    violations = await store.audit_relation_schema()
    assert len(violations) == 1
    v = violations[0]
    assert v["from_type"] == "inbox"
    assert v["relation_type"] == "depends_on"
    assert v["to_type"] == "inbox"
    assert v["count"] == 1


async def test_audit_relation_schema_clean_when_only_legal(store) -> None:  # type: ignore[no-untyped-def]
    a = await _store_entry(store, content="a")
    b = await _store_entry(store, content="b")
    await store.add_relation(a, b, "related")  # (*, related, *) is allowed

    violations = await store.audit_relation_schema()
    assert violations == []


# ---------------------------------------------------------------------------
# MCP action: audit_schema
# ---------------------------------------------------------------------------


async def test_mcp_audit_schema_action(store) -> None:  # type: ignore[no-untyped-def]
    from distillery.mcp.tools.relations import _handle_relations

    a = await _store_entry(store, content="a")
    b = await _store_entry(store, content="b")
    await store.add_relation(a, b, "depends_on")  # illegal

    result = await _handle_relations(store, {"action": "audit_schema"})
    data = json.loads(result[0].text)

    assert data.get("error") is not True
    assert data["action"] == "audit_schema"
    assert data["clean"] is False
    assert data["count"] == 1
    assert data["violations"][0]["relation_type"] == "depends_on"
