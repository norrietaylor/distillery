"""Feed adapters for Distillery ambient monitoring.

This package provides adapter implementations that poll external sources and
normalise their output to :class:`~distillery.feeds.models.FeedItem`.

Supported adapters:

- :class:`~distillery.feeds.github.GitHubAdapter` — polls GitHub repository
  events via the ``/repos/{owner}/{repo}/events`` REST endpoint.
- :class:`~distillery.feeds.rss.RSSAdapter` — parses RSS 2.0 and Atom feeds
  via the standard library :mod:`xml.etree.ElementTree`.
"""

from distillery.feeds.github import GitHubAdapter
from distillery.feeds.models import FeedItem
from distillery.feeds.rss import RSSAdapter

__all__ = ["FeedItem", "GitHubAdapter", "RSSAdapter"]
