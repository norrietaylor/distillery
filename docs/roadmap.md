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

### Onboarding
- [x] `/setup` skill — MCP connectivity wizard, auto-poll configuration
- [x] uvx-first setup — `uvx distillery-mcp` as recommended first-time path

---

## Planned

### New Skills
- [ ] `/whois` — evidence-backed expertise map
- [ ] `/investigate` — deep domain context builder
- [ ] `/digest` — team activity summaries
- [ ] `/briefing` — team knowledge dashboard
- [ ] `/process` — batch classify + digest + stale detection pipeline
- [ ] `/gh-sync` — GitHub issue/PR knowledge tracking

### Infrastructure
- [ ] RRF score normalization — hybrid search scores cluster near 1.0 (#170)
- [ ] GitHub event content filtering — skip low-value WatchEvent/ForkEvent (#171)
- [ ] Access control — team/private visibility flag (#149)

---

## Deferred

- [ ] LangGraph evaluation for complex skill orchestration
- [ ] CODE pipeline formalization for team workflows
- [ ] Web UI or REST API
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
