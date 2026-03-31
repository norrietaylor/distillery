# Architecture

Distillery is built as a 4-layer system where skills (SKILL.md files) drive all user interaction, the MCP server mediates all storage access, and backends are swappable through typed Protocol interfaces.

<picture>
  <img alt="Distillery Architecture" src="assets/architecture.svg" style="max-width: 100%; height: auto;" width="720">
</picture>

## Layers

```text
Skills (.claude-plugin/skills/<name>/SKILL.md)  →  slash commands users invoke
    ↓
MCP Server (src/distillery/mcp/server.py)  →  22 tools over stdio or HTTP (FastMCP 2.x)
    ↓
Core Protocols (store/protocol.py, embedding/protocol.py)  →  typed Protocol interfaces
    ↓
Backends (store/duckdb.py, embedding/jina.py, embedding/openai.py)  →  DuckDB + VSS, embedding APIs
```

| Layer | What it does | Key files |
|-------|-------------|-----------|
| **Skills** | 10 SKILL.md files — portable, version-controlled slash commands. Not Python code. | `.claude-plugin/skills/*/SKILL.md` |
| **MCP Server** | 22 tools exposed over stdio (local) or HTTP (team). Built on FastMCP 2.x with `@server.tool` decorators. | `src/distillery/mcp/server.py` |
| **Core Protocols** | Typed `Protocol` interfaces (structural subtyping, not ABCs). All storage operations are async. | `src/distillery/store/protocol.py`, `src/distillery/embedding/protocol.py` |
| **Backends** | DuckDB with VSS extension for vector search (HNSW index, cosine similarity). Jina v3 and OpenAI embedding adapters. | `src/distillery/store/duckdb.py`, `src/distillery/embedding/jina.py` |

## Key Design Decisions

**Skills are SKILL.md files, not Python code.** They are portable, version-controlled, and team-shareable. Claude Code loads the markdown and follows the instructions — no compilation or import required.

**MCP server is the sole runtime interface.** All storage access goes through the protocol, over stdio (local) or HTTP (team). Skills never access the database directly.

**Storage abstraction via `DistilleryStore` protocol.** Enables future migration to Elasticsearch without rewriting skills or the MCP server.

**Configurable embedding providers.** Swap between Jina v3, OpenAI, or a zero-vector stub for testing via `distillery.yaml`.

**Semantic deduplication.** Prevents knowledge base pollution with configurable thresholds:

| Threshold | Default | Action |
|-----------|---------|--------|
| Skip | 0.95 | Near-duplicate — don't store |
| Merge | 0.80 | Similar enough to combine |
| Link | 0.60 | Related — store with cross-reference |
| Below 0.60 | — | Unique — store normally |

**Classification with confidence scoring.** LLM-based type assignment with a team review queue for low-confidence results (below the configurable `confidence_threshold`, default: 60%).

## Core Data Model

The `Entry` dataclass (`src/distillery/models.py`) is the fundamental unit of knowledge:

| Field | Type | Description |
|-------|------|-------------|
| `id` | str (UUID4) | Unique identifier |
| `content` | str | The knowledge content |
| `entry_type` | EntryType | session, bookmark, minutes, meeting, reference, idea, inbox, person, project, digest, github, feed |
| `source` | EntrySource | claude_code, manual, import |
| `status` | EntryStatus | active, pending_review, archived |
| `tags` | list[str] | Hierarchical tags (`project/distillery/decisions`) |
| `metadata` | dict | Type-specific fields (validated per entry type) |
| `version` | int | Incremented on updates |
| `author` | str | Who created the entry |
| `project` | str \| None | Which project context |
| `created_at` | datetime | Creation timestamp |
| `updated_at` | datetime | Last modification |

## Project Structure

```
distillery/
├── .claude-plugin/skills/   # Claude Code skill definitions (loaded via plugin)
│   ├── distill/SKILL.md
│   ├── recall/SKILL.md
│   ├── pour/SKILL.md
│   ├── bookmark/SKILL.md
│   ├── minutes/SKILL.md
│   ├── classify/SKILL.md
│   ├── watch/SKILL.md
│   ├── radar/SKILL.md
│   ├── tune/SKILL.md
│   ├── setup/SKILL.md
│   └── CONVENTIONS.md
├── src/distillery/
│   ├── models.py            # Entry, SearchResult, enums
│   ├── config.py            # YAML config loading
│   ├── security.py          # Input sanitization and content validation
│   ├── store/
│   │   ├── protocol.py      # DistilleryStore protocol
│   │   └── duckdb.py        # DuckDB + VSS backend
│   ├── embedding/
│   │   ├── protocol.py      # EmbeddingProvider protocol
│   │   ├── jina.py          # Jina v3 adapter
│   │   └── openai.py        # OpenAI adapter
│   ├── classification/
│   │   ├── models.py        # ClassificationResult, DeduplicationResult
│   │   ├── engine.py        # ClassificationEngine
│   │   └── dedup.py         # DeduplicationChecker
│   ├── mcp/
│   │   ├── server.py        # MCP server (22 tools, FastMCP 2.x)
│   │   ├── auth.py          # GitHub OAuth via FastMCP GitHubProvider
│   │   ├── middleware.py     # Request logging, rate limiting, security headers
│   │   ├── budget.py        # Embedding API budget tracking
│   │   └── __main__.py      # CLI: --transport stdio|http
│   └── feeds/
│       ├── github.py        # GitHub event adapter
│       ├── rss.py           # RSS/Atom feed adapter
│       ├── scorer.py        # Embedding-based relevance scorer
│       ├── poller.py        # Background feed poller
│       └── interests.py     # Interest extractor for source suggestions
├── tests/                   # 1100+ tests (unit + integration)
├── deploy/
│   ├── fly/                 # Fly.io deployment (persistent DuckDB)
│   └── prefect/             # Prefect Horizon deployment (MotherDuck)
└── docs/                    # This documentation site
```

## Feed Architecture

The ambient intelligence system monitors external sources and scores relevance:

1. **Source registry** — managed via `/watch`, stored in DuckDB
2. **Feed adapters** — GitHub REST API events, RSS/Atom feeds
3. **Relevance scoring** — embedding-based cosine similarity against user interest profile
4. **Interest extraction** — mines existing entries for tags, domains, repos, expertise
5. **Digest generation** — `/radar` synthesizes recent feed entries into grouped summaries
