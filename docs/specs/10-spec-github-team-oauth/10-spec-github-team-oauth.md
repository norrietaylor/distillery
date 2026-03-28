# 10-spec-github-team-oauth

## Introduction/Overview

This spec adds remote team access to the Distillery MCP server. Today Distillery runs exclusively over stdio transport — a local-only tool. This spec adds streamable-HTTP transport, GitHub OAuth authentication via FastMCP's built-in `GitHubProvider`, MotherDuck storage validation for shared backends, and team setup documentation. Together these allow team members to connect to a hosted Distillery instance from their Claude Code installations using their GitHub account.

The codebase is architecturally ready: the lifespan context manager (`server.py:247-310`) already implements a singleton pattern for stateless HTTP sessions, and `StorageConfig` already models MotherDuck backends. This spec completes the wiring.

**Epic:** [#24](https://github.com/norrietaylor/distillery/issues/24)
**Child issues:** #25 (HTTP transport), #26 (GitHub OAuth), #27 (Horizon deploy — deferred), #28 (shared storage), #29 (team docs), #30 (tests)

## Goals

1. Add streamable-HTTP transport via `--transport http` CLI flag, keeping stdio as default
2. Secure HTTP transport with GitHub OAuth using FastMCP's `GitHubProvider`
3. Validate MotherDuck backend configuration for shared multi-instance deployments
4. Add auth configuration to `distillery.yaml` to support future multi-team extension
5. Document team member setup for remote MCP connection
6. Maintain full backward compatibility — stdio mode unchanged, no auth required locally

## User Stories

- As a **team member**, I want to connect my Claude Code to a hosted Distillery instance so that I can access shared team knowledge without running the server locally.
- As a **team member**, I want to authenticate with my GitHub account so that I don't need separate credentials for Distillery.
- As an **operator**, I want to start the MCP server in HTTP mode with `--transport http` so that I can deploy it as a persistent endpoint.
- As an **operator**, I want the server to refuse to start in HTTP mode without GitHub OAuth credentials so that I can't accidentally deploy an unauthenticated endpoint.
- As an **operator**, I want MotherDuck configuration validated at startup so that misconfigured shared storage fails fast with a clear error.
- As a **contributor**, I want auth configuration in `distillery.yaml` so that future multi-team features (org-based access, team mapping) can extend it without restructuring.

## Demoable Units of Work

### Unit 1: HTTP Transport + MotherDuck Validation

**Purpose:** Add a `--transport` CLI flag so the MCP server can run as a persistent streamable-HTTP endpoint, and validate MotherDuck backend configuration for shared deployments.

**Issues:** [#25](https://github.com/norrietaylor/distillery/issues/25), [#28](https://github.com/norrietaylor/distillery/issues/28)

**Functional Requirements:**

- `pyproject.toml` shall bump the `fastmcp` dependency from `>=2.0.0` to `>=2.12.0`
- `src/distillery/mcp/__main__.py` shall add an `argparse`-based CLI with:
  - `--transport`: `stdio` (default) | `http`
  - `--host`: bind address (default `0.0.0.0`, env fallback `DISTILLERY_HOST`)
  - `--port`: bind port (default `8000`, env fallback `DISTILLERY_PORT`)
- When `--transport http`: call `server.run(transport="streamable-http", host=host, port=port, path="/mcp", stateless_http=True)`
- When `--transport stdio` (or no flag): existing `server.run_stdio_async(show_banner=False)` behavior, unchanged
- `src/distillery/config.py` shall add validation: when `storage.backend == "motherduck"`, `storage.database_path` must start with `md:`. Raise `ValueError` with clear message otherwise
- `src/distillery/config.py` shall add validation: when `storage.backend == "motherduck"` and the env var named by `motherduck_token_env` is not set, raise `ValueError` at config validation time (not deferred to DuckDB connection)
- The lifespan singleton pattern in `server.py:247-310` shall continue to work correctly in stateless HTTP mode — no changes needed, but this must be verified by test

**Proof Artifacts:**

- Test: `tests/test_mcp_http_transport.py::test_http_server_starts` — `--transport http` binds and responds to MCP `initialize` handshake
- Test: `tests/test_mcp_http_transport.py::test_all_tools_accessible_over_http` — all 17 tools appear in `tools/list` response over HTTP
- Test: `tests/test_mcp_http_transport.py::test_stateless_http_singleton` — two sequential HTTP requests share the same store instance (lifespan singleton verified)
- Test: `tests/test_config.py::test_motherduck_backend_requires_md_prefix` — validation rejects non-`md:` path with motherduck backend
- Test: `tests/test_config.py::test_motherduck_missing_token_raises` — missing token env var raises `ValueError`
- Test: `tests/test_mcp_http_transport.py::test_stdio_default_unchanged` — `distillery-mcp` with no flags starts stdio mode (backward compatibility)

### Unit 2: GitHub OAuth Authentication

**Purpose:** Secure the HTTP endpoint with GitHub OAuth so only authenticated team members can connect. Stdio mode remains unauthenticated.

**Issue:** [#26](https://github.com/norrietaylor/distillery/issues/26)

**Functional Requirements:**

- New `src/distillery/mcp/auth.py` shall provide `build_github_auth(config: DistilleryConfig) -> GitHubProvider` that:
  - Reads `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` from the env var names specified in `config.server.auth.client_id_env` and `config.server.auth.client_secret_env`
  - Raises `ValueError` with a clear message if either env var is missing or empty
  - Returns a configured `fastmcp.server.auth.providers.github.GitHubProvider` instance
  - Never logs secret values at any log level
- `create_server()` in `server.py` shall accept an optional `auth: AuthProvider | None` parameter and pass it to `FastMCP("distillery", lifespan=lifespan, auth=auth)`
- `__main__.py` shall wire auth when `--transport http`:
  - Call `build_github_auth(config)` and pass result to `create_server(config=config, auth=auth)`
  - If `config.server.auth.provider` is `"none"` or unset, skip auth (allows HTTP without OAuth for local testing)
- `__main__.py` shall NOT wire auth for stdio transport — no credentials required
- `distillery.yaml` shall support a new `server` section:
  ```yaml
  server:
    auth:
      provider: github          # github | none
      client_id_env: GITHUB_CLIENT_ID
      client_secret_env: GITHUB_CLIENT_SECRET
  ```
- `src/distillery/config.py` shall add:
  - `ServerAuthConfig` dataclass with fields: `provider` (str, default `"none"`), `client_id_env` (str, default `"GITHUB_CLIENT_ID"`), `client_secret_env` (str, default `"GITHUB_CLIENT_SECRET"`)
  - `ServerConfig` dataclass with field: `auth` (`ServerAuthConfig`)
  - `DistilleryConfig.server` field (`ServerConfig`)
  - Validation: `server.auth.provider` must be one of `{"github", "none"}`
- The `GitHubProvider` constructor shall receive:
  - `client_id`: value from the env var
  - `client_secret`: value from the env var
  - `base_url`: constructed from host/port or a `DISTILLERY_BASE_URL` env var (required in HTTP+auth mode)

**Proof Artifacts:**

- Test: `tests/test_mcp_auth.py::test_build_github_auth_reads_env` — `build_github_auth()` reads correct env vars from config
- Test: `tests/test_mcp_auth.py::test_build_github_auth_missing_client_id` — raises `ValueError` with clear message
- Test: `tests/test_mcp_auth.py::test_build_github_auth_missing_client_secret` — raises `ValueError` with clear message
- Test: `tests/test_mcp_auth.py::test_stdio_mode_no_auth_required` — `create_server()` with `auth=None` starts cleanly
- Test: `tests/test_mcp_auth.py::test_no_secrets_in_logs` — with debug logging enabled, no secret values appear in log output
- Test: `tests/test_config.py::test_server_auth_config_parsing` — YAML `server.auth` section parses correctly
- Test: `tests/test_config.py::test_server_auth_invalid_provider` — invalid provider raises `ValueError`
- Test: `tests/test_mcp_http_transport.py::test_http_auth_identity_visible_to_tools` — smoke test: start HTTP server with `DebugTokenVerifier`, make authenticated request, assert tool handler can read caller identity from FastMCP `Context` (validates multi-team extension point)

### Unit 3: Team Setup Documentation

**Purpose:** Document how team members connect to a hosted Distillery instance and authenticate with GitHub OAuth. Audit existing skills for stdio-specific assumptions.

**Issues:** [#29](https://github.com/norrietaylor/distillery/issues/29)

**Functional Requirements:**

- New `docs/team-setup.md` shall document:
  - Adding the remote server to Claude Code (`~/.claude/settings.json` with `url` and `transport: "http"`)
  - First-time GitHub OAuth login flow (browser opens for authorization)
  - Verifying connection works (invoke any skill, e.g. `/recall test`)
  - Troubleshooting: auth failure, connection timeout, wrong URL, expired token
- New `docs/deployment.md` shall document:
  - Operator setup: GitHub OAuth App registration (homepage URL, callback URL pattern)
  - Environment variables required for HTTP mode (`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `DISTILLERY_BASE_URL`, `MOTHERDUCK_TOKEN`)
  - `distillery.yaml` server section configuration
  - Starting the server: `distillery-mcp --transport http --port 8000`
  - Placeholder section for Prefect Horizon deployment (to be completed in a follow-up)
- `distillery.yaml.example` shall be updated with the `server` section (commented out, with explanatory notes)
- All skills in `.claude/skills/` shall be audited for stdio-specific assumptions. Any issues found shall be documented as GitHub issues for follow-up (not fixed in this spec unless trivial)

**Proof Artifacts:**

- File: `docs/team-setup.md` exists with sections: connection setup, authentication, verification, troubleshooting
- File: `docs/deployment.md` exists with sections: OAuth app setup, environment variables, server config, startup, Horizon placeholder
- File: `distillery.yaml.example` contains `server:` section with auth config and comments
- File: Skills audit results documented in `docs/specs/10-spec-github-team-oauth/skills-audit.md`

## Non-Goals (Out of Scope)

- Prefect Horizon deployment configuration (`prefect.yaml`) — follow-up after transport+auth are proven (#27)
- Per-entry `team_id` or visibility flags — backlog item #12, planned as next spec
- Multi-team access control, org-based team mapping, or RBAC — future spec building on the `server.auth` extension point
- Elasticsearch migration — separate Phase 2 initiative
- WebSocket transport — only streamable-HTTP is in scope
- Rate limiting or request quotas — defer to hosting platform (Horizon)
- Token refresh or session management beyond what FastMCP provides natively

## Design Considerations

### Config: Hybrid CLI + YAML approach

Transport mode (`--transport`, `--host`, `--port`) is a **runtime concern** — the same deployment may run in stdio for local dev and HTTP when deployed. These stay as CLI flags with env var fallbacks, not in YAML. This avoids maintaining separate config files per environment.

Auth configuration (`provider`, `client_id_env`, `client_secret_env`) is a **deployment identity concern** that will grow with multi-team features (`allowed_orgs`, `required_scopes`, `team_mapping`). This lives in the YAML `server.auth` section where it can be extended naturally. The `--transport http` flag triggers reading the auth config; stdio ignores it entirely.

### Multi-team extension point

This spec deliberately lays groundwork for the next spec (multi-team access control, backlog #12 and #32):

1. **Auth config in YAML** — the `server.auth` section provides a natural home for `allowed_orgs`, `required_scopes`, and `team_mapping` in a follow-up spec
2. **Smoke test for per-request identity** — Unit 2's `test_http_auth_identity_visible_to_tools` verifies that tool handlers can read the authenticated user's identity from FastMCP's `Context` object. This proves the plumbing works without adding unused production code
3. **`GitHubProvider` scope configuration** — the `required_scopes` parameter (defaulting to `["user"]`) can be extended to `["user", "read:org"]` to enable org membership queries for team resolution

What this spec does NOT do for multi-team: no `Entry.visibility` field, no per-team storage isolation, no query filtering by team scope, no production code that reads auth identity in tool handlers. The smoke test validates the mechanism; the multi-team spec activates it.

### FastMCP `GitHubProvider` integration

The installed FastMCP package provides `GitHubProvider` at `fastmcp.server.auth.providers.github`. It requires three parameters: `client_id`, `client_secret`, `base_url`. It automatically configures GitHub's authorization and token endpoints, supports PKCE, and returns user claims (login, name, email, orgs) via token introspection against GitHub's `/user` API.

Per-request auth context is available to tool handlers through FastMCP's `Context` object (not through the lifespan dict, which is process-scoped). The smoke test in Unit 2 verifies this path.

### Stateless HTTP singleton safety

The `_shared` dict in `server.py` implements process-level singleton state. FastMCP's streamable-HTTP transport uses `uvicorn` which defaults to a single worker. The singleton pattern is safe in this configuration. Multi-worker deployments (e.g. `--workers N`) would require external coordination (MotherDuck handles this at the storage level). This spec does not add multi-worker support.

## Repository Standards

- Conventional Commits: `feat(mcp):`, `feat(config):`, `docs:`, `test(mcp):`
- Scopes: `mcp`, `config`, `cli`
- mypy strict for `src/`, relaxed for `tests/`
- ruff with existing rule set (line length 100, E501 ignored)
- Shared `conftest.py` fixtures for new test modules
- All async tests use `asyncio_mode = "auto"`
- CI matrix: Python 3.11, 3.12, 3.13

## Technical Considerations

- `fastmcp>=2.12.0` must resolve cleanly across the CI matrix. If the version is not yet released on PyPI, pin to the latest available `>=2.x` that includes `GitHubProvider` and adjust the spec
- `GitHubProvider.base_url` must be the publicly accessible URL of the server (not `0.0.0.0`). In HTTP+auth mode, `DISTILLERY_BASE_URL` env var is required
- The `DebugTokenVerifier` from `fastmcp.server.auth` can be used in integration tests to simulate authenticated requests without real GitHub credentials
- HTTP transport integration tests should use `httpx.AsyncClient` against a locally-bound server (ephemeral port) to avoid port conflicts in CI
- MotherDuck token validation in `config.py` should check env var existence at validation time, not at connection time, so operators get immediate feedback on misconfiguration

## Security Considerations

- `GITHUB_CLIENT_SECRET` must never appear in logs, error messages, or config dumps. `build_github_auth()` shall validate this
- Stdio mode requires no credentials — local trust model preserved
- HTTP mode without auth (`provider: none`) is permitted for local testing but should log a warning: "HTTP server running without authentication"
- The `server.auth` YAML section stores env var *names*, not secret values — safe to commit
- OAuth callback URL validation is handled by `GitHubProvider`'s `allowed_client_redirect_uris` — defaults are safe for Claude Code's localhost redirect

## Success Metrics

- All existing tests pass with zero regressions
- `distillery-mcp --transport http` starts and responds to MCP `initialize` within 5 seconds
- All 17 tools accessible over HTTP transport
- GitHub OAuth flow completes for a test client (validated via `DebugTokenVerifier` in CI, manual GitHub OAuth in staging)
- MotherDuck misconfiguration produces actionable error message at startup
- `pytest --cov=src/distillery --cov-fail-under=80` passes
- New team member can connect using only `docs/team-setup.md` (manual validation)

## Future Work

The following items are explicitly deferred to subsequent specs and should be executed in order:

1. **Multi-team access control** (backlog #12, #32) — extends `server.auth` with `allowed_orgs` and `team_mapping`, adds `Entry.visibility` enum (`team`/`private`/`public`), filters queries by team scope. Relies on the auth identity smoke test from this spec
2. **Prefect Horizon deployment** (#27) — `prefect.yaml` manifest, Horizon secret configuration, CI validation of deployment config
3. **Access control on MCP tools** — Horizon provides tool-level RBAC at the gateway; application-level tool restrictions can be added via FastMCP's `restrict_tag()` decorator if needed

## Open Questions

1. **FastMCP version availability** — Is `fastmcp>=2.12.0` released on PyPI with `GitHubProvider`? If not, what is the minimum version that includes it? (To be resolved during task planning)
2. **`base_url` for local development** — When running `--transport http` locally without a public URL, should `base_url` default to `http://localhost:{port}` or require explicit `DISTILLERY_BASE_URL`? (Recommend: default to localhost, require env var only when `server.auth.provider != "none"`)
