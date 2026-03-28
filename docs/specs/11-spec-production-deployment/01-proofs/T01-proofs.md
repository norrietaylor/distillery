# T01: Application Resilience - Proof Summary

## Task
Make DuckDBStore resilient to missing VSS extension and transient connection failures. Add /health endpoint.

## Proof Artifacts

| # | Type | File | Status | Description |
|---|------|------|--------|-------------|
| 1 | test | T01-01-test.txt | PASS | 8 resilience-specific tests covering VSS degradation, brute-force search, retry logic, and /health endpoint |
| 2 | cli | T01-02-cli.txt | PASS | ruff check + mypy --strict pass with zero errors |
| 3 | test | T01-03-test.txt | PASS | Full test suite (1057 tests) passes with no regressions |

## Changes Made

1. **VSS graceful degradation** (`src/distillery/store/duckdb.py`):
   - `_setup_vss()` wrapped in try-except; sets `self._vss_available` flag
   - Added `vss_available` property

2. **HNSW index skip** (`src/distillery/store/duckdb.py`):
   - `_create_index()` skips HNSW creation when `_vss_available` is False
   - Logs warning: "HNSW index not created, falling back to brute-force search"

3. **Brute-force search** (verified, no code change needed):
   - `array_cosine_similarity` is a DuckDB core function, not part of VSS
   - `search()` and `find_similar()` work without HNSW index

4. **Transient connection retry** (`src/distillery/store/duckdb.py`):
   - Outer retry loop (3 attempts) for IOException, ConnectionException, HTTPException
   - Exponential backoff: 1s, 2s, 4s

5. **Health endpoint** (`src/distillery/mcp/server.py`):
   - `GET /health` via FastMCP `custom_route` (outside auth-protected MCP path)
   - Returns `{status, vss_available, store_initialized, database_path}`

## Test Coverage

- `test_vss_unavailable_graceful_degradation` - Feature Scenario 1
- `test_hnsw_index_skipped_when_vss_unavailable` - Feature Scenario 2
- `test_search_without_hnsw_index` - Feature Scenario 3
- `test_find_similar_without_hnsw_index` - Feature Scenario 4
- `test_connection_retry_on_transient_error` - Feature Scenario 5
- `test_retry_exhausted_with_exponential_backoff` - Feature Scenario 6
- `test_health_endpoint` - Feature Scenarios 7-8
- `test_health_endpoint_no_auth_required` - Feature Scenario 9
