---
name: radar
description: "Generate an ambient intelligence digest from recent feed activity with source suggestions"
min_server_version: "0.7.0"  # distillery_relations action="metrics" (bridges/communities)
allowed-tools:
  - "mcp__*__distillery_status"
  - "mcp__*__distillery_search"
  - "mcp__*__distillery_list"
  - "mcp__*__distillery_store"
  - "mcp__*__distillery_update"
  - "mcp__*__distillery_find_similar"
  - "mcp__*__distillery_relations"
context: fork
effort: high
---

<!-- Trigger phrases: radar, /radar, what's new, show my digest, ambient digest, what have I missed, feed digest -->

# Radar — Ambient Intelligence Digest

Radar surfaces recent feed entries, synthesizes them into a grouped digest, and suggests new sources to watch. Pass `--structure` to also append a Knowledge Structure section (orphans, bridges, communities) computed from the entry-relations graph.

## When to Use

- Digest of recent feed items (`/radar`)
- See what has been captured from monitored sources recently
- New source suggestions (`/radar --suggest`)
- "show my digest", "what's new from feeds", "what have I missed"

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Parse Arguments

| Flag | Description |
|------|-------------|
| `--days N` | Look back N days for recent feed entries (overrides `feeds.digest.window_days`, default 7) |
| `--limit N` | Maximum number of feed entries to include (overrides `feeds.digest.candidate_limit`, default 35) |
| `--project <name>` | Scope feed entries to a specific project |
| `--topic <query>` | Use the literal string as a semantic-search query instead of mining tags. Repeatable; each `--topic` is one query. When set, use Path 1 in Step 3a and skip Path 2 (tag mining). |
| `--suggest` | Include source suggestions at end of digest |
| `--structure` | Append a Knowledge Structure section (orphans + bridges + communities). Default: off |
| `--store` | Store digest as a knowledge entry (default: display-only) |
| `--include-evergreen` | Include older / first-poll backfill items in the candidate set (default: excluded) |

**`--topic` examples:**

```text
/radar --topic "build hermeticity"
/radar --topic agentic-eval --days 14
/radar --topic "build hermeticity" --topic "wheels caching"
```

Multiple `--topic` flags may be passed; each becomes a separate
`distillery_search` query. Deduplicate the literal query strings (case- and
whitespace-insensitive) before issuing.

The look-back window is bounded by `metadata.published_at` (the feed item's
publication timestamp), not `created_at`. Items with no `published_at` are
included unless they are flagged `metadata.backfill = true` (first-poll
backfill batches), in which case they are hidden by default. Pass
`--include-evergreen` to override and surface them.

### Step 3: Retrieve Recent Feed Entries

Use tag-driven semantic search to surface the most relevant feed entries, not just the newest.

**3a. Determine the query set:**

Two paths — explicit override or auto-derived from interests.

*Path 1 — `--topic` override (skip tag mining):*

If one or more `--topic <query>` flags were supplied, use the supplied
strings directly as the query set. Deduplicate (case-insensitive, trim
whitespace), preserving the user's order. Skip the rest of Step 3a and
proceed to 3b. Report: `Using <N> user-supplied topic(s): <comma-separated>.`

*Path 2 — Namespace-diverse interest profile (default):*

Build an interest profile that excludes feed-ingested content. Make a single
call that aggregates tag counts across all curated types at once:

`distillery_list(group_by="tags", entry_type=["session", "reference", "bookmark", "idea", "minutes"])`

The grouped counts come back already merged across the curated types in this
one call (the `entry_type` list is OR-matched), so use the returned group
counts directly as the combined count map — no client-side merging needed.

Then select **5 namespace-diverse tags**, *not* the raw top-5 by count. A
tag's namespace is its hierarchical path with the leaf segment removed,
capped at two segments (e.g., `domain/build/hermeticity` → namespace
`domain/build`; `tech/duckdb` → namespace `tech`; single-segment `release`
namespaces to itself). The selection rule:

1. Group all tags by namespace.
2. Pick the highest-count tag in each namespace (alphabetical tie-break) —
   the *namespace leader*.
3. Rank namespaces by *aggregate population* (sum of counts across all
   tags in the namespace), then by leader count, then alphabetically.
4. Return the namespace leaders of the top 5 namespaces.

This guarantees the query set spans up to five distinct conceptual
clusters. The reference implementation lives in
`distillery.feeds.radar_selection.select_namespace_diverse_tags` — call it
mentally as `select_namespace_diverse_tags(merged_counts, top_n=5)`.

Convert each chosen tag path to a natural-language query by taking the leaf
segment and replacing hyphens with spaces (e.g.,
`domain/build/hermeticity` → query `"hermeticity"`). De-duplicate the
normalized query strings (case- and whitespace-insensitive), preserving the
highest-ranked occurrence; if a collision drops a tag, substitute the
next-ranked namespace leader from the merged counts so the query set still
spans up to 5 distinct queries.

**3b. Search by interests (primary path):**

Compute `published_after = (now - <days>).isoformat()` where `<days>` is the
`--days` flag if provided, otherwise the configured `feeds.digest.window_days`
(default 7). Resolve `<limit>` from the `--limit` flag if provided, otherwise
from the configured `feeds.digest.candidate_limit` (default 35). Compute `Q`
(the number of queries to issue):

- If explicit `--topic` flags were provided (Path 1): `Q = min(number_of_distinct_explicit_topics, <limit>)` — honor every user-supplied topic up to the limit; do *not* apply the 5-query cap.
- Otherwise (Path 2, namespace-derived): `Q = min(number_of_distinct_namespace_queries, 5, <limit>)` — namespace-derived queries are capped at 5.

If `Q == 0` (no queries — e.g. `<limit>` is 0 or both paths produced an
empty set), short-circuit: skip Step 3b entirely and proceed to Step 3c
(fallback). Otherwise distribute the `<limit>` budget exactly so the sum
of per-query limits never exceeds `<limit>`: let `base = <limit> // Q`
and `rem = <limit> % Q`, then assign `base + 1` to the first `rem`
queries and `base` to the rest (skipping any zero-budget queries). For
each query, call:

`distillery_search(query="<query>", entry_type="feed", limit=<per-query budget>, published_after=<iso>, include_evergreen=<bool>)`

With the default `<limit>` of 35 and Q=5, this yields 5 queries of 7 results
each → 35 raw → ~30 unique candidates after dedup. For small limits (e.g.,
`--limit 3` with 5 queries), Q=3 and only 3 queries are issued so the
override is honored exactly. Pass `include_evergreen=true` only when the user
supplied `--include-evergreen`. If `--project` was specified, also pass
`project=<name>`.

Deduplicate results across queries by entry ID, keeping the highest similarity score.

Report: `Retrieved <total> entries via interest-based search (<N> queries, window=<days>d).`

**3c. Fallback (if interest tags unavailable):**

This fallback applies only to Path 2 (auto-derived interest profile). If
`--topic` was supplied, Step 3b always has at least one query and 3c is
skipped.

If the curated-type `group_by="tags"` call returns no tags, fall back to:

`distillery_list(entry_type="feed", limit=<limit>, output_mode="summary", published_after=<iso>, include_evergreen=<bool>, project=<name?>)`

Apply the same project-scoping rule as Step 3b: only include `project=<name>`
when `--project` was supplied, so the fallback never synthesizes entries from
other projects when the user explicitly scoped the request.

Report: `Retrieved <total> entries via recent listing (fallback, window=<days>d).`

If the curated-type `group_by="tags"` call itself errors, treat that as an MCP error per the Rules section below — report and stop.

**3d. Empty results:**

If no feed entries are found by either path, display:

```
No feed entries found in the last <N> days.

Suggestions:
- Trigger feed polling via POST to /hooks/poll (or use /setup to configure scheduled polling)
- Add sources with /watch add <url>
- Check that feed sources are configured in distillery.yaml
```

Stop here if no entries exist.

### Step 4: Synthesize Digest

You (the executing Claude instance) produce the synthesis — do not dump raw entries.

**Grouping:** Group entries by source tag if present (e.g., `source/github`, `source/rss`), or by topic otherwise.

**Per group:**
- Heading with the group name
- 2-4 sentence summary of key themes
- Bullet list of notable items (title/snippet + source URL if available)

**Cross-group summary:** 2-3 sentences highlighting the most important signals across all sources.

### Step 5: Suggest Sources

When `--suggest` is specified, use the query set from Step 3a — namespace-diverse interest tags from Path 2, or the user-supplied `--topic` strings from Path 1 — to suggest new sources. Based on those topics, recommend 3–5 relevant RSS feeds or GitHub repos the user might want to add via `/watch add <url>`. Omit this section silently if Step 3a produced no queries or if `--suggest` was not specified.

### Step 6: Knowledge Structure (if --structure specified)

When `--structure` is specified, append a "Knowledge Structure" section to the digest. Compose it from three subsections in this order. Skip the entire step silently if `--structure` was not specified.

**6a. Orphans:**

Call `distillery_list(structural=["orphans"], limit=10)`. If `--project` was specified, also pass `project=<name>`. The envelope returns matching entries and a `structural_filter` field for confirmation. Render up to 10 orphan titles as a short bullet list (entry id + first line of content or title). If the list is empty, render: `No orphan entries — every entry has at least one relation.`

**6b. Bridges:**

Call `distillery_relations(action="metrics", metric="bridges", scope="global", limit=5)`. If `--project` was specified, also pass `project=<name>`.

If the call returns an `INTERNAL` error whose message contains `"NetworkX not installed"`, emit a single one-line note in the section: `Run \`pip install distillery-mcp[graph]\` to enable bridges/communities.` Then skip subsection 6c and continue to Step 7 (the same error in 6c would be redundant).

On success, render the top-5 bridging entries as a numbered list with their betweenness score formatted to 3 decimals (e.g. `0.412`). Resolve each id to a short title using its data already retrieved during digest synthesis if possible; otherwise show the id. If `results` is empty, render `No bridges found (graph too small or disconnected).`

**6c. Communities:**

Call `distillery_relations(action="metrics", metric="communities", scope="global", limit=5)`. If `--project` was specified, also pass `project=<name>`.

If 6b succeeded but this call returns the same `"NetworkX not installed"` `INTERNAL` error (e.g. a transient install state), emit the one-line `pip install distillery-mcp[graph]` note from 6b and continue to Step 7.

On success, sort the `results` array by each community's `total_members`
field in descending order (community with the most members first). For
each community in that sorted order, render the first three ids from its
`members` array (positional, not ranked by any other metric). Output
format: `Community <n> (<total_members> entries): <id1>, <id2>, <id3>`,
where `<n>` is the rank in the sorted list. Document this ordering
inline in the rendered output via the heading.

**Optional stale flag:** For each community, if `updated_at` is available on every member and EVERY member has `updated_at < now - 60 days`, mark the community with a `[stale]` tag in its line. Skip the stale check silently if `updated_at` is not available without an extra fetch.

**6d. Graph health:**

Call `distillery_relations(action="metrics", metric="health", scope="global", limit=1)`. If `--project` was specified, also pass `project=<name>`.

If 6b already emitted the `pip install distillery-mcp[graph]` note (NetworkX missing), skip this subsection. On success, render a one-line summary at the **top** of the Knowledge Structure section (above Orphans) so the reader sees the overall shape before the detail:

`Graph health: orphan rate <orphan_rate as %>, <edge_count> edges over <graph_node_count>/<total_entries> nodes, mean degree <mean_degree>, <connected_component_count> components (largest <largest_component_fraction as %>).`

Frame the goal inline: a falling `orphan_rate` and a `largest_component_fraction` approaching 1.0 indicate a consolidating, traversable graph.

### Step 7: Check for Duplicates (if --store specified)

If `--store` was specified, check for duplicate digests before storing.

Call `distillery_find_similar(content="<digest summary>", dedup_action=True)`. Handle by `action` field:

**`"create"`:** No similar entries. Proceed to Step 8.

**`"skip"`:** Near-exact duplicate. Show similarity table and offer: (1) Store anyway, (2) Skip.

**`"merge"`:** Very similar entry exists. Show similarity table and offer: (1) Store anyway, (2) Merge with existing, (3) Skip.

For merge: combine new digest with the most similar entry's content, call `distillery_update` with the entry ID and merged content, confirm and stop.

**`"link"`:** Related but distinct. Show similarity table, note new entry will be linked. Ask to proceed or skip. If proceeding, include `"related_entries": ["<id1>", ...]` in metadata at Step 8.

```
Similar entries found:

| Entry ID | Similarity | Preview |
|----------|-----------|---------|
| <id>     | <score%>  | <content_preview> |
```

On skip in any case: "Skipped. No new entry was stored." and stop.

### Step 8: Store Digest

If `--store` was specified, store the digest. Determine author & project per CONVENTIONS.md.

Call `distillery_store(content="<full digest markdown>", entry_type="digest", author="<author>", project="<project>", tags=["digest", "radar", "ambient"], metadata={"period_start": "<YYYY-MM-DD>", "period_end": "<YYYY-MM-DD>"})`. Record the returned `entry_id`.

On MCP errors, see CONVENTIONS.md error handling — display and stop.

### Step 9: Confirm

Display the digest. If `--store` was specified, append:

```
[digest] Stored: <entry_id>
Project: <project> | Author: <author>
Summary: <first 200 chars of digest>...
Tags: digest, radar, ambient
```

Omit the stored block if `--store` was not specified.

## Output Format

```
# Radar Digest — <YYYY-MM-DD>

<N> feed entries from the last <days> days.

---

## <Group Name>
<2-4 sentence summary>
- **<item title>** — <brief description> ([source](<url>))

---

## Overall Summary
<2-3 sentence cross-group synthesis>

---

## Suggested Sources

| # | URL | Type | Why |
|---|-----|------|-----|
| 1 | <url> | <type> | <rationale> |

To add a source: /watch add <url> [--type rss|github]

---

## Knowledge Structure

### Orphans
- <id> — <title or first line>
- ...

### Bridges (top by betweenness centrality)
1. <id> — <title> (score: 0.412)
2. ...

### Communities (ordered by total member count; top 3 members shown per community)
- Community 1 (12 entries): <id1>, <id2>, <id3>
- Community 2 (8 entries) [stale]: <id1>, <id2>, <id3>
- ...

> Note (only when nx is missing): Run `pip install distillery-mcp[graph]` to enable bridges/communities.

---

[digest] Stored: <entry_id>
Project: <project> | Author: <author>
Summary: <first 200 chars>...
Tags: digest, radar, ambient
```

## Rules

- NEVER use Bash, Python, or any tool not listed in allowed-tools
- If an MCP tool call fails, report the error to the user and STOP. Do not attempt workarounds.
- Default lookback is `feeds.digest.window_days` (7 days); default candidate limit is `feeds.digest.candidate_limit` (35 entries) — respect `--days` and `--limit` overrides
- Filter on `published_after` (publication time), not `date_from` (ingest time) — older items polled today are not new intelligence
- First-poll backfill items (`metadata.backfill = true`) are excluded by default; surface them with `--include-evergreen`
- Group entries by source tag when available; fall back to topic grouping
- Display digest by default; store only with `--store` flag
- Always include `digest`, `radar`, `ambient` tags when storing
- Always use `entry_type="digest"` for store calls
- Metadata must include `period_start` and `period_end` as ISO 8601 dates
- Follow shared dedup pattern from CONVENTIONS.md (create/skip/merge/link outcomes)
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — report errors and stop
- Omit Suggested Sources section entirely if no results or error
- Knowledge Structure section is appended only when `--structure` is set; default is off
- When `distillery_relations(action="metrics")` returns an `INTERNAL` error containing `"NetworkX not installed"`, treat it as a graceful degradation (not a hard error) — emit the one-line `pip install distillery-mcp[graph]` note and continue. Treat any other relations error per CONVENTIONS.md error handling
- Bridge scores are rendered to 3 decimals; communities are ordered by total member count and show top-3 member ids each
