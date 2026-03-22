# T02 Proof Artifacts: MCP Server Extensions

## Summary

Task T02 adds three new MCP tools to expose classification and review queue
operations: `distillery_classify`, `distillery_review_queue`, and
`distillery_resolve_review`.

## Artifacts

| File | Type | Status |
|------|------|--------|
| T02-01-test.txt | test | PASS |
| T02-02-test.txt | test | PASS |
| T02-03-file.txt | file | PASS |

## What Was Implemented

### distillery_classify
- Accepts `entry_id`, `entry_type`, `confidence`, optional `reasoning`,
  `suggested_tags`, `suggested_project`
- Retrieves the entry; returns NOT_FOUND if missing
- Sets `entry_type` and `status` (active if confidence >= threshold,
  pending_review otherwise) using `config.classification.confidence_threshold`
- Merges `suggested_tags` with existing tags (no duplicates)
- Sets `suggested_project` only when the entry has no existing project
- Stores classification metadata: `confidence`, `classified_at`,
  `classification_reasoning`
- Records `reclassified_from` when the entry was already classified

### distillery_review_queue
- Returns `pending_review` entries sorted by `created_at` descending
- Supports optional `entry_type` filter and `limit` parameter
- Each result includes: `id`, `content_preview` (200 chars), `entry_type`,
  `confidence`, `author`, `created_at`, `classification_reasoning`

### distillery_resolve_review
- Accepts `entry_id`, `action` (approve/reclassify/archive), optional
  `new_entry_type` (required for reclassify), optional `reviewer`
- `approve`: sets `status=active`, records `reviewed_at`/`reviewed_by`
- `reclassify`: updates `entry_type`, sets `reclassified_from` + `reviewed_at`
- `archive`: sets `status=archived`, records `archived_at`/`archived_by`

## Test Coverage

27 new tests in `tests/test_mcp_classify.py`:
- 10 tests for `distillery_classify` (happy path, error cases, edge cases)
- 7 tests for `distillery_review_queue` (filtering, shape, validation)
- 10 tests for `distillery_resolve_review` (all 3 actions, validation, edge cases)
- 1 end-to-end test: classify -> review_queue -> resolve_review

All 366 tests in the full suite pass with no regressions.
