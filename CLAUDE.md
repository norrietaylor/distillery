# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Distillery

Distillery is a knowledge-base system for Claude Code. It stores, searches, and classifies knowledge entries using DuckDB with vector similarity search (VSS/HNSW). It includes ambient intelligence features that poll external feeds (GitHub, RSS) and score relevance using embeddings. It exposes functionality via an MCP server (stdio or streamable-HTTP transport) with 21 tools, orchestrated by 9 Claude Code skills (`/distill`, `/recall`, `/pour`, `/bookmark`, `/minutes`, `/classify`, `/watch`, `/radar`, `/tune`). HTTP transport supports GitHub OAuth for team access.

## Commands

```bash
# Install (editable dev mode)
pip install -e ".[dev]"

# Run all tests
pytest

# Run by marker
pytest -m unit
pytest -m integration

# Run a single test file or specific test
pytest tests/test_models.py -v
pytest tests/test_models.py::test_name -v

# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Type check (strict mode enforced in CI)
mypy --strict src/distillery/

# Coverage (CI threshold: 80%)
pytest --cov=src/distillery --cov-fail-under=80

# CLI
distillery status
distillery health

# MCP server (stdio, default)
distillery-mcp

# MCP server (HTTP with GitHub OAuth)
distillery-mcp --transport http --port 8000
```

## Architecture

Four-layer design:

```text
Skills (.claude/skills/<name>/SKILL.md)  →  slash commands users invoke
    ↓
MCP Server (src/distillery/mcp/server.py)  →  21 tools over stdio or HTTP (FastMCP 2.x/3.x)
    ↓
Core Protocols (store/protocol.py, embedding/protocol.py)  →  typed Protocol interfaces
    ↓
Backends (store/duckdb.py, embedding/jina.py, embedding/openai.py)  →  DuckDB + VSS, embedding APIs
```

- **Entry** (`models.py`): core data model — UUID id, content, entry_type, source, status, tags, metadata, version
- **DistilleryStore** (`store/protocol.py`): async protocol for CRUD + semantic search + similarity
- **EmbeddingProvider** (`embedding/protocol.py`): protocol for embed/embed_batch
- **ClassificationEngine** (`classification/engine.py`): LLM-based entry classification
- **DeduplicationChecker** (`classification/dedup.py`): similarity threshold logic (skip: 0.95, merge: 0.80, link: 0.60)

Uses Python `Protocol` (structural subtyping), not ABCs. All storage operations are async.

## Conventions

- **Python 3.11+** required
- **mypy --strict** on `src/` (tests are exempt from `disallow_untyped_defs`)
- **ruff** line length 100, rules: E, W, F, I, N, UP, B, C4, SIM (E501 ignored)
- **pytest-asyncio** in auto mode — async test functions are detected automatically
- **Test markers**: `@pytest.mark.unit`, `@pytest.mark.integration`
- **Commit format**: Conventional Commits — `type(scope): description`
  - Types: feat, fix, docs, test, refactor, chore
  - Scopes: store, mcp, embedding, classification, config, skills, cli, auth, feeds

## Testing

- Fixtures in `tests/conftest.py`: `make_entry()`, `mock_embedding_provider`, `deterministic_embedding_provider`, `store` (async in-memory DuckDB)
- The `deterministic_embedding_provider` uses an 8-dimensional registry for controlled similarity testing
- CI matrix: Python 3.11, 3.12, 3.13

## Skills

9 skills live in `.claude/skills/<name>/SKILL.md` with YAML frontmatter. Shared conventions are in `.claude/skills/CONVENTIONS.md`. All skills follow the same pattern: check MCP availability, determine author (git config > env > ask), determine project (git repo name > flag > ask), execute, confirm.

- **Knowledge capture**: `/distill`, `/bookmark`, `/minutes`
- **Knowledge retrieval**: `/recall`, `/pour`, `/classify`
- **Ambient intelligence**: `/watch` (manage feed sources), `/radar` (digest + source suggestions), `/tune` (adjust thresholds)
