# /recall — Semantic Search

Searches the knowledge base using natural language queries and returns ranked results with full provenance.

## Usage

```text
/recall distributed caching strategies
/recall --type bookmark --limit 5 API design
/recall --author alice --project billing authentication
```

**Trigger phrases:** "what do we know about", "search knowledge", "find in knowledge base"

## When to Use

- Finding relevant entries on any topic
- Searching for past decisions, discussions, or bookmarks
- Filtering by type, author, or project

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--type <type>` | Filter by entry type (session, bookmark, minutes, etc.) | All types |
| `--author <name>` | Filter by author | All authors |
| `--project <name>` | Filter by project | All projects |
| `--limit <n>` | Maximum results to return | 10 |

If no query is provided, you'll be prompted for one.

## Output

Each result includes:

- **Similarity score** — percentage match (e.g., `92%`)
- **Type badge** — `[session]`, `[bookmark]`, `[minutes]`, etc.
- **Full content** — never truncated
- **Provenance** — entry ID, author, project, creation date
- **Tags** — if any are present

```text
## Results (3 found)

### 92% [session] Caching Strategy Decision
We decided to use Redis for the session cache with a 15-minute TTL...

ID: a1b2c3d4 | Author: alice | Project: billing | 2026-03-15
Tags: domain/caching, project/billing/decisions

---

### 78% [bookmark] Redis Best Practices
Summary of Redis configuration recommendations from the official docs...

ID: e5f6g7h8 | Author: bob | Project: billing | 2026-03-10
Tags: source/bookmark/redis.io, domain/caching
```

## Tips

- Queries are semantic, not keyword-based — "how do we handle auth?" finds entries about authentication even if they don't contain the word "auth"
- Use `--type` to narrow results when you know what you're looking for
- If an invalid `--type` is provided, you'll see the list of valid types
