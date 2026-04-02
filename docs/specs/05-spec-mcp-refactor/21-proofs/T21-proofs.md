# T21 Proof Summary: T04.4 — Write check_conflicts handler tests

## Task

T04.4 — Write `tests/test_mcp_conflicts.py` covering the `_handle_check_conflicts` handler.

## Implementation

Created `/home/norrie.guest/code/distillery/.worktrees/feature-mcp-refactor/tests/test_mcp_conflicts.py` with 35 unit tests covering:

- **First-pass (no llm_responses)**: returns `conflict_candidates` with prompts when similar entries exist, including all required fields (`entry_id`, `conflict_prompt`, `content_preview`, `similarity_score`)
- **First-pass no similar entries**: returns empty `conflict_candidates` for empty store or orthogonal vectors
- **Second-pass with conflict**: returns `has_conflicts=True` with serialised conflict entries including all fields (`entry_id`, `conflict_reasoning`, `similarity_score`, `content_preview`)
- **Second-pass no conflict**: returns `has_conflicts=False` with empty `conflicts` list
- **Multiple candidates**: only LLM-confirmed conflicts appear in the result
- **Validation errors**: missing `content`, non-dict `llm_responses`, non-dict response item, missing `is_conflict` field all return `INVALID_PARAMS`
- **Error handling**: store exceptions caught and return `CONFLICT_ERROR`
- **Threshold**: high threshold excludes low-similarity entries, low threshold includes them
- **Content preview**: truncated to 120 characters in both first and second pass

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T21-01-test.txt | test | PASS |
| T21-02-lint.txt | cli (ruff) | PASS |

## Results

- 35 tests, 35 passed, 0 failed
- Ruff lint: no errors
- Handler imported directly from `distillery.mcp.tools.quality`
- All tests marked `@pytest.mark.unit` (via `pytestmark`)
