# /investigate — Deep Context Builder

Compiles comprehensive context on a topic by executing a 4-phase retrieval: seed search, relationship expansion (with hidden-connection gap fill), tag expansion, and gap filling. Combines semantic search with explicit relationship traversal — and similarity-based hidden-link discovery — to surface context that keyword search alone misses.

## Usage

```text
/investigate authentication flow
/investigate --entry <uuid>
/investigate DuckDB migration --project distillery
```

**Trigger phrases:** "investigate", "deep context", "what do we know about", "trace connections", "follow relationships"

## When to Use

- Deep research on a topic spanning multiple entries and relationships
- Starting from a specific entry and following its connections
- Understanding how entries relate across sessions, issues, and meeting notes
- Discovering knowledge gaps before a decision or discussion

## What It Does

### Phase 1: Seed Search

Performs a semantic search for the topic (or loads a single entry when `--entry <uuid>` is supplied), collecting the initial set of relevant entries.

### Phase 2: Multi-Hop Relationship Expansion

For each seed entry, issues a single `distillery_relations(action="traverse", hops=2, direction="both")` call. The server-side BFS returns nodes reachable within two hops (depth 0 = the seed, depth 1 = directly linked, depth 2 = reached via one intermediate) along with the edges between them. One round-trip per seed replaces the previous per-relation `get` fan-out, so deeper subgraphs surface in fewer calls.

### Phase 2b: Hidden Connections (similarity-based gap fill)

For each seed entry (capped at the top 20 seeds by Phase 1 relevance), calls `distillery_find_similar(source_entry_id=<seed>, exclude_linked=true, threshold=0.7, limit=5)`. The MCP server filters out entries that already share a stored relation with the seed in either direction, so what comes back is unlinked-but-semantically-related — the entries the graph alone would miss. These appear in the synthesis tagged `potentially related` and are *never* added to the Relationship Map (they have no recorded edge).

### Phase 3: Tag Expansion

Extracts unique tag-namespace prefixes from the result set and runs up to 3 follow-up searches derived from the most-populated namespaces.

### Phase 4: Gap Filling

Identifies people, projects, or topics that are mentioned but sparsely represented (fewer than 2 entries) and runs up to 3 targeted searches to fill the gaps.

## Output Format

```text
# Investigate: authentication flow

Investigated "authentication flow": 14 entries across 4 phases, 9 relationship edges traversed (hops=2), 3 potentially related via similarity.

## Context Summary
The team adopted GitHub OAuth as an identity gate [Entry a1b2c3d4],
verified via the /user endpoint [Entry e5f6g7h8]. A SQLite-backed
session store from a sibling project [Entry b9c0d1e2, potentially
related] surfaces similar token-lifetime trade-offs but is not
formally linked to the auth subsystem.

## Relationship Map
Entry a1b2c3d4 [session] "OAuth identity gate"
  —[citation]→ Entry e5f6g7h8 [reference] "Token verification"
  —[link]→ Entry i9j0k1l2 [github] "Issue #42: scope decision"

## Knowledge Gaps
- Token refresh behavior (mentioned but no dedicated entry)
- Multi-team RBAC design (referenced once, no decision recorded)
```

## Options

| Flag | Description |
|------|-------------|
| `--entry <uuid>` | Start from a specific entry instead of a topic search |
| `--project <name>` | Scope Phase 1 and Phase 4 searches to a specific project |

## Tips

- More thorough than `/recall` — follows relationships **and** surfaces hidden similarity-only links
- The `potentially related` marker tells you the connection was inferred from embeddings, not from a stored relation — useful as a prompt to capture the link via `distillery_relations(action="add")`
- Phase 2b is capped at the top 20 seeds to keep cost bounded; results beyond that are skipped silently
- Use before important decisions to ensure you have full context
- The gap analysis (Phase 4) helps identify what to capture next with `/distill`
- Works well with `/gh-sync` entries — follow issue chains and PR discussions
