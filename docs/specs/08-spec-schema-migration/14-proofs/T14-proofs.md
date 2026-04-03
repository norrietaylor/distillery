# T14: Export/Import Tests and Round-Trip Verification — Proof Summary

## Task

T03.3: Create `tests/test_cli_export_import.py` with comprehensive tests covering
export JSON structure, embedding exclusion, merge/replace modes, embedding
recomputation, malformed-JSON error handling, round-trip fidelity, feed source
import de-duplication, and replace-mode confirmation prompt.

## Files Modified

- `tests/test_cli_export_import.py` — created (10 new tests)
- `src/distillery/store/duckdb.py` — added missing imports for
  `_CREATE_META_TABLE` and `run_pending_migrations` from `migrations.py`
  (pre-existing bug from T02.3 that blocked store initialization)
- `src/distillery/cli.py` — fixed metadata JSON-string serialization in
  `_cmd_export` (DuckDB returns JSON columns as strings; the fix parses them
  back to dicts before writing the export file, enabling round-trip fidelity)
- `tests/test_cloud_storage.py` — updated `TestSyncInitializeHttpfs` mocks to
  patch `run_pending_migrations` instead of removed methods (from T02.3 stash)
- `tests/test_store_migration.py` — updated `test_meta_schema_version_after_init`
  to assert `max(MIGRATIONS)` instead of `'0'` (from T02.3 stash)

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T14-01-test.txt | test (new test file) | PASS |
| T14-02-test.txt | test (full suite) | PASS |

## Test Coverage (10 tests in test_cli_export_import.py)

1. `test_export_creates_valid_json` — export from a seeded 2-entry store; verifies JSON structure and required fields
2. `test_export_excludes_embeddings` — verifies no "embedding" key in exported entries
3. `test_import_merge_skips_existing` — same entry imported twice in merge mode; second pass reports 0 imported, 1 skipped
4. `test_import_merge_adds_new` — merging payload with existing + new ID; only new entry imported
5. `test_import_replace_drops_existing` — 3 pre-seeded entries deleted; only 2 replacement entries remain
6. `test_import_recomputes_embeddings` — verifies zero NULL embeddings after import
7. `test_import_malformed_json` — garbage input returns exit code 1
8. `test_roundtrip_fidelity` — export → replace import → re-export; entries match (excluding timestamps)
9. `test_import_feed_sources_merge` — feed sources added on first import; 0 added on re-import (duplicates silently skipped)
10. `test_import_replace_requires_confirmation` — replace without `--yes` with EOF input returns 0 (cancelled, not error)

## Pre-existing Bugs Fixed

1. **Missing imports in duckdb.py**: T02.3 refactored `_sync_initialize` to use `run_pending_migrations` from `migrations.py` but forgot to add the import. Result: `NameError: name '_CREATE_META_TABLE' is not defined` on every store initialization. Fixed by adding the import.

2. **Metadata serialization in export**: DuckDB returns JSON columns as Python strings. The export code was writing these strings directly to the JSON file, producing `"metadata": "{}"` instead of `"metadata": {}`. On re-import, `dict('{}')` fails with a TypeError. Fixed by parsing metadata strings back to dicts in the export path.
