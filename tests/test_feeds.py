"""Tests for the feeds package: FeedItem, GitHubAdapter, RSSAdapter.

Covers:
  - FeedItem dataclass construction and field defaults
  - _parse_github_url: URL parsing for various formats
  - _event_to_feed_item: GitHub event JSON -> FeedItem normalisation
  - GitHubAdapter.fetch: mocked httpx responses
  - parse_feed_xml: RSS 2.0 and Atom XML parsing
  - RSSAdapter.fetch: mocked httpx responses
  - last_polled_at tracking on both adapters
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from distillery.feeds.github import GitHubAdapter, _event_to_feed_item, _parse_github_url
from distillery.feeds.models import FeedItem
from distillery.feeds.rss import RSSAdapter, parse_feed_xml

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# FeedItem
# ---------------------------------------------------------------------------


class TestFeedItem:
    def test_required_fields(self) -> None:
        item = FeedItem(source_url="https://example.com/rss", source_type="rss", item_id="1")
        assert item.source_url == "https://example.com/rss"
        assert item.source_type == "rss"
        assert item.item_id == "1"

    def test_optional_fields_default_to_none(self) -> None:
        item = FeedItem(source_url="u", source_type="github", item_id="x")
        assert item.title is None
        assert item.url is None
        assert item.content is None
        assert item.published_at is None
        assert item.raw is None
        assert item.extra == {}

    def test_equality_ignores_raw(self) -> None:
        a = FeedItem(source_url="u", source_type="rss", item_id="1", raw={"a": 1})
        b = FeedItem(source_url="u", source_type="rss", item_id="1", raw={"b": 2})
        assert a == b

    def test_equality_considers_item_id(self) -> None:
        a = FeedItem(source_url="u", source_type="rss", item_id="1")
        b = FeedItem(source_url="u", source_type="rss", item_id="2")
        assert a != b


# ---------------------------------------------------------------------------
# _parse_github_url
# ---------------------------------------------------------------------------


class TestParseGitHubUrl:
    def test_bare_slug(self) -> None:
        assert _parse_github_url("owner/repo") == ("owner", "repo")

    def test_https_github(self) -> None:
        assert _parse_github_url("https://github.com/owner/repo") == ("owner", "repo")

    def test_https_github_trailing_slash(self) -> None:
        assert _parse_github_url("https://github.com/owner/repo/") == ("owner", "repo")

    def test_https_github_git_suffix(self) -> None:
        assert _parse_github_url("https://github.com/owner/repo.git") == ("owner", "repo")

    def test_api_github_repos_url(self) -> None:
        assert _parse_github_url("https://api.github.com/repos/owner/repo") == ("owner", "repo")

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot extract owner/repo"):
            _parse_github_url("https://not-github.com/owner/repo")

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_github_url("")

    def test_slug_with_dots_and_hyphens(self) -> None:
        assert _parse_github_url("my.org/my-repo") == ("my.org", "my-repo")


# ---------------------------------------------------------------------------
# _event_to_feed_item
# ---------------------------------------------------------------------------


class TestEventToFeedItem:
    _SOURCE_URL = "https://github.com/owner/repo"

    def _make_event(self, **overrides: object) -> dict:  # type: ignore[type-arg]
        base: dict = {  # type: ignore[type-arg]
            "id": "12345",
            "type": "PushEvent",
            "actor": {"login": "alice"},
            "repo": {"name": "owner/repo"},
            "payload": {
                "commits": [{"message": "Fix the bug"}],
            },
            "created_at": "2024-03-25T10:00:00Z",
        }
        base.update(overrides)
        return base

    def test_item_id_from_event_id(self) -> None:
        event = self._make_event()
        item = _event_to_feed_item(event, self._SOURCE_URL)
        assert item.item_id == "12345"

    def test_source_url_preserved(self) -> None:
        item = _event_to_feed_item(self._make_event(), self._SOURCE_URL)
        assert item.source_url == self._SOURCE_URL

    def test_source_type_is_github(self) -> None:
        item = _event_to_feed_item(self._make_event(), self._SOURCE_URL)
        assert item.source_type == "github"

    def test_title_contains_event_type_and_actor(self) -> None:
        item = _event_to_feed_item(self._make_event(), self._SOURCE_URL)
        assert "PushEvent" in item.title  # type: ignore[operator]
        assert "alice" in item.title  # type: ignore[operator]

    def test_content_from_commit_message(self) -> None:
        item = _event_to_feed_item(self._make_event(), self._SOURCE_URL)
        assert item.content == "Fix the bug"

    def test_published_at_parsed(self) -> None:
        item = _event_to_feed_item(self._make_event(), self._SOURCE_URL)
        assert item.published_at == datetime(2024, 3, 25, 10, 0, 0, tzinfo=UTC)

    def test_published_at_none_when_missing(self) -> None:
        event = self._make_event(created_at=None)
        item = _event_to_feed_item(event, self._SOURCE_URL)
        assert item.published_at is None

    def test_url_from_issue_payload(self) -> None:
        event = self._make_event(
            type="IssuesEvent",
            payload={"issue": {"html_url": "https://github.com/owner/repo/issues/1"}},
        )
        item = _event_to_feed_item(event, self._SOURCE_URL)
        assert item.url == "https://github.com/owner/repo/issues/1"

    def test_url_from_pr_payload(self) -> None:
        event = self._make_event(
            type="PullRequestEvent",
            payload={"pull_request": {"html_url": "https://github.com/owner/repo/pull/5"}},
        )
        item = _event_to_feed_item(event, self._SOURCE_URL)
        assert item.url == "https://github.com/owner/repo/pull/5"

    def test_url_fallback_to_repo(self) -> None:
        event = self._make_event(payload={})
        item = _event_to_feed_item(event, self._SOURCE_URL)
        assert item.url == "https://github.com/owner/repo"

    def test_extra_contains_event_type(self) -> None:
        item = _event_to_feed_item(self._make_event(), self._SOURCE_URL)
        assert item.extra["event_type"] == "PushEvent"
        assert item.extra["actor"] == "alice"
        assert item.extra["repo"] == "owner/repo"

    def test_raw_preserved(self) -> None:
        event = self._make_event()
        item = _event_to_feed_item(event, self._SOURCE_URL)
        assert item.raw is event


# ---------------------------------------------------------------------------
# GitHubAdapter
# ---------------------------------------------------------------------------


class TestGitHubAdapter:
    def test_init_parses_slug(self) -> None:
        adapter = GitHubAdapter("owner/repo")
        assert adapter.owner == "owner"
        assert adapter.repo == "repo"

    def test_last_polled_at_starts_none(self) -> None:
        adapter = GitHubAdapter("owner/repo")
        assert adapter.last_polled_at is None

    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError):
            GitHubAdapter("not-a-valid-url-at-all")

    def test_fetch_returns_feed_items(self) -> None:
        events = [
            {
                "id": "42",
                "type": "PushEvent",
                "actor": {"login": "bob"},
                "repo": {"name": "owner/repo"},
                "payload": {"commits": [{"message": "Initial commit"}]},
                "created_at": "2024-03-25T09:00:00Z",
            }
        ]
        mock_response = MagicMock()
        mock_response.json.return_value = events
        mock_response.raise_for_status.return_value = None

        with patch("distillery.feeds.github.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            adapter = GitHubAdapter("owner/repo")
            items = adapter.fetch()

        assert len(items) == 1
        assert items[0].item_id == "42"
        assert items[0].source_type == "github"

    def test_fetch_updates_last_polled_at(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None

        with patch("distillery.feeds.github.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            adapter = GitHubAdapter("owner/repo")
            assert adapter.last_polled_at is None
            adapter.fetch()
            assert adapter.last_polled_at is not None

    def test_fetch_empty_response(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status.return_value = None

        with patch("distillery.feeds.github.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            items = GitHubAdapter("owner/repo").fetch()
        assert items == []

    def test_fetch_token_set_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_testtoken")
        adapter = GitHubAdapter("owner/repo")
        # Token should have been picked up from the environment
        assert adapter._token == "ghp_testtoken"  # noqa: SLF001


# ---------------------------------------------------------------------------
# parse_feed_xml — RSS 2.0
# ---------------------------------------------------------------------------


_RSS_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        <link>https://example.com</link>
        <description>A test feed</description>
        <item>
          <title>First post</title>
          <link>https://example.com/1</link>
          <description>Content of first post</description>
          <guid>https://example.com/guid/1</guid>
          <pubDate>Mon, 25 Mar 2024 10:00:00 +0000</pubDate>
          <category>tech</category>
        </item>
        <item>
          <title>Second post</title>
          <link>https://example.com/2</link>
          <description>Content of second post</description>
          <pubDate>Sun, 24 Mar 2024 08:00:00 +0000</pubDate>
        </item>
      </channel>
    </rss>
""").encode()


_ATOM_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Atom Test Feed</title>
      <id>https://example.com/atom</id>
      <entry>
        <id>https://example.com/entry/1</id>
        <title>Atom Entry One</title>
        <link rel="alternate" href="https://example.com/entry/1"/>
        <summary>Summary of entry one</summary>
        <published>2024-03-25T12:00:00Z</published>
        <updated>2024-03-25T12:00:00Z</updated>
      </entry>
      <entry>
        <id>https://example.com/entry/2</id>
        <title>Atom Entry Two</title>
        <link href="https://example.com/entry/2"/>
        <content>Full content of entry two</content>
        <updated>2024-03-24T08:00:00Z</updated>
      </entry>
    </feed>
""").encode()


_RSS_NO_GUID_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>No GUID</title>
          <link>https://example.com/no-guid</link>
        </item>
      </channel>
    </rss>
""").encode()


class TestParseFeedXmlRSS:
    _SOURCE_URL = "https://example.com/rss"

    def test_returns_two_items(self) -> None:
        items = parse_feed_xml(_RSS_XML, self._SOURCE_URL)
        assert len(items) == 2

    def test_first_item_title(self) -> None:
        items = parse_feed_xml(_RSS_XML, self._SOURCE_URL)
        assert items[0].title == "First post"

    def test_first_item_url(self) -> None:
        items = parse_feed_xml(_RSS_XML, self._SOURCE_URL)
        assert items[0].url == "https://example.com/1"

    def test_first_item_content(self) -> None:
        items = parse_feed_xml(_RSS_XML, self._SOURCE_URL)
        assert items[0].content == "Content of first post"

    def test_first_item_guid(self) -> None:
        items = parse_feed_xml(_RSS_XML, self._SOURCE_URL)
        assert items[0].item_id == "https://example.com/guid/1"

    def test_first_item_published_at(self) -> None:
        items = parse_feed_xml(_RSS_XML, self._SOURCE_URL)
        assert items[0].published_at == datetime(2024, 3, 25, 10, 0, 0, tzinfo=UTC)

    def test_first_item_category_in_extra(self) -> None:
        items = parse_feed_xml(_RSS_XML, self._SOURCE_URL)
        assert "categories" in items[0].extra
        assert "tech" in items[0].extra["categories"]

    def test_source_url_preserved(self) -> None:
        items = parse_feed_xml(_RSS_XML, self._SOURCE_URL)
        for item in items:
            assert item.source_url == self._SOURCE_URL

    def test_source_type_is_rss(self) -> None:
        items = parse_feed_xml(_RSS_XML, self._SOURCE_URL)
        for item in items:
            assert item.source_type == "rss"

    def test_item_without_guid_gets_stable_id(self) -> None:
        items = parse_feed_xml(_RSS_NO_GUID_XML, self._SOURCE_URL)
        assert len(items) == 1
        assert len(items[0].item_id) == 16  # SHA-256 prefix

    def test_item_without_guid_stable_across_calls(self) -> None:
        items1 = parse_feed_xml(_RSS_NO_GUID_XML, self._SOURCE_URL)
        items2 = parse_feed_xml(_RSS_NO_GUID_XML, self._SOURCE_URL)
        assert items1[0].item_id == items2[0].item_id


class TestParseFeedXmlAtom:
    _SOURCE_URL = "https://example.com/atom"

    def test_returns_two_entries(self) -> None:
        items = parse_feed_xml(_ATOM_XML, self._SOURCE_URL)
        assert len(items) == 2

    def test_first_entry_title(self) -> None:
        items = parse_feed_xml(_ATOM_XML, self._SOURCE_URL)
        assert items[0].title == "Atom Entry One"

    def test_first_entry_url(self) -> None:
        items = parse_feed_xml(_ATOM_XML, self._SOURCE_URL)
        assert items[0].url == "https://example.com/entry/1"

    def test_first_entry_content_from_summary(self) -> None:
        items = parse_feed_xml(_ATOM_XML, self._SOURCE_URL)
        assert items[0].content == "Summary of entry one"

    def test_second_entry_content_from_content_tag(self) -> None:
        items = parse_feed_xml(_ATOM_XML, self._SOURCE_URL)
        assert items[1].content == "Full content of entry two"

    def test_first_entry_published_at(self) -> None:
        items = parse_feed_xml(_ATOM_XML, self._SOURCE_URL)
        assert items[0].published_at == datetime(2024, 3, 25, 12, 0, 0, tzinfo=UTC)

    def test_second_entry_published_at_from_updated(self) -> None:
        items = parse_feed_xml(_ATOM_XML, self._SOURCE_URL)
        assert items[1].published_at == datetime(2024, 3, 24, 8, 0, 0, tzinfo=UTC)

    def test_entry_id_preserved(self) -> None:
        items = parse_feed_xml(_ATOM_XML, self._SOURCE_URL)
        assert items[0].item_id == "https://example.com/entry/1"

    def test_source_url_preserved(self) -> None:
        items = parse_feed_xml(_ATOM_XML, self._SOURCE_URL)
        for item in items:
            assert item.source_url == self._SOURCE_URL

    def test_source_type_is_rss(self) -> None:
        items = parse_feed_xml(_ATOM_XML, self._SOURCE_URL)
        for item in items:
            assert item.source_type == "rss"


# ---------------------------------------------------------------------------
# RSSAdapter
# ---------------------------------------------------------------------------


class TestRSSAdapter:
    def test_empty_url_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            RSSAdapter("")

    def test_last_polled_at_starts_none(self) -> None:
        adapter = RSSAdapter("https://example.com/rss")
        assert adapter.last_polled_at is None

    def test_source_url_preserved(self) -> None:
        adapter = RSSAdapter("https://example.com/rss")
        assert adapter.source_url == "https://example.com/rss"

    def test_fetch_returns_items(self) -> None:
        mock_response = MagicMock()
        mock_response.content = _RSS_XML
        mock_response.raise_for_status.return_value = None

        with patch("distillery.feeds.rss.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            adapter = RSSAdapter("https://example.com/rss")
            items = adapter.fetch()

        assert len(items) == 2
        assert items[0].title == "First post"

    def test_fetch_updates_last_polled_at(self) -> None:
        mock_response = MagicMock()
        mock_response.content = _RSS_XML
        mock_response.raise_for_status.return_value = None

        with patch("distillery.feeds.rss.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            adapter = RSSAdapter("https://example.com/rss")
            assert adapter.last_polled_at is None
            adapter.fetch()
            assert adapter.last_polled_at is not None

    def test_fetch_atom_feed(self) -> None:
        mock_response = MagicMock()
        mock_response.content = _ATOM_XML
        mock_response.raise_for_status.return_value = None

        with patch("distillery.feeds.rss.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            adapter = RSSAdapter("https://example.com/atom")
            items = adapter.fetch()

        assert len(items) == 2
        assert items[0].title == "Atom Entry One"


# ---------------------------------------------------------------------------
# _derive_source_tags
# ---------------------------------------------------------------------------


class TestDeriveSourceTags:
    """Tests for _derive_source_tags() in poller.py."""

    def _make_item(self, source_url: str, source_type: str) -> FeedItem:
        return FeedItem(source_url=source_url, source_type=source_type, item_id="test-id")

    def test_source_tag_rss_generic(self) -> None:
        """All feeds get a source/{source_type} tag."""
        from distillery.feeds.poller import _derive_source_tags

        item = self._make_item("https://example.com/rss", "rss")
        tags = _derive_source_tags(item, "rss")
        assert "source/rss" in tags

    def test_source_tag_github_type(self) -> None:
        """GitHub feeds get source/github tag."""
        from distillery.feeds.poller import _derive_source_tags

        item = self._make_item("https://github.com/owner/repo", "github")
        tags = _derive_source_tags(item, "github")
        assert "source/github" in tags

    def test_source_tag_github_owner_repo(self) -> None:
        """GitHub feeds derive source/github/{owner}/{repo}."""
        from distillery.feeds.poller import _derive_source_tags

        item = self._make_item("https://github.com/owner/repo", "github")
        tags = _derive_source_tags(item, "github")
        assert "source/github/owner/repo" in tags

    def test_source_tag_github_slug_format(self) -> None:
        """GitHub bare slug also works for owner/repo derivation."""
        from distillery.feeds.poller import _derive_source_tags

        item = self._make_item("owner/repo", "github")
        tags = _derive_source_tags(item, "github")
        assert "source/github" in tags
        assert "source/github/owner/repo" in tags

    def test_source_tag_reddit(self) -> None:
        """Reddit RSS URLs derive source/reddit/{subreddit}."""
        from distillery.feeds.poller import _derive_source_tags

        item = self._make_item("https://www.reddit.com/r/python/.rss", "rss")
        tags = _derive_source_tags(item, "rss")
        assert "source/rss" in tags
        assert "source/reddit/python" in tags

    def test_source_tag_reddit_no_generic_domain(self) -> None:
        """Reddit URLs should not also produce a generic domain tag."""
        from distillery.feeds.poller import _derive_source_tags

        item = self._make_item("https://www.reddit.com/r/python/.rss", "rss")
        tags = _derive_source_tags(item, "rss")
        # Should not have a plain reddit.com domain tag — only source/reddit/{sub}
        assert "source/reddit-com" not in tags

    def test_source_tag_domain_extraction(self) -> None:
        """Generic RSS feeds derive source/{domain-slug} with www. stripped and dots as hyphens."""
        from distillery.feeds.poller import _derive_source_tags

        item = self._make_item("https://www.example.com/feed.xml", "rss")
        tags = _derive_source_tags(item, "rss")
        assert "source/rss" in tags
        # Dots replaced with hyphens; www. stripped
        assert "source/example-com" in tags

    def test_source_tag_domain_no_www_prefix(self) -> None:
        """Domain without www. prefix also works, dots replaced with hyphens."""
        from distillery.feeds.poller import _derive_source_tags

        item = self._make_item("https://blog.example.com/atom.xml", "rss")
        tags = _derive_source_tags(item, "rss")
        assert "source/blog-example-com" in tags

    def test_source_tag_invalid_github_url_still_returns_type_tag(self) -> None:
        """Unparseable GitHub URL still returns source/github tag."""
        from distillery.feeds.poller import _derive_source_tags

        item = self._make_item("https://not-github.com/foo", "github")
        tags = _derive_source_tags(item, "github")
        assert "source/github" in tags
        # No owner/repo tag — parsing failed silently
        assert not any("source/github/" in t for t in tags)

    def test_source_tag_invalid_tags_dropped(self) -> None:
        """Tags that fail validate_tag() are silently dropped."""
        from distillery.feeds.poller import _derive_source_tags

        # URL with uppercase in domain would still be lowercased; test via empty domain
        item = self._make_item("", "rss")
        tags = _derive_source_tags(item, "rss")
        # source/rss should still be valid
        assert "source/rss" in tags
        # No crashes; all returned tags should be valid
        from distillery.models import validate_tag

        for tag in tags:
            validate_tag(tag)  # should not raise


# ---------------------------------------------------------------------------
# build_keyword_map
# ---------------------------------------------------------------------------


class TestBuildKeywordMap:
    """Tests for build_keyword_map() in poller.py."""

    def test_leaf_segment_mapped(self) -> None:
        """The leaf segment of a tag maps to the full tag path."""
        from distillery.feeds.poller import build_keyword_map

        kw_map = build_keyword_map({"domain/authentication": 5})
        assert kw_map.get("authentication") == "domain/authentication"

    def test_hyphenated_leaf_splits_long_words(self) -> None:
        """Hyphenated leaf segments produce individual words > 3 chars."""
        from distillery.feeds.poller import build_keyword_map

        kw_map = build_keyword_map({"security/supply-chain": 3})
        # leaf = "supply-chain"; both "supply" and "chain" are > 3 chars
        assert kw_map.get("supply") == "security/supply-chain"
        assert kw_map.get("chain") == "security/supply-chain"

    def test_short_words_not_mapped(self) -> None:
        """Words of 3 chars or fewer from hyphenated leaves are not mapped."""
        from distillery.feeds.poller import build_keyword_map

        kw_map = build_keyword_map({"ops/ci-cd": 1})
        # leaf = "ci-cd"; "ci" (2 chars) and "cd" (2 chars) skipped
        # The whole leaf "ci-cd" should still map
        assert "ci" not in kw_map
        assert "cd" not in kw_map
        assert kw_map.get("ci-cd") == "ops/ci-cd"

    def test_higher_count_wins_on_collision(self) -> None:
        """When two tags produce the same keyword, the higher-count tag wins."""
        from distillery.feeds.poller import build_keyword_map

        vocab = {"domain/authentication": 10, "security/authentication": 2}
        kw_map = build_keyword_map(vocab)
        assert kw_map.get("authentication") == "domain/authentication"

    def test_alphabetical_tiebreak(self) -> None:
        """Equal counts resolve alphabetically (earlier tag path wins)."""
        from distillery.feeds.poller import build_keyword_map

        vocab = {"b-namespace/auth": 5, "a-namespace/auth": 5}
        kw_map = build_keyword_map(vocab)
        assert kw_map.get("auth") == "a-namespace/auth"

    def test_case_insensitive_keyword(self) -> None:
        """Keywords are stored lowercase regardless of input (tags must already be lowercase)."""
        from distillery.feeds.poller import build_keyword_map

        kw_map = build_keyword_map({"lang/python": 1})
        assert kw_map.get("python") == "lang/python"

    def test_empty_vocabulary_returns_empty_map(self) -> None:
        """Empty vocabulary produces an empty keyword map."""
        from distillery.feeds.poller import build_keyword_map

        assert build_keyword_map({}) == {}


# ---------------------------------------------------------------------------
# match_topic_tags
# ---------------------------------------------------------------------------


class TestMatchTopicTags:
    """Tests for match_topic_tags() in poller.py."""

    def test_single_hit(self) -> None:
        """A keyword present in the text returns the corresponding tag."""
        from distillery.feeds.poller import match_topic_tags

        kw_map = {"authentication": "domain/authentication"}
        result = match_topic_tags("Using authentication tokens", kw_map)
        assert "domain/authentication" in result

    def test_case_insensitive(self) -> None:
        """Matching is case-insensitive."""
        from distillery.feeds.poller import match_topic_tags

        kw_map = {"authentication": "domain/authentication"}
        result = match_topic_tags("AUTHENTICATION is required", kw_map)
        assert "domain/authentication" in result

    def test_no_match_returns_empty(self) -> None:
        """Text with no matching keywords returns an empty list."""
        from distillery.feeds.poller import match_topic_tags

        kw_map = {"authentication": "domain/authentication"}
        result = match_topic_tags("Hello world, nothing to see here", kw_map)
        assert result == []

    def test_deduplication(self) -> None:
        """The same keyword appearing multiple times produces only one tag entry."""
        from distillery.feeds.poller import match_topic_tags

        kw_map = {"authentication": "domain/authentication"}
        result = match_topic_tags("authentication and more authentication", kw_map)
        assert result.count("domain/authentication") == 1

    def test_multiple_hits(self) -> None:
        """Multiple distinct keywords each map to their respective tags."""
        from distillery.feeds.poller import match_topic_tags

        kw_map = {
            "authentication": "domain/authentication",
            "security": "domain/security",
        }
        result = match_topic_tags("authentication and security", kw_map)
        assert "domain/authentication" in result
        assert "domain/security" in result

    def test_empty_text_returns_empty(self) -> None:
        """Empty text produces no matches."""
        from distillery.feeds.poller import match_topic_tags

        kw_map = {"authentication": "domain/authentication"}
        result = match_topic_tags("", kw_map)
        assert result == []

    def test_empty_keyword_map_returns_empty(self) -> None:
        """Empty keyword map produces no matches."""
        from distillery.feeds.poller import match_topic_tags

        result = match_topic_tags("authentication security python", {})
        assert result == []


# ---------------------------------------------------------------------------
# derive_all_tags (topic_tag matching integration)
# ---------------------------------------------------------------------------


class TestDeriveAllTagsTopicTag:
    """Tests for derive_all_tags() in poller.py — Tier 1 + Tier 2 combination."""

    def _make_item(
        self,
        source_url: str,
        source_type: str,
        title: str = "",
        content: str = "",
    ) -> FeedItem:
        return FeedItem(
            source_url=source_url,
            source_type=source_type,
            item_id="test-id",
            title=title,
            content=content,
        )

    def test_topic_tag_matched_from_title(self) -> None:
        """An item with 'authentication' in its title gets the matching topic tag."""
        from distillery.feeds.poller import derive_all_tags

        kw_map = {"authentication": "domain/authentication"}
        item = self._make_item(
            "https://example.com/rss", "rss", title="OAuth authentication guide"
        )
        tags = derive_all_tags(item, "rss", kw_map)
        assert "domain/authentication" in tags

    def test_no_topic_match_only_source_tags(self) -> None:
        """An item with no keyword matches gets only source tags."""
        from distillery.feeds.poller import derive_all_tags

        kw_map = {"authentication": "domain/authentication"}
        item = self._make_item("https://example.com/rss", "rss", title="Random news update")
        tags = derive_all_tags(item, "rss", kw_map)
        assert "source/rss" in tags
        assert "domain/authentication" not in tags

    def test_source_tags_appear_before_topic_tags(self) -> None:
        """Source tags (Tier 1) come before topic tags (Tier 2) in the result."""
        from distillery.feeds.poller import derive_all_tags

        kw_map = {"authentication": "domain/authentication"}
        item = self._make_item(
            "https://example.com/rss",
            "rss",
            content="authentication token management",
        )
        tags = derive_all_tags(item, "rss", kw_map)
        source_indices = [i for i, t in enumerate(tags) if t.startswith("source/")]
        topic_indices = [i for i, t in enumerate(tags) if not t.startswith("source/")]
        if source_indices and topic_indices:
            assert max(source_indices) < min(topic_indices)

    def test_deduplication_across_tiers(self) -> None:
        """A tag present in both source and topic tiers appears only once."""
        from distillery.feeds.poller import derive_all_tags

        # keyword_map maps "rss" -> "source/rss" — same as a source tag
        kw_map = {"rss": "source/rss"}
        item = self._make_item("https://example.com/rss", "rss", title="rss feeds are great")
        tags = derive_all_tags(item, "rss", kw_map)
        assert tags.count("source/rss") == 1

    def test_empty_keyword_map_returns_source_tags_only(self) -> None:
        """Empty keyword map still returns source tags."""
        from distillery.feeds.poller import derive_all_tags

        item = self._make_item(
            "https://github.com/owner/repo", "github", title="New release"
        )
        tags = derive_all_tags(item, "github", {})
        assert "source/github" in tags
        assert "source/github/owner/repo" in tags
