---
name: bookmark
description: "Save a URL with an auto-generated summary to the knowledge base"
allowed-tools:
  - "mcp__*__distillery_store"
  - "mcp__*__distillery_check_dedup"
  - "mcp__*__distillery_status"
  - "WebFetch"
disable-model-invocation: true
effort: medium
---

<!-- Trigger phrases: bookmark, save this link, store this URL, remember this page, /bookmark <url> [#tags] -->

# Bookmark — URL Knowledge Capture

Fetches a URL, generates a concise summary, checks for duplicates, and stores the result as a bookmark entry.

## When to Use

- `/bookmark <url> [#tags]`
- "bookmark this", "save this link", "store this URL", "remember this page"

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Parse Arguments

- **First argument**: URL (required). If missing, ask the user.
- **`#tag` tokens**: explicit tags to apply

Example: `/bookmark https://example.com/article #caching #architecture`

### Step 3: Fetch URL Content

Use WebFetch to retrieve content at the URL.

If WebFetch fails, prompt for a manual summary:

```
Could not fetch URL: <url>
Error: <error message>

Please provide a manual summary of the page content:
>
```

Continue to Step 4 with the manual summary.

### Step 4: Generate Summary

Synthesize content into a summary: **2-4 sentences** on main topic and takeaways, followed by **3-5 bullet points**.

Show preview before storing:

```
## Bookmark Summary (preview)

<summary text>

Key points:
- <point 1>
- <point 2>
- <point 3>

Ready to store? (yes / edit / skip)
```

If the user edits, accept their revision. If they skip, confirm "Skipped. No entry was stored."

### Step 5: Check for Duplicates

Call `distillery_check_dedup(content="<url> <summary>")`. Handle by `action` field:

**`"create"`:** No similar entries. Proceed to Step 6.

**`"skip"`:** Near-exact duplicate. Show similarity table and offer: (1) Store anyway, (2) Skip.

**`"merge"` or `"link"`:** Related entry exists. Show similarity table and offer: (1) Store anyway, (2) Skip.

```
Similar entries found:

| Entry ID | Similarity | URL | Preview |
|----------|-----------|-----|---------|
| <id>     | 92%       | <url> | <first 80 chars> |

1. Store anyway  2. Skip
```

On skip, confirm "Skipped. No new entry was stored." and stop.

### Step 6: Determine Author & Project

See CONVENTIONS.md for resolution order. Cache for the session.

### Step 7: Extract Tags

Combine explicit `#tag` arguments with 2-5 auto-extracted keywords from the summary. Tag format rules:
- Lowercase, hyphen-separated within segments
- `source/bookmark/{domain}` — derived from URL domain (drop `www.`, dots to hyphens)
- `domain/{topic}` — subject-area tags
- `project/{repo-name}/references` — if project is known
- Repo/domain name normalization: lowercase, drop `www.`, replace non-`[a-z0-9-]` with hyphens, collapse consecutive hyphens, trim leading/trailing hyphens. Must match `[a-z0-9][a-z0-9\-]*`.
- Strip leading `#` from user-provided tags

### Step 8: Store Entry

```
distillery_store(
  content="<summary>\n\nKey points:\n- ...",
  entry_type="bookmark",
  author="<author>",
  project="<project>",
  tags=[...],
  metadata={"url": "<the-url>", "summary": "<2-4 sentence summary>"}
)
```

### Step 9: Confirm

```
[bookmark] Stored: <entry-id>
Project: <project> | Author: <author>
Summary: <first 200 chars>...
Tags: tag1, tag2, tag3
```

## Output Format

**Stored:**
```
[bookmark] Stored: <entry-id>
Project: <project> | Author: <author>
Summary: <first 200 chars>...
Tags: tag1, tag2, tag3
```

**Skipped:**
```
Skipped. No new entry was stored.
```

## Rules

- Store only the summary, never raw HTML
- Always use WebFetch (not curl) to retrieve URL content
- Always show the summary preview before storing
- Always check for duplicates before storing (threshold 0.8)
- If URL is inaccessible, fall back to asking for a manual summary
- Always store the original URL in `metadata.url`, even if content was manually provided
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — if store fails after one attempt, report and stop
