# 16-spec-api-consolidation

## Introduction/Overview

Distillery v0.3 exposes 20 MCP tools, several of which overlap in functionality (e.g., `stale`, `aggregate`, `tag_tree`, `metrics` are all filtered views of entry data). This spec consolidates the MCP tool surface from 20 to 12 by absorbing 6 analytics tools into `list` parameter extensions, moving `poll` and `rescore` to webhook-only endpoints, adding a new `classify-batch` webhook, and rewiring the existing `/api/maintenance` orchestrator. The result is a smaller, more composable API that reduces cognitive load for skill authors and LLM tool-use while preserving all existing functionality.

## Goals

1. **Reduce MCP tool count from 20 to 12** by absorbing redundant analytics tools into `list` and moving poll/rescore to webhooks
2. **Extend `list` with 3 new parameters** (`stale_days`, `group_by`, `output`) that replace 4 standalone tools
3. **Add `classify-batch` webhook** with configurable LLM and heuristic classification modes
4. **Maintain backward compatibility** — all functionality currently exposed by removed tools remains accessible through the consolidated API
5. **Rewire `/api/maintenance`** to orchestrate the new webhook surface (poll → rescore → classify-batch)

## User Stories

- As a **skill author**, I want fewer MCP tools with composable parameters so that I can build skills without memorizing 20 tool signatures
- As an **LLM agent**, I want a smaller tool surface so that tool selection is faster and less error-prone
- As an **operator**, I want a single maintenance endpoint that runs all periodic tasks so that I only need one cron entry
- As a **self-hosted user**, I want heuristic classification so that I can classify inbox entries without LLM inference costs

## Demoable Units of Work

### Unit 1: Extend `list` Tool — `stale_days`, `group_by`, `output` Parameters

**Purpose:** Absorb functionality of `stale`, `aggregate`, `tag_tree`, and `metrics` tools into the existing `list` tool via three new optional parameters. This is the foundation — all other units depend on the extended `list` being available.

**Functional Requirements:**

- The system shall add a `stale_days` parameter (int, optional) to the `list` tool that filters to entries not accessed in N+ days, using `COALESCE(accessed_at, updated_at)` as the access timestamp
- The system shall add a `group_by` parameter (str, optional, one of: `entry_type`, `status`, `author`, `project`, `source`, `tags`) that switches the return format from an entry list to `{groups: [{value: str, count: int}], total_entries: int, total_groups: int}`
- The system shall support `group_by="tags"` combined with `tag_prefix` to replicate `tag_tree` functionality (hierarchical tag browsing)
- The system shall add an `output` parameter (str, optional, value: `"stats"`) that returns `{entries_by_type: dict, entries_by_status: dict, total_entries: int, storage_bytes: int}` — replicating `metrics` tool output
- The system shall validate that `group_by` and `output="stats"` are mutually exclusive (return validation error if both provided)
- The system shall validate that `stale_days` is composable with all existing filters (`entry_type`, `author`, `project`, `tags`, `status`, etc.)
- The system shall return results ordered by `created_at` descending in default mode, and by `count` descending in `group_by` mode

**Proof Artifacts:**

- Test: `tests/test_mcp_tools/test_list_extensions.py` passes — covers `stale_days` filtering, all `group_by` variants, `output="stats"`, mutual exclusivity validation, and composition with existing filters
- CLI: `list(stale_days=30)` returns entries not accessed in 30+ days
- CLI: `list(group_by="entry_type")` returns `{groups: [{value: "session", count: 12}, ...]}` format
- CLI: `list(group_by="tags", tag_prefix="topic/")` returns tag counts under the `topic/` namespace
- CLI: `list(output="stats")` returns entry counts by type/status and storage size

---

### Unit 2: Remove Absorbed Tools and Move Poll/Rescore to Webhooks

**Purpose:** Delete the 8 MCP tool registrations that are now redundant, completing the 20→12 reduction. Move poll and rescore logic to webhook-only handlers.

**Functional Requirements:**

- The system shall remove MCP tool registrations for: `distillery_stale`, `distillery_aggregate`, `distillery_tag_tree`, `distillery_metrics`, `distillery_interests`, `distillery_type_schemas`, `distillery_poll`, `distillery_rescore`
- The system shall serve entry type schemas as an MCP resource (`distillery://schemas/entry-types`) instead of a tool, loaded on client connect
- The system shall inline the `interests` computation (interest profile from KB) into the poll webhook pipeline rather than exposing it as a standalone tool
- The system shall move poll handler logic from the MCP tool to `POST /hooks/poll` webhook endpoint, accepting an optional `source_url` query parameter
- The system shall move rescore handler logic from the MCP tool to `POST /hooks/rescore` webhook endpoint, accepting an optional `limit` query parameter
- The system shall ensure all existing tests for removed tools are either migrated to test the equivalent `list` parameter or the webhook endpoint, or deleted with justification
- The system shall return a clear error message if a client attempts to call a removed tool name (FastMCP handles this automatically via tool registration)

**Proof Artifacts:**

- Test: `pytest tests/test_mcp_tools/` passes — no test references removed tool names except as negative cases
- CLI: MCP server `list_tools()` returns exactly 12 tools
- CLI: `POST /hooks/poll` returns poll results with per-source breakdown
- CLI: `POST /hooks/rescore?limit=50` returns rescore statistics
- File: `src/distillery/mcp/server.py` — no registration calls for the 8 removed tools

---

### Unit 3: Add `classify-batch` Webhook with Heuristic Mode

**Purpose:** Add a new webhook endpoint for batch classification of inbox entries, with both LLM and heuristic classification modes. Extend the existing partial heuristic classifier to production readiness.

**Functional Requirements:**

- The system shall expose `POST /hooks/classify-batch` accepting optional query parameters `entry_type` (default: `"inbox"`) and `mode` (default: from config `classification.mode`)
- The system shall return `{classified: int, pending_review: int, errors: int, by_type: {assigned_type: count}}`
- The system shall support `mode=llm` using the existing `ClassificationEngine` with server-side Haiku calls, where confidence >= threshold sets `status=active` and confidence < threshold sets `status=pending_review`
- The system shall support `mode=heuristic` using embedding-only classification that maps entry embeddings to nearest entry-type cluster centroids via cosine similarity
- The system shall build cluster centroids by averaging embeddings of existing entries grouped by `entry_type` (minimum 3 entries per type to form a centroid)
- The system shall fall back to `pending_review` status for heuristic mode when no centroid has similarity >= 0.5
- The system shall make classification mode configurable via `configure(section="classification", key="mode", value="llm"|"heuristic"`)
- The system shall authenticate the webhook endpoint with bearer token in hosted mode (consistent with existing `/hooks/poll` and `/hooks/rescore`)
- The system shall add `distillery maintenance classify [--type inbox] [--mode llm|heuristic]` CLI command that calls the webhook

**Proof Artifacts:**

- Test: `tests/test_webhooks/test_classify_batch.py` passes — covers LLM mode, heuristic mode, empty inbox, auth, and error handling
- Test: `tests/test_classification/test_heuristic.py` passes — covers centroid computation, similarity thresholds, fallback behavior, and insufficient-data edge cases
- CLI: `POST /hooks/classify-batch?mode=heuristic` returns classification results with zero LLM inference
- CLI: `distillery maintenance classify --mode heuristic` triggers classification via CLI

---

### Unit 4: Rewire Maintenance Orchestrator and Update Skills

**Purpose:** Rewire `/api/maintenance` to call the new webhook surface, and update all skills that referenced removed tools to use the consolidated API.

**Functional Requirements:**

- The system shall rewrite the `/api/maintenance` webhook handler to sequentially call: poll → rescore → classify-batch (replacing the current metrics + quality + stale + interests pipeline)
- The system shall return a combined response from `/api/maintenance` with sections for each sub-operation's results
- The system shall update the `/briefing` skill to use `list(stale_days=N)` instead of calling the `stale` tool
- The system shall update the `/briefing` skill to use `list(group_by="status")` and `list(group_by="entry_type")` instead of calling `aggregate`
- The system shall update the `/pour` skill to use `list(group_by="tags")` instead of calling `tag_tree`
- The system shall update the `/investigate` skill to use `list(group_by="tags")` instead of calling `tag_tree`
- The system shall update the `/digest` skill to use `list(output="stats")` instead of calling `metrics`
- The system shall update the `/radar` skill to remove any reference to the `interests` tool (interest profile is now internal to poll pipeline)
- The system shall update the `/setup` skill to generate webhook URLs for `/hooks/poll`, `/hooks/rescore`, and `/hooks/classify-batch`
- The system shall update all skill SKILL.md frontmatter `tools:` lists to reflect the 12-tool surface

**Proof Artifacts:**

- Test: `tests/test_webhooks/test_maintenance.py` passes — verifies orchestrator calls poll → rescore → classify-batch in sequence
- CLI: `POST /api/maintenance` returns combined results from all three sub-operations
- File: All `skills/*/SKILL.md` files reference only the 12 active tools in their `tools:` frontmatter
- Test: `pytest tests/` passes — full test suite green with no references to removed tool names in skill logic

## Non-Goals (Out of Scope)

- **New skill creation** — no new skills are added; existing skills are rewired
- **Database schema changes** — the `list` extensions use existing columns (`accessed_at`, `updated_at`, `entry_type`, `status`, etc.)
- **Authentication changes** — webhook auth uses the existing bearer token mechanism
- **`watch --sync-history` flag** — mentioned in the API spec but is a separate feature (bulk historical ingest)
- **`store_batch()` for bulk insert** — referenced in poll pipeline for sync-history; deferred with that feature
- **MCP resource implementation details** — `distillery://schemas/entry-types` is defined but the resource serving mechanism depends on FastMCP version; implementation details are left to the developer
- **Embedding provider changes** — no changes to Jina/OpenAI embedding backends

## Design Considerations

No UI components. All changes are to the MCP tool API, webhook endpoints, CLI, and skill definitions. Tool parameter naming follows existing conventions (`snake_case`, consistent with current `list` parameters).

## Repository Standards

- **Python 3.11+**, **mypy --strict** on `src/`
- **ruff** line length 100, rules: E, W, F, I, N, UP, B, C4, SIM
- **pytest-asyncio** auto mode with `@pytest.mark.unit` / `@pytest.mark.integration` markers
- **Conventional Commits**: `refactor(mcp): ...`, `feat(mcp): ...`, `feat(classification): ...`
- **Protocol-based design**: storage and embedding use `Protocol` interfaces, not ABCs
- Tests use fixtures from `tests/conftest.py`: `make_entry()`, `mock_embedding_provider`, `store`

## Technical Considerations

- **`list` SQL generation**: The `stale_days` filter adds a `WHERE COALESCE(accessed_at, updated_at) < NOW() - INTERVAL N DAYS` clause to the existing query builder in the DuckDB store. `group_by` switches the query to `SELECT {field}, COUNT(*) ... GROUP BY {field}`. `output="stats"` runs a separate aggregate query plus `PRAGMA database_size`.
- **Mutual exclusivity**: `group_by` and `output="stats"` cannot be combined — the tool must validate this and return a clear error before executing any query.
- **Heuristic classifier centroids**: Computed on-demand per classify-batch call (not cached). For a typical KB of <10k entries, this is fast enough. Caching can be added later if profiling shows need.
- **MCP resource serving**: FastMCP 2.x supports `@server.resource()` decorator. The `type_schemas` data is static and can be served as a JSON resource.
- **Webhook handler reuse**: The poll and rescore handlers already exist as internal functions called by MCP tools. Refactor to extract the handler logic, then register it as both a webhook route and (previously) an MCP tool — then remove the MCP registration.
- **Maintenance orchestrator**: Uses internal function calls, not HTTP self-calls. Each sub-operation returns its result dict; the orchestrator merges them.

## Security Considerations

- **Webhook authentication**: `/hooks/classify-batch` must use the same bearer token auth as existing webhooks. The `classify-batch` endpoint processes entries that may contain sensitive content — ensure no content leaks in error responses.
- **Heuristic mode**: No external API calls (no LLM, embeddings already stored). Reduces attack surface compared to LLM mode.
- **Configure tool**: The new `classification.mode` config key uses the existing whitelist validation in `configure`. No new config keys are exposed beyond what's defined.

## Success Metrics

- MCP tool count drops from 20 to exactly 12
- All existing tests pass after migration (zero regression)
- Full test suite maintains ≥80% coverage
- Heuristic classification achieves ≥70% accuracy on a sample of pre-classified entries (measured via test fixture)
- No skill references removed tool names

## Open Questions

No open questions at this time.
