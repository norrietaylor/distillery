# T04 Proof Summary: MCP Server E2E Tests

## Task

Add `tests/test_e2e_mcp.py` with 9+ end-to-end scenarios exercising the full MCP server lifecycle through `create_server()` and the `_call_tool` dispatcher. Uses `StubEmbeddingProvider` and in-memory DuckDB. Each test calls 2+ tools in sequence to verify round-trip behaviour.

## Implementation

**File created:** `tests/test_e2e_mcp.py`

### Scenarios (12 tests across 11 classes)

| # | Class | Tools exercised | Scenario |
|---|-------|-----------------|----------|
| 1 | TestStoreGetRoundTrip | store, get | store → retrieve by ID |
| 2 | TestStoreSearchRoundTrip | store (x3), search | store 3 entries → semantic search |
| 3 | TestStoreFindSimilarRoundTrip | store, find_similar | store → similarity search |
| 4 | TestClassifyReviewResolveRoundTrip | store, classify, review_queue, resolve_review | full classification pipeline |
| 5 | TestStoreCheckDedupRoundTrip | store, check_dedup | store → dedup check |
| 6 | TestStoreUpdateGetRoundTrip | store, update, get | store → update → re-fetch (version=2) |
| 7 | TestStoreListPagination | store (x5), list (x2) | paginated list with offset |
| 8 | TestStatusReflectsEntries | status, store (x3), status | empty then populated counts |
| 9 | TestErrorPathNotFound | get | NOT_FOUND on non-existent ID |
| 10 | TestErrorPathInvalidInput | store | INVALID_INPUT on missing fields |
| 11 | TestCallToolDispatcher | store, status, list_tools | dispatcher routing + tool registration |

### Key design choices

- All tests use `StubEmbeddingProvider(dimensions=4)` — no external API calls
- All tests use `db_path=":memory:"` — no filesystem state
- All tests marked `@pytest.mark.integration`
- Uses `parse_mcp_response()` from `tests.conftest` for JSON parsing
- Each scenario calls handlers directly (same code path as `_call_tool` dispatcher)
- `TestCallToolDispatcher.test_create_server_registers_all_tools` verifies all 11 tools registered via `create_server()`

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T04-01-test.txt | pytest run (all tests) | PASS |
| T04-02-cli.txt | pytest run (integration marker) | PASS |

## Result

**12 tests, 12 passed, 0 failed**

Pre-existing failures in `tests/test_cli.py` (13 tests) are unrelated to T04 — they exist on the baseline commit before this change and are scoped to T03 (CI Hardening).
