# CW-RESEARCH: Distillery — General Codebase Research Report

**Date:** 2026-03-21
**Topic:** General (full project)
**Status:** Greenfield — no code exists yet

---

## Summary

Distillery is a **team-accessible "Second Brain"** inspired by Tiago Forte's BASB methodology (CODE + PARA), accessed through an agentic interface (Claude Code skills) and backed by a vector database. It captures, classifies, connects, and surfaces team knowledge through conversational commands.

**Key findings:**

1. **The project is well-scoped** — a 3-phase roadmap with a 4-week MVP targeting 6 core skills, a storage abstraction layer, and a classification pipeline with semantic deduplication.
2. **Strong lineage** — ports proven patterns from an existing personal second brain (Obsidian + Claude Code) and adopts key patterns from Elastic Brain (two-phase extraction, semantic dedup, namespace taxonomy, provenance tracking).
3. **Technology choices are sound** — phased DuckDB → Elasticsearch migration behind a storage abstraction layer. DuckDB VSS is experimental but acceptable for prototype; Elasticsearch `semantic_text` is production-ready with native hybrid search.
4. **Five critical gaps** must be addressed pre-MVP: retrieval quality evaluation, access control model, embedding model selection, content lifecycle policy, and conflict resolution strategy.
5. **The agentic interface is the differentiator** — unlike Elastic Brain (CLI + REST + SPA) or traditional RAG systems, Distillery's LLM IS the interface. Skills are the API surface.

---

## 1. Tech Stack & Project Structure

### Current State

- **Working directory:** `/Users/norrie/code/distillery`
- **Files:** `distillery-brainstorm.md` (770 lines, comprehensive design document)
- **No code, no manifest files, no dependencies**

### Proposed Technology Stack

| Layer | Phase 1 (MVP) | Phase 2 (Team) | Phase 3 (Ambient) |
|-------|---------------|----------------|---------------------|
| Interface | Claude Code skills | Same | Same |
| Storage | DuckDB + VSS extension | Elasticsearch (semantic_text) | Same |
| Embeddings | External (OpenAI/Cohere/BGE-M3) | ES native or external | Same |
| Language | Python (implied by `DistilleryStore` Protocol) | Same | Same |
| Orchestration | Claude Code skill invocation | Same | + scheduled polling |
| Configuration | YAML config file | Same | + feed configuration |

### Claude Code Skills Architecture

Skills are the primary interface. Each skill is a directory containing:
- `SKILL.md` — YAML frontmatter (name, description, triggers) + markdown instructions
- Optional supporting scripts, reference files, templates

**Installation paths:**
- Personal: `~/.claude/skills/<name>/SKILL.md`
- Project: `.claude/skills/<name>/SKILL.md` (committed to git, shared with team)
- Enterprise: via managed settings

**Key skill features relevant to Distillery:**
- `$ARGUMENTS` for passing query text to `/recall`, `/distill`, etc.
- `allowed-tools` to restrict tool access per skill
- `context: fork` for isolated subagent execution
- `${CLAUDE_SESSION_ID}` for linking entries to sessions
- Dynamic context injection via `` !`shell command` `` syntax

### Existing Skills (from personal system at `/Users/norrie/code/claude-config/skills/`)

| Skill | Purpose | Distillery Relevance |
|-------|---------|---------------------|
| `session-log` | Capture session context to `~/second-brain-inbox/` | Direct ancestor of `/distill` |
| `confer` | Adversarial deliberation (proposer → advocate → arbiter) | Pattern for decision documentation |
| `prd-generator` | Prose-driven PRD generation | Knowledge lifecycle patterns |
| `gh-onmyplate` | GitHub notification triage | Pattern for `/gh-sync`, noise filtering |
| `lead-architect` | PRD → architecture + worker plans | Framework for `/investigate` |

### Session-Log Skill (Direct Ancestor of `/distill`)

**Output format:** Markdown file at `~/second-brain-inbox/YYYY.MM.DD-session-HHMMSS.md`

```yaml
---
type: inbox
source: agent-session
project: "<project-name>"
created: "YYYY-MM-DD HH:mm"
modified: "YYYY-MM-DD HH:mm"
original_text: "<one-line summary for classifier>"
tags: [session-log]
---
```

**Sections:** What Was Done, Decisions, Open Questions, Key Files

**Distillery adaptation:** Replace file drop with direct vector DB storage. Add `author`, `session_id`, `team` metadata. Auto-extract decisions, action items, architectural insights. Team visibility by default.

---

## 2. Architecture & Patterns

### Storage Abstraction Layer (Critical Pattern)

Skills talk to an interface, not directly to DuckDB or Elasticsearch:

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

**Open investigation:** Whether hybrid search semantics (BM25+kNN+RRF) can be abstracted across backends, or if retrieval logic tuned on DuckDB will need re-tuning on ES.

### Two-Phase Extraction (from Elastic Brain)

1. **Extractor:** What knowledge exists in this content? (decisions, insights, patterns, entities)
2. **Creator:** How to store without duplicates? (semantic search → score thresholds → skip/merge/create)

Applied to `/distill`:
- Phase 1: Extract decisions, action items, architectural insights
- Phase 2: Find similar entries, offer to merge/update/link

### Semantic Deduplication (Critical — from Elastic Brain)

Score thresholds on semantic similarity:
- **≥ 20:** Duplicate → skip or merge
- **10–15:** Related → enhance existing entry + create link
- **< 10:** Novel → create new entry

Without this, repeated `/distill` calls pollute the KB.

### Classification Pipeline

The intelligence layer that transforms a document store into a knowledge graph:

```
INPUT: Raw content
OUTPUT: entry_type, confidence, metadata (entities, tags, project associations, cross-references), reasoning
RULE: confidence < threshold (0.6) → pending_review → team review queue
```

**Why classification is essential for MVP:** It extracts entities, tags, project associations, and cross-references that build connective tissue between entries. Without it, `/recall` and `/pour` can only match embeddings. With it, they can traverse relationships.

### Knowledge Graph Construction

1. **Entities:** Extracted from content (people, projects, domains, decisions)
2. **Tags:** Assigned by classifier or author
3. **Relationships:** Direct links, semantic links, temporal links
4. **Traversal:** `/pour` walks the graph to synthesize multi-entry answers

### Hierarchical Namespace/Taxonomy (from Elastic Brain)

Instead of flat tags:
```
/project/billing-v2/decisions
/project/auth-rewrite/architecture
/team/onboarding/runbooks
/domain/payments/expertise
/external/stripe/changelog
```

### Skill Interaction Flow

```
User Query → Claude Code Session → Skill (e.g., /recall)
    → DistilleryStore Interface → Concrete Backend (DuckDB/ES)
    → Embedding lookup + metadata filters → LLM Synthesis
    → Answer with provenance (entry IDs, sources)
```

### MCP Integration Opportunity

Distillery could expose an MCP server for vector search, retrieval, and storage operations. Any Claude Code session could connect and use Distillery skills. Existing MCP ecosystem includes servers for Qdrant, Chroma, Milvus, and DuckDB memory.

---

## 3. Dependencies & Integrations

### Vector Database Options (Researched)

#### DuckDB + VSS Extension (Phase 1)

**Current status (2026):** Experimental. Not production-ready.

| Aspect | Detail |
|--------|--------|
| Persistence | HNSW indexes in-memory by default; experimental persistence has WAL recovery issues |
| Vector types | 32-bit float only, no quantization |
| Distance metrics | Cosine, Euclidean, Dot Product |
| Hybrid search | Not native — must implement manually |
| Embedding generation | External (no built-in) |
| Concurrency | Not designed for high-concurrency serving |
| Cost | Free, embedded, zero infrastructure |

**Verdict:** Acceptable for prototype. Known risks (data corruption on unexpected shutdown). Must have backup strategy.

#### Elasticsearch semantic_text (Phase 2)

**Current status (2026):** Production-ready.

| Aspect | Detail |
|--------|--------|
| Semantic search | `semantic_text` field type — auto embedding generation + ANN search |
| Chunking | Automatic (250-word sections, 100-word overlap) |
| Hybrid search | Native BM25 + kNN + RRF (Reciprocal Rank Fusion) |
| Quantization | BBQ — up to 32x memory reduction with minimal accuracy loss |
| ES\|QL | Temporal queries, aggregations for digests/radar/briefing |
| Embedding models | Built-in ES service, OpenAI, Cohere, Jina v5 |
| New (2026) | Linear Retriever — weighted alternative to RRF |

**Verdict:** Strong production choice. Team has ES expertise. Elastic Brain proves the pattern.

#### Managed Vector DBs (Pinecone/Qdrant/Weaviate) — Skipped

Single-purpose (vectors only). Would need a second database for structured metadata, analytics, temporal queries. Hidden cost at scale.

### Embedding Model Options (Researched)

| Model | Dimensions | Cost | Self-hosted | Accuracy | Best For |
|-------|-----------|------|-------------|----------|----------|
| OpenAI text-embedding-3-large | 3072 | $$$ | No | Highest | English-primary, budget flexible |
| OpenAI text-embedding-3-small | 512 | $$ | No | High | Cost-conscious, good accuracy |
| Cohere embed-v3 | 1024 | $$ | No | High | Multilingual, cost-sensitive |
| **BGE-M3** | Configurable | **Free** | **Yes** | **Highest** | **Multilingual production, self-hosted** |
| Nomic Embed Text V2 | 768 | Free | Yes | High | Lightweight, efficient |
| all-mpnet-base-v2 | 768 | Free | Yes | Good | Simple, commercially safe |

**Key insight:** Matryoshka embeddings allow dimension reduction post-generation (768d retains 97-99% accuracy of full dimensions). Critical for storage cost reduction.

**Recommendation for Distillery:**
- **Phase 1 (prototype):** OpenAI text-embedding-3-small (fast iteration, simple API)
- **Phase 2 (production):** BGE-M3 self-hosted or Cohere embed-v3 (cost/quality balance)
- **Must decide:** Re-embedding strategy on model upgrades (lazy vs batch)

### External System Integrations

| System | Skill | Integration Method |
|--------|-------|-------------------|
| GitHub | `/gh-sync` | `gh` CLI / GitHub API |
| Slack | `/radar` (Phase 3) | Slack MCP / API |
| RSS feeds | `/radar` (Phase 3) | Standard RSS fetch |
| Hacker News | `/radar` (Phase 3) | API / RSS |
| Webhooks | `/radar` (Phase 3) | Ingest API endpoint |

---

## 4. Data Models & API Surface

### Core Entry Schema

```json
{
  "id": "uuid",
  "content": "...",
  "source": "claude-code | slack | github | rss | manual",
  "entry_type": "session | bookmark | minutes | meeting | reference | person | project | idea | inbox | digest | github",
  "session_type": "work | cowork | null",
  "author": "norrie",
  "project": "billing-v2",
  "tags": ["architecture", "decisions"],
  "timestamp": "2026-03-20T...",
  "session_id": "...",
  "url": "...",
  "meeting_id": "...",
  "version": 1,

  "team": "engineering",
  "visibility": "team | private",
  "confidence": 0.87,
  "classified_at": "2026-03-20T...",
  "status": "active | pending_review | archived",

  "created_at": "2026-03-20T...",
  "updated_at": "2026-03-20T...",
  "update_count": 0,
  "source_hash": "...",
  "author_chain": ["norrie"]
}
```

### Type System (Ported from Personal System)

| Type | Phase | Ported From | Team Additions |
|------|-------|-------------|----------------|
| `reference` | MVP | Direct port | — |
| `inbox` | MVP | Direct port | — |
| `idea` | MVP | Direct port | — |
| `meeting` | MVP | `/meeting` | `team`, `visibility` |
| `person` | Phase 2 | `person` | Evidence-backed expertise scoring |
| `project` | Phase 2 | `project` | `owner`, `team` |
| `digest` | Phase 2 | `digest` | Team-level aggregation |
| `github` | Phase 2 | `github` | Shared tracking |
| `task` | Evaluate | `task` | `assignee`; or defer to external trackers |
| `admin` | Drop | — | Merge into `reference` |
| `dailynote` | Drop | — | Personal artifact |

### Skill API Surface (All Phases)

#### Phase 1 — MVP (6 skills)

| Skill | Input | Output | Storage Operation |
|-------|-------|--------|-------------------|
| `/distill` | Session context or free text | Confirmation + entry ID | `store()` + `find_similar()` + `classify()` |
| `/recall` | Natural language query | Synthesized answer with sources | `search()` with semantic + metadata filters |
| `/pour` | Topic or question | Multi-entry synthesis | `search()` → graph traversal → synthesis |
| `/bookmark` | URL + optional summary/tags | Confirmation + entry ID | `store()` with URL metadata |
| `/minutes` | Meeting context | Confirmation + meeting ID | `store()` or `update()` (versioned) |
| `/classify` | Entry ID or batch | Classification results | `update()` with type, confidence, metadata |

#### Phase 2 — Team Expansion (6 skills)

| Skill | Purpose |
|-------|---------|
| `/whois` | "Who knows about X?" — evidence-backed expertise map |
| `/investigate` | Deep domain context builder (5-phase workflow) |
| `/digest` | Team activity summaries with stale detection |
| `/briefing` | Team knowledge dashboard |
| `/process` | Batch classify + digest + stale detection |
| `/gh-sync` | GitHub issue/PR tracking |

#### Phase 3 — Ambient Intelligence (3 skills)

| Skill | Purpose |
|-------|---------|
| `/radar` | View latest ambient feed digest |
| `/watch` | Add/remove/list monitored feed sources |
| `/tune` | Adjust relevance thresholds and trust weights |

### Feed Configuration (Phase 3)

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

### Relevance Scoring Pipeline (Phase 3)

```
For each new feed item:
  1. Embed item (title + summary)
  2. Query vector DB for active projects + recent references
  3. Compute cosine similarity against each project embedding
  4. Score = max(similarities) × (project priority × tag overlap × recency × source trust)
  5. score > relevance_threshold → include in digest
  6. score > alert_threshold → immediate notification
```

---

## 5. Test & Quality Patterns

### No Code Exists Yet

Test strategy must be defined as part of MVP. Key areas requiring testing:

1. **Retrieval quality** — precision/recall metrics for `/recall` queries. Baseline measurement plan needed before first deployment.
2. **Classification accuracy** — confidence calibration (does 0.8 confidence mean 80% accuracy?). Correction rate tracking.
3. **Deduplication** — score threshold tuning (are 20/10 the right boundaries?). False positive/negative rates.
4. **Storage abstraction** — integration tests against both DuckDB and Elasticsearch backends.
5. **Skill behavior** — end-to-end tests for each skill (input → expected storage operations → expected output).

### Quality Signals from Personal System

The personal second brain tracks:
- Classification log (every classification recorded with type, confidence, reasoning)
- Dirty detection (entries where `modified > classified_at` need re-classification)
- Correction rate (how often human review changes classifier output)
- Stale entry detection (projects inactive 14+ days)

These should port to Distillery as operational metrics.

---

## 6. Critical Gaps & Open Decisions

### Pre-MVP Blockers

1. **Retrieval quality evaluation** — How do we know `/recall` returns useful results? Need baseline metrics (relevance scoring, user satisfaction, precision/recall). Without this, no feedback loop for improvement.

2. **Access control model** — Minimum viable: binary `team/private` flag on every entry. If team members fear captures are visible to wrong audience, they won't capture. Must address before first team deployment.

3. **Embedding model selection** — Which model, what dimensionality, how to handle model upgrades (re-embedding entire corpus). Affects storage schema design.

4. **Content lifecycle** — When/how entries move to archive or expire. PARA has "Archives" but the brainstorm doesn't operationalize it. A KB that only grows becomes noisy.

5. **Conflict resolution** — Two people `/distill` contradictory information about same topic. Semantic dedup handles exact duplicates, not conflicting facts. Need strategy (flag conflicts, version with attribution, surface for team resolution).

### Design Decisions (Not Blockers)

6. **Implicit vs explicit classification** — Auto-classify on every `/distill`, or let author choose type? Brainstorm leans implicit with override.

7. **Entry mutability** — Vector entries are harder to "append to" than files. Versioning strategy needed for minutes, expertise profiles.

8. **Cross-references** — Replace Obsidian wiki-links with what? Entry IDs, tags, hierarchical paths, or all three?

9. **Source of truth** — Distillery is a knowledge layer, not a task tracker. Must not duplicate Jira/Linear/GitHub.

10. **Storage migration friction** — Can `DistilleryStore` abstraction realistically insulate against SQL → ES|QL differences? If gap too large, start on ES directly.

---

## 7. Elastic Brain Comparison

*Note: The `elastic/elastic_brain` GitHub repo is private/internal. Analysis is based on the detailed comparison in the brainstorm document.*

### Shared Principles

| Principle | Elastic Brain | Distillery |
|-----------|---------------|------------|
| Knowledge distillation over storage | Extract understanding, discard source | Same — progressive distillation |
| Type system | ~31 knowledge types with schemas | Type dispatch with per-type schemas |
| Classification pipeline | Two-phase (extractor + creator) | Confidence-scored + human review |
| Semantic deduplication | Creator searches before storing | Adopting this pattern |
| Structured metadata | Namespace, tags, relationships, provenance | Same on every vector entry |

### Key Divergences

| Dimension | Elastic Brain | Distillery |
|-----------|---------------|------------|
| Interface | CLI + REST + React SPA | Claude Code skills (agent-native) |
| Ingestion | Batch CLI, queue-based (Redis/RQ) | Real-time + ambient + manual |
| Human in loop | None (fully automated) | Confidence threshold + team review |
| Sources | Elastic ecosystem only | Anything (sessions, meetings, feeds, Slack) |
| Collaboration | Single-user extraction | Multi-author, team-visible, attributed |
| Feed intelligence | None | Active polling + relevance scoring |

### Adopted Patterns

1. **Semantic deduplication** with score thresholds
2. **Two-phase extraction** (extract → deduplicate/store)
3. **Namespace/taxonomy** (hierarchical, validated)
4. **Provenance tracking** (source chain, author chain, version history)
5. **Processing state tracking** (prevents reprocessing)

---

## 8. External Context

### Source: Personal Second Brain (`norrietaylor/second-brain`)

GitHub repo explored. Key skills and patterns documented in Section 1 (session-log, confer, prd-generator, gh-onmyplate, lead-architect). The session-log skill is the direct ancestor of `/distill`.

### Source: Elastic Brain (`elastic/elastic_brain`)

Private/internal repository. Analysis based on brainstorm document comparison (Section 7). Key architectural patterns identified for adoption.

### Source: Technology Research (Web)

DuckDB VSS, Elasticsearch semantic_text, embedding models, MCP ecosystem, and Claude Code skills architecture researched and documented in Sections 1-3.

---

## 9. Roadmap

### Phase 1 — MVP (4 weeks)

- [ ] Define access control model (minimum: team/private flag)
- [ ] Select embedding model + define re-embedding strategy
- [ ] Design retrieval quality metrics (baseline measurement plan)
- [ ] Design content lifecycle policy (archival, expiration)
- [ ] Design conflict detection strategy
- [ ] Implement storage abstraction layer (`DistilleryStore` protocol)
- [ ] Build storage backend (DuckDB + VSS)
- [ ] Design classification pipeline for knowledge graph construction
- [ ] Design semantic deduplication (score thresholds for skip/merge/create)
- [ ] Build 6 core skills: `/distill`, `/recall`, `/pour`, `/bookmark`, `/minutes`, `/classify`
- [ ] Define metadata schema: minimal core + typed extensions per entry type
- [ ] Deploy for single team, measure retrieval quality

### Phase 2 — Team Expansion

- [ ] Build 6 additional skills: `/whois`, `/investigate`, `/digest`, `/briefing`, `/process`, `/gh-sync`
- [ ] Port type schemas (only types justified for team use)
- [ ] Design namespace taxonomy (hierarchical, validated)
- [ ] Design provenance tracking
- [ ] Evaluate Elasticsearch migration
- [ ] Design session capture hooks (auto-distill on session end)

### Phase 3 — Ambient Intelligence

- [ ] Design feed polling architecture (scheduler, source adapters)
- [ ] Define feed source adapter interface
- [ ] Design relevance scoring pipeline
- [ ] Solve cold-start problem
- [ ] Build `/radar`, `/watch`, `/tune` skills
- [ ] Implement feedback loop

---

## Meta-Prompt for /cw-spec

The following meta-prompt can be used to invoke `/cw-spec` with enriched context from this research:

---

**Feature Name:** Distillery MVP — Team Knowledge Base with Agentic Interface

**Problem Statement:** Teams accumulate knowledge across sessions, meetings, code reviews, and external sources, but this knowledge is scattered across individual memories, Slack threads, and undocumented decisions. There is no shared, searchable, AI-accessible knowledge base that captures, classifies, and surfaces team knowledge through conversational commands.

**Key Components:**
1. **Storage abstraction layer** — `DistilleryStore` protocol with DuckDB backend (Phase 1)
2. **Classification pipeline** — confidence-scored auto-classification with semantic deduplication and team review queue
3. **6 core skills** — `/distill` (capture), `/recall` (search), `/pour` (synthesize), `/bookmark` (URLs), `/minutes` (meetings), `/classify` (pipeline)
4. **Entry type system** — type dispatch with per-type schemas (reference, inbox, idea, meeting, session, bookmark)
5. **Metadata schema** — structured metadata on every vector entry (author, project, tags, confidence, provenance)

**Architectural Constraints:**
- All interaction through Claude Code skills (no GUI, no REST API for MVP)
- Storage abstraction must support future migration to Elasticsearch
- Classification is mandatory — it builds the knowledge graph connective tissue
- Semantic deduplication prevents KB pollution (score thresholds: ≥20 skip, 10-15 link, <10 create)
- Access control: binary team/private flag on every entry
- Python implementation (Protocol-based abstractions)

**Patterns to Follow:**
- Two-phase extraction (extract → deduplicate/store) from Elastic Brain
- Session-log skill pattern from personal second brain (frontmatter + sections)
- Confidence threshold + review queue pattern (threshold 0.6, below → pending_review)
- Progressive distillation (raw → classified → refined over time)

**Suggested Demoable Units:**
1. `/distill` captures a session summary → stored in vector DB with metadata → retrievable via `/recall`
2. `/recall` returns semantically relevant entries with provenance (entry IDs, authors, timestamps)
3. `/pour` synthesizes across multiple entries on a topic, citing sources
4. `/bookmark` stores URL with AI-generated summary, deduplicates against existing bookmarks
5. `/minutes` stores meeting notes, updatable via meeting_id (versioned)
6. `/classify` processes inbox entries, assigns types with confidence, routes low-confidence to review queue
7. Semantic deduplication: `/distill` on already-known topic offers merge instead of duplicate creation

**Code References:**
- Brainstorm: `/Users/norrie/code/distillery/distillery-brainstorm.md`
- Session-log skill (ancestor of /distill): `/Users/norrie/code/claude-config/skills/session-log/SKILL.md`
- Research report: `/Users/norrie/code/distillery/docs/specs/research-general/research-general.md`

---
