# T01 Proof Summary — Feed Configuration & Source Registry

**Task:** T01: Feed Configuration & Source Registry
**Date:** 2026-03-27
**Status:** PASS

## Requirements Implemented

1. **EntryType.FEED** — Added `FEED = "feed"` to the `EntryType` enum in `src/distillery/models.py`. Updated the ClassificationEngine prompt to include the `feed` category.

2. **Feed metadata schema** — Added `"feed"` entry to `TYPE_METADATA_SCHEMAS` with:
   - Required: `source_url` (str), `source_type` (str)
   - Optional: `title` (str), `item_url` (str), `published_at` (str), `relevance_score` (float)
   - Constraints: `source_type` must be one of `["rss", "github", "hackernews", "webhook"]`

3. **FeedsConfig dataclass** — Added to `src/distillery/config.py`:
   - `FeedSourceConfig`: url, source_type, label, poll_interval_minutes (default 60), trust_weight (default 1.0)
   - `FeedsThresholdsConfig`: alert (default 0.85), digest (default 0.60)
   - `FeedsConfig`: sources (list of FeedSourceConfig), thresholds (FeedsThresholdsConfig)
   - Wired into `DistilleryConfig.feeds` with full YAML parsing and validation

4. **distillery_watch MCP tool** — Added to `src/distillery/mcp/server.py`:
   - `list` action: returns current sources with count
   - `add` action: validates and appends a new source to the in-memory registry
   - `remove` action: removes a source by exact URL match
   - All actions include persistence note in the response

5. **/watch skill** — Created `.claude/skills/watch/SKILL.md` with list/add/remove subcommands, output format, and rules.

6. **distillery.yaml.example** — Added `feeds` section with thresholds, sources, and comprehensive inline comments.

## Proof Artifacts

| # | File | Type | Status |
|---|------|------|--------|
| 1 | T01-01-test.txt | test | PASS |
| 2 | T01-02-cli.txt | cli | PASS |

## Test Coverage

- **New test file:** `tests/test_watch.py` — 34 unit tests covering:
  - `EntryType.FEED` enum value and schema registration
  - Feed metadata validation (valid cases, missing required fields, invalid constraints)
  - `_handle_watch` list, add, remove actions with all edge cases
- **Extended test file:** `tests/test_config.py` — 15 new unit tests covering:
  - `FeedsConfig` defaults with no YAML present
  - YAML loading of feeds section (sources, thresholds)
  - Validation errors (invalid source_type, missing url, negative poll interval, trust_weight out of range, alert < digest)
- **Eval scenarios:** `tests/eval/scenarios/watch.yaml` — 5 scenarios for the `/watch` skill

**Total tests added:** 50 (from 544 baseline to 594)

## Files Modified

- `src/distillery/models.py` — EntryType.FEED enum value, feed metadata schema, docstring update
- `src/distillery/config.py` — FeedSourceConfig, FeedsThresholdsConfig, FeedsConfig dataclasses, _parse_feed_source, _parse_feeds, _validate updates, load_config update
- `src/distillery/mcp/server.py` — distillery_watch tool registration, _handle_watch handler, FeedSourceConfig import
- `src/distillery/classification/engine.py` — Added `feed` to the classification prompt

## Files Created

- `.claude/skills/watch/SKILL.md` — /watch skill definition
- `tests/test_watch.py` — Unit tests for feed entry type and distillery_watch handler
- `tests/eval/scenarios/watch.yaml` — Eval scenarios for /watch skill
- `distillery.yaml.example` — Updated with feeds section
