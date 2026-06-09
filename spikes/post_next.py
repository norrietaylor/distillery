"""Composite "what to post next" scorer — blends the three graph lenses.

Reconciles structural-hole brokerage (query 1), resonance gap (query 2), and
audience-interest recency into one transparent, ranked recommendation over the
owner's expertise topics. Each signal is min-max normalised across the candidate
topics, then combined with explicit weights so the recommendation is auditable.

  score = w_b*brokerage + w_g*resonance_gap + w_r*recency

Run: .venv/bin/python spikes/post_next.py
"""

from __future__ import annotations

import asyncio

from network import build_metrics, build_store

W_BROKERAGE, W_GAP, W_RECENCY = 0.4, 0.4, 0.2


def normalize(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi == lo:
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


async def main() -> None:
    store, id_of, prov = await build_store()
    print(f"embedding provider: {prov}")
    m = build_metrics(await store.list_relations(), id_of)

    mine = [r for r in m["rows"] if r["mine"]]
    brokerage = normalize([float(r["span"]) for r in mine])
    gap = normalize([r["gap"] for r in mine])
    recency = normalize([r["recency"] for r in mine])

    scored = []
    for r, b, g, rc in zip(mine, brokerage, gap, recency, strict=True):
        score = W_BROKERAGE * b + W_GAP * g + W_RECENCY * rc
        scored.append({**r, "n_brokerage": b, "n_gap": g, "n_recency": rc, "score": score})
    scored.sort(key=lambda r: -r["score"])

    print(f"\nComposite post-next ranking  (weights: brokerage {W_BROKERAGE}, "
          f"gap {W_GAP}, recency {W_RECENCY})")
    print(f"  {'rank':<4} {'topic':<22} {'brokerage':>10} {'gap':>6} {'recency':>8} {'SCORE':>7}")
    for i, r in enumerate(scored, 1):
        print(f"  {i:<4} {r['topic']:<22} {r['n_brokerage']:>10.2f} {r['n_gap']:>6.2f} "
              f"{r['n_recency']:>8.2f} {r['score']:>7.3f}")

    top = scored[0]
    print("\n" + "=" * 72)
    print(f"RECOMMENDATION: post next on '{top['topic']}' (score {top['score']:.3f})")
    print(f"  why: bridges {top['span']} audience communities (brokerage {top['n_brokerage']:.2f}), "
          f"unmet demand (gap {top['n_gap']:.2f}), interest {top['n_recency']:.2f} fresh.")
    print("  Adjust weights to taste — the breakdown stays auditable. A real agent would "
          "draft the post (embeddings) and cite the graph evidence above.")
    print("=" * 72)
    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
