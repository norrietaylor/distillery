# T04 Proof Summary — /classify Skill

**Task:** T04: /classify Skill -- Manual Classification & Review Queue
**Spec:** docs/specs/03-spec-distillery-classification/03-spec-distillery-classification.md
**Feature file:** docs/specs/03-spec-distillery-classification/classify-skill.feature
**Completed:** 2026-03-22

## Deliverable

Created `.claude/skills/classify/SKILL.md` — a Claude Code skill file for classifying
knowledge entries and triaging the manual review queue.

## Proof Artifacts

| File | Type | Status | Description |
|------|------|--------|-------------|
| T04-01-file.txt | file | PASS | SKILL.md existence, frontmatter, sections, MCP tool references, confidence levels |
| T04-02-file.txt | file | PASS | YAML structure, CONVENTIONS.md compliance, feature spec coverage |

## Implementation Summary

The skill implements four modes:

1. **Classify by ID** (`/classify <entry_id>`): Retrieves the entry via `distillery_get`,
   computes a classification, calls `distillery_classify`, and displays the result with
   confidence percentage and level label. Shows old vs. new for reclassifications. Notes
   when entry is sent to review queue due to low confidence.

2. **Batch inbox** (`/classify --inbox`): Lists `entry_type=inbox` entries via
   `distillery_list`, classifies each using `distillery_classify`, and displays a markdown
   summary table with totals (classified/review/errors).

3. **Review queue** (`/classify --review`): Fetches `distillery_review_queue`, displays each
   pending entry with preview and metadata, prompts for approve/reclassify/archive/skip per
   entry, calls `distillery_resolve_review`, and displays a final triage summary.

4. **Help** (no arguments): Displays usage with examples for all three modes.

## Pattern Compliance

- Follows `.claude/skills/CONVENTIONS.md` structure: YAML frontmatter, Prerequisites, When to Use,
  Process (numbered steps), Output Format, Rules
- Consistent MCP unavailability check (Step 1 in all modes)
- Error display format matches other skills (`Error:` prefix with `Suggested Action:` block)
- Confidence formatting: percentage with high/medium/low label at defined thresholds (>=80%, 50-79%, <50%)
- Reviewer identity follows same priority as author: git config > env var > ask user
- Provenance line format matches CONVENTIONS.md: `ID: ... | Author: ... | Project: ... | <date>`

## Test Baseline

All 384 existing tests pass (no Python changes required — skill is SKILL.md only).
