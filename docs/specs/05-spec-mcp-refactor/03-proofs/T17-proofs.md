# T17 Proof Summary

**Task**: T17 (T03.2): Replace hardcoded constants with config reads and add tests
**Status**: COMPLETED
**Timestamp**: 2026-04-01T00:00:00Z

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T17-01-test.txt | test | PASS |
| T17-02-grep.txt | cli | PASS |

## Requirements Verification

| Requirement | Status | Evidence |
|-------------|--------|---------|
| _DEFAULT_DEDUP_THRESHOLD removed from mcp/ | PASS | grep returns no matches |
| _DEFAULT_DEDUP_LIMIT removed from mcp/ | PASS | grep returns no matches |
| _DEFAULT_STALE_DAYS removed from mcp/ | PASS | grep returns no matches |
| crud.py _handle_store reads from config.defaults | PASS | Uses cfg.defaults.dedup_threshold and cfg.defaults.dedup_limit |
| analytics.py _handle_stale reads from config.defaults | PASS | Uses config.defaults.stale_days |
| analytics.py _sync_gather_metrics reads from config.defaults | PASS | Uses config.defaults.stale_days |
| tests/test_config.py DefaultsConfig defaults test | PASS | test_defaults_defaults passes |
| tests/test_config.py DefaultsConfig YAML override test | PASS | test_loads_defaults passes |
| All 89 config tests pass | PASS | 89 passed in 0.07s |
| All 1217 project tests pass | PASS | 1217 passed, 61 skipped |

## Files Modified

- `src/distillery/mcp/tools/crud.py` — Removed `_DEFAULT_DEDUP_THRESHOLD` and `_DEFAULT_DEDUP_LIMIT` constants; `_handle_store` now reads from `cfg.defaults.dedup_threshold` and `cfg.defaults.dedup_limit` (falling back to `DefaultsConfig()` when cfg is None)
- `src/distillery/mcp/tools/analytics.py` — Removed `_DEFAULT_STALE_DAYS` constant; `_sync_gather_metrics` uses `config.defaults.stale_days`; `_handle_stale` uses `config.defaults.stale_days` instead of `config.classification.stale_days`
- `src/distillery/mcp/tools/__init__.py` — Removed re-export of `_DEFAULT_STALE_DAYS`
- `src/distillery/mcp/server.py` — Removed import of `_DEFAULT_DEDUP_LIMIT` and `_DEFAULT_DEDUP_THRESHOLD`; `distillery_store` tool signature now uses `None` sentinel defaults for `dedup_threshold` and `dedup_limit` so runtime config is used
- `tests/test_stale.py` — Updated `_make_config` to set `defaults.stale_days` (via `DefaultsConfig`) instead of `classification.stale_days`

## Validation

- `mypy --strict src/distillery/mcp/` passes with no issues
- `ruff check src/distillery/mcp/ tests/test_stale.py` passes with no issues
- All 1217 tests pass (61 skipped)
