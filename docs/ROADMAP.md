<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/distillery-logo-dark-256.png" width="100">
    <source media="(prefers-color-scheme: light)" srcset="assets/distillery-logo-256.png" width="100">
    <img alt="Distillery" src="assets/distillery-logo-256.png" width="100">
  </picture>
</p>

<h1 align="center">Distillery Roadmap</h1>

---

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
- [x] 282 tests passing, mypy strict, ruff clean

### Core Skills (Spec 02)
- [x] `/distill` — session knowledge capture with duplicate detection
- [x] `/recall` — semantic search with provenance display
- [x] `/pour` — multi-pass retrieval + structured synthesis with citations
- [x] `/bookmark` — URL fetch, auto-summarize, store with dedup check
- [x] `/minutes` — meeting notes with `--update` (append) and `--list` modes
- [x] Shared `CONVENTIONS.md` — author/project identification, error handling patterns

### Classification Pipeline (Spec 03)
- [x] `ClassificationEngine` — LLM prompt-based type assignment with confidence scoring
- [x] `DeduplicationChecker` — skip/merge/link/create at configurable thresholds (0.95/0.80/0.60)
- [x] 4 new MCP tools: classify, review_queue, resolve_review, check_dedup (11 total)
- [x] `/classify` skill — classify by ID, batch inbox, review queue triage
- [x] `/distill` updated with full dedup flow via `distillery_check_dedup`
- [x] Config extended with dedup threshold fields and ordering validation

### MVP Maturity (Spec 06)
- [x] Implicit retrieval feedback — `search_log`/`feedback_log` + `distillery_quality` tool
- [x] Stale entry detection — `distillery_stale` tool + `accessed_at` tracking
- [x] Conflict detection — `ConflictChecker` + `distillery_check_conflicts` tool
- [x] Usage metrics dashboard — `distillery_metrics` tool (15 tools total)

### FastMCP Migration (Spec 07)
- [x] Migrated from `mcp` library to FastMCP 2.x with `@server.tool` decorators
- [x] Lazy module-level auto-discovery for `fastmcp run` and FastMCP Cloud

### Infrastructure Improvements (Spec 08)
- [x] Hierarchical tag namespace — slash-separated tags with validation and `distillery_tag_tree` tool
- [x] 4 new entry types — `person`, `project`, `digest`, `github` with strict metadata validation
- [x] `distillery_type_schemas` MCP tool for schema discovery (17 tools total)
- [x] `TagsConfig` — `enforce_namespaces`, `reserved_prefixes` in `distillery.yaml`

### Remaining MVP Items
- [ ] Deploy for single-user validation — use the system end-to-end, validate retrieval quality

---

## Phase 2 — Team Expansion

Scale from single user to team. Six new skills, richer metadata, optional Elasticsearch migration.

### New Skills
- [ ] `/whois` — evidence-backed expertise map ("Who knows about distributed caching?")
- [ ] `/investigate` — deep domain context builder (5-phase workflow)
- [ ] `/digest` — team activity summaries with stale entry detection
- [ ] `/briefing` — team knowledge dashboard
- [ ] `/process` — batch classify + digest + stale detection pipeline
- [ ] `/gh-sync` — GitHub issue/PR knowledge tracking

### Infrastructure
- [x] **HTTP transport** — `distillery-mcp --transport http` for streamable-HTTP MCP server (Spec 10)
- [x] **GitHub OAuth** — team authentication via FastMCP `GitHubProvider` (Spec 10)
- [x] **MotherDuck validation** — strict `md:` prefix and token checks at startup (Spec 10)
- [ ] **Prefect Horizon deployment** — `prefect.yaml` manifest for managed hosting
- [ ] **Elasticsearch migration** — `ElasticsearchStore` backend via `DistilleryStore` protocol
  - Native `semantic_text` for auto-embedding
  - Hybrid search (BM25 + kNN + RRF)
  - ES|QL for temporal queries and aggregations
  - Triggered when DuckDB hits concurrency or scale ceiling (~10K entries)
- [ ] **Access control** — team/private visibility flag on entries (multi-team extension point ready)
- [ ] **Session capture hooks** — auto-distill on Claude Code session end
- [x] **Namespace taxonomy** — hierarchical, validated tag system (`project/billing-v2/decisions`)
- [ ] **Provenance tracking** — full version history, source chain, author chain
- [x] **Port type schemas** — `person` (expertise profiles), `project`, `digest`, `github` entry types

### Quality
- [ ] Classification correction tracking — measure how often human review overrides the classifier
- [ ] Dirty detection — flag entries for re-classification when content is updated
- [ ] Stale entry detection — projects inactive 14+ days
- [ ] Retrieval quality feedback loop — use correction data to tune prompts

---

## Phase 3 — Ambient Intelligence

The knowledge base starts watching the world. Feed polling, relevance scoring, proactive insights.

### New Skills
- [ ] `/radar` — view latest ambient feed digest (what happened that matters to our projects?)
- [ ] `/watch` — add/remove/list monitored feed sources
- [ ] `/tune` — adjust relevance thresholds and source trust weights

### Infrastructure
- [ ] **Feed polling architecture** — scheduler with configurable intervals per source
- [ ] **Source adapters** — RSS, Slack, GitHub, Hacker News, webhooks
- [ ] **Relevance scoring pipeline:**
  1. Embed incoming item
  2. Compare against active project embeddings
  3. Score = similarity x priority x tag overlap x recency x source trust
  4. Above relevance threshold → include in digest
  5. Above alert threshold → immediate notification
- [ ] **Cold-start bootstrapping** — seed relevance scoring without feedback data
- [ ] **Feedback loop** — trust weight adjustment based on user engagement with digest items

### Configuration
```yaml
feeds:
  - name: "Stripe Changelog"
    type: rss
    url: "https://stripe.com/blog/feed.xml"
    poll_interval: "6h"
    trust_weight: 0.9
    tags: ["payments", "billing"]

thresholds:
  relevance: 0.65
  alert: 0.90
  max_digest_items: 20
```

---

## Deferred / Evaluate Later

- [ ] LangGraph evaluation for complex skill orchestration
- [ ] CODE pipeline formalization for team workflows
- [ ] Web UI or REST API (all access currently via MCP + Claude Code)
- [ ] Multi-team support and cross-team knowledge sharing (auth extension point in place)
- [ ] Re-embedding migration tooling (model upgrade path)

---

## Technology Stack

| Layer | Phase 1 | Phase 2 (Current) | Phase 3 |
|-------|---------|-------------------|---------|
| Interface | Claude Code skills | Same | Same |
| Transport | stdio | stdio + streamable-HTTP | Same |
| Auth | None (local trust) | GitHub OAuth (FastMCP) | + multi-team RBAC |
| Storage | DuckDB + VSS | + MotherDuck (shared) / Elasticsearch | Same |
| Embeddings | Jina v3 / OpenAI | ES native or external | Same |
| Language | Python 3.11+ | Same | Same |
| Hosting | Local | + Prefect Horizon | Same |
| Orchestration | Skill invocation | Same | + scheduled polling |
| Config | `distillery.yaml` | + `server.auth` section | + feed config |
