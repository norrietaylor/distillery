# 18-spec-edge-by-default-and-link-suggestion

## Introduction/Overview

Spec 17 promoted recurring entity tags to nodes and backfilled stranded edges (epic [#653](https://github.com/norrietaylor/distillery/issues/653) steps 1–2). This spec covers steps 3–4: make **edge creation the default at ingestion** so new entries stop entering the graph as orphans, and add a **scheduled link-suggestion job** that auto-creates high-confidence `related` edges and routes low-confidence candidates to a review queue. Together these keep `orphan_rate` trending down after the one-time backfill, rather than re-accumulating orphans on every feed poll.

The primitives already exist but are dormant: `AutoLinkConfig.enabled` defaults to `False` (`config.py:189`), and the `link_prediction` metric (`graph/metrics.py:74`) plus `find_similar(accept_action="link")` (`search.py:41`) are never scheduled. The auto-create path requires **no LLM inference** — `link_prediction` is Adamic-Adar graph math and `find_similar` runs cosine over already-stored embeddings — so it runs safely headless in `/api/maintenance`.

## Goals

1. Enable semantic auto-linking by default across all ingestion paths (`store`, `store_batch`, feed poller), so a new entry with a close neighbour gains a `related` edge on write.
2. Provide a relation-candidate review surface so sub-threshold link suggestions are human-resolvable, without a new table.
3. Add a scheduled link-suggestion job that sweeps low-degree/orphan nodes, auto-creates `related` edges above a high threshold, and routes mid-confidence candidates to review.
4. Wire that job into the existing `/api/maintenance` pipeline (bearer auth, cooldown, weekly cron) with no LLM inference.
5. Keep every new behaviour idempotent and config-gated, re-runnable on a schedule without duplicating edges.

## User Stories

- As a knowledge-base operator, I want new entries to auto-link to close neighbours on ingest so feed-heavy instances stop accumulating orphans between maintenance runs.
- As an operator, I want a weekly job to propose edges for entries that entered without a neighbour, so the graph keeps densifying after the one-time backfill.
- As a reviewer, I want low-confidence edge suggestions queued rather than silently created or discarded, so I can confirm real connections without trusting noisy auto-links.

## Demoable Units of Work

> Requirement IDs use the format **R{unit}.{seq}**. These IDs are referenced directly by the planner — do not renumber after approval.

### Unit 1: Edge-by-default at ingestion

**Purpose:** Flip semantic auto-linking on by default so every ingestion path attempts ≥1 `related` edge per new entry (best-effort: orphans with no neighbour above threshold are swept later by Unit 3).
**Depends on:** None
**Affected areas:** `src/distillery/config.py`, `src/distillery/mcp/server.py`, `src/distillery/store/duckdb.py`

**Functional Requirements:**
- **R1.1**: `AutoLinkConfig.enabled` shall default to `True` (`config.py:189`), making semantic auto-link the default write-path behaviour; `threshold` (0.85) and `max_links` (5) defaults are unchanged.
- **R1.2**: All three ingestion paths shall exercise `_auto_link_semantic` with the configured values: single `store`, `store_batch`, and feed poll-ingest (poller routes through `store`, so verify it inherits the behaviour).
- **R1.3**: Auto-link shall remain idempotent on the `(from_id, to_id, relation_type)` unique index and capped at `max_links` edges per entry; a re-store of the same entry creates no duplicate edges.
- **R1.4**: Setting `auto_link.enabled = False` in config shall fully restore the prior no-edge write behaviour (the kill switch is preserved).

**Proof Artifacts:**
- Test: with default config, store an entry whose embedding is within threshold of an existing entry; assert a `related` edge from new→existing exists after `store()` with no explicit `accept_action`, demonstrating R1.1/R1.2.
- Test: store the same entry twice (or store two cross-similar entries) and assert edge count respects `max_links` and does not grow on the second store, demonstrating R1.3.

### Unit 2: Relation-candidate review surface

**Purpose:** Persist sub-threshold edge suggestions as reviewable candidates and let a reviewer accept (promote to a live edge) or reject (remove) them — the queue Unit 3 routes into.
**Depends on:** None
**Affected areas:** `src/distillery/store/protocol.py`, `src/distillery/store/duckdb.py`, `src/distillery/mcp/tools/relations.py`

**Functional Requirements:**
- **R2.1**: A candidate edge shall be persisted as an `entry_relations` row carrying `metadata.review_status = "pending"` and the candidate score (e.g. `metadata.suggestion_score`); no new table is introduced.
- **R2.2**: The store shall expose a method to list pending candidates (`metadata.review_status = "pending"`), returning endpoint ids, relation type, and score, ordered by score descending.
- **R2.3**: `distillery_relations` shall gain an action to **list** pending relation candidates and an action to **resolve** one: `accept` clears the pending flag (edge becomes a normal live edge), `reject` removes the row. Resolution is idempotent — resolving an already-resolved candidate is a no-op success.
- **R2.4**: Pending candidates shall be excluded from normal `get_related` / traversal results by default (they are not yet real edges), and surfaced only through the candidate-listing action.

**Proof Artifacts:**
- Test: insert a pending candidate via the store helper; the list action returns it and `get_related` (default) does not, demonstrating R2.1/R2.2/R2.4.
- Test: `accept` a pending candidate → it appears in `get_related` and `review_status` is cleared; `reject` another → the row is gone; re-resolving both is a no-op, demonstrating R2.3.

### Unit 3: Scheduled link-suggestion job

**Purpose:** Sweep low-degree/orphan nodes, score candidate edges via `link_prediction` + `find_similar`, auto-create high-confidence `related` edges, and route mid-confidence candidates to the Unit 2 review queue.
**Depends on:** Unit 2
**Affected areas:** `src/distillery/config.py`, `src/distillery/store/protocol.py`, `src/distillery/store/duckdb.py`, `src/distillery/mcp/tools/relations.py`

**Functional Requirements:**
- **R3.1**: Config shall expose a `link_suggestion` block: `enabled` (default `True`), `auto_create_threshold` (default `0.85`, reusing the auto-link bar), `review_floor` (default `0.60`, reusing `dedup_link_threshold`), and `max_candidates_per_run` (a bound, default e.g. `200`). Candidates scoring `>= auto_create_threshold` are auto-created; `[review_floor, auto_create_threshold)` are queued; `< review_floor` are discarded (counted).
- **R3.2**: `distillery_relations` shall gain `action="suggest_links"` that selects low-degree/orphan nodes, generates candidates via `link_prediction` (Adamic-Adar over the adjacency) and `find_similar` over stored embeddings, and applies the R3.1 routing. It performs **no LLM inference**.
- **R3.3**: Auto-created edges use `relation_type="related"` and are idempotent on the unique index; queued candidates are written as Unit 2 pending rows (idempotent — an existing pending or live edge for the same pair is not re-queued).
- **R3.4**: The action shall return counts: `edges_created`, `candidates_queued`, `discarded`, `nodes_scanned`, and respect `max_candidates_per_run` (logging when the bound truncates the sweep — no silent cap).
- **R3.5**: Re-running `suggest_links` immediately after a run creates zero new edges and queues zero new candidates (idempotency / convergence).

**Proof Artifacts:**
- Test: seed a graph with one pair above `auto_create_threshold` and one pair in the review band; after `suggest_links`, assert one new live `related` edge and one pending candidate, with response counts matching, demonstrating R3.1–R3.4.
- Test: run `suggest_links` twice; assert the second run reports `edges_created=0` and `candidates_queued=0`, demonstrating R3.5.

### Unit 4: Wire link-suggestion into /api/maintenance

**Purpose:** Run the link-suggestion job in the scheduled maintenance pipeline alongside poll → rescore → classify-batch.
**Depends on:** Unit 3
**Affected areas:** `src/distillery/mcp/webhooks.py`, `src/distillery/config.py`

**Functional Requirements:**
- **R4.1**: `_run_maintenance` (`webhooks.py:885`) shall add a link-suggestion phase after the existing phases that invokes the Unit 3 `suggest_links` path, gated by `link_suggestion.enabled`.
- **R4.2**: The phase shall reserve its own cooldown (matching the existing per-phase cooldown pattern) and be non-fatal: a failure is logged and reported but does not abort already-completed phases.
- **R4.3**: The `/api/maintenance` JSON response shall include a `link_suggestion` block with the Unit 3 counts; bearer auth is unchanged.
- **R4.4**: The phase shall perform no LLM inference and require no new credentials or external calls.

**Proof Artifacts:**
- Test: `POST /api/maintenance` (authenticated, link-suggestion enabled) with a seeded store; assert the response JSON contains a `link_suggestion` block with the expected count keys, demonstrating R4.1/R4.3.
- Test: with `link_suggestion.enabled = False`, the maintenance response omits/skips the phase and the other phases still run, demonstrating R4.1 gating.

## Non-Goals (Out of Scope)

- A hosted inference agent that auto-clears the relation-candidate review queue (judging which pending candidates are real edges) — tracked as a follow-up issue; this spec only builds the queue and manual accept/reject.
- Promoting `project` / `source` / `author` strings to first-class nodes (the hard "no orphan ever" invariant) — Unit 1 is best-effort semantic linking only.
- Surfacing graph-health metrics (`orphan_rate`, mean degree, component count) in `/briefing` or `radar --structure` — deferred (epic health-metrics item, separate spec).
- New edge types — only the existing `related` type is created; no `about`/`mentions` work here (spec 17 owns `mentions`).
- A formal typed `(from_type, relation, to_type)` triple schema — ontology #1, separate spec.

## Design Considerations

No UI requirements. All surfaces are MCP tool responses, the `/api/maintenance` JSON body, and test assertions.

## Repository Standards

- Python 3.11+, `mypy --strict` on `src/`, `ruff` (line length 100).
- Async store operations via `Protocol` structural typing — extend `store/protocol.py`, implement in `store/duckdb.py`.
- Relation writes use the existing idempotent `(from_id, to_id, relation_type)` unique index and `INSERT OR IGNORE` pattern.
- New MCP behaviour extends existing tools (new `distillery_relations` actions) rather than adding a tool, per the additive-API stability pledge.
- Maintenance phases follow the existing reserve-cooldown / terminal-failure pattern in `webhooks.py:885-1025`.
- Conventional Commits; scopes `store`, `mcp`, `config`, `feeds`.

## Verification

**Project maturity:** Established

**Available commands:**
| Check | Command |
|-------|---------|
| Lint  | `ruff check src/ tests/` |
| Build | `none` (pure Python package) |
| Test  | `pytest` |

**Greenfield bootstrapping:** N/A — all commands available.

Type checking (`mypy --strict src/distillery/`) is enforced in CI and applies to all units.

## Technical Considerations

- Auto-link is already wired into `_sync_store` (`duckdb.py:1665`) and `_sync_store_batch` (`duckdb.py:1760`); the poller stores via `store()`, so Unit 1 is primarily the config-default flip plus tests proving all three paths inherit it. Verify `server.py:183-185,235-237` passes the config through (it does today).
- The relation-candidate queue reuses `entry_relations` + a `metadata.review_status` flag rather than a new table, keeping the migration surface zero. `get_related` and traversal must filter `metadata.review_status = "pending"` out of default results (R2.4) so candidates don't pollute the live graph before resolution.
- `link_prediction` is quadratic when `source` is `None`; the `suggest_links` job must iterate per low-degree/orphan node (bounded source) and respect `max_candidates_per_run`, never scoring all non-existent edges globally.
- Both auto-create and queue paths must be idempotent so the scheduled maintenance run can call them repeatedly. A candidate pair that already has a live edge or a pending row is skipped.
- `find_similar` and `link_prediction` operate on stored embeddings / existing adjacency only — no embedding or LLM inference is triggered by the scheduled path, which is what makes it safe to run headless in cron (Q2 confirmed).

## Security Considerations

No new credentials, tokens, or external calls. The link-suggestion maintenance phase reuses the existing bearer-auth and cooldown machinery. Auto-created and candidate edges derive from already-stored entries and embeddings; no new PII surface.

## Success Metrics

- With auto-link default-on, a newly stored entry with a close neighbour has ≥1 `related` edge immediately after `store()` (no manual `accept_action`).
- `suggest_links` is idempotent: a second consecutive run creates 0 edges and queues 0 candidates.
- After running `suggest_links` on a seeded fixture with orphans, `orphan_rate` measurably decreases and at least one previously-orphan node gains an edge or a pending candidate.
- The `/api/maintenance` response carries link-suggestion counts when enabled and omits the phase when disabled.

## Open Questions

No open questions at this time.
