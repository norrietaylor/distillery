# 09-spec-sprint1-foundation

## Introduction/Overview

Harden the Distillery platform for multi-user deployment by completing two foundation pieces: authenticated GitHub feed polling for private repositories (#74), and exposing audit log data through `distillery_metrics` so operators can monitor instance usage (#148). DuckDB versioning (#62) is already implemented and excluded from this spec.

## Goals

1. GitHub feed adapter passes `GITHUB_TOKEN` to API requests, enabling private repo monitoring and higher rate limits
2. Redirects (301) from renamed/transferred repos are followed transparently
3. Token is never logged or exposed in entry metadata
4. `distillery_metrics(scope="audit")` returns login history, user activity, and recent operations
5. Audit log reads go through the `DistilleryStore` protocol via a new `query_audit_log` method

## User Stories

- As an **operator**, I want to monitor private GitHub repositories so that my team's internal activity feeds into the knowledge base.
- As an **operator**, I want to see who has accessed the shared Distillery instance so that I can detect unauthorized access attempts and understand usage patterns.
- As a **developer**, I want audit log data exposed through the existing metrics tool so that I don't need direct database access to inspect login history.

## Demoable Units of Work

### Unit 1: GitHub Token Passthrough for Private Repo Polling

**Purpose:** Wire the global `GITHUB_TOKEN` env var through the poller to the GitHub adapter, enabling private repo event fetching with automatic redirect following.

**Functional Requirements:**
- The system shall pass `GITHUB_TOKEN` (read from environment) to `GitHubAdapter` when constructed by `_build_adapter()` in `feeds/poller.py`
- The system shall follow HTTP 301 redirects transparently when fetching GitHub events (httpx default behavior — verify not disabled)
- The system shall never include the GitHub token value in stored entry metadata, log messages, or error responses
- The system shall add the `ghp_` and `github_pat_` token patterns to `security.py` redaction if not already present (verify coverage)
- The system shall continue to work without a token configured — unauthenticated polling of public repos remains functional
- The system shall log (at DEBUG level) whether authenticated or unauthenticated mode is active when polling starts

**Proof Artifacts:**
- Test: `tests/test_feeds.py` — new test verifying `_build_adapter()` passes token to `GitHubAdapter`
- Test: `tests/test_feeds.py` — test confirming adapter works without token (backward compatibility)
- Test: `tests/test_security.py` — test verifying GitHub token patterns are redacted from log output
- CLI: `distillery poll` with `GITHUB_TOKEN` set fetches events from a private repo without errors

### Unit 2: Audit Log Store Protocol Method

**Purpose:** Add a `query_audit_log` method to the `DistilleryStore` protocol and implement it in `DuckDBStore`, providing the read path for audit data.

**Functional Requirements:**
- The system shall add `query_audit_log(filters: dict[str, Any] | None = None, limit: int = 50) -> list[dict[str, Any]]` to the `DistilleryStore` protocol in `store/protocol.py`
- The system shall implement `query_audit_log` in `store/duckdb.py` with the following filter support:
  - `user` (str): Filter by `user_id` exact match
  - `operation` (str): Filter by `tool` exact match
  - `date_from` (str, ISO 8601): Filter `timestamp >= date_from`
  - `date_to` (str, ISO 8601): Filter `timestamp <= date_to`
- The system shall return audit log rows as dicts with keys: `id`, `timestamp` (ISO 8601 string), `user_id`, `tool`, `entry_id`, `action`, `outcome`
- The system shall order results by `timestamp DESC` (newest first)
- The system shall validate `limit` in range `[1, 500]` with default `50`
- The system shall use `asyncio.to_thread` wrapping consistent with other store methods

**Proof Artifacts:**
- Test: `tests/test_duckdb_store.py` or `tests/test_store_integration.py` — unit test writing audit records then querying with various filters
- Test: Verify empty audit log returns `[]` without error
- Test: Verify date range filtering works correctly

### Unit 3: Audit Metrics Scope in distillery_metrics

**Purpose:** Add `scope="audit"` to `distillery_metrics`, aggregating audit log data into the 4-section response format specified in #148.

**Functional Requirements:**
- The system shall accept `scope="audit"` as a valid value for `distillery_metrics`
- The system shall accept optional `date_from` and `user` parameters when `scope="audit"`
- The system shall return a response with four sections:
  - `recent_logins`: List of auth events (`auth_login`, `auth_login_failed`, `auth_org_denied`) with user, operation, result, timestamp — limited to 50 most recent
  - `login_summary`: Aggregated counts — `total_logins`, `unique_users`, `failed_attempts`, `org_denials`
  - `active_users`: List of unique users with `last_seen` timestamp and `operation_count` — ordered by last_seen DESC
  - `recent_operations`: List of non-auth tool operations with user, operation, entry_id, timestamp — limited to 50 most recent
- The system shall use `store.query_audit_log()` (from Unit 2) as the data source — no direct SQL in the tool handler
- The system shall apply `date_from` filter to all four sections when provided
- The system shall apply `user` filter to `recent_operations` and `active_users` sections when provided (login sections always show all users for security visibility)
- The system shall return `error_response(INVALID_PARAMS, ...)` if `scope="audit"` is used with incompatible parameters (e.g., `entry_type`)

**Proof Artifacts:**
- Test: `tests/test_mcp_analytics.py` — test `_handle_metrics` with `scope="audit"` returns all 4 sections
- Test: Verify `date_from` filtering narrows results
- Test: Verify `user` filtering narrows `recent_operations` and `active_users`
- Test: Verify empty audit log returns zeroed summary and empty lists
- CLI: `distillery_metrics(scope="audit")` via MCP returns structured JSON with login history

## Non-Goals (Out of Scope)

- Per-source GitHub tokens (each feed source using a different token) — global `GITHUB_TOKEN` only
- Audit log retention/cleanup policies
- Audit log export to external systems
- Real-time audit alerts or notifications
- UI/dashboard for audit data visualization
- DuckDB versioning (#62) — already implemented

## Design Considerations

No specific design requirements identified. All changes are backend/API only.

## Repository Standards

- Conventional Commits: `feat(feeds): ...`, `feat(store): ...`, `feat(mcp): ...`
- mypy `--strict` on all `src/` code
- ruff with line-length 100, rules E/W/F/I/N/UP/B/C4/SIM
- pytest markers: `@pytest.mark.unit` for unit tests, `@pytest.mark.integration` for store tests
- Coverage must remain >= 80%
- All store methods async, wrapped via `asyncio.to_thread` for sync DuckDB ops

## Technical Considerations

- **Token propagation**: `_build_adapter()` in `poller.py` needs access to `GITHUB_TOKEN` env var or config. Simplest path: read `os.environ.get("GITHUB_TOKEN", "")` directly in `_build_adapter()`, matching the existing pattern in `GitHubAdapter.__init__()`.
- **httpx redirect behavior**: httpx does **not** follow redirects by default (`follow_redirects=False`). The `GitHubAdapter` must explicitly set `follow_redirects=True` on `httpx.Client(...)` to handle 301 redirects from renamed/transferred repos.
- **Audit log query performance**: The audit_log table has no indexes beyond the PK. For large deployments, consider whether a timestamp index is needed. For now, `LIMIT 50` keeps queries fast.
- **Protocol extension**: Adding `query_audit_log` to the Protocol is a breaking change for any external implementations. Since `DuckDBStore` is the only implementation, this is acceptable.

## Security Considerations

- `GITHUB_TOKEN` must never appear in stored entry metadata, log output, or MCP tool responses
- Verify `security.py` redaction patterns cover `ghp_`, `gho_`, `github_pat_` prefixes (already present per research)
- Audit metrics should be accessible to all authenticated users (no additional RBAC for reading audit logs)
- `query_audit_log` must use parameterized SQL queries (no string interpolation)

## Success Metrics

- Private GitHub repos can be polled successfully with `GITHUB_TOKEN` set
- `distillery_metrics(scope="audit")` returns valid JSON with all 4 sections
- Zero token leakage in logs or stored entries (verified by security tests)
- All new code passes mypy strict and ruff checks
- Test coverage remains >= 80%

## Open Questions

No open questions at this time.
