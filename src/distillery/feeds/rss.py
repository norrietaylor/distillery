"""RSS 2.0 and Atom feed adapter.

Fetches a feed URL with :mod:`httpx`, parses the XML body using the standard
library :mod:`xml.etree.ElementTree`, and normalises each entry to a
:class:`~distillery.feeds.models.FeedItem`.

Both RSS 2.0 and Atom 1.0 formats are supported.  The adapter detects the
format by inspecting the root element tag.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as DefusedElementTree
import httpx

from distillery.feeds.models import FeedItem

logger = logging.getLogger(__name__)

# Atom namespace URI.
_ATOM_NS = "http://www.w3.org/2005/Atom"

# Dublin Core namespace (used for <dc:creator> in RSS feeds).
_DC_NS = "http://purl.org/dc/elements/1.1/"

# Request timeout in seconds.
_REQUEST_TIMEOUT = 30.0

# Reddit subreddit URL pattern — matches /r/<name>/ or /r/<name>
_REDDIT_SUBREDDIT_RE = re.compile(
    r"^https?://(?:(?:www|old)\.)?reddit\.com/r/[^/]+/?$",
    re.IGNORECASE,
)

# User-Agent that Reddit will accept (requires a descriptive bot string).
_REDDIT_USER_AGENT = "Distillery/0.1 (RSS feed reader; https://github.com/norrietaylor/distillery)"


def _normalise_feed_url(url: str) -> tuple[str, dict[str, str]]:
    """Normalise a feed URL and return ``(url, extra_headers)``.

    Applies domain-specific transformations:

    - **Reddit**: Appends ``.rss`` to bare subreddit URLs and uses a
      descriptive User-Agent (Reddit blocks generic bots).

    Args:
        url: The raw feed URL.

    Returns:
        A tuple of the (possibly rewritten) URL and any extra HTTP headers
        to include in the request.
    """
    extra_headers: dict[str, str] = {}
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    # Reddit: /r/SubName/ → /r/SubName/.rss
    if host in ("reddit.com", "www.reddit.com", "old.reddit.com"):
        extra_headers["User-Agent"] = _REDDIT_USER_AGENT
        if _REDDIT_SUBREDDIT_RE.match(url) and not url.rstrip("/").endswith(".rss"):
            url = url.rstrip("/") + "/.rss"

    return url, extra_headers


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _text(element: Element | None, tag: str, ns: str | None = None) -> str | None:
    """Return stripped text of the first child matching *tag*, or ``None``.

    Args:
        element: Parent element to search within.
        tag: Local tag name (without namespace prefix).
        ns: Optional XML namespace URI.

    Returns:
        Stripped text content, or ``None`` if not found or empty.
    """
    if element is None:
        return None
    qualified = f"{{{ns}}}{tag}" if ns else tag
    child = element.find(qualified)
    if child is not None and child.text:
        stripped = child.text.strip()
        return stripped if stripped else None
    return None


def _attr(element: Element | None, tag: str, attr: str, ns: str | None = None) -> str | None:
    """Return an attribute value from the first child matching *tag*, or ``None``.

    Args:
        element: Parent element to search within.
        tag: Local tag name (without namespace prefix).
        attr: Attribute name.
        ns: Optional XML namespace URI.

    Returns:
        Attribute value, or ``None`` if not found.
    """
    if element is None:
        return None
    qualified = f"{{{ns}}}{tag}" if ns else tag
    child = element.find(qualified)
    if child is not None:
        return child.get(attr)
    return None


def _parse_rfc822_date(raw: str) -> datetime | None:
    """Parse an RFC 2822 date string (used in RSS 2.0) to a UTC datetime.

    Args:
        raw: Date string (e.g. ``"Mon, 25 Mar 2024 12:00:00 +0000"``).

    Returns:
        Timezone-aware :class:`~datetime.datetime`, or ``None`` on failure.
    """
    try:
        dt = parsedate_to_datetime(raw)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _parse_iso8601_date(raw: str) -> datetime | None:
    """Parse an ISO 8601 date string (used in Atom) to a UTC datetime.

    Args:
        raw: Date string (e.g. ``"2024-03-25T12:00:00Z"`` or with offset).

    Returns:
        Timezone-aware :class:`~datetime.datetime`, or ``None`` on failure.
    """
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _stable_id(source_url: str, fallback_content: str) -> str:
    """Derive a stable item id from source URL and some fallback content.

    Used when a feed item has no ``<guid>`` or ``<id>`` element.

    Args:
        source_url: Feed source URL.
        fallback_content: Any string that uniquely identifies the item
            (e.g. item link + title).

    Returns:
        A hex string SHA-256 digest (first 16 characters).
    """
    digest = hashlib.sha256(f"{source_url}\x00{fallback_content}".encode()).hexdigest()
    return digest[:16]


# ---------------------------------------------------------------------------
# RSS 2.0 parser
# ---------------------------------------------------------------------------


def _parse_rss_item(item: Element, source_url: str) -> FeedItem:
    """Convert a single RSS 2.0 ``<item>`` element to a :class:`FeedItem`.

    Args:
        item: The ``<item>`` XML element.
        source_url: Canonical feed URL.

    Returns:
        A normalised :class:`FeedItem`.
    """
    title = _text(item, "title")
    link = _text(item, "link")
    description = _text(item, "description")
    guid = _text(item, "guid")
    pub_date_raw = _text(item, "pubDate")

    # Author: try <author>, then <dc:creator>.
    author = _text(item, "author") or _text(item, "creator", _DC_NS)

    item_id = guid or _stable_id(source_url, f"{link or ''}{title or ''}")
    published_at = _parse_rfc822_date(pub_date_raw) if pub_date_raw else None

    # Categories
    categories: list[str] = []
    for cat_el in item.findall("category"):
        if cat_el.text:
            stripped = cat_el.text.strip()
            if stripped:
                categories.append(stripped)

    extra: dict[str, Any] = {}
    if categories:
        extra["categories"] = categories

    return FeedItem(
        source_url=source_url,
        source_type="rss",
        item_id=item_id,
        title=title,
        url=link,
        content=description,
        author=author,
        published_at=published_at,
        raw=item,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Atom parser
# ---------------------------------------------------------------------------


def _parse_atom_entry(entry: Element, source_url: str) -> FeedItem:
    """Convert a single Atom ``<entry>`` element to a :class:`FeedItem`.

    Args:
        entry: The ``<entry>`` XML element (Atom namespace).
        source_url: Canonical feed URL.

    Returns:
        A normalised :class:`FeedItem`.
    """
    ns = _ATOM_NS
    title = _text(entry, "title", ns)
    atom_id = _text(entry, "id", ns)
    updated_raw = _text(entry, "updated", ns)
    published_raw = _text(entry, "published", ns)

    # Atom <author><name>
    author: str | None = None
    author_el = entry.find(f"{{{ns}}}author")
    if author_el is not None:
        author = _text(author_el, "name", ns)

    # Atom <link rel="alternate"> or first <link>
    link: str | None = None
    for link_el in entry.findall(f"{{{ns}}}link"):
        rel = link_el.get("rel", "alternate")
        if rel == "alternate":
            link = link_el.get("href")
            break
    if link is None:
        link = _attr(entry, "link", "href", ns)

    # Atom <content> or <summary>
    content: str | None = None
    content_el = entry.find(f"{{{ns}}}content")
    if content_el is not None and content_el.text:
        content = content_el.text.strip() or None
    if content is None:
        summary_el = entry.find(f"{{{ns}}}summary")
        if summary_el is not None and summary_el.text:
            content = summary_el.text.strip() or None

    item_id = atom_id or _stable_id(source_url, f"{link or ''}{title or ''}")

    # Use <published> if available, fall back to <updated>
    date_raw = published_raw or updated_raw
    published_at = _parse_iso8601_date(date_raw) if date_raw else None

    return FeedItem(
        source_url=source_url,
        source_type="rss",
        item_id=item_id,
        title=title,
        url=link,
        content=content,
        author=author,
        published_at=published_at,
        raw=entry,
    )


# ---------------------------------------------------------------------------
# Format detection and top-level parser
# ---------------------------------------------------------------------------


def _is_atom(root: Element) -> bool:
    """Return ``True`` if *root* is an Atom feed root element.

    Args:
        root: XML root element.

    Returns:
        ``True`` for Atom feeds, ``False`` for RSS.
    """
    return root.tag == f"{{{_ATOM_NS}}}feed" or root.tag == "feed"


def parse_feed_xml(xml_bytes: bytes, source_url: str) -> list[FeedItem]:
    """Parse RSS 2.0 or Atom XML and return a list of :class:`FeedItem`.

    Args:
        xml_bytes: Raw XML content (bytes).
        source_url: Canonical URL of the feed (stored in every item).

    Returns:
        List of :class:`FeedItem` objects in document order.

    Raises:
        xml.etree.ElementTree.ParseError: If *xml_bytes* is not valid XML.
        defusedxml.EntitiesForbidden: If the XML contains entity declarations
            (blocked by defusedxml's default ``forbid_entities=True``).
    """
    # Use defusedxml to safely parse XML — blocks XXE, entity expansion,
    # and DTD retrieval while accepting valid feeds with DOCTYPE declarations.
    root = DefusedElementTree.fromstring(xml_bytes)

    items: list[FeedItem] = []

    if _is_atom(root):
        for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
            try:
                items.append(_parse_atom_entry(entry, source_url))
            except Exception:
                logger.exception("RSSAdapter: failed to parse Atom entry")
    else:
        # RSS 2.0: root is <rss>, channel items are at rss/channel/item
        channel = root.find("channel")
        if channel is None:
            # Some feeds omit the <channel> wrapper; try direct <item> children.
            channel = root
        for item in channel.findall("item"):
            try:
                items.append(_parse_rss_item(item, source_url))
            except Exception:
                logger.exception("RSSAdapter: failed to parse RSS item")

    return items


# ---------------------------------------------------------------------------
# Adapter class
# ---------------------------------------------------------------------------


class RSSAdapter:
    """Feed adapter that fetches and parses an RSS 2.0 or Atom feed URL.

    Parameters
    ----------
    url:
        Full URL of the RSS or Atom feed.

    Raises
    ------
    ValueError
        If *url* is empty.
    """

    def __init__(self, url: str) -> None:
        if not url.strip():
            raise ValueError("RSSAdapter requires a non-empty feed URL.")
        raw = url.strip()
        normalised, extra_headers = _normalise_feed_url(raw)
        self._source_url = raw  # original URL — used as identity / source_url in FeedItems
        self._fetch_url = normalised  # possibly rewritten URL — used for HTTP requests only
        self._extra_headers = extra_headers
        self.last_polled_at: datetime | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def source_url(self) -> str:
        """The original feed URL passed at construction time (identity key)."""
        return self._source_url

    def fetch(self) -> list[FeedItem]:
        """Fetch the feed URL and return normalised :class:`FeedItem` objects.

        Updates :attr:`last_polled_at` on every successful HTTP response
        (even when the feed contains no items).

        Returns:
            A list of :class:`~distillery.feeds.models.FeedItem` objects in
            document order (newest-first for well-formed feeds).

        Raises:
            httpx.HTTPStatusError: On non-2xx HTTP responses.
            httpx.RequestError: On network-level failures.
            xml.etree.ElementTree.ParseError: If the response body is not
                valid XML.
        """
        logger.debug("RSSAdapter: fetching %s", self._fetch_url)

        headers = {"User-Agent": "Distillery/0.1 (RSS adapter)"}
        headers.update(self._extra_headers)

        with httpx.Client(timeout=_REQUEST_TIMEOUT, verify=True) as client:
            response = client.get(
                self._fetch_url,
                headers=headers,
                follow_redirects=True,
            )
            response.raise_for_status()

        self.last_polled_at = datetime.now(tz=UTC)

        # Use the original source_url (not the rewritten fetch URL) so
        # FeedItem.source_url and _stable_id inputs stay consistent.
        return parse_feed_xml(response.content, self._source_url)
