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
