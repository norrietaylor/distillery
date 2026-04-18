# /gh-sync — GitHub Issue/PR Sync

Syncs GitHub issues and pull requests from a repository into the Distillery knowledge base as searchable `github` entries. The skill dispatches a background sync on the Distillery MCP server and returns immediately with a `job_id`; progress is checked on demand.

## Usage

```text
/gh-sync owner/repo                 # start a background sync
/gh-sync status                     # list recent jobs
/gh-sync status <job_id>            # check one job
/gh-sync status <owner/repo>        # check latest job for this repo
```

**Trigger phrases:** "sync GitHub", "import issues", "sync repo issues", "capture PR history", "how's the sync", "gh-sync status"

## When to Use

- Capturing GitHub issues and PRs alongside session notes for traceable decisions
- Making issue discussions and PR context searchable via `/recall` and `/pour`
- Checking on a previously-started sync without re-running it

## What It Does

1. **Dispatches an async job** on the Distillery MCP server (`distillery_gh_sync(background=true)`) and returns the `job_id` immediately.
2. The server fetches issues/PRs from the GitHub API, respects rate limits, dedupes against `metadata.external_id`, creates new entries or updates existing ones, and wires `link` relations for cross-references.
3. Status polls (`distillery_sync_status`) report `status`, `entries_created`, `entries_updated`, `pages_processed`, and any errors.

## Options

Currently the backend tool accepts only `url`, `author`, `project`, and `background`. The flags below were previously documented but are not wired through — they'll be noted as unsupported if supplied, and the sync will run without them:

| Flag | Status |
|------|--------|
| `--issues` | not supported |
| `--prs` | not supported |
| `--since DATE` | not supported |
| `--limit N` | not supported |
| `--project <name>` | supported (overrides git-derived project) |

## Tips

- The command returns in under a second — the sync runs in the background.
- Ask "how's the sync going" or run `/gh-sync status` later to see progress.
- Synced entries are searchable via `/recall` and synthesizable via `/pour`.
- Use `/investigate` to follow relationship chains across synced issues.
- Combine with `/watch add github:owner/repo` for ongoing event monitoring (different from `/gh-sync` which imports full issue/PR content).
