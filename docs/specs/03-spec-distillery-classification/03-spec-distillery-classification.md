# 03-spec-distillery-classification: Classification Pipeline & Semantic Deduplication

## Introduction/Overview

The classification pipeline is the intelligence layer that transforms raw knowledge entries into well-typed, deduplicated, confidence-scored records. It provides LLM-based auto-classification of entry types, semantic deduplication to prevent knowledge base pollution from repeated `/distill` calls, a team review queue for low-confidence classifications, and a `/classify` skill for manual invocation. This spec completes the Phase 1 MVP alongside the storage layer (spec 01) and skills layer (spec 02).

## Goals

1. Implement an LLM-based classification pipeline that assigns `entry_type`, confidence score, and reasoning to entries
2. Add semantic deduplication logic with configurable score thresholds (skip/merge/create decisions) integrated into `/distill`
3. Expose classification operations through new MCP server tools (`distillery_classify`, `distillery_review_queue`)
4. Ship a `/classify` Claude Code skill for manual classification and review queue triage
5. Extend the config system with deduplication thresholds and classification settings

## User Stories

- As a team member, I want `/distill` to automatically detect and handle duplicate knowledge so the KB stays clean without manual effort
- As a team member, I want to run `/classify` on inbox entries so they get properly typed with confidence scores
- As a team lead, I want to review low-confidence classifications so I can correct the classifier and improve accuracy over time
- As a team member, I want entries classified below the confidence threshold to be flagged for review rather than silently miscategorized

## Demoable Units of Work

### Unit 1: Classification Engine & Deduplication Logic (Python Module)

**Purpose:** Implement the core classification and deduplication logic as a Python module that the MCP server and skills consume.

**Functional Requirements:**

*Classification Engine:*
- The system shall implement a `ClassificationEngine` class in `src/distillery/classification/engine.py`
- The engine shall accept raw content text and return a `ClassificationResult` dataclass containing: `entry_type` (EntryType enum), `confidence` (float 0.0-1.0), `reasoning` (str explaining the classification), `suggested_tags` (list[str]), and `suggested_project` (str | None)
- The engine shall use an LLM prompt (stored as a constant in the module) that analyzes content and outputs structured JSON with the classification fields
- The prompt shall include descriptions of all valid entry types (session, bookmark, minutes, meeting, reference, idea, inbox) with examples of each
- The engine shall parse the LLM's JSON response and validate it against expected types and ranges
- If confidence is below the configured `classification.confidence_threshold` (default 0.6), the engine shall set the entry's status to `pending_review`
- If confidence is at or above the threshold, the engine shall set the entry's status to `active`
- The engine shall be callable both synchronously (for use in MCP tool handlers) and asynchronously
- The engine shall handle LLM response parsing failures gracefully, defaulting to `entry_type: inbox`, `confidence: 0.0`, `status: pending_review`

*Deduplication Logic:*
- The system shall implement a `DeduplicationChecker` class in `src/distillery/classification/dedup.py`
- The checker shall accept content text and use `DistilleryStore.find_similar()` to find existing entries
- The checker shall return a `DeduplicationResult` dataclass containing: `action` (enum: `skip`, `merge`, `link`, `create`), `similar_entries` (list of SearchResult), `highest_score` (float), and `reasoning` (str)
- Deduplication thresholds (configurable in `distillery.yaml` under `classification`):
  - `dedup_skip_threshold` (default 0.95): Score at or above this means content is a duplicate — recommend skip
  - `dedup_merge_threshold` (default 0.80): Score between merge and skip thresholds — recommend merging with the most similar existing entry
  - `dedup_link_threshold` (default 0.60): Score between link and merge thresholds — recommend creating new entry but linking to related entries via metadata
  - Below link threshold: content is novel — recommend creating a new entry
- The checker shall populate `reasoning` with a human-readable explanation of why the action was chosen, including the highest similarity score and the most similar entry's first line
- The checker shall respect a configurable `dedup_limit` (default 5) for how many similar entries to return

*Shared Data Models:*
- `ClassificationResult` and `DeduplicationResult` dataclasses shall be defined in `src/distillery/classification/models.py`
- `DeduplicationAction` enum (`skip`, `merge`, `link`, `create`) shall be defined in the same module

**Proof Artifacts:**
- Test: `tests/test_classification_engine.py` passes — demonstrates classification with mocked LLM responses for each entry type, confidence thresholding, and parse failure handling
- Test: `tests/test_dedup.py` passes — demonstrates all four dedup actions (skip/merge/link/create) at different similarity score levels using a mock store
- File: `src/distillery/classification/__init__.py`, `engine.py`, `dedup.py`, `models.py` exist

### Unit 2: MCP Server Extensions (classify & review_queue tools)

**Purpose:** Add two new MCP server tools that expose classification and review queue operations to Claude Code skills.

**Functional Requirements:**

*distillery_classify tool:*
- The tool shall accept: `entry_id` (str, required) — the ID of an entry to classify
- The tool shall retrieve the entry via `distillery_get`, run it through the `ClassificationEngine`, and update the entry via `distillery_update` with:
  - `entry_type`: the classified type
  - `metadata.confidence`: the confidence score
  - `metadata.classified_at`: ISO 8601 timestamp of classification
  - `metadata.classification_reasoning`: the reasoning text
  - `tags`: merged with any `suggested_tags` from the classifier (no duplicates)
  - `project`: set to `suggested_project` if the entry's project was previously None
  - `status`: `active` if confidence >= threshold, `pending_review` if below
- The tool shall return the updated entry data plus classification details
- If the entry is already classified (has `metadata.confidence`), the tool shall reclassify and note it as a reclassification in the response
- If the entry ID does not exist, the tool shall return a structured error

*distillery_review_queue tool:*
- The tool shall accept: `limit` (int, default 10), `entry_type` (str, optional filter)
- The tool shall call `distillery_list` with `status: "pending_review"` filter, plus any additional entry_type filter
- The tool shall return the list of entries awaiting review, sorted by `created_at` descending (newest first)
- Each entry in the response shall include: id, content (first 200 chars), entry_type, confidence, author, created_at, classification_reasoning

*distillery_resolve_review tool:*
- The tool shall accept: `entry_id` (str), `action` (str: `approve`, `reclassify`, `archive`), and optional `new_entry_type` (str, required if action is `reclassify`)
- `approve`: set status to `active`, add `metadata.reviewed_at` and `metadata.reviewed_by` (from caller)
- `reclassify`: update `entry_type` to the new value, set status to `active`, set `metadata.reclassified_from` to the old type, add `metadata.reviewed_at`
- `archive`: soft-delete via `distillery_delete` (sets status to `archived`)
- The tool shall return the updated entry or confirmation of archival

**Proof Artifacts:**
- Test: `tests/test_mcp_classify.py` passes — demonstrates classify, review_queue, and resolve_review tools via MCP client test harness with mocked classification engine
- File: Updated `src/distillery/mcp/server.py` contains the 3 new tool registrations (10 total tools)

### Unit 3: Config Extensions & Dedup Integration into /distill

**Purpose:** Extend the configuration system with dedup thresholds and integrate the dedup checker into the `/distill` skill flow.

**Functional Requirements:**

*Config Extensions:*
- The `ClassificationConfig` dataclass shall be extended with:
  - `dedup_skip_threshold: float = 0.95`
  - `dedup_merge_threshold: float = 0.80`
  - `dedup_link_threshold: float = 0.60`
  - `dedup_limit: int = 5`
- The `_parse_classification` function shall load these new fields from `distillery.yaml`
- The `_validate` function shall verify: `0 <= link_threshold <= merge_threshold <= skip_threshold <= 1.0`
- `distillery.yaml.example` shall be updated with the new classification section

*Dedup MCP Tool:*
- A new `distillery_check_dedup` MCP tool shall accept: `content` (str), and return the `DeduplicationResult` (action, similar entries, reasoning)
- This tool wraps the `DeduplicationChecker` class and reads thresholds from config

*/distill Skill Update:*
- The `/distill` SKILL.md shall be updated to replace its current simple `find_similar` check with the full dedup flow:
  1. Call `distillery_check_dedup` with the distilled content
  2. Based on the returned `action`:
     - `skip`: Display the duplicate entry and confirm with user ("This appears to be a duplicate of [entry]. Skip storing?")
     - `merge`: Display the similar entry and offer to merge ("This overlaps significantly with [entry]. Merge new content into the existing entry?"). If yes, call `distillery_update` to append content
     - `link`: Proceed with storing, but add `metadata.related_entries` containing the IDs of linked entries
     - `create`: Proceed with storing normally
  3. After storing (for merge/link/create), run classification via `distillery_classify` on the new/updated entry

**Proof Artifacts:**
- Test: `tests/test_config.py` updated — demonstrates new dedup threshold fields load correctly and validation catches invalid ordering
- Test: `tests/test_mcp_dedup.py` passes — demonstrates `distillery_check_dedup` tool returns correct actions at various similarity levels
- File: Updated `.claude/skills/distill/SKILL.md` contains the full dedup flow
- File: Updated `distillery.yaml.example` contains dedup threshold configuration

### Unit 4: /classify Skill — Manual Classification & Review Queue

**Purpose:** Ship the `/classify` Claude Code skill for classifying entries and triaging the review queue.

**Functional Requirements:**

*Invocation and Modes:*
- The skill shall be defined in `.claude/skills/classify/SKILL.md` with YAML frontmatter containing `name: classify` and a description that triggers on "classify", "categorize", "review queue", "triage"
- The skill shall support three modes:
  1. **Classify by ID:** `/classify <entry_id>` — classify a specific entry
  2. **Batch classify inbox:** `/classify --inbox` — find all `inbox`-type entries and classify them
  3. **Review queue:** `/classify --review` — display the review queue and enable triage

*Classify by ID Mode:*
- Call `distillery_classify` with the entry ID
- Display the classification result: entry type, confidence (as percentage), reasoning, suggested tags
- If confidence is below threshold, note that the entry has been sent to the review queue
- If the entry was already classified, show both old and new classification for comparison

*Batch Inbox Mode:*
- Call `distillery_list` with `entry_type: "inbox"` to find unclassified entries
- For each entry, call `distillery_classify`
- Display a summary table: entry ID (short), content preview (first 80 chars), assigned type, confidence
- Report totals: N classified, M sent to review queue, K already classified

*Review Queue Mode:*
- Call `distillery_review_queue` to get pending entries
- Display each entry with: ID, content preview, current classification, confidence, reasoning
- For each entry, ask the user: approve (accept classification), reclassify (choose new type), or archive (remove)
- Call `distillery_resolve_review` with the user's choice
- After processing all entries (or user exits), display summary: N approved, M reclassified, K archived

*Output Format:*
- Use markdown tables for batch results
- Use headers and provenance lines consistent with other skills (ID, author, timestamp)
- Display confidence as percentage with color-coding guidance: >= 80% "high", 60-79% "medium", < 60% "low"

*Error Handling:*
- Check MCP availability (same pattern as other skills via `distillery_status`)
- If no arguments provided, display help showing the three modes
- Handle missing entry IDs with clear error messages

**Proof Artifacts:**
- File: `.claude/skills/classify/SKILL.md` exists with correct frontmatter and complete instructions
- Test: Manual invocation of `/classify <id>` classifies an entry; `/classify --review` displays the queue and allows triage

## Non-Goals (Out of Scope)

- **Automated classification on every store** — for MVP, classification is manual via `/classify` or triggered by `/distill`. Background auto-classification of all new entries is deferred.
- **Classification model training** — the LLM prompt is static. Fine-tuning or prompt optimization from correction data is deferred.
- **Hierarchical taxonomy/namespace** — Elastic Brain-style `/project/billing-v2/decisions` paths are Phase 2. MVP uses flat tags.
- **Dirty detection** — auto-reclassification when entry content changes (brainstorm mentions `modified > classified_at`) is deferred.
- **Correction rate tracking** — metrics on how often human review changes classifier output. Useful but deferred to Phase 2.
- **Stale entry detection** — identifying entries from inactive projects. Deferred to Phase 2 `/process` skill.
- **Phase 2/3 skills** — `/whois`, `/investigate`, `/digest`, `/briefing`, `/process`, `/gh-sync`, `/radar`, `/watch`, `/tune`

## Design Considerations

No GUI. All interaction through Claude Code skills connecting to the MCP server.

- The review queue is displayed as a markdown list in the Claude Code terminal via `/classify --review`
- Confidence percentages use plain text (no color — terminal markdown only)
- Classification reasoning is shown inline to help users understand and correct the classifier
- Dedup warnings in `/distill` show the similar entry's full content so users can make informed skip/merge decisions

## Repository Standards

- Classification module lives in `src/distillery/classification/` following existing package structure
- Python 3.11+, mypy strict, ruff, pytest with pytest-asyncio
- Type hints on all public functions, docstrings on all public classes and methods
- New MCP tools follow existing tool patterns in `server.py` (input validation, structured error responses, JSON serialization)
- New tests follow existing patterns (`test_mcp_server.py` style for MCP tools, dedicated test files per module)
- Skill follows `.claude/skills/<name>/SKILL.md` convention and references `CONVENTIONS.md`

## Technical Considerations

- **LLM classification is prompt-based.** The `ClassificationEngine` constructs a prompt with entry content and type descriptions, then parses structured JSON output. It does NOT call an external LLM API directly — it uses the MCP tool's execution context (Claude is already the LLM). The engine formats the prompt and expected output structure; the actual LLM inference happens when the `/classify` skill reads the prompt and generates the classification.
- **Classification is a skill-level operation.** The `distillery_classify` MCP tool stores the classification *result* — it does not run LLM inference itself. The `/classify` skill generates the classification using its own LLM reasoning, then calls `distillery_classify` to persist it. This avoids adding LLM API dependencies to the MCP server.
- **Dedup thresholds differ from brainstorm.** The brainstorm used Elastic Brain's raw similarity scores (20+/10-15/<10). Distillery uses cosine similarity normalized to [0,1], so thresholds are 0.95/0.80/0.60 respectively.
- **Config backward compatibility.** New `ClassificationConfig` fields have defaults, so existing `distillery.yaml` files work without changes.
- **Metadata as extension point.** Classification data (`confidence`, `classified_at`, `classification_reasoning`, `reclassified_from`, `reviewed_at`, `reviewed_by`, `related_entries`) is stored in the `metadata` dict, not as top-level Entry fields. This avoids schema migrations.
- **MCP tool count.** Server grows from 7 to 11 tools (adding `distillery_classify`, `distillery_review_queue`, `distillery_resolve_review`, `distillery_check_dedup`).

## Security Considerations

- No new API keys or credentials introduced — classification uses the in-context LLM
- Review queue entries are team-visible (consistent with all-team-visible MVP policy)
- No PII handling beyond existing author names
- Classification reasoning may contain content summaries — same sensitivity level as the entries themselves

## Success Metrics

- All new test files pass with `pytest`
- `mypy --strict` passes on all source files including new classification module
- `ruff check` passes with zero errors
- `distillery_classify` MCP tool correctly stores classification metadata on entries
- `distillery_review_queue` returns entries with `status: pending_review`
- `distillery_resolve_review` transitions entries to correct status
- `distillery_check_dedup` returns correct actions at each threshold level
- `/classify` skill successfully classifies entries, processes inbox, and enables review queue triage
- `/distill` skill uses full dedup flow instead of simple `find_similar` check
- Config loads new dedup thresholds and validates ordering constraints

## Open Questions

1. **Classification prompt tuning** — The initial prompt will need iteration based on real usage. Track cases where human review changes the classification to identify prompt improvement opportunities. For MVP, ship a reasonable prompt and iterate.
2. **Merge strategy for dedup** — When merging duplicate content, should the new content be appended below the existing content, or should it replace it? For MVP: append under a `## Merged — <timestamp>` heading (similar to `/minutes --update` pattern).
3. **Batch classification limits** — `/classify --inbox` with many entries could be slow. For MVP, process up to 20 entries per invocation and report if more remain. Background batch processing is Phase 2 (`/process` skill).
