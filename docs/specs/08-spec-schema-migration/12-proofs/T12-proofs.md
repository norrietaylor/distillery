# T12 Proof Summary: Implement distillery export command

## Task
T03.1 — Add `distillery export --output PATH` subcommand to cli.py

## Status: PASS

## Artifacts

| File | Type | Status |
|------|------|--------|
| T12-01-test.txt | test | PASS |
| T12-02-cli.txt | cli | PASS |

## Implementation

### Files Modified
- `src/distillery/cli.py` — added `export` subparser, `_cmd_export()` function, and dispatch in `main()`
- `tests/test_cli.py` — added `TestExportCommand` class with 8 tests

### Approach
- Added `export` subparser with required `--output PATH` flag in `_build_parser()`
- Implemented `_cmd_export(config_path, fmt, output_path)` following the `_cmd_poll` async pattern
- Queries entries without the embedding column (explicit column list)
- Queries feed_sources and _meta tables directly via `store._conn`
- Serializes datetime values as ISO strings
- Writes JSON: `{"version": 1, "exported_at": "<ISO>", "meta": {...}, "entries": [...], "feed_sources": [...]}`
- Prints: "Exported {N} entries and {M} feed sources to {path}"

## Test Results
37 tests passed (29 pre-existing + 8 new export tests)
