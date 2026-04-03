# T11 (T03.2) Proof Summary

Task: Extend _handle_interests with suggest_sources and remove suggest_sources tool

## Changes Made

1. **analytics.py** (`src/distillery/mcp/tools/analytics.py`): Extended `_handle_interests` with two new optional parameters:
   - `suggest_sources: bool = False` — when True, appends feed source suggestions
   - `max_suggestions: int = 5` — controls max number of suggestions returned
   When `suggest_sources=True`, the handler imports and calls `_derive_suggestions` and `_normalise_watched_set` from feeds.py and appends a `suggestions` key to the response.

2. **feeds.py** (`src/distillery/mcp/tools/feeds.py`): Removed `_handle_suggest_sources` handler function and `_VALID_SUGGEST_SOURCE_TYPES` constant. Helper functions `_normalise_watched_set` and `_derive_suggestions` retained for use by analytics.py.

3. **tools/__init__.py** (`src/distillery/mcp/tools/__init__.py`): Removed `_handle_suggest_sources` import and export.

4. **server.py** (`src/distillery/mcp/server.py`): 
   - Removed `_handle_suggest_sources` import
   - Removed `distillery_suggest_sources` tool registration
   - Updated `distillery_interests` tool to include `suggest_sources` and `max_suggestions` parameters

5. **webhooks.py** (`src/distillery/mcp/webhooks.py`): Updated `_handle_maintenance` to call `_handle_interests(suggest_sources=True, max_suggestions=3)` instead of separate `_handle_suggest_sources` call. Reads suggestions from `interests_data["suggestions"]`.

6. **radar/SKILL.md** (`.claude-plugin/skills/radar/SKILL.md`):
   - Removed `distillery_suggest_sources` from `allowed-tools`
   - Updated Step 5 to call `distillery_interests(suggest_sources=true, max_suggestions=5)` and read the `suggestions` key

7. **Test files updated**:
   - `tests/test_mcp_analytics.py`: Added `TestInterestsSuggestSources` class with 8 new tests
   - `tests/test_mcp_feeds.py`: Removed `TestHandleSuggestSources` class and `_handle_suggest_sources` import
   - `tests/test_webhooks.py`: Updated maintenance handler tests to remove `_handle_suggest_sources` mock
   - `tests/test_mcp_coverage_gaps.py`: Updated `TestSuggestSourcesGaps` to use `_handle_interests`
   - `tests/test_e2e_mcp.py`: Removed `distillery_suggest_sources` from expected tool set (23 → 22)
   - `tests/test_mcp_http_transport.py`: Updated EXPECTED_TOOLS and count (23 → 22)
   - `tests/test_mcp_server.py`: Removed `distillery_suggest_sources` from expected tools
   - `tests/test_interests.py`: Updated `TestHandleSuggestSources` to use `_handle_interests`

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T11-01-test.txt | test | PASS |
| T11-02-file.txt | file | PASS |

## Test Results

- All 1543 tests pass (excluding test_eval_claude.py which requires live Claude API)
- Specifically: 89 tests in test_mcp_analytics.py + test_mcp_feeds.py + test_webhooks.py all pass
- New `TestInterestsSuggestSources` class with 8 tests verifies the new functionality
- No ruff lint errors
- No mypy strict errors on modified source files
