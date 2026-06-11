"""Query #3 — Emerging adjacency via link prediction (Adamic-Adar).

Topics the owner does NOT yet cover but that are tightly woven into the audience
neighbourhood of topics they DO own — the natural topics to expand into early.
Computed with Adamic-Adar over the topic co-occurrence graph (topics linked when
they share interested people). Adamic-Adar weights shared neighbours by
1/log(degree), so a connection through a niche shared topic counts more than one
through a hub everybody touches.

Run: .venv/bin/python spikes/q3_link_prediction.py
"""

from __future__ import annotations

import asyncio

import networkx as nx

from network import MY_EXPERTISE, build_metrics, build_store


async def main() -> None:
    store, id_of, prov = await build_store()
    print(f"embedding provider: {prov}")
    m = build_metrics(await store.list_relations(), id_of)
    G = m["topic_cooc"]

    expertise = [t for t in MY_EXPERTISE if t in G]
    candidates = [t for t in G if t not in MY_EXPERTISE]

    scored = []
    for c in candidates:
        pairs = [(c, e) for e in expertise if c != e]
        aa = sum(p for _u, _v, p in nx.adamic_adar_index(G, pairs))
        # which expertise topics connect to this candidate, and via which shared topics
        connectors = sorted(
            e for e in expertise if len(list(nx.common_neighbors(G, c, e))) > 0 or G.has_edge(c, e)
        )
        cn = sum(len(list(nx.common_neighbors(G, c, e))) for e in expertise if c != e)
        scored.append({"topic": c, "aa": aa, "cn": cn, "connectors": connectors,
                       "demand": m["by_topic"][c]["demand"], "supply": m["by_topic"][c]["supply"]})

    scored.sort(key=lambda r: (-r["aa"], -r["cn"], r["topic"]))

    print(f"\nowner expertise: {expertise}")
    print("Emerging adjacencies — topics to expand into, ranked by Adamic-Adar affinity")
    print(f"  {'rank':<4} {'topic':<22} {'AA':>6} {'common':>7} {'demand':>7} {'supply':>7}  connectors")
    for i, r in enumerate(scored, 1):
        print(f"  {i:<4} {r['topic']:<22} {r['aa']:>6.2f} {r['cn']:>7} {r['demand']:>7} "
              f"{r['supply']:>7.2f}  {', '.join(r['connectors'])}")

    top = scored[0]
    print("\n" + "=" * 74)
    print(f"DELTA: '{top['topic']}' is the strongest emerging adjacency "
          f"(AA {top['aa']:.2f}, {top['cn']} shared sub-topics with your expertise) — "
          f"you don't cover it yet, but your audience already connects it to what you own.")
    print("  Link prediction finds where to GROW; query 1 finds where to BROKER; "
          "query 2 finds where demand is UNMET. Three lenses, one graph.")
    print("=" * 74)
    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
