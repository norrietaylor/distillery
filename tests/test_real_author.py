"""Tests for real author extraction from source payloads (issue #302).

Covers:
- GitHubSyncAdapter: extracts user.login from issue/PR payload
- RSS poller: extracts author from RSS <author> / <dc:creator> and Atom <author><name>
- Fallback behaviour when author is missing from payload
- metadata.imported_by records the sync tool name
"""

from __future__ import annotations

import re
import textwrap

import pytest

from distillery.feeds.github_sync import GitHubSyncAdapter
from distillery.feeds.models import FeedItem
from distillery.feeds.poller import _item_to_entry_kwargs
from distillery.feeds.rss import parse_feed_xml

# ---------------------------------------------------------------------------
# GitHub sync — author extraction
# ---------------------------------------------------------------------------


def _mock_issue(
    number: int = 1,
    title: str = "Test issue",
    body: str | None = "Issue body",
    user_login: str | None = "octocat",
    is_pr: bool = False,
) -> dict:
    """Build a mock GitHub issue API response with configurable user."""
    issue: dict = {
        "number": number,
        "title": title,
        "body": body,
        "state": "open",
        "html_url": f"https://github.com/test/repo/issues/{number}",
        "labels": [],
        "assignees": [],
    }
    if user_login is not None:
        issue["user"] = {"login": user_login}
    else:
        issue["user"] = None
    if is_pr:
        issue["pull_request"] = {"url": f"https://api.github.com/repos/test/repo/pulls/{number}"}
    return issue


class TestGitHubSyncRealAuthor:
    """GitHubSyncAdapter should use user.login from the issue payload."""

    @pytest.mark.integration
    async def test_entry_author_is_github_user(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Entry author should be the GitHub user who created the issue."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1, user_login="alice")],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        await adapter.sync()

        entries = await store.list_entries(filters={"entry_type": "github"}, limit=10, offset=0)
        assert len(entries) == 1
        assert entries[0].author == "alice"

    @pytest.mark.integration
    async def test_imported_by_metadata(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """metadata.imported_by should record 'gh-sync'."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1, user_login="bob")],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        await adapter.sync()

        entries = await store.list_entries(filters={"entry_type": "github"}, limit=10, offset=0)
        assert entries[0].metadata["imported_by"] == "gh-sync"

    @pytest.mark.integration
    async def test_fallback_when_user_missing(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """When user is null in payload, author should fall back to adapter default."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1, user_login=None)],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        await adapter.sync()

        entries = await store.list_entries(filters={"entry_type": "github"}, limit=10, offset=0)
        assert entries[0].author == "gh-sync"

    @pytest.mark.integration
    async def test_pr_author_extracted(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """PR entries should also use user.login as author."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=5, user_login="carol", is_pr=True)],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/5/comments.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        await adapter.sync()

        entries = await store.list_entries(filters={"entry_type": "github"}, limit=10, offset=0)
        assert entries[0].author == "carol"

    @pytest.mark.integration
    async def test_existing_entry_author_is_updated_from_payload(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Re-syncing an existing entry should correct a stale tool author."""
        # First sync: payload has no user → entry gets the fallback author.
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1, user_login=None)],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        await adapter.sync()

        entries = await store.list_entries(filters={"entry_type": "github"}, limit=10, offset=0)
        assert len(entries) == 1
        assert entries[0].author == "gh-sync"

        # Second sync: payload now includes a real user → existing entry
        # should be updated with the real author.
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1, user_login="alice")],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        await adapter.sync()

        entries = await store.list_entries(filters={"entry_type": "github"}, limit=10, offset=0)
        assert len(entries) == 1  # still one entry, not a duplicate
        assert entries[0].author == "alice"

    @pytest.mark.integration
    async def test_mixed_authors_in_batch(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Multiple issues with different authors should each get the correct author."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[
                _mock_issue(number=1, user_login="alice"),
                _mock_issue(number=2, user_login="bob"),
                _mock_issue(number=3, user_login=None),
            ],
        )
        for n in (1, 2, 3):
            httpx_mock.add_response(
                url=re.compile(rf".*/repos/test/repo/issues/{n}/comments.*"),
                json=[],
            )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        await adapter.sync()

        entries = await store.list_entries(filters={"entry_type": "github"}, limit=10, offset=0)
        authors = {e.metadata["ref_number"]: e.author for e in entries}
        assert authors[1] == "alice"
        assert authors[2] == "bob"
        assert authors[3] == "gh-sync"  # fallback


# ---------------------------------------------------------------------------
# RSS / Atom — author extraction
# ---------------------------------------------------------------------------


_RSS_WITH_AUTHOR_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Post with author</title>
          <link>https://example.com/1</link>
          <author>jane@example.com (Jane Doe)</author>
          <guid>guid-1</guid>
        </item>
        <item>
          <title>Post without author</title>
          <link>https://example.com/2</link>
          <guid>guid-2</guid>
        </item>
      </channel>
    </rss>
""").encode()


_RSS_WITH_DC_CREATOR_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
      <channel>
        <item>
          <title>Post with dc:creator</title>
          <link>https://example.com/1</link>
          <dc:creator>John Smith</dc:creator>
          <guid>guid-dc-1</guid>
        </item>
      </channel>
    </rss>
""").encode()


_ATOM_WITH_AUTHOR_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Atom Feed</title>
      <id>https://example.com/atom</id>
      <entry>
        <id>entry-1</id>
        <title>Entry with author</title>
        <link rel="alternate" href="https://example.com/entry/1"/>
        <author><name>Alice Author</name></author>
        <summary>Summary</summary>
      </entry>
      <entry>
        <id>entry-2</id>
        <title>Entry without author</title>
        <link rel="alternate" href="https://example.com/entry/2"/>
        <summary>Another summary</summary>
      </entry>
    </feed>
""").encode()


class TestRSSAuthorExtraction:
    """RSS parser should extract author from <author> and <dc:creator>."""

    _SOURCE_URL = "https://example.com/feed"

    @pytest.mark.unit
    def test_rss_author_present(self) -> None:
        items = parse_feed_xml(_RSS_WITH_AUTHOR_XML, self._SOURCE_URL)
        assert items[0].author == "jane@example.com (Jane Doe)"

    @pytest.mark.unit
    def test_rss_author_missing(self) -> None:
        items = parse_feed_xml(_RSS_WITH_AUTHOR_XML, self._SOURCE_URL)
        assert items[1].author is None

    @pytest.mark.unit
    def test_rss_dc_creator(self) -> None:
        items = parse_feed_xml(_RSS_WITH_DC_CREATOR_XML, self._SOURCE_URL)
        assert items[0].author == "John Smith"


class TestAtomAuthorExtraction:
    """Atom parser should extract author from <author><name>."""

    _SOURCE_URL = "https://example.com/atom"

    @pytest.mark.unit
    def test_atom_author_present(self) -> None:
        items = parse_feed_xml(_ATOM_WITH_AUTHOR_XML, self._SOURCE_URL)
        assert items[0].author == "Alice Author"

    @pytest.mark.unit
    def test_atom_author_missing(self) -> None:
        items = parse_feed_xml(_ATOM_WITH_AUTHOR_XML, self._SOURCE_URL)
        assert items[1].author is None


# ---------------------------------------------------------------------------
# Poller — _item_to_entry_kwargs author handling
# ---------------------------------------------------------------------------


class TestPollerAuthorHandling:
    """_item_to_entry_kwargs should use item.author when available."""

    @pytest.mark.unit
    def test_author_from_feed_item(self) -> None:
        item = FeedItem(
            source_url="https://example.com/feed",
            source_type="rss",
            item_id="test-1",
            title="Test",
            content="Content",
            author="feed-author",
        )
        kwargs = _item_to_entry_kwargs(item, 0.8)
        assert kwargs["author"] == "feed-author"

    @pytest.mark.unit
    def test_fallback_to_distillery_poller(self) -> None:
        item = FeedItem(
            source_url="https://example.com/feed",
            source_type="rss",
            item_id="test-2",
            title="Test",
            content="Content",
        )
        kwargs = _item_to_entry_kwargs(item, 0.8)
        assert kwargs["author"] == "distillery-poller"

    @pytest.mark.unit
    def test_imported_by_in_metadata(self) -> None:
        item = FeedItem(
            source_url="https://example.com/feed",
            source_type="rss",
            item_id="test-3",
            title="Test",
            content="Content",
            author="someone",
        )
        kwargs = _item_to_entry_kwargs(item, 0.8)
        assert kwargs["metadata"]["imported_by"] == "distillery-poller"

    @pytest.mark.unit
    def test_empty_string_author_falls_back(self) -> None:
        item = FeedItem(
            source_url="https://example.com/feed",
            source_type="rss",
            item_id="test-4",
            title="Test",
            content="Content",
            author="",
        )
        kwargs = _item_to_entry_kwargs(item, 0.8)
        assert kwargs["author"] == "distillery-poller"
