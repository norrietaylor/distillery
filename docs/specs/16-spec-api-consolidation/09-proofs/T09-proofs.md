# T09 Proof Summary: Remove 8 MCP Tool Registrations + Add type_schemas Resource

## Task
T02.2 — Remove 8 MCP tool registrations and add `distillery://schemas/entry-types` resource.

## Changes Made

### `src/distillery/mcp/server.py`
- Removed 8 `@server.tool` registrations: `distillery_stale`, `distillery_aggregate`, `distillery_tag_tree`, `distillery_metrics`, `distillery_interests`, `distillery_type_schemas`, `distillery_poll`, `distillery_rescore`
- Added `@server.resource("distillery://schemas/entry-types")` — serves same JSON as the former `distillery_type_schemas` tool
- Updated module docstring to reflect 12-tool surface

### Test files updated (tool count assertions)
- `tests/test_mcp_server.py` — updated expected tool set to 12, added new resource test
- `tests/test_e2e_mcp.py` — updated expected tool set to 12
- `tests/test_mcp_http_transport.py` — updated EXPECTED_TOOLS constant and count assertion (20→12), replaced `distillery_metrics` calls with `distillery_list`

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T09-01-tool-count.txt | cli — list_tools() returns exactly 12 | PASS |
| T09-02-resource-registration.txt | cli — resource registered and returns valid JSON | PASS |
| T09-03-test-suite.txt | test — 71 targeted tests + 1950 full suite | PASS |

## Verification

- `list_tools()` returns exactly 12 tools (confirmed programmatically)
- `distillery://schemas/entry-types` resource registered and returns `{"schemas": {...}}`
- `ruff check` — clean
- `mypy --strict src/distillery/mcp/server.py` — clean
- 1950 tests pass (pre-existing `test_cli_export_import.py` timezone failure excluded)
