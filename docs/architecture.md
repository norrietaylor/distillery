# Architecture

Distillery is built as a 4-layer system where skills (SKILL.md files) drive all user interaction, the MCP server mediates all storage access, and backends are swappable through typed Protocol interfaces.

<div markdown="0">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 560" font-family="Inter, -apple-system, system-ui, sans-serif" style="max-width: 760px; width: 100%; height: auto;">
  <defs>
    <style>
      .d-bg { fill: #0f0f0f; }
      .d-layer { fill: #1a1a1a; }
      .d-label { fill: #888; font-size: 11px; font-weight: 500; letter-spacing: 0.5px; text-transform: uppercase; }
      .d-pill { fill: #242424; }
      .d-pill-text { fill: #e8e8e8; font-size: 12px; font-weight: 500; }
      .d-amber-bg { fill: #BA7517; }
      .d-amber-text { fill: #EF9F27; }
      .d-white { fill: #fff; font-size: 15px; font-weight: 600; }
      .d-white-sub { fill: rgba(255,255,255,0.7); font-size: 11px; }
      .d-box { fill: #242424; stroke: #BA7517; stroke-width: 1.5; }
      .d-box-title { fill: #EF9F27; font-size: 13px; font-weight: 600; }
      .d-box-sub { fill: #888; font-size: 10px; }
      .d-line { stroke: #444; stroke-width: 2; }
      .d-auth { fill: #242424; stroke: #4ade80; stroke-width: 1.5; }
      .d-auth-title { fill: #4ade80; font-size: 13px; font-weight: 600; }
      .d-feed { fill: #242424; stroke: #60a5fa; stroke-width: 1.5; }
      .d-feed-title { fill: #60a5fa; font-size: 13px; font-weight: 600; }
      .d-type-text { fill: #e8e8e8; font-size: 10px; }
      .d-tag-text { fill: #EF9F27; font-size: 10px; }
    </style>
  </defs>

  <!-- Background -->
  <rect class="d-bg" width="760" height="560" rx="16"/>

  <!-- Layer 1: Skills -->
  <rect class="d-layer" x="30" y="16" width="700" height="72" rx="12"/>
  <text class="d-label" x="50" y="36">10 Claude Code Skills</text>
  <rect class="d-pill" x="50" y="44" width="62" height="26" rx="6"/><text class="d-pill-text" x="81" y="61" text-anchor="middle">/distill</text>
  <rect class="d-pill" x="120" y="44" width="56" height="26" rx="6"/><text class="d-pill-text" x="148" y="61" text-anchor="middle">/recall</text>
  <rect class="d-pill" x="184" y="44" width="50" height="26" rx="6"/><text class="d-pill-text" x="209" y="61" text-anchor="middle">/pour</text>
  <rect class="d-pill" x="242" y="44" width="74" height="26" rx="6"/><text class="d-pill-text" x="279" y="61" text-anchor="middle">/bookmark</text>
  <rect class="d-pill" x="324" y="44" width="68" height="26" rx="6"/><text class="d-pill-text" x="358" y="61" text-anchor="middle">/minutes</text>
  <rect class="d-pill" x="400" y="44" width="66" height="26" rx="6"/><text class="d-pill-text" x="433" y="61" text-anchor="middle">/classify</text>
  <rect class="d-pill" x="474" y="44" width="56" height="26" rx="6"/><text class="d-pill-text" x="502" y="61" text-anchor="middle">/watch</text>
  <rect class="d-pill" x="538" y="44" width="54" height="26" rx="6"/><text class="d-pill-text" x="565" y="61" text-anchor="middle">/radar</text>
  <rect class="d-pill" x="600" y="44" width="50" height="26" rx="6"/><text class="d-pill-text" x="625" y="61" text-anchor="middle">/tune</text>
  <rect class="d-pill" x="658" y="44" width="54" height="26" rx="6"/><text class="d-pill-text" x="685" y="61" text-anchor="middle">/setup</text>

  <!-- Connector -->
  <line class="d-line" x1="380" y1="88" x2="380" y2="104"/>

  <!-- Layer 2: MCP Server -->
  <rect class="d-amber-bg" x="30" y="104" width="700" height="52" rx="10"/>
  <text class="d-white" x="380" y="128" text-anchor="middle">MCP Server</text>
  <text class="d-white-sub" x="380" y="144" text-anchor="middle">FastMCP 2.x/3.x  ·  stdio + streamable-HTTP  ·  22 tools  ·  @server.tool decorators</text>

  <!-- Connector: MCP to Auth + Protocols -->
  <line class="d-line" x1="380" y1="156" x2="380" y2="168"/>
  <line class="d-line" x1="190" y1="168" x2="570" y2="168"/>
  <line class="d-line" x1="190" y1="168" x2="190" y2="180"/>
  <line class="d-line" x1="380" y1="168" x2="380" y2="180"/>
  <line class="d-line" x1="570" y1="168" x2="570" y2="180"/>

  <!-- Layer 3a: Auth -->
  <rect class="d-auth" x="30" y="180" width="220" height="64" rx="8"/>
  <text class="d-auth-title" x="140" y="202" text-anchor="middle">GitHub OAuth</text>
  <text class="d-box-sub" x="140" y="218" text-anchor="middle">OrgRestrictedGitHubProvider</text>
  <text class="d-box-sub" x="140" y="232" text-anchor="middle">Middleware · Budget · Rate limits</text>

  <!-- Layer 3b: Core Protocols -->
  <rect class="d-box" x="268" y="180" width="224" height="64" rx="8"/>
  <text class="d-box-title" x="380" y="202" text-anchor="middle">Core Protocols</text>
  <text class="d-box-sub" x="380" y="218" text-anchor="middle">DistilleryStore · EmbeddingProvider</text>
  <text class="d-box-sub" x="380" y="232" text-anchor="middle">Typed Protocol interfaces (async)</text>

  <!-- Layer 3c: Feeds -->
  <rect class="d-feed" x="510" y="180" width="220" height="64" rx="8"/>
  <text class="d-feed-title" x="620" y="202" text-anchor="middle">Feed System</text>
  <text class="d-box-sub" x="620" y="218" text-anchor="middle">GitHub · RSS/Atom adapters</text>
  <text class="d-box-sub" x="620" y="232" text-anchor="middle">Poller · Scorer · Interests</text>

  <!-- Connector: Protocols to Backends -->
  <line class="d-line" x1="380" y1="244" x2="380" y2="256"/>
  <line class="d-line" x1="140" y1="256" x2="620" y2="256"/>
  <line class="d-line" x1="140" y1="256" x2="140" y2="268"/>
  <line class="d-line" x1="285" y1="256" x2="285" y2="268"/>
  <line class="d-line" x1="475" y1="256" x2="475" y2="268"/>
  <line class="d-line" x1="620" y1="256" x2="620" y2="268"/>

  <!-- Layer 4: Backends -->
  <rect class="d-box" x="30" y="268" width="210" height="72" rx="8"/>
  <text class="d-box-title" x="135" y="290" text-anchor="middle">DuckDB + VSS</text>
  <text class="d-box-sub" x="135" y="306" text-anchor="middle">HNSW cosine similarity</text>
  <text class="d-box-sub" x="135" y="320" text-anchor="middle">Vector search + SQL storage</text>

  <rect class="d-box" x="254" y="268" width="152" height="72" rx="8"/>
  <text class="d-box-title" x="330" y="290" text-anchor="middle">Embedding</text>
  <text class="d-box-sub" x="330" y="306" text-anchor="middle">Jina v3 / OpenAI</text>
  <text class="d-box-sub" x="330" y="320" text-anchor="middle">Configurable provider</text>

  <rect class="d-box" x="420" y="268" width="160" height="72" rx="8"/>
  <text class="d-box-title" x="500" y="290" text-anchor="middle">Classification</text>
  <text class="d-box-sub" x="500" y="306" text-anchor="middle">LLM engine + Dedup</text>
  <text class="d-box-sub" x="500" y="320" text-anchor="middle">Conflicts + Tag validation</text>

  <rect class="d-box" x="594" y="268" width="136" height="72" rx="8"/>
  <text class="d-box-title" x="662" y="290" text-anchor="middle">Config</text>
  <text class="d-box-sub" x="662" y="306" text-anchor="middle">distillery.yaml</text>
  <text class="d-box-sub" x="662" y="320" text-anchor="middle">Security · Validation</text>

  <!-- Entry Types -->
  <text class="d-label" x="50" y="370">12 Entry Types</text>
  <rect class="d-pill" x="50" y="380" width="56" height="22" rx="5"/><text class="d-type-text" x="78" y="395" text-anchor="middle">session</text>
  <rect class="d-pill" x="114" y="380" width="66" height="22" rx="5"/><text class="d-type-text" x="147" y="395" text-anchor="middle">bookmark</text>
  <rect class="d-pill" x="188" y="380" width="58" height="22" rx="5"/><text class="d-type-text" x="217" y="395" text-anchor="middle">minutes</text>
  <rect class="d-pill" x="254" y="380" width="60" height="22" rx="5"/><text class="d-type-text" x="284" y="395" text-anchor="middle">meeting</text>
  <rect class="d-pill" x="322" y="380" width="66" height="22" rx="5"/><text class="d-type-text" x="355" y="395" text-anchor="middle">reference</text>
  <rect class="d-pill" x="396" y="380" width="38" height="22" rx="5"/><text class="d-type-text" x="415" y="395" text-anchor="middle">idea</text>
  <rect class="d-pill" x="442" y="380" width="42" height="22" rx="5"/><text class="d-type-text" x="463" y="395" text-anchor="middle">inbox</text>
  <rect class="d-pill" x="492" y="380" width="52" height="22" rx="5"/><text class="d-type-text" x="518" y="395" text-anchor="middle">person</text>
  <rect class="d-pill" x="552" y="380" width="52" height="22" rx="5"/><text class="d-type-text" x="578" y="395" text-anchor="middle">project</text>
  <rect class="d-pill" x="612" y="380" width="48" height="22" rx="5"/><text class="d-type-text" x="636" y="395" text-anchor="middle">digest</text>
  <rect class="d-pill" x="668" y="380" width="48" height="22" rx="5"/><text class="d-type-text" x="692" y="395" text-anchor="middle">github</text>
  <rect class="d-pill" x="50" y="408" width="40" height="22" rx="5"/><text class="d-type-text" x="70" y="423" text-anchor="middle">feed</text>

  <!-- Dedup Thresholds -->
  <text class="d-label" x="50" y="456">Dedup Thresholds</text>
  <rect class="d-pill" x="50" y="466" width="140" height="22" rx="5"/><text class="d-type-text" x="120" y="481" text-anchor="middle">skip >= 0.95</text>
  <rect class="d-pill" x="200" y="466" width="140" height="22" rx="5"/><text class="d-type-text" x="270" y="481" text-anchor="middle">merge >= 0.80</text>
  <rect class="d-pill" x="350" y="466" width="140" height="22" rx="5"/><text class="d-type-text" x="420" y="481" text-anchor="middle">link >= 0.60</text>
  <rect class="d-pill" x="500" y="466" width="140" height="22" rx="5"/><text class="d-type-text" x="570" y="481" text-anchor="middle">unique &lt; 0.60</text>

  <!-- Tag Namespaces -->
  <text class="d-label" x="50" y="516">Hierarchical Tags</text>
  <text class="d-tag-text" x="50" y="536">project/distillery/sessions  ·  domain/storage  ·  source/bookmark/duckdb-org  ·  team/distillery</text>
</svg>
</div>

## Layers

| Layer | What it does | Key files |
|-------|-------------|-----------|
| **Skills** | 10 SKILL.md files — portable, version-controlled slash commands. Not Python code. | `.claude-plugin/skills/*/SKILL.md` |
| **MCP Server** | 22 tools exposed over stdio (local) or streamable-HTTP (team). Built on FastMCP 2.x/3.x with `@server.tool` decorators. | `src/distillery/mcp/server.py` |
| **Auth** | GitHub OAuth with org-restricted access. Middleware handles logging, rate limiting, security headers, budget tracking. | `src/distillery/mcp/auth.py`, `middleware.py`, `budget.py` |
| **Core Protocols** | Typed `Protocol` interfaces (structural subtyping, not ABCs). All storage operations are async. | `src/distillery/store/protocol.py`, `embedding/protocol.py` |
| **Feeds** | GitHub events and RSS/Atom polling. Relevance scoring via embeddings. Interest extraction for source suggestions. | `src/distillery/feeds/` |
| **Backends** | DuckDB + VSS (HNSW cosine similarity), Jina v3 / OpenAI embeddings, LLM classification with dedup + conflict detection. | `src/distillery/store/duckdb.py`, `embedding/`, `classification/` |

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
