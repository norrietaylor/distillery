# Distillery MCP Server Setup

This guide explains how to connect Claude Code (or any MCP-compatible client)
to the Distillery MCP server.

## Prerequisites

- Python 3.11 or later
- Distillery installed in your Python environment
- An embedding provider API key (Jina or OpenAI) if you want semantic search

## Installation

Install Distillery from the project root:

```bash
pip install -e .
```

This registers two CLI entry points:

- `distillery` -- the CLI tool (health check, etc.)
- `distillery-mcp` -- the MCP server

## Configuration

Distillery reads `distillery.yaml` from the current working directory, or from
the path set in the `DISTILLERY_CONFIG` environment variable.

Create a minimal `distillery.yaml`:

```yaml
storage:
  backend: duckdb
  database_path: ~/.distillery/distillery.db

embedding:
  provider: jina          # or "openai", or "" for stub (no semantic search)
  model: jina-embeddings-v3
  dimensions: 1024
  api_key_env: JINA_API_KEY  # name of the env var that holds your key
```

If no config file is present, Distillery uses built-in defaults (stub embedding
provider, in-memory database path `~/.distillery/distillery.db`).

## Starting the Server

### Via Python module

```bash
python -m distillery.mcp
```

### Via installed entry point

```bash
distillery-mcp
```

By default, the server communicates over `stdio` and logs to `stderr`.

For team access, use HTTP transport with GitHub OAuth:

```bash
distillery-mcp --transport http --port 8000
```

See [deployment.md](deployment.md) for full HTTP setup and [team-setup.md](team-setup.md) for
connecting team members.

## Connecting Claude Code

### Local (stdio)

Add the following to your Claude Code MCP settings file
(`~/.claude/settings.json` or the project-level `.claude/settings.json`):

```json
{
  "mcpServers": {
    "distillery": {
      "command": "python",
      "args": ["-m", "distillery.mcp"],
      "env": {
        "JINA_API_KEY": "your-jina-api-key-here",
        "DISTILLERY_CONFIG": "/path/to/your/distillery.yaml"
      }
    }
  }
}
```

If you installed the package and `distillery-mcp` is on your `PATH`, you can
use the entry point instead:

```json
{
  "mcpServers": {
    "distillery": {
      "command": "distillery-mcp",
      "env": {
        "JINA_API_KEY": "your-jina-api-key-here"
      }
    }
  }
}
```

After saving the settings file, restart Claude Code or reload the MCP servers.
You should see "distillery" appear in the connected MCP servers list.

### Remote (HTTP)

For team access via a hosted Distillery server:

```json
{
  "mcpServers": {
    "distillery": {
      "url": "https://your-distillery-host.example.com/mcp",
      "transport": "http"
    }
  }
}
```

On first use, Claude Code will open a browser window for GitHub OAuth login.
No local installation or API keys needed — the server handles embedding and
storage.

See [team-setup.md](team-setup.md) for the full team member guide.

## Available Tools

Once connected, the following tools are available:

| Tool | Description |
|------|-------------|
| `distillery_status` | Returns database stats: total entries, breakdown by type and status, embedding model in use |
| `distillery_store` | Store a new knowledge entry; checks for duplicates, conflicts, and returns warnings |
| `distillery_get` | Retrieve a single entry by UUID |
| `distillery_update` | Partially update an existing entry (with metadata re-validation) |
| `distillery_search` | Semantic search using cosine similarity; returns ranked results |
| `distillery_find_similar` | Find entries similar to a given text (for deduplication) |
| `distillery_list` | List entries with optional filtering and pagination |
| `distillery_classify` | Classify an entry by type with LLM-based confidence scoring |
| `distillery_review_queue` | List entries pending manual review |
| `distillery_resolve_review` | Resolve a pending review entry (accept/reject/reclassify) |
| `distillery_check_dedup` | Check content for duplicates against existing entries |
| `distillery_check_conflicts` | Detect semantic contradictions between new content and existing entries |
| `distillery_metrics` | Comprehensive usage dashboard: entries, activity, search, quality, staleness |
| `distillery_quality` | Aggregate retrieval quality metrics from implicit feedback signals |
| `distillery_stale` | Surface entries not accessed within a configurable time window |
| `distillery_tag_tree` | Return a nested tree of all tags in use with entry counts per node |
| `distillery_type_schemas` | Return the metadata schema registry for all entry types |
| `distillery_watch` | List, add, or remove monitored feed sources |
| `distillery_poll` | Trigger a feed poll cycle and return results (fetched, scored, stored counts) |
| `distillery_interests` | Return the user's interest profile (top tags, domains, repos, expertise) |
| `distillery_suggest_sources` | Return interest profile with suggestion context for source discovery |

## Verifying the Server Works

Use the `distillery_status` tool to confirm the server is running and the
database is accessible:

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
  "database_path": "/Users/you/.distillery/distillery.db"
}
```

You can also run the CLI health check directly:

```bash
distillery health
```

## Embedding Providers

### Jina (default)

Sign up at [jina.ai](https://jina.ai) to obtain an API key. Set it via:

```bash
export JINA_API_KEY=jina_...
```

Or reference it from `distillery.yaml` via `api_key_env: JINA_API_KEY`.

### OpenAI

Set your OpenAI API key:

```bash
export OPENAI_API_KEY=sk-...
```

Update `distillery.yaml`:

```yaml
embedding:
  provider: openai
  model: text-embedding-3-small
  dimensions: 1536
  api_key_env: OPENAI_API_KEY
```

### Stub (no API key required)

Leave `provider` empty in `distillery.yaml` to use the built-in stub provider.
The stub returns zero vectors, so semantic search results will not be
meaningful, but all other operations (store, get, update, list) work normally.

```yaml
embedding:
  provider: ""
  dimensions: 1024
```

## Persistent Storage for Cloud Deployments

By default Distillery stores the DuckDB database on the local filesystem.
When running on ephemeral infrastructure (e.g. FastMCP Cloud / Prefect Horizon)
the local `/tmp` directory is wiped on every container reprovision, losing all
stored knowledge.  Two persistent-storage options are supported.

### Option A: S3-backed DuckDB

DuckDB's `httpfs` extension lets the database file live in an S3 bucket (or any
S3-compatible object store such as MinIO or Cloudflare R2).

**`distillery.yaml`**

```yaml
storage:
  backend: duckdb
  database_path: s3://my-bucket/distillery/distillery.db
  s3_region: us-east-1
  # s3_endpoint: https://my-minio.example.com  # for non-AWS services
```

**Credentials** — resolved in this order:
1. `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` environment variables
2. `AWS_SESSION_TOKEN` (for temporary STS credentials)
3. IAM role / instance metadata (no env vars needed on AWS infrastructure)

MCP server settings with explicit credentials:

```json
{
  "mcpServers": {
    "distillery": {
      "command": "distillery-mcp",
      "env": {
        "JINA_API_KEY": "your-jina-api-key-here",
        "DISTILLERY_CONFIG": "/path/to/distillery.yaml",
        "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
        "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "AWS_DEFAULT_REGION": "us-east-1"
      }
    }
  }
}
```

### Option B: MotherDuck

> **Known limitation:** MotherDuck does not support the DuckDB VSS extension.
> HNSW vector index creation will fail, which means semantic search will not work.
> Use S3-backed DuckDB (Option A) for deployments that require search.
> MotherDuck can be used for basic CRUD operations (store, get, list) only.

[MotherDuck](https://motherduck.com) is DuckDB's managed cloud service.  Databases
are stored in your MotherDuck account and accessed via the `md:` URI prefix.

**`distillery.yaml`**

```yaml
storage:
  backend: motherduck
  database_path: md:distillery
  motherduck_token_env: MOTHERDUCK_TOKEN  # default; can be omitted
```

**Credentials** — set `MOTHERDUCK_TOKEN` in your environment:

```bash
export MOTHERDUCK_TOKEN=your-motherduck-token-here
```

MCP server settings:

```json
{
  "mcpServers": {
    "distillery": {
      "command": "distillery-mcp",
      "env": {
        "JINA_API_KEY": "your-jina-api-key-here",
        "DISTILLERY_CONFIG": "/path/to/distillery.yaml",
        "MOTHERDUCK_TOKEN": "your-motherduck-token-here"
      }
    }
  }
}
```

## Troubleshooting

**Server does not appear in Claude Code**

- Check that the command path is correct: `which python` or `which distillery-mcp`
- Verify the settings JSON is valid (no trailing commas)
- Check `DISTILLERY_CONFIG` points to a readable file

**Embedding errors**

- Confirm the API key environment variable is set and not empty
- Check that the `api_key_env` field in `distillery.yaml` matches the variable name

**Database errors**

- Ensure the parent directory of `database_path` exists, or use `:memory:` for
  testing
- If you switch embedding models, you must create a new database -- the schema
  records the model name and rejects mismatches

**HTTP transport / GitHub OAuth**

- `distillery-mcp --transport http` fails with missing credentials: set
  `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` env vars, or set
  `server.auth.provider: none` in `distillery.yaml` for unauthenticated local testing
- OAuth login fails: verify the GitHub OAuth App callback URL matches your
  server's `DISTILLERY_BASE_URL`
- See [deployment.md](deployment.md) for GitHub OAuth App registration steps
