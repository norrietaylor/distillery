# T02: Test Infrastructure Consolidation — Proof Summary

**Task**: T02 — Test Infrastructure Consolidation
**Date**: 2026-03-25
**Status**: COMPLETE

## Deliverables

### 1. tests/conftest.py created

Created `/Users/norrie/code/distillery/tests/conftest.py` (7,213 bytes) containing:

- `make_entry(**kwargs) -> Entry` — factory with defaults `content="Default content"`, `entry_type=INBOX`, `source=MANUAL`, `author="tester"`
- `parse_mcp_response(content: list) -> dict` — JSON parser for MCP TextContent lists
- `MockEmbeddingProvider` — hash-based 4D provider class
- `DeterministicEmbeddingProvider` — registry + hash fallback 4D provider class
- `ControlledEmbeddingProvider` — registry + L2 normalisation 8D provider class
- `mock_embedding_provider` fixture — returns `MockEmbeddingProvider()`
- `deterministic_embedding_provider` fixture — returns `DeterministicEmbeddingProvider()`
- `controlled_embedding_provider` fixture — returns `ControlledEmbeddingProvider()`
- `store` fixture — async in-memory `DuckDBStore` using `mock_embedding_provider`

### 2. Duplicate helpers removed

Removed from 6 test modules:
- `_make_entry`: removed from `test_duckdb_store.py`, `test_mcp_server.py`, `test_mcp_classify.py`, `test_mcp_dedup.py`, `test_store_integration.py`, `test_dedup.py`
- `_parse_response`: removed from `test_mcp_server.py`, `test_mcp_classify.py`, `test_mcp_dedup.py`
- Embedding provider classes: removed from `test_duckdb_store.py` (`_MockEmbeddingProvider`), `test_mcp_server.py` (`_DeterministicEmbeddingProvider`), `test_mcp_classify.py` (`_DeterministicEmbeddingProvider`), `test_mcp_dedup.py` (`_ControlledEmbeddingProvider`), `test_store_integration.py` (`_DeterministicEmbeddingProvider`), `test_store_protocol.py` (`_MockEmbeddingProvider`)

### 3. All tests pass

- 400 tests pass (13 pre-existing failures in `test_cli.py` belong to T01 scope and were failing before this task)
- 384 tests pass when excluding `test_cli.py` (T01 scope)

## Proof Artifacts

| Artifact | Type | Status |
|----------|------|--------|
| T02-01-test.txt | pytest run output | PASS |
| T02-02-cli.txt | duplicate helpers grep | PASS |

## Notes

- `conftest.py` passes `mypy --ignore-missing-imports` (project-level `import-untyped` warnings are pre-existing, not caused by conftest)
- All modified files pass `ruff check`
- The `_make_entry` in `test_dedup.py` used different defaults (SESSION/CLAUDE_CODE) — refactored to use `make_entry()` with explicit override kwargs
- The `test_store_protocol.py` tests were refactored to accept `mock_embedding_provider` as a fixture parameter instead of instantiating a private class inline
- Local `embedding_provider` fixture aliases in `test_mcp_server.py`, `test_mcp_dedup.py`, and `test_store_integration.py` delegate to the appropriate conftest fixture
