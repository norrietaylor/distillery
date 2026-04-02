# 01-spec-webhook-endpoints

## Introduction/Overview

Distillery needs automated scheduled operations (hourly feed polling, daily rescoring, weekly KB maintenance) but the only current interface is the MCP protocol, which requires OAuth authentication. Claude Code's `RemoteTrigger` API requires a `connector_uuid` that is not discoverable via any API or UI. This spec adds lightweight REST webhook endpoints alongside the existing MCP server, callable by any HTTP scheduler (GitHub Actions cron, external cron services, or `curl` from a RemoteTrigger with Bash). The webhooks share the same uvicorn process and DuckDB store singleton, authenticated via a simple bearer token.

## Goals

1. Expose three POST webhook endpoints (`/api/poll`, `/api/rescore`, `/api/maintenance`) that perform the same operations as their MCP tool counterparts
2. Authenticate webhook requests with a bearer token (`DISTILLERY_WEBHOOK_SECRET`) verified using constant-time comparison
3. Persist per-endpoint cooldown timestamps to DuckDB to prevent runaway scheduling even if the secret leaks
4. Compose the webhook app alongside the existing MCP app in a single Starlette parent app — zero impact on existing MCP/OAuth behavior
5. Provide a GitHub Actions cron workflow that calls these endpoints on schedule

## User Stories

- As a **Distillery operator**, I want feed sources polled automatically every hour so that new content is ingested without manual intervention.
- As a **Distillery operator**, I want feed relevance scores re-evaluated daily so that scores reflect the latest knowledge base state.
- As a **Distillery operator**, I want weekly KB maintenance (metrics, quality, stale detection, interest refresh, source suggestions) to run automatically and store a digest entry for longitudinal tracking.
- As a **Distillery operator**, I want webhook endpoints protected by a bearer token and per-endpoint cooldowns so that accidental or malicious over-triggering cannot overload the system.
- As a **plugin user running /setup**, I want the onboarding wizard to verify webhook health and guide me through GitHub Actions setup instead of the broken RemoteTrigger flow.

## Demoable Units of Work

### Unit 1: Webhook Infrastructure (Config + App Composition + Auth + Cooldowns)

**Purpose:** Establish the webhook app factory, bearer token authentication, DuckDB-persisted cooldowns, and app composition so that the server accepts authenticated POST requests at `/api/*` while the MCP path remains unaffected.

**Functional Requirements:**
- The system shall add a `WebhookConfig` dataclass to `config.py` with fields `enabled: bool = True` and `secret_env: str = "DISTILLERY_WEBHOOK_SECRET"`, wired into `ServerConfig` as `webhooks: WebhookConfig`.
- The system shall parse the `webhooks` section from YAML config in `_parse_server()` and pass defaults when absent.
- The system shall expose the closure-scoped `_shared` dict on the FastMCP server object (e.g., `server._distillery_shared = _shared`) so `__main__.py` can pass it to the webhook app.
- The system shall create a new module `src/distillery/mcp/webhooks.py` with a factory function `create_webhook_app(shared_state: dict, config: DistilleryConfig) -> Starlette`.
- The webhook app shall verify every request's `Authorization: Bearer <token>` header against the value of the env var named by `config.server.webhooks.secret_env`, using `hmac.compare_digest` for constant-time comparison.
- The system shall return `401 Unauthorized` with `{"ok": false, "error": "unauthorized"}` when the bearer token is missing or incorrect.
- The system shall implement per-endpoint cooldown tracking using `store.get_metadata(key)` / `store.set_metadata(key, value)` with ISO 8601 timestamps, keyed as `webhook_cooldown:{endpoint}`.
- The system shall reject requests within the cooldown window with `429 Too Early` and a `Retry-After` header (seconds until cooldown expires), body `{"ok": false, "error": "too_early", "retry_after": <seconds>}`.
- Default cooldown intervals: poll = 300 seconds (5 min), rescore = 3600 seconds (1 hour), maintenance = 21600 seconds (6 hours).
- The system shall implement `_ensure_store(shared_state, config)` to handle the case where a webhook arrives before any MCP client connects, running the same store initialization logic as the MCP lifespan. This is safe because asyncio is single-threaded.
- In `__main__.py`, when `transport == "http"` and `config.server.webhooks.enabled` is `True` and the webhook secret env var is set, the system shall compose a parent Starlette app with `Mount("/api", app=webhook_app)` and `Mount("/", app=wrapped_app)`.
- When webhooks are disabled or no secret is set, the system shall pass `wrapped_app` directly to uvicorn (identical to current behavior).
- The webhook app shall apply `RateLimitMiddleware` from existing middleware with tighter limits (10 requests/minute, 100 requests/hour).

**Proof Artifacts:**
- Test: `pytest tests/test_webhooks.py::test_auth_missing_token` passes — demonstrates 401 on missing auth
- Test: `pytest tests/test_webhooks.py::test_auth_wrong_token` passes — demonstrates 401 on wrong token
- Test: `pytest tests/test_webhooks.py::test_auth_valid_token` passes — demonstrates request accepted with correct token
- Test: `pytest tests/test_webhooks.py::test_cooldown_enforced` passes — demonstrates 429 within cooldown window
- Test: `pytest tests/test_webhooks.py::test_cooldown_persisted` passes — demonstrates cooldown survives store reinit
- Test: `pytest tests/test_webhooks.py::test_app_composition` passes — demonstrates MCP and webhook apps both mounted
- Test: `pytest tests/test_webhooks.py::test_webhooks_disabled` passes — demonstrates no `/api` routes when disabled
- CLI: `mypy --strict src/distillery/config.py src/distillery/mcp/webhooks.py` returns no errors

### Unit 2: Webhook Handlers (Poll + Rescore + Maintenance)

**Purpose:** Implement the three POST endpoint handlers that perform the actual operations, reusing existing `FeedPoller` and store query logic. The maintenance endpoint stores a digest entry for longitudinal tracking.

**Functional Requirements:**
- `POST /api/poll` shall instantiate `FeedPoller` using the shared store, config, and embedding provider, call `poller.poll()`, and return `{"ok": true, "data": {"sources_polled": N, "items_fetched": N, "items_stored": N, "errors": [...]}}`.
- `POST /api/rescore` shall accept an optional JSON body `{"limit": N}` (default 200), call `poller.rescore(limit=N)`, and return `{"ok": true, "data": {"rescored": N, "upgraded": N, "downgraded": N}}`.
- `POST /api/maintenance` shall sequentially execute: metrics (7-day period), quality check, stale detection (30 days, limit 10), interests (30 days, top 10), and source suggestions (max 3).
- The maintenance endpoint shall compose a one-paragraph digest summary from the results and store it as an entry with `entry_type="session"`, `author="distillery-maintenance"`, `tags=["system/digest", "system/weekly", "system/maintenance"]`, and metadata containing `period_start` and `period_end` ISO dates.
- The maintenance endpoint shall return `{"ok": true, "data": {"metrics": {...}, "quality": {...}, "stale_count": N, "top_interests": [...], "suggested_sources": [...], "digest_entry_id": "..."}}`.
- All endpoints shall return `{"ok": false, "error": "<message>"}` with appropriate HTTP status codes (500 for internal errors, 400 for bad request body).
- All endpoints shall update the cooldown timestamp in DuckDB after successful execution (not on error).
- All endpoint handlers shall log operation start/completion at INFO level.

**Proof Artifacts:**
- Test: `pytest tests/test_webhooks.py::test_poll_handler` passes — demonstrates poll returns expected shape with mocked poller
- Test: `pytest tests/test_webhooks.py::test_rescore_handler` passes — demonstrates rescore with custom limit
- Test: `pytest tests/test_webhooks.py::test_maintenance_handler` passes — demonstrates all 5 operations run and digest stored
- Test: `pytest tests/test_webhooks.py::test_maintenance_stores_digest` passes — demonstrates digest entry created with correct tags/metadata
- Test: `pytest tests/test_webhooks.py::test_handler_error_returns_500` passes — demonstrates error response format
- CLI: `mypy --strict src/distillery/mcp/webhooks.py` returns no errors

### Unit 3: Deployment + Scheduling + Setup Skill Update

**Purpose:** Wire up the Fly.io deploy config, create the GitHub Actions cron workflow, and update the `/setup` skill to use webhook health checks instead of the broken RemoteTrigger flow.

**Functional Requirements:**
- The system shall add a `webhooks` section to `deploy/fly/distillery-fly.yaml` under `server:` with `enabled: true` and `secret_env: DISTILLERY_WEBHOOK_SECRET`.
- The system shall create `.github/workflows/scheduler.yml` with three cron triggers: hourly poll (`23 * * * *`), daily rescore (`17 6 * * *`), and weekly maintenance (`41 7 * * 1`).
- The workflow shall support `workflow_dispatch` for manual runs with an `operation` input (choices: poll, rescore, maintenance, all).
- Each cron job shall execute a single `curl -sf -X POST -H "Authorization: Bearer $SECRET" $URL/api/<endpoint>` using `secrets.DISTILLERY_WEBHOOK_SECRET` and `vars.DISTILLERY_URL`.
- The workflow shall use `timeout-minutes: 5` per job to prevent hung requests.
- The workflow shall report the JSON response body in the job summary.
- The `/setup` skill (`.claude-plugin/skills/setup/SKILL.md`) shall remove Step 4 (MCP Connector Registration) entirely — hosted/team scheduling is handled by the GitHub Actions workflow, not by the setup wizard.
- The `/setup` skill Step 5 (Scheduled Tasks) shall only configure `CronCreate` jobs for **local transport**. For hosted/team transport, Step 5 shall display a note that scheduling is handled by GitHub Actions and skip cron creation.
- The `/setup` skill shall remove all `RemoteTrigger` references — the connector UUID problem is sidestepped entirely.

**Proof Artifacts:**
- File: `deploy/fly/distillery-fly.yaml` contains `webhooks:` section with `enabled: true`
- File: `.github/workflows/scheduler.yml` contains three cron expressions and `workflow_dispatch`
- File: `.claude-plugin/skills/setup/SKILL.md` contains no `RemoteTrigger` references, skips cron setup for hosted/team transport, and only creates `CronCreate` jobs for local transport
- CLI: `ruff check src/ tests/` returns no errors
- CLI: `ruff format --check src/ tests/` returns no errors

## Non-Goals (Out of Scope)

- Modifying the existing MCP protocol path (`/mcp`), OAuth flow, or middleware stack
- Adding webhook support to stdio transport mode
- Changing the health check endpoint or DuckDB storage layer
- Adding new MCP tools — webhooks are a parallel interface, not a replacement
- Implementing async/background job execution (webhooks are synchronous)
- Adding webhook endpoint for arbitrary MCP tool invocation (only poll, rescore, maintenance)
- Dashboard or UI for viewing webhook execution history

## Design Considerations

No specific design requirements identified. This is a server-side backend feature with no UI components.

## Repository Standards

- **Python 3.11+** required
- **mypy --strict** on `src/` — all new code must pass strict type checking
- **ruff** line length 100, rules: E, W, F, I, N, UP, B, C4, SIM (E501 ignored)
- **pytest-asyncio** in auto mode
- **Test markers**: `@pytest.mark.unit`, `@pytest.mark.integration`
- **Commit format**: Conventional Commits — `type(scope): description`
  - Relevant scopes: `mcp`, `config`, `skills`, `feeds`
- **Dataclass conventions**: Follow existing pattern in `config.py` — `@dataclass`, `field(default_factory=...)` for mutable defaults, full docstrings with Attributes section
- **Existing patterns**: `Protocol`-based interfaces, async store operations, `_parse_*` functions in config

## Technical Considerations

- **App composition**: Starlette `Mount` routes are prefix-matched. `/api` mount must come before `/` catch-all to ensure webhook routes take priority.
- **Store initialization race**: The `_ensure_store()` function must replicate the MCP lifespan's store init logic. Since asyncio is single-threaded, there's no real race — the function just needs to check `_shared` and init if empty.
- **Shared state**: The `_shared` dict is a closure variable in `create_server()`. Attaching it to the server object (`server._distillery_shared`) is the minimal-impact way to expose it to `__main__.py`. This is an internal implementation detail, not a public API.
- **Cooldown persistence**: Uses the existing `get_metadata`/`set_metadata` store protocol methods with keys like `webhook_cooldown:poll`. Values are ISO 8601 timestamps. This survives server restarts since DuckDB is persisted on Fly volumes.
- **Rate limiting**: The existing `RateLimitMiddleware` is reused with tighter limits for the webhook app. This provides IP-based rate limiting on top of the bearer token auth and per-endpoint cooldowns.
- **FeedPoller instantiation**: Webhooks instantiate `FeedPoller` the same way the MCP tool handlers do — using the shared store, config, and embedding provider from `_shared`.

## Security Considerations

- **Bearer token auth**: The webhook secret is stored as a Fly.io secret and GitHub Actions secret. It is never logged or included in responses.
- **Constant-time comparison**: `hmac.compare_digest` prevents timing attacks on the token.
- **Secret redaction**: The existing `SecretRedactFilter` on the distillery logger prevents accidental secret leakage in logs.
- **Cooldown defense**: Per-endpoint cooldowns limit damage if the secret leaks — an attacker can trigger each operation at most once per cooldown period.
- **No data exfiltration path**: Webhook responses contain aggregate counts and IDs, not entry content. The maintenance digest is stored in the KB, not returned in full.
- **Transport security**: Fly.io terminates TLS — all webhook traffic is encrypted in transit.

## Success Metrics

- All three webhook endpoints respond correctly to authenticated requests in tests
- Cooldown enforcement prevents duplicate operations within the minimum interval
- GitHub Actions cron workflow executes successfully on schedule
- `mypy --strict` passes on all new code
- Test coverage for `webhooks.py` >= 90%
- `/setup` skill correctly guides users through webhook-based scheduling (manual verification)

## Open Questions

No open questions at this time. All design decisions have been resolved through the clarifying questions.
