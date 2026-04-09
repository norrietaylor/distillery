# T06 Proof Summary: Wire list extensions into MCP tool + validation

Task: T01.2 — Add stale_days, group_by, output parameters to distillery_list MCP tool

## Changes Made

### src/distillery/mcp/server.py
- Added `stale_days: int | None = None`, `group_by: str | None = None`, `output: str | None = None` to `distillery_list` function signature
- Updated docstring to document new parameters

### src/distillery/mcp/tools/crud.py
- Added `_VALID_GROUP_BY_VALUES` frozenset constant (entry_type, status, author, project, source, tags)
- Added validation for `stale_days` (must be int, >= 1)
- Added validation for `group_by` (must be one of `_VALID_GROUP_BY_VALUES`)
- Added validation for `output` (must be "stats")
- Added mutual exclusivity check (group_by + output="stats" => INVALID_PARAMS error)
- Added group_by mode: calls store.list_entries with group_by, returns grouped dict directly
- Added stats mode: calls store.list_entries with output="stats", returns stats dict directly
- Updated default list mode to pass stale_days to store.list_entries

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T06-01-test.txt | pytest regression suite | PASS |
| T06-02-cli.txt | inline validation (8 scenarios) | PASS |
| T06-03-cli.txt | ruff + mypy static analysis | PASS |
