"""Shared GitHub label → Distillery tag sanitiser.

Both the server-side feeds adapter (:mod:`distillery.feeds.github_sync`) and
the ``/gh-sync`` skill convert GitHub label names into Distillery tag
segments. They must agree on the rule so the two import paths produce the
same tag set on the same labels; see issue #241.

The sanitiser is intentionally lenient:

* ``github_actions`` (a default label on any repo using GitHub Actions) is
  coerced to ``github-actions`` rather than dropped, preserving the topical
  signal that underscore-variant labels carry.
* Labels that still fail Distillery's tag grammar after coercion return
  ``None`` so callers skip just that label rather than failing the whole
  entry.
"""

from __future__ import annotations

import re

from distillery.models import is_valid_tag_segment

_COLLAPSE_HYPHENS_RE = re.compile(r"-+")


def sanitize_label(label: str) -> str | None:
    """Return a Distillery-safe tag segment derived from *label*, or ``None``.

    The coercion is: lowercase, replace spaces and underscores with hyphens,
    collapse runs of hyphens, strip leading and trailing hyphens, then accept
    the result only if it matches Distillery's tag segment grammar
    (``[a-z0-9][a-z0-9-]*``).

    Examples::

        sanitize_label("bug")              == "bug"
        sanitize_label("github_actions")   == "github-actions"
        sanitize_label("High Priority")    == "high-priority"
        sanitize_label("CLA Signed")       == "cla-signed"
        sanitize_label("!!! urgent")       is None   # "!" is uncoercible
        sanitize_label("")                 is None

    Args:
        label: Raw label name as returned by the GitHub REST API.

    Returns:
        The sanitised tag segment, or ``None`` if no valid segment can be
        derived from *label*.
    """
    candidate = label.lower().replace(" ", "-").replace("_", "-")
    candidate = _COLLAPSE_HYPHENS_RE.sub("-", candidate).strip("-")
    if not candidate:
        return None
    return candidate if is_valid_tag_segment(candidate) else None
