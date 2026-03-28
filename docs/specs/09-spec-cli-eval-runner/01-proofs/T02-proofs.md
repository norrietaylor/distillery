# T02 Proof Summary: CLI-Based Eval Runner

## Task

Rewrite ClaudeEvalRunner to shell out to the Claude CLI instead of using the
anthropic SDK. Add seed_file_store() to mcp_bridge.py. Add _parse_stream_events()
for stream-json parsing. Add total_cost_usd to PerformanceMetrics. Remove
anthropic from pyproject.toml eval extras. Update tests.

## Proof Artifacts

| # | File | Type | Status |
|---|------|------|--------|
| 1 | T02-01-test.txt | test | PASS |
| 2 | T02-02-test.txt | test | PASS |
| 3 | T02-03-file.txt | file | PASS |

## Details

### T02-01-test.txt (New Tests Only)
- 15 new tests all passing:
  - TestParseStreamEvents (8 tests): empty input, text-only response, tool_use
    and result pairing, multiple tool calls, error responses, invalid JSON
    handling, missing result event defaults, total_cost_usd absent
  - TestClaudeEvalRunnerInit (2 tests): FileNotFoundError when CLI missing,
    no ANTHROPIC_API_KEY required
  - TestSeedFileStore (3 tests): seeds entries and returns count, zero entries,
    creates readable DB file
  - TestPerformanceMetrics (2 tests): total_cost_usd default zero, explicit value

### T02-02-test.txt (Full Eval Unit Suite)
- 96 tests all passing (81 existing + 15 new)
- All existing tests continue to pass with the rewritten runner

### T02-03-file.txt (File Verification)
- Confirmed: `anthropic` is no longer in pyproject.toml eval extras
- eval extras is now an empty list

## Coverage
- Full test suite: 842 passed, 36 skipped, 80.93% coverage (above 80% threshold)
