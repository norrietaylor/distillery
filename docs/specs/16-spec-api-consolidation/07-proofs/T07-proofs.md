# T07 Proof Summary: Write test suite for list extensions

**Task**: T01.3 — Write test suite for list extensions  
**Timestamp**: 2026-04-09  
**Status**: PASS

## Files Created

- `tests/test_mcp_tools/__init__.py`
- `tests/test_mcp_tools/test_list_extensions.py`

## Test Results

### T07-01-test.txt — Full verbose run

40 tests collected:
- **38 PASSED** — All stale_days, group_by, output=stats, and mutual exclusivity tests
- **2 XFAILED** (expected) — `group_by=tags` and `group_by=tags with tag_prefix` are marked
  `xfail(strict=True)` because DuckDB 1.5.1 does not support `UNNEST()` inside a CTE SELECT.
  These tests document the desired behavior and will automatically start passing when the
  store-layer bug in `aggregate_entries` is fixed.

### T07-02-test.txt — Summary run

38 passed, 2 xfailed

## Coverage

| Feature | Tests | Status |
|---------|-------|--------|
| stale_days validation (not int, zero, negative, float) | 4 | PASS |
| stale_days=1 minimum valid | 1 | PASS |
| stale_days filtering: stale entries returned | 1 | PASS |
| stale_days filtering: recent entries excluded | 1 | PASS |
| stale_days COALESCE with updated_at (no accessed_at) | 1 | PASS |
| stale_days composed with entry_type filter | 1 | PASS |
| stale_days composed with author filter | 1 | PASS |
| stale_days composed with project filter | 1 | PASS |
| stale_days composed with tags filter | 1 | PASS |
| stale_days on empty store | 1 | PASS |
| group_by not string validation | 1 | PASS |
| group_by invalid value validation | 1 | PASS |
| group_by + output=stats mutual exclusivity | 2 | PASS |
| output invalid value / not string | 2 | PASS |
| group_by=entry_type format | 1 | PASS |
| group_by=entry_type counts | 1 | PASS |
| group_by=status | 1 | PASS |
| group_by=author | 1 | PASS |
| group_by=project | 1 | PASS |
| group_by=source | 1 | PASS |
| group_by=tags (DuckDB UNNEST bug) | 1 | XFAIL |
| group_by=tags with tag_prefix (DuckDB UNNEST bug) | 1 | XFAIL |
| group_by ordering count DESC | 1 | PASS |
| group_by total_groups before limit | 1 | PASS |
| group_by with entry_type filter | 1 | PASS |
| group_by all valid non-tag values | 1 | PASS |
| output=stats format | 1 | PASS |
| output=stats total_entries | 1 | PASS |
| output=stats entries_by_type | 1 | PASS |
| output=stats entries_by_status | 1 | PASS |
| output=stats storage_bytes | 1 | PASS |
| output=stats + stale_days | 1 | PASS |
| output=stats empty store | 1 | PASS |

## Known Issue Documented

DuckDB 1.5.1 does not support `UNNEST()` in a CTE SELECT clause.
The `aggregate_entries` method in `store/duckdb.py` uses this pattern for `group_by="tags"`.
Two tests are marked `xfail(strict=True)` so the regression will be detected when fixed.
