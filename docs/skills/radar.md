# /radar — Ambient Intelligence Digest

Surfaces recent feed entries, synthesizes them into a grouped digest, and optionally suggests new sources based on your interest profile.

## Usage

```text
/radar                                  # Default: last 7 days, up to 20 entries
/radar --days 3                         # Last 3 days
/radar --limit 10                       # Limit to 10 entries
/radar --topic "build hermeticity"      # Use an explicit topic instead of mining tags
/radar --topic agentic-eval --days 14   # Topic + custom window
/radar --topic build --topic wheels     # Multiple topics; one search query each
/radar --suggest                        # Include source suggestions
/radar --store                          # Store the digest as an entry (default: display-only)
/radar --include-evergreen              # Surface older / first-poll backfill items
```

**Trigger phrases:** "what's new", "show my digest", "ambient digest", "what have I missed", "feed digest"

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--days <n>` | Look back period in days (overrides `feeds.digest.window_days`) | `feeds.digest.window_days` (7 if unset) |
| `--limit <n>` | Maximum entries to include | 20 |
| `--topic <query>` | Use the literal string as the semantic-search query instead of mining tags. Repeatable. | Off (auto-mine) |
| `--suggest` | Include new source suggestions | Off |
| `--store` | Store the digest as an entry | Off (display-only) |
| `--include-evergreen` | Include items older than the window or flagged as first-poll backfill | Off |

The look-back window is bounded by `metadata.published_at` (the feed item's
publication time), not the ingest timestamp. First-poll backfill batches —
items pulled when a feed source is first registered — are flagged
`metadata.backfill = true` and excluded from the default candidate set so
they don't surface as "new intelligence". Use `--include-evergreen` to
override.

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

1. Determines the query set:
   - If one or more `--topic` flags are supplied, the literal strings become the queries (deduplicated, preserving order).
   - Otherwise the skill mines curated entries (`session`, `reference`, `bookmark`, `idea`, `note`, `minutes`) for a tag profile, then picks **3 namespace-diverse tags** rather than the raw top-3 by count. A tag's namespace is its hierarchical path with the leaf removed, capped at two segments (e.g., `domain/build/hermeticity` → `domain/build`; `tech/duckdb` → `tech`). One leader per namespace prevents one dominant cluster from crowding out distinct topics.
2. Runs one `distillery_search` per query against feed entries, deduplicating results by entry ID.
3. Groups entries by source tag or topic.
4. Synthesizes 2-4 sentence summaries per group with bullet points.
5. Generates a cross-group overall summary.
6. If `--suggest` is enabled, the feed scorer mines the knowledge base for an interest profile and emits source recommendations inline (the former `distillery_interests` tool was folded into `/radar`'s internal pipeline).
7. Stores the digest as an entry (type `digest`) only when `--store` is specified.

## Tips

- Digests are display-only by default; pass `--store` to persist with tags `digest/radar/ambient` for future retrieval
- Source suggestions are based on your interest profile (mined from existing entries)
- Use `/watch add` to subscribe to suggested sources
- Groups are organized by source when available, falling back to topic clustering
