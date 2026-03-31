# Skills Overview

Distillery provides 10 Claude Code slash commands organized into three categories: knowledge capture, knowledge retrieval, and ambient intelligence.

## Knowledge Capture

| Skill | Purpose |
|-------|---------|
| [`/distill`](distill.md) | Capture decisions, insights, and action items from working sessions |
| [`/bookmark`](bookmark.md) | Save URLs with auto-generated summaries |
| [`/minutes`](minutes.md) | Create and update structured meeting notes |

## Knowledge Retrieval

| Skill | Purpose |
|-------|---------|
| [`/recall`](recall.md) | Semantic search over the knowledge base |
| [`/pour`](pour.md) | Multi-entry synthesis with citations and gap analysis |
| [`/classify`](classify.md) | Classify entries by type and triage the review queue |

## Ambient Intelligence

| Skill | Purpose |
|-------|---------|
| [`/watch`](watch.md) | Manage monitored feed sources (GitHub, RSS) |
| [`/radar`](radar.md) | Generate a digest of recent feed activity |
| [`/tune`](tune.md) | Adjust feed relevance thresholds |

## Onboarding

| Skill | Purpose |
|-------|---------|
| [`/setup`](setup.md) | First-time configuration wizard |

## How Skills Work

Skills are defined as `SKILL.md` files in `.claude-plugin/skills/`. When you invoke a slash command, Claude Code loads the markdown and follows the instructions — no Python code is executed by the skill itself. All data operations go through the Distillery MCP server's tools.

### Common Patterns

All skills share these conventions (defined in `CONVENTIONS.md`):

- **MCP health check** — skills verify the MCP server is reachable before proceeding
- **Author resolution** — determined from `git config user.name`, then `DISTILLERY_AUTHOR` env var, then asks
- **Project resolution** — determined from `--project` flag, then `git rev-parse --show-toplevel`, then asks
- **Tag extraction** — 2-5 keywords, lowercase, hyphen-separated, hierarchical (e.g., `project/distillery/decisions`)
- **Error handling** — display the error and stop; no retry loops
- **Preview before store** — all write operations show a preview and ask for confirmation
