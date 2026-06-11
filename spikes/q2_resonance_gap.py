"""Query #2 — Resonance gap: high audience demand, low recent supply.

A resonance gap is a topic the audience wants (demand) that nobody is currently
serving (low recent, age-decayed supply). This is the global-sensemaking query
GraphRAG is strong at and embeddings can't answer — similarity has no notion of
supply. The highest-demand topic is often the worst pick because it is saturated.

  demand        = interested people, reach-weighted by community span
  recent_supply = posts about the topic, decayed by age (30-day half-life)
  gap           = reach_demand / (recent_supply + 1)

Run: .venv/bin/python spikes/q2_resonance_gap.py
"""

from __future__ import annotations

import asyncio

from network import build_metrics, build_store


async def main() -> None:
    store, id_of, prov = await build_store()
    print(f"embedding provider: {prov}")
    m = build_metrics(await store.list_relations(), id_of)
    rows = m["rows"]

    def show(title, ordered, cols):
        print(f"\n{title}")
        print("  " + f"{'rank':<4} {'topic':<22}" + "".join(f"{c:>9}" for c in cols) + f"{'mine':>6}")
        for i, r in enumerate(ordered, 1):
            vals = "".join(f"{r[c]:>9.2f}" if isinstance(r[c], float) else f"{r[c]:>9}" for c in cols)
            print(f"  {i:<4} {r['topic']:<22}{vals}{'yes' if r['mine'] else '':>6}")

    by_demand = sorted(rows, key=lambda r: (-r["demand"], r["topic"]))
    show("RANKING 1 — Demand only (query 1's popularity view)", by_demand, ["demand", "span"])

    by_gap = sorted(rows, key=lambda r: (-r["gap"], r["topic"]))
    show("RANKING 2 — Resonance gap = reach_demand / (recent_supply + 1)",
         by_gap, ["demand", "reach", "supply", "gap"])

    mine = sorted([r for r in rows if r["mine"]], key=lambda r: (-r["gap"], -r["demand"]))
    show("RANKING 3 — Actionable: resonance gap among owner-expertise topics",
         mine, ["demand", "reach", "supply", "gap"])

    hype = by_demand[0]
    hr = next(i for i, r in enumerate(by_gap, 1) if r["topic"] == hype["topic"])
    top = mine[0]
    stale = m["by_topic"]["ide-tooling"]
    print("\n" + "=" * 72)
    print(f"DELTA: highest-demand '{hype['topic']}' (demand {hype['demand']}) is SATURATED "
          f"(supply {hype['supply']:.2f}) -> gap rank #{hr}/{len(by_gap)}.")
    print(f"  actionable pick '{top['topic']}' (demand {top['demand']}, supply {top['supply']:.2f}, "
          f"gap {top['gap']:.2f}).")
    print(f"  recency: 'ide-tooling' has a post but at 120d its decayed supply is only "
          f"{stale['supply']:.3f} -> gap reopened.")
    print("  embeddings cannot compute this: no notion of supply.")
    print("=" * 72)
    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
