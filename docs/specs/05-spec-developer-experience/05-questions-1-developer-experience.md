# Clarifying Questions — Round 1

## Q1: CLI Scope
**Answer:** Status + health only (`distillery status`, `distillery health`). Read-only diagnostics. Defer full CRUD commands to a future spec.

## Q2: E2E Test Scope
**Answer:** MCP round-trip. Test MCP server lifecycle: start → call tools (store, search, classify) → verify responses → shutdown. Uses in-memory DuckDB + StubEmbeddingProvider.

## Q3: Coverage Threshold
**Answer:** 80% — standard threshold that catches major gaps without blocking edge cases.

## Q4: Dependency Hygiene
**Answer:** Yes — move pytest, mypy, ruff out of core `dependencies` into `[project.optional-dependencies] dev` only.
