# Recency-decay toggle audit

**Investigator:** sub-agent W1-recency-probe
**Date:** 2026-05-03T07:23:11Z
**Branch:** bench/recency-toggle-probe
**Repo state:** 12a29e0ed9f7cd0222a2d5eb296bbeec7b86aa28

## Question

Is `recency_decay` toggleable per-query on `DuckDBStore`, or does toggling
require rebuilding the store?

## Findings

### Where the recency logic lives

- **Constructor parameters (per-store, set once at instantiation).**
  `src/distillery/store/duckdb.py:151-152` declares
  `recency_window_days: int = 90` and `recency_min_weight: float = 0.5` as
  keyword-only `__init__` parameters. They are persisted as private fields
  at `src/distillery/store/duckdb.py:164-165`
  (`self._recency_window_days`, `self._recency_min_weight`).
- **Recency-weight computation.** `_recency_weight(self, created_at)` at
  `src/distillery/store/duckdb.py:1491-1508` reads the stored fields
  (`self._recency_window_days` and `self._recency_min_weight`) directly —
  there is no override hook, no method-level argument, and no class-level
  setter. The decay is linear from `1.0` at the window edge down to
  `recency_min_weight`, computed as
  `decay = 1.0 - (age_days - window) / max(window, 1)` and clamped via
  `max(self._recency_min_weight, decay)`.
- **Application site.** Recency is applied unconditionally inside the
  hybrid (BM25 + vector RRF) path at
  `src/distillery/store/duckdb.py:1640-1652`:
  ```python
  # --- RRF fusion with recency decay (used for ORDERING only) ---
  ...
  recency = self._recency_weight(entry_created[eid])
  rrf_score *= recency
  ```
  There is no `if recency_enabled:` guard. The vector-only fallback path
  (`src/distillery/store/duckdb.py:1583-1596`) does **not** apply recency
  at all — it sorts purely by raw cosine similarity.

### Public API surface that controls it

- **Protocol contract.** `DistilleryStore.search()` in
  `src/distillery/store/protocol.py:147-179` accepts exactly three
  arguments: `query: str`, `filters: dict[str, Any] | None`, `limit: int`.
  The `filters` dict's documented keys are
  `entry_type`, `author`, `project`, `tags`, `status`, `verification`,
  `date_from`, `date_to` — none of them touch recency scoring. There is
  **no per-call kwarg or filter key** for toggling, weighting, or
  parameterising recency.
- **Concrete implementation.**
  `DuckDBStore.search()` at
  `src/distillery/store/duckdb.py:1510-1515` adheres to that signature
  exactly (`query, filters, limit`) — no extra keyword arguments.
- **Config plumbing.** `DefaultsConfig` at
  `src/distillery/config.py:108-109` exposes `recency_window_days: int = 90`
  and `recency_min_weight: float = 0.5`. The CLI threads them straight into
  the constructor at `src/distillery/cli.py:522-523, 673-674, 795-796,
  1063-1064, 1754-1755` — every `DuckDBStore(...)` call site reads the
  config-level defaults at construction time and never revisits them.
- **Config file.** `distillery-dev.yaml` does not set either field, so dev
  runs use the defaults (`90` / `0.5`). The values are settable via
  `defaults.recency_window_days` / `defaults.recency_min_weight` in the
  YAML (parsed at `src/distillery/config.py:497-519`), but again — only
  read when the store object is constructed.

### Query-time multiplier vs index-time materialisation

The decay is a **query-time multiplier**, not an index-time materialisation.
`_recency_weight` is called inside the per-result loop at
`src/distillery/store/duckdb.py:1644-1653`, multiplying each candidate's
RRF score before sorting. Nothing about recency is baked into the HNSW
index, the FTS index, or the row layout. The only thing locked in at
construction time is the `self._recency_window_days` /
`self._recency_min_weight` *values*, not any pre-computed decay column.

This is why a per-query toggle would be a small refactor — the math is
already entirely query-time — but the toggle doesn't exist today.

### Test evidence

- `tests/test_duckdb_store.py:1107-1162` exercises hybrid search and
  asserts that `recency_window_days=90` / `recency_min_weight=0.5` are
  persisted on `_recency_window_days` / `_recency_min_weight` after
  passing through the constructor. There is no test that toggles recency
  per query — only construction-time variants.
- `tests/test_duckdb_store.py:1377-1413` (`Tests for _recency_weight
  calculation`) instantiates a store with specific recency parameters and
  calls `_recency_weight` directly. Confirms the decay math but again
  only via the constructor-injected fields.
- `tests/test_config.py:99-199` covers config loading of
  `recency_window_days` / `recency_min_weight` defaults and YAML overrides.
  No test passes a recency value to `search()`; it's not in the API.

In summary: every test that varies recency does so by constructing a fresh
`DuckDBStore` with different constructor kwargs. There is no test that
toggles recency on an existing store, because the API does not allow it.

### Effective workaround

Setting `recency_min_weight=1.0` at construction time effectively disables
the multiplier:
- For entries inside the window, `_recency_weight` returns `1.0` (line
  1503-1504, unchanged).
- For entries outside the window, `decay < 1.0`, but
  `max(self._recency_min_weight, decay) == max(1.0, decay) == 1.0`
  (line 1508).

So `recency_min_weight=1.0` neutralises the decay multiplier without code
changes. This still requires constructing a separate `DuckDBStore`
instance — there is no per-query equivalent.

## Verdict

**Per-store.** Recency cannot be toggled on a per-query basis. The
`DuckDBStore.search()` signature (`src/distillery/store/protocol.py:147-152`,
`src/distillery/store/duckdb.py:1510-1515`) accepts no recency-related
kwarg, and `_recency_weight` reads from instance state set in `__init__`
(`src/distillery/store/duckdb.py:151-152, 164-165, 1491-1508`). To
compare `--recency on` vs `--recency off`, the bench must instantiate a
new store per cell with different `recency_min_weight` values (or with
the multiplier conditionally disabled via a small code change).

## Recommendation

For **W2-bench-runner**:

1. **Build one store per `(retrieval, granularity, embed-model, recency)`
   cell**, not per question. Recency is a per-store axis, not per-query;
   trying to share a store across `recency=on`/`recency=off` cells will
   silently use whichever value the store was constructed with.
2. **Use `recency_min_weight=1.0` for the `--recency off` cell** and the
   default `recency_min_weight=0.5` for `--recency on`. Both cells keep
   `hybrid_search=True` so only the recency axis varies. This avoids
   conflating "recency off" with "hybrid off" — important because
   disabling hybrid search would also short-circuit the only path where
   recency is applied (the vector-only fallback at
   `src/distillery/store/duckdb.py:1583-1596` does not multiply by
   `_recency_weight` at all).
3. **Cost implication.** The bench plan's headline cell (LongMemEvalₛ,
   ~500 questions, fastembed `bge-small`) already constructs an in-memory
   `DuckDBStore` per question (per the plan's verification step 4 and
   discipline rule 5 — fixed seed *per* question). Adding `recency` as a
   per-cell axis multiplies the matrix by 2 (on vs off) but does not
   change the per-question rebuild cost — the inner loop already pays it.
   Net impact on the nightly run: an extra ~15 min for the recency-off
   ablation cell, which the plan already budgets in §3.
4. **Verification step.** The plan's verification step 3 says "Verify
   `--recency on|off` is a per-query parameter, not a store-construction
   parameter. If it's the latter, the bench design needs to rebuild the
   store per cell — file a dependent task before continuing." This audit
   confirms it is the latter. **Per the plan's own gate, a dependent
   issue should be filed** asking either:
   - (a) Expose recency as a `search()` kwarg
     (`recency: bool = True` or `recency_min_weight: float | None = None`)
     so a single in-memory store can serve all bench cells, or
   - (b) Document the per-store contract explicitly in the
     `DistilleryStore` protocol and accept the bench rebuild cost.

   This audit does not file the issue (per the prompt constraints — that
   is the human reviewer's call); the recommendation here is option (a)
   on grounds of API ergonomics and bench efficiency, but option (b) is
   defensible if the maintainers prefer to keep `search()` lean.
5. **Tactical guidance for W2-bench-runner.** Don't block on the
   dependent issue. Implement the bench against the current per-store
   contract (rebuild per cell with `recency_min_weight ∈ {0.5, 1.0}`).
   When/if a per-query toggle lands, the bench can be simplified in a
   follow-up — but the current rebuild model is correct and the per-cell
   cost is acceptable per the plan's own budget.
