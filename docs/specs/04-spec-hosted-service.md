# Spec 04 — Hosted HTTP Gateway

## Overview

A self-hosted FastAPI service that bridges the browser extension (and any HTTP client) to the Distillery storage layer. Users deploy this themselves — no cloud vendor required.

**Key question from issue #34:** *"Could we host a service running Claude CLI and route requests to it?"*

**Answer: Yes, and that's exactly what this spec proposes.** See the two implementation options below.

---

## The Two Options

### Option A — Direct Python Library (recommended for MVP)

The gateway imports `distillery` directly and calls the same Python functions the MCP server uses. No subprocess overhead.

```
HTTP request → FastAPI → DistilleryStore + EmbeddingProvider + Claude API
                           (same objects the MCP server uses)
```

- Fast: no subprocess startup, no MCP wire protocol overhead
- Predictable: deterministic summarization via direct `anthropic` client call
- Testable: standard Python unit tests
- Fail-loud: no API key → 402 on startup, not at request time

### Option B — Claude CLI Subprocess (power-user mode)

The gateway runs `claude --print "/bookmark <url> #tag"` as a subprocess. Claude Code reads the Distillery MCP config from `.claude/settings.json` and executes the full skill.

```
HTTP request → FastAPI → subprocess: claude --print "/bookmark <url>"
                          (Claude Code + Distillery MCP skill)
```

- Leverages existing skills with zero reimplementation
- Skills stay current automatically as SKILL.md files evolve
- Slow: subprocess startup + LLM session init per request (~3–10s)
- Opaque: output parsing required; skill output format can change

**Recommendation:** Start with Option A (direct library) for `/bookmark` and `/status`. Reserve Option B as an optional "rich mode" flag for operations that benefit from full skill orchestration (e.g., `/pour`, `/investigate`).

---

## Architecture

```
                          ┌─────────────────────────────┐
Browser Extension         │   Distillery HTTP Gateway   │
    │  POST /api/bookmark │                             │
    │  POST /api/watch    │  ┌──────────────────────┐  │
    │  GET  /api/status   │  │  FastAPI app          │  │
    │  GET  /api/search   │  │  Auth: Bearer token   │  │
    └────────────────────►│  │  User config map      │  │
                          │  └──────────┬───────────┘  │
                          │             │               │
                          │  ┌──────────▼───────────┐  │
                          │  │  BookmarkService       │  │
                          │  │  1. httpx fetch URL    │  │
                          │  │  2. Claude API summ.   │  │
                          │  │  3. find_similar dedup │  │
                          │  │  4. distillery_store   │  │
                          │  └──────────┬───────────┘  │
                          │             │               │
                          │  ┌──────────▼───────────┐  │
                          │  │  DuckDB (per-user)     │  │
                          │  │  ~/.distillery/<token> │  │
                          │  │  or S3 per user        │  │
                          │  └──────────────────────┘  │
                          └─────────────────────────────┘
```

---

## API Endpoints

### `GET /api/health`

No auth required. Returns server version and whether Anthropic API key is configured.

```json
{ "status": "ok", "version": "0.2.0", "summarization": true }
```

Returns `{ "status": "degraded", "summarization": false }` if `ANTHROPIC_API_KEY` is not set. The gateway **does not start** if the key is absent and `REQUIRE_SUMMARIZATION=true` (default).

---

### `POST /api/bookmark`

```json
{
  "url": "https://example.com/article",
  "tags": ["ai", "research"],
  "project": "my-project"
}
```

Auth: `Authorization: Bearer <token>`

**Response 200:**
```json
{
  "entry_id": "uuid",
  "summary": "2-4 sentence summary…",
  "tags": ["source/bookmark/example-com", "domain/ai", "project/my-project/references"],
  "duplicate": false
}
```

**Response 409 (duplicate detected):**
```json
{
  "entry_id": null,
  "duplicate": true,
  "existing_id": "uuid",
  "similarity": 0.92,
  "force": false
}
```
Client may retry with `{ "force": true }` to save anyway.

**Response 402:** Anthropic API key not configured on server.
**Response 422:** URL not reachable and no fallback content provided.

---

### `POST /api/watch`

Register a URL/feed for polling (see Spec 05).

```json
{
  "url": "https://reddit.com/r/machinelearning",
  "type": "subreddit",
  "interval": "6h",
  "tags": ["ml", "research"],
  "auth": { "type": "none" }
}
```

**Response 201:**
```json
{ "watch_id": "uuid", "next_poll": "2026-03-29T01:00:00Z" }
```

---

### `GET /api/search` *(planned)*

```
GET /api/search?q=transformer+architecture&limit=5
```

Proxies `distillery_search` and returns results with similarity scores.

**Note:** Not yet implemented in the initial release.

---

### `GET /api/status`

Proxies `distillery_status`. Returns entry counts, DB size, embedding model.

---

## Authentication

Each user gets a unique bearer token. The gateway maps `token → user_config`:

```yaml
# gateway.yaml
users:
  - token: "tok_abc123"
    db_path: "~/.distillery/user_abc.db"
    project: "personal"
  - token: "tok_def456"
    db_path: "s3://my-bucket/distillery/user_def.db"
    project: "work"

anthropic_api_key_env: ANTHROPIC_API_KEY
embedding:
  provider: jina
  api_key_env: JINA_API_KEY

require_summarization: true   # If false, store title+URL on Anthropic failure
```

Tokens are secrets — treat like passwords. No OAuth in MVP; simple bearer token is sufficient for self-hosted.

---

## Per-User Knowledge Bases

Each user gets their own DuckDB file. Options:
- Local path: `~/.distillery/<token-prefix>.db` — simplest for single-host deploy
- S3: `s3://bucket/distillery/<token-prefix>.db` — multi-host, persistent across restarts
- MotherDuck: `md:<token-prefix>` — managed cloud DuckDB

The `DuckDBStore` already supports S3 and MotherDuck URIs.

---

## Deployment

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -e ".[server]"
CMD ["distillery-gateway", "--config", "/config/gateway.yaml"]
```

```bash
docker run -d \
  -e ANTHROPIC_API_KEY=sk-... \
  -e JINA_API_KEY=... \
  -v $(pwd)/gateway.yaml:/config/gateway.yaml \
  -p 8080:8080 \
  distillery-gateway
```

### `distillery gateway` CLI Command

```bash
distillery gateway [--config gateway.yaml] [--port 8080] [--host 0.0.0.0]
```

Added to `src/distillery/cli.py` alongside existing `status`, `health`, `eval` subcommands.

---

## Dependencies to Add

```toml
[project.optional-dependencies]
server = [
  "fastapi>=0.111.0",
  "uvicorn[standard]>=0.29.0",
  "anthropic>=0.26.0",
  "httpx>=0.27.0",   # already present
]
```

Install: `pip install "distillery[server]"`

---

## Summarization Logic (Option A)

When `POST /api/bookmark` is received:

1. `httpx.get(url, follow_redirects=True, timeout=15)` — fetch page HTML
2. Strip tags → plain text (via simple regex or `html.parser`)
3. Call `anthropic.messages.create(model="claude-haiku-4-5-20251001", ...)` with prompt:
   ```
   Summarise this web page in 2-4 sentences and list 3-5 key bullet points.
   URL: <url>
   Content: <first 6000 chars of text>
   ```
4. If `ANTHROPIC_API_KEY` absent → raise `HTTP 402`
5. Call `store.find_similar(url + "\n" + summary, threshold=0.80)` for dedup
6. If duplicate → return 409
7. Call `store.store(entry)` → return 200

---

## Security Notes

- Bind to `127.0.0.1` or behind a reverse proxy (nginx/Caddy) with TLS
- Tokens are bcrypt-hashed in `gateway.yaml` (or plaintext for local dev, clearly documented)
- Rate limit per token: 60 requests/minute (configurable)
- URL fetch is sandboxed — no SSRF to private RFC-1918 ranges (block 10.x, 192.168.x, 172.16-31.x, localhost)
- HTML content truncated to 8KB before sending to Claude API

---

## Implementation Checklist

- [ ] `src/distillery/server/__init__.py`
- [ ] `src/distillery/server/app.py` — FastAPI app factory
- [ ] `src/distillery/server/auth.py` — token validation middleware
- [ ] `src/distillery/server/bookmark.py` — bookmark service (fetch + summarise + store)
- [ ] `src/distillery/server/config.py` — `GatewayConfig` dataclass
- [ ] `src/distillery/server/ssrf.py` — SSRF protection for URL fetching
- [ ] `src/distillery/cli.py` — add `gateway` subcommand
- [ ] `pyproject.toml` — add `[server]` optional dependency group
- [ ] `Dockerfile.gateway`
- [ ] `tests/test_server/` — unit tests for bookmark service, auth, SSRF guard
