# T04 Proof Summary: Interest Extractor & Source Recommender

**Task**: T04 - Interest Extractor & Source Recommender
**Completed**: 2026-03-28
**Model**: sonnet

## Summary

Implemented `InterestExtractor` and `InterestProfile` in
`src/distillery/feeds/interests.py`, plus two new MCP tools
(`distillery_interests`, `distillery_suggest_sources`) in
`src/distillery/mcp/server.py`.

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T04-01-test.txt | test | PASS |
| T04-02-import.txt | cli | PASS |

## What Was Implemented

### `src/distillery/feeds/interests.py`

- **`InterestProfile`** dataclass with fields:
  - `top_tags`: recency-weighted `(tag, normalised_weight)` pairs
  - `bookmark_domains`: domains from bookmark entries
  - `tracked_repos`: GitHub `owner/repo` identifiers
  - `expertise_areas`: topics from person entries
  - `watched_sources`: exclusion list from `FeedsConfig`
  - `suggestion_context`: LLM-ready prose paragraph
  - `entry_count`, `generated_at`

- **`InterestExtractor`** class:
  - Paginates `list_entries` (default 200/page, max 2000 entries)
  - Applies hard cutoff at `recency_days * 3`
  - Recency weights: full (1.0) within 14 days, linear decay to 0.1 at `recency_days`
  - Extracts tags (weighted), bookmark domains, GitHub repos, expertise areas
  - Builds suggestion_context prose paragraph

### `src/distillery/mcp/server.py`

- **`distillery_interests`** tool:
  - Parameters: `recency_days` (default 90), `top_n` (default 20)
  - Returns JSON with profile fields

- **`distillery_suggest_sources`** tool:
  - Parameters: `max_suggestions`, `source_types` filter, `recency_days`, `top_n`
  - Derives GitHub suggestions from tracked repos
  - Derives RSS suggestions from bookmark domains
  - Excludes already-watched sources

- **`_handle_interests`** and **`_handle_suggest_sources`** handlers (testable without MCP context)

### `tests/test_interests.py`

43 unit tests covering all classes, methods, and tool handlers.

## Test Results

- 43/43 tests in `test_interests.py` PASS
- 695/695 unit tests in full suite PASS
- `ruff check`: clean
- `mypy --strict` on new files: clean
