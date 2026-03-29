# Spec 05 — /watch Skill + Feed Polling

## Overview

The `/watch` skill lets users register URLs and feeds for automatic monitoring. When content changes, new entries are stored in Distillery. Users view digests via `/radar` (Phase 3) and can manage sources via `/watch`.

**Scope from issue #34:**
- Web pages (change detection via content diff)
- Subreddits (Reddit JSON API, no auth required for public subreddits)
- RSS / Atom feeds
- Web-based feeds with auth (HTTP Basic, Bearer token, cookie)

---

## Source Types

| Type | Detection method | Auth support |
|------|-----------------|--------------|
| `webpage` | Hash diff of extracted text content | None, Basic, Bearer, Cookie |
| `subreddit` | Reddit JSON API (`/r/<name>/new.json`) | None (public), OAuth2 (private) |
| `rss` | RSS 2.0 / Atom feed polling | None, Basic, Bearer |
| `atom` | Atom feed polling | None, Basic, Bearer |

Future (Phase 3+): Slack, GitHub, Hacker News, webhooks.

---

## Skill Interface

```
/watch <url>                        # Add watch, auto-detect type
/watch <url> --type rss --every 2h  # Explicit type and interval
/watch <url> --auth bearer:TOKEN    # With auth
/watch --list                       # List watched sources
/watch --list --project my-project  # Filter by project
/watch --remove <watch_id>          # Stop watching
/watch --pause <watch_id>           # Pause without removing
/watch --resume <watch_id>          # Resume paused watch
```

### Type Auto-detection

| URL pattern | Detected type |
|-------------|---------------|
| `reddit.com/r/<sub>` | `subreddit` |
| `.xml`, `/feed`, `/rss`, `/atom` | `rss` |
| `*.rss`, `*.atom` | `rss` |
| Anything else | `webpage` |

---

## Data Model

New `watch_source` table in DuckDB:

```sql
CREATE TABLE watch_sources (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  url         TEXT NOT NULL,
  type        TEXT NOT NULL,       -- webpage | subreddit | rss | atom
  project     TEXT,
  author      TEXT,
  tags        TEXT[],
  interval    TEXT DEFAULT '6h',   -- polling interval: 1h, 6h, 24h
  auth_type   TEXT DEFAULT 'none', -- none | basic | bearer | cookie
  auth_config VARCHAR,             -- encrypted auth credentials (JSON string)
  status      TEXT DEFAULT 'active', -- active | paused | error
  last_polled TIMESTAMP,
  last_hash   TEXT,                -- content hash for change detection
  created_at  TIMESTAMP DEFAULT now(),
  error_count INTEGER DEFAULT 0,
  last_error  TEXT
);
```

New `Entry` type: `WATCH_ITEM` (stored when a change is detected).

---

## Polling Architecture

### Daemon Mode

```bash
distillery watch --daemon [--config distillery.yaml]
```

Runs a polling loop:
1. Load all `active` watch sources
2. Group by `interval` → schedule next poll times
3. For each due source: poll → diff → store if changed
4. Sleep until next poll time
5. Exit cleanly on SIGTERM

### Hosted Gateway Integration

When running via the hosted gateway (Spec 04), the gateway process manages polling in a background `asyncio` task. No separate daemon needed.

### Poll Logic Per Source Type

**`webpage`:**
1. `httpx.get(url, headers=auth_headers)`
2. Extract text (strip HTML tags)
3. Compute SHA-256 hash of normalised text
4. Compare with `last_hash`
5. If different → generate diff summary via Claude API → store as `WATCH_ITEM` entry
6. Update `last_hash`, `last_polled`

**`subreddit`:**
1. `GET https://www.reddit.com/r/<sub>/new.json?limit=25`
2. Collect post IDs seen since `last_polled`
3. For each new post → store as `WATCH_ITEM` with title, URL, score, comment count
4. Batch: up to 25 new items per poll cycle

**`rss` / `atom`:**
1. `httpx.get(feed_url, headers=auth_headers)`
2. Parse with `feedparser` (or stdlib `xml.etree.ElementTree`)
3. Filter items with `published > last_polled`
4. For each new item → store as `WATCH_ITEM`

---

## Auth Configuration

Auth credentials are stored encrypted in `auth_config` JSONB. The `auth_type` field selects the scheme:

| `auth_type` | `auth_config` structure |
|-------------|------------------------|
| `none` | `{}` |
| `basic` | `{ "username": "...", "password": "..." }` |
| `bearer` | `{ "token": "..." }` |
| `cookie` | `{ "cookies": { "session": "..." } }` |

Credentials are AES-256 encrypted at rest using the gateway's `SECRET_KEY` env var. Never stored in plaintext.

---

## Entry Format (WATCH_ITEM)

```python
Entry(
  entry_type=EntryType.WATCH_ITEM,
  content="<diff summary or item text>",
  source=EntrySource.WATCH,
  tags=["source/watch/reddit-com", "domain/ml", "project/my-proj/feeds"],
  metadata={
    "watch_id": "uuid",
    "source_url": "https://...",
    "source_type": "subreddit",
    "item_url": "https://reddit.com/r/...",   # for subreddit/rss items
    "change_type": "new_content",              # or "update"
    "detected_at": "2026-03-28T20:00:00Z",
  }
)
```

---

## MCP Tools to Add

| Tool | Purpose |
|------|---------|
| `distillery_watch_add` | Register a new watch source |
| `distillery_watch_list` | List watch sources with optional filters |
| `distillery_watch_update` | Pause, resume, or update interval |
| `distillery_watch_remove` | Delete a watch source |
| `distillery_watch_poll` | Manually trigger a poll for one source |

---

## SKILL.md Steps

```
/watch <url> [--type TYPE] [--every INTERVAL] [--auth bearer:TOKEN] [--project PROJECT] [#tags]
```

1. **Check MCP availability** — `distillery_status`
2. **Parse arguments** — extract URL, flags, tags
3. **Auto-detect type** — from URL pattern (see table above)
4. **Validate URL** — fetch HEAD request to confirm reachability
5. **Determine author + project** — same as other skills
6. **Confirm with user** — show: URL, type, interval, auth method, tags
7. **Register** — `distillery_watch_add(url, type, interval, auth_config, tags, project)`
8. **Confirm** — show watch_id and next scheduled poll time

---

## Rate Limits & Politeness

- Minimum poll interval: 1h for webpages/RSS, 30m for subreddits
- Respect `Cache-Control` and `ETag` headers (conditional GET)
- `User-Agent: Distillery/0.2 (+https://github.com/norrietaylor/distillery)`
- Exponential backoff on errors: 1h → 2h → 4h → 8h → pause after 5 consecutive failures
- Max 50 active watch sources per user

---

## Implementation Checklist

- [ ] Add `watch_source` table to `DuckDBStore`
- [ ] Add `WATCH_ITEM` to `EntryType` enum
- [ ] Add `WATCH` to `EntrySource` enum
- [ ] Implement 5 MCP tools (`distillery_watch_*`)
- [ ] Implement source adapters: `WebpageAdapter`, `SubredditAdapter`, `RssAdapter`
- [ ] Implement polling loop (`src/distillery/watch/poller.py`)
- [ ] Add `distillery watch --daemon` CLI command
- [ ] Integrate polling into gateway background task
- [ ] Write `/watch` SKILL.md
- [ ] Implement auth encryption/decryption
- [ ] Tests for each adapter + polling logic
- [ ] SSRF guard for watch URLs (reuse from Spec 04)
