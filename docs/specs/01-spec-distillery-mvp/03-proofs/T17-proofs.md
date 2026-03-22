# T03.4 Proof Summary: Integrate embedding into DuckDBStore and add _meta table

## Task
Wire the configured EmbeddingProvider into DuckDBStore so that store() generates
embeddings before inserting, and search()/find_similar() embed the query text
before vector search. Add a _meta table that stores the embedding model name and
dimensions, with mismatch detection on startup.

## Proof Artifacts

| # | Type | File | Status |
|---|------|------|--------|
| 1 | test | T17-01-test.txt | PASS |
| 2 | cli  | T17-02-cli.txt  | PASS |
| 3 | file | T17-03-file.txt | PASS |

## Summary

### T17-01-test.txt
Full pytest run of `tests/test_duckdb_store.py` -- 68 tests all passing.
Tests cover store, get, update, delete, search, find_similar, and list_entries,
all now exercising the real embedding path via a mock provider.

### T17-02-cli.txt
Custom integration script verifying:
- _meta table records model name and dimensions on first use
- RuntimeError raised when reopening DB with mismatched model
- store() generates real embeddings (not zero placeholders)
- update() re-embeds content when content field changes
- search() and find_similar() embed query text before vector search

### T17-03-file.txt
Code structure verification confirming all required integration points
exist in `src/distillery/store/duckdb.py`.

## Changes Made

### Modified: `src/distillery/store/duckdb.py`
- Added `_CREATE_META_TABLE` SQL constant
- Added `_create_meta_table()` method
- Added `_validate_or_record_meta()` method with model/dimensions mismatch detection
- Updated `_sync_initialize()` to call meta table creation and validation
- Replaced placeholder zero-vector in `_sync_store()` with `self._embedding_provider.embed()`
- Added re-embedding in `_sync_update()` when content changes
- `search()` and `find_similar()` already called `embed()` (from T02.4)

## Result
All requirements satisfied. All 68 existing tests pass. Integration tests confirm
_meta table functionality and embedding wiring.
