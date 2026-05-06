"""Tag selection helpers for the ``/radar`` skill.

The ``/radar`` skill builds an interest profile from curated entries and uses
the top tags as semantic-search seeds against feed entries.  Issue #460
documented that the original "top-N by combined count" rule consistently
collapsed to the same dominant tags — distinct conceptual clusters ranked
below position three were never seeded, no matter how heavily they appeared
in the knowledge base.

This module provides :func:`select_namespace_diverse_tags`, which picks the
top tag from each of the most-populated tag *namespaces* before taking the
overall top-N.  Tag namespaces are derived from the second segment of a
hierarchical tag path (``domain/build/hermeticity`` → namespace
``domain/build``).  Single-segment tags (``release``, ``feed``) namespace to
themselves.

The function is deterministic given a count map: ties on count are broken
alphabetically, both within namespaces (which tag wins the namespace) and
across namespaces (which namespace wins a slot).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping


def tag_namespace(tag: str) -> str:
    """Return the namespace portion of a hierarchical tag path.

    The namespace is *everything except the leaf segment*, capped at the
    first two segments.  That keeps the partition aligned with how
    Distillery's curated tags fan out:

    - ``domain/agents/eval`` → ``domain/agents`` (the ``domain/`` prefix is
      too coarse on its own — different sub-domains are different topics)
    - ``domain/build/hermeticity`` → ``domain/build``
    - ``tech/duckdb`` → ``tech`` (only one prefix segment present, so all
      ``tech/*`` tags share a single namespace)
    - ``release`` → ``release`` (single-segment tags namespace to
      themselves so they still compete for a slot)
    - ``a/b/c/d`` → ``a/b`` (cap at two segments)

    Examples
    --------
    >>> tag_namespace("domain/build/hermeticity")
    'domain/build'
    >>> tag_namespace("tech/duckdb")
    'tech'
    >>> tag_namespace("release")
    'release'
    """
    if not tag:
        return tag
    parts = tag.split("/")
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        # ``prefix/leaf`` — namespace is the prefix.
        return parts[0]
    # Three or more segments: namespace is the first two; everything from
    # the third segment onward is treated as leaf detail.
    return f"{parts[0]}/{parts[1]}"


def select_namespace_diverse_tags(
    tag_counts: Mapping[str, int | float],
    *,
    top_n: int = 3,
) -> list[str]:
    """Select up to ``top_n`` tags drawn from distinct namespaces.

    The selection rule:

    1. Group all tags by :func:`tag_namespace`.
    2. For each namespace, pick its highest-count tag (alphabetical
       tie-break) — this is the *namespace leader*.
    3. Rank namespaces by *aggregate* population (sum of counts across the
       namespace's tags), then by leader count, then alphabetically.  This
       matches the issue #460 spec ("most-populated namespaces") and
       prevents a broadly-populated namespace from losing to one with a
       single spiky tag.
    4. Return the namespace leaders of the top ``top_n`` namespaces.

    Parameters
    ----------
    tag_counts:
        Mapping of fully-qualified tag path to occurrence count (or any
        comparable numeric weight).
    top_n:
        Maximum number of namespace leaders to return.  Default ``3``.

    Returns
    -------
    list[str]
        Tag paths in descending namespace-rank order.  Empty if
        ``tag_counts`` is empty or ``top_n <= 0``.
    """
    if top_n <= 0 or not tag_counts:
        return []

    grouped: dict[str, list[tuple[str, int | float]]] = defaultdict(list)
    for tag, count in tag_counts.items():
        if not tag:
            continue
        grouped[tag_namespace(tag)].append((tag, count))

    leaders: list[tuple[str, str, int | float, int | float]] = []
    for ns, members in grouped.items():
        # Highest count first; alphabetical tag name as deterministic tie-break.
        members.sort(key=lambda item: (-item[1], item[0]))
        leader_tag, leader_count = members[0]
        namespace_total = sum(count for _tag, count in members)
        leaders.append((ns, leader_tag, leader_count, namespace_total))

    # Rank namespaces by aggregate population first, then leader count, then
    # deterministic alphabetical tie-breaks (namespace name, then leader tag).
    leaders.sort(key=lambda item: (-item[3], -item[2], item[0], item[1]))

    return [tag for _ns, tag, _leader_count, _ns_total in leaders[:top_n]]


__all__ = ["select_namespace_diverse_tags", "tag_namespace"]
