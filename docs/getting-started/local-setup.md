# Local Setup

Run Distillery locally with your own DuckDB database and embedding provider. This gives you a private, self-contained knowledge base.

## Prerequisites

- Python 3.11+
- An embedding API key ([Jina AI](https://jina.ai) or OpenAI)

## Install

```bash
# Recommended (no clone needed)
uvx distillery-mcp

# Or install from source
git clone https://github.com/norrietaylor/distillery.git
cd distillery
pip install -e .
```

This registers two CLI entry points:

- `distillery` — the CLI tool (health check, status)
- `distillery-mcp` — the MCP server

## Configure

Create `distillery.yaml`:

```yaml
storage:
  backend: duckdb
  database_path: ~/.distillery/distillery.db

embedding:
  provider: jina
  model: jina-embeddings-v3
  dimensions: 1024
  api_key_env: JINA_API_KEY

classification:
  confidence_threshold: 0.6
  dedup_skip_threshold: 0.95
  dedup_merge_threshold: 0.80
  dedup_link_threshold: 0.60
```

Set your API key:

```bash
export JINA_API_KEY=jina_...
```

!!! tip "No API key?"
    You can use the stub embedding provider (`provider: ""`) for testing. Semantic search won't return meaningful results, but all other operations work normally.

## Connect to Claude Code

Add to your Claude Code MCP settings (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "distillery": {
      "command": "python",
      "args": ["-m", "distillery.mcp"],
      "env": {
        "JINA_API_KEY": "your-jina-api-key",
        "DISTILLERY_CONFIG": "/path/to/distillery.yaml"
      }
    }
  }
}
```

Or use `uvx` (recommended):

```json
{
  "mcpServers": {
    "distillery": {
      "command": "uvx",
      "args": ["distillery-mcp"],
      "env": {
        "JINA_API_KEY": "your-jina-api-key"
      }
    }
  }
}
```

Or use the installed entry point:

```json
{
  "mcpServers": {
    "distillery": {
      "command": "distillery-mcp",
      "env": {
        "JINA_API_KEY": "your-jina-api-key"
      }
    }
  }
}
```

Restart Claude Code and verify:

```text
distillery_metrics(scope="summary")
```

## Embedding Providers

### Jina (default)

Sign up at [jina.ai](https://jina.ai) for an API key:

```bash
export JINA_API_KEY=jina_...
```

### OpenAI

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

### Stub (no API key)

Leave `provider` empty for zero-vector embeddings. Useful for testing:

```yaml
embedding:
  provider: ""
  dimensions: 1024
```

## Cloud Storage Options

### S3-backed DuckDB

DuckDB's `httpfs` extension lets the database file live in S3 (or MinIO, Cloudflare R2):

```yaml
storage:
  backend: duckdb
  database_path: s3://my-bucket/distillery/distillery.db
  s3_region: us-east-1
```

Credentials are resolved from `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` environment variables or IAM roles.

### MotherDuck

[MotherDuck](https://motherduck.com) is DuckDB's managed cloud service:

```yaml
storage:
  backend: motherduck
  database_path: md:distillery
  motherduck_token_env: MOTHERDUCK_TOKEN
```

```bash
export MOTHERDUCK_TOKEN=your-motherduck-token
```

## Next Steps

- See [MCP Server Reference](mcp-setup.md) for the full tool reference and advanced configuration
- See [Team Member Guide](../team/team-setup.md) to connect to a hosted team instance instead
- See [Skills Reference](../skills/index.md) for detailed documentation on each skill
