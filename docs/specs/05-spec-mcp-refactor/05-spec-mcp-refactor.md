# 05-spec-mcp-refactor

## Introduction/Overview

Refactor the monolithic MCP server (`server.py`, 4,041 lines) into domain-specific modules, standardize error codes, extract shared validation helpers, make hardcoded defaults configurable, and achieve 100% test coverage for middleware and all 22 tool handlers. This is the server-side companion to spec 04 (plugin/skill hardening).

## Goals

1. Split `server.py` into 7 domain modules with clear boundaries and no circular imports
2. Standardize all MCP error codes to a single taxonomy (eliminate `INVALID_INPUT` vs `VALIDATION_ERROR` inconsistency)
3. Extract shared validation logic (limit ranges, required fields) into reusable helpers
4. Make hardcoded defaults (`_DEFAULT_DEDUP_THRESHOLD`, `_DEFAULT_DEDUP_LIMIT`, `_DEFAULT_STALE_DAYS`) configurable via `distillery.yaml`
5. Achieve 100% test coverage for `middleware.py` (432 lines, currently 0%) and all 22 tool handlers (currently 11 untested)

## User Stories

- As a **contributor**, I want MCP handlers organized by domain so that I can find and modify tool logic without navigating a 4,000-line file.
- As a **developer**, I want consistent error codes so that client-side error handling doesn't need to account for multiple codes meaning the same thing.
- As an **operator**, I want dedup thresholds and stale-entry days configurable via `distillery.yaml` so that I can tune behavior per deployment without code changes.
- As a **maintainer**, I want full test coverage on middleware and all handlers so that refactoring is safe and regressions are caught.

## Demoable Units of Work

### Unit 1: server.py Domain Module Split

**Purpose:** Break the monolithic server.py into 7 focused modules under `src/distillery/mcp/tools/`, preserving all existing behavior and the public API surface.

**Functional Requirements:**
- The system shall create a `src/distillery/mcp/tools/` package with the following modules:

  | Module | Handlers | Purpose |
  |--------|----------|---------|
  | `crud.py` | `_handle_status`, `_handle_store`, `_handle_get`, `_handle_update`, `_handle_list` | Core CRUD operations |
  | `search.py` | `_handle_search`, `_handle_find_similar`, `_handle_aggregate` | Search and similarity |
  | `classify.py` | `_handle_classify`, `_handle_review_queue`, `_handle_resolve_review` | Classification and review |
  | `quality.py` | `_handle_check_dedup`, `_handle_check_conflicts` | Data quality checks |
  | `analytics.py` | `_handle_metrics`, `_handle_quality`, `_handle_stale`, `_handle_tag_tree`, `_handle_interests`, `_handle_type_schemas` | Analytics and reporting |
  | `feeds.py` | `_handle_watch`, `_handle_poll`, `_handle_rescore`, `_handle_suggest_sources` | Feed management |
  | `meta.py` | (reserved for future cross-cutting tool concerns) | Tool metadata |

- Each module shall export its handler functions and be imported by `server.py` (or a new `tools/__init__.py`) to register them with FastMCP.
- `server.py` shall be reduced to: FastMCP app creation, lifespan management, shared state initialization, tool registration (importing handlers from domain modules), and middleware composition. Target: ≤500 lines.
- All handler functions shall maintain their existing signatures and behavior — this is a pure structural refactoring with no behavioral changes.
- Shared utilities used by multiple handlers (store access, embedding provider access, config access, error response formatting) shall be extracted to `src/distillery/mcp/tools/_common.py`.
- The `tools/` package `__init__.py` shall re-export all handler registration functions for clean imports.
- All existing tests shall pass without modification after the split.

**Proof Artifacts:**
- File: `src/distillery/mcp/tools/` directory exists with 7 module files + `__init__.py` + `_common.py`
- File: `src/distillery/mcp/server.py` is ≤500 lines
- CLI: `pytest -m unit --tb=short -q` passes with same count as before the split
- CLI: `mypy --strict src/distillery/mcp/` passes with no new errors

### Unit 2: Error Code Standardization and Validation Helpers

**Purpose:** Eliminate the `INVALID_INPUT` / `VALIDATION_ERROR` inconsistency and extract duplicated validation patterns into shared helpers.

**Functional Requirements:**
- The system shall define a standard error code enum or constants module at `src/distillery/mcp/tools/_errors.py` with the following codes:
  - `INVALID_PARAMS` — request parameters fail validation (replaces both `INVALID_INPUT` and `VALIDATION_ERROR`)
  - `NOT_FOUND` — requested resource does not exist
  - `CONFLICT` — operation conflicts with existing state (e.g., dedup detection)
  - `INTERNAL` — unexpected server-side error
- All 22 handlers shall use only these standardized error codes.
- The system shall provide a `validate_limit(value, min_val=1, max_val=1000, default=50)` helper in `_common.py` that returns the validated integer or raises a standardized error.
- The system shall provide a `validate_required(params, *field_names)` helper that checks for missing required fields and returns a standardized error listing all missing fields.
- The system shall provide a `tool_error(code, message)` helper that formats a consistent MCP error response.
- All existing hardcoded limit-validation patterns (repeated in `_handle_search`, `_handle_list`, `_handle_find_similar`, `_handle_aggregate`, etc.) shall be replaced with calls to `validate_limit()`.

**Proof Artifacts:**
- File: `src/distillery/mcp/tools/_errors.py` exists with 4 standardized error codes
- CLI: `grep -r 'INVALID_INPUT\|VALIDATION_ERROR' src/distillery/mcp/` returns no matches
- Test: `pytest tests/test_mcp_server.py -v` passes (existing error-related tests still work)

### Unit 3: Configurable Defaults

**Purpose:** Move hardcoded operational defaults into `distillery.yaml` configuration so operators can tune behavior per deployment.

**Functional Requirements:**
- The `distillery.yaml` configuration schema shall be extended with a `defaults` section:
  ```yaml
  defaults:
    dedup_threshold: 0.92
    dedup_limit: 3
    stale_days: 30
  ```
- The `Config` dataclass in `config.py` shall include a `defaults` field with a `DefaultsConfig` dataclass containing `dedup_threshold` (float, default 0.92), `dedup_limit` (int, default 3), and `stale_days` (int, default 30).
- Handlers that currently reference `_DEFAULT_DEDUP_THRESHOLD`, `_DEFAULT_DEDUP_LIMIT`, and `_DEFAULT_STALE_DAYS` constants shall read from the config object instead.
- The constants shall be removed from `server.py` (or the new domain modules).
- If the `defaults` section is absent from `distillery.yaml`, the existing default values shall be used (backward compatible).

**Proof Artifacts:**
- File: `src/distillery/config.py` contains `DefaultsConfig` dataclass with 3 fields
- File: No `_DEFAULT_DEDUP_THRESHOLD`, `_DEFAULT_DEDUP_LIMIT`, or `_DEFAULT_STALE_DAYS` constants in `src/distillery/mcp/`
- Test: `pytest tests/test_config.py -v` passes with new defaults config tests
- CLI: Setting `defaults.dedup_threshold: 0.85` in `distillery.yaml` changes dedup behavior

### Unit 4: Full Test Coverage — Middleware and All Handlers

**Purpose:** Achieve 100% test coverage for `middleware.py` and all 22 MCP tool handlers, closing the highest-risk quality gap.

**Functional Requirements:**
- The system shall include tests for all 3 middleware classes in a new `tests/test_middleware.py`:
  - **RateLimitMiddleware**: per-IP rate limiting (per-minute and per-hour windows), sliding window expiry, rate limit header presence, 429 response with `Retry-After`
  - **BodySizeLimitMiddleware**: requests within limit pass through, oversized requests receive 413, boundary conditions
  - **OrgMembershipMiddleware**: valid org member passes, non-member rejected with 403, missing auth header handling, GitHub API error handling, caching behavior
- The system shall include tests for all 11 currently untested handlers. New test files shall follow the existing pattern (one file per domain or grouped logically):
  - `tests/test_mcp_analytics.py` — `aggregate`, `tag_tree`, `type_schemas`, `metrics`, `quality`, `stale`, `interests`
  - `tests/test_mcp_feeds.py` — `watch`, `poll`, `suggest_sources`
  - `tests/test_mcp_conflicts.py` — `check_conflicts`
- Each handler test shall cover: (a) successful operation with valid input, (b) validation error with invalid input, (c) edge cases specific to the handler's domain.
- All tests shall use the existing test fixtures from `conftest.py` (`make_entry`, `store`, `mock_embedding_provider`).
- All tests shall be marked with `@pytest.mark.unit`.
- After all tests are added, `pytest --cov=src/distillery/mcp --cov-report=term-missing` shall show ≥95% coverage for the `mcp/` package.

**Proof Artifacts:**
- File: `tests/test_middleware.py` exists with tests for all 3 middleware classes
- File: `tests/test_mcp_analytics.py` exists with tests for 7 handlers
- File: `tests/test_mcp_feeds.py` exists with tests for 3 handlers
- File: `tests/test_mcp_conflicts.py` exists with tests for `check_conflicts`
- CLI: `pytest --cov=src/distillery/mcp --cov-fail-under=95` passes
- CLI: `pytest -m unit --tb=short -q` shows increased test count (expect ~100+ new tests)

## Non-Goals (Out of Scope)

- Skill/plugin frontmatter changes — covered in spec 04
- Tool count consolidation (#99) — separate issue
- `X-Request-ID` correlation support — deferred
- Hook definitions — deferred
- Custom agent definition — deferred
- Behavioral changes to any handler — this is structural refactoring + test coverage only
- HTTP transport changes or webhook modifications

## Design Considerations

No specific design requirements identified. The module split follows standard Python package conventions.

## Repository Standards

- **Conventional Commits**: `refactor(mcp):` for the split, `test(mcp):` for coverage, `feat(config):` for configurable defaults
- **mypy --strict** on all new `src/` files
- **ruff** formatting on all new files
- **pytest-asyncio** auto mode for async handler tests
- **Test markers**: `@pytest.mark.unit` on all new tests

## Technical Considerations

- **Circular imports**: The domain modules will need access to shared state (store, embedding provider, config). This shall be passed via a shared context object or accessed through the FastMCP app's lifespan state, not via module-level imports of `server.py`.
- **FastMCP tool registration**: Handlers are registered via `@mcp.tool()` decorators. After the split, registration can happen either via decorators in the domain modules (importing the `mcp` app instance) or via explicit registration in `server.py` (importing handler functions). The latter avoids circular imports.
- **Backward compatibility**: The refactoring must not change any tool's name, description, parameter schema, or response format. The MCP protocol surface is the contract.
- **Test isolation**: Middleware tests need an ASGI test client. Use `httpx.AsyncClient` with `ASGITransport` to test middleware in isolation without starting a real server.

## Security Considerations

- Middleware tests for `OrgMembershipMiddleware` must verify that org membership checks cannot be bypassed (missing header, invalid token, non-member).
- Middleware tests for `RateLimitMiddleware` must verify that rate limits are enforced per-IP and cannot be trivially circumvented.
- Error responses must not leak internal state (stack traces, file paths, database details) — standardized error codes help enforce this.

## Success Metrics

| Metric | Target |
|--------|--------|
| `server.py` line count | ≤500 lines |
| Domain modules | 7 files in `mcp/tools/` |
| Error code consistency | 0 occurrences of `INVALID_INPUT` or `VALIDATION_ERROR` |
| `mcp/` package test coverage | ≥95% |
| New test count | ~100+ new unit tests |
| Hardcoded defaults removed | 0 `_DEFAULT_*` constants in `mcp/` |

## Open Questions

No open questions at this time.
