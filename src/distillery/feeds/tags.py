"""Shared tag sanitisation for feed adapters and skills.

Distillery tag grammar: ``[a-z0-9][a-z0-9-]*`` (lowercase alphanumeric plus
hyphens).  This module normalises external labels (GitHub, RSS, etc.) into
conforming tags.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

_TAG_RE = re.compile(r"[a-z0-9][a-z0-9\-]*")


def sanitise_label(label: str) -> str | None:
    """Return a Distillery-safe tag derived from an external label, or None.

    Normalisation steps:
    1. Lowercase
    2. Spaces and underscores become hyphens
    3. Consecutive hyphens collapsed
    4. Leading/trailing hyphens stripped

    Returns ``None`` if the result still doesn't match the tag grammar.
    """
    candidate = label.lower().replace(" ", "-").replace("_", "-")
    candidate = re.sub(r"-+", "-", candidate).strip("-")
    return candidate if _TAG_RE.fullmatch(candidate) else None


def normalize_tag(tag: str, reserved_prefixes: list[str]) -> str:
    """Collapse variant spellings of a reserved-prefix tag to a canonical form.

    When namespace enforcement is enabled (``tags.enforce_namespaces``), tags
    that share a reserved top-level prefix but differ only in how their
    sub-segments are separated should resolve to a single canonical tag so the
    same concept does not fragment across spellings (issue #628).  Examples
    (with ``reserved_prefixes`` containing ``"source"`` / ``"entity"``)::

        source/slack/links   -> source/slack-links
        source/slack-links   -> source/slack-links   (already canonical)
        source/slack-dms     -> source/slack-dms     (distinct concept, kept)
        entity/cloudflare/workers -> entity/cloudflare-workers

    The canonical form keeps the reserved top-level prefix verbatim and flattens
    everything after it into a single hyphen-joined leaf, treating ``/`` and
    ``-`` as equivalent separators.  Tags whose top-level segment is not a
    reserved prefix, or that have no sub-segment, are returned unchanged.

    Args:
        tag: The full tag path (already lowercased / sanitised).
        reserved_prefixes: Top-level prefixes eligible for normalisation, from
            :class:`~distillery.config.TagsConfig.reserved_prefixes`.

    Returns:
        The canonical tag string (unchanged when no normalisation applies).
    """
    if "/" not in tag:
        return tag
    top, remainder = tag.split("/", 1)
    if top not in reserved_prefixes or not remainder:
        return tag
    # Treat '/' and '-' after the prefix as equivalent separators; collapse the
    # remainder into a single hyphen-joined leaf so variant spellings converge.
    leaf = "-".join(seg for seg in re.split(r"[/-]+", remainder) if seg)
    if not leaf:
        return tag
    return f"{top}/{leaf}"


def canonicalize_tag(
    tag: str,
    *,
    aliases: Mapping[str, str] | None = None,
    reserved_prefixes: Sequence[str] = (),
    normalize_namespaces: bool = False,
) -> str:
    """Resolve a tag to its canonical form (issue #653, ontology #3).

    Two ordered steps, both optional:

    1. **Alias substitution** — when *tag* is a key in the (already chain-
       flattened) *aliases* map, replace it with its canonical target. A
       whole-tag dict lookup only; no substring or prefix matching, so an alias
       key ``domain/sand`` never affects ``domain/sandbox``.
    2. **Namespace normalization** — when *normalize_namespaces* is true, apply
       :func:`normalize_tag` so variant separator spellings of a reserved-prefix
       tag collapse (``entity/cloudflare/workers`` -> ``entity/cloudflare-workers``).

    Alias substitution runs first so an operator-declared merge wins over the
    mechanical separator-collapse. Idempotent given a flattened (chain-free,
    cycle-free) alias map: ``canonicalize_tag(canonicalize_tag(t)) ==
    canonicalize_tag(t)``. Grammar validation stays the caller's responsibility
    (the :class:`~distillery.models.Entry` constructor still validates tags).

    Args:
        tag: The full tag path (already lowercased / sanitised).
        aliases: Flattened ``alias -> canonical`` map (see
            :class:`~distillery.config.TagsConfig.aliases`). ``None`` / empty
            means no alias step.
        reserved_prefixes: Passed through to :func:`normalize_tag`.
        normalize_namespaces: When true, run the namespace-normalization step.

    Returns:
        The canonical tag string (unchanged when no rule applies).
    """
    result = tag
    if aliases:
        result = aliases.get(result, result)
    if normalize_namespaces:
        result = normalize_tag(result, list(reserved_prefixes))
    return result


def canonicalize_tags(
    tags: Iterable[str],
    *,
    aliases: Mapping[str, str] | None = None,
    reserved_prefixes: Sequence[str] = (),
    normalize_namespaces: bool = False,
) -> list[str]:
    """Canonicalize every tag and dedupe, preserving first-seen order.

    Thin batch wrapper over :func:`canonicalize_tag`. Because aliasing can map
    two distinct tags onto one canonical form, the dedupe is what collapses an
    entry that carries both an alias and its target down to a single tag.
    """
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        canonical = canonicalize_tag(
            t,
            aliases=aliases,
            reserved_prefixes=reserved_prefixes,
            normalize_namespaces=normalize_namespaces,
        )
        if canonical not in seen:
            seen.add(canonical)
            out.append(canonical)
    return out
