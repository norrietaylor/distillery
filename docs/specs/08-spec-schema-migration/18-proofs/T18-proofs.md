# Task 18 Proof Summary

## Task: FIX-REVIEW: Export omits created_by and last_modified_by columns (data loss)

## Fix Applied

In `src/distillery/cli.py`, added `created_by` and `last_modified_by` to:
1. The SELECT query (line 559-560): now includes both columns after `updated_at`
2. The `entry_cols` list (lines 562-565): now includes both columns as the 13th and 14th elements

## Root Cause

The export function only selected 12 columns, omitting `created_by` and `last_modified_by`. Since the import side used `.get("created_by", "")` with a default of empty string, a round-trip would silently reset these fields to empty string, causing data loss.

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T18-01-test.txt | pytest run (19 export/import tests) | PASS |
| T18-02-cli.txt | grep showing fix in place | PASS |

## Verification

All 19 export/import tests pass, including `test_roundtrip_fidelity` which verifies that `created_by` and `last_modified_by` survive an export-import cycle (these fields are not in the `volatile_fields` exclusion set, so they must match exactly).
