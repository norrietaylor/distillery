---
title: "Walking the Graph: Distillery 0.5.0"
published: false
description: "What 0.5.0 ships — multi-hop traversal, hidden-link discovery, structural insights — and how a regression gate kept the graph launch honest."
tags: [claudecode, mcp, devtools, release, knowledgegraph]
canonical_url: https://norrietaylor.github.io/distillery/blog/distillery-0-5-0-graph/
---

# Walking the Graph: Distillery 0.5.0

!!! note "Release summary"
    Distillery 0.5.0 shipped May 7, 2026. It's the release where the
    knowledge graph stops being plumbing and becomes a primary retrieval
    surface — multi-hop traversal in `/investigate`, opt-in graph-expanded
    synthesis in `/pour --graph`, and structural insights (orphans /
    bridges / communities) in `/radar --structure`. Graph features are
    default-off. The release body lives on the
    [GitHub release page](https://github.com/norrietaylor/distillery/releases/tag/v0.5.0).

[The 0.4.0 post](distillery-0-4-0-full-proof.md) was about turning the MCP tool surface into a public contract. This post is about what we built on top of that contract once the contract was load-bearing.

The single sentence is: **Distillery learned to walk the graph.**

The longer version is that we'd been carrying an `entry_relations` table since 0.3.0 — every entry could be linked to every other entry with a typed edge — but only one skill (`/investigate` Phase 2) actually traversed it, and only one hop deep, and only after a per-relation `distillery_get` fan-out that punished any seed with more than a handful of neighbours. The graph existed; nothing read it well. 0.5.0 fixes that, end to end, in eight PRs and a regression gate.

## What we shipped

### Hidden-connections discovery in `/investigate`

`/investigate` already retrieved seeds, walked their direct relations, expanded by tag, and probed for gaps. 0.5.0 adds two changes that, together, change the character of what comes back.

The first is multi-hop traversal. Phase 2 now issues a single `distillery_relations(action="traverse", hops=2, direction="both")` per seed, and the MCP server runs the BFS internally and returns the full subgraph — nodes (with depth), edges, and counts — in one envelope. Two-hop neighbours surface in the same call as one-hop. The previous fan-out (one `get` per related id, per seed) is gone.

The second, more interesting change is **Phase 2b — hidden connections**. For each Phase 1 seed, the skill calls `distillery_find_similar(source_entry_id=<seed>, exclude_linked=true, threshold=0.7)`. The MCP server filters out anything that already shares a stored relation with the seed in either direction, so what comes back is unlinked-but-semantically-related — the entries the graph alone would never surface, because nobody wrote down that they were related, but that the embedding space says belong with this seed.

These are tagged `potentially related` in the synthesis and the sources table — never added to the relationship map, because they have no recorded edge. The framing matters: a stored relation is something a human authored; a Phase 2b hit is a hypothesis the embedding space is generating. Treating them differently in the output is what makes the skill useful instead of noisy.

In practice this is the fix for the "I know we wrote about this somewhere but it never gets cited together" failure mode. The graph captures intentional knowledge structure; embeddings capture incidental similarity. Phase 2b reads both.

### Multi-hop synthesis in `/pour --graph`

`/pour` runs four-pass retrieval (curated → broad → concept follow-up → tag expansion → gap fill) and synthesizes the union into a structured narrative with citations. Until 0.5.0, all four passes were pure semantic search. Now there's an opt-in `--graph` flag that adds 1-hop graph expansion to every search call.

The mechanism is one new MCP feature: `distillery_search` accepts `expand_graph=true, expand_hops=1`. The server runs the underlying hybrid search, then for each hit follows outgoing relations one hop and includes the neighbours in the response, with a 0.5-per-hop score discount and `provenance: "search" | "graph"` recorded on every result. The skill picks this up in synthesis: graph-only entries are labelled `[Entry abc12345, structurally related]` in the prose, and the sources table gains a `Provenance` column showing `search` or `graph (via <parent_short_id>)`.

The audit trail is the point. When a synthesis cites an entry, the reader can tell whether that entry matched the query directly or was pulled in because it's linked to a match. The first signal is "this entry talks about your topic"; the second is "this entry is what your topic depends on, even though it doesn't mention your topic by name." Both are useful; treating them as the same signal is how you get LLM-generated synthesis that confidently cites a paragraph that has nothing to do with the question.

`--graph` is **off by default**. On a sparse graph it adds nothing. On a well-curated graph (sessions linked to PRs, references, follow-up minutes) it pulls in exactly the context that semantic search misses — the downstream impacts, the prior decisions a search-matched entry references, the related work in adjacent subsystems.

### Structural insights in `/radar --structure`

`/radar` digests recent feed activity. With `--structure`, it also appends a snapshot of the **shape** of your knowledge base:

- **Orphans** — entries with no incoming or outgoing relations. Knowledge fragments worth reviewing for connection opportunities. Surfaced via `distillery_list(structural=["orphans"])`.
- **Bridges** — top-5 entries by betweenness centrality. The "joints" of the graph; the entries whose loss or contradiction would disconnect the most knowledge. Surfaced via `distillery_relations(action="metrics", metric="bridges")`.
- **Communities** — clusters detected in the entry-relations graph, sorted by member count, with optional `[stale]` tagging when every member's `updated_at` is older than 60 days.

Bridges and communities require the `[graph]` extra (NetworkX); if it's missing, `/radar` emits a one-line `pip install distillery-mcp[graph]` hint and continues without those subsections. Orphans don't need NetworkX — they're a pure SQL filter on `entry_relations`.

The framing here is "what does the shape of my knowledge look like, separate from what's new this week." Most digest tools answer the second question. `--structure` answers the first.

## Skill ergonomics

Two changes that are smaller than the graph work but matter every day.

`/radar --topic <query>` lets you bypass the auto-derived interest profile and pass a literal search query straight through. Repeatable — `/radar --topic build --topic wheels` issues two separate `distillery_search` calls. The 5-query namespace cap doesn't apply to `--topic`; every distinct topic you supply is honored, up to `--limit`. This is the right flag when you want to follow a specific thread without your dominant tag clusters drowning it out.

The default `/radar` (no flags) also got rewired. We now select **5 namespace-diverse tags** rather than the raw top-5 by count. A tag's namespace is its hierarchical path with the leaf removed, capped at two segments — `domain/build/hermeticity` belongs to `domain/build`, `tech/duckdb` to `tech`. Selection picks one leader per namespace, sorts namespaces by aggregate population, and returns the top-5 leaders. The result is that the query set spans up to five distinct conceptual clusters instead of returning five close variants of the same cluster.

The candidate budget moved from 20 to 35 by default (`feeds.digest.candidate_limit`), and `--limit` is a per-invocation override. With Q=5 queries and a 35-entry budget, each query gets 7 results — 35 raw → ~30 unique candidates after dedup. Small overrides like `--limit 3` reduce Q to 3 so the override is honored exactly; no zero-budget queries are issued.

## The discipline: regression-gated launch

The graph features are default-off, but they touch the same call sites that the LongMemEval headline numbers come from. Shipping them without measuring whether they regressed the baseline would be exactly the kind of silent quality drift that `bench/LIMITATIONS.md` exists to prevent.

So we ran a regression gate. The full discipline note is in [`bench/LIMITATIONS.md`](https://github.com/norrietaylor/distillery/blob/main/bench/LIMITATIONS.md) §(f); the short version is that we split the graph bench coverage into two cells.

**Cell A — graph regression gate (DO).** Same config as HEADLINE (`hybrid / session / recency-on / bge-small`, 500q × 5 seeds), re-run with `--expand-graph` enabled. Pass criterion: Cell A's mean R@5 must be within 0.5pp of the HEADLINE mean. The first full-500q × 5-seed run on the 0.5.0 commit landed at **mean R@5 = 0.972** (stddev 0.000), exactly matching the HEADLINE mean of 0.972 — **delta = 0.0pp, gate_pass=true**. Aggregate receipt: [`bench/results/graph_regression_cell_a.json`](https://github.com/norrietaylor/distillery/blob/main/bench/results/graph_regression_cell_a.json). Workflow run: [`actions/runs/25453787717`](https://github.com/norrietaylor/distillery/actions/runs/25453787717).

**Cell B — graph value-add (DEFER).** A claim of the form "graph features improve LongMemEval" is **not supported** by this benchmark and we don't make it. LongMemEval is single-user, single-session — every question is scored against one user's haystack — and the graph hypothesis Distillery's features are designed to exploit is cross-user / cross-session entry relations. Measuring graph value-add on LongMemEval would be a category error. The deferred eval is one of: a multi-hop QA dataset, a synthetic team-knowledge eval (multiple authors, cross-author lookups), or an in-house `/investigate` / `/pour` synthesis eval that scores the value the graph adds to multi-document narrative answers. Until that eval exists, no public surface — this post, the README, the benchmarks page, the release notes — claims that graph features improve LongMemEval scores.

Concretely: the 0.5.0 release notes say **"no regression with graph enabled"**, never "graph improves LongMemEval." A Cell A run with mean R@5 *higher* than HEADLINE would not be a value-add result either — it would be within the noise band the variance gate already characterises in `bench/results/variance_baseline.json`.

This is not the most exciting thing we could have written about a release shipping graph features. It is the most honest one.

## What's next

Epic [#147](https://github.com/norrietaylor/distillery/issues/147) — the graph epic — closes with this release. The remaining work points outward:

- A **multi-hop QA eval** that actually exercises the graph hypothesis. Some combination of an existing dataset (HotpotQA-shaped) adapted to the Distillery store, or a synthetic eval generated against the team-knowledge use case.
- A **synthesis eval** that scores the value the graph adds to `/investigate` and `/pour` narrative outputs — judging whether graph-only context made the synthesis better or just longer.
- More **structural surfaces** in the skills layer: graph-aware deduplication, bridge-aware retention policies, community-derived tag suggestions.

The graph is now first-class infrastructure. The interesting questions are about what to do with it.

## Try it

```bash
uvx distillery-mcp@0.5.0
# or
pip install distillery-mcp==0.5.0
# graph metrics (bridges + communities) require NetworkX:
pip install -e ".[graph]"
```

Hosted demo at `https://distillery-mcp.fly.dev/mcp` is redeployed to match. Skills remain as before for anyone who doesn't opt into the new flags — `/pour` without `--graph` and `/radar` without `--structure` behave identically to 0.4.x.

The full release notes are on the [GitHub release](https://github.com/norrietaylor/distillery/releases/tag/v0.5.0). Discussion thread lives in [GitHub Discussions](https://github.com/norrietaylor/distillery/discussions).

---

The 0.4.0 pledge was that the surface is a contract. 0.5.0 is what that contract enables: a release that adds a new retrieval modality without breaking anything downstream, gated behind a regression check, with the value-add claim deferred until we have an eval that can measure it. Walk the graph. Don't oversell it.
