# 05-spec-developer-experience

## Introduction/Overview

This spec improves the developer experience around Distillery by fixing the broken CLI entry point, hardening CI with multi-version testing and coverage enforcement, consolidating duplicated test infrastructure, and adding MCP round-trip E2E tests. These changes reduce friction for contributors, catch regressions earlier, and establish a foundation for future CLI commands.

## Goals

1. Fix the broken `distillery` CLI entry point with status and health subcommands
2. Add Python 3.12/3.13 CI matrix with pip caching and 80% coverage threshold
3. Eliminate duplicated test helpers by creating a shared `conftest.py`
4. Add MCP server E2E tests covering full tool round-trips (store → search → classify → review)
5. Clean up dependency declarations — dev tools out of core dependencies

## User Stories

- As a **developer**, I want `distillery status` to show database stats so I can verify my local setup works without launching the MCP server.
- As a **contributor**, I want CI to test against Python 3.12 and 3.13 so I know my changes work across supported versions.
- As a **contributor**, I want a single `conftest.py` with shared fixtures so I don't have to copy-paste helpers when writing new tests.
- As a **maintainer**, I want E2E tests that exercise the MCP server lifecycle so that protocol-level regressions are caught automatically.
- As a **user**, I want `pip install distillery` to only install runtime dependencies, not dev tools.

## Demoable Units of Work

### Unit 1: CLI Entry Point & Dependency Cleanup

**Purpose:** Fix the broken `distillery` command, add read-only diagnostics, and clean up pyproject.toml so core dependencies only include runtime packages.

**Functional Requirements:**

- The system shall provide a `distillery.cli` module with a `main()` function matching the existing `project.scripts` entry point
- `distillery status` shall display: total entry count, entries by type, entries by status, database path, embedding model, and database file size — matching the output of the `distillery_status` MCP tool
- `distillery health` shall verify database connectivity and report success/failure with exit code 0/1
- `distillery --version` shall print the package version from `distillery.__init__`
- `distillery` with no subcommand shall print usage help and exit 0
- The CLI shall load config via the same `load_config()` chain as the MCP server (explicit path → `DISTILLERY_CONFIG` → `distillery.yaml` → defaults)
- The CLI shall support `--config PATH` to override the config file location
- `pyproject.toml` core `dependencies` shall contain only runtime packages: `duckdb`, `pyyaml`, `httpx`, `mcp`
- `pyproject.toml` `[project.optional-dependencies] dev` shall contain all dev/test tools: `pytest`, `pytest-asyncio`, `pytest-cov`, `mypy`, `ruff`, `types-PyYAML`
- The CLI module shall pass `mypy --strict` and `ruff check`

**Proof Artifacts:**
- CLI: `distillery status` returns JSON with `total_entries` field on a fresh database
- CLI: `distillery health` exits 0 with "OK" message when database is accessible
- CLI: `distillery --version` prints `distillery 0.1.0`
- CLI: `pip install .` (without `[dev]`) succeeds and does not install pytest or mypy
- Test: `tests/test_cli.py` passes — covers status, health, version, help, invalid subcommand, and --config override

### Unit 2: Test Infrastructure Consolidation

**Purpose:** Eliminate duplicated fixtures and helpers across 6+ test modules by centralizing them in `conftest.py`.

**Functional Requirements:**

- The system shall provide `tests/conftest.py` with shared fixtures and helpers
- `conftest.py` shall define a `make_entry(**kwargs) -> Entry` factory function (replacing `_make_entry` in 6 modules)
- `conftest.py` shall define a `parse_mcp_response(content) -> dict` helper (replacing `_parse_response` in 3 modules)
- `conftest.py` shall define three embedding provider fixtures:
  - `mock_embedding_provider` — hash-based, 4D vectors (for basic store tests)
  - `deterministic_embedding_provider` — registry + hash fallback, 4D (for search/similarity tests)
  - `controlled_embedding_provider` — registry + L2 normalization, 8D (for precise threshold tests)
- `conftest.py` shall define a `store` fixture — async DuckDBStore with in-memory DB and mock embedding provider
- All existing test modules shall import from `conftest.py` instead of defining local duplicates
- No existing test shall change behavior — all 368 tests shall continue to pass
- The `conftest.py` module shall include type annotations compatible with `mypy --strict` (using `tests.*` override)

**Proof Artifacts:**
- Test: `pytest tests/ -v` passes with 368+ tests (zero regressions)
- File: `tests/conftest.py` exists and contains `make_entry`, `parse_mcp_response`, and 3 embedding provider fixtures
- CLI: `grep -r "_make_entry" tests/` returns only `conftest.py` (no duplicates in other modules)

### Unit 3: CI Hardening

**Purpose:** Expand CI to test Python 3.12/3.13, add pip caching, enforce 80% coverage threshold, and apply test markers.

**Functional Requirements:**

- `.github/workflows/ci.yml` shall use a matrix strategy testing Python 3.11, 3.12, and 3.13
- The CI workflow shall cache pip dependencies using `actions/setup-python@v5` with `cache: 'pip'`
- The pytest step shall run with `--cov=src --cov-report=term-missing --cov-fail-under=80`
- The CI workflow shall upload a coverage report as a GitHub Actions artifact
- Test files shall apply `@pytest.mark.unit` or `@pytest.mark.integration` markers to all test functions/classes
- The `addopts` in `pyproject.toml` shall not include coverage flags (keep them in CI only, to avoid slowing local runs)
- All 368+ tests shall pass on Python 3.11, 3.12, and 3.13

**Proof Artifacts:**
- File: `.github/workflows/ci.yml` contains `matrix: python-version: ["3.11", "3.12", "3.13"]`
- File: `.github/workflows/ci.yml` contains `--cov-fail-under=80`
- CLI: `pytest tests/ -m unit` runs only unit-marked tests
- CLI: `pytest tests/ -m integration` runs only integration-marked tests

### Unit 4: MCP Server E2E Tests

**Purpose:** Add end-to-end tests that exercise the full MCP server lifecycle — initialization, tool dispatch, and shutdown — to catch protocol-level regressions.

**Functional Requirements:**

- The system shall provide `tests/test_e2e_mcp.py` with E2E tests for the MCP server
- E2E tests shall use `StubEmbeddingProvider` (no API keys required) and in-memory DuckDB
- E2E tests shall exercise the MCP server through its public interface (`create_server`, `_lifespan`, `_call_tool` dispatcher) rather than calling individual handlers directly
- The test suite shall cover the following round-trip scenarios:
  1. **Store → Get**: store an entry via `distillery_store`, retrieve it via `distillery_get`, verify content matches
  2. **Store → Search**: store 3 entries, search via `distillery_search`, verify results returned (scores may be degenerate with stub embeddings — test structure, not ranking)
  3. **Store → Find Similar**: store entries, call `distillery_find_similar`, verify response structure
  4. **Store → Classify → Review Queue → Resolve**: store entry → classify with low confidence → verify appears in review queue → resolve (approve) → verify status is active
  5. **Store → Check Dedup**: store entry, check dedup for identical content, verify action returned
  6. **Store → Update → Get**: store entry, update content, get and verify version incremented
  7. **Store → List**: store multiple entries, list with pagination (limit/offset), verify ordering (newest first)
  8. **Status**: call `distillery_status` on empty DB, verify zero counts; store entries, verify counts update
  9. **Error paths**: call `distillery_get` with non-existent ID → NOT_FOUND; call `distillery_store` with missing fields → INVALID_INPUT
- Each test shall verify the full JSON response structure (not just success/failure)
- E2E tests shall be marked with `@pytest.mark.integration`
- E2E tests shall use shared fixtures from `conftest.py` (depends on Unit 2)

**Proof Artifacts:**
- Test: `pytest tests/test_e2e_mcp.py -v` passes with 9+ test scenarios
- Test: Each scenario exercises at least 2 MCP tools in sequence (true round-trip, not isolated calls)
- CLI: `pytest tests/test_e2e_mcp.py --tb=long` shows full tool call → response chain on failure

## Non-Goals (Out of Scope)

- CLI commands for write operations (store, update, delete) — deferred to a future spec
- MCP stdio transport testing (actual stdin/stdout protocol framing) — tests use the handler dispatch layer
- Pre-commit hooks — quality gates remain CI-only per current conventions
- Coverage threshold above 80% — can be raised incrementally
- Replacing `unittest.mock` patterns with a different mocking library

## Design Considerations

- CLI output shall be JSON by default (machine-readable), with a `--format text` flag for human-readable output
- CLI shall reuse the same `DuckDBStore` and config loading as the MCP server — no parallel implementation
- E2E tests exercise the dispatcher (`_call_tool`) rather than raw MCP transport to keep tests fast and deterministic

## Repository Standards

- Conventional Commits: `feat(cli):`, `refactor(tests):`, `chore(ci):`, `test(e2e):`
- Scopes: `cli`, `tests`, `ci`, `config`
- mypy strict for `src/`, relaxed for `tests/`
- ruff with existing rule set (E, W, F, I, N, UP, B, C4, SIM)
- All async tests use `asyncio_mode = "auto"`

## Technical Considerations

- The CLI module must be importable without heavy dependencies (lazy-import DuckDB and embedding providers)
- `conftest.py` fixtures use `yield` for async lifecycle management (initialize → yield → close)
- Python 3.12/3.13 compatibility: verify `StrEnum`, `asyncio.to_thread`, and DuckDB VSS extension work across versions
- Coverage measurement: `--cov=src` covers only production code, not test files
- The `_state` dict pattern in MCP server means E2E tests need to exercise `create_server()` to get a properly initialized server instance

## Security Considerations

- CLI `distillery status` may expose database file path — acceptable for a local CLI tool
- No API keys are required for CLI status/health (uses config but doesn't call embedding APIs)
- E2E tests use `StubEmbeddingProvider` — no secrets needed in CI

## Success Metrics

- `distillery status` and `distillery health` work on first try after `pip install -e .`
- CI runs complete in under 5 minutes across all 3 Python versions
- Coverage stays above 80% as measured by `pytest-cov`
- Zero test regressions (368+ existing tests continue to pass)
- New contributors can run `pytest tests/ -m unit` for fast feedback (< 10 seconds)

## Open Questions

- No open questions at this time.
