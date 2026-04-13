# Roadmap

## Complete

### Storage & Data Model
- [x] `Entry` data model with structured metadata and type-specific extensions
- [x] `DistilleryStore` protocol — async storage abstraction enabling backend migration
- [x] DuckDB backend with VSS extension and HNSW index (cosine similarity)
- [x] Configurable embedding providers (Jina v3 default, OpenAI adapter)
- [x] Embedding model lock via `_meta` table — prevents mixed-model corruption
- [x] MCP server with 18 tools over stdio and streamable-HTTP
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
- [x] Implicit retrieval feedback + quality metrics (now via `distillery_metrics(scope="search_quality")`)
- [x] Stale entry detection — `distillery_stale` tool
- [x] Conflict detection (now via `distillery_find_similar(conflict_check=true)`)
- [x] Usage metrics dashboard — `distillery_metrics` tool

### Infrastructure
- [x] FastMCP 2.x/3.x with `@server.tool` decorators
- [x] Hierarchical tag namespace with validation and `distillery_tag_tree` tool
- [x] 12 entry types including `person`, `project`, `digest`, `github`, `feed`
- [x] `distillery_type_schemas` MCP tool for schema discovery

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
- [x] `distillery_relations` tool for managing entry links

### New Entry Fields
- [x] `expires_at` — time-limited entries with UTC normalization
- [x] `verification` — orthogonal quality tracking (Unverified, Testing, Verified)
- [x] `session_id` — first-class field for session-scoped entries
- [x] Extended `EntrySource` — added inference, documentation, external provenance values

### Session Hooks
- [x] Hook dispatcher script (`distillery-hooks.sh`) — routes UserPromptSubmit, SessionStart, PreCompact
- [x] Memory nudge — periodic reminder to `/distill` every 30 prompts
- [x] SessionStart briefing — automatic context injection via HTTP MCP
- [x] Scope-aware `/setup` hook configuration — detects plugin install scope (user/project)

### Onboarding
- [x] `/setup` skill — MCP connectivity wizard, auto-poll configuration, session hook setup
- [x] uvx-first setup — `uvx distillery-mcp` as recommended first-time path

---

## Planned

### P0 — API Hardening

Work targets `staging/api-hardening` branch. Sequenced — foundation fixes unblock bulk ingest.

**Phase A: Foundation fixes**

- [ ] Re-land API consolidation (20→12 tools) and conflict prompt leak fix onto `staging/api-hardening` from `main`
- [ ] [#232](https://github.com/norrietaylor/distillery/issues/232) — `distillery_store` tool description enum omits `github` entry type
- [ ] [#238](https://github.com/norrietaylor/distillery/issues/238) — Add `output_mode: "summary"` to skip dedup/conflict checks
- [ ] [#241](https://github.com/norrietaylor/distillery/issues/241) — label→tag sanitiser fails on underscored labels
- [ ] [#240](https://github.com/norrietaylor/distillery/issues/240) — `/gh-sync` passes invalid `output_mode="metadata"`

**Phase B: API surface + infrastructure**

- [ ] [#245](https://github.com/norrietaylor/distillery/issues/245) — Harden MCP interface: tool descriptions, error codes, validation, docs
- [ ] [#244](https://github.com/norrietaylor/distillery/issues/244) — Bulk ingest pipeline (`store_batch`, `watch --sync-history`, gh-sync elimination)
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
| Embeddings | Jina v3 / OpenAI | Same |
| Language | Python 3.11+ | Same |
| Hosting | Local / Fly.io / Prefect Horizon | Same |
