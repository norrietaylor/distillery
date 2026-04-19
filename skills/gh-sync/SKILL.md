---
name: gh-sync
description: "Sync GitHub issues and pull requests into the Distillery knowledge base as searchable, linkable entries"
allowed-tools:
  - "mcp__*__distillery_store"
  - "mcp__*__distillery_get"
  - "mcp__*__distillery_update"
  - "mcp__*__distillery_list"
  - "mcp__*__distillery_relations"
context: fork
effort: high
---

<!-- Trigger phrases: gh-sync, /gh-sync, sync github, sync issues, sync prs, github sync, sync repo issues -->

# gh-sync — GitHub Issue/PR Knowledge Tracking

gh-sync fetches issues and pull requests from a GitHub repository and stores them as searchable, linkable entries in the Distillery knowledge base. Each issue or PR becomes a `github` entry with full metadata, cross-reference relations, and incremental sync support.

## When to Use

- Capturing GitHub issues and PRs alongside session notes for traceable decisions (`/gh-sync owner/repo`)
- Syncing only issues (`/gh-sync owner/repo --issues`) or only PRs (`/gh-sync owner/repo --prs`)
- Incrementally updating after previous syncs (only fetches items updated since last run)
- "sync github issues", "capture PR history", "make issues searchable", "track github decisions"

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Parse Arguments

If no repository argument is provided, ask:

> Which GitHub repository would you like to sync? (e.g., `owner/repo` or `https://github.com/owner/repo`)

Extract from arguments:

| Argument / Flag | Description |
|-----------------|-------------|
| `owner/repo` | Repository slug or full GitHub URL (required) |
| `--issues` | Sync issues only (exclude PRs) |
| `--prs` | Sync PRs only (exclude issues) |
| `--project <name>` | Tag synced entries under this project (overrides git-derived project) |

If both `--issues` and `--prs` are provided, sync both (equivalent to providing neither).

Determine author & project per CONVENTIONS.md. The `owner/repo` argument must be validated as a recognisable slug (e.g. `org/repo`) or GitHub URL. If invalid, report:

```
Error: Invalid repository format. Expected "owner/repo" or "https://github.com/owner/repo".
```

and stop.

### Step 3: Check for Existing Sync State

Query for any previously synced entries from this repository to determine if this is an incremental sync:

```python
distillery_list(
    entry_type="github",
    limit=1,
    # metadata filter — look for entries from this repo
)
```

Report one of:
- `First sync for {owner}/{repo} — fetching all open and closed items.`
- `Incremental sync for {owner}/{repo} — fetching items updated since last sync.`

The `GitHubSyncAdapter` (invoked internally by the MCP backend) tracks the last sync timestamp via the store metadata table. The skill surfaces the state to the user but does not manage the timestamp directly.

### Step 4: Retrieve Existing Entries for Dedup

Before processing, retrieve the list of already-synced entries for this repository so that updates are routed correctly:

```python
distillery_list(
    entry_type="github",
    limit=500,
    output_mode="summary",
    # scope to the target repo
)
```

Note the `total_count` field from the response. If `total_count > 500`, paginate by calling `distillery_list` with increasing `offset` (500, 1000, ...) until all entries are retrieved.

Use the `metadata.external_id` field of each returned entry to build a lookup map: `{external_id: entry_id}`. This map determines whether an incoming item should be stored (new) or updated (existing).

### Step 5: Sync Issues and PRs

For each item fetched from GitHub (handled by the backend sync adapter):

**5a. Determine item type:**

Each GitHub item is either an issue or a PR. Items with a `pull_request` key in the API response are PRs; all others are issues.

Apply the filter:
- `--issues` flag: skip items where `ref_type == "pr"`
- `--prs` flag: skip items where `ref_type == "issue"`
- No flag (or both): process all items

**5b. Check for existing entry:**

Look up `metadata.external_id` (format: `{owner}/{repo}#issue-{number}` or `{owner}/{repo}#pr-{number}`) in the dedup map built in Step 4.

**If not found (new entry):**

```python
distillery_store(
    content="<title + body + top comments, markdown-formatted>",
    entry_type="github",
    author="<author>",
    project="<project>",
    tags=["<label1>", "<label2>", ...],
    metadata={
        "repo": "<owner>/<repo>",
        "ref_type": "<issue|pr>",
        "ref_number": <number>,
        "title": "<title>",
        "url": "<html_url>",
        "state": "<open|closed>",
        "labels": ["<label>", ...],
        "assignees": ["<login>", ...],
        "external_id": "<owner>/<repo>#<ref_type>-<number>"
    }
)
```

**If found (existing entry):**

```python
distillery_update(
    entry_id="<existing_entry_id>",
    content="<updated content>",
    metadata={
        "state": "<current state>",
        "labels": ["<label>", ...],
        "assignees": ["<login>", ...]
    }
)
```

**5c. Create cross-reference relations:**

After storing or updating, parse the entry content for cross-reference patterns (`#123`, `Closes #123`, `Fixes #123`, `Resolves #123`). For each referenced number found:

1. Look up the external_id `{owner}/{repo}#issue-{ref}` and `{owner}/{repo}#pr-{ref}` in the dedup map
2. If found, create a `link` relation between the current entry and the referenced entry:

```python
distillery_relations(
    action="add",
    from_id="<current_entry_id>",
    to_id="<referenced_entry_id>",
    relation_type="link"
)
```

Skip self-references (where `ref_number == current_number`). Skip if target entry not found in the knowledge base. Relation creation failures are non-fatal — log and continue.

Track count of relations created for the summary report.

### Step 6: Confirm

Display the sync summary:

```
Synced {N} issues, {M} PRs from {owner}/{repo}. {K} new, {L} updated. {R} cross-reference relations created.
```

Where:
- `N` = count of issues processed (0 if `--prs` only)
- `M` = count of PRs processed (0 if `--issues` only)
- `K` = count of new entries stored
- `L` = count of existing entries updated
- `R` = count of `link` relations created

If no items were found (e.g., empty repository or all items already up to date), display:

```
No new or updated items found for {owner}/{repo} since last sync.
```

## Output Format

```
gh-sync: {owner}/{repo}
Fetching {"all items" | "issues only" | "PRs only"}...

{First sync | Incremental sync} — {N} items retrieved from GitHub API.

Processing:
  Issues: {N} ({K} new, {L} updated)
  PRs:    {M} ({K} new, {L} updated)
  Relations: {R} cross-reference links created

Synced {total_N} issues, {total_M} PRs from {owner}/{repo}. {K} new, {L} updated. {R} cross-reference relations created.
```

Example:

```
gh-sync: norrietaylor/distillery
Fetching all items...

Incremental sync — 12 items retrieved from GitHub API.

Processing:
  Issues: 8 (3 new, 5 updated)
  PRs:    4 (2 new, 2 updated)
  Relations: 6 cross-reference links created

Synced 8 issues, 4 PRs from norrietaylor/distillery. 5 new, 7 updated. 6 cross-reference relations created.
```

## Rules

- `owner/repo` argument is required — ask if not provided
- `--issues` and `--prs` can be combined (equivalent to syncing both)
- Never store duplicate entries — always check `metadata.external_id` before storing
- Use `entry_type="github"` for all synced entries
- `metadata.external_id` format: `{owner}/{repo}#issue-{number}` or `{owner}/{repo}#pr-{number}`
- Required metadata fields: `repo`, `ref_type`, `ref_number`, `title`, `url`, `state`
- Labels are converted to tags by the shared sanitiser (`distillery.feeds.github_tag.sanitize_label`): lowercase, spaces and underscores become hyphens, consecutive hyphens collapse, leading/trailing hyphens are stripped, and labels that still do not match the tag grammar `[a-z0-9][a-z0-9-]*` are dropped rather than failing the whole entry. Example: `github_actions` → `github-actions`, `!!! urgent` → dropped.
- Entry content: `# {title}\n\n{body}\n\n**{commenter}**: {comment}` (top 10 comments max)
- Cross-reference relation creation is non-fatal — continue on failure, report in summary
- Self-references (an issue referencing its own number) are skipped
- `GITHUB_TOKEN` is read from environment by the backend adapter — not handled by the skill
- This skill does not filter by project on read (all `github` entries for the repo are dedup candidates)
- Apply `--project` to all `distillery_store` and `distillery_update` calls when provided
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — report errors and stop
- Display-only summary — this skill does not store its own output as a knowledge entry
