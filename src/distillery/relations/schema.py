"""Typed relation schema for the knowledge graph (issue #653, ontology #1).

Single source of truth for two things:

1. ``VALID_RELATION_TYPES`` — the closed vocabulary of relation-type *names*.
   This replaces the two duplicated copies that previously lived in
   ``store/duckdb.py`` and ``mcp/tools/relations.py``.
2. ``RELATION_SCHEMA`` — the legal ``(from_type, relation, to_type)`` triples,
   i.e. which entry types may sit on either end of each relation. ``"*"`` is a
   wildcard matching any (current or future) entry type; multi-target unions
   (the epic's ``session -> citation -> reference|bookmark``) are expressed as
   multiple rows rather than a special union object, so membership is a plain
   set lookup.

The validator is a pure function callable from both the async ``add_relation``
path and the synchronous raw-SQL writers, so a single schema governs every edge
creator.

Design note — the initial table is deliberately wildcard-heavy for the
corpus-wide *semantic* relations (``related``, ``link``, ``citation``,
``duplicate``, ``merge_source``) and the curation relations. Those are created
by auto-link / reconcile / suggest_links / find_similar over arbitrary type
pairs, so narrowing them would retroactively outlaw existing edges and sabotage
the very writers epic #653 is turning on. Only the relations the epic wants
*structurally* constrained get narrow triples. The unions can be tightened in a
later hardening step once the real type-pair distribution is known (use
``audit_relation_schema`` on the store to surface it).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Wildcard endpoint — matches any entry type, including types added later.
WILDCARD = "*"

#: Closed vocabulary of relation-type names (single source of truth).
VALID_RELATION_TYPES: frozenset[str] = frozenset(
    {
        "link",
        "corrects",
        "supersedes",
        "related",
        "blocks",
        "depends_on",
        "citation",
        "duplicate",
        "merge_source",
        "sync_source",
        "mentions",
        "chunk",
    }
)

#: Legal ``(from_type, relation, to_type)`` triples. ``WILDCARD`` on either end
#: matches any entry type. Derived so that nothing currently created by a real
#: edge writer becomes illegal (see module docstring).
RELATION_SCHEMA: frozenset[tuple[str, str, str]] = frozenset(
    {
        # --- gh-sync structural & cross-reference edges ---
        ("github", "depends_on", "github"),  # sub-issue -> epic
        ("github", "citation", "github"),  # PR -> issue
        ("github", "link", "github"),  # generic cross-ref
        # --- epic-named narrow examples ---
        ("session", "citation", "reference"),  # session -> citation -> reference|bookmark
        ("session", "citation", "bookmark"),
        ("feed", "related", "project"),
        # --- mentions -> person|entity (epic example + promote_entities) ---
        # promote_entities writes ANY from-type -> entity, so the from side is
        # wildcard to grandfather every member entry.
        (WILDCARD, "mentions", "person"),
        (WILDCARD, "mentions", "entity"),
        # --- chunk: structural doc-split linking, any -> any ---
        (WILDCARD, "chunk", WILDCARD),
        # --- corpus-wide semantic / dedup relations (see module docstring) ---
        (WILDCARD, "related", WILDCARD),
        (WILDCARD, "link", WILDCARD),
        (WILDCARD, "citation", WILDCARD),
        (WILDCARD, "duplicate", WILDCARD),
        (WILDCARD, "merge_source", WILDCARD),
        # --- curation / manual relations (no automated writer today) ---
        (WILDCARD, "supersedes", WILDCARD),
        (WILDCARD, "corrects", WILDCARD),
        (WILDCARD, "blocks", WILDCARD),
        (WILDCARD, "sync_source", WILDCARD),
    }
)


class RelationSchemaError(ValueError):
    """Raised when a ``(from_type, relation, to_type)`` triple is not allowed.

    Subclasses :class:`ValueError` so existing ``except ValueError`` handlers in
    the MCP relation tool surface it as a clean error response.
    """


def triple_allowed(from_type: str, relation_type: str, to_type: str) -> bool:
    """Return whether the triple is permitted by ``RELATION_SCHEMA``.

    Checks the four wildcard combinations (exact, from-wild, to-wild, both-wild)
    so a single membership helper is fully symmetric.
    """
    return (
        (from_type, relation_type, to_type) in RELATION_SCHEMA
        or (WILDCARD, relation_type, to_type) in RELATION_SCHEMA
        or (from_type, relation_type, WILDCARD) in RELATION_SCHEMA
        or (WILDCARD, relation_type, WILDCARD) in RELATION_SCHEMA
    )


def validate_relation_triple(
    from_type: str,
    relation_type: str,
    to_type: str,
    *,
    enforce: bool = True,
) -> None:
    """Validate an edge against the relation ontology.

    The relation-type *name* check is unconditional — an unknown ``relation_type``
    always raises :class:`RelationSchemaError` regardless of *enforce* (a typo'd
    type is never legitimate). The *triple* (endpoint-pairing) check is gated by
    *enforce*: when ``True`` an illegal triple raises; when ``False`` (warn-only
    mode) it logs a WARNING and returns, giving operators a migration window
    before strict enforcement is switched on.
    """
    if relation_type not in VALID_RELATION_TYPES:
        raise RelationSchemaError(
            f"Invalid relation_type {relation_type!r}. "
            f"Must be one of: {', '.join(sorted(VALID_RELATION_TYPES))}."
        )
    if triple_allowed(from_type, relation_type, to_type):
        return
    msg = (
        f"Relation schema violation: ({from_type!r}, {relation_type!r}, "
        f"{to_type!r}) is not an allowed (from_type, relation, to_type) triple."
    )
    if enforce:
        raise RelationSchemaError(msg)
    logger.warning("%s (warn-only mode — edge allowed)", msg)
