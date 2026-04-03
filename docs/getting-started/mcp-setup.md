# MCP Server Reference

Complete reference for the Distillery MCP server — all 18 tools, configuration options, and troubleshooting.

## Starting the Server

### stdio (local, default)

```bash
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

## Configuration

Distillery reads `distillery.yaml` from the current working directory, or from the path set in `DISTILLERY_CONFIG`.

See [`distillery.yaml.example`](https://github.com/norrietaylor/distillery/blob/main/distillery.yaml.example) for all available settings.

## Available Tools

| Tool | Description |
|------|-------------|
| **CRUD** | |
| `distillery_store` | Store a new knowledge entry with content, tags, and metadata |
| `distillery_get` | Retrieve a single entry by UUID |
| `distillery_update` | Partially update an existing entry (tags, status, metadata) |
| `distillery_list` | List entries with filtering, pagination, and optional review-queue enrichment (`output_mode="review"`) |
| **Discovery** | |
| `distillery_search` | Semantic search using cosine similarity; returns ranked results |
| `distillery_find_similar` | Find similar entries — supports dedup mode (`dedup_action=true`) and conflict detection (`conflict_check=true`) |
| `distillery_aggregate` | Group entry counts by field (type, status, project, author) |
| `distillery_stale` | Surface entries not accessed within a configurable time window |
| `distillery_tag_tree` | Nested tree of all tags in use with entry counts |
| **Classification** | |
| `distillery_classify` | Classify an entry by type with LLM-based confidence scoring |
| `distillery_resolve_review` | Resolve a pending review entry (accept/reject/reclassify) |
| **Observability** | |
| `distillery_metrics` | Usage dashboard with configurable scope: `"summary"` (health check), `"full"` (all metrics), or `"search_quality"` (retrieval stats) |
| **Feeds** | |
| `distillery_watch` | List, add, or remove monitored feed sources (RSS, GitHub) |
| `distillery_poll` | Trigger a feed poll cycle (fetch, score, store) |
| `distillery_rescore` | Re-score feed entries against current interest profile |
| `distillery_interests` | User's interest profile (top tags/domains); optionally includes source suggestions (`suggest_sources=true`) |
| **Configuration** | |
| `distillery_configure` | Update runtime configuration (thresholds, settings) and persist to `distillery.yaml` |
| `distillery_type_schemas` | Metadata schema registry for all entry types |

## Verifying the Server

Call the `distillery_metrics` MCP tool from within Claude Code:

```text
distillery_metrics(scope="summary")
```

Expected response:

```json
{
  "status": "ok",
  "total_entries": 0,
  "entries_by_type": {},
  "entries_by_status": {},
  "database_size_bytes": null,
  "embedding_model": "jina-embeddings-v3",
  "embedding_dimensions": 1024,
  "database_path": "/home/you/.distillery/distillery.db"
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

**Database errors**

- Ensure the parent directory of `database_path` exists, or use `:memory:` for testing
- If you switch embedding models, you must create a new database — the schema records the model name and rejects mismatches

**HTTP transport / GitHub OAuth**

- `distillery-mcp --transport http` fails with missing credentials: set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`, or set `server.auth.provider: none` in `distillery.yaml` for local testing
- OAuth login fails: verify the GitHub OAuth App callback URL matches your server's `DISTILLERY_BASE_URL`
- See [Operator Deployment](../team/deployment.md) for GitHub OAuth App registration steps
