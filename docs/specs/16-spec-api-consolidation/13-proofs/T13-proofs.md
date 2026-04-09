# T13: Add CLI command for classify-batch - Proof Artifacts

## Summary

Successfully implemented the `distillery maintenance classify` CLI command that triggers batch classification of pending entries.

## Implementation Details

- Added `maintenance` subcommand with nested `classify` sub-subcommand
- Implemented options:
  - `--type TYPE`: Filter entries by type (default: "inbox")
  - `--mode {llm,heuristic}`: Classification mode (defaults to config value)
  - `--format {text,json}`: Output format
- CLI command calls `_run_classify_batch()` from webhooks module internally
- Output shows formatted results with classified/pending_review/errors counts

## Proof Artifacts

### T13-01-help.txt
Shows the help output for the new command with all options properly documented.
Status: PASS

### T13-02-empty-inbox.txt
Tests the command with an empty database, confirming it exits with code 0 and shows correct counts.
Status: PASS

### T13-03-json-format.txt
Tests JSON output format, confirming the response includes all required fields (classified, pending_review, errors, by_type).
Status: PASS

### T13-04-test-suite.txt
All 6 new unit tests for the maintenance classify command pass:
- test_maintenance_classify_empty_inbox
- test_maintenance_classify_json_format
- test_maintenance_classify_missing_config
- test_maintenance_classify_with_type_option
- test_maintenance_classify_with_mode_option
- test_maintenance_classify_help

### T13-05-all-cli-tests.txt
All 63 CLI tests pass (57 existing + 6 new), confirming no regressions.

## Files Modified

- `src/distillery/cli.py`: Added parser for maintenance classify subcommand and handler function
- `tests/test_cli.py`: Added 6 comprehensive tests for the new command

## Requirements Met

1. ✓ Added `distillery maintenance classify` subcommand
2. ✓ Accepts `--type` option (default: "inbox")
3. ✓ Accepts `--mode` option with choices: llm, heuristic
4. ✓ Calls classify-batch webhook handler internally
5. ✓ Outputs formatted results showing classified/pending_review/errors counts
6. ✓ Follows existing CLI command patterns
