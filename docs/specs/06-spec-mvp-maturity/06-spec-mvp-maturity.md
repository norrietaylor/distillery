# 06-spec-mvp-maturity

## Introduction/Overview

This spec addresses the four remaining MVP items from the Distillery roadmap: retrieval quality measurement, content lifecycle management, conflict detection, and usage metrics. Together these features close the gap between "feature-complete" and "production-ready" for single-user validation, establishing the operational maturity needed before Phase 2 team expansion.

## Goals

1. Track implicit retrieval feedback so search quality can be measured and improved over time
2. Detect stale entries and surface them for manual archive review
3. Warn users when newly stored content contradicts existing entries
4. Provide a metrics dashboard tool for monitoring system health and usage patterns
5. Add configurable thresholds for staleness and conflict detection to `distillery.yaml`

## User Stories

- As a **user**, I want to know when my search results are getting better or worse over time so I can adjust my knowledge capture habits.
- As a **user**, I want to see which entries are stale so I can archive outdated knowledge before it pollutes search results.
- As a **user**, I want to be warned when I store something that contradicts an existing entry so I can resolve the conflict immediately.
- As a **user**, I want a metrics overview so I can understand how I'm using the knowledge base and whether it's working well.

## Demoable Units of Work

### Unit 1: Implicit Retrieval Feedback

**Purpose:** Track which search results are actually useful by recording implicit signals — when an entry returned by search is subsequently referenced (via `distillery_get`) within a configurable time window, that counts as a positive signal.

**Functional Requirements:**

- The system shall add a `search_log` table in DuckDB with columns: `id` (UUID), `query` (text), `result_entry_ids` (list), `result_scores` (list), `timestamp` (datetime), `session_id` (optional text)
- The system shall log every `distillery_search` call to `search_log` with query, returned entry IDs, and their scores
- The system shall add a `feedback_log` table with columns: `id` (UUID), `search_id` (FK), `entry_id` (text), `signal` (enum: positive/negative), `timestamp` (datetime)
- When `distillery_get` is called within 5 minutes of a search that returned that entry, the system shall automatically record a positive feedback signal
- The feedback time window shall be configurable via `classification.feedback_window_minutes` in `distillery.yaml` (default: 5)
- The system shall provide a `distillery_quality` MCP tool that returns aggregate quality metrics: total searches, total feedback signals, positive rate, average result count, and per-entry-type breakdown
- The `search_log` and `feedback_log` tables shall be created during `DuckDBStore.initialize()` alongside existing tables
- The store protocol shall add `log_search()` and `log_feedback()` async methods

**Proof Artifacts:**
- Test: `tests/test_feedback.py` passes — covers search logging, implicit feedback recording, time window expiry, and quality metrics aggregation
- CLI: `distillery_quality` MCP tool returns `{"total_searches": N, "positive_rate": 0.X, ...}` after storing and searching entries
- Test: Feedback is NOT recorded when `distillery_get` is called more than 5 minutes after search

### Unit 2: Stale Entry Detection

**Purpose:** Surface entries that haven't been accessed or updated recently so users can decide whether to archive them, preventing knowledge base decay.

**Functional Requirements:**

- The system shall add an `accessed_at` column to the `entries` table (nullable datetime, updated on `get`, `search` hit, `update`)
- For existing entries without `accessed_at`, the system shall fall back to `updated_at` for staleness calculation
- The system shall provide a `distillery_stale` MCP tool that returns entries not accessed within a configurable number of days
- `distillery_stale` shall accept optional parameters: `days` (default: 30), `limit` (default: 20), `entry_type` (optional filter)
- Each result from `distillery_stale` shall include: `id`, `content_preview` (200 chars), `entry_type`, `author`, `project`, `last_accessed` (accessed_at or updated_at fallback), `days_since_access`
- The staleness threshold default (30 days) shall be configurable via `classification.stale_days` in `distillery.yaml`
- The system shall NOT auto-archive stale entries — this is manual review only
- `DuckDBStore.get()` and `DuckDBStore.search()` shall update `accessed_at` on retrieved entries

**Proof Artifacts:**
- Test: `tests/test_stale.py` passes — covers staleness detection, accessed_at updates on get/search, day threshold filtering, and fallback to updated_at
- CLI: `distillery_stale` returns entries older than 30 days with `days_since_access` field
- Test: Entry accessed via search has its `accessed_at` updated and no longer appears in stale results

### Unit 3: Conflict Detection on Store

**Purpose:** When storing a new entry, detect potential contradictions with existing entries and return warnings alongside the dedup warnings already provided by `distillery_store`.

**Functional Requirements:**

- The system shall add a `ConflictChecker` class in `src/distillery/classification/conflict.py` that detects semantic contradictions
- `ConflictChecker` shall use `store.find_similar()` to find topically related entries (similarity >= configurable threshold, default 0.60)
- For each similar entry, `ConflictChecker` shall use the `ClassificationEngine` prompt pattern to ask the LLM whether the new content contradicts the existing entry
- `ConflictChecker.check()` shall return a `ConflictResult` dataclass with: `has_conflicts` (bool), `conflicts` (list of `ConflictEntry`), where each `ConflictEntry` has: `entry_id`, `content_preview`, `similarity_score`, `conflict_reasoning`
- The `distillery_store` MCP tool shall call `ConflictChecker.check()` after the existing dedup check and include conflict warnings in the response under a `conflicts` key
- Conflict checking shall be non-fatal — if it fails, the entry is still stored (same pattern as dedup)
- The conflict similarity threshold shall be configurable via `classification.conflict_threshold` in `distillery.yaml` (default: 0.60)
- The system shall provide a `distillery_check_conflicts` MCP tool for checking content against existing entries without storing
- `ConflictChecker` shall accept the LLM response as a parameter (it does not call the LLM itself — the MCP handler builds the prompt and the caller provides the response, matching the existing `ClassificationEngine` pattern)

**Proof Artifacts:**
- Test: `tests/test_conflict.py` passes — covers conflict detection with mock LLM responses, no-conflict cases, non-fatal failure handling
- Test: `distillery_store` response includes `conflicts` key when contradictions are detected
- Test: `distillery_check_conflicts` MCP tool returns conflict analysis for given content

### Unit 4: Usage Metrics Dashboard

**Purpose:** Provide a `distillery_metrics` MCP tool that aggregates usage statistics and quality signals into a single dashboard view for monitoring system health.

**Functional Requirements:**

- The system shall provide a `distillery_metrics` MCP tool that returns a comprehensive metrics object
- The metrics object shall include:
  - `entries`: total count, count by type, count by status, count by source
  - `activity`: entries created in last 7/30/90 days, entries updated in last 7/30/90 days
  - `search`: total searches (from `search_log`), searches in last 7/30 days, average results per search
  - `quality`: positive feedback rate, total feedback signals, feedback signals in last 30 days
  - `staleness`: count of entries not accessed in 30+ days, count by entry type
  - `storage`: database file size, embedding model, embedding dimensions
- The tool shall accept an optional `period_days` parameter (default: 30) that adjusts the "recent" window for activity and search metrics
- The metrics tool shall be read-only and not modify any data
- All date-based metrics shall use UTC timestamps consistently
- The tool shall work even if `search_log`/`feedback_log` tables have no data (return zeros)

**Proof Artifacts:**
- Test: `tests/test_metrics.py` passes — covers all metric categories, empty database case, period_days parameter, date-range filtering
- CLI: `distillery_metrics` returns JSON with all specified top-level keys (`entries`, `activity`, `search`, `quality`, `staleness`, `storage`)
- Test: Metrics correctly reflect entry counts, search activity, and staleness after populating test data

## Non-Goals (Out of Scope)

- Auto-archival of stale entries — this spec only surfaces candidates for manual review
- Retrieval quality tuning or prompt optimization — this spec only establishes the measurement baseline
- LLM-based conflict resolution — this spec detects and warns about conflicts, not resolves them
- Historical trend storage — metrics are computed on-the-fly, not stored as time-series
- Explicit thumbs-up/down feedback — only implicit signals (search → get correlation) are tracked
- Conflict detection on search results — only on store

## Design Considerations

- Conflict warnings in `distillery_store` response use the same structure as dedup warnings for consistency
- Metrics output is JSON, matching existing MCP tool response patterns
- Stale entry results match the structure of `distillery_review_queue` for UI consistency
- No new CLI commands — all features are MCP tools accessible via Claude Code skills

## Repository Standards

- Conventional Commits: `feat(store):`, `feat(mcp):`, `test(feedback):`, `test(stale):`
- Scopes: `store`, `mcp`, `classification`, `config`
- mypy strict for `src/`, relaxed for `tests/`
- ruff with existing rule set
- Shared `conftest.py` fixtures for new test modules
- All async tests use `asyncio_mode = "auto"`

## Technical Considerations

- `search_log` and `feedback_log` tables are append-only — no UPDATE operations needed
- `accessed_at` updates in `get()`/`search()` use the existing `asyncio.to_thread()` pattern
- Conflict detection prompt follows the same template pattern as `ClassificationEngine._CLASSIFY_PROMPT`
- The feedback time window correlation uses in-memory state in the MCP server `_state` dict (a list of recent search IDs with timestamps, pruned on each `distillery_get` call)
- Schema migration: `accessed_at` column added via `ALTER TABLE entries ADD COLUMN IF NOT EXISTS` during `initialize()`
- `ConflictChecker` does NOT call the LLM directly — it builds a prompt and parses a response, matching the existing `ClassificationEngine` pattern where the MCP handler orchestrates the LLM call

## Security Considerations

- `search_log` contains query text — may reveal user intent patterns. Acceptable for single-user local deployment.
- `feedback_log` is low-sensitivity (just entry IDs and timestamps)
- No new API keys or external services required
- Conflict detection reuses existing `find_similar()` — no new embedding API calls beyond what dedup already does

## Success Metrics

- After 1 week of usage, `distillery_quality` reports a positive feedback rate above 0.0 (feedback is being captured)
- `distillery_stale` surfaces entries that the user confirms are indeed outdated
- `distillery_store` warns about at least one real contradiction during normal usage
- `distillery_metrics` provides a meaningful snapshot of system health on demand

## Open Questions

- No open questions at this time.
