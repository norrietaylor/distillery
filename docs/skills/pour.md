# /pour — Multi-Entry Synthesis

Performs multi-pass retrieval and synthesizes findings into a structured narrative with inline citations, contradiction flags, and knowledge gap analysis. Optionally augments retrieval with 1-hop graph expansion via `--graph`.

## Usage

```text
/pour how does our auth system work?
/pour --project billing payment processing
/pour --graph DuckDB migration plan
```

**Trigger phrases:** "synthesize", "what's the full picture on", "deep dive into"

## When to Use

- Building a comprehensive understanding of a topic from multiple entries
- Preparing for a design review or decision by gathering all related knowledge
- Identifying contradictions or gaps in the team's knowledge
- Pulling in *structurally related* context (linked but not semantically matched) via `--graph`

## How It Works

1. **Curated-content search** — limit=10 over `session`/`bookmark`/`minutes`/`reference`/`idea`/`digest` so high-value entries aren't drowned out by feed volume
2. **Broad search** — limit=20 across all entry types
3. **Follow-up searches** — up to 3 additional queries for related concepts found in the earlier passes
4. **Tag expansion** — up to 3 additional queries derived from the namespace-prefixed tag vocabulary in the seed results
5. **Gap-filling** — up to 2 targeted queries for referenced but missing topics
6. **Synthesis** — combines all unique entries into a structured narrative with inline citations

If fewer than 2 entries are found, falls back to a standard `/recall`-style display.

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--project <name>` | Scope synthesis to a specific project | — |
| `--graph` | Enable 1-hop graph-expanded retrieval — every search call passes `expand_graph=true, expand_hops=1` | Off |

## `--graph` flag

`--graph` is **off by default** and must be opted into explicitly. When set, every `distillery_search` call across Pass 1a, 1b, Pass 2 (concept and tag-derived), Pass 3, and Step 7 refinement is invoked with `expand_graph=true, expand_hops=1`. Each search seed is augmented with its 1-hop structural neighbours from `entry_relations`, with a 0.5-per-hop score discount. Each result carries `provenance: "search" | "graph"`, `depth`, and `parent_id`.

In synthesis, graph-only entries are labelled `[Entry abc12345, structurally related]` in the prose, and the **Sources** table gains a `Provenance` column showing `search` or `graph (via <parent_short_id>)`. The retrieval audit trail is therefore explicit — readers can tell which entries matched the query directly and which were pulled in because they're linked to a match. If the same entry appears via both provenances across passes, `search` wins (the stronger signal).

The retrieval summary line gains a graph-expansion total when `--graph` is set:

```text
Retrieved 18 unique entries across 4 search passes (graph expansion: 12 seed → 18 after 1-hop neighbours).
```

Without `--graph`, Pour's behaviour is unchanged from prior releases — no provenance column, no "structurally related" labels, no expansion totals.

## Output

```markdown
# Pour: Authentication System

## Summary
The authentication system uses GitHub OAuth as an identity gate [Entry a1b2c3d4],
with tokens verified via the /user endpoint [Entry e5f6g7h8]. A downstream
session-store decision [Entry m1n2o3p4, structurally related] is linked to
the OAuth entry via `entry_relations` and explains why tokens are stored
locally rather than on the server.

## Timeline
- 2026-03-10: Initial OAuth implementation decided [Entry a1b2c3d4]
- 2026-03-15: FastMCP GitHubProvider integrated [Entry i9j0k1l2]

## Key Decisions
- Use `user` scope only — no repo access [Entry a1b2c3d4]
- Tokens stored locally, never on server [Entry e5f6g7h8]

## Sources
| # | Entry ID | Type      | Date       | Similarity | Provenance        |
|---|----------|-----------|------------|------------|-------------------|
| 1 | a1b2c3d4 | session   | 2026-03-10 | 95%        | search            |
| 2 | e5f6g7h8 | bookmark  | 2026-03-12 | 88%        | search            |
| 3 | m1n2o3p4 | reference | 2026-03-14 | 71%        | graph (via a1b2c3d4) |
```

### Citations

Every claim is traced back to a source using `[Entry <short-id>]` format (first 8 characters of the UUID). Empty sections are omitted. Graph-only entries carry the `structurally related` qualifier inline.

### Interactive Refinement

After the initial synthesis, you can ask follow-up questions (up to 5 rounds). Each refinement is appended as an addendum. When `--graph` is set, refinement searches also pass `expand_graph=true, expand_hops=1`.

## Tips

- `/pour` is best for broad topics — use `/recall` for quick lookups
- `--graph` shines when the topic has well-curated relations (e.g., a feature with linked sessions, GitHub PRs, and reference docs); on a sparse graph it adds little
- Graph-only context is supporting, not primary — treat the search-matched entries as load-bearing claims and graph-only entries as "why this matters" or "what follows"
- If only one author contributed, the output includes a perspective bias note
- Entries are deduplicated by ID across all search passes
