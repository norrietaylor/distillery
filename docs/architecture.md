# Architecture

Distillery is built as a 4-layer system where skills (SKILL.md files) drive all user interaction, the MCP server mediates all storage access, and backends are swappable through typed Protocol interfaces.

<div markdown="0">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 420" font-family="Inter, -apple-system, system-ui, sans-serif" style="max-width: 720px; width: 100%; height: auto;">
  <defs>
    <style>
      .layer-bg { fill: #1a1a1a; }
      .layer-label { fill: #888; font-size: 11px; font-weight: 500; letter-spacing: 0.5px; text-transform: uppercase; }
      .skill { fill: #242424; }
      .skill-text { fill: #e8e8e8; font-size: 13px; font-weight: 500; }
      .mcp-bg { fill: #BA7517; }
      .mcp-title { fill: #fff; font-size: 16px; font-weight: 600; }
      .mcp-sub { fill: rgba(255,255,255,0.7); font-size: 11px; }
      .backend-bg { fill: #242424; stroke: #BA7517; stroke-width: 1.5; }
      .backend-title { fill: #EF9F27; font-size: 14px; font-weight: 600; }
      .backend-sub { fill: #888; font-size: 11px; }
      .connector { stroke: #444; stroke-width: 2; }
    </style>
  </defs>
  <rect width="720" height="420" fill="#0f0f0f" rx="16"/>
  <rect class="layer-bg" x="40" y="20" width="640" height="160" rx="12"/>
  <text class="layer-label" x="60" y="44">Claude Code</text>
  <rect class="skill" x="60" y="54" width="72" height="30" rx="6"/><text class="skill-text" x="96" y="74" text-anchor="middle">/distill</text>
  <rect class="skill" x="142" y="54" width="68" height="30" rx="6"/><text class="skill-text" x="176" y="74" text-anchor="middle">/recall</text>
  <rect class="skill" x="220" y="54" width="60" height="30" rx="6"/><text class="skill-text" x="250" y="74" text-anchor="middle">/pour</text>
  <rect class="skill" x="290" y="54" width="84" height="30" rx="6"/><text class="skill-text" x="332" y="74" text-anchor="middle">/bookmark</text>
  <rect class="skill" x="384" y="54" width="78" height="30" rx="6"/><text class="skill-text" x="423" y="74" text-anchor="middle">/minutes</text>
  <rect class="skill" x="472" y="54" width="74" height="30" rx="6"/><text class="skill-text" x="509" y="74" text-anchor="middle">/classify</text>
  <rect class="skill" x="556" y="54" width="62" height="30" rx="6"/><text class="skill-text" x="587" y="74" text-anchor="middle">/watch</text>
  <rect class="skill" x="60" y="88" width="62" height="30" rx="6"/><text class="skill-text" x="91" y="108" text-anchor="middle" font-size="11">/radar</text>
  <rect class="skill" x="132" y="88" width="54" height="30" rx="6"/><text class="skill-text" x="159" y="108" text-anchor="middle" font-size="11">/tune</text>
  <rect class="mcp-bg" x="60" y="100" width="600" height="64" rx="8"/>
  <text class="mcp-title" x="360" y="128" text-anchor="middle">MCP Server</text>
  <text class="mcp-sub" x="360" y="148" text-anchor="middle">FastMCP 2.x/3.x  ·  stdio + HTTP  ·  22 tools</text>
  <line class="connector" x1="360" y1="180" x2="360" y2="195"/>
  <line class="connector" x1="200" y1="195" x2="520" y2="195"/>
  <line class="connector" x1="200" y1="195" x2="200" y2="210"/>
  <line class="connector" x1="360" y1="195" x2="360" y2="210"/>
  <line class="connector" x1="520" y1="195" x2="520" y2="210"/>
  <rect class="backend-bg" x="60" y="210" width="200" height="80" rx="8"/>
  <text class="backend-title" x="160" y="238" text-anchor="middle">DuckDB + VSS</text>
  <text class="backend-sub" x="160" y="258" text-anchor="middle">HNSW cosine similarity</text>
  <text class="backend-sub" x="160" y="274" text-anchor="middle">Vector search + SQL</text>
  <rect class="backend-bg" x="280" y="210" width="160" height="80" rx="8"/>
  <text class="backend-title" x="360" y="238" text-anchor="middle">Embedding</text>
  <text class="backend-sub" x="360" y="258" text-anchor="middle">Jina v3 / OpenAI</text>
  <text class="backend-sub" x="360" y="274" text-anchor="middle">Configurable provider</text>
  <rect class="backend-bg" x="460" y="210" width="220" height="80" rx="8"/>
  <text class="backend-title" x="570" y="238" text-anchor="middle">Classification</text>
  <text class="backend-sub" x="570" y="258" text-anchor="middle">LLM engine + Dedup</text>
  <text class="backend-sub" x="570" y="274" text-anchor="middle">Conflicts + Tag validation</text>
  <text class="layer-label" x="60" y="324">11 Entry Types</text>
  <rect class="skill" x="60" y="334" width="66" height="24" rx="6"/><text class="backend-sub" x="93" y="350" text-anchor="middle" fill="#e8e8e8">session</text>
  <rect class="skill" x="134" y="334" width="74" height="24" rx="6"/><text class="backend-sub" x="171" y="350" text-anchor="middle" fill="#e8e8e8">bookmark</text>
  <rect class="skill" x="216" y="334" width="66" height="24" rx="6"/><text class="backend-sub" x="249" y="350" text-anchor="middle" fill="#e8e8e8">minutes</text>
  <rect class="skill" x="290" y="334" width="72" height="24" rx="6"/><text class="backend-sub" x="326" y="350" text-anchor="middle" fill="#e8e8e8">reference</text>
  <rect class="skill" x="370" y="334" width="46" height="24" rx="6"/><text class="backend-sub" x="393" y="350" text-anchor="middle" fill="#e8e8e8">idea</text>
  <rect class="skill" x="424" y="334" width="60" height="24" rx="6"/><text class="backend-sub" x="454" y="350" text-anchor="middle" fill="#e8e8e8">person</text>
  <rect class="skill" x="492" y="334" width="62" height="24" rx="6"/><text class="backend-sub" x="523" y="350" text-anchor="middle" fill="#e8e8e8">project</text>
  <rect class="skill" x="562" y="334" width="56" height="24" rx="6"/><text class="backend-sub" x="590" y="350" text-anchor="middle" fill="#e8e8e8">github</text>
  <text class="layer-label" x="60" y="386">Hierarchical Tags</text>
  <text class="backend-sub" x="60" y="404" fill="#EF9F27">project/distillery/sessions  ·  domain/storage  ·  source/bookmark/duckdb-org  ·  team/distillery</text>
</svg>
</div>

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

```text
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
