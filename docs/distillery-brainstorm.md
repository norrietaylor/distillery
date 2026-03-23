# Project Distillery — Brainstorm Log

**Date:** 2026-03-20

## Concept

A team-accessible "Second Brain" inspired by Tiago Forte's Building a Second Brain (BASB) methodology.

**Key differences from traditional BASB:**
- Data stored in a hosted vector database (not Obsidian)
- Shared knowledge base accessible to an entire team
- Core methodology retained: CODE (Capture, Organize, Distill, Express) and PARA (Projects, Areas, Resources, Archives)

## Name Selection

### Candidates Considered

| Name | Angle | Notes |
|---|---|---|
| Hivemind | Team/collective | Simple, memorable |
| Cortex | Brain metaphor | Implies shared cognition |
| Synapse | Connection | Link between people/neurons |
| Nucleus | Core | Team orbits around it |
| CODEC | CODE + Collective | Also encoder/decoder |
| Paralex | PARA + lexicon | Knowledge lattice |
| Engram | Neuroscience | Memory trace — maps to embeddings |
| Recall | Function | What brains and the system do |
| Stoa | Philosophy | Place for thought |
| **Distillery** | **Methodology (Distill)** | **Selected** |

### Why Distillery

- Maps to the "Distill" step in CODE — the highest-value step (noise → signal)
- Metaphor: refining raw information into concentrated knowledge
- Vector DB angle: embeddings are a distillation of meaning into dense vectors
- Team angle: a distillery is a *place* people go to get the good stuff

## Namespace Availability

### GitHub
- `distillery/distillery` — not taken
- Top existing result: `bitwalker/distillery` (2,961★) — Elixir deployment tool, no conflict

### npm
- `distillery` — taken but dormant (v0.1.1, 2 versions)
- `distill` — taken but dormant (v0.0.3, 3 versions)

### Domains (checked 2026-03-20)

| Domain | Status |
|---|---|
| distillery.dev | Taken |
| distillery.ai | Taken (parked, no DNS) |
| distillery.io | Taken |
| distillery.app | Possibly available |
| **distillery.team** | **Possibly available — best fit** |
| distillery.co | Taken |
| thedistillery.dev | Possibly available |
| thedistillery.ai | Taken |

### Recommended domains to register
1. **distillery.team** — reinforces collaborative nature
2. **distillery.app** — clean, modern
3. **thedistillery.dev** — developer-oriented

## Agentic Interface

### Claude Code Integration

Distillery is accessed through an agentic interface — not a traditional GUI. Users interact with the knowledge base via **Claude Code skills** (slash commands).

### Core Interactions

| Skill | Action | Example |
|---|---|---|
| `/distill` | Store content into the knowledge base | `/distill "summary of auth refactor decisions"` |
| `/recall` | Query the knowledge base semantically | `/recall "what do we know about rate limiting?"` |
| `/pour` | Retrieve and synthesize across multiple entries | `/pour "all context on the billing migration"` |
| `/bookmark` | Store a URL with summary and tags | `/bookmark https://... --tags "auth,oauth" --summary "RFC for token rotation"` |
| `/minutes` | Store or update team meeting summaries | `/minutes "standup 2026-03-20" --update "added action items"` |

### What Gets Stored

Distillery captures knowledge artifacts from Claude Code workflows:

- **Session summaries** — end-of-session distillations of what was discussed, decided, and built
- **Session context** — full or partial conversation context from work/cowork sessions
- **Code context** — architectural decisions, implementation rationale, debugging insights
- **Cowork artifacts** — pair programming session outcomes, design discussions, trade-off analyses
- **Team knowledge** — onboarding context, runbooks, tribal knowledge that lives in people's heads
- **Resource bookmarks** — URLs with AI-generated or manual summaries, tagged for retrieval
- **Meeting minutes** — team meeting summaries, updatable over time (append action items, outcomes, follow-ups)

### Storage Model

Each entry is stored as a vector embedding with structured metadata:

```
{
  "content": "...",           // the distilled knowledge
  "source": "claude-code",   // origin system
  "entry_type": "session|bookmark|minutes|manual",
  "session_type": "work | cowork | null",
  "author": "norrie",        // who created it
  "project": "billing-v2",   // project context
  "tags": ["architecture", "decisions"],
  "timestamp": "2026-03-20T...",
  "session_id": "...",        // link back to full session if stored
  "url": "...",              // for bookmarks
  "meeting_id": "...",       // for minutes, enables updates
  "version": 1              // for mutable entries (minutes), tracks revisions
}
```

### Flow

```
Claude Code Session
       │
       ▼
   /distill ──→ Embed + Store ──→ Vector DB
                                      │
   /recall  ──→ Semantic Search ──────┘
       │
       ▼
  Synthesized Answer (with sources)
```

### Design Principles

- **Capture should be frictionless** — one command at end of session, or automatic via hooks
- **Retrieval is conversational** — ask questions in natural language, get synthesized answers with provenance
- **Team-first** — all entries are visible to the team by default; private entries are the exception
- **Progressive distillation** — raw session context can be stored, then refined into summaries over time (mirrors Forte's progressive summarization)
- **Ambient intelligence** — the system actively watches the team's information landscape and surfaces what matters

## Ambient Feed Intelligence

Distillery doesn't just store what humans push into it — it actively monitors external sources, filters for relevance to active team projects, and produces curated digests.

### Concept

A background process polls configured feeds and channels on a schedule, scores each item against the team's active project embeddings in the vector DB, and surfaces high-relevance items as a digest. The team gets a "the world moved and here's what matters to you" briefing without anyone having to manually curate it.

### Sources

| Source Type | Examples | Polling Method |
|---|---|---|
| RSS/Atom feeds | Engineering blogs, release notes, CVE feeds, HN, industry newsletters | Standard RSS fetch |
| Slack channels | `#engineering`, `#incidents`, `#random-interesting`, vendor channels | Slack MCP / API — search or history |
| GitHub | Watched repos (releases, issues, discussions), dependency updates | GitHub API / `gh` CLI |
| Hacker News / Reddit | Subreddits, HN front page, specific search terms | API / RSS |
| Vendor/product feeds | Cloud provider status, dependency changelogs, SDK releases | RSS or webhook |
| ArXiv / research | Specific categories or keyword searches | ArXiv API / RSS |
| Custom webhooks | Internal tools, CI/CD events, observability alerts | Ingest API endpoint |

### Relevance Scoring

Each polled item is scored against the team's knowledge base:

```
For each new item:
  1. Embed the item (title + summary/content)
  2. Query vector DB for active projects + recent references
  3. Compute cosine similarity against each project embedding
  4. Score = max(similarities) weighted by:
     - Project priority (high/medium/low)
     - Tag overlap (exact tag matches boost score)
     - Recency of project activity
     - Source trust weight (configurable per feed)
  5. If score > relevance_threshold → include in digest
  6. If score > alert_threshold → notify immediately
```

### Two-Tier Output

**1. Periodic Digest (`/radar`)**
Scheduled (daily or weekly), summarizes all high-relevance items grouped by project:

```markdown
# Team Radar — 2026-03-20

## billing-v2 (3 items)
- **Stripe SDK v12 released** — Breaking changes to PaymentIntent API
  Source: Stripe changelog | Relevance: 0.91
- **HN Discussion: "Idempotency in payment systems"** — 340 points
  Source: Hacker News | Relevance: 0.78
- **Slack #payments: outage post-mortem from Acme Corp**
  Source: #payments channel | Relevance: 0.74

## auth-rewrite (2 items)
- **CVE-2026-1234: JWT library vulnerability**
  Source: NVD feed | Relevance: 0.95 ⚠️
- **Blog: "OAuth 2.1 simplified" by Aaron Parecki**
  Source: RSS | Relevance: 0.82

## Low relevance (skipped): 47 items
```

**2. Real-time Alerts**
Items above `alert_threshold` (e.g., CVEs affecting dependencies, breaking changes in used SDKs) get pushed immediately via Slack/webhook.

### Feed Configuration

```yaml
feeds:
  - name: "Stripe Changelog"
    type: rss
    url: "https://stripe.com/blog/feed.xml"
    poll_interval: "6h"
    trust_weight: 0.9
    tags: ["payments", "billing"]

  - name: "#engineering Slack"
    type: slack_channel
    channel: "#engineering"
    poll_interval: "1h"
    trust_weight: 0.7

  - name: "GitHub Releases — Dependencies"
    type: github_releases
    repos: ["elastic/elasticsearch", "vercel/next.js"]
    poll_interval: "12h"
    trust_weight: 0.95

  - name: "Hacker News"
    type: hackernews
    min_score: 100
    poll_interval: "3h"
    trust_weight: 0.5

thresholds:
  relevance: 0.65       # minimum to include in digest
  alert: 0.90           # immediate notification
  max_digest_items: 20  # cap per digest
```

### Skill Integration

| Skill | Role |
|---|---|
| `/radar` | View the latest ambient digest on demand |
| `/watch` | Add/remove/list feed sources |
| `/tune` | Adjust relevance thresholds, trust weights |
| `/digest` | Now includes ambient items alongside team activity |

### Feedback Loop

When a team member marks a digest item as useful (👍) or irrelevant (👎), the system adjusts:
- Source trust weights (consistently irrelevant source → lower weight)
- Project-tag associations (refines what "relevant to project X" means)
- Personal relevance profiles (optional — individual interests within team context)

This creates a flywheel: the more the team uses Distillery, the better it gets at filtering signal from noise.

## Lineage: Porting from Personal Second Brain

Distillery inherits architecture and methodology from an existing personal second brain system built on Obsidian + Claude Code. This section maps what ports, what adapts, and what gets dropped.

### Source System Overview

The personal system uses:
- **Obsidian vault** as storage (markdown files in `04 Data/YYYY/MM/`)
- **Obsidian Bases** as query/view layer (`.base` files with frontmatter-driven database views)
- **Claude Code skills** for automation (classify, people-expertise-map, get-context-on-domain)
- **Slash commands** for workflows (`/today`, `/eod`, `/meeting`, `/learned`, `/gh-import`)
- **Type dispatch system** — every note has a `type` frontmatter field that dispatches to a schema file
- **Classification pipeline** — AI classifies raw captures with confidence scores; low-confidence items routed to human review
- **Progressive summarization** — daily → weekly → monthly digests

### High-Value — Direct Port

#### 1. Classification Pipeline

The confidence-scored auto-classification with human review loop is the core intelligence layer.

**Personal system:** Raw text → classify skill → assign type + confidence → create note → log classification. Below threshold (0.6) → `status: needs_review` for human triage.

**Distillery port:**
- Same pipeline, vector DB as target instead of markdown files
- Team review queue instead of personal review — any team member can resolve
- Classification contract preserved:
  ```
  INPUT: Raw content
  OUTPUT: entry_type, confidence, metadata, reasoning
  RULES: confidence < threshold → pending_review
  ```
- Reclassification as additive migration (never lose data, only add fields)

#### 2. Type System

Most types port directly with team-scoping additions.

| Personal Type | Distillery Type | Changes |
|---|---|---|
| `reference` | **reference** | Direct port — the core use case |
| `meeting` | **meeting** | Add `team`, `visibility` fields |
| `person` | **person** | Becomes team-shared expertise profiles |
| `project` | **project** | Add `owner`, `team` fields |
| `task` | **task** | Add `assignee`; or defer to external trackers |
| `idea` | **idea** | Direct port — team ideation |
| `inbox` | **inbox** | Unprocessed queue pattern works for team captures |
| `digest` | **digest** | Team-level activity digests |
| `github` | **github** | Shared GitHub issue/PR tracking |
| `admin` | Merge into `reference` | Low standalone value for team KB |
| `dailynote` | Drop | Personal artifact, doesn't scale to team |

#### 3. People-Expertise Map

**More valuable at team scale.** The "who knows about X?" / "what does @person do?" queries are exactly what teams need.

**Personal system:** Multi-source ping-pong discovery — Slack → GitHub → vault → cross-reference → score → rank.

**Distillery port:**
- Same discovery methodology as a `/whois` skill
- Store resulting profiles as `person` entries in vector DB
- Team members can query and update each other's profiles
- Evidence-backed expertise scoring (PRs authored, reviews done, Slack answers)

#### 4. Get-Context-on-Domain

**Personal system:** Iterative cross-referencing — code → people → Slack → GitHub → decisions. Five phases: Initial Discovery → Identify Key Actors → Timeline Reconstruction → Architecture Evolution → Iterative Deep Dives.

**Distillery port:**
- `/investigate <domain>` skill with same phased workflow
- Stores resulting domain context report as a `reference` entry
- Next person who asks gets cached report + incremental updates
- Completeness checklist preserved (original authors, key PRs, architecture phases, decision rationale)

#### 5. Digest Generation

**Personal system:** Progressive summarization — daily digests (< 150 words + classification log), weekly (< 250 words + analysis + reflection prompts), monthly (< 400 words + trends).

**Distillery port:**
- Team-level digests: what was captured, decided, discussed
- Stale entry detection (projects inactive 14+ days, overdue tasks)
- Trend analysis (captures/week, type distribution, correction rate)
- Reflection prompts adapted for team retrospectives

### Medium-Value — Adapt

#### 6. Session Capture (`/learned` → `/distill`)

**Personal system:** End-of-session context capture to external inbox.

**Distillery:** Core write path. Adapt by adding `author`, `session_id`, `team` metadata. Auto-extract decisions, action items, architectural insights. Team visibility by default.

#### 7. Morning/Evening Rhythms (`/today` + `/eod` → `/briefing` + `/process`)

**Personal system:** `/today` = morning briefing + daily note + GitHub sync. `/eod` = inbox processing + dirty detection + digest generation.

**Distillery:** The personal rhythm doesn't port, but the operations inside do:
- Inbox processing (classify unprocessed items) → triggered or scheduled skill
- GitHub sync → `/gh-sync` for team-tracked issues
- Dirty detection (modified > classified_at) → re-embed stale entries
- Digest generation → team cron

#### 8. Confidence Threshold + Review Queue

**Personal system:** Configurable threshold (0.6) in `config.yaml`. Below threshold → `needs_review` → appears in Bases view.

**Distillery:** Same pattern. Team review queue where any member can resolve. Threshold configurable per team. Correction analysis feeds threshold tuning.

### Drop — Not Portable

| Component | Reason |
|---|---|
| Obsidian CLI skill | Storage-layer specific — replaced by vector DB API |
| Obsidian Bases skill | View layer — replaced by semantic search |
| File naming conventions (`YYYY.MM.DD-kebab.md`) | No files — vector entries have IDs |
| Wiki-links (`[[note\|display]]`) | Replace with entry ID references |
| Git conventions (`sb:` prefix commits) | No git — vector DB has own versioning |
| Daily notes | Personal workflow artifact |
| Templater integration | Obsidian-specific |
| `sb-ingest` drop folder | Replace with API endpoint / webhook |
| SIGPIPE workarounds, CLI gotchas | Obsidian-specific |

### Architecture Translation

```
Personal (Obsidian)              →  Team (Distillery)
─────────────────────────────────────────────────────
04 Data/YYYY/MM/*.md             →  Vector DB entries
02 Areas/*.base (queries)        →  Semantic search + metadata filters
05 Meta/claude/<type>.claude.md  →  Entry type schemas (same pattern)
05 Meta/config.yaml              →  Team config (thresholds, settings)
05 Meta/logs/inbox-log.md        →  Classification audit log (DB table)
05 Meta/context/tags.md          →  Team tag taxonomy (config)
Obsidian CLI                     →  Vector DB SDK / API client
Wiki-links [[note|display]]      →  Entry ID references
Frontmatter fields               →  Structured metadata on vectors
confidence + classified_at       →  Same — on every entry
~/second-brain-inbox/            →  Ingest API / webhook endpoint
```

### Proposed Skill Set

Full skill inventory ported and adapted from the personal system:

| Skill | Origin | Purpose |
|---|---|---|
| `/distill` | `/learned` | Store session context with team metadata |
| `/classify` | classify skill | Same pipeline, team review queue |
| `/recall` | obsidian search | Semantic vector search |
| `/pour` | manual cross-referencing | Multi-entry synthesis |
| `/bookmark` | new | URL + summary storage |
| `/minutes` | `/meeting` | Team meeting notes, updatable |
| `/whois` | people-expertise-map | "Who knows about X?" with evidence |
| `/investigate` | get-context-on-domain | Deep domain context builder |
| `/digest` | `/generate-digests` | Team activity summaries |
| `/briefing` | `/today` | Team knowledge dashboard |
| `/process` | `/eod` | Batch classify + digest + stale detection |
| `/gh-sync` | `/gh-import` + GitHub sync | Team GitHub issue/PR tracking |
| `/radar` | new (ambient intelligence) | View latest ambient feed digest |
| `/watch` | new (ambient intelligence) | Add/remove/list monitored feed sources |
| `/tune` | new (ambient intelligence) | Adjust relevance thresholds and trust weights |

### Key Design Decisions to Make

1. **Implicit vs explicit classification** — Personal system classifies everything. Should Distillery auto-classify, or let authors choose type on capture?
2. **Entry mutability** — Personal system uses append-only for GitHub notes and digests. Vector entries are harder to "append to." Versioning strategy needed.
3. **Cross-references** — Personal system uses wiki-links. Distillery needs an equivalent for linking related entries (entry IDs? tags? both?).
4. **Privacy model** — Personal system is single-user. Distillery needs: public (team), private (individual), restricted (subgroup)?
5. **Source of truth** — Personal system is the source of truth for meeting notes, tasks, etc. Distillery should be a *knowledge layer*, not a task tracker. Avoid duplicating Jira/Linear/GitHub.

## Comparison: Elastic Brain

`elastic/elastic_brain` is an internal Elastic research project for building a self-learning knowledge base from Elastic Stack assets (dashboards, pipelines, configs, docs). It was compared against Distillery on 2026-03-20 to identify shared principles, divergences, and ideas to adapt.

### What Elastic Brain Is

A **knowledge extraction pipeline** that uses LLMs to distill structured, reusable knowledge items from raw Elastic ecosystem content. It does NOT store raw documents — it extracts understanding and discards the source. Built with LangGraph agents, Elasticsearch as both vector store and metadata store, and Redis/RQ for async job processing.

**Key architecture:**
- **Learner Agent** (LangGraph) orchestrates two sub-agents: Extractor (analyzes content) and Creator (dedup + store)
- **Retriever Agent** answers questions by searching the knowledge base semantically
- **Elasticsearch** with `semantic_text` field type for native embedding + ANN search
- **Redis/RQ** queue for async batch processing
- **CLI-driven** batch ingestion (`generate`, `ask`, `namespace`, `export`)
- **FastAPI** backend + React frontend for browsing/querying
- Uses Claude Sonnet 4.5 (via Bedrock) for extraction, Claude Haiku 4.5 for orchestration

### Shared Principles

| Principle | Elastic Brain | Distillery |
|---|---|---|
| **Knowledge distillation over document storage** | Core philosophy — extract understanding, discard raw source | Same — progressive distillation from raw sessions to refined knowledge |
| **Type system** | ~31 knowledge types (`visualization_pattern`, `processor_pattern`, `security_use_case`, etc.) | Type dispatch system with schemas per type |
| **Classification pipeline** | Two-phase: extractor identifies knowledge, creator classifies + deduplicates | Confidence-scored classification with human review loop |
| **Semantic deduplication** | Creator searches existing entries before creating; score thresholds decide skip/create/update | Not yet designed — should adopt this |
| **Structured metadata** | Namespace, tags, relationships, provenance on every entry | Structured metadata on every vector entry |
| **Specialized prompts per content type** | Different extraction prompts for dashboards vs pipelines vs docs | Type schemas dispatch different processing rules |

### What Distillery Should Adopt from Elastic Brain

#### 1. Semantic Deduplication (Critical)

Elastic Brain's creator sub-agent searches for existing knowledge before storing anything. Score thresholds:
- **20+** = duplicate → skip or merge
- **10-15** = related → enhance existing entry
- **< 10** = novel → create new

Distillery MUST have this. Without it, repeated `/distill` calls about the same topic will pollute the knowledge base. Add a dedup step to the classification pipeline:

```
On /distill:
  1. Embed new content
  2. Search existing entries (semantic)
  3. If high similarity → offer to merge/update instead of create
  4. If moderate similarity → link as related
  5. If low similarity → create new entry
```

#### 2. Two-Phase Extraction (Extractor + Creator)

The separation of "what knowledge exists in this content" (Extractor) from "how to store it without duplicates" (Creator) is clean. Distillery's `/distill` should similarly separate:
- **Phase 1:** Extract — what decisions, insights, patterns are in this session?
- **Phase 2:** Store — do any of these already exist? Create, update, or link?

#### 3. Namespace/Taxonomy System

Elastic Brain uses a YAML-defined hierarchical namespace schema with validation rules. Paths like `/integration/aws/cloudwatch/visualization_patterns`. This is more rigorous than Distillery's flat tag system.

**Adapt as:** A lightweight hierarchical taxonomy for Distillery entries:
```
/project/billing-v2/decisions
/project/auth-rewrite/architecture
/team/onboarding/runbooks
/domain/payments/expertise
/external/stripe/changelog
```

Not as deep as Elastic Brain's schema (they have 31 types × products × integrations), but the principle of validated, hierarchical organization is sound.

#### 4. Elasticsearch as Vector Store

Elastic Brain uses Elasticsearch's native `semantic_text` field — no external vector DB needed. Elasticsearch handles embedding generation and ANN search internally.

**Relevance to Distillery:** If the team is already an Elasticsearch shop, this eliminates the "choose a vector DB" decision entirely. Worth serious consideration vs Pinecone/Weaviate/Qdrant. Tradeoffs:
- **Pro:** Single infrastructure dependency, native hybrid search (BM25 + semantic), battle-tested at scale
- **Pro:** No external embedding API calls — ES handles it
- **Con:** Heavier operational footprint than a managed vector DB
- **Con:** Semantic text is relatively new in ES

#### 5. Provenance Tracking

Every Elastic Brain entry tracks: `created_at`, `updated_at`, `update_count`, `version`, `source_hash`. This audit trail is important for team trust — "where did this knowledge come from?"

Distillery should track:
- Original source (session ID, URL, meeting, feed item)
- Author chain (who created, who updated)
- Confidence at creation + any reclassification history
- Version history for mutable entries (minutes, profiles)

#### 6. Processing State Tracking

Elastic Brain tracks every file's processing state (`in-progress`, `finished`, `error`) with file hashes for incremental processing. This prevents reprocessing unchanged content.

Distillery needs this for:
- Feed polling (don't re-process items already seen)
- Session ingestion (don't re-distill the same session)
- Bulk imports (resume interrupted batch jobs)

### Where Distillery Diverges (and Should)

| Dimension | Elastic Brain | Distillery | Why Diverge |
|---|---|---|---|
| **Interface** | CLI + REST API + React SPA | Claude Code skills (agentic, conversational) | Distillery is agent-native; the LLM IS the interface |
| **Ingestion model** | Batch CLI runs, queue-based | Real-time capture + ambient polling + manual | Teams need frictionless capture, not batch jobs |
| **Human in the loop** | None — fully automated extraction | Confidence threshold + team review queue | Team knowledge needs human validation |
| **Content sources** | Elastic ecosystem only (repos, docs) | Anything — sessions, meetings, feeds, URLs, Slack | General-purpose team brain vs product-specific KB |
| **Collaboration model** | Shared state via ES, but single-user extraction | Multi-author, team-visible, with attribution | Team-first design from the start |
| **Mutability** | Entries are updatable (merge/enhance) | Entries need versioning (minutes evolve, profiles grow) | Team content changes over time; need history |
| **Feed intelligence** | None — no ambient monitoring | Active polling + relevance scoring + digests | Distillery's ambient radar is a differentiator |
| **Retrieval UX** | Search + browse + ask | Conversational (`/recall`, `/pour`) with synthesis | Agent-native retrieval vs search-box retrieval |
| **Raw content** | Discarded after extraction | Optionally retained (session context) | Sometimes you need the full conversation, not just the distillation |

### Key Insight

Elastic Brain and Distillery occupy different points on the same spectrum:

```
Raw Document Store (RAG)  ←→  Elastic Brain  ←→  Distillery
       ↑                           ↑                  ↑
  Store everything           Extract knowledge    Extract + curate +
  Retrieve chunks            Discard source       collaborate + monitor
  Dumb retrieval             Smart extraction      Smart everything
```

Elastic Brain is a **knowledge refinery** — it processes bulk content into structured knowledge. Distillery is a **team knowledge organism** — it captures, classifies, connects, monitors, and surfaces knowledge through an agentic interface. They share the core insight (distill, don't store raw) but Distillery adds the human/team/ambient layers.

### Ideas to Explore

1. **Could Distillery use Elastic Brain's extraction pipeline?** For bulk document ingestion (onboarding a new team, importing a wiki), Elastic Brain's queue-based extraction pattern is better suited than one-at-a-time `/distill` commands. Consider a `/bulk-ingest` skill that uses a similar pattern.

2. **Dual extraction pattern.** Elastic Brain extracts both generic patterns AND source-specific docs from a single asset. Distillery could similarly extract both team-level knowledge AND project-specific context from a single session.

3. **LangGraph for agent orchestration.** Elastic Brain uses LangGraph for multi-step extraction workflows. Distillery's skills are currently conceptualized as Claude Code skills (simpler). For complex workflows like `/investigate` or `/process`, LangGraph could provide better orchestration with retry logic, parallel tool calls, and state management.

## Memory Layer: Technology Debate

Researched 2026-03-20. Three contenders evaluated for Distillery's storage backend.

### Option A: Elasticsearch (semantic_text)

**Pros:**
- Proven at Elastic Brain scale — working internal reference implementation exists
- Native `semantic_text` field — embedding generation + ANN search handled internally, zero external embedding API calls
- Hybrid search — BM25 lexical + kNN vector + RRF rank fusion in a single query. Critical for Distillery: metadata filters ("meeting notes from project X") + semantic search ("about rate limiting decisions") compose naturally
- ES|QL for temporal queries — digests, `/radar`, and `/briefing` need time-series aggregations
- BBQ quantization — 95% memory reduction for embeddings, 15ms latency at 100MB RAM
- Inference Endpoints API — swap embedding models (ELSER, Cohere, OpenAI) without code changes
- Operational maturity — battle-tested at scale, team likely already has ES expertise
- Agent ecosystem — MCP integration, A2A protocol support already shipping

**Cons:**
- Operational weight — ES is a heavy service. Running a cluster for a small KB is overkill initially
- Cost — Elastic Cloud pricing is non-trivial for < 10K entries
- Vendor lock-in — `semantic_text` is Elastic-specific. Migrating means rebuilding the embedding pipeline
- Complexity floor — index mappings, sharding, replica management even for simple use cases
- Write latency — near-real-time (1s refresh), not instant

### Option B: DuckDB + VSS Extension

**Pros:**
- Zero infrastructure — embedded database, single file. No server, no cluster, no cloud dependency
- Local-first — each team member can have a local replica. Works offline. Syncs via file copy or MotherDuck
- SQL interface — standard SQL queries. Lower learning curve than ES query DSL
- Composable analytics — excels at analytical queries (type distribution, capture frequency, trends for `/digest`)
- MCP server pattern proven — [IzumiSy/mcp-duckdb-memory-server](https://github.com/IzumiSy/mcp-duckdb-memory-server) implements knowledge graph with entities/observations/relations tables
- Cost — free, open source
- MotherDuck — cloud-hosted DuckDB for team access without running infrastructure

**Cons:**
- VSS extension is experimental — HNSW persistence requires `hnsw_enable_experimental_persistence = true`, with WAL recovery issues and data corruption risk
- No native embedding generation — must generate embeddings externally (OpenAI, Cohere, local model)
- FLOAT arrays only — limited to 32-bit float vectors. No quantization options
- Memory management — HNSW index allocates outside DuckDB's memory limits
- No hybrid search — no native BM25 + vector fusion. Would need manual implementation
- Scale ceiling — designed for analytics, not high-concurrency serving
- Existing MCP server has no vector search — uses Fuse.js fuzzy string matching, not semantic search

### Option C: Managed Vector DB (Pinecone / Qdrant / Weaviate)

**Pros:**
- Purpose-built — best-in-class retrieval performance (Pinecone: 7ms p99 vs ES: 1600ms per benchmark)
- Managed — zero ops burden
- Metadata filtering — all support hybrid filter + vector search
- Simple API — upsert vectors, query by similarity. Minimal conceptual overhead

**Cons:**
- Single-purpose — need a separate store for structured metadata, analytics, temporal queries
- Cloud-only — no local-first option (except Qdrant self-hosted)
- Cost at scale — Pinecone pricing can surprise
- No analytical queries — can't run "capture frequency by week" or "type distribution" without a second database
- Vendor lock-in — each has its own API. Migration means reindexing

### Comparison Matrix

| Dimension | Elasticsearch | DuckDB + VSS | Managed Vector DB |
|---|---|---|---|
| Setup complexity | High | Low | Low |
| Operational burden | High | None (embedded) | None (managed) |
| Vector search quality | Strong (hybrid) | Experimental | Best-in-class |
| Embedding generation | Built-in | External | External |
| Structured queries | ES\|QL (strong) | SQL (excellent) | Limited |
| Temporal analytics | Native | Native | Not available |
| Cost (small team) | $$$ | Free | $$ |
| Cost (at scale) | $$ | $ (MotherDuck) | $$$ |
| Team expertise (Elastic) | High | Medium | Low |
| Hybrid search | Native (BM25+kNN+RRF) | Manual | Varies |
| Local-first | No | Yes | No |
| MCP ecosystem | Emerging | Exists (no vector) | Emerging |
| Maturity for vectors | Production | Experimental | Production |
| Migration risk | Medium | Low (standard SQL) | Medium |

### Recommendation: Phased Approach

**Phase 1 — Prototype (now):** DuckDB + external embeddings (OpenAI/Cohere). Single file, zero infrastructure, SQL for analytics. Use HNSW with experimental persistence — acceptable risk for a research project. Build skill interfaces and classification pipeline against a **storage abstraction layer**.

**Phase 2 — Team adoption:** When KB exceeds ~10K entries or needs concurrent multi-user access, migrate to Elasticsearch with `semantic_text`. Team has ES expertise, Elastic Brain proves the pattern, gain hybrid search + native embeddings + temporal analytics. Abstraction layer makes this a backend swap, not a rewrite.

**Skip managed vector DBs** — they solve similarity search well but Distillery needs structured metadata, temporal queries, analytical aggregations, and hybrid search. Would end up bolting on a second database.

### Critical Architecture Decision: Storage Abstraction Layer

Build from day one. The skills (`/distill`, `/recall`, `/pour`) talk to an interface, not directly to DuckDB or ES:

```python
class DistilleryStore(Protocol):
    async def store(self, entry: Entry) -> str: ...
    async def search(self, query: str, filters: dict) -> list[Entry]: ...
    async def get(self, entry_id: str) -> Entry: ...
    async def update(self, entry_id: str, updates: dict) -> Entry: ...
    async def find_similar(self, content: str, threshold: float) -> list[Entry]: ...
    async def aggregate(self, query: AggregationQuery) -> AggregationResult: ...

class DuckDBStore(DistilleryStore): ...   # Phase 1
class ElasticsearchStore(DistilleryStore): ...  # Phase 2
```

### Sources

- [Why Elasticsearch is the Best Memory for AI Agents](https://dev.to/omkar598/why-elasticsearch-is-the-best-memory-for-ai-agents-a-deep-dive-into-agentic-architecture-137l)
- [MCP DuckDB Memory Server](https://github.com/IzumiSy/mcp-duckdb-memory-server)
- [DuckDB Vector Similarity Search](https://duckdb.org/2024/05/03/vector-similarity-search-vss)
- [Vector Technologies for AI: Extending Your Data Stack](https://motherduck.com/blog/vector-technologies-ai-data-stack/)
- [DuckDB VSS Extension Docs](https://duckdb.org/docs/stable/core_extensions/vss)
- [Hindsight MCP Memory Server](https://hindsight.vectorize.io/blog/2026/03/04/mcp-agent-memory)

## Deliberation Results (Confer)

Conducted 2026-03-20 via structured adversarial deliberation (proposer → advocate → arbiter).

### Verdict

The brainstorm conflates three projects into one. Scope is the primary risk. The core insight (agent-native team KB via Claude Code skills) is strong and differentiated. The arbiter found the advocate's position strictly stronger than the proposer's — same diagnosis, but the advocate defined the cuts, the MVP, and identified critical gaps.

### Scope Decision

**Phase 1 — MVP (target: 4 weeks, single team)**

6 core skills:
- `/distill` — capture session context + knowledge
- `/recall` — semantic search
- `/pour` — multi-entry synthesis
- `/bookmark` — URL + summary storage
- `/minutes` — team meeting notes (updatable)
- `/classify` — retained; needed to build the connected knowledge graph

Classification rationale: While explicit skill choice (`/distill` vs `/minutes`) provides an initial type signal, classification goes deeper — it extracts entities, tags, project associations, and cross-references that build the connective tissue between entries. Without it, the KB is a flat collection of documents. With it, `/recall` and `/pour` can traverse relationships, not just match embeddings. Classification is what makes this a *knowledge graph* rather than a *document store*.

**Phase 2 — Team Expansion**
- `/whois` — people-expertise map
- `/investigate` — domain context builder
- `/digest` — team activity summaries
- `/briefing` — team knowledge dashboard
- `/process` — batch classify + digest + stale detection
- `/gh-sync` — GitHub issue/PR tracking
- Elasticsearch migration (if DuckDB hits scale ceiling)

**Phase 3 — Ambient Intelligence**
- `/radar` — ambient feed digest
- `/watch` — feed source management
- `/tune` — relevance threshold tuning
- Feed polling infrastructure (RSS, Slack, GitHub, HN, webhooks)
- Relevance scoring pipeline
- Feedback loop (trust weight adjustment)

Ambient feed intelligence is NOT cut — it is a core differentiator. It is deferred to Phase 3 because it requires: (a) a working KB with project embeddings to score against, (b) enough team usage to bootstrap the feedback loop, and (c) its own development cycle for polling infrastructure and source adapters. Building it before the core KB is validated would be premature.

### Critical Gaps to Address (pre-MVP)

These were identified as architectural omissions, not nice-to-haves:

1. **Retrieval quality evaluation** — How do we know `/recall` returns useful results? Need baseline metrics (relevance scoring, user satisfaction, precision/recall). Without this, no feedback loop for improvement.

2. **Access control model** — "Team-first" visibility needs specifics. Minimum viable: binary team/private flag on every entry. If people fear captures are visible to wrong audience, they won't capture. Address before first team deployment.

3. **Embedding model selection** — Which model, what dimensionality, how to handle model upgrades (re-embedding entire corpus). Operational concern that affects storage schema design.

4. **Content lifecycle** — Archival, expiration, noise growth. A KB that only grows becomes noisy. Define when/how content moves to archive or expires. PARA has "Archives" but the brainstorm doesn't operationalize it.

5. **Conflict resolution** — Two people `/distill` contradictory information about the same topic. Semantic dedup handles exact duplicates but not conflicting facts. Need a strategy (flag conflicts, version with attribution, surface for team resolution).

### Open Investigation

**Storage migration friction:** The `DistilleryStore` abstraction layer is the right pattern, but whether it can realistically insulate against SQL → ES|QL differences needs investigation before committing to the phased approach. Specifically: can hybrid search (BM25+kNN+RRF) semantics be abstracted, or will retrieval logic tuned on DuckDB need to be re-tuned on ES? If the gap is too large, starting on ES directly (accepting higher ops overhead) may be the pragmatic choice for a team at Elastic.

## Roadmap

### Phase 1 — MVP (4 weeks)

- [ ] Define access control model (minimum: team/private flag)
- [ ] Select embedding model + define re-embedding strategy
- [ ] Design retrieval quality metrics (baseline measurement plan)
- [ ] Design content lifecycle policy (archival, expiration)
- [ ] Design conflict detection strategy
- [ ] Implement storage abstraction layer (`DistilleryStore` protocol)
- [ ] Build storage backend (DuckDB or ES — pending investigation)
- [ ] Design classification pipeline for knowledge graph construction
- [ ] Design semantic deduplication (score thresholds for skip/merge/create)
- [ ] Build 6 core skills: `/distill`, `/recall`, `/pour`, `/bookmark`, `/minutes`, `/classify`
- [ ] Define metadata schema: minimal core + typed extensions per entry type
- [ ] Deploy for single team, measure retrieval quality

### Phase 2 — Team Expansion

- [ ] Build 6 additional skills: `/whois`, `/investigate`, `/digest`, `/briefing`, `/process`, `/gh-sync`
- [ ] Port type schemas from personal system (only types justified for team use)
- [ ] Design namespace taxonomy (hierarchical, validated)
- [ ] Design provenance tracking (source chain, author chain, version history)
- [ ] Evaluate Elasticsearch migration (if on DuckDB and hitting scale ceiling)
- [ ] Design session capture hooks (auto-distill on session end)

### Phase 3 — Ambient Intelligence

- [ ] Design feed polling architecture (scheduler, source adapters)
- [ ] Define feed source adapter interface (RSS, Slack, GitHub, HN, webhooks)
- [ ] Design relevance scoring pipeline (embedding comparison + boosting)
- [ ] Solve cold-start problem (bootstrap relevance scoring without feedback data)
- [ ] Build `/radar`, `/watch`, `/tune` skills
- [ ] Implement feedback loop (trust weight adjustment)

### Deferred / Evaluate Later

- [ ] Confirm domain availability on a registrar
- [ ] Evaluate LangGraph for complex skill orchestration (define need first)
- [ ] Design the CODE pipeline for team workflows
