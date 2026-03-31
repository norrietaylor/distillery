# /bookmark — URL Knowledge Capture

Fetches a URL, generates a concise summary, checks for duplicates, and stores the result as a bookmark entry.

## Usage

```text
/bookmark https://example.com/article
/bookmark https://redis.io/docs/best-practices #caching #redis
```

**Trigger phrases:** "bookmark this", "save this link", "store this URL", "remember this page"

## When to Use

- Saving a reference article or documentation page
- Bookmarking a blog post, tutorial, or resource for future recall
- Building a curated collection of links on a topic

## How It Works

1. **Fetches the URL** content (using WebFetch)
2. **Generates a summary** — 2-4 sentences + 3-5 key bullet points
3. **Checks for duplicates** against existing entries (threshold: 0.80)
4. **Shows a preview** and asks for confirmation
5. **Stores** with automatic tags: `source/bookmark/{domain}`, `domain/{topic}`, `project/{repo}/references`

If the URL is inaccessible, you're asked to provide a manual summary.

## Options

| Option | Description |
|--------|-------------|
| URL (required) | The URL to bookmark |
| `#tag` | One or more explicit tags (merged with auto-extracted tags) |

## Output

### Preview

```text
## Bookmark Preview

**URL:** https://redis.io/docs/best-practices
**Project:** billing

Redis recommends using connection pooling with a maximum of 100 connections
per instance. Key expiration should use active + lazy strategies...

- Connection pooling: max 100 connections per instance
- TTL: use active + lazy expiration
- Memory: set maxmemory-policy to allkeys-lru
- Persistence: RDB snapshots every 15 minutes for durability

**Tags:** source/bookmark/redis.io, domain/caching, project/billing/references

Store this bookmark? (y/n)
```

### Confirmation

```text
Stored: e5f6g7h8
URL: https://redis.io/docs/best-practices | Project: billing
Summary: Redis recommends using connection pooling with a maximum...
Tags: source/bookmark/redis.io, domain/caching, project/billing/references
```

## Tips

- Only the summary is stored, never the raw HTML
- The original URL is always preserved in `metadata.url`
- If a similar bookmark already exists (>80% similarity), you choose whether to skip, merge, or create
