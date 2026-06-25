---
name: investigate
description: "Compile deep context on a topic by combining semantic search with relationship traversal across 4 retrieval phases"
allowed-tools:
  - "mcp__*__distillery_status"
  - "mcp__*__distillery_search"
  - "mcp__*__distillery_get"
  - "mcp__*__distillery_relations"
  - "mcp__*__distillery_find_similar"
  - "mcp__*__distillery_list"
context: fork
effort: high
---

<!-- Trigger phrases: investigate, /investigate, deep context, what do we know about, trace connections, follow relationships, /investigate <topic>, /investigate --entry <id> -->

# Investigate — Deep Context Builder

Investigate compiles comprehensive context on a topic by executing a 4-phase retrieval: seed search, relationship expansion (with hidden-connection gap fill), tag expansion, and gap filling. It combines semantic search with explicit relationship traversal to surface context that keyword search alone misses.

<!-- Recent changes: Phases 1 and 2 are fused into a single distillery_search(expand_graph=true, expand_hops=2, output_mode="full") call — server-side BFS returns the seeds plus their 2-hop graph neighbours (each with provenance/depth/parent_id/relation_type and inline content) in one round-trip, replacing the prior 1 search + up-to-20 traverse + N get fan-out (#651). Phase 2b now issues a single batched distillery_find_similar(source_entry_ids=[...]) call (top ≤20 seeds) that reuses each seed's stored embedding (no re-embed, no budget spend) and runs all seeds server-side in one round-trip, returning results_by_seed — replacing the prior per-seed fan-out in bounded parallel batches (~4); the 502-under-concurrency concern is moot now that it is one call. Relationship traversal is skipped when the seed set has no relations (sparse-graph short-circuit). -->


## When to Use

- Deep research on a topic spanning multiple entries and relationships (`/investigate <topic>`)
- Starting from a specific entry and following its connections (`/investigate --entry <uuid>`)
- "What do we know about X", "trace connections for X", "deep context on X"
- Understanding how entries relate to each other across sessions, issues, and meeting notes
- Discovering knowledge gaps on a topic before a decision or discussion

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Determine Author & Project

Determine author and project per CONVENTIONS.md (Author & Project Resolution). Although `/investigate` is display-only and does not store entries, project is needed to scope searches via `--project`, and author is used for project resolution context.

- **Author**: `git config user.name` → `DISTILLERY_AUTHOR` env var → ask user. Cache for the conversation.
- **Project**: `--project` flag if provided → `basename $(git rev-parse --show-toplevel)` → ask user. Cache for the conversation.

If already resolved earlier in the conversation, reuse the cached values.

### Step 3: Parse Arguments

If no arguments provided, ask:

> What topic would you like to investigate? (e.g., "authentication architecture", "caching decisions") Or provide a specific entry ID with `--entry <uuid>`.

Extract from arguments:
- **Topic**: main query string (everything except flags)
- **--entry `<uuid>`**: if present, start Phase 1 from this specific entry instead of a search
- **--project `<name>`**: if present, scope Phase 1 and Phase 4 searches to that project

### Step 4: 4-Phase Retrieval

Track a **result set** keyed by entry ID throughout all phases. Each entry is counted once — the phase that first discovered it is recorded. Track relationship edges separately.

---

**Phase 1+2 — Seed + Graph Expansion (one call):**

If no `--entry` was provided, run a single graph-expanded search. This fuses the
seed search and the 2-hop relationship traversal **server-side**, returning the
seeds plus their graph neighbours — with inline content — in ONE round-trip:

```python
distillery_search(
    query="<topic>",
    expand_graph=True,
    expand_hops=2,
    limit=20,
    output_mode="full",
    project="<project if specified>",
)
```

The envelope is `{results: [...], count, graph_expansion: {seed_count, expanded_count}}`.
Each result carries:

- `provenance`: `"search"` — a seed hit (Phase 1) — or `"graph"` — reached via a
  relationship (Phase 2).
- for `provenance="graph"`: `depth` (1 or 2), `parent_id`, and `relation_type`
  (the edge type linking it to its parent).
- `entry`: the full entry (`output_mode="full"`), so no per-node `get` is needed.

Add every result to the result set. Tag `provenance="search"` entries as Phase 1
(seeds) and `provenance="graph"` entries as Phase 2 (record `depth`, `parent_id`,
`relation_type`). For each graph entry, record the edge
`<parent_id> —[<relation_type>]→ <entry_id>` for the Relationship Map.

Report: `Phase 1-2 (Seed + Graph): <seed_count> seeds + <expanded_count> via relationships (hops=2, one call).`

If `seed_count` is 0, display:

```text
No entries found for "<topic>".

Suggestions:
- Capture relevant knowledge with /distill
- Sync GitHub issues with /gh-sync
- Save references with /bookmark
```

and stop.

**Sparse-graph short-circuit:** when `expanded_count` is 0 the seeds have no
relations (the knowledge graph is sparse for this topic). Note it in the report;
the Relationship Map will be empty and similarity (Phase 2b) is the only
expansion lever.

**`--entry <uuid>` variant:** when starting from a specific entry instead of a
topic, load it and traverse its relationships directly — the entry is the sole
seed, so this is one traverse, not a fan-out:

```python
distillery_get(entry_id="<uuid>")                                      # seed entry
distillery_relations(action="traverse", entry_id="<uuid>", hops=2, direction="both")
```

Add the seed (Phase 1) and each traversed node (Phase 2), recording `depth` and
each `edges` entry as `<from_id> —[<relation_type>]→ <to_id>`. Hydrate any node
not already loaded with `distillery_get(entry_id="<id>")`. If `distillery_get`
returns not found for the `--entry` uuid, report the error and stop.

---

**Phase 2b — Hidden Connections (gap fill via similarity):**

For the **seeds** (Phase 1 `provenance="search"` entries), surface entries that are semantically similar to each seed but are NOT already linked to it via any relation (i.e., absent from `entry_relations` in either direction). Issue **ONE batched call** for up to the top 20 seeds by Phase 1 relevance score:

```python
distillery_find_similar(
    source_entry_ids=[<top ≤20 seed ids by Phase-1 relevance>],
    exclude_linked=True,
    threshold=0.7,
    limit=5,
)
```

Batch mode reuses each seed's **already-stored embedding** — no re-embedding round-trip and no embedding-budget spend — and runs all seeds in a single server-side read, returning everything in **one round-trip**. Cap at the top 20 seeds; skip the rest. When the sparse-graph short-circuit fired (Phase 1-2 `expanded_count` = 0), Phase 2b is the primary expansion lever — still run it.

The response is `results_by_seed`, a map keyed by each seed id: `{ "<seed_id>": { results: [...], count, excluded_count } }`, plus `seed_count` and `threshold`. Each seed always self-excludes; with `exclude_linked=True`, linked entries are filtered out per seed. A seed with no stored embedding maps to an empty `results` list (not an error). Iterate `results_by_seed`: the hits are unlinked-but-semantically-related candidates.

Add each returned entry id (not already in the result set) tagged as discovered in Phase 2b ("potentially related"). Do NOT add these to the Relationship Map — they have no recorded edge. Cite them in the Context Summary and the Sources table with a `potentially related` marker so the user knows the connection is inferred from embeddings, not stored as a relation.

Report: `Phase 2b (Hidden Connections): <N> potentially related entries across <S> seeds.`

If `results_by_seed` yields zero entries for every seed, note this in the Phase 2b report and continue.

---

**Phase 3 — Tag Expansion:**

Extract all tags from entries currently in the result set. Identify unique namespace prefixes (e.g., tags like `domain/authentication`, `domain/oauth` → prefix `domain`). Call once and reuse the result across all namespaces:

```python
distillery_list(group_by="tags")
```

From the returned tag groups, rank tags by count. Filter to those matching the namespace prefixes extracted from the result set. Convert top-ranked tag segments to search queries (replace hyphens with spaces: `domain/oauth` → `"oauth"`). Run up to 3 `distillery_search` calls from these ranked tag-derived queries:

```python
distillery_search(query="<tag-derived query>", limit=10, project="<project if specified>")
```

Add any entries not already in the result set to it, tagged as discovered in Phase 3.

Report: `Phase 3 (Tags): <N> new entries from tag expansion across <M> namespaces.`

If no tags are found in the result set, skip Phase 3 searches and note: `Phase 3 (Tags): No tags found in seed results — skipped.`

---

**Phase 4 — Gap Fill:**

Analyze the content of all entries currently in the result set. Identify:
- People mentioned by name but not yet represented as `person` entries
- Projects or repositories referenced but not yet in the result set
- Key topics, decisions, or concepts mentioned but sparsely represented (fewer than 2 entries)

For each identified gap (up to 3), run a targeted search:

```python
distillery_search(query="<gap query>", limit=10, project="<project if specified>")
```

Add any entries not already in the result set, tagged as discovered in Phase 4.

Report: `Phase 4 (Gap Fill): <N> new entries from <G> targeted gap searches.`

---

**Summary line:**

```text
Investigated "<topic>": <total_N> entries across <phases_with_results> phases, <K> relationship edges traversed (hops=2), <P> potentially related via similarity.
```

### Step 5: Synthesize Output

You (the executing Claude instance) produce the synthesis. Do not dump raw entries.

**a. Context Summary (always include):**

A 2–4 paragraph narrative weaving findings together. Use `[Entry <short-id>]` inline citations (short-id = first 8 chars of UUID). For Phase 2b candidates, use `[Entry <short-id>, potentially related]` to flag that the connection is inferred from embedding similarity rather than a stored relation. Describe what the knowledge base knows about the topic, how entries connect, and what the overall picture reveals.

Example: `The team evaluated DuckDB as the storage backend in early 2026 [Entry 550e8400], driven by requirements for embedded analytical queries [Entry 7c9e6679]. A sync with GitHub issues confirms the decision was tracked formally [Entry a1b2c3d4]. A SQLite benchmark from a different project [Entry b9c0d1e2, potentially related] surfaces similar trade-offs but is not formally linked.`

**b. Relationship Map (omit if no relations found):**

Text-based representation of connections between entries:

```text
Entry 550e8400 [session] "DuckDB evaluation"
  —[citation]→ Entry 7c9e6679 [reference] "Analytical query requirements"
  —[link]→ Entry a1b2c3d4 [github] "Issue #42: storage backend decision"

Entry 7c9e6679 [reference] "Analytical query requirements"
  —[citation]→ Entry 550e8400 [session] "DuckDB evaluation"
```

List each entry that has at least one relation. Show relation type and a short label (first 40 chars of content or `title` metadata field if present). Omit entries with no relations from this section.

**c. Timeline (omit if all entries same day or fewer than 3 entries):**

Chronological list of entries, ordered by `created_at`:

| Date | Short ID | Type | Author | Summary |
|------|----------|------|--------|---------|
| 2026-01-15 | 550e8400 | [session] | Alice | DuckDB evaluation and benchmark results |
| 2026-01-20 | 7c9e6679 | [reference] | Bob | Analytical query requirements doc |

**d. Key People (omit if all entries have the same single author):**

Authors and mentioned people:
- For each unique author in the result set: name, number of entries, entry types
- People mentioned in content by name but not as authors: note they appear in content but may not have captured knowledge directly

**e. Knowledge Gaps (omit if none identified):**

From Phase 4 gap analysis:
- Topics referenced but with sparse coverage (fewer than 2 entries)
- People mentioned but without dedicated `person` entries
- Decisions mentioned but without corresponding `minutes` or `session` entries

Suggest follow-up actions using appropriate skills (e.g., `/distill`, `/gh-sync`, `/minutes`).

### Step 6: Source Attribution

Table of all entries in the result set:

| Phase | Short ID | Type | Author | Date | Relation Edges | Preview |
|-------|----------|------|--------|------|---------------|---------|
| 1 | 550e8400 | [session] | Alice Smith | 2026-01-15 | 2 | We decided to use DuckDB for... |
| 2 | 7c9e6679 | [reference] | Bob Jones | 2026-01-20 | 1 | Analytical query requirements... |
| 2b | b9c0d1e2 | [session] | Carol Lim | 2026-02-03 | 0 (potentially related) | SQLite vs DuckDB benchmark... |
| 3 | a1b2c3d4 | [github] | — | 2026-01-22 | 1 | Issue #42: storage backend deci... |

- **Phase**: discovery phase (`1`, `2`, `2b`, `3`, `4`)
- **Short ID**: first 8 chars of UUID
- **Relation Edges**: number of relation edges this entry participates in. For Phase 2b entries this is `0 (potentially related)` — they are similarity-only candidates with no stored relation.
- **Preview**: first 40 chars of content, or `title` metadata field if present

## Output Format

Heading `# Investigate: <Topic>`, then the summary line, then sections: Context Summary, Relationship Map, Timeline, Key People, Knowledge Gaps, Sources — each as described above. Omit empty sections.

```text
# Investigate: <topic or "Entry <short-id>">

Investigated "<topic>": <N> entries across <phases> phases, <K> relationship edges traversed (hops=2), <P> potentially related via similarity.

---

## Context Summary

<2–4 paragraph narrative with [Entry <short-id>] citations>

---

## Relationship Map

<text-based relationship graph — omit if no relations>

---

## Timeline

<chronological table — omit if all same day or fewer than 3 entries>

---

## Key People

<author and mention list — omit if single author>

---

## Knowledge Gaps

<gap analysis with suggestions — omit if none>

---

## Sources

| Phase | Short ID | Type | Author | Date | Relation Edges | Preview |
|-------|----------|------|--------|------|---------------|---------|
| ...   | ...      | ...  | ...    | ...  | ...           | ...     |
```

## Rules

- NEVER use Bash, Python, or any tool not listed in allowed-tools
- If an MCP tool call fails, report the error to the user and STOP. Do not attempt workarounds.
- Always use `[Entry <short-id>]` citation format (short-id = first 8 chars of UUID)
- Deduplicate the result set by entry ID across all phases — each entry counted once
- Record which phase first discovered each entry
- Phases 1-2 use one `distillery_search(expand_graph=true, expand_hops=2, output_mode="full")` call (server-side BFS); the `--entry` variant uses `distillery_get` + one `distillery_relations(action="traverse", hops=2, direction="both")`. Do not recurse into graph-expanded entries.
- Phase 2b runs ONE batched `distillery_find_similar(source_entry_ids=[<top ≤20 seeds>], exclude_linked=true, threshold=0.7, limit=5)` call (capped to the top 20 seeds); batch mode reuses each seed's stored embedding (no re-embed, no budget) and returns all seeds in one round-trip as `results_by_seed`
- Phase 2b candidates are tagged `potentially related` — never include them in the Relationship Map (they have no stored edge); cite them with `[Entry <short-id>, potentially related]` in the Context Summary
- Loop limits: up to 3 `distillery_search` calls in Phase 3, up to 3 targeted searches in Phase 4
- Track relation edges separately from the result set entry count
- Omit sections with no content — never display empty sections
- If `--entry <uuid>` is provided and `distillery_get` returns not found, report the error and stop
- Apply `--project` filter to all `distillery_search` calls in Phase 1 and Phase 4 when provided
- `distillery_relations` returning empty `nodes`/`edges` for an entry is not an error — record 0 edges and continue
- `distillery_find_similar` batch mode returning an empty `results` list for a seed (after `exclude_linked` filtering, or because the seed has no stored embedding) is not an error — record 0 candidates for that seed and continue
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — report errors and stop
- Display-only — this skill never stores output
