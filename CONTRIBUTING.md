# Contributing to Distillery

Thank you for your interest in contributing to Distillery. This guide covers everything you need
to get started, from setting up your environment to submitting a pull request.

---

## Prerequisites

- Python 3.11 or later
- `pip` or `uv` for dependency management
- A working installation of `git`

---

## Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/norrietaylor/distillery.git
   cd distillery
   ```

2. Install in editable dev mode:
   ```bash
   pip install -e ".[dev]"
   ```
   Or with `uv`:
   ```bash
   uv pip install -e ".[dev]"
   ```

3. Verify the installation:
   ```bash
   distillery health
   python3 -m pytest tests/ -q
   ```

---

## Code Style

Distillery uses **ruff** for linting and formatting, and **mypy** in strict mode for type checking.

### Ruff

Run linting:
```bash
ruff check src/ tests/
```

Run formatting:
```bash
ruff format src/ tests/
```

### Mypy

Run type checking:
```bash
mypy src/distillery/
```

All code must pass `mypy --strict`. Use `Protocol` rather than abstract base classes where
possible — this keeps dependencies minimal and makes the interfaces composable.

---

## Testing

Distillery uses **pytest** with **pytest-asyncio** for async test support.

### Running tests

Run the full test suite:
```bash
python3 -m pytest tests/ -v
```

Run a specific marker subset:
```bash
python3 -m pytest tests/ -m unit
python3 -m pytest tests/ -m integration
```

Run tests for a specific module:
```bash
python3 -m pytest tests/store/ -v
python3 -m pytest tests/classification/ -v
```

### Test markers

| Marker | Description |
|--------|-------------|
| `unit` | Fast, isolated tests with no external dependencies |
| `integration` | Tests that interact with DuckDB or the file system |
| `slow` | Long-running tests (excluded from fast CI runs) |

All new features must include tests. PRs that reduce test coverage will not be merged.

---

## Commit Conventions

Distillery follows [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

### Format

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types

| Type | When to use |
|------|-------------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation only |
| `test` | Adding or fixing tests |
| `refactor` | Code change that is not a fix or feature |
| `chore` | Build process, dependency updates, tooling |

### Distillery-specific examples

```
feat(store): add DuckDB vector search with cosine similarity
fix(mcp): handle missing embedding provider in distillery_recall
docs: update CONTRIBUTING.md with new test markers
test(classification): add integration tests for DeduplicationChecker
feat(embedding): implement JinaEmbeddingProvider with task types
chore: update ruff to v0.4 and fix new lint warnings
```

Scope values: `store`, `mcp`, `embedding`, `classification`, `config`, `skills`, `cli`, `auth`, `feeds`

---

## Pull Request Process

1. **Branch from `main`**:
   ```bash
   git checkout main && git pull
   git checkout -b feat/your-feature-name
   ```

2. **Keep commits focused** — one logical change per commit. Squash fixup commits before
   opening a PR.

3. **Ensure CI is green** — all lint, type checking, and tests must pass.

4. **Include tests** — new behaviour must be covered by tests. Bug fixes should include a
   regression test.

5. **Update CHANGELOG.md** — add an entry under `[Unreleased]` describing the change.

6. **Open a PR against `main`** with a clear title following Conventional Commits format.
   Fill in the PR template, describing what changed and why.

7. **Respond to review feedback promptly**. Unresponsive PRs may be closed after 30 days.

---

## Architecture Overview

Distillery is built as a 4-layer model:

```
Skills (Claude Code slash commands)
    ↓
MCP Server (distillery-mcp)
    ↓
Store / Embedding / Classification (Python protocols)
    ↓
DuckDB (local persistent storage)
```

### Layers

| Layer | Description | Key types |
|-------|-------------|-----------|
| **Skills** | `/distill`, `/recall`, `/pour`, `/bookmark`, `/minutes`, `/classify`, `/watch`, `/radar`, `/tune` — SKILL.md files that orchestrate MCP tool calls | — |
| **MCP Server** | FastMCP server exposing 21 tools over stdio/HTTP transport | `mcp/server.py` |
| **Core protocols** | `DistilleryStore`, `EmbeddingProvider`, `ClassificationEngine` — typed `Protocol` interfaces | `store/protocol.py`, `embedding/protocol.py`, `classification/engine.py` |
| **DuckDB backend** | `DuckDBStore` implements `DistilleryStore`; vector similarity search via VSS extension | `store/duckdb.py` |

New contributors should start by reading `src/distillery/models.py` (the `Entry` data model)
and `src/distillery/store/protocol.py` (the store interface) to understand the core data flow.

---

## License

Licensed under the [Apache License 2.0](LICENSE). By submitting a contribution, you agree that
your changes will be licensed under the same terms.
