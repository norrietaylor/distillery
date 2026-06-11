"""Query #1 — Structural-hole brokerage: post on topics that bridge clusters.

Per Burt's structural-holes theory, the high-value post sits in a topic that
bridges audience communities that rarely talk to each other, where the owner has
credibility. Ranking by community span (and corroborating Burt constraint) beats
both naive popularity and pure semantic similarity, which are blind to network
structure.

Run: .venv/bin/python spikes/q1_structural_holes.py
"""

from __future__ import annotations

import asyncio

from network import EXPERTISE_BLOB, TOPICS, build_metrics, build_store


async def main() -> None:
    store, id_of, prov = await build_store()
    print(f"embedding provider: {prov}")
    m = build_metrics(await store.list_relations(), id_of)
    rows = m["rows"]
    print(f"detected {len(m['communities'])} audience communities "
          f"(sizes {sorted((len(c) for c in m['communities']), reverse=True)})")

    def show(title, ordered):
        print(f"\n{title}")
        print(f"  {'rank':<4} {'topic':<22} {'pop':>3} {'span':>4} {'constraint':>10} {'mine':>5}")
        for i, r in enumerate(ordered, 1):
            print(f"  {i:<4} {r['topic']:<22} {r['demand']:>3} {r['span']:>4} "
                  f"{r['constraint']:>10.3f} {'yes' if r['mine'] else '':>5}")

    naive = sorted(rows, key=lambda r: (-r["demand"], r["topic"]))
    show("RANKING 1 — Naive popularity (most interested people)", naive)

    mine = [r for r in rows if r["mine"]]
    sh = sorted(mine, key=lambda r: (-r["span"], r["demand"], r["constraint"]))
    show("RANKING 2 — Structural-hole brokerage (owner-expertise topics)", sh)

    results = await store.search(EXPERTISE_BLOB, filters={"entry_type": "reference"}, limit=len(TOPICS))
    sem = [m["by_topic"][res.entry.metadata["topic_id"]] | {"_s": res.score}
           for res in results if res.entry.metadata.get("topic_id") in m["by_topic"]]
    print(f"\nRANKING 3 — Semantic search (similarity to: \"{EXPERTISE_BLOB}\")")
    print(f"  {'rank':<4} {'topic':<22} {'score':>6} {'pop':>3} {'span':>4} {'mine':>5}")
    for i, r in enumerate(sem, 1):
        print(f"  {i:<4} {r['topic']:<22} {r['_s']:>6.3f} {r['demand']:>3} "
              f"{r['span']:>4} {'yes' if r['mine'] else '':>5}")

    top = sh[0]["topic"]
    nr = next(i for i, r in enumerate(naive, 1) if r["topic"] == top)
    print("\n" + "=" * 70)
    print(f"DELTA: structural-hole top pick '{top}' bridges {sh[0]['span']} communities "
          f"but ranks #{nr}/{len(naive)} by popularity "
          f"{'(LAST)' if nr == len(naive) else ''} — the graph surfaces it, popularity buries it.")
    print("=" * 70)
    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
