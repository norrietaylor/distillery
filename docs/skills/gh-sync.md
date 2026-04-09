# /gh-sync — GitHub Issue/PR Sync

Syncs GitHub issues and pull requests from a repository into the Distillery knowledge base as searchable `github` entries. Each issue or PR becomes a knowledge entry with full metadata, cross-reference relations, and incremental sync support.

## Usage

```text
/gh-sync owner/repo
/gh-sync owner/repo --issues
/gh-sync owner/repo --prs
/gh-sync owner/repo --since 2026-01-01
```

**Trigger phrases:** "sync GitHub", "import issues", "sync repo issues", "capture PR history"

## When to Use

- Capturing GitHub issues and PRs alongside session notes for traceable decisions
- Making issue discussions and PR context searchable via `/recall` and `/pour`
- Syncing only issues or only PRs for focused imports
- Incrementally updating after previous syncs (only fetches items updated since last run)

## What It Does

1. **Fetches issues/PRs** from the GitHub API (respects rate limits)
2. **Checks for existing entries** to avoid duplicates (incremental sync)
3. **Creates `github` entries** with structured metadata (labels, assignees, state, milestone)
4. **Adds relations** between related issues/PRs (cross-references, parent issues)
5. **Tags entries** with `source/github/owner/repo` and label-derived tags

## Options

| Flag | Description |
|------|-------------|
| `--issues` | Sync only issues (skip PRs) |
| `--prs` | Sync only pull requests (skip issues) |
| `--since DATE` | Only sync items updated after this date |
| `--limit N` | Maximum number of items to sync |

## Tips

- Run incrementally — subsequent syncs only fetch items updated since the last run
- Synced entries are searchable via `/recall` and synthesizable via `/pour`
- Use `/investigate` to follow relationship chains across synced issues
- Combine with `/watch add github:owner/repo` for ongoing event monitoring (different from `/gh-sync` which imports full issue/PR content)
