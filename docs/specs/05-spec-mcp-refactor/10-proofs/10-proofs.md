# T01.6 Proof Summary: Extract analytics handlers to tools/analytics.py

## Task
T01.6: Extract analytics handlers to tools/analytics.py

## Requirement
R01.6.1: analytics.py contains _handle_metrics, _handle_quality, _handle_stale,
_handle_tag_tree, _handle_interests, _handle_type_schemas

## Proof Artifacts

| File | Type | Status | Description |
|------|------|--------|-------------|
| 10-01-cli.txt | cli | PASS | pytest -m unit --tb=short -q |

## Summary

Created `src/distillery/mcp/tools/analytics.py` containing all 6 analytics
handlers extracted from `server.py`:
- `_handle_metrics` + `_sync_gather_metrics`
- `_handle_quality` + `_sync_gather_quality`
- `_handle_stale` + `_sync_gather_stale`
- `_handle_tag_tree`
- `_handle_type_schemas`
- `_handle_interests`
- `_DEFAULT_STALE_DAYS` constant

Updated `tools/__init__.py` to re-export all 6 handlers.

Updated `server.py` to import the handlers from `tools/analytics.py` and
removed the now-redundant local definitions.

All 895 unit tests passed (baseline was 895 passing), confirming no regression
from the refactor.
