# T02 Proof Summary: Entry Type Schemas with Metadata Validation

## Task

Add four new entry types (`person`, `project`, `digest`, `github`) to the `EntryType` enum,
define a `TYPE_METADATA_SCHEMAS` registry with required/optional metadata fields, add a
`validate_metadata()` function, enforce validation in `DuckDBStore.store()` and `update()`,
and add a `distillery_type_schemas` MCP tool.

## Implementation

**Files modified:**

- `src/distillery/models.py` — Added `PERSON`, `PROJECT`, `DIGEST`, `GITHUB` enum values;
  added `TYPE_METADATA_SCHEMAS` registry; added `validate_metadata()` function.
- `src/distillery/store/duckdb.py` — Imported `validate_metadata`; called it in `_sync_store()`
  before the INSERT; called it in `_sync_update()` before the UPDATE when `metadata` is in updates.
- `src/distillery/mcp/server.py` — Extended `_VALID_ENTRY_TYPES` with the four new types;
  added `distillery_type_schemas` tool wrapper; added `_handle_type_schemas()` handler.
- `src/distillery/classification/engine.py` — Updated the classification prompt to list
  the four new entry types so `test_prompt_lists_all_entry_types` stays green.

**Files created:**

- `tests/test_type_schemas.py` — 45 unit and integration tests covering all scenarios
  from the feature spec.

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T02-01-test.txt | Unit + integration tests (test_type_schemas.py, 45 tests) | PASS |
| T02-02-test.txt | Full regression suite (603 tests) | PASS |

## Results

- `tests/test_type_schemas.py` — 45 tests, all PASS
- Full suite — 603 tests, all PASS (no regressions)
- `ruff check src/distillery/ tests/test_type_schemas.py` — no errors
- `mypy --strict src/distillery/` — 1 pre-existing error (yaml stubs), not introduced by this task
