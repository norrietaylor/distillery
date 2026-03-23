# T02 Proof Summary: CONTRIBUTING.md & CHANGELOG.md

## Task

Create CONTRIBUTING.md and CHANGELOG.md at the repository root following agentry conventions
and Keep a Changelog format.

## Proof Artifacts

| Artifact | Type | Status | File |
|----------|------|--------|------|
| CONTRIBUTING.md sections check | file | PASS | T02-01-contributing-sections.txt |
| CHANGELOG.md format and content | file | PASS | T02-02-changelog-format.txt |

## Summary

Both files were created and verified:

### CONTRIBUTING.md

All 8 required sections are present:
- Prerequisites (Python 3.11+, pip or uv)
- Setup (editable dev mode with `pip install -e ".[dev]"`)
- Code Style (ruff + mypy strict, Protocol preference)
- Testing (pytest + pytest-asyncio, marker descriptions, subset commands)
- Commit Conventions (Conventional Commits with Distillery-specific scope examples)
- Pull Request Process (branch from main, focused commits, CI, CHANGELOG update, review)
- Architecture Overview (4-layer model: Skills -> MCP Server -> Protocols -> DuckDB)
- License note (Apache 2.0)

### CHANGELOG.md

Follows Keep a Changelog 1.1.0 format with Semantic Versioning reference.
v0.1.0 - 2026-03-22 entry documents all three MVP specifications:
- Spec 01: Storage Layer & Data Model (Entry model, DistilleryStore, DuckDBStore, embedding providers, MCP server 7 tools, config)
- Spec 02: Core Skills (/distill, /recall, /pour, /bookmark, /minutes, conventions)
- Spec 03: Classification Pipeline (ClassificationEngine, DeduplicationChecker, 4 new MCP tools, /classify, config extensions)

## Result: PASS
