"""Shared tag sanitisation for feed adapters and skills.

Distillery tag grammar: ``[a-z0-9][a-z0-9-]*`` (lowercase alphanumeric plus
hyphens).  This module normalises external labels (GitHub, RSS, etc.) into
conforming tags.
"""

from __future__ import annotations

import re

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
