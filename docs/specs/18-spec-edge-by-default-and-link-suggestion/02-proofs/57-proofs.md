# Task 57 Proof Summary

**Task**: FIX-REVIEW: guard NULL embeddings in `_sync_cosine_candidates`
**Date**: 2026-06-24
**Model**: sonnet

## Fix Applied

Added `AND embedding IS NOT NULL` to the WHERE clause in `_sync_cosine_candidates`
(src/distillery/store/duckdb.py, line ~4328). This prevents `array_cosine_similarity(NULL, ?)`
from returning NULL scores, which previously caused `float(None)` TypeError on line 4334.

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| 57-01-test.txt | Regression test | PASS |
| 57-02-lint.txt | ruff + mypy | PASS |

## Regression Test

`test_suggest_links_tolerates_null_embedding` in `tests/test_relations.py`:
- Seeds one entry with a valid embedding
- Seeds one valid-band neighbour
- Inserts a third entry then NULLs its embedding directly in the DB
- Asserts `suggest_links()` completes without error
- Asserts the NULL-embedding entry does not appear in candidates or live edges
