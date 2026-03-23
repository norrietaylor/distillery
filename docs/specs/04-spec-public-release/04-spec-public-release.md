# 04-spec-public-release: Prepare Repo for Public Release

## Introduction/Overview

Prepare the Distillery repository for public release on GitHub. This involves switching the license from MIT to Apache 2.0, adding standard open-source project files (CONTRIBUTING.md, CHANGELOG.md), aligning tooling configuration with the conventions established in the `agentry` sibling project, cleaning up committed artifacts, and adding a CI workflow.

## Goals

1. License the project under Apache 2.0 with all required files in place
2. Add CONTRIBUTING.md and CHANGELOG.md following agentry conventions
3. Align pyproject.toml with agentry patterns (classifiers, keywords, lint rules, pytest config)
4. Remove committed binary artifacts and relocate internal docs
5. Add GitHub Actions CI workflow for automated quality gates on PRs

## User Stories

- As a potential contributor, I want to see a LICENSE, CONTRIBUTING.md, and CHANGELOG.md so I know the project is well-maintained and how to participate
- As a maintainer, I want CI running on every PR so that lint, type checking, and tests are enforced automatically
- As a user browsing GitHub, I want a clean repo without binary artifacts or misplaced internal docs

## Demoable Units of Work

### Unit 1: License & Project Metadata

**Purpose:** Switch from MIT to Apache 2.0 and add PyPI-standard metadata to pyproject.toml.

**Functional Requirements:**
- The system shall include a `LICENSE` file at the repo root containing the full Apache License 2.0 text with copyright line: `Copyright 2026 Distillery Contributors`
- The `pyproject.toml` shall set `license = {text = "Apache-2.0"}` (replacing `{text = "MIT"}`)
- The `pyproject.toml` shall include `keywords`:
  ```
  ["knowledge-base", "second-brain", "embeddings", "mcp", "claude-code", "vector-search", "duckdb"]
  ```
- The `pyproject.toml` shall include PyPI `classifiers`:
  ```
  "Development Status :: 3 - Alpha"
  "Environment :: Console"
  "Intended Audience :: Developers"
  "License :: OSI Approved :: Apache Software License"
  "Operating System :: OS Independent"
  "Programming Language :: Python :: 3"
  "Programming Language :: Python :: 3.11"
  "Programming Language :: Python :: 3.12"
  "Programming Language :: Python :: 3.13"
  "Topic :: Software Development :: Libraries :: Python Modules"
  ```
- The `README.md` license section shall reference Apache 2.0 (replacing MIT)

**Proof Artifacts:**
- File: `LICENSE` exists at repo root and contains "Apache License" and "Distillery Contributors"
- File: `pyproject.toml` contains `Apache-2.0` license and all classifiers
- File: `README.md` references Apache 2.0

### Unit 2: CONTRIBUTING.md & CHANGELOG.md

**Purpose:** Add standard open-source contribution guide and changelog following agentry conventions.

**Functional Requirements:**
- The system shall include a `CONTRIBUTING.md` at the repo root with these sections (matching agentry pattern):
  - Prerequisites (Python 3.11+, pip or uv)
  - Setup (clone, install with `-e ".[dev]"`)
  - Code Style (ruff for linting/formatting, mypy strict for type checking, Protocol preference)
  - Testing (pytest with pytest-asyncio, marker descriptions, how to run subsets)
  - Commit Conventions (Conventional Commits with examples relevant to Distillery: `feat(store)`, `fix(mcp)`, `docs`, `test(classification)`)
  - Pull Request Process (branch from main, focused commits, CI green, tests required, review)
  - Architecture Overview (brief description of the 4-layer model: Skills → MCP Server → Store/Embedding/Classification → DuckDB, with key protocols listed)
  - License note ("Licensed under Apache 2.0. By submitting a contribution, you agree...")
- The system shall include a `CHANGELOG.md` at the repo root using [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format with:
  - Header referencing Semantic Versioning
  - `[v0.1.0] - 2026-03-22` entry documenting Phase 1 MVP under three sub-sections:
    - **Spec 01 — Storage Layer & Data Model**: Entry data model, DistilleryStore protocol, DuckDB backend, embedding providers, MCP server (7 tools), config system
    - **Spec 02 — Core Skills**: /distill, /recall, /pour, /bookmark, /minutes, shared conventions
    - **Spec 03 — Classification Pipeline**: ClassificationEngine, DeduplicationChecker, 4 new MCP tools (11 total), /classify skill, config extensions

**Proof Artifacts:**
- File: `CONTRIBUTING.md` exists with all required sections
- File: `CHANGELOG.md` exists with v0.1.0 entry and all three spec sections

### Unit 3: Tooling Configuration Alignment

**Purpose:** Align ruff, mypy, and pytest configuration with agentry conventions for consistent quality enforcement.

**Functional Requirements:**
- The `pyproject.toml` `[tool.ruff.lint]` section shall include extended rule selection matching agentry:
  ```
  select = ["E", "W", "F", "I", "N", "UP", "B", "C4", "SIM"]
  ignore = ["E501"]
  ```
- The `pyproject.toml` shall add `[tool.ruff.lint.isort]` with `known-first-party = ["distillery"]`
- The `pyproject.toml` `[tool.mypy]` section shall add a test override:
  ```
  [[tool.mypy.overrides]]
  module = "tests.*"
  disallow_untyped_defs = false
  disallow_incomplete_defs = false
  ```
- The `pyproject.toml` `[tool.pytest.ini_options]` shall be updated with:
  ```
  addopts = ["-v", "--strict-markers", "--tb=short"]
  markers = [
      "unit: unit tests",
      "integration: integration tests",
  ]
  ```
- After configuration changes, `ruff check src/ tests/` shall pass with zero errors (fix any new violations introduced by the expanded rule set)
- After configuration changes, `mypy --strict src/distillery/` shall pass
- After configuration changes, `pytest` shall pass

**Proof Artifacts:**
- CLI: `ruff check src/ tests/` returns zero errors
- CLI: `mypy --strict src/distillery/` returns zero errors
- CLI: `pytest` returns all tests passing

### Unit 4: Repo Cleanup & CI Workflow

**Purpose:** Remove binary artifacts, relocate internal docs, and add GitHub Actions CI.

**Functional Requirements:**
- All `__pycache__/` directories and `*.pyc` files shall be removed from git tracking via `git rm -r --cached`
- The `.gitignore` shall already exclude `__pycache__/` (verified — it does)
- `distillery-brainstorm.md` shall be moved from repo root to `docs/distillery-brainstorm.md`
- The system shall include a `.github/workflows/ci.yml` GitHub Actions workflow that:
  - Triggers on push to `main` and pull requests to `main`
  - Runs on `ubuntu-latest` with Python 3.11
  - Steps: checkout, install Python, `pip install -e ".[dev]"`, then three parallel jobs or sequential steps:
    1. `ruff check src/ tests/` (lint)
    2. `mypy --strict src/distillery/` (type check)
    3. `pytest` (test)
  - Fails the PR if any step fails

**Proof Artifacts:**
- CLI: `git ls-files '*.pyc'` returns empty (no binary files tracked)
- File: `docs/distillery-brainstorm.md` exists (not in repo root)
- File: `.github/workflows/ci.yml` exists with lint, typecheck, and test steps
- CLI: `act` or manual push validates CI workflow runs (optional — manual verification acceptable)

## Non-Goals (Out of Scope)

- **PyPI publishing** — no `twine upload` or release automation for now
- **Code of Conduct** — can be added later if community grows
- **Issue/PR templates** — deferred to when external contributions start
- **Branch protection rules** — GitHub settings, not repo files
- **Security policy (SECURITY.md)** — deferred
- **Fixing existing code** — this spec only touches config, docs, and CI; no source code changes unless ruff's expanded rules require fixes

## Design Considerations

No specific design requirements identified. All changes are project configuration and documentation.

## Repository Standards

Follow agentry conventions throughout:
- Apache 2.0 license with identical formatting
- CONTRIBUTING.md structure matching agentry's sections
- CHANGELOG.md using Keep a Changelog format
- pyproject.toml tooling sections matching agentry's ruff/mypy/pytest config patterns
- GitHub Actions CI with the same quality gates

## Technical Considerations

- **Ruff expanded rules may surface new violations.** Adding `I` (isort), `N` (pep8-naming), `UP` (pyupgrade), `B` (bugbear), `C4` (comprehensions), `SIM` (simplify) may flag existing code. These must be fixed as part of Unit 3 to ensure CI passes.
- **mypy test override** relaxes strict mode for test files only, matching agentry. This avoids requiring type annotations on every test function.
- **Git history** — moving `distillery-brainstorm.md` uses `git mv` to preserve history.

## Security Considerations

- No secrets or credentials involved
- Scan confirmed: no hardcoded API keys in committed files (only example placeholders like `your-jina-api-key` and `sk-...` in docstrings)
- `distillery.yaml` (which could contain env var names) is already in `.gitignore`

## Success Metrics

- `LICENSE`, `CONTRIBUTING.md`, `CHANGELOG.md` exist at repo root
- `pyproject.toml` references Apache-2.0, has classifiers, keywords, extended lint rules
- `ruff check`, `mypy --strict`, and `pytest` all pass
- No `.pyc` files tracked in git
- CI workflow runs on push/PR to main
- `distillery-brainstorm.md` moved to `docs/`

## Open Questions

No open questions at this time.
