# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Distillery

Distillery is a knowledge-base system for Claude Code. It stores, searches, and classifies knowledge entries using DuckDB with vector similarity search (VSS/HNSW). It includes ambient intelligence features that poll external feeds (GitHub, RSS) and score relevance using embeddings. It exposes functionality via an MCP server (stdio or streamable-HTTP transport) with 12 tools, orchestrated by 14 Claude Code skills (`/distill`, `/recall`, `/pour`, `/bookmark`, `/minutes`, `/classify`, `/watch`, `/radar`, `/tune`, `/digest`, `/gh-sync`, `/investigate`, `/briefing`, `/setup`). HTTP transport supports GitHub OAuth for team access. REST webhook endpoints (`/hooks/poll`, `/hooks/rescore`, `/hooks/classify-batch`, `/api/maintenance`) run alongside the MCP server for automated scheduling via GitHub Actions cron.

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
Skills (skills/<name>/SKILL.md)  →  slash commands users invoke
    ↓
MCP Server (src/distillery/mcp/server.py)  →  12 tools over stdio or HTTP (FastMCP 2.x/3.x)
Webhook API (src/distillery/mcp/webhooks.py) →  /hooks/poll, /hooks/rescore, /hooks/classify-batch, /api/maintenance (bearer auth)
    ↓
Core Protocols (store/protocol.py, embedding/protocol.py)  →  typed Protocol interfaces
    ↓
Backends (store/duckdb.py, embedding/jina.py, embedding/openai.py)  →  DuckDB + VSS, embedding APIs
```

- **Entry** (`models.py`): core data model — str id (UUID4), content, entry_type, source, status, tags, metadata, version, project (str | None)
- **DistilleryStore** (`store/protocol.py`): async protocol for CRUD + semantic search + similarity + feed source persistence
- **EmbeddingProvider** (`embedding/protocol.py`): protocol for embed/embed_batch
- **ClassificationEngine** (`classification/engine.py`): LLM-based entry classification
- **DeduplicationChecker** (`classification/dedup.py`): similarity threshold logic (skip: >= 0.95, merge: >= 0.80, link: >= 0.60)
- **ClassificationConfig**: `confidence_threshold` default 0.6 (60%) — entries below this go to review queue

Uses Python `Protocol` (structural subtyping), not ABCs. All storage operations are async.

## Deployment

A generic `Dockerfile` at the repo root builds the Distillery MCP server image, published to `ghcr.io/norrietaylor/distillery`. Platform-specific deployment configs (Fly.io, Prefect Horizon) live in the [distill_ops](https://github.com/norrietaylor/distill_ops) repo.

Local development uses `distillery-dev.yaml` at the repo root. The `DISTILLERY_CONFIG` env var points each deployment to its config file.

## Git Workflow

Always create a pull request for changes — never push directly to `main`. Create a branch, commit, push the branch, then open a PR via `mcp__github__create_pull_request`.

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

14 skills live in `skills/<name>/SKILL.md` with YAML frontmatter. Shared conventions are in `skills/CONVENTIONS.md`. All skills follow the same pattern: check MCP availability, determine author (git config > env > ask), determine project (git repo name > flag > ask), execute, confirm.

- **Knowledge capture**: `/distill`, `/bookmark`, `/minutes`
- **Knowledge retrieval**: `/recall`, `/pour`, `/classify`
- **Ambient intelligence**: `/watch` (manage feed sources — `rss` and `github` types only), `/radar` (digest + source suggestions), `/tune` (adjust thresholds — alert >= digest)
- **Team**: `/digest` (team activity summary), `/gh-sync` (GitHub issue/PR sync), `/investigate` (deep context builder), `/briefing` (team dashboard)
- **Onboarding**: `/setup` (MCP connectivity wizard — local transport uses `CronCreate`; hosted/team uses GitHub Actions webhook scheduler)

## Documentation

User-facing documentation is built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/) and lives in `docs/`. Configuration is in `mkdocs.yml`.

```bash
# Build docs locally
make docs-build          # or: mkdocs build --strict

# Serve docs locally (hot reload)
make docs-serve          # or: mkdocs serve

# Install docs dependencies
pip install .[docs]
```

The docs site is deployed to GitHub Pages via `.github/workflows/pages.yml` on push to `main`. The `docs/` directory contains only MkDocs source files — legacy docs and specs have been removed. SKILL.md files in `skills/` are Claude-facing instructions; the `docs/skills/` pages are human-readable rewrites.