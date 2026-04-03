# T02.3 Proof Summary: Refactor _sync_initialize to use migration system

## Task

Replace the ad-hoc initialization calls in `DuckDBStore._sync_initialize()` with `run_pending_migrations()` from `migrations.py`.

## Changes

1. **`src/distillery/store/duckdb.py`**:
   - Added import of `_CREATE_META_TABLE`, `run_pending_migrations` from `distillery.store.migrations`
   - Removed 9 SQL constant definitions (now in `migrations.py`)
   - Removed 7 helper methods (`_create_schema`, `_create_index`, `_create_meta_table`, `_create_log_tables`, `_create_feed_sources_table`, `_add_accessed_at_column`, `_add_ownership_columns`)
   - Refactored `_sync_initialize()` to: bootstrap `_meta` table, call `run_pending_migrations()`, validate embedding meta, track version info
   - Simplified `_track_version_info()` to only handle DuckDB/VSS version tracking (schema_version now managed by migration runner)

2. **`tests/test_cloud_storage.py`**:
   - Updated 5 test methods in `TestSyncInitializeHttpfs` to patch `run_pending_migrations` instead of the removed helper methods

3. **`tests/test_store_migration.py`**:
   - Updated `test_meta_schema_version_default_zero` -> `test_meta_schema_version_after_init` to expect version 6 (latest migration) instead of 0

## Proof Artifacts

| # | File | Type | Status |
|---|------|------|--------|
| 1 | T10-01-test.txt | test | PASS (121 passed) |
| 2 | T10-02-mypy.txt | mypy | PASS (no issues) |
| 3 | T10-03-regression.txt | cli | PASS (old methods removed, new flow verified) |
