# /radar — Ambient Intelligence Digest

Surfaces recent feed entries, synthesizes them into a grouped digest, and optionally suggests new sources based on your interest profile.

## Usage

```
/radar                         # Default: last 7 days, up to 20 entries
/radar --days 3                # Last 3 days
/radar --limit 10              # Limit to 10 entries
/radar --suggest               # Include source suggestions
/radar --no-store              # Don't save the digest
```

**Trigger phrases:** "what's new", "show my digest", "ambient digest", "what have I missed", "feed digest"

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--days <n>` | Look back period in days | 7 |
| `--limit <n>` | Maximum entries to include | 20 |
| `--suggest` | Include new source suggestions | Off |
| `--no-store` | Don't store the digest as an entry | Stores by default |

## Output

```markdown
# Radar Digest — 2026-03-31

12 feed entries from the last 7 days.

## DuckDB
DuckDB 1.2 shipped with improved HNSW index performance and a new
JSON extension for nested document queries.

- v1.2 release includes 3x faster vector search indexing
- New JSON extension supports path-based queries
- Community contribution guide updated

## Claude Code
Two new features landed: hook-based automation and MCP server improvements.

- Session hooks enable custom automation on start/end events
- MCP server now supports parallel tool execution

## Overall Summary
This week saw performance improvements in DuckDB's vector search (directly
relevant to Distillery's storage layer) and new automation capabilities
in Claude Code.

## Suggested Sources
| URL | Type | Why |
|-----|------|-----|
| github.com/jlowin/fastmcp | github | FastMCP is a core dependency |
| simonwillison.net/atom/everything | rss | Covers DuckDB, embeddings, AI tooling |

Digest stored: m3n4o5p6
```

## How It Works

1. Retrieves recent feed entries from the knowledge base (type `feed`)
2. Groups entries by source tag or topic
3. Synthesizes 2-4 sentence summaries per group with bullet points
4. Generates a cross-group overall summary
5. If `--suggest` is enabled, calls `distillery_suggest_sources` for recommendations
6. Stores the digest as an entry (type `digest`) unless `--no-store` is specified

## Tips

- The digest is stored by default with tags `digest/radar/ambient` for future retrieval
- Source suggestions are based on your interest profile (mined from existing entries)
- Use `/watch add` to subscribe to suggested sources
- Groups are organized by source when available, falling back to topic clustering
