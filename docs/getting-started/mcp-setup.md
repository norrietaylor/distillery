# MCP Server Reference

Complete reference for the Distillery MCP server — tools, configuration options, and troubleshooting.

## Starting the Server

### stdio (local, default)

```bash
# Recommended
uvx distillery-mcp

# Or using the installed entry point
distillery-mcp
# or
python -m distillery.mcp
```

### HTTP (team access)

```bash
distillery-mcp --transport http --port 8000
```

See [Operator Deployment](../team/deployment.md) for full HTTP setup with GitHub OAuth.

### CLI Flags

```text
distillery-mcp [OPTIONS]

Options:
  --transport {stdio|http}  Transport mode (default: stdio)
  --host HOST              Bind address (default: 0.0.0.0, env: DISTILLERY_HOST)
  --port PORT              Bind port (default: 8000, env: DISTILLERY_PORT)
  --help                   Show this help message
```

For the full `distillery` CLI (status, export/import, eval, maintenance), see the [CLI Reference](../reference/cli.md).

## Configuration

Distillery reads `distillery.yaml` from the current working directory, or from the path set in `DISTILLERY_CONFIG`.

See [`distillery.yaml.example`](https://github.com/norrietaylor/distillery/blob/main/distillery.yaml.example) for all available settings.

## Available Tools

The server exposes **16 tools** plus one MCP resource (`distillery://schemas/entry-types`).

| Tool | Description |
|------|-------------|
| **CRUD** | |
| `distillery_store` | Store a single knowledge entry with content, tags, and metadata. Returns dedup action when a near-duplicate is detected. |
| `distillery_store_batch` | Bulk-ingest multiple entries in a single call. Used for migrations, backfills, and `/gh-sync`. |
| `distillery_get` | Retrieve a single entry by UUID. |
| `distillery_update` | Partially update an existing entry (tags, status, metadata, verification). |
| `distillery_correct` | Store a structured correction over an existing entry, preserving the original via `entry_relations`. |
| `distillery_list` | List entries with filtering, pagination, grouping, and review-queue enrichment. Default `output_mode="summary"`; other modes: `"full"` (content body), `"ids"` (id-only), `"review"` (pending-review queue). Absorbed flags: `stale_days`, `group_by`, `feed_url`, `source` (URLs alias to `feed_url`). Excludes archived entries by default (override with `include_archived=true`). |
| **Discovery** | |
| `distillery_search` | Hybrid BM25 + vector search with RRF fusion; falls back to vector-only if FTS unavailable. |
| `distillery_find_similar` | Cosine-similarity search. Supports dedup mode (`dedup_action=true`) and conflict detection (`conflict_check=true`). |
| **Classification** | |
| `distillery_classify` | Classify an entry by type with LLM-based confidence scoring. Supports `mode="batch"` for the whole pending-review queue. |
| `distillery_resolve_review` | Resolve a pending-review entry (accept/reject/reclassify). Idempotent for no-op transitions. |
| **Relations** | |
| `distillery_relations` | Manage typed links between entries (corrections, supersedes, related). |
| **Feeds** | |
| `distillery_watch` | List, add, or remove monitored feed sources (`rss`, `github`). Validates URL syntax and probes reachability before persisting. |
| `distillery_gh_sync` | Sync GitHub issues/PRs into the knowledge base. Returns immediately with a job ID; the actual sync runs as a server-side background task. |
| `distillery_sync_status` | Look up the status of a `distillery_gh_sync` job (queued / running / completed / failed). |
| **Configuration & Health** | |
| `distillery_configure` | Read or update runtime configuration (thresholds, defaults, classification). Persists changes to `distillery.yaml`. |
| `distillery_status` | Lightweight health/metadata probe — version, build SHA, transport, tool count, entry count, embedding provider, last feed poll, uptime. Replaces the former `distillery_metrics(scope="summary")` call. |

### MCP Resources

| URI | Description |
|-----|-------------|
| `distillery://schemas/entry-types` | Metadata schemas for all structured entry types (session, bookmark, minutes, meeting, reference, idea, inbox, …). Replaces the former `distillery_type_schemas` tool. |

### Removed in this release

The `staging/api-hardening` consolidation removed the following tools. If you have a stale skill cache, re-install the plugin to pick up the new tool list.

| Removed tool | Replacement |
|--------------|-------------|
| `distillery_aggregate` | `distillery_list(group_by=…)` |
| `distillery_stale` | `distillery_list(stale_days=…)` |
| `distillery_tag_tree` | `distillery_list(group_by="tag")` |
| `distillery_metrics` (scope=`summary`) | `distillery_status` |
| `distillery_metrics` (scope=`full`/`search_quality`) | `distillery_list(output_mode="full")` for entry stats; quality stats folded into `distillery_status` |
| `distillery_metrics` (scope=`audit`) | Operator-only — query the `audit_log` table directly via `store.query_audit_log()`; no public MCP tool path remains |
| `distillery_interests` | Surfaced internally by `/radar` via the feed scorer (no public tool) |
| `distillery_type_schemas` | MCP resource `distillery://schemas/entry-types` |
| `distillery_poll` | REST endpoint `POST /api/maintenance` (or Claude Code routines via `/setup`) |
| `distillery_rescore` | REST endpoint `POST /api/maintenance` (or Claude Code routines) |

See [architecture.md → Webhook Endpoints](../architecture.md#webhook-endpoints-partially-deprecated) for the REST surface.

## Verifying the Server

Call the `distillery_status` MCP tool from within Claude Code:

```text
distillery_status()
```

Expected response:

```json
{
  "status": "ok",
  "version": "0.4.0",
  "build_sha": "dev",
  "transport": "stdio",
  "tool_count": 16,
  "store": { "entry_count": 0, "db_size_bytes": null },
  "embedding_provider": "jina-embeddings-v3",
  "last_feed_poll": { "source_count": 0, "last_poll_at": null }
}
```

You can also run:

```bash
distillery health
```

## Troubleshooting

**Server does not appear in Claude Code**

- Check that the command path is correct: `which python` or `which distillery-mcp`
- Verify the settings JSON is valid (no trailing commas)
- Check `DISTILLERY_CONFIG` points to a readable file

**Embedding errors**

- Confirm the API key environment variable is set and not empty
- Check that `api_key_env` in `distillery.yaml` matches the variable name
- Provider 429s are surfaced to the caller (no silent retry budget); the embedding budget defaults to unlimited and can be tightened in `distillery.yaml`

**Database errors**

- Ensure the parent directory of `database_path` exists, or use `:memory:` for testing
- If you switch embedding models, you must create a new database — the schema records the model name and rejects mismatches

**HTTP transport / GitHub OAuth**

- `distillery-mcp --transport http` fails with missing credentials: set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`, or set `server.auth.provider: none` in `distillery.yaml` for local testing
- OAuth login fails: verify the GitHub OAuth App callback URL matches your server's `DISTILLERY_BASE_URL`
- See [Operator Deployment](../team/deployment.md) for GitHub OAuth App registration steps
