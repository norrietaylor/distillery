# 07-spec-tool-consolidation

## Introduction/Overview

Consolidate the Distillery MCP tool surface from 22 tools to 16 by merging 5 groups of functionally overlapping tools. This reduces token overhead for LLM callers, simplifies API discovery, and eliminates redundant code paths. All removals are hard (no deprecation aliases) with immediate updates to skills, eval scenarios, and tests.

## Goals

1. Reduce the MCP tool count from 22 to 16 by removing 6 redundant tools
2. Extend remaining tools with optional parameters to absorb functionality of removed tools
3. Update all 10 skill SKILL.md files to reference consolidated tool names/parameters
4. Update eval scenarios (YAML + promptfoo) and all tests to reflect new tool surface
5. Maintain full backward compatibility at the protocol layer — no changes to store/protocol interfaces

## User Stories

- As a **skill author**, I want fewer tools to choose from so that I can find the right tool faster and reduce prompt complexity.
- As an **LLM caller**, I want a smaller tool surface so that tool schemas consume fewer context tokens.
- As a **contributor**, I want less duplicated handler code so that changes to shared logic only need to happen in one place.

## Demoable Units of Work

### Unit 1: Observability Consolidation — `metrics` absorbs `status` and `quality`

**Purpose:** Merge 3 overlapping observability tools into one, reducing the tool count by 2.

**Functional Requirements:**
- `distillery_metrics` shall accept an optional `scope` parameter with values `"summary"` | `"full"` | `"search_quality"` (default: `"full"`).
  - `"summary"`: returns entry counts by type/status, database size, embedding model info (current `status` output)
  - `"full"`: returns the complete metrics payload — entries, activity, search, quality, staleness, storage (current `metrics` behavior)
  - `"search_quality"`: returns search totals, feedback rates, quality breakdown (current `quality` output)
- The `_handle_status` and `_handle_quality` handlers shall be removed from `src/distillery/mcp/tools/crud.py` and `src/distillery/mcp/tools/analytics.py` respectively.
- The `distillery_status` and `distillery_quality` MCP tool registrations shall be removed from the server.
- The `_handle_metrics` handler in `analytics.py` shall be extended to handle all 3 scopes.
- All skills that call `distillery_status` (every skill calls it for health checks per CONVENTIONS.md) shall be updated to call `distillery_metrics(scope="summary")`.
- Skills that call `distillery_quality` (webhook maintenance) shall call `distillery_metrics(scope="search_quality")`.
- CONVENTIONS.md shall update the health check pattern from `distillery_status` to `distillery_metrics(scope="summary")`.

**Proof Artifacts:**
- CLI: `grep -r 'distillery_status\|distillery_quality' src/distillery/mcp/` returns no tool registrations
- File: All 10 SKILL.md files reference `distillery_metrics` not `distillery_status`
- Test: `pytest tests/test_mcp_analytics.py -v` passes with scope parameter tests

### Unit 2: Similarity Consolidation — `find_similar` absorbs `check_dedup` and `check_conflicts`

**Purpose:** Merge 3 similarity-based tools into one, reducing the tool count by 2.

**Functional Requirements:**
- `distillery_find_similar` shall accept the following optional parameters:
  - `dedup_action: bool = False` — when true, include a `dedup` field in the response with `action` (`"create"` | `"skip"` | `"merge"` | `"link"`) and `similar_entries` list, matching current `check_dedup` output format.
  - `conflict_check: bool = False` — when true, include a `conflict_prompt` field alongside each similar entry for LLM-based conflict resolution (current `check_conflicts` pass 1).
  - `llm_responses: list[dict] | None = None` — when provided, execute conflict resolution pass 2 using the LLM responses (current `check_conflicts` pass 2).
- The `_handle_check_dedup` handler in `quality.py` and `_handle_check_conflicts` handler in `quality.py` shall be removed.
- The `distillery_check_dedup` and `distillery_check_conflicts` tool registrations shall be removed.
- The `_handle_find_similar` handler in `search.py` shall be extended to support dedup and conflict modes.
- All skills that call `distillery_check_dedup` (`/distill`, `/bookmark`, `/minutes`, `/radar` per spec 05) shall call `distillery_find_similar(content=..., dedup_action=true)` instead.
- Skills or handlers that call `distillery_check_conflicts` shall call `distillery_find_similar(content=..., conflict_check=true)` instead.

**Proof Artifacts:**
- CLI: `grep -r 'check_dedup\|check_conflicts' src/distillery/mcp/` returns no tool registrations
- File: `/distill`, `/bookmark` SKILL.md files call `distillery_find_similar(dedup_action=true)`
- Test: `pytest tests/test_mcp_server.py tests/test_mcp_dedup.py tests/test_mcp_conflicts.py -v` all pass

### Unit 3: List/Interests Consolidation + Eval Updates

**Purpose:** Merge `review_queue` into `list`, `suggest_sources` into `interests`, remove both tools, and update all eval scenarios.

**Functional Requirements:**
- `distillery_list` shall accept an optional `output_mode` parameter with values `"default"` | `"review"` (default: `"default"`).
  - `"review"`: filters to `status="pending_review"` and enriches results with `confidence` and `classification_reasoning` from entry metadata (current `review_queue` behavior).
- The `_handle_review_queue` handler in `classify.py` shall be removed.
- The `distillery_review_queue` tool registration shall be removed.
- Skills that call `distillery_review_queue` (`/classify`) shall call `distillery_list(status="pending_review", output_mode="review")` instead.
- `distillery_interests` shall accept optional parameters:
  - `suggest_sources: bool = False` — when true, append feed source suggestions to the response.
  - `max_suggestions: int = 5` — maximum number of source suggestions to return.
- The `_handle_suggest_sources` handler in `analytics.py` shall be removed.
- The `distillery_suggest_sources` tool registration shall be removed.
- Skills/handlers that call `distillery_suggest_sources` (`/radar`, webhook maintenance) shall call `distillery_interests(suggest_sources=true)` instead.
- All eval scenario YAML files in `tests/eval/scenarios/` that reference removed tools shall be updated to use the consolidated tool names and parameters.
- The `promptfooconfig.yaml` shall be updated to reference consolidated tools in its assertions.
- The `allowed-tools` lists in all 10 SKILL.md frontmatter shall be updated to remove references to deleted tools and add any newly required tools.
- The `mcp_bridge.py` eval bridge shall be updated to remove dispatch entries for deleted tools and add parameter handling for new optional params.

**Proof Artifacts:**
- CLI: `grep -r 'review_queue\|suggest_sources' src/distillery/mcp/` returns no tool registrations
- CLI: `distillery-mcp` starts and reports 16 registered tools (down from 22)
- Test: `pytest -m unit --tb=short -q` passes with all tests updated
- Test: `pytest -m eval --tb=short -q` passes (eval scenarios reference new tool names)
- File: `promptfooconfig.yaml` contains no references to removed tools

## Non-Goals (Out of Scope)

- Changes to the store/protocol layer — this is MCP tool surface only
- Removing `stale` (access-time filter not available via `list`)
- Removing `aggregate` (flexible GROUP BY distinct from fixed `metrics` output)
- Removing `rescore` (feed-specific operation, no overlap)
- Adding new tools — this is consolidation only
- Deprecation aliases — hard removal per user decision

## Design Considerations

No specific design requirements identified. Tool parameter additions follow existing FastMCP patterns (optional params with defaults).

## Repository Standards

- **Conventional Commits**: `refactor(mcp):` for tool consolidation, `chore(skills):` for skill updates, `test(eval):` for eval updates
- **mypy --strict** on all modified `src/` files
- **ruff** formatting on all modified files
- All new optional parameters shall have type annotations and defaults

## Technical Considerations

- **Domain module locations**: Post-MCP-refactor (PR #106), handlers live in `src/distillery/mcp/tools/`:
  - `crud.py` — status, store, get, update, list
  - `search.py` — search, find_similar
  - `classify.py` — classify, review_queue, resolve_review
  - `quality.py` — check_dedup, check_conflicts
  - `analytics.py` — metrics, quality, stale, tag_tree, interests, suggest_sources, type_schemas
  - `feeds.py` — watch, poll, rescore
- **`quality.py` may become empty**: After removing `check_dedup` and `check_conflicts`, `quality.py` has no handlers. Either delete it or repurpose it for the dedup/conflict logic as helper functions imported by `search.py`.
- **Skill `allowed-tools` updates**: Spec 04 added `allowed-tools` to all skills. These lists reference tool names like `mcp__*__distillery_check_dedup` — all must be updated to `mcp__*__distillery_find_similar`.
- **CONVENTIONS.md health check**: Currently says "call `distillery_status` once per conversation." Must update to `distillery_metrics(scope="summary")`.
- **Webhook handlers**: `webhooks.py` calls `_handle_metrics`, `_handle_quality`, `_handle_stale`, `_handle_interests`, `_handle_suggest_sources`. These internal calls must be updated too.

## Security Considerations

- No new security concerns. Tool consolidation doesn't change authorization or data access patterns.
- Ensure `find_similar` with `conflict_check=true` doesn't expose LLM prompt content that shouldn't be visible to the caller (verify existing `check_conflicts` behavior is safe).

## Success Metrics

| Metric | Target |
|--------|--------|
| Tool count | 16 (down from 22) |
| Removed tools | `status`, `quality`, `check_dedup`, `check_conflicts`, `review_queue`, `suggest_sources` |
| Skills updated | 10/10 SKILL.md + CONVENTIONS.md |
| Tests passing | All unit + eval tests |
| Eval scenarios updated | All YAML + promptfoo configs |

## Open Questions

No open questions at this time.
