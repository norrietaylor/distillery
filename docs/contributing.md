# Contributing

Thank you for your interest in contributing to Distillery. This guide covers environment setup, code style, testing, and the pull request process.

## Prerequisites

- Python 3.11 or later
- `pip` or `uv` for dependency management
- `git`

## Setup

```bash
git clone https://github.com/norrietaylor/distillery.git
cd distillery
pip install -e ".[dev]"
```

Verify:

```bash
distillery health
pytest tests/ -q
```

## Code Style

### Ruff

```bash
ruff check src/ tests/    # lint
ruff format src/ tests/   # format
```

### Mypy

```bash
mypy --strict src/distillery/
```

All code must pass `mypy --strict`. Use `Protocol` rather than abstract base classes — this keeps dependencies minimal and interfaces composable.

## Testing

Distillery uses **pytest** with **pytest-asyncio** (auto mode).

```bash
pytest tests/ -v                  # full suite
pytest tests/ -m unit             # unit tests only
pytest tests/ -m integration      # integration tests only
pytest tests/store/ -v            # specific module
```

### Test Markers

| Marker | Description |
|--------|-------------|
| `unit` | Fast, isolated tests with no external dependencies |
| `integration` | Tests that interact with DuckDB or the file system |
| `slow` | Long-running tests (excluded from fast CI runs) |

All new features must include tests. PRs that reduce coverage will not be merged. CI enforces an 80% coverage threshold.

### Test Fixtures

Key fixtures in `tests/conftest.py`:

- `make_entry()` — factory for `Entry` objects
- `mock_embedding_provider` — mock for embedding calls
- `deterministic_embedding_provider` — 8-dimensional registry for controlled similarity testing
- `store` — async in-memory DuckDB store

## Commit Conventions

Distillery follows [Conventional Commits](https://www.conventionalcommits.org/).

```text
<type>(<scope>): <description>
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

### Scopes

`store`, `mcp`, `embedding`, `classification`, `config`, `skills`, `cli`, `auth`, `feeds`

### Examples

```text
feat(store): add DuckDB vector search with cosine similarity
fix(mcp): handle missing embedding provider in distillery_recall
docs: update CONTRIBUTING.md with new test markers
test(classification): add integration tests for DeduplicationChecker
```

## Pull Request Process

1. **Branch from `main`**:
   ```bash
   git checkout main && git pull
   git checkout -b feat/your-feature-name
   ```

2. **Keep commits focused** — one logical change per commit

3. **Ensure CI passes** — lint, type checking, and tests must all be green

4. **Include tests** — new features need tests; bug fixes need regression tests

5. **Update CHANGELOG.md** — add an entry under `[Unreleased]`

6. **Open a PR against `main`** with a clear title following Conventional Commits format

## Architecture Overview

See [Architecture](architecture.md) for the full system design. New contributors should start with:

- `src/distillery/models.py` — the `Entry` data model
- `src/distillery/store/protocol.py` — the store interface

## License

Apache 2.0. By submitting a contribution, you agree that your changes will be licensed under the same terms.
