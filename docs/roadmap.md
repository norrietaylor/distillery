# Roadmap

## Phase 1 — MVP (Complete)

The foundation: storage layer, 6 core skills, classification pipeline.

### Storage Layer & Data Model (Spec 01)
- [x] `Entry` data model with structured metadata and type-specific extensions
- [x] `DistilleryStore` protocol — async storage abstraction enabling backend migration
- [x] DuckDB backend with VSS extension and HNSW index (cosine similarity)
- [x] Configurable embedding providers (Jina v3 default, OpenAI adapter)
- [x] Embedding model lock via `_meta` table — prevents mixed-model corruption
- [x] MCP server with 7 core tools (store, get, update, search, find_similar, list, status)
- [x] `distillery.yaml` config system with validation

### Core Skills (Spec 02)
- [x] `/distill` — session knowledge capture with duplicate detection
- [x] `/recall` — semantic search with provenance display
- [x] `/pour` — multi-pass retrieval + structured synthesis with citations
- [x] `/bookmark` — URL fetch, auto-summarize, store with dedup check
- [x] `/minutes` — meeting notes with `--update` (append) and `--list` modes
- [x] Shared `CONVENTIONS.md` — author/project identification, error handling patterns

### Classification Pipeline (Spec 03)
- [x] `ClassificationEngine` — LLM prompt-based type assignment with confidence scoring
- [x] `DeduplicationChecker` — skip/merge/link/create at configurable thresholds
- [x] 4 new MCP tools: classify, review_queue, resolve_review, check_dedup
- [x] `/classify` skill — classify by ID, batch inbox, review queue triage

### MVP Maturity (Spec 06)
- [x] Implicit retrieval feedback + `distillery_quality` tool
- [x] Stale entry detection — `distillery_stale` tool
- [x] Conflict detection — `distillery_check_conflicts` tool
- [x] Usage metrics dashboard — `distillery_metrics` tool

### FastMCP Migration (Spec 07)
- [x] Migrated from `mcp` library to FastMCP 2.x with `@server.tool` decorators

### Infrastructure Improvements (Spec 08)
- [x] Hierarchical tag namespace with validation and `distillery_tag_tree` tool
- [x] 4 new entry types — `person`, `project`, `digest`, `github`
- [x] `distillery_type_schemas` MCP tool for schema discovery

---

## Phase 2 — Team Expansion

Scale from single user to team. Six new skills, richer metadata, optional Elasticsearch migration.

### New Skills (Planned)
- [ ] `/whois` — evidence-backed expertise map
- [ ] `/investigate` — deep domain context builder
- [ ] `/digest` — team activity summaries
- [ ] `/briefing` — team knowledge dashboard
- [ ] `/process` — batch classify + digest + stale detection pipeline
- [ ] `/gh-sync` — GitHub issue/PR knowledge tracking

### Infrastructure
- [x] HTTP transport — `distillery-mcp --transport http`
- [x] GitHub OAuth — team authentication via FastMCP `GitHubProvider`
- [x] Prefect Horizon deployment
- [x] Fly.io deployment with persistent DuckDB on volume
- [ ] Elasticsearch migration — hybrid search (BM25 + kNN + RRF)
- [ ] Access control — team/private visibility flag
- [x] Namespace taxonomy — hierarchical, validated tag system

---

## Phase 3 — Ambient Intelligence (Complete)

The knowledge base watches the world. Feed polling, relevance scoring, proactive insights.

### Skills
- [x] `/radar` — ambient feed digest with AI source suggestions
- [x] `/watch` — add/remove/list monitored feed sources
- [x] `/tune` — adjust relevance thresholds and trust weights

### Infrastructure
- [x] Feed polling architecture — `FeedPoller` with configurable intervals
- [x] Source adapters — GitHub events (REST API) and RSS/Atom
- [x] Relevance scoring pipeline — embedding-based cosine similarity
- [x] Interest extractor — mines entries for tags, domains, repos, expertise
- [x] 5 new MCP tools: watch, poll, interests, suggest_sources, rescore

### Onboarding
- [x] `/setup` skill — MCP connectivity wizard, auto-poll configuration

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
| Storage | DuckDB + VSS / MotherDuck | + Elasticsearch |
| Embeddings | Jina v3 / OpenAI | + ES native |
| Language | Python 3.11+ | Same |
| Hosting | Local / Fly.io / Prefect Horizon | Same |
