# Distillery Backlog

Prioritized work items derived from [ROADMAP.md](ROADMAP.md) and spec research. Items are grouped by phase and ordered by priority within each group.

**Completed specs:** 01 (storage/data model), 02 (core skills), 03 (classification), 04 (public release), 05 (developer experience), 06 (MVP maturity), 07 (FastMCP migration), 08 (infrastructure improvements), 09 (CLI eval runner), 10 (ambient intelligence).

**Current state:** 21 MCP tools, 9 skills, FastMCP 2.x/3.x, Python 3.11-3.13 CI matrix, 80% coverage threshold, 1000+ tests.

---

## Phase 1 — MVP Remaining

| # | Item | Description | Status |
|---|------|-------------|--------|
| 1 | Single-user validation | Deploy and use the system end-to-end, validate retrieval quality using `distillery_quality` metrics | In progress |
| 2 | Retrieval quality baseline | Implicit feedback tracking via `search_log`/`feedback_log`, `distillery_quality` tool | Done (spec 06) |
| 3 | Content lifecycle policy | Stale entry detection via `distillery_stale` tool + `accessed_at` tracking. Auto-archival deferred | Done (spec 06) |
| 4 | Conflict detection | `ConflictChecker` + `distillery_check_conflicts` tool, warnings in `distillery_store` | Done (spec 06) |

---

## Phase 2 — Team Expansion

### Skills

| # | Item | Description | Status |
|---|------|-------------|--------|
| 5 | `/whois` | Evidence-backed expertise map ("Who knows about distributed caching?") | Not started |
| 6 | `/investigate` | Deep domain context builder (5-phase workflow) | Not started |
| 7 | `/digest` | Team activity summaries with stale entry detection | Not started |
| 8 | `/briefing` | Team knowledge dashboard | Not started |
| 9 | `/process` | Batch classify + digest + stale detection pipeline | Not started |
| 10 | `/gh-sync` | GitHub issue/PR knowledge tracking | Not started |

### Infrastructure

| # | Item | Description | Status |
|---|------|-------------|--------|
| 11 | Elasticsearch migration | `ElasticsearchStore` backend — hybrid search (BM25 + kNN + RRF), ES\|QL for temporal queries. Triggered when DuckDB hits ~10K entries | Not started |
| 12 | Access control | Team/private visibility flag on entries | Not started |
| 13 | Session capture hooks | Auto-distill on Claude Code session end | Not started |
| 14 | Namespace taxonomy | Hierarchical validated tag system (`project/billing-v2/decisions`) | Done (spec 08) |
| 15 | Provenance tracking | Full version history, source chain, author chain | Not started |
| 16 | Port type schemas | `person`, `project`, `digest`, `GitHub` entry types | Done (spec 08) |

### Quality

| # | Item | Description | Status |
|---|------|-------------|--------|
| 17 | Classification correction tracking | Measure how often human review overrides the classifier | Not started |
| 18 | Dirty detection | Flag entries for re-classification when content is updated | Not started |
| 19 | Stale entry detection | Surfacing via `distillery_stale` tool done (spec 06). Auto-archival policy remaining | Done (spec 06) |
| 20 | Retrieval quality feedback loop | Implicit feedback infrastructure done (spec 06). Prompt tuning from feedback data remaining | Partial (spec 06) |

---

## Phase 3 — Ambient Intelligence

### Skills

| # | Item | Description | Status |
|---|------|-------------|--------|
| 21 | `/radar` | Ambient feed digest with AI source suggestions | Done (spec 10) |
| 22 | `/watch` | Add/remove/list monitored feed sources | Done (spec 10) |
| 23 | `/tune` | Adjust relevance thresholds and source trust weights | Done (spec 10) |

### Infrastructure

| # | Item | Description | Status |
|---|------|-------------|--------|
| 24 | Feed polling architecture | `FeedPoller` + `distillery poll` CLI + `distillery_poll` MCP tool | Done (spec 10) |
| 25 | Source adapters | GitHub events + RSS/Atom done. Slack, Hacker News, webhooks remaining | Partial (spec 10) |
| 26 | Relevance scoring pipeline | Embedding-based cosine similarity scorer + interest extractor | Done (spec 10) |
| 27 | Cold-start bootstrapping | Seed relevance scoring without feedback data | Not started |
| 28 | Feedback loop | Trust weight adjustment based on user engagement with digest items | Not started |

---

## Deferred / Evaluate Later

| # | Item | Description |
|---|------|-------------|
| 29 | LangGraph evaluation | Evaluate for complex skill orchestration |
| 30 | CODE pipeline formalization | Formalize for team workflows |
| 31 | Web UI / REST API | All access currently via MCP + Claude Code |
| 32 | Multi-team support | Cross-team knowledge sharing |
| 33 | Re-embedding migration tooling | Model upgrade path |