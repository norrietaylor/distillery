---
name: gh-sync
description: "Sync GitHub issues and pull requests into the Distillery knowledge base as searchable, linkable entries"
allowed-tools:
  - "mcp__*__distillery_gh_sync"
  - "mcp__*__distillery_sync_status"
context: fork
effort: low
---

<!-- Trigger phrases: gh-sync, /gh-sync, sync github, sync issues, sync prs, github sync, sync repo issues -->

# gh-sync — GitHub Issue/PR Sync (async dispatch)

gh-sync dispatches a background GitHub sync to the Distillery MCP server. The server fetches issues and pull requests, stores them as `github` entries, dedupes, and wires cross-reference relations. The skill itself returns immediately with a `job_id`; status is checked on demand.

## When to Use

- Capturing GitHub issues and PRs alongside session notes for traceable decisions (`/gh-sync owner/repo`)
- Checking progress of a running or recent sync (`/gh-sync status [job_id]`)
- "sync github issues", "capture PR history", "make issues searchable", "track github decisions"

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Parse Arguments

Detect the flow from the first argument:

| First token | Flow | Next steps |
|-------------|------|------------|
| `status` | **Status (all)** if no second token → Step 4 | |
| `status <job_id>` or `status <source_url>` | **Status (one)** → Step 4 | |
| anything else | **Start sync** → Step 3 (treat as `owner/repo` or GitHub URL) | |

For the start flow, validate `owner/repo` or full GitHub URL. If invalid, report:

```
Error: Invalid repository format. Expected "owner/repo" or "https://github.com/owner/repo".
```

and stop. If no argument at all, ask:

> Which GitHub repository would you like to sync? (e.g., `owner/repo` or `https://github.com/owner/repo`)

Determine `author` and `project` per CONVENTIONS.md. Accept an optional `--project <name>` flag to override the git-derived project.

Flags `--issues`, `--prs`, `--since`, `--limit` are **not currently passed through** — the backend tool does not accept them. If the user supplies any of these flags, **do not silently start an unfiltered sync**. Stop and ask the user for explicit confirmation, e.g.:

> The `--issues`/`--prs`/`--since`/`--limit` flags are not yet supported by the backend. Running this will trigger a **full, unfiltered sync** of all issues and PRs. Proceed anyway? (yes / no)

Only start the sync if the user confirms with `yes`. Otherwise abort without calling `distillery_gh_sync`.

### Step 3: Start Background Sync

Call the server tool in background mode:

```python
distillery_gh_sync(
    url="<owner/repo or URL>",
    author="<author>",
    project="<project>",        # omit if unset
    background=true,
)
```

Read `sync_job.job_id` from the response. Report:

```
Started gh-sync job <job_id> for <owner/repo>.
Running in the background — ask "how's the sync" or run `/gh-sync status <job_id>` to check.
```

Stop. Do NOT poll `distillery_sync_status` in this turn — the point of the async path is to return fast.

### Step 4: Status

Two sub-flows:

**4a. Single job** (`status <id>` or `status <url>`):

```python
distillery_sync_status(job_id="<id>")   # if looks like a UUID
# or
distillery_sync_status(source_url="<url>")
```

Render the response as a one-liner:

```
<job_id> (<source_url>): <status> — <entries_created> new, <entries_updated> updated, <pages_processed> pages. <elapsed>
```

If `error_message` is set, surface it verbatim on a second line and suggest re-running.

**4b. All recent jobs** (`status` alone):

```python
distillery_sync_status()
```

Render as a table of the top 5 rows sorted by `created_at desc`:

| job_id (short) | source_url | status | new | updated | created_at |
|----------------|------------|--------|-----|---------|------------|

## Output Format

**Start flow:**

```
gh-sync: <owner/repo>
Started job <job_id> in background.
Check with: /gh-sync status <job_id>
```

**Status (single):**

```
<job_id> (<owner/repo>): <status>
  <entries_created> new, <entries_updated> updated, <pages_processed> pages
  [if errors]: <error_message>
```

**Status (list):** markdown table as above.

## Rules

- ONLY use `distillery_gh_sync` and `distillery_sync_status`. Do NOT hand-roll fetch/dedup/store — the server does it.
- Always pass `background=true` on `distillery_gh_sync`. Never call it synchronously.
- NEVER poll `distillery_sync_status` in a loop within one skill turn. If the user wants to "wait", tell them to re-run `/gh-sync status <id>` after a minute.
- On `distillery_gh_sync` error: surface the error verbatim and STOP. No retries.
- `owner/repo` argument is required for the start flow — ask if not provided.
- `--issues`, `--prs`, `--since`, `--limit` are not currently supported by the backend tool. Warn the user if supplied.
- Apply `--project` to the `project=` parameter when provided; otherwise use the git-derived project from CONVENTIONS.md.
- `GITHUB_TOKEN` is read from environment by the backend adapter — not handled by the skill.
- Display-only summaries — this skill does not store its own output as a knowledge entry.
