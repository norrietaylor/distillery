# T10 Proof Summary — T02.3: Migrate tests for removed tools

## Task

Update or delete tests that reference the 8 removed MCP tools:
`distillery_stale`, `distillery_aggregate`, `distillery_tag_tree`,
`distillery_metrics`, `distillery_interests`, `distillery_type_schemas`,
`distillery_poll`, `distillery_rescore`

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T10-01-test.txt | test run (123 tests) | PASS |
| T10-02-grep.txt | grep analysis of removed tool name references | PASS |

## Changes Made

### tests/test_mcp_server.py

- Updated module docstring to reflect 12-tool surface and list removed tools
- Added `TestRemovedTools` class with 2 negative tests:
  - `test_removed_tools_not_registered`: verifies none of the 8 removed
    tool names appear in `create_server().list_tools()`
  - `test_removed_tools_count_unchanged`: verifies exactly 12 tools registered

### tests/test_mcp_analytics.py

- Updated module docstring to clarify these are handler-level tests,
  not MCP tool tests, and explain the architectural change

### tests/test_poller.py

- Updated module docstring to note `distillery_poll` and `distillery_rescore`
  are no longer MCP tools; `_handle_poll` is tested as a handler function

## Justification for Kept Tests

- `test_mcp_analytics.py` — Tests analytics handlers directly (`_handle_stale`,
  `_handle_tag_tree`, etc.). These handler functions still exist and are used
  internally by webhooks. Direct handler tests remain valid.
- `TestHandlePoll` in `test_poller.py` — Tests `_handle_poll` as a function
  (not a registered MCP tool). The function still exists and powers the
  `/api/poll` webhook. Valid unit test.
- `TestStatusTool` in `test_mcp_server.py` — Tests `_handle_metrics` handler
  directly. The handler still exists and is used by webhooks/maintenance.

## Verification

```
pytest tests/test_mcp_server.py tests/test_mcp_analytics.py tests/test_poller.py
123 passed, 0 failed
```

New negative tests confirm:
- `distillery_stale` not in tool registry
- `distillery_aggregate` not in tool registry
- `distillery_tag_tree` not in tool registry
- `distillery_metrics` not in tool registry
- `distillery_interests` not in tool registry
- `distillery_type_schemas` not in tool registry
- `distillery_poll` not in tool registry
- `distillery_rescore` not in tool registry
- Total registered tools: exactly 12
