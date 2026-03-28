# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
- 15 MCP tools total

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
- 17 MCP tools total, 600+ tests

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
- `FeedsConfig` in `distillery.yaml` with sources, thresholds, and trust weights
- MotherDuck backend (`md:distillery`) for persistent storage across container restarts
- 21 MCP tools total, 1000+ tests

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

[Unreleased]: https://github.com/norrietaylor/distillery/compare/v0.1.0...HEAD
[v0.1.0]: https://github.com/norrietaylor/distillery/releases/tag/v0.1.0
