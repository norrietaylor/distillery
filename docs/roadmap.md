# Roadmap

## Complete

### Storage & Data Model
- [x] `Entry` data model with structured metadata and type-specific extensions
- [x] `DistilleryStore` protocol — async storage abstraction enabling backend migration
- [x] DuckDB backend with VSS extension and HNSW index (cosine similarity)
- [x] Configurable embedding providers (fastembed default for the plugin install path, Jina v3 / OpenAI adapters)
- [x] Embedding model lock via `_meta` table — prevents mixed-model corruption
- [x] MCP server with 16 tools over stdio and streamable-HTTP (consolidated from 20 in `staging/api-hardening`)
- [x] `distillery.yaml` config system with validation

### Core Skills
- [x] `/distill` — session knowledge capture with duplicate detection
- [x] `/recall` — semantic search with provenance display
- [x] `/pour` — multi-pass retrieval + structured synthesis with citations
- [x] `/bookmark` — URL fetch, auto-summarize, store with dedup check
- [x] `/minutes` — meeting notes with `--update` (append) and `--list` modes
- [x] Shared `CONVENTIONS.md` — author/project identification, error handling patterns

### Classification Pipeline
- [x] `ClassificationEngine` — LLM prompt-based type assignment with confidence scoring
- [x] `DeduplicationChecker` — skip/merge/link/create at configurable thresholds
- [x] `/classify` skill — classify by ID, batch inbox, review queue triage

### Quality & Observability
- [x] Implicit retrieval feedback + quality metrics (folded into `distillery_status`)
- [x] Stale entry detection — `distillery_list(stale_days=…)` (formerly the `distillery_stale` tool)
- [x] Conflict detection — `distillery_find_similar(conflict_check=true)`
- [x] Usage metrics dashboard — `distillery_status` tool (replaces former `distillery_metrics`)

### Infrastructure
- [x] FastMCP 2.x/3.x with `@server.tool` decorators
- [x] Hierarchical tag namespace with validation; tag inventory via `distillery_list(group_by="tag")` (formerly `distillery_tag_tree`)
- [x] 12 entry types including `person`, `project`, `digest`, `github`, `feed`
- [x] Entry-type schema discovery via MCP resource `distillery://schemas/entry-types` (replaces `distillery_type_schemas`)

### Team Access
- [x] HTTP transport — `distillery-mcp --transport http`
- [x] GitHub OAuth — team authentication via FastMCP `GitHubProvider`
- [x] Prefect Horizon deployment (MotherDuck)
- [x] Fly.io deployment with persistent DuckDB on volume
- [x] Namespace taxonomy — hierarchical, validated tag system

### Ambient Intelligence
- [x] `/radar` — interest-driven feed digest with AI source suggestions
- [x] `/watch` — add/remove/list monitored feed sources
- [x] `/tune` — adjust relevance thresholds and trust weights
- [x] `/compass` — contrast internal knowledge against ambient intelligence; emit a directional assessment (ahead / exposed / decide / confirm)
- [x] Feed polling architecture — `FeedPoller` with configurable intervals
- [x] Source adapters — GitHub events (REST API) and RSS/Atom
- [x] Relevance scoring pipeline — embedding-based cosine similarity
- [x] Interest extractor — mines entries for tags, domains, repos, expertise
- [x] Auto-tagging — source tags (`source/github/owner/repo`, `source/reddit/sub`) and topic tags from KB vocabulary
- [x] `distillery retag` CLI — backfill tags on existing feed entries

### Search
- [x] Hybrid BM25 + vector search — DuckDB FTS extension with Reciprocal Rank Fusion (RRF)
- [x] Recency decay — configurable time-weighted scoring (90-day window, 0.5 min weight)
- [x] Graceful degradation — falls back to vector-only if FTS extension unavailable

### Team Skills
- [x] `/digest` — team activity summaries over configurable time windows
- [x] `/gh-sync` — sync GitHub issues/PRs into the knowledge base as searchable entries
- [x] `/investigate` — deep context builder with 4-phase retrieval and relationship traversal
- [x] `/briefing` — knowledge dashboard with solo mode (5 sections) and team mode (8 sections)

### Entry Relations & Corrections
- [x] `entry_relations` table with backfill migration
- [x] `distillery_correct` tool for structured corrections
- [x] `distillery_relations` tool for managing entry links, graph traversal, and structural metrics (bridges, communities, constraint, link prediction, orphans)

### New Entry Fields
- [x] `expires_at` — time-limited entries with UTC normalization
- [x] `verification` — orthogonal quality tracking (Unverified, Testing, Verified)
- [x] `session_id` — first-class field for session-scoped entries
- [x] Extended `EntrySource` — added inference, documentation, external provenance values

### Session Hooks
- [x] Hook dispatcher script (`distillery-hooks.sh`) — routes SessionStart
- [x] SessionStart briefing — automatic context injection via HTTP MCP
- [x] Scope-aware `/setup` hook configuration — detects plugin install scope (user/project)

### Onboarding
- [x] `/setup` skill — MCP connectivity wizard, auto-poll configuration, session hook setup
- [x] uvx-first setup — `uvx --from 'distillery-mcp[fastembed]>=0.6.0' distillery-mcp` as recommended first-time path (zero API key required)

### API Hardening (`staging/api-hardening` → released)
- [x] API consolidation: 20 → 16 tools. Removed `distillery_aggregate`, `distillery_stale`, `distillery_tag_tree`, `distillery_metrics`, `distillery_interests`, `distillery_type_schemas`, `distillery_poll`, `distillery_rescore`. Functionality folded into `distillery_list`, `distillery_status`, `distillery_configure`, REST `/api/maintenance`, and the `distillery://schemas/entry-types` resource.
- [x] [#244](https://github.com/norrietaylor/distillery/issues/244) — Bulk ingest pipeline: new `distillery_store_batch` tool; `/gh-sync` runs as a server-side background job tracked by `distillery_sync_status`
- [x] [#245](https://github.com/norrietaylor/distillery/issues/245) — Hardened MCP interface: tool descriptions, structured error codes, schema validation, INVALID_PARAMS suggestions
- [x] [#232](https://github.com/norrietaylor/distillery/issues/232) — `distillery_store` enum includes `github`
- [x] [#238](https://github.com/norrietaylor/distillery/issues/238) — `distillery_store` accepts `output_mode="summary"` to skip dedup/conflict checks
- [x] [#241](https://github.com/norrietaylor/distillery/issues/241) — label→tag sanitiser handles underscored labels
- [x] [#240](https://github.com/norrietaylor/distillery/issues/240) — `/gh-sync` passes valid `output_mode`
- [x] [#317](https://github.com/norrietaylor/distillery/issues/317) — `distillery_list` / `distillery_search` exclude archived entries by default
- [x] [#311](https://github.com/norrietaylor/distillery/issues/311) — `distillery_list` default `output_mode="summary"`
- [x] [#346](https://github.com/norrietaylor/distillery/issues/346), [#347](https://github.com/norrietaylor/distillery/issues/347), [#349](https://github.com/norrietaylor/distillery/issues/349) — DuckDB WAL recovery and FTS replay hardening
- [x] [#351](https://github.com/norrietaylor/distillery/issues/351) — Embedding budget default raised to unlimited; provider 429s surface to caller

---

## Planned

### P0 — Follow-up

- [ ] [#112](https://github.com/norrietaylor/distillery/issues/112) — Security Review Follow-Up

### P0 — Quality & Bugfixing

PRs go directly to `main`.

- [ ] [#230](https://github.com/norrietaylor/distillery/issues/230) — DuckDB WAL corruption on unclean shutdown
- [ ] [#236](https://github.com/norrietaylor/distillery/issues/236) — RateLimitMiddleware defaults starve local-client bursts
- [ ] [#221](https://github.com/norrietaylor/distillery/issues/221) — FeedPoller poll cycle exceeds 5 minutes
- [ ] [#169](https://github.com/norrietaylor/distillery/issues/169) — `distillery retag` produces no output
- [ ] [#235](https://github.com/norrietaylor/distillery/issues/235) — Plugin auto-registers hosted demo MCP

### P0 — Memory Benchmarking

- [ ] [#233](https://github.com/norrietaylor/distillery/issues/233) — LongMemEval retrieval benchmark

### P1 — Near-term Features

- [ ] [#199](https://github.com/norrietaylor/distillery/issues/199) — `distillery_extract` for PreCompact summarisation
- [ ] [#237](https://github.com/norrietaylor/distillery/issues/237) — Retrieval-hygiene conventions docs
- [ ] [#212](https://github.com/norrietaylor/distillery/issues/212) — Slim down container image
- [ ] [#163](https://github.com/norrietaylor/distillery/issues/163) — Relevance-sorted feed queries for /radar
- [ ] [#152](https://github.com/norrietaylor/distillery/issues/152) — `/whois` skill
- [ ] [#151](https://github.com/norrietaylor/distillery/issues/151) — `/process` skill
- [ ] [#149](https://github.com/norrietaylor/distillery/issues/149) — Access control (visibility flag)

---

## Deferred

- [ ] [#147](https://github.com/norrietaylor/distillery/issues/147), [#142](https://github.com/norrietaylor/distillery/issues/142), [#141](https://github.com/norrietaylor/distillery/issues/141), [#140](https://github.com/norrietaylor/distillery/issues/140), [#138](https://github.com/norrietaylor/distillery/issues/138), [#158](https://github.com/norrietaylor/distillery/issues/158) — Graph analysis arc (NetworkX, hidden connections, epiphany generation)
- [ ] [#167](https://github.com/norrietaylor/distillery/issues/167) — Slack conversation adapter
- [ ] [#101](https://github.com/norrietaylor/distillery/issues/101) — Browser extension
- [ ] [#93](https://github.com/norrietaylor/distillery/issues/93) — Public knowledge spaces for OSS projects
- [ ] [#81](https://github.com/norrietaylor/distillery/issues/81) — Tauri desktop frontend
- [ ] LangGraph evaluation for complex skill orchestration
- [ ] Multi-team support and cross-team knowledge sharing
- [ ] Re-embedding migration tooling

---

## Technology Stack

| Layer | Current | Planned |
|-------|---------|---------|
| Interface | Claude Code skills | Same |
| Transport | stdio + streamable-HTTP | Same |
| Auth | GitHub OAuth (FastMCP) | + multi-team RBAC |
| Storage | DuckDB + VSS + FTS / MotherDuck | Same |
| Search | Hybrid BM25 + vector (RRF) | + score normalization |
| Embeddings | fastembed (default for plugin) / Jina v3 / OpenAI | Same |
| Language | Python 3.11+ | Same |
| Hosting | Local / Fly.io / Prefect Horizon | Same |
