---
name: bookmark
description: "Saves a URL and its auto-generated summary to the knowledge base. Triggered by: 'bookmark', 'save this link', 'store this URL', 'remember this page', or '/bookmark <url> [#tags]'."
---

# Bookmark — URL Knowledge Capture

Bookmark fetches a URL, generates a concise summary, checks for duplicates, and stores the result as a bookmark entry in Distillery.

## Prerequisites

- The Distillery MCP server must be configured in your Claude Code settings
- See docs/mcp-setup.md for setup instructions

If the server is not available, the skill will display a setup message with next steps.

## When to Use

- When you want to save a URL and its summary to the knowledge base
- When invoked via `/bookmark <url> [#tags]`
- When asked to "bookmark this", "save this link", "store this URL", or "remember this page"

## Process

### Step 1: Check MCP Availability

Call `distillery_status` to confirm the Distillery MCP server is running.

If the tool is unavailable or returns an error, display:

```
Warning: Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.

To set up the server:
1. Ensure Distillery is installed: https://github.com/norrie-distillery/distillery
2. Configure the server in your Claude Code settings: see docs/mcp-setup.md
3. Restart Claude Code or reload MCP servers

For detailed setup instructions, see: docs/mcp-setup.md
```

Stop here if MCP is unavailable.

### Step 2: Parse Arguments

Parse the invocation arguments:

- **First argument**: the URL to bookmark (required)
- **Remaining `#tag` tokens**: explicit tags to apply

Example: `/bookmark https://example.com/article #caching #architecture`
- URL: `https://example.com/article`
- Explicit tags: `["caching", "architecture"]`

If no URL was provided in the arguments, ask the user:

```
Please provide the URL to bookmark:
>
```

Do not proceed without a URL.

### Step 3: Fetch URL Content

Use the WebFetch tool to retrieve the content at the provided URL.

If WebFetch fails (network error, 4xx, 5xx, or timeout), display:

```
Could not fetch URL: <url>
Error: <error message>

Please provide a manual summary of the page content:
>
```

Accept the user's manual summary and continue to Step 4, using it in place of the fetched content.

### Step 4: Generate Summary

Synthesize the fetched content (or user-provided summary) into a concise summary:

- **2–4 sentences** capturing the main topic, purpose, and key takeaways
- Follow with **3–5 key points** as a brief bullet list

Show the generated summary to the user before storing:

```
## Bookmark Summary (preview)

<summary text>

Key points:
- <point 1>
- <point 2>
- <point 3>

Ready to store? (yes / edit / skip)
```

If the user chooses to edit, accept their revised version. If the user chooses to skip, confirm:

```
Skipped. No entry was stored.
```

### Step 5: Check for Duplicates

Call `distillery_find_similar` with the URL and summary text combined, using threshold `0.8`:

```
distillery_find_similar(content="<url> <summary>", threshold=0.8)
```

If no similar entries are found (score < 0.8), proceed directly to Step 6.

If similar entries are found, display a comparison table and prompt the user:

```
Similar entries found in the knowledge base:

| Entry ID | Similarity | URL | Preview |
|----------|-----------|-----|---------|
| <id>     | 92%       | <existing-url> | <first 80 chars of content> |

How would you like to proceed?
1. Store anyway — save as a new bookmark entry
2. Skip — do not store this bookmark

Enter 1 or 2:
```

If the user chooses skip (2):
- Confirm: "Skipped. No new entry was stored."
- Stop here.

If the user chooses store anyway (1):
- Continue to Step 6.

### Step 6: Determine Author

Determine the author for the stored entry using this priority order:

1. Run `git config user.name` — use the result if non-empty
2. Check the `DISTILLERY_AUTHOR` environment variable — use it if set
3. Ask the user: "What is your name (for author attribution)?"

Cache the author for the remainder of the session.

### Step 7: Determine Project

Determine the project context using this priority order:

1. Run `git rev-parse --show-toplevel` to get the repository root, then extract the directory name as the project name
2. If no git repository is found, ask: "What project is this for?"

Cache the project for the remainder of the session.

### Step 8: Extract Tags

Combine explicit tags from Step 2 with auto-extracted keywords from the summary.

Prefer hierarchical tags that reflect the bookmark's origin and content:

- Use `source/bookmark/{domain}` as a base tag derived from the URL domain (e.g. a URL from `docs.python.org` yields `source/bookmark/docs-python-org`, converting dots to hyphens and dropping `www.`)
- Use `domain/{topic}` for subject-area tags (e.g. `domain/web-performance`, `domain/api-design`)
- If the current project is known, add `project/{repo-name}/references`
  - Sanitize repo names: convert to lowercase, replace underscores and dots with hyphens, remove any characters not matching `[a-z0-9-]`
- Fall back to flat tags only when no domain or project context is available

Tag format rules:
- Tags are lowercase and hyphen-separated within each segment (e.g., `source/bookmark/docs-python-org`, `domain/api-design`)
- Auto-extract 2–5 relevant keywords from the summary content
- Merge with any explicit `#tag` arguments from the invocation
- Strip leading `#` characters from user-provided tags

### Step 9: Store Entry

Call `distillery_store` with:

```
distillery_store(
  content="<summary>\n\nKey points:\n- <point 1>\n- <point 2>\n...",
  entry_type="bookmark",
  author="<determined in Step 6>",
  project="<determined in Step 7>",
  tags=["<tag1>", "<tag2>", ...],
  metadata={
    "url": "<the-url>",
    "summary": "<2-4 sentence summary>"
  }
)
```

If `distillery_store` returns an error, display it clearly (see Rules below).

### Step 10: Confirm

Display the result to the user:

```
Bookmarked: <entry-id>

URL: <url>
Project: <project>

Summary:
<first 200 chars of summary>...

Tags: tag1, tag2, tag3
```

## Output Format

**Before storing** — summary preview:
```
## Bookmark Summary (preview)

<summary text>

Key points:
- <point 1>
- <point 2>
- <point 3>

Ready to store? (yes / edit / skip)
```

**After storing** — confirmation:
```
Bookmarked: <entry-id>

URL: <url>
Project: <project>

Summary:
<first 200 chars of summary>...

Tags: tag1, tag2, tag3
```

**When duplicates found** — comparison table:
```
| Entry ID | Similarity | URL | Preview |
|----------|-----------|-----|---------|
| abc-123  | 92%       | https://... | Key points about... |
```

**When skipped:**
```
Skipped. No new entry was stored.
```

**When URL is inaccessible:**
```
Could not fetch URL: <url>
Error: <error message>

Please provide a manual summary of the page content:
>
```

## Rules

- Store only the summary, not raw page HTML — never include full HTML content in stored entries
- Always use WebFetch (not curl or other tools) to retrieve URL content
- Always show the generated summary to the user before storing, so they can review and edit
- Always check for duplicates before storing (threshold 0.8)
- If the URL is inaccessible, fall back to asking the user for a manual summary rather than aborting
- Parse `#tag` syntax from arguments for explicit tags; merge with auto-extracted tags
- Tags must be lowercase and hyphen-separated; strip leading `#` from user-provided tags
- Always store the original URL in metadata (`metadata.url`), even if content was manually provided
- Follow shared author/project determination patterns from CONVENTIONS.md
- If MCP is unavailable, display the setup message and stop immediately
- If `distillery_store` or any MCP tool returns an error, display it clearly:

```
Error: <error message from MCP tool>

Suggested Action:
- If "API key invalid" -> Re-check the embedding provider API key in your config
- If "Database error" -> Ensure the database path is writable and the file exists
- If "Connection error" -> Verify the Distillery MCP server is running
```

- Do not enter infinite retry loops — if a store fails after one retry, report the error and stop
- The `metadata.url` field must always contain the original URL for provenance
