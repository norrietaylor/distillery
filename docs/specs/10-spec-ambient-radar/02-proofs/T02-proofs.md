# T02 Proof Summary — GitHub Adapter & RSS Adapter

**Task:** T02: GitHub Adapter & RSS Adapter
**Date:** 2026-03-27
**Status:** PASS

## Requirements Implemented

1. **`src/distillery/feeds/` package** — Created the `feeds` package with:
   - `__init__.py` re-exporting `FeedItem`, `GitHubAdapter`, `RSSAdapter`
   - `models.py` — `FeedItem` dataclass
   - `github.py` — `GitHubAdapter` class
   - `rss.py` — `RSSAdapter` class

2. **FeedItem dataclass** (`src/distillery/feeds/models.py`):
   - Fields: `source_url`, `source_type`, `item_id` (required); `title`, `url`, `content`, `published_at`, `raw`, `extra` (optional)
   - `raw` field excluded from equality comparisons (`compare=False`)
   - All adapters normalise to this single canonical structure

3. **GitHubAdapter** (`src/distillery/feeds/github.py`):
   - Polls `GET /repos/{owner}/{repo}/events` via `httpx`
   - Accepts URL forms: `owner/repo` slug, `https://github.com/owner/repo`, `https://api.github.com/repos/owner/repo`
   - Optional PAT via constructor or `GITHUB_TOKEN` env var
   - Normalises events to `FeedItem` (item_id, title, url, content, published_at, extra)
   - Tracks `last_polled_at: datetime | None`

4. **RSSAdapter** (`src/distillery/feeds/rss.py`):
   - Fetches feed URL with `httpx` and parses via stdlib `xml.etree.ElementTree`
   - Supports RSS 2.0 (auto-detects `<rss>` root) and Atom 1.0 (auto-detects `<feed xmlns=...>`)
   - Extracts: title, link/href, content/description/summary, guid/id, pubDate/published
   - Derives stable SHA-256 prefix item_id when `<guid>` / `<id>` absent
   - Tracks `last_polled_at: datetime | None`

## Proof Artifacts

| # | File | Type | Status |
|---|------|------|--------|
| 1 | T02-01-test.txt | test | PASS |
| 2 | T02-02-cli.txt | cli | PASS |

## Test Coverage

**New test file:** `tests/test_feeds.py` — 58 unit tests covering:
- `FeedItem` dataclass (required fields, defaults, equality semantics)
- `_parse_github_url` (slug, full URL, API URL, .git suffix, invalid, dots/hyphens)
- `_event_to_feed_item` (id, source, title, content, published_at, url derivation, extra, raw)
- `GitHubAdapter` init, `fetch()` with mocked httpx (returns items, updates last_polled_at, empty response, env token)
- `parse_feed_xml` RSS 2.0 (2 items, title/url/content/guid/pubDate/categories, stable id fallback)
- `parse_feed_xml` Atom 1.0 (2 entries, content vs summary, published vs updated)
- `RSSAdapter` (empty URL, fetch with mocked httpx for RSS and Atom, last_polled_at)

**Total tests added:** 58 (baseline 594 → 652 excluding pre-existing failures)

## Files Created

- `src/distillery/feeds/__init__.py` — package init
- `src/distillery/feeds/models.py` — FeedItem dataclass
- `src/distillery/feeds/github.py` — GitHubAdapter
- `src/distillery/feeds/rss.py` — RSSAdapter
- `tests/test_feeds.py` — 58 unit tests

## Pre-existing Failures (not introduced by T02)

- `tests/test_e2e_mcp.py::TestCallToolDispatcher::test_create_server_registers_all_tools` — expects 17 tools but `distillery_watch` (added by T01) is not in the expected set
- `tests/test_mcp_server.py::TestCreateServer::test_server_registers_all_tools` — expects `distillery_watch`, `distillery_interests`, `distillery_suggest_sources` (T01/T04 tools, test not yet updated)

Both failures pre-exist T02 and are owned by T01/T04 workers.
