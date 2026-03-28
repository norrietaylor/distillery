# T03 Proof Summary: Relevance Scoring & Background Poller

## Task

Add `RelevanceScorer`, `FeedPoller`, `distillery_poll` MCP tool, and `distillery poll` CLI command.

## Implementation

### Files Created
- `src/distillery/feeds/scorer.py` — `RelevanceScorer` class: embeds item text via `find_similar`, returns max similarity score
- `src/distillery/feeds/poller.py` — `FeedPoller`, `PollResult`, `PollerSummary` classes; iterates sources, polls adapters, deduplicates (threshold 0.95), scores items, stores above threshold
- `tests/test_poller.py` — 28 unit tests covering scorer, poller, MCP handler, and CLI command

### Files Modified
- `src/distillery/feeds/__init__.py` — exports `RelevanceScorer`, `FeedPoller`, `PollResult`, `PollerSummary`
- `src/distillery/mcp/server.py` — added `distillery_poll` tool and `_handle_poll` handler
- `src/distillery/cli.py` — added `poll` subcommand with `--source` flag and `_cmd_poll` handler
- `tests/test_mcp_server.py` — updated tool registry test to include feeds tools (pre-existing gap)
- `tests/test_e2e_mcp.py` — updated tool registry test to include feeds tools (pre-existing gap)

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T03-01-test.txt | pytest run of tests/test_poller.py | PASS |
| T03-02-import.txt | import verification of all new symbols | PASS |

## Test Results

28/28 tests passed in `tests/test_poller.py`.
Full suite: 1021 passed, 41 skipped.

## Key Design Decisions

- `RelevanceScorer.score()` returns max cosine similarity from `find_similar(threshold=0.0)` — callers apply their own thresholds
- `FeedPoller` deduplicates at `0.95` similarity threshold (matching `config.classification.dedup_skip_threshold`)
- Items with no title or content (empty text) are counted as `below_threshold` rather than `skipped_dedup`
- `trust_weight` from `FeedSourceConfig` multiplies the raw relevance score before threshold comparison
- `_handle_poll` with `source_url` filter creates a shallow config copy narrowed to that source
- CLI `poll` command follows the same pattern as `status` and `health` with `--format json` support
