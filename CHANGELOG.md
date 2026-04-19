# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed

- **Scheduling via Claude Code routines** — `/setup` and `/watch` skills now configure Claude Code routines instead of CronCreate jobs or GitHub Actions webhook scheduling. Three routines replace the previous approach: hourly feed poll, daily stale check, weekly maintenance (#272)
- **`distillery_list` default `output_mode` is now `"summary"`** — previously `"full"`, which returned entire entry bodies and flooded agent context (e.g. ~6 KB per gh-sync entry × `limit=50` ≈ 300 KB). Summary mode returns `id`, `title` (derived from metadata or first line of content), `entry_type`, `tags`, `project`, `author`, `created_at`, `metadata`, `session_id`, and a `content_preview` truncated to ~200 chars. Pass `output_mode="full"` explicitly when the whole body is needed (#311).
- **`distillery_store` `dedup_action` semantics tightened** — when a new row is persisted independently, `dedup_action` is now always `"stored"` (previously `"merged"` / `"linked"` when the top match crossed the merge or link threshold, even though a separate row was written). `"merged"` / `"linked"` are reserved for future behaviour where content is actually folded into an existing row or an explicit link is created without a new row. The similarity signal remains available via the informational `existing_entry_id` + `similarity` fields. Callers who want to avoid independent duplicates should call `distillery_find_similar(dedup_action=true)` before storing. (#332)

### Deprecated

- **Webhook scheduling endpoints** — `/hooks/poll`, `/hooks/rescore`, and `/hooks/classify-batch` are deprecated in favour of Claude Code routines. The `/api/maintenance` endpoint is retained for orchestrated operations. Deprecated endpoints log warnings on use. (#272)

---

## [v0.2.1] - 2026-04-07

### Fixes

- **RRF score normalization** — min-max normalization across the full candidate set instead of top-1 division; hybrid search scores now spread meaningfully across [0, 1] (#170, PR #184)
- **Interest profile feed exclusion** — feed entries excluded from `InterestExtractor` to prevent feedback loop where polled content drifts the profile (#175, PR #181)
- **`/pour` curated-first pass** — Pass 1a searches curated entry types (session, bookmark, minutes, etc.) before the broad search, preventing feed volume from drowning out decisions and bookmarks (#175, PR #181)
- **GitHub event type filtering** — `GitHubAdapter` filters low-value events (WatchEvent, ForkEvent, etc.) by default; configurable via `include_event_types` parameter (#171, PR #183)
- **`distillery_list` total_count** — response includes `total_count` (total matching entries before pagination) via new `count_entries()` store method; falls back to `len(entries)` on error (#179, PR #182)
- **Dynamic version tests** — version assertions now compare against `pyproject.toml` and `__version__` instead of hardcoded strings

---

## [v0.2.0] - 2026-04-06

**Theme: Feed Intelligence + Improved Retrieval**

### Hybrid Search (PR #168, #164)

- Hybrid BM25 + vector search with Reciprocal Rank Fusion (RRF) — combines keyword matching with semantic similarity
- DuckDB FTS extension with full-text index on `entries.content` (migration 7)
- Recency decay: configurable time-weighted scoring (`recency_window_days=90`, `recency_min_weight=0.5`)
- Graceful degradation to vector-only if FTS extension unavailable
- New config fields: `hybrid_search`, `rrf_k`, `recency_window_days`, `recency_min_weight` in `defaults` section

### Feed Auto-Tagging (PR #168, #145)

- Source tags derived at ingestion: `source/rss`, `source/github/{owner}/{repo}`, `source/reddit/{subreddit}`, `source/{domain}`
- Topic tags matched from KB vocabulary via keyword map (no LLM/embedding cost)
- `distillery retag` CLI command for backfilling tags on existing feed entries (`--dry-run`, `--force`)
- `get_tag_vocabulary()` added to `DistilleryStore` protocol and `DuckDBStore`
- `_handle_tag_tree` refactored to use `store.get_tag_vocabulary()` instead of direct DB access

### Skill Retrieval Upgrades (PR #172)

- `/radar` Step 3: switched from `distillery_list` (newest-first) to interest-driven `distillery_search` with fallback
- `/pour` Pass 2: tag-based query expansion via `distillery_tag_tree` — discovers related topics from KB vocabulary
- `distillery_tag_tree` added to `/pour` allowed-tools
- `CONVENTIONS.md` Skills Registry updated for new tool usage

### Sprint 1 Foundation (PR #165, #74, #148)

- GitHub token passthrough: `_build_adapter()` forwards `GITHUB_TOKEN` env var to `GitHubAdapter`, enabling private repo polling with transparent redirect following
- Audit log query method: `query_audit_log()` added to `DistilleryStore` protocol and `DuckDBStore` with filtering by user, operation, and date range
- Audit metrics scope: `distillery_metrics(scope="audit")` returns login history, login summary, active users, and recent operations

### Documentation (PR #166, #172)

- uvx recommended as primary first-time setup path across README, docs, and `/setup` skill
- Plugin install + uvx presented as two-step flow (install plugin for skills, switch to uvx for private DB)
- Architecture docs updated: new Search Architecture section, Feed Architecture updated with auto-tagging
- Roadmap updated: hybrid search and auto-tagging moved from Planned to Complete

### Webhook Endpoints (PR #94)

- REST webhook API (`/api/poll`, `/api/rescore`, `/api/maintenance`) with bearer token auth
- Per-endpoint cooldowns persisted in DuckDB, rate limiting, audit logging
- ASGI dispatcher routing `/api/*` to webhooks, all other paths to MCP
- GitHub Actions webhook scheduler integration for `/setup` skill

### Eval Supplement (PR #102)

- promptfoo PR CI gate (`eval-pr.yml`) with 10 smoke-test scenarios
- RAGAS retrieval quality metrics (`retrieval_scorer.py`) with golden dataset
- 13 adversarial/edge-case eval scenarios (malformed input, empty store, boundaries)
- Per-run cost tracking with `--compare-cost` flag and per-skill breakdown

### Promotion Readiness (PR #103)

- README badges (PyPI, License, Python), demo GIF, `.env.example`
- `SECURITY.md` with GitHub Security Advisories disclosure policy

### Plugin Audit (PR #105)

- `allowed-tools` on all 10 skills, `disable-model-invocation` on write skills
- Skill descriptions rewritten from trigger-phrase lists to purpose statements
- `context: fork` on `/pour` and `/radar`, `effort` hints on all skills
- `userConfig` in `plugin.json` with `sensitive: true` for API keys

### MCP Server Refactor (PR #106)

- Split `server.py` (4,041 lines) into 7 domain modules under `mcp/tools/`
- Standardized error codes (`INVALID_PARAMS`, `NOT_FOUND`, `CONFLICT`, `INTERNAL`)
- Extracted validation helpers (`validate_limit`, `validate_required`, `tool_error`)
- Configurable defaults (`defaults.dedup_threshold`, `dedup_limit`, `stale_days`) in `distillery.yaml`
- Full middleware test coverage (rate limiting, body size, org membership)
- Tests for all 22 tool handlers; `mcp/` package at 95%+ coverage

### Skill UX Improvements (PR #115)

- Dedup standardization: `/minutes` and `/radar` now call `distillery_find_similar(dedup_action=true)`
- `--project` filtering on `/classify --inbox`, `/minutes --list`, `/radar`
- Confirmation format template and entry types table in CONVENTIONS.md
- `/radar` defaults to display-only (requires `--store` to persist)
- `distillery_configure` MCP tool for runtime threshold changes (`/tune` no longer requires manual YAML editing)
- Progressive disclosure: `/setup` references extracted to `references/` subdirectory

### Tool Consolidation (PR #118)

- Consolidated 22 MCP tools down to 18 by merging overlapping tools:
  - `distillery_metrics` absorbs `distillery_status` and `distillery_quality` (via `scope` parameter)
  - `distillery_find_similar` absorbs `distillery_check_dedup` and `distillery_check_conflicts` (via `dedup_action` and `conflict_check` parameters)
  - `distillery_list` absorbs `distillery_review_queue` (via `output_mode="review"`)
  - `distillery_interests` absorbs `distillery_suggest_sources` (via `suggest_sources` parameter)
- All skills, eval scenarios, and tests updated to use consolidated tool names
- 18 MCP tools total, 1600+ tests

### Remaining Audit (PRs #120, #121)

- SessionStart hook for review queue notifications
- `distillery-researcher` custom agent for `/pour` and `/radar` workflows
- `X-Request-ID` middleware for HTTP request correlation
- Model hints on `/recall` and `/tune` skills
- Stale tool reference cleanup across skills and cron payloads

### Spec 05 — Developer Experience

- Fixed `distillery` CLI entry point with `status` and `health` subcommands
- Consolidated test fixtures into shared `conftest.py` (`make_entry`, embedding providers)
- Hardened CI: Python 3.11/3.12/3.13 matrix, pip caching, 80% coverage threshold
- Added MCP server E2E test suite
- Cleaned up dependencies: dev tools out of core `dependencies`

### Spec 06 — MVP Maturity

- Implicit retrieval feedback: `search_log`/`feedback_log` tables, automatic positive signal
  on search → get correlation within configurable time window
- `distillery_quality` tool: aggregate search quality metrics (positive feedback rate, per-type breakdown)
- `distillery_stale` tool: surface entries not accessed within configurable days threshold
- `distillery_check_conflicts` tool: detect semantic contradictions on store, non-fatal warnings
- `distillery_metrics` tool: comprehensive usage dashboard (entries, activity, search, quality, staleness, storage)
- `ConflictChecker` class for LLM-based contradiction detection
- Config extensions: `feedback_window_minutes`, `stale_days`, `conflict_threshold`
- 15 MCP tools total (later consolidated to 18)

### Spec 07 — FastMCP Migration

- Migrated from `mcp` library to FastMCP 2.x with `@server.tool` decorators
- Replaced `Server` + manual handler registration with `FastMCP` scaffold and lifespan context
- Updated `__main__.py` to use `server.run_stdio_async()`
- Added lazy module-level `mcp` attribute (PEP 562 `__getattr__`) for FastMCP auto-discovery
- Compatibility shim (`_get_lifespan_context`) supporting both FastMCP 2.x and 3.x

### Spec 08 — Infrastructure Improvements

- Hierarchical tag namespace: slash-separated tags (`project/billing-v2/decisions`) with per-segment
  validation, `tag_prefix` filter in search/list, `distillery_tag_tree` MCP tool
- 4 new entry types: `person`, `project`, `digest`, `github` with `TYPE_METADATA_SCHEMAS` registry
- Strict metadata validation: `validate_metadata()` enforced at store and update time
- `distillery_type_schemas` MCP tool for schema discovery
- `TagsConfig` in `distillery.yaml`: `enforce_namespaces`, `reserved_prefixes`
- DuckDB concurrent initialization retry with `INSERT OR IGNORE` for meta bootstrap
- Updated `/distill` and `/bookmark` skills with hierarchical tag suggestions
- 17 MCP tools total (later consolidated to 18), 600+ tests

### Spec 09 — CLI Eval Runner

- Rewrote eval framework to use Claude Code CLI (`claude -p`) instead of Anthropic Python SDK
- `HashEmbeddingProvider` — deterministic mock embedding provider (`embedding.provider: "mock"`)
- Authenticates via `CLAUDE_CODE_OAUTH_TOKEN` — no `ANTHROPIC_API_KEY` needed
- Stream-json parsing for tool calls, tokens, timing from CLI output
- `seed_file_store()` for pre-seeding eval scenario databases
- Nightly eval workflow with Node.js + Claude CLI in CI

### Spec 10 — Ambient Intelligence (Phase 3)

- `/watch` skill — manage monitored feed sources (add, remove, list)
- `/radar` skill — ambient digest with AI-generated source suggestions via calling Claude instance
- `/tune` skill — display and adjust feed relevance thresholds
- `feeds/` package: `GitHubAdapter` (polls repo events), `RSSAdapter` (parses RSS 2.0 + Atom)
- `RelevanceScorer` — embedding-based relevance scoring (no LLM in background poller)
- `FeedPoller` — iterates sources, scores items, stores above threshold with dedup
- `InterestExtractor` — mines existing entries for tag frequencies, domains, repos, expertise
- 4 new MCP tools: `distillery_watch`, `distillery_poll`, `distillery_interests`, `distillery_suggest_sources`
- `distillery poll` CLI command for cron-based scheduling
- `FeedsConfig` in `distillery.yaml` with sources (each with per-source `trust_weight`) and thresholds
- MotherDuck backend (`md:distillery`) for persistent storage across container restarts
- 21 MCP tools total (later consolidated to 18), 1000+ tests

### Spec 10b — GitHub Team OAuth

- Streamable-HTTP transport: `distillery-mcp --transport http` starts an HTTP MCP server alongside
  the existing stdio mode. CLI flags `--host` / `--port` with `DISTILLERY_HOST` / `DISTILLERY_PORT`
  env var fallbacks
- GitHub OAuth authentication via FastMCP `GitHubProvider`: HTTP mode secured with OAuth 2.1 PKCE
  flow. Stdio mode remains unauthenticated (local trust model)
- `ServerAuthConfig` / `ServerConfig` dataclasses in `config.py` with YAML `server.auth` section
- New `src/distillery/mcp/auth.py` module: `build_github_auth()` reads credentials from env vars,
  never logs secrets, fails fast on missing credentials
- MotherDuck backend validation: `backend=motherduck` requires `md:` prefix on `database_path` and
  `MOTHERDUCK_TOKEN` env var present at startup
- Team setup documentation: `docs/team-setup.md` (member guide), `docs/deployment.md` (operator
  guide), skills audit confirming all 9 skills are transport-agnostic
- Bumped `fastmcp` dependency from `>=2.0.0` to `>=2.12.0`
- Multi-team extension point: smoke test proves tool handlers can read caller identity from
  FastMCP `Context` — no production wiring yet, validated for future access control spec
- 1000+ tests, 80%+ coverage

---

## [v0.1.0] - 2026-03-22

Initial public release of the Distillery MVP, covering three specification areas.

### Spec 01 — Storage Layer & Data Model

- `Entry` data model with UUID, content, embedding, tags, source, topic, category, timestamps,
  and review-queue fields
- `DistilleryStore` protocol defining the full CRUD + search + classification interface
- `DuckDBStore` backend implementing `DistilleryStore` with VSS extension for vector similarity
  search (cosine similarity)
- `EmbeddingProvider` protocol with `OpenAIEmbeddingProvider` and `JinaEmbeddingProvider`
  implementations (rate limiting, retry, task-type support)
- MCP server (`distillery-mcp`) exposing 7 tools over stdio: `distillery_store`,
  `distillery_recall`, `distillery_search_by_tag`, `distillery_get`, `distillery_update`,
  `distillery_delete`, `distillery_health`
- `DistilleryConfig` with YAML-based configuration, environment variable overrides, and
  embedding provider selection

### Spec 02 — Core Skills

- `/distill` skill — capture session knowledge with duplicate detection and tag suggestions
- `/recall` skill — semantic search with provenance and relevance filtering
- `/pour` skill — multi-pass retrieval and structured synthesis with citations
- `/bookmark` skill — store URLs with auto-generated summaries and tag inference
- `/minutes` skill — meeting notes capture with append-update and list modes
- Shared slash-command conventions: output format, error handling, dry-run support

### Spec 03 — Classification Pipeline

- `ClassificationEngine` for automatic topic and category assignment using configurable
  taxonomy
- `DeduplicationChecker` for semantic similarity detection with configurable thresholds
- 4 additional MCP tools (11 total): `distillery_classify`, `distillery_review_queue`,
  `distillery_resolve_review`, `distillery_check_dedup`
- `/classify` skill — classify entries by ID, process full inbox, and manage review queue
- Config extensions: deduplication thresholds, classification taxonomy, review-queue settings

[Unreleased]: https://github.com/norrietaylor/distillery/compare/v0.2.1...HEAD
[v0.2.1]: https://github.com/norrietaylor/distillery/compare/v0.2.0...v0.2.1
[v0.2.0]: https://github.com/norrietaylor/distillery/compare/v0.1.1...v0.2.0
[v0.1.0]: https://github.com/norrietaylor/distillery/releases/tag/v0.1.0
