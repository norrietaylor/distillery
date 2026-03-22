# T03 Proof Summary: Config Extensions & Dedup Integration into /distill

## Task

T03 — Extend the configuration system with dedup thresholds, add the
`distillery_check_dedup` MCP tool, and update the `/distill` skill with the
full dedup flow.

## Deliverables Implemented

### 1. ClassificationConfig extended (src/distillery/config.py)

Four new fields added with defaults matching the spec:
- `dedup_skip_threshold` (default 0.95)
- `dedup_merge_threshold` (default 0.80)
- `dedup_link_threshold` (default 0.60)
- `dedup_limit` (default 5)

`_parse_classification` updated to load all four new fields from YAML.
`_validate` updated to enforce:
  - each threshold in [0.0, 1.0]
  - ordering: dedup_link_threshold <= dedup_merge_threshold <= dedup_skip_threshold
  - dedup_limit must be a positive integer

### 2. distillery.yaml.example updated

New `classification` section comments added explaining all four dedup fields
with their defaults and the ordering constraint.

### 3. distillery_check_dedup MCP tool added (src/distillery/mcp/server.py)

Tool added to `_list_tools` (server now has 11 tools total).
Dispatch added in `_call_tool`.
Handler `_handle_check_dedup` implemented: instantiates `DeduplicationChecker`
with thresholds from config, calls `checker.check(content)`, serialises
`DeduplicationResult` fields into a JSON response.

### 4. /distill SKILL.md updated (.claude/skills/distill/SKILL.md)

Step 6 replaced: was `distillery_find_similar` with a threshold of 0.8.
Now uses `distillery_check_dedup` with four action branches:
- `create` -> proceed to Step 7
- `skip` -> prompt user (store anyway / skip)
- `merge` -> prompt user (store anyway / merge / skip)
- `link` -> proceed with related_entries in metadata

### 5. tests/test_config.py updated

New tests:
- `test_dedup_threshold_defaults` — verifies default values
- `test_loads_dedup_thresholds` — verifies YAML round-trip
- `test_dedup_skip_threshold_above_one_raises_value_error`
- `test_dedup_link_threshold_below_zero_raises_value_error`
- `test_dedup_threshold_ordering_violated_raises_value_error`
- `test_dedup_merge_above_skip_raises_value_error`
- `test_dedup_limit_zero_raises_value_error`
- `test_dedup_limit_non_integer_raises_value_error`
- `test_example_config_dedup_thresholds`

### 6. tests/test_mcp_dedup.py created (new file)

9 tests covering `_handle_check_dedup` directly:
- Empty store -> action=create
- Create result has reasoning
- Missing content field -> INVALID_INPUT error
- Identical embeddings -> action=skip (including field presence check)
- Moderate similarity -> action=merge
- Low similarity -> action=link
- Custom skip threshold applied
- dedup_limit restricts entries returned

## Proof Artifacts

| Artifact | Type | Status |
|----------|------|--------|
| T03-01-test.txt | pytest tests/test_config.py | PASS (38/38) |
| T03-02-test.txt | pytest tests/test_mcp_dedup.py | PASS (9/9) |
| T03-03-test.txt | pytest tests/ (full suite) | PASS (384/384) |
