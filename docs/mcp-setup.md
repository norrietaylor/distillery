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

The server communicates over `stdio` using the MCP protocol and logs to
`stderr` so it does not interfere with the transport stream.

## Connecting Claude Code

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

## Available Tools

Once connected, the following tools are available:

| Tool | Description |
|------|-------------|
| `distillery_status` | Returns database stats: total entries, breakdown by type and status, embedding model in use |
| `distillery_store` | Store a new knowledge entry; checks for duplicates and returns warnings |
| `distillery_get` | Retrieve a single entry by UUID |
| `distillery_update` | Partially update an existing entry |
| `distillery_search` | Semantic search using cosine similarity; returns ranked results |
| `distillery_find_similar` | Find entries similar to a given text (for deduplication) |
| `distillery_list` | List entries with optional filtering and pagination |

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
