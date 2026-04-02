# T15 Proof Summary: Replace INVALID_INPUT/VALIDATION_ERROR with INVALID_PARAMS

## Task

T02.3 — Replace all string literals `"INVALID_INPUT"` and `"VALIDATION_ERROR"` passed to
`error_response()` in the MCP tool handler modules with `"INVALID_PARAMS"`, and update all
test assertions that check for the old codes.

## Artifacts

| File | Type | Status |
|------|------|--------|
| T15-01-test.txt | pytest (in-scope tests) | PASS — 86/86 |
| T15-02-test-full.txt | pytest (full suite) | PASS — 1217 passed, 61 skipped |
| T15-03-grep-old-codes.txt | grep absence check | PASS — no old codes in tool modules |

## Changes Made

### Tool modules (implementation)

- `src/distillery/mcp/tools/quality.py` — 5 occurrences replaced
- `src/distillery/mcp/tools/analytics.py` — 7 occurrences replaced
- `src/distillery/mcp/tools/crud.py` — 18 occurrences replaced (including docstring)
- `src/distillery/mcp/tools/classify.py` — 10 occurrences replaced
- `src/distillery/mcp/tools/search.py` — 6 occurrences replaced

### Test files (assertions and docstrings)

- `tests/test_mcp_server.py` — 10 assertions updated
- `tests/test_mcp_classify.py` — 9 assertions updated
- `tests/test_mcp_dedup.py` — 1 assertion updated
- `tests/test_conflict.py` — 2 assertions + 2 docstrings updated
- `tests/test_stale.py` — 2 assertions updated
- `tests/test_list_output_modes.py` — 5 assertions updated
- `tests/test_e2e_mcp.py` — 1 assertion + 3 comments updated
- `tests/test_metrics.py` — 1 assertion + 1 docstring updated

### Not changed

- `src/distillery/mcp/tools/_errors.py` docstring — intentionally retains old code names as
  historical documentation of what the enum replaces. No functional code changed.

## Outcome

All 1217 tests pass. No remaining functional occurrences of `INVALID_INPUT` or
`VALIDATION_ERROR` in the MCP tool handler modules.
