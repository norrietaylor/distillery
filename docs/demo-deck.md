<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/distillery-logo-dark-512.png" width="200">
    <source media="(prefers-color-scheme: light)" srcset="assets/distillery-logo-512.png" width="200">
    <img alt="Distillery" src="assets/distillery-logo-512.png" width="200">
  </picture>
</p>

---

<!-- Slide deck formatted as markdown sections. Each ## is a slide. -->
<!-- Render with any markdown presentation tool (Marp, Slidev, Deckset, etc.) -->

## Distillery

**A team-accessible Second Brain powered by Claude Code**

Refine raw information into concentrated, searchable team knowledge.

*Inspired by Tiago Forte's Building a Second Brain — CODE methodology*

---

## The Problem

Teams generate knowledge constantly:
- Architecture decisions in Claude Code sessions
- Meeting outcomes discussed but not recorded
- Useful articles shared once and forgotten
- Insights scattered across Slack, docs, and memory

**Result:** Knowledge is created, then lost. New team members start from zero. Decisions get relitigated. Context evaporates.

---

## The Solution

<p align="center"><img src="assets/distillery-logo-256.png" width="80"></p>

Distillery captures, classifies, connects, and surfaces team knowledge through **conversational commands** inside Claude Code.

No context switching. No separate app. Knowledge flows where work happens.

---

## How It Works

```
         You working in Claude Code
                    │
            "We decided to use Redis
             for the session cache"
                    │
                /distill
                    │
        ┌───────────┴───────────┐
        │  Dedup Check          │
        │  Is this already      │
        │  known? (0.95/0.80    │
        │  /0.60 thresholds)    │
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │  Classify             │
        │  Type: session        │
        │  Confidence: 0.92     │
        │  Tags: [cache, redis] │
        └───────────┬───────────┘
                    │
              Stored in KB
          (embedded + indexed)
```

---

## 6 Skills — The Interface

| | Skill | What it does |
|---|---|---|
| **Capture** | `/distill` | Distill session knowledge with duplicate detection |
| **Search** | `/recall` | Semantic search — "what do we know about caching?" |
| **Synthesize** | `/pour` | Multi-entry synthesis with citations |
| **Bookmark** | `/bookmark` | Store URLs with auto-generated summaries |
| **Record** | `/minutes` | Meeting notes with append updates |
| **Organize** | `/classify` | Classify entries, triage review queue |

---

## Demo: /distill

Capture a decision from a working session:

```
> /distill

Scanning session context...

Distilled Summary:
  - Decided to use Redis for session caching (replaced Memcached)
  - Rationale: native pub/sub for cache invalidation across services
  - Action item: benchmark Redis cluster vs single-node for our load

Checking for duplicates...
  No similar entries found (highest score: 0.34)

Stored as entry abc12345
  Type: session | Author: norrie | Project: api-refactor
  Tags: [redis, caching, architecture]
```

---

## Demo: /recall

Search the knowledge base with natural language:

```
> /recall distributed caching strategies

Results (4 entries):

  92% [session] Decided to use Redis for session caching...
  ID: abc12345 | Author: norrie | Project: api-refactor | 2026-03-22

  87% [bookmark] Redis vs Memcached: A 2026 Comparison...
  ID: def67890 | Author: alice | Project: api-refactor | 2026-03-20

  71% [minutes] Standup: discussed CDN caching layer for static assets...
  ID: ghi11223 | Author: bob | Project: frontend | 2026-03-19

  65% [session] Evaluated Varnish for API response caching...
  ID: jkl44556 | Author: norrie | Project: api-refactor | 2026-03-15
```

---

## Demo: /pour

Synthesize across multiple entries into a cited narrative:

```
> /pour how does our caching strategy work?

Pass 1: 8 entries found (broad search)
Pass 2: 4 additional entries (follow-up on "Redis", "CDN", "invalidation")
Pass 3: 2 entries (gap-fill on "Varnish evaluation")
Total: 12 unique entries across 3 passes

## Summary

The team's caching strategy has evolved over the past month...
Redis was selected for session caching [Entry abc123] after evaluating
Memcached [Entry jkl445]. The CDN layer handles static assets [Entry ghi112]...

## Key Decisions
- Redis over Memcached for session cache (norrie, 2026-03-22)
- Varnish rejected for API caching due to config complexity (norrie, 2026-03-15)

## Knowledge Gaps
- No entries about cache warming strategy
- Single perspective on Redis decision (only norrie)

Would you like to go deeper on any sub-topic?
```

---

## Semantic Deduplication

Prevents knowledge base pollution from repeated captures:

```
Score >= 0.95  →  SKIP     "This is already captured"
Score 0.80-0.95 →  MERGE    "Merge into existing entry?"
Score 0.60-0.80 →  LINK     "Store and link to related entries"
Score < 0.60  →  CREATE   "Novel knowledge — store as new"
```

```
> /distill "We're using Redis for caching"

Duplicate detected (similarity: 0.97)
  Existing entry abc12345: "Decided to use Redis for session caching..."

This appears to be a duplicate. Options:
  1. Skip (don't store)
  2. Merge new details into existing entry
  3. Store anyway as separate entry
```

---

## Classification Pipeline

LLM-based auto-classification with confidence scoring:

```
                    Raw Content
                        │
                   ┌────┴────┐
                   │ Classify │
                   │ (LLM)   │
                   └────┬────┘
                        │
              ┌─────────┼─────────┐
              │         │         │
         conf >= 0.6   │    conf < 0.6
              │         │         │
           Active    Suggest   Pending
                     tags &    Review
                     project     │
                              ┌──┴──┐
                              │Queue│
                              └──┬──┘
                                 │
                        /classify --review
                                 │
                     Approve / Reclassify / Archive
```

---

## Architecture

```
┌──────────────────────────────────────────────┐
│               Claude Code                     │
│                                               │
│   /distill  /recall  /pour  /bookmark         │
│   /minutes  /classify                         │
│                                               │
│   ┌──────────────────────────────────────┐    │
│   │        MCP Server (stdio)            │    │
│   │        11 tools                      │    │
│   └──────────────┬───────────────────────┘    │
└──────────────────┼────────────────────────────┘
                   │
     ┌─────────────┼──────────────┐
     │             │              │
  DuckDB       Embedding    Classification
  + HNSW       Provider     Engine + Dedup
  index      (Jina/OpenAI)  (LLM-based)
```

**Key:** The MCP server is the sole runtime interface. Skills are markdown files. Storage is swappable.

---

## What Makes This Different

| Traditional KB | Distillery |
|---|---|
| Separate app to switch to | Lives in your coding tool |
| Manual categorization | LLM auto-classification |
| Keyword search | Semantic vector search |
| Flat document list | Multi-pass synthesis with citations |
| Grows noisy over time | Semantic dedup keeps it clean |
| Individual silos | Team-shared by default |

---

## Roadmap

<table>
<tr>
<td width="33%" valign="top">

### Phase 1 — MVP
**Complete**

- Storage layer (DuckDB + VSS)
- 6 core skills
- Classification pipeline
- Semantic deduplication
- Configurable embeddings

</td>
<td width="33%" valign="top">

### Phase 2 — Team
**Next**

- `/whois` expertise map
- `/digest` team summaries
- `/gh-sync` GitHub tracking
- Elasticsearch migration
- Access control
- Session capture hooks

</td>
<td width="33%" valign="top">

### Phase 3 — Ambient
**Future**

- `/radar` feed digest
- `/watch` source mgmt
- `/tune` relevance tuning
- Feed polling infra
- Relevance scoring
- Trust feedback loop

</td>
</tr>
</table>

---

## Getting Started

```bash
# Install
pip install -e .

# Configure
cp distillery.yaml.example distillery.yaml
export JINA_API_KEY=jina_...

# Connect to Claude Code
# Add MCP server config to ~/.claude/settings.json
# (see docs/mcp-setup.md)

# Verify
> distillery_status
```

Then start capturing:

```
> /distill
> /recall what do we know about...
> /pour give me the full picture on...
```

---

<p align="center">
  <img src="assets/distillery-logo-256.png" width="100">
  <br><br>
  <strong>Distillery</strong>
  <br>
  Refine raw information into concentrated team knowledge.
  <br><br>
  <code>pip install -e .</code> &middot; <a href="../README.md">README</a> &middot; <a href="ROADMAP.md">Roadmap</a> &middot; <a href="mcp-setup.md">Setup Guide</a>
</p>
