# 12-spec-team-skills

## Introduction/Overview

Ship four team-oriented skills (`/digest`, `/gh-sync`, `/investigate`, `/briefing`) backed by a first-class entry relationships store concept (#146). This collapses Sprint 3 and Sprint 4 into a single deliverable by deferring NetworkX (#138) and access control (#149) — both are v2 enhancements, not prerequisites.

## Goals

1. `related_entries` promoted from metadata convention to a queryable `entry_relations` table with typed relationships and bidirectional traversal
2. `/digest` generates team activity summaries from internal entries (not feeds)
3. `/gh-sync` syncs GitHub issue/PR content into the knowledge base via REST API
4. `/investigate` compiles deep context by combining semantic search with relationship traversal
5. `/briefing` produces a team dashboard combining digest, metrics, interests, and feed intelligence

## User Stories

- As a **team lead**, I want a weekly digest of what my team captured so that I can track knowledge growth without reading every entry.
- As a **developer**, I want GitHub issues and PRs searchable alongside my session notes so that decisions are traceable across tools.
- As a **developer**, I want to investigate a topic by following connections between entries so that I discover context that keyword search misses.
- As a **team lead**, I want a single briefing command that shows team activity, top signals, and knowledge health so that I have situational awareness.

## Demoable Units of Work

### Unit 1: Entry Relations Store Concept (#146)

**Purpose:** Promote `related_entries` from a metadata JSON field to a queryable relationship table, enabling traversal by all skills.

**Functional Requirements:**
- The system shall add migration 8 creating an `entry_relations` table:
  ```sql
  CREATE TABLE IF NOT EXISTS entry_relations (
      id VARCHAR PRIMARY KEY,
      from_id VARCHAR NOT NULL,
      to_id VARCHAR NOT NULL,
      relation_type VARCHAR NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
  );
  ```
- The system shall add the following methods to `DistilleryStore` protocol and `DuckDBStore`:
  - `add_relation(from_id: str, to_id: str, relation_type: str) -> str` — returns relation ID, validates both entry IDs exist
  - `get_related(entry_id: str, relation_type: str | None = None, direction: str = "both") -> list[dict[str, Any]]` — returns related entries with relation metadata. `direction`: `"outgoing"`, `"incoming"`, or `"both"`
  - `remove_relation(relation_id: str) -> bool`
- The system shall support relation types: `link` (dedup), `merge_source`, `citation`, `sync_source`
- The system shall validate that `from_id` and `to_id` reference existing entries (raise `ValueError` if not found)
- The system shall add a `distillery_relations` MCP tool that wraps `add_relation`, `get_related`, and `remove_relation` via an `action` parameter (pattern matching `distillery_watch`)
- The system shall add a backfill step to migration 8 that scans `metadata.related_entries` on existing entries and inserts corresponding rows into `entry_relations` with type `link`

**Proof Artifacts:**
- Test: `tests/test_relations.py` — CRUD operations on entry_relations table
- Test: Validation rejects non-existent entry IDs
- Test: Bidirectional traversal returns relations from both directions
- Test: Backfill migrates existing metadata.related_entries
- Test: `distillery_relations` MCP tool handler

### Unit 2: /digest — Team Activity Summaries (#150)

**Purpose:** Generate structured summaries of internal team activity, distinct from `/radar`'s external feed digest.

**Functional Requirements:**
- The skill shall accept `--days N` (default 7), `--project <name>`, and `--store` flags
- The skill shall call `distillery_list(entry_type=["session", "bookmark", "minutes", "idea", "reference"], limit=100, date_from=<lookback>)` to retrieve internal entries (explicitly excluding `feed`, `github`, `digest` types)
- The skill shall call `distillery_aggregate(group_by="author", date_from=<lookback>)` for per-author activity counts
- The skill shall call `distillery_aggregate(group_by="entry_type", date_from=<lookback>)` for type distribution
- The skill shall call `distillery_metrics(scope="audit", date_from=<lookback>)` for active user data (when available, non-fatal if absent)
- The skill shall synthesize output into sections: Per-Author Activity, Top Topics (from tag frequency), Key Decisions (entries containing decision-related keywords), Entry Counts
- The skill shall call `distillery_list(total_count=...)` and report "Summarizing N of M entries" using the `total_count` field
- The skill shall follow the standard dedup flow and confirmation format from CONVENTIONS.md when `--store` is specified (store as `entry_type="digest"`)
- The skill shall add `distillery_list`, `distillery_aggregate`, `distillery_metrics`, `distillery_search`, `distillery_store`, `distillery_find_similar` to allowed-tools

**Proof Artifacts:**
- File: `skills/digest/SKILL.md` with complete skill definition
- File: CONVENTIONS.md Skills Registry updated

### Unit 3: /gh-sync — GitHub Issue/PR Knowledge Tracking (#154)

**Purpose:** Sync GitHub issue and PR content into the knowledge base as searchable, linkable entries.

**Functional Requirements:**
- The skill shall accept a repository argument: `/gh-sync owner/repo`, `/gh-sync owner/repo --issues`, `/gh-sync owner/repo --prs`
- The system shall add a `GitHubSyncAdapter` class in `src/distillery/feeds/github_sync.py` that uses the GitHub REST API (not GraphQL — simpler, PAT already works):
  - `GET /repos/{owner}/{repo}/issues?state=all&per_page=100&since=<last_sync>` (issues + PRs share this endpoint; filter by `pull_request` key presence)
  - Fetch issue/PR body, title, labels, state, assignees, comments (top 10 by reactions)
- The system shall store each issue/PR as `entry_type="github"` with metadata: `repo`, `ref_type` ("issue" or "pr"), `ref_number`, `title`, `url`, `state`, `labels`, `assignees`
- The system shall use `external_id` = `{owner}/{repo}#issue-{number}` for dedup (same pattern as feed entries)
- The system shall track last sync timestamp per repo via `store.set_metadata("gh_sync:{owner}/{repo}", <ISO timestamp>)`
- The system shall concatenate title + body + top comments into entry `content`, with markdown separators
- The system shall create `link` relations between issues that reference each other (e.g., "Closes #123" → link from PR entry to issue entry)
- The system shall read `GITHUB_TOKEN` from environment (same pattern as GitHubAdapter)
- The skill shall report: `Synced {N} issues, {M} PRs from {owner}/{repo}. {K} new, {L} updated.`
- The skill shall add `distillery_store`, `distillery_get`, `distillery_update`, `distillery_list`, `distillery_relations` to allowed-tools

**Proof Artifacts:**
- File: `src/distillery/feeds/github_sync.py` with `GitHubSyncAdapter`
- File: `skills/gh-sync/SKILL.md` with complete skill definition
- Test: `tests/test_github_sync.py` — mock API responses, entry creation, dedup, cross-reference linking
- Test: Incremental sync only fetches newer items

### Unit 4: /investigate — Deep Context Builder (#153, v1 without NetworkX)

**Purpose:** Compile comprehensive context on a topic by combining semantic search with relationship traversal.

**Functional Requirements:**
- The skill shall accept a topic argument or `--entry <id>` to start from a specific entry
- The skill shall execute a 4-phase retrieval:
  - **Phase 1 — Seed**: `distillery_search(query=<topic>, limit=20)` (or `distillery_get(<entry_id>)` if starting from an entry)
  - **Phase 2 — Expand relationships**: For each seed entry, call `distillery_relations(action="get", entry_id=<id>)` to discover linked entries. Fetch any not already in the result set via `distillery_get`.
  - **Phase 3 — Tag expansion**: Same pattern as `/pour` Pass 2 — use `distillery_tag_tree` to find related tag namespaces, search for them.
  - **Phase 4 — Gap fill**: Identify people, projects, or topics mentioned in content but not yet represented. Run targeted searches (up to 3).
- The skill shall deduplicate across all phases by entry ID
- The skill shall produce a structured output: Context Summary (narrative), Relationship Map (text-based: entry → related entries with relation types), Timeline, Key People (authors + mentioned), Knowledge Gaps
- The skill shall report: `Investigated "<topic>": {N} entries across {M} phases, {K} relationship edges traversed.`
- The skill shall add `distillery_search`, `distillery_get`, `distillery_relations`, `distillery_tag_tree`, `distillery_list`, `distillery_metrics` to allowed-tools

**Proof Artifacts:**
- File: `skills/investigate/SKILL.md` with complete skill definition
- File: CONVENTIONS.md Skills Registry updated

### Unit 5: /briefing — Team Knowledge Dashboard (#155, v1)

**Purpose:** Single-command team overview combining activity, feed intelligence, metrics, and knowledge health.

**Functional Requirements:**
- The skill shall accept `--project <name>` and `--days N` (default 7) flags
- The skill shall gather data from multiple tools in sequence:
  1. `distillery_metrics(scope="summary")` — entry counts, DB size, embedding model
  2. `distillery_metrics(scope="audit", date_from=<lookback>)` — active users, login summary
  3. `distillery_list(entry_type=["session", "bookmark", "minutes"], limit=50, date_from=<lookback>)` — recent internal activity
  4. `distillery_aggregate(group_by="author", date_from=<lookback>)` — per-author counts
  5. `distillery_interests(recency_days=<days>, top_n=10, suggest_sources=true)` — interest profile + suggestions
  6. `distillery_search(query=<top interest>, entry_type="feed", limit=5, date_from=<lookback>)` — top feed signals
- The skill shall synthesize into sections: System Health (metrics), Team Activity (who did what), Top Interests (trending topics), Feed Highlights (top external signals), Suggested Actions (stale entries, suggested sources, review queue count)
- The skill shall not store output by default (display-only, like `/radar`)
- The skill shall add all read tools to allowed-tools: `distillery_metrics`, `distillery_list`, `distillery_aggregate`, `distillery_interests`, `distillery_search`, `distillery_stale`, `distillery_tag_tree`

**Proof Artifacts:**
- File: `skills/briefing/SKILL.md` with complete skill definition
- File: CONVENTIONS.md Skills Registry updated with all 4 new skills

## Non-Goals (Out of Scope)

- NetworkX graph analysis (#138) — deferred to v2 enhancement
- Access control / entry visibility (#149) — deferred
- Hidden connections tool (#140) — deferred (requires #138 for full value)
- `/whois` skill (#152) — requires NetworkX centrality for evidence ranking
- `/process` skill (#151) — batch pipeline, independent of team skills
- GraphQL API for /gh-sync — REST API is sufficient and simpler
- Real-time webhook sync for GitHub — polling/manual trigger only

## Design Considerations

No UI requirements. All skills are SKILL.md files following CONVENTIONS.md patterns. The `entry_relations` table and MCP tool are the only code changes.

## Repository Standards

- Conventional Commits: `feat(store): ...`, `feat(skills): ...`, `feat(feeds): ...`
- mypy `--strict` on all `src/` code
- ruff with line-length 100
- pytest markers: `@pytest.mark.unit`, `@pytest.mark.integration`
- Coverage >= 80%
- All store methods async via `asyncio.to_thread`
- Migrations: forward-only, idempotent, transactional

## Technical Considerations

- **entry_relations table**: Separate table (not a list column) enables typed relationships, bidirectional queries, and clean indexing. Migration 8 creates the table and backfills from `metadata.related_entries`.
- **GitHub REST vs GraphQL**: REST API is simpler, already authenticated via `GITHUB_TOKEN`, and supports `since` parameter for incremental sync. GraphQL would be more efficient for bulk fetching but adds client complexity.
- **Incremental sync state**: Stored in `_meta` table as `gh_sync:{owner}/{repo}` → ISO timestamp. Same pattern as webhook cooldowns.
- **Cross-reference parsing**: Parse `#123`, `Closes #123`, `Fixes #123` patterns in issue/PR bodies to create `link` relations between entries. Regex-based, no NLP needed.
- **Relationship traversal depth**: `/investigate` Phase 2 follows relationships one hop by default. Configurable via `--depth N` in future, but v1 does single-hop to avoid explosion.
- **Skills depend on Unit 1**: Units 3 and 4 use `distillery_relations`. Unit 1 must be implemented first. Units 2 and 5 have no dependency on Unit 1.

## Security Considerations

- `GITHUB_TOKEN` used by `/gh-sync` — same redaction patterns as existing GitHubAdapter
- Issue/PR content may contain sensitive information — stored as `entry_type="github"` entries, subject to same access rules as other entries
- No new secrets or credentials beyond existing `GITHUB_TOKEN`

## Success Metrics

- All 4 skills functional and documented
- `entry_relations` table populated with dedup link relationships from existing entries
- `/gh-sync` successfully syncs issues and PRs from a real repository
- `/briefing` produces a coherent team dashboard in under 30 seconds
- All new code passes mypy strict and ruff checks
- Test coverage remains >= 80%

## Open Questions

- Should `/gh-sync` fetch PR review comments (adds complexity, many API calls) or just the PR body + top issue comments?
- Should `/investigate` relationship traversal be depth-limited by default (1 hop) or expand until no new entries are found (risk: explosion on densely connected entries)?
