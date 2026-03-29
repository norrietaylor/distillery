---
marp: true
theme: default
paginate: true
---

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/distillery-logo-dark-512.png" width="200">
    <source media="(prefers-color-scheme: light)" srcset="assets/distillery-logo-512.png" width="200">
    <img alt="Distillery" src="assets/distillery-logo-512.png" width="200">
  </picture>
</p>

# Distillery
### A team Second Brain — built into Claude Code

---

## The Problem

Your team generates knowledge constantly.

- **Architecture decisions** made in Claude Code — never written down
- **Meeting outcomes** discussed, forgotten by next sprint
- **Useful articles** shared once in Slack, impossible to find later
- **Hard-won insights** trapped in one person's head

---

## The Problem

**The result:**

Knowledge gets created, then lost.
Decisions get relitigated.
New team members start from zero.

> *"Didn't we already figure this out?"*

---

## The Solution

Knowledge capture should live **where work happens**.

```
You                  Claude Code                Distillery
 │                        │                         │
 │  /distill              │                         │
 ├───────────────────────▶│ ──────────────────────▶ │
 │                        │    capture              │
 │                        │    deduplicate          │
 │                        │    classify + embed     │
 │                        │    index                │
 │  /recall               │                         │
 ├───────────────────────▶│ ──────────────────────▶ │
 │  ◀─────────────────────│ ◀────────────────────── │
 │    semantically ranked results                   │
```

No context switching. No separate app. One slash command.

---

## 9 Skills — The Interface

| Category | Skill | What it does |
|---|---|---|
| **Capture** | `/distill` | Distill session knowledge with duplicate detection |
| **Search** | `/recall` | Natural language semantic search |
| **Synthesize** | `/pour` | Multi-pass synthesis with cited narrative |
| **Organize** | `/bookmark` | Save URLs with auto-generated summaries |
| **Record** | `/minutes` | Meeting notes with append and browse modes |
| **Triage** | `/classify` | Classify entries, work the review queue |
| **Ambient** | `/watch` | Manage monitored feed sources |
| **Ambient** | `/tune` | Calibrate relevance thresholds |
| **Ambient** | `/radar` | Proactive digest of what's new in your ecosystem |

---

## Demo: /distill

Capture a decision from a working session:

```
> /distill

  Distilling session context...

  ┌────────────────────────────────────────────────────────┐
  │ Summary                                                │
  │  - Decided to use Redis for session caching            │
  │  - Replaced Memcached — native pub/sub wins            │
  │  - Action item: benchmark cluster vs single-node       │
  └────────────────────────────────────────────────────────┘

  Checking for duplicates...
    No similar entries found (highest score: 0.34) ✓

  Stored → abc12345
    Type: session  │  Author: norrie  │  Project: api-refactor
    Tags: [redis, caching, architecture]
```

---

## Demo: /recall and /pour

**`/recall` — find what the team already knows**

```
> /recall distributed caching

  92%  [session]   Decided to use Redis for session caching  (norrie, 2026-03-22)
  87%  [bookmark]  Redis vs Memcached: A 2026 Comparison     (alice, 2026-03-20)
  71%  [minutes]   Standup: CDN caching layer for static...  (bob,   2026-03-19)
```

**`/pour` — synthesize before a big decision**

```
> /pour how does our caching strategy work?

  Pass 1: 8 entries  →  Pass 2: +4 entries  →  Pass 3: +2 (gap-fill)
  Total: 12 unique entries

  Redis was selected for session caching [abc123] after evaluating
  Memcached [jkl445]. The CDN layer handles static assets [ghi112]...

  Knowledge Gaps:  no entries on cache warming strategy
```

---

## Demo: /bookmark, /minutes, /classify

**`/bookmark`** — save a URL in seconds

```
> /bookmark https://stripe.com/blog/payment-intents #payments #api
  Fetched → auto-summarized → stored → dedup checked ✓
```

**`/minutes`** — capture and append meeting notes

```
> /minutes                →  capture new meeting
> /minutes --update <id>  →  append to existing
> /minutes --list         →  browse all meetings
```

**`/classify`** — triage the review queue

```
> /classify --inbox
  3 entries pending review:
  [1] Low confidence (0.43) → "Stripe webhook retry logic notes"
      Suggested type: bookmark  │  Accept / Reclassify / Archive
```

---

## Ambient Intelligence

The knowledge base starts **watching the world for you**.

```
┌─────────────────────────────────────────────────────────┐
│                   The outside world                      │
│    GitHub repos  ·  RSS feeds  ·  (Slack, HN — soon)    │
└──────────────────────────┬──────────────────────────────┘
                           │  polls every N hours
                           ▼
                 ┌──────────────────────┐
                 │   Relevance Scoring  │
                 │  embedding cosine ≥  │
                 │  your interests      │
                 └──────────┬───────────┘
                            │
            ┌───────────────┼────────────────┐
            │               │                │
     below threshold   digest range     alert range
        (ignored)       → /radar          → notify
```

Three skills: **`/watch`** to add sources · **`/tune`** to calibrate · **`/radar`** to read the digest

---

## Demo: /watch and /tune

**`/watch`** — manage your feed sources

```
> /watch add https://github.com/anthropics/anthropic-cookbook #ai #tools
  Added: anthropics/anthropic-cookbook (github) — polls every 6h  trust: 0.90

> /watch list
  [1] anthropics/anthropic-cookbook   github   6h   trust: 0.90
  [2] stripe.com/blog/feed.xml        rss      6h   trust: 0.85
```

**`/tune`** — calibrate what surfaces

```
> /tune
  Current thresholds:
    relevance (digest):  0.65   →  lower = more items surface
    alert (immediate):   0.90   →  raise = fewer interruptions
    max digest items:    20

  Adjust relevance → 0.70   [saved ✓]
```

---

## Demo: /radar

```
> /radar

  Ambient digest — last 24h  (6 items above threshold 0.65)

  ★★★  [0.94]  anthropics/anthropic-cookbook
               New example: multi-agent orchestration patterns
               → matches your interests: #ai, #architecture

  ★★   [0.78]  stripe.com/blog
               Payment Intents v3: what changed in the API
               → matches: #payments, #api

  ★    [0.67]  github.com/duckdb/duckdb
               VSS extension: HNSW scan performance improvements
               → matches: #search, #storage

  ─────────────────────────────────────────────────────
  Suggested new sources based on your interests:
    → pgvector/pgvector   (GitHub)  — "adjacent to DuckDB VSS"
    → simonwillison.net   (RSS)     — "high overlap with your #ai tags"
```

---

## Under the Hood: Semantic Deduplication

Every capture runs through this before storing:

```
New entry arrives
       │
       ├──  score ≥ 0.95  →  SKIP    "Already captured — nothing to do"
       │
       ├──  score 0.80–0.95  →  MERGE   "Merge into existing entry?"
       │
       ├──  score 0.60–0.80  →  LINK    "Store + link to related entries"
       │
       └──  score < 0.60   →  CREATE  "Novel knowledge — store as new"
```

Thresholds are fully configurable in `distillery.yaml`.
Runs on every `/distill` and `/bookmark`.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Claude Code                          │
│                                                          │
│  /distill  /recall  /pour  /bookmark  /minutes           │
│  /classify  /watch  /tune  /radar                        │
│                                                          │
│  ┌───────────────────────────────────────────────────┐   │
│  │   MCP Server — 21 tools                           │   │
│  │   stdio (local)  ·  HTTP + GitHub OAuth (team)    │   │
│  └──────────────────────┬────────────────────────────┘   │
└─────────────────────────┼───────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
       DuckDB         Embedding     Classification
       + HNSW          Provider      Engine + Dedup
       index         (Jina/OpenAI)    (LLM-based)
```

Team access: `distillery-mcp --transport http` → shared server, GitHub OAuth

---

## What Makes This Different

| Traditional KB | Distillery |
|---|---|
| Separate app to switch to | Lives inside Claude Code |
| Manual categorization | LLM auto-classification |
| Keyword search | Semantic vector search |
| Flat document list | Multi-pass synthesis with citations |
| Grows noisy over time | Semantic dedup keeps it clean |
| Individual silos | Team-shared by default |
| Passive | Watches external sources for you |

---

## Status & What's Next

**Shipped:**
- ✅ **Phase 1** — 9 skills, 21 tools, DuckDB + HNSW, classification, dedup (1000+ tests)
- ✅ **Phase 3** — Ambient intelligence: feed polling, relevance scoring, `/radar /watch /tune`
- ✅ **Phase 2 infra** — HTTP transport, GitHub OAuth, MotherDuck, namespace taxonomy

**Up next — Phase 2 Team Skills:**

| Skill | What it unlocks |
|---|---|
| `/whois` | Evidence-backed expertise map: "Who knows about caching?" |
| `/investigate` | Deep domain context builder (5-phase workflow) |
| `/digest` | Team activity summaries with stale entry detection |
| `/briefing` | Team knowledge dashboard |
| `/process` | Batch classify + digest + stale detection pipeline |
| `/gh-sync` | GitHub issue/PR knowledge tracking |

**Also:** Elasticsearch backend, Prefect Horizon deploy, session capture hooks

---

## Getting Started

```bash
# Install
pip install -e .

# Configure
cp distillery.yaml.example distillery.yaml
export JINA_API_KEY=jina_...

# Add MCP to Claude Code  →  docs/mcp-setup.md

# Verify
distillery status
```

Start capturing:

```
> /distill      →  capture what you just decided
> /recall       →  find what the team already knows
> /pour         →  synthesize the full picture before a big decision
> /radar        →  see what's changed in your ecosystem overnight
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
