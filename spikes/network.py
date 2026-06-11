"""Shared synthetic audience graph + Distillery seeding for the spikes.

One in-memory Distillery store, seeded with a small professional-network graph:
people clustered into communities, topics, audience interest edges, the owner's
expertise (`covers`) edges, and posts (the supply side). Every spike
(q1_structural_holes, q2_resonance_gap, q3_link_prediction, post_next) imports
``build_store`` + ``build_metrics`` from here so they share an identical network.

Distillery primitives exercised: ``store_batch``, ``add_relation``,
``list_relations`` (the full edge list), and ``search``. The graph algorithms
(community detection, Burt constraint, link prediction) run in networkx over the
edge list — Distillery stores the graph, the agent computes the metrics.
"""

from __future__ import annotations

import math
from collections import defaultdict

import networkx as nx

from distillery.models import Entry, EntrySource, EntryType
from distillery.store.duckdb import DuckDBStore

HALF_LIFE_DAYS = 30.0

COMMUNITIES = {
    "infra":    [f"a{i}" for i in range(1, 9)],   # DevOps / Infra crowd
    "ai":       [f"b{i}" for i in range(1, 9)],   # AI / ML crowd
    "devtools": [f"c{i}" for i in range(1, 7)],   # DevTools / DX crowd
}

TOPICS = {
    "kubernetes":           "Kubernetes cluster operations, scheduling, and production reliability.",
    "observability":        "Observability, metrics, tracing, and logging for distributed services.",
    "distributed-systems":  "Distributed systems design: consensus, partitioning, fault tolerance.",
    "llm-evaluation":       "Evaluating large language models: benchmarks, eval harnesses, scoring.",
    "rag":                  "Retrieval augmented generation pipelines and vector search.",
    "ai-agents":            "Autonomous AI agents, tool use, planning, and orchestration.",
    "developer-tools":      "Developer tooling, CLIs, and engineering productivity.",
    "ide-tooling":          "IDE extensions, language servers, and editor integrations.",
    "build-systems":        "Build systems, incremental compilation, and CI caching.",
    "agent-infrastructure": "Infrastructure for running AI agents at scale: orchestration, "
                            "observability, and developer tooling for agent fleets.",
}

# topic -> interested people. Bridge topics deliberately span communities.
INTEREST = {
    "kubernetes":           ["a1", "a2", "a3", "a4", "a5", "a6"],
    "observability":        ["a3", "a4", "a5", "a6", "a7"],
    "distributed-systems":  ["a1", "a2", "b1", "b2"],                 # bridges infra<->ai
    "llm-evaluation":       ["b1", "b2", "b3", "b4", "b5", "b6", "b7"],
    "rag":                  ["b2", "b3", "b4", "b5", "b6"],
    "ai-agents":            ["b6", "b7", "c1", "c2", "c3"],           # bridges ai<->devtools
    "developer-tools":      ["c1", "c2", "c3", "c4", "c5", "c6"],
    "ide-tooling":          ["c2", "c3", "c4", "c5"],
    "build-systems":        ["c4", "c5", "c6"],
    "agent-infrastructure": ["a1", "b6", "c1"],                       # bridges all three
}

# (topic, author, age_in_days) — the supply side. Topics absent here have zero supply.
POSTS = [
    ("llm-evaluation", "b1", 2), ("llm-evaluation", "b3", 5),         # hype topic: saturated
    ("llm-evaluation", "b5", 9), ("llm-evaluation", "me", 14),
    ("rag", "b2", 3), ("rag", "b4", 8), ("rag", "b6", 20),
    ("developer-tools", "c1", 4), ("developer-tools", "c3", 11), ("developer-tools", "c5", 25),
    ("kubernetes", "a2", 6), ("kubernetes", "a4", 18),
    ("ai-agents", "b7", 7), ("ai-agents", "c2", 16),
    ("ide-tooling", "c4", 120),                                       # stale -> decays -> gap reopens
]

# the account owner's credibility areas (covers edges)
MY_EXPERTISE = ["distributed-systems", "ai-agents", "developer-tools", "agent-infrastructure"]
EXPERTISE_BLOB = "distributed systems, autonomous AI agents, and developer tooling"

# Per-topic audience-interest recency in [0,1] (1 = freshly trending, lower = cooling).
# In production this would be temporal metadata on the `interested_in` edges; Distillery
# relations carry no weight/time column today, so it lives here (see README "Distillery gaps").
DEMAND_RECENCY = {
    "distributed-systems": 0.9, "ai-agents": 1.0,
    "developer-tools": 0.6, "agent-infrastructure": 1.0,
}


def make_provider():
    """Return (provider, name). Real fastembed for a meaningful semantic baseline;
    hash fallback if the model can't be fetched (offline)."""
    try:
        from distillery.embedding.fastembed import FastembedProvider

        p = FastembedProvider()
        p.embed("warmup")  # force model load; raises offline
        return p, f"fastembed/{p.model_name}"
    except Exception as exc:  # noqa: BLE001
        print(f"  (fastembed unavailable: {exc!s:.50} -> hash fallback; semantic baseline degraded)")

        class Hash4D:
            _DIMS = 4

            def _v(self, t):
                h = hash(t) & 0xFFFFFFFF
                parts = [float((h >> (8 * i)) & 0xFF) + 1.0 for i in range(self._DIMS)]
                m = math.sqrt(sum(x * x for x in parts))
                return [x / m for x in parts]

            def embed(self, t):
                return self._v(t)

            def embed_batch(self, ts):
                return [self._v(t) for t in ts]

            @property
            def dimensions(self):
                return self._DIMS

            @property
            def model_name(self):
                return "hash-4d"

        return Hash4D(), "hash-4d"


async def build_store() -> tuple[DuckDBStore, dict[str, str], str]:
    """Seed the full network into a fresh in-memory store.

    Returns (store, id_of, provider_name) where id_of maps node keys
    ("me", "a1", "kubernetes", "post0", ...) to Distillery entry UUIDs.
    """
    provider, prov_name = make_provider()
    store = DuckDBStore(db_path=":memory:", embedding_provider=provider)
    await store.initialize()

    entries: list[Entry] = []
    id_of: dict[str, str] = {}

    me = Entry(
        content="Account owner posting on distributed systems, AI agents, developer tools.",
        entry_type=EntryType.PERSON, source=EntrySource.MANUAL, author="owner",
        metadata={"expertise": MY_EXPERTISE, "role": "owner"},
    )
    entries.append(me)
    id_of["me"] = me.id

    for comm, people in COMMUNITIES.items():
        for p in people:
            e = Entry(content=f"{p} — {comm} community.", entry_type=EntryType.PERSON,
                      source=EntrySource.IMPORT, author="seed",
                      metadata={"expertise": [comm], "community": comm})
            entries.append(e)
            id_of[p] = e.id

    for tid, content in TOPICS.items():
        e = Entry(content=content, entry_type=EntryType.REFERENCE, source=EntrySource.IMPORT,
                  author="seed", tags=["node/topic"], metadata={"topic_id": tid})
        entries.append(e)
        id_of[tid] = e.id

    for i, (tid, author, age) in enumerate(POSTS):
        e = Entry(content=f"Post about {tid}.", entry_type=EntryType.SESSION,
                  source=EntrySource.IMPORT, author=author, tags=["node/post"],
                  metadata={"topic_id": tid, "age_days": age})
        entries.append(e)
        id_of[f"post{i}"] = e.id

    await store.store_batch(entries)

    async def link(a: str, b: str, rel: str) -> None:
        await store.add_relation(id_of[a], id_of[b], rel)

    for people in COMMUNITIES.values():  # dense intra-community cliques
        for i in range(len(people)):
            for j in range(i + 1, len(people)):
                await link(people[i], people[j], "connected_to")
    for a, b in [("a1", "b1"), ("b1", "c1"), ("a2", "c2")]:  # sparse cross-community bridges
        await link(a, b, "connected_to")
    for p in ["a1", "a2", "b1", "b2", "c1", "c2"]:  # owner spans communities (the broker)
        await link("me", p, "connected_to")
    for tid, people in INTEREST.items():
        for p in people:
            await link(p, tid, "interested_in")
    for tid in MY_EXPERTISE:
        await link("me", tid, "covers")
    for i, (tid, author, _age) in enumerate(POSTS):
        await link(f"post{i}", tid, "about")
        await link(f"post{i}", author, "authored_by")

    return store, id_of, prov_name


def build_metrics(relations: list[dict], id_of: dict[str, str]) -> dict:
    """Reconstruct the graph from the edge list and compute per-topic base metrics.

    Returns a dict with: person_graph, communities, comm_of, interest (topic->people),
    supply (topic->decayed), constraint (Burt, per node), topic_cooc (topic-topic graph
    weighted by shared audience), and rows (one dict per topic with the base signals).
    """
    id_to_key = {v: k for k, v in id_of.items()}
    post_age = {f"post{i}": age for i, (_t, _a, age) in enumerate(POSTS)}

    person_graph = nx.Graph()
    G = nx.Graph()  # people + topics, for Burt constraint
    interest: dict[str, list[str]] = defaultdict(list)
    post_topic: dict[str, str] = {}

    for r in relations:
        fk, tk, rel = id_to_key.get(r["from_id"]), id_to_key.get(r["to_id"]), r["relation_type"]
        if fk is None or tk is None:
            continue
        if rel == "connected_to":
            person_graph.add_edge(fk, tk)
            G.add_edge(fk, tk)
        elif rel == "interested_in":
            interest[tk].append(fk)
            G.add_edge(fk, tk)
        elif rel == "about":
            post_topic[fk] = tk

    person_graph.remove_node("me")  # owner is the broker, not part of audience clustering
    communities = nx.community.greedy_modularity_communities(person_graph)
    comm_of = {p: idx for idx, c in enumerate(communities) for p in c}
    constraint = nx.constraint(G)

    supply: dict[str, float] = defaultdict(float)
    for post, tid in post_topic.items():
        supply[tid] += 0.5 ** (post_age[post] / HALF_LIFE_DAYS)

    # topic-topic co-occurrence graph (shared interested people, owner excluded)
    topic_cooc = nx.Graph()
    topic_cooc.add_nodes_from(TOPICS)
    topics = list(TOPICS)
    aud = {t: {p for p in interest.get(t, []) if p != "me"} for t in topics}
    for i in range(len(topics)):
        for j in range(i + 1, len(topics)):
            shared = aud[topics[i]] & aud[topics[j]]
            if shared:
                topic_cooc.add_edge(topics[i], topics[j], weight=len(shared))

    rows = []
    for tid in TOPICS:
        people = [p for p in interest.get(tid, []) if p in comm_of]
        demand = len(people)
        span = len({comm_of[p] for p in people})
        reach = demand * (1 + 0.5 * (span - 1))
        s = supply.get(tid, 0.0)
        rows.append({
            "topic": tid, "demand": demand, "span": span, "reach": reach,
            "supply": s, "gap": reach / (s + 1.0), "constraint": constraint.get(tid, float("nan")),
            "recency": DEMAND_RECENCY.get(tid, 0.0), "mine": tid in MY_EXPERTISE,
        })

    return {
        "person_graph": person_graph, "communities": communities, "comm_of": comm_of,
        "interest": dict(interest), "supply": dict(supply), "constraint": constraint,
        "topic_cooc": topic_cooc, "rows": rows, "by_topic": {r["topic"]: r for r in rows},
    }
