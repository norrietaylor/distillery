"""Feed adapters for Distillery ambient monitoring.

This package provides adapter implementations that poll external sources and
normalise their output to :class:`~distillery.feeds.models.FeedItem`.

Supported adapters:

- :class:`~distillery.feeds.github.GitHubAdapter` — polls GitHub repository
  events via the ``/repos/{owner}/{repo}/events`` REST endpoint.
- :class:`~distillery.feeds.rss.RSSAdapter` — parses RSS 2.0 and Atom feeds
  via the standard library :mod:`xml.etree.ElementTree`.

Scoring and polling:

- :class:`~distillery.feeds.scorer.RelevanceScorer` — scores a feed item
  against the knowledge base using cosine similarity.
- :class:`~distillery.feeds.poller.FeedPoller` — polls all configured sources,
  scores items, and stores those above the relevance threshold.
"""

from distillery.feeds.github import GitHubAdapter
from distillery.feeds.models import FeedItem
from distillery.feeds.poller import FeedPoller, PollerSummary, PollResult
from distillery.feeds.rss import RSSAdapter
from distillery.feeds.scorer import RelevanceScorer

__all__ = [
    "FeedItem",
    "FeedPoller",
    "GitHubAdapter",
    "PollerSummary",
    "PollResult",
    "RelevanceScorer",
    "RSSAdapter",
]
