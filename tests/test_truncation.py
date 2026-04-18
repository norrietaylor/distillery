"""Tests for the feed content truncation utilities.

Covers:
  - truncate_content: no-op for short text, truncation for long text
  - truncate_content: custom max_chars parameter
  - _item_text integration with truncation
  - Jina payload includes truncate: true
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from distillery.feeds.models import FeedItem
from distillery.feeds.poller import _item_text
from distillery.feeds.truncation import (
    _TRUNCATED_SUFFIX,
    MAX_CONTENT_CHARS,
    truncate_content,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# truncate_content
# ---------------------------------------------------------------------------


class TestTruncateContent:
    def test_short_text_unchanged(self) -> None:
        text = "Hello, world!"
        assert truncate_content(text) == text

    def test_exact_limit_unchanged(self) -> None:
        text = "a" * MAX_CONTENT_CHARS
        assert truncate_content(text) == text

    def test_over_limit_truncated(self) -> None:
        text = "a" * (MAX_CONTENT_CHARS + 500)
        result = truncate_content(text)
        assert len(result) == MAX_CONTENT_CHARS
        assert result.endswith(_TRUNCATED_SUFFIX)
        cutoff = MAX_CONTENT_CHARS - len(_TRUNCATED_SUFFIX)
        assert result[:cutoff] == "a" * cutoff

    def test_empty_text_unchanged(self) -> None:
        assert truncate_content("") == ""

    def test_custom_max_chars(self) -> None:
        text = "a" * 30  # 30 chars, will be truncated to 20
        result = truncate_content(text, max_chars=20)
        assert len(result) == 20
        assert result.endswith(_TRUNCATED_SUFFIX)

    def test_custom_max_chars_very_small(self) -> None:
        """When max_chars is smaller than the suffix, return truncated suffix."""
        text = "abcdefghij"
        result = truncate_content(text, max_chars=5)
        assert len(result) == 5
        assert result == _TRUNCATED_SUFFIX[:5]

    def test_custom_max_chars_no_truncation(self) -> None:
        text = "abc"
        result = truncate_content(text, max_chars=5)
        assert result == "abc"


# ---------------------------------------------------------------------------
# _item_text with truncation
# ---------------------------------------------------------------------------


class TestItemTextTruncation:
    def test_short_content_unchanged(self) -> None:
        item = FeedItem(
            source_url="https://example.com",
            source_type="rss",
            item_id="1",
            title="Short title",
            content="Short content",
        )
        result = _item_text(item)
        assert result == "Short title\nShort content"

    def test_long_content_truncated(self) -> None:
        long_content = "x" * (MAX_CONTENT_CHARS + 1000)
        item = FeedItem(
            source_url="https://example.com",
            source_type="rss",
            item_id="1",
            title="Title",
            content=long_content,
        )
        result = _item_text(item)
        assert result.endswith(_TRUNCATED_SUFFIX)
        # Title + newline + truncated content (which itself is <= MAX_CONTENT_CHARS)
        assert len(result) <= MAX_CONTENT_CHARS + len("Title\n")

    def test_truncation_can_be_disabled(self) -> None:
        long_content = "x" * (MAX_CONTENT_CHARS + 1000)
        item = FeedItem(
            source_url="https://example.com",
            source_type="rss",
            item_id="1",
            content=long_content,
        )
        result = _item_text(item, apply_truncation=False)
        assert len(result) == MAX_CONTENT_CHARS + 1000
        assert _TRUNCATED_SUFFIX not in result


# ---------------------------------------------------------------------------
# Jina payload includes truncate: true
# ---------------------------------------------------------------------------


class TestJinaTruncateFlag:
    def test_jina_payload_includes_truncate_true(self) -> None:
        """Verify that JinaEmbeddingProvider sends truncate: true in the API payload."""
        from distillery.embedding.jina import JinaEmbeddingProvider

        provider = JinaEmbeddingProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [{"embedding": [0.1] * 1024, "index": 0}],
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("distillery.embedding.jina.httpx.Client", return_value=mock_client):
            provider.embed("test text")

        # Extract the payload from the post call
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload is not None
        assert payload["truncate"] is True
