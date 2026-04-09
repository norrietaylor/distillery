# /investigate — Deep Context Builder

Compiles comprehensive context on a topic by executing a 4-phase retrieval: seed search, relationship expansion, tag expansion, and gap filling. Combines semantic search with explicit relationship traversal to surface context that keyword search alone misses.

## Usage

```text
/investigate authentication flow
/investigate --entry <uuid>
/investigate DuckDB migration --depth 3
```

**Trigger phrases:** "investigate", "deep context", "what do we know about", "trace connections", "follow relationships"

## When to Use

- Deep research on a topic spanning multiple entries and relationships
- Starting from a specific entry and following its connections
- Understanding how entries relate across sessions, issues, and meeting notes
- Discovering knowledge gaps before a decision or discussion

## What It Does

### Phase 1: Seed Search
Performs semantic search for the topic, collecting the initial set of relevant entries.

### Phase 2: Relationship Expansion
Follows explicit relations (corrections, references, parent/child) from seed entries to discover connected knowledge.

### Phase 3: Tag Expansion
Uses shared tags to find entries in the same topic space that weren't surfaced by semantic search.

### Phase 4: Gap Filling
Identifies areas where knowledge is thin and reports gaps — topics mentioned but not well-covered.

## Output Format

```text
Investigation: authentication flow
Sources: 12 entries across 4 phases

[Structured narrative organized by theme]

Relationships:
  entry-A --corrects--> entry-B
  entry-C --references--> entry-D

Knowledge Gaps:
  - OAuth refresh token handling (mentioned but no dedicated entry)
  - Rate limiting strategy (referenced in 2 entries, no decision recorded)
```

## Options

| Flag | Description |
|------|-------------|
| `--entry UUID` | Start from a specific entry instead of a topic search |
| `--depth N` | Maximum relationship traversal depth (default: 2) |
| `--project NAME` | Scope to a specific project |

## Tips

- More thorough than `/recall` — follows relationships and identifies gaps
- Use before important decisions to ensure you have full context
- The gap analysis helps identify what to capture next with `/distill`
- Works well with `/gh-sync` entries — follow issue chains and PR discussions
