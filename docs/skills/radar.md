# /radar — Ambient Intelligence Digest

Surfaces recent feed entries, synthesizes them into a grouped digest, optionally suggests new sources, and optionally appends a structural view of the knowledge graph (`--structure`).

## Usage

```text
/radar                                  # Default: last 7 days, up to 35 entries
/radar --days 3                         # Last 3 days
/radar --limit 10                       # Limit to 10 entries (overrides feeds.digest.candidate_limit)
/radar --topic "build hermeticity"      # Use an explicit topic instead of mining tags
/radar --topic agentic-eval --days 14   # Topic + custom window
/radar --topic build --topic wheels     # Multiple topics; one search query each
/radar --structure                      # Append orphans + bridges + communities
/radar --suggest                        # Include source suggestions
/radar --store                          # Store the digest as an entry (default: display-only)
/radar --include-evergreen              # Surface older / first-poll backfill items
```

**Trigger phrases:** "what's new", "show my digest", "ambient digest", "what have I missed", "feed digest"

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--days <n>` | Look back period in days (overrides `feeds.digest.window_days`) | `feeds.digest.window_days` (7 if unset) |
| `--limit <n>` | Maximum entries to include (overrides `feeds.digest.candidate_limit`) | `feeds.digest.candidate_limit` (35 if unset) |
| `--topic <query>` | Use the literal string as the semantic-search query instead of mining tags. Repeatable. | Off (auto-mine) |
| `--structure` | Append a Knowledge Structure section (orphans + bridges + communities) | Off |
| `--suggest` | Include new source suggestions | Off |
| `--store` | Store the digest as an entry | Off (display-only) |
| `--include-evergreen` | Include items older than the window or flagged as first-poll backfill | Off |

The look-back window is bounded by `metadata.published_at` (the feed item's
publication time), not the ingest timestamp. First-poll backfill batches —
items pulled when a feed source is first registered — are flagged
`metadata.backfill = true` and excluded from the default candidate set so
they don't surface as "new intelligence". Use `--include-evergreen` to
override.

## Query selection

Two paths feed the candidate-search step:

**Path 1 — `--topic` override.** Each `--topic <query>` flag becomes one literal `distillery_search` call. Topics are deduplicated case-insensitively, preserving order. The 5-query namespace cap does *not* apply — every distinct user-supplied topic is honored, up to `--limit`. Tag mining is skipped entirely.

**Path 2 — Namespace-diverse interest profile (default).** The skill mines curated entries (`session`, `reference`, `bookmark`, `idea`, `note`, `minutes`) for a tag profile, then picks **5 namespace-diverse tags** rather than the raw top-5 by count. A tag's namespace is its hierarchical path with the leaf removed, capped at two segments (e.g., `domain/build/hermeticity` → `domain/build`; `tech/duckdb` → `tech`). One leader per namespace prevents a dominant cluster from crowding out distinct topics. The reference implementation lives in `distillery.feeds.radar_selection.select_namespace_diverse_tags`.

## Limit semantics and the 5-query default

The candidate budget is distributed across queries so the sum of per-query limits never exceeds `--limit`:

- Compute `Q` (the query count): up to 5 for Path 2, up to `min(distinct_topics, --limit)` for Path 1.
- Let `base = limit // Q` and `rem = limit % Q`. The first `rem` queries get `base + 1`, the rest get `base`.

With the default `--limit 35` and Q=5 (Path 2), this yields 5 queries × 7 results each → ~30 unique candidates after dedup. For small overrides like `--limit 3`, Q is reduced to 3 so the override is honored exactly (no zero-budget queries are issued). If `Q == 0` (e.g., `--limit 0` or both paths yielded an empty set), the search step short-circuits and falls back to a recent-listing query.

Configure the system-wide default via `feeds.digest.candidate_limit` in `distillery.yaml`:

```yaml
feeds:
  digest:
    window_days: 7
    candidate_limit: 35
```

Both YAML loading and the MCP `distillery_configure` tool validate this knob the same way (positive integer); `--limit` overrides it per-invocation.

## `--structure` flag — Knowledge Structure section

When `--structure` is set, an additional section is appended to the digest with three subsections:

**Orphans.** Up to 10 entries with no incoming or outgoing relations, surfaced via `distillery_list(structural=["orphans"])`. These are knowledge fragments worth reviewing for connection opportunities. Empty list renders as `No orphan entries — every entry has at least one relation.`

**Bridges.** Top-5 entries by **betweenness centrality** in the entry-relations graph, surfaced via `distillery_relations(action="metrics", metric="bridges")`. Scores are rendered to 3 decimals (e.g., `0.412`). High-centrality entries are knowledge "joints" — losing or contradicting them disconnects the graph the most.

**Communities.** Detected clusters in the entry-relations graph, surfaced via `distillery_relations(action="metrics", metric="communities")`. Communities are sorted by `total_members` (largest first). For each community, the line shows the first three member ids: `Community 1 (12 entries): <id1>, <id2>, <id3>`. If every member has `updated_at < now - 60 days`, the community is tagged `[stale]`.

Bridges and communities require the `[graph]` extra (NetworkX). If the MCP server returns `INTERNAL` with `"NetworkX not installed"`, `/radar` emits a single one-line note — `Run \`pip install distillery-mcp[graph]\` to enable bridges/communities.` — and continues without the structural metrics. The orphans subsection does not require NetworkX.

## Output

```markdown
# Radar Digest — 2026-05-07

12 feed entries from the last 7 days.

## DuckDB
DuckDB 1.2 shipped with improved HNSW index performance and a new
JSON extension for nested document queries.

- v1.2 release includes 3x faster vector search indexing
- New JSON extension supports path-based queries

## Claude Code
Two new features landed: hook-based automation and MCP server improvements.

- Session hooks enable custom automation on start/end events
- MCP server now supports parallel tool execution

## Overall Summary
This week saw performance improvements in DuckDB's vector search (directly
relevant to Distillery's storage layer) and new automation capabilities
in Claude Code.

## Knowledge Structure

### Orphans
- a1b2c3d4 — One-off reference doc on token rotation
- e5f6g7h8 — Standalone bookmark, no follow-up captured

### Bridges (top by betweenness centrality)
1. m1n2o3p4 — OAuth design session (score: 0.412)
2. q1r2s3t4 — DuckDB migration plan (score: 0.387)

### Communities (ordered by total member count; top 3 members shown per community)
- Community 1 (12 entries): m1n2o3p4, q1r2s3t4, u1v2w3x4
- Community 2 (8 entries) [stale]: y1z2a3b4, c1d2e3f4, g1h2i3j4
```

## Tips

- Digests are display-only by default; pass `--store` to persist with tags `digest/radar/ambient` for future retrieval
- `--topic` is the right flag when you want to follow a specific thread *and* you don't want the digest diluted by your dominant tag clusters
- `--structure` is most useful as an occasional pulse-check, not every run — bridges and communities don't move much day-to-day
- Source suggestions (`--suggest`) are based on the same query set used in Step 3a
- Use `/watch add` to subscribe to suggested sources
