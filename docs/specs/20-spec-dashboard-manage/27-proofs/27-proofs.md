# Task 27 Proof Summary

**Task**: FIX-REVIEW: Badge counts not wired to auto-refresh + missing project filter
**Status**: COMPLETED
**Timestamp**: 2026-04-10T08:58:36Z

## Changes Made

File modified: `dashboard/src/App.svelte`

1. Added `selectedProject` to the imports from `$lib/stores`.
2. Updated `refreshBadgeCounts()` to read `$selectedProject` and pass `project` argument to both `callTool` calls when a project is selected (non-null).
3. Added `refreshBadgeCounts()` call inside the `setInterval` callback in `startAutoRefresh()`, alongside the existing `triggerRefresh()` call.

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| 27-01-test.txt | test (vitest) | PASS |

## Test Results

- 10 test files, 260 tests — all passed.
- No regressions introduced.
