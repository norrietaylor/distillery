"""Unit tests for tag canonicalization (issue #653, ontology #3).

Covers the pure ``canonicalize_tag`` / ``canonicalize_tags`` helpers in
``distillery.feeds.tags``: alias substitution, precedence over namespace
normalization, idempotency, substring safety, and order-preserving dedupe.
"""

from __future__ import annotations

import pytest

from distillery.feeds.tags import canonicalize_tag, canonicalize_tags

pytestmark = pytest.mark.unit


def test_alias_collapse() -> None:
    aliases = {"domain/sandbox": "domain/build/sandboxing"}
    assert canonicalize_tag("domain/sandbox", aliases=aliases) == "domain/build/sandboxing"


def test_alias_wins_over_namespace_normalize() -> None:
    """Alias substitution runs before the separator-collapse, so an operator
    merge wins over the mechanical normalization."""
    aliases = {"entity/cloudflare/sandboxes": "entity/cloudflare"}
    result = canonicalize_tag(
        "entity/cloudflare/sandboxes",
        aliases=aliases,
        reserved_prefixes=["entity"],
        normalize_namespaces=True,
    )
    # Alias fires first -> entity/cloudflare, NOT entity/cloudflare-sandboxes.
    assert result == "entity/cloudflare"


def test_namespace_normalize_without_matching_alias() -> None:
    """With no matching alias, the namespace-collapse still applies."""
    result = canonicalize_tag(
        "entity/cloudflare/workers",
        reserved_prefixes=["entity"],
        normalize_namespaces=True,
    )
    assert result == "entity/cloudflare-workers"


def test_no_op_for_unknown_tag() -> None:
    assert canonicalize_tag("project/billing", aliases={"x": "y"}) == "project/billing"


def test_namespace_normalize_off_by_default() -> None:
    """Without normalize_namespaces, the separator-collapse does not run."""
    assert canonicalize_tag("entity/cloudflare/workers") == "entity/cloudflare/workers"


def test_substring_alias_does_not_fire() -> None:
    """Whole-tag match only: an alias key must not match a longer tag."""
    aliases = {"domain/sand": "domain/build/sandboxing"}
    assert canonicalize_tag("domain/sandbox", aliases=aliases) == "domain/sandbox"


def test_idempotent_with_flattened_map() -> None:
    """Given a flattened (single-hop) map, canonicalization is idempotent."""
    aliases = {"domain/sandbox": "domain/build/sandboxing"}
    once = canonicalize_tag("domain/sandbox", aliases=aliases)
    twice = canonicalize_tag(once, aliases=aliases)
    assert once == twice == "domain/build/sandboxing"


def test_canonicalize_tags_dedupes_preserving_order() -> None:
    """Aliasing two tags onto one canonical form collapses to a single tag,
    keeping first-seen order."""
    aliases = {"domain/sandbox": "domain/build/sandboxing"}
    result = canonicalize_tags(
        ["tech/duckdb", "domain/sandbox", "domain/build/sandboxing"],
        aliases=aliases,
    )
    assert result == ["tech/duckdb", "domain/build/sandboxing"]


def test_canonicalize_tags_empty() -> None:
    assert canonicalize_tags([]) == []
