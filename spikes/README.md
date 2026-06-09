# Spikes — Distillery as memory for a content-recommendation agent

Throwaway research spikes (not shipped code, not imported by `distillery`) that
test one claim: **a graph layered on Distillery's existing store can decide
*what to post next* better than popularity or embedding similarity alone.**

They seed a synthetic audience graph into a real in-memory Distillery store and
compute graph metrics in networkx over `store.list_relations()`. Distillery
stores the graph; the agent computes the metrics.

> Scope: assistive only. An agent like this drafts content, suggests
> connections, and analyses *your own* data through official APIs — it performs
> no automated actions or scraping against any external platform.

## Run

```bash
# from repo root, deps: networkx, fastembed (real embeddings; falls back to a hash provider offline)
.venv/bin/python spikes/q1_structural_holes.py   # brokerage: topics that bridge clusters
.venv/bin/python spikes/q2_resonance_gap.py      # demand vs recent supply (temporal decay)
.venv/bin/python spikes/q3_link_prediction.py    # emerging adjacencies to grow into
.venv/bin/python spikes/post_next.py             # composite: blends the three into one ranking
```

`network.py` holds the shared synthetic network + seeding (`build_store`) and
metric reconstruction (`build_metrics`). The synthetic net: 23 people in 3
communities (infra / ai / devtools), 10 topics, owner expertise, 15 posts.

## What each spike shows

| Spike | Question | Result on the synthetic net |
|---|---|---|
| q1 structural holes | Which topic *brokers* disconnected audience clusters? | `agent-infrastructure` (bridges 3 communities) — ranks **#9/10 by popularity**; the graph surfaces it |
| q2 resonance gap | High demand, low recent supply? | Highest-demand `llm-evaluation` is **saturated** (gap #9/10); `distributed-systems` is the unmet pick |
| q3 link prediction | Topics to *expand into* (Adamic-Adar)? | `llm-evaluation`/`rag` are adjacent (audience already bridges them) but saturated → combine with q2: `build-systems` is adjacent **and** unserved |
| post_next | One auditable recommendation? | `agent-infrastructure` (brokerage 1.00 · gap 1.00 · recency 1.00) |

The lenses are orthogonal: q1 = where to **broker**, q2 = where demand is
**unmet**, q3 = where to **grow**. `post_next` blends q1 + q2 + recency with
explicit, tunable weights so the recommendation stays explainable.

## Why a graph (vs. embeddings)

Embedding similarity answers "what's topically me" — it has no notion of
audience community structure (q1) or content supply (q2). Those are graph
properties. This is the "hidden connections" intuition made concrete, and the
case GraphRAG-style global sensemaking wins on.

## Distillery primitives used vs. gaps found

Used as-is: `store_batch`, `add_relation`, `list_relations` (full edge list),
`search`, arbitrary node metadata, the native `person` type. Distillery also
ships `bridges` and `communities` graph metrics via `distillery_relations
action="metrics"` — community detection is already built in.

Gaps surfaced (build-on-top, per the architecture plan):

- **Relations carry no weight/timestamp column.** `add_relation(from, to, type)`
  only. Edge recency/weight (interest decay, engagement strength) had to live in
  node metadata or in-script (`DEMAND_RECENCY`). Bi-temporal edges (the
  Graphiti lesson) would need a schema extension.
- **Some graph algorithms not built in.** `bridges` and `communities` ship in
  `distillery.graph.metrics`; the spikes' Burt constraint (structural holes) and
  Adamic-Adar link prediction run in networkx on top here.
- **No external-platform ingress.** Feeds are RSS/GitHub; an official-API/OAuth
  adapter is required (and is the compliance boundary).
