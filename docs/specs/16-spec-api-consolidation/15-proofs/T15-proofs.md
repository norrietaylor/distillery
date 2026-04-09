# T15 Proof Summary — Update all skill SKILL.md files for 12-tool surface

**Task**: T04.2 — Update all 14 skill SKILL.md files to reference the consolidated 12-tool API surface.

**Executed**: 2026-04-09
**Status**: PASS

## Proof Artifacts

| File | Type | Status | Description |
|------|------|--------|-------------|
| T15-01-grep.txt | cli | PASS | No removed tool references remain in SKILL.md files |
| T15-02-tools-audit.txt | file | PASS | All frontmatter tools are from the valid 12-tool set |
| T15-03-logic-changes.txt | file | PASS | All logic replacements verified per task requirements |

## Summary of Changes

### Frontmatter `allowed-tools` Updates (14 skills)

Removed from all skill frontmatter:
- `distillery_stale` (was in: briefing)
- `distillery_aggregate` (was in: briefing, digest)
- `distillery_tag_tree` (was in: investigate, pour)
- `distillery_metrics` (was in: bookmark, briefing, classify, digest, distill, investigate, minutes, pour, radar, recall, setup, tune, watch)
- `distillery_interests` (was in: radar)

### Skill Logic Updates

- **briefing**: `distillery_stale` → `distillery_list(stale_days=30)`, `distillery_aggregate(group_by="author")` → `distillery_list(group_by="author", output_mode="stats")`
- **digest**: `distillery_aggregate(group_by=...)` → `distillery_list(group_by=..., output_mode="stats")`, removed `distillery_metrics` audit call
- **investigate**: Phase 3 `distillery_tag_tree` → `distillery_list(group_by="tags", output_mode="stats")`
- **pour**: Tag expansion `distillery_tag_tree` → `distillery_list(group_by="tags", output_mode="stats")`
- **radar**: Interest profile `distillery_interests` → `distillery_list(group_by="tags", output_mode="stats")`, source suggestions now heuristic, empty-results guidance updated
- **setup**: Health check `distillery_metrics` → `distillery_list(limit=1)` + `distillery_configure`, cron prompts updated to webhook URLs (`/hooks/poll`, `/hooks/rescore`, `/hooks/classify-batch`)
- **tune**: Threshold read `distillery_metrics` → `distillery_configure(action="get", section="feeds.thresholds")`
- **watch**: CronCreate prompt updated to use `/hooks/poll` webhook URL

### Skills with Only Frontmatter Changes (no logic needed)

- bookmark, classify, distill, gh-sync, minutes, recall — only removed `distillery_metrics` from allowed-tools
