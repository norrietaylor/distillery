<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/distillery-logo-dark-512.png" width="180">
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/distillery-logo-512.png" width="180">
    <img alt="Distillery" src="docs/assets/distillery-logo-512.png" width="180">
  </picture>
</p>

<h1 align="center">Distillery</h1>

<p align="center">
  <strong>A team-accessible Second Brain powered by Claude Code</strong>
  <br>
  Capture, classify, connect, and surface team knowledge through conversational commands.
</p>

<p align="center">
  <a href="#skills">Skills</a> &middot;
  <a href="#quick-start">Quick Start</a> &middot;
  <a href="#architecture">Architecture</a> &middot;
  <a href="docs/ROADMAP.md">Roadmap</a> &middot;
  <a href="docs/mcp-setup.md">MCP Setup</a> &middot;
  <a href="https://norrietaylor.github.io/distillery/">Slides</a>
</p>

---

## What is Distillery?

Distillery is a team knowledge base accessed through Claude Code skills. It refines raw information from working sessions, meetings, bookmarks, and conversations into concentrated, searchable knowledge — stored as vector embeddings in a local database and retrieved through natural language.

Inspired by Tiago Forte's **Building a Second Brain** methodology (CODE: Capture, Organize, Distill, Express), Distillery maps the "Distill" step — the highest-value transformation from noise to signal — into a tool the whole team can use.

## Skills

Distillery provides 6 Claude Code slash commands:

| Skill | Purpose | Example |
|-------|---------|---------|
| `/distill` | Capture session knowledge with dedup detection | `/distill "We decided to use DuckDB for local storage"` |
| `/recall` | Semantic search with provenance | `/recall distributed caching strategies` |
| `/pour` | Multi-entry synthesis with citations | `/pour how does our auth system work?` |
| `/bookmark` | Store URLs with auto-generated summaries | `/bookmark https://example.com/article #caching` |
| `/minutes` | Meeting notes with append updates | `/minutes --update standup-2026-03-22` |
| `/classify` | Classify entries and triage review queue | `/classify --inbox` |

### How `/pour` works

Pour performs multi-pass retrieval to build a complete picture:

1. **Broad search** — initial semantic search across the knowledge base
2. **Follow-up** — searches for related concepts found in pass 1
3. **Gap-filling** — targeted queries for referenced but missing topics

The output is a structured synthesis with **Summary**, **Timeline**, **Key Decisions**, **Contradictions**, and **Knowledge Gaps** — all with inline citations linking back to source entries.

## Quick Start

### Prerequisites

- Python 3.11+
- An embedding API key ([Jina AI](https://jina.ai) or OpenAI)

### Install

```bash
git clone https://github.com/distillery/distillery.git
cd distillery
pip install -e .
```

### Configure

Create `distillery.yaml`:

```yaml
storage:
  backend: duckdb
  database_path: ~/.distillery/distillery.db

embedding:
  provider: jina
  model: jina-embeddings-v3
  dimensions: 1024
  api_key_env: JINA_API_KEY

classification:
  confidence_threshold: 0.6
  dedup_skip_threshold: 0.95
  dedup_merge_threshold: 0.80
  dedup_link_threshold: 0.60
```

Set your API key:

```bash
export JINA_API_KEY=jina_...
```

### Connect to Claude Code

Add to your Claude Code MCP settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "distillery": {
      "command": "python",
      "args": ["-m", "distillery.mcp"],
      "env": {
        "JINA_API_KEY": "your-jina-api-key",
        "DISTILLERY_CONFIG": "/path/to/distillery.yaml"
      }
    }
  }
}
```

Restart Claude Code. Verify with:

```
distillery_status
```

See [docs/mcp-setup.md](docs/mcp-setup.md) for detailed setup instructions.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Claude Code                     │
│  ┌──────┐ ┌──────┐ ┌────┐ ┌────────┐ ┌───────┐ │
│  │/distill│/recall│/pour│/bookmark│/minutes│ │
│  └───┬───┘ └──┬───┘ └─┬──┘ └───┬────┘ └──┬────┘ │
│      │        │       │        │         │       │
│  ┌───┴────────┴───────┴────────┴─────────┴───┐   │
│  │          MCP Server (stdio)                │   │
│  │  17 tools: store, get, update, search,      │   │
│  │  find_similar, list, status, classify,      │   │
│  │  review_queue, resolve_review, check_dedup, │   │
│  │  check_conflicts, metrics, quality, stale,  │   │
│  │  tag_tree, type_schemas                     │   │
│  └──────────────┬────────────────────────────┘   │
└─────────────────┼────────────────────────────────┘
                  │
    ┌─────────────┼──────────────┐
    │             │              │
┌───┴───┐  ┌─────┴─────┐  ┌────┴────────┐
│DuckDB │  │ Embedding  │  │Classification│
│+ VSS  │  │ Provider   │  │   Engine     │
│(HNSW) │  │(Jina/OpenAI)│  │  + Dedup    │
└───────┘  └───────────┘  └─────────────┘
```

### Key design decisions

- **Skills are SKILL.md files**, not Python code — portable, version-controlled, team-shareable
- **MCP server is the sole runtime interface** — all storage access goes through the protocol
- **Storage abstraction** via `DistilleryStore` protocol — enables future migration to Elasticsearch without rewriting skills
- **Configurable embedding providers** — swap between Jina v3, OpenAI, or a zero-vector stub for testing
- **Semantic deduplication** — prevents knowledge base pollution with configurable skip/merge/link/create thresholds
- **Classification with confidence scoring** — LLM-based type assignment with team review queue for low-confidence results

## Project Structure

```
distillery/
├── .claude/skills/          # Claude Code skill definitions
│   ├── distill/SKILL.md
│   ├── recall/SKILL.md
│   ├── pour/SKILL.md
│   ├── bookmark/SKILL.md
│   ├── minutes/SKILL.md
│   ├── classify/SKILL.md
│   └── CONVENTIONS.md
├── src/distillery/
│   ├── models.py            # Entry, SearchResult, enums
│   ├── config.py            # YAML config loading
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
│   └── mcp/
│       └── server.py        # MCP server (17 tools, FastMCP 2.x/3.x)
├── tests/                   # 600+ tests
├── docs/
│   ├── mcp-setup.md
│   ├── ROADMAP.md
│   └── specs/               # Specifications
├── distillery.yaml.example
└── pyproject.toml
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy --strict src/distillery/

# Lint
ruff check src/ tests/
```

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
