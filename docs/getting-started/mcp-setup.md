# MCP Server Reference

Complete reference for the Distillery MCP server — all 22 tools, configuration options, and troubleshooting.

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
| `distillery_status` | Database stats: total entries, breakdown by type/status, embedding model |
| `distillery_store` | Store a new knowledge entry with duplicate and conflict checks |
| `distillery_get` | Retrieve a single entry by UUID |
| `distillery_update` | Partially update an existing entry (with metadata re-validation) |
| `distillery_search` | Semantic search using cosine similarity; returns ranked results |
| `distillery_find_similar` | Find entries similar to given text (for deduplication) |
| `distillery_list` | List entries with optional filtering and pagination |
| `distillery_classify` | Classify an entry by type with LLM-based confidence scoring |
| `distillery_review_queue` | List entries pending manual review |
| `distillery_resolve_review` | Resolve a pending review entry (accept/reject/reclassify) |
| `distillery_check_dedup` | Check content for duplicates against existing entries |
| `distillery_check_conflicts` | Detect semantic contradictions with existing entries |
| `distillery_metrics` | Usage dashboard: entries, activity, search, quality, staleness |
| `distillery_quality` | Aggregate retrieval quality metrics from implicit feedback |
| `distillery_stale` | Surface entries not accessed within a configurable time window |
| `distillery_tag_tree` | Nested tree of all tags in use with entry counts |
| `distillery_type_schemas` | Metadata schema registry for all entry types |
| `distillery_watch` | List, add, or remove monitored feed sources |
| `distillery_poll` | Trigger a feed poll cycle (fetch, score, store) |
| `distillery_interests` | Return user's interest profile (top tags, domains, repos) |
| `distillery_suggest_sources` | Interest profile with suggestion context for source discovery |
| `distillery_rescore` | Re-score feed entries against current interest profile |

## Verifying the Server

Call the `distillery_status` MCP tool from within Claude Code:

```
distillery_status
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
