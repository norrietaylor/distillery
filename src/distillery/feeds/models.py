"""Shared data model for normalised feed items.

All feed adapters produce :class:`FeedItem` instances so that downstream
consumers (scorer, poller) work with a single canonical structure regardless
of the originating source type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class FeedItem:
    """A single normalised item fetched from a monitored feed source.

    All fields that are not available from a particular source are left as
    ``None`` or an empty collection; adapters must never fabricate data.

    Attributes:
        source_url: The canonical URL of the feed itself (not the item).
        source_type: Adapter type.  One of ``'rss'`` or ``'github'``.
        item_id: A stable identifier for this item within the source (e.g.
            GitHub event id, RSS ``<guid>`` value).  Used to detect duplicates
            across polls.
        title: Short human-readable title for the item, when available.
        url: URL pointing directly to the item (article, event page, etc.).
        content: Full or summarised body text of the item.  May be ``None``
            when the source only provides a title/link.
        author: The original content creator (e.g. GitHub username, RSS
            author element).  ``None`` when the source does not provide
            author information.
        published_at: Publication or event creation timestamp.  ``None`` if
            not provided by the source.
        raw: The original parsed object (dict for JSON sources, element for
            XML sources) preserved for debugging.  Not included in equality
            comparisons.
        extra: Adapter-specific key/value pairs that do not fit the standard
            fields above (e.g. GitHub event type, RSS category list).
    """

    source_url: str
    source_type: str
    item_id: str
    title: str | None = None
    url: str | None = None
    content: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    raw: Any = field(default=None, compare=False, repr=False)
    extra: dict[str, Any] = field(default_factory=dict)
