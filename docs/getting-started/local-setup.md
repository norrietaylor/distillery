# Local Setup

Run Distillery locally with your own DuckDB database and embedding provider. This gives you a private, self-contained knowledge base.

## Prerequisites

- Python 3.11+
- Optional: an embedding API key ([Jina AI](https://jina.ai) or OpenAI). On-device `fastembed` (the plugin's install-time default) requires no key.

## Install

### Run with uvx (recommended)

`uvx` runs the package ephemerally — no persistent install, no virtualenv to manage:

```bash
# Bundles the fastembed extra so on-device embeddings work out of the box
uvx --from 'distillery-mcp[fastembed]>=0.6.0' distillery-mcp

# Or, if you intend to use Jina/OpenAI only:
uvx distillery-mcp
```

### Install persistently (pip / source)

A persistent install registers CLI entry points (`distillery`, `distillery-mcp`) on your PATH:

```bash
# From PyPI (with on-device fastembed)
pip install 'distillery-mcp[fastembed]'

# Or without fastembed if you only need Jina/OpenAI
pip install distillery-mcp

# Or install from source
git clone https://github.com/norrietaylor/distillery.git
cd distillery
pip install -e '.[fastembed]'
```

## Configure

Create `distillery.yaml`. The plugin's install-time default is on-device `fastembed` — no API key required:

```yaml
storage:
  backend: duckdb
  database_path: ~/.distillery/distillery.db

embedding:
  provider: fastembed
  model: BAAI/bge-small-en-v1.5
  dimensions: 384

classification:
  confidence_threshold: 0.6
  dedup_skip_threshold: 0.95
  dedup_merge_threshold: 0.80
  dedup_link_threshold: 0.60
```

Prefer a hosted provider? See [Embedding Providers](#embedding-providers) below for Jina, OpenAI, and stub configurations.

## Connect to Claude Code

Add to your Claude Code MCP settings (`~/.claude/settings.json`). The default fastembed setup needs no API key:

```json
{
  "mcpServers": {
    "distillery": {
      "command": "uvx",
      "args": ["--from", "distillery-mcp[fastembed]>=0.6.0", "distillery-mcp"],
      "env": {
        "DISTILLERY_EMBEDDING_PROVIDER": "fastembed",
        "DISTILLERY_CONFIG": "/path/to/distillery.yaml",
        "GITHUB_TOKEN": "ghp_..."
      }
    }
  }
}
```

For Jina or OpenAI, swap `DISTILLERY_EMBEDDING_PROVIDER` and add the matching key (`JINA_API_KEY` or `OPENAI_API_KEY`) to the `env` block.

Or use the installed entry point (if you ran `pip install`):

```json
{
  "mcpServers": {
    "distillery": {
      "command": "distillery-mcp",
      "env": {
        "DISTILLERY_EMBEDDING_PROVIDER": "fastembed",
        "DISTILLERY_CONFIG": "/path/to/distillery.yaml",
        "GITHUB_TOKEN": "ghp_..."
      }
    }
  }
}
```

Or use `python -m` (if installed from source):

```json
{
  "mcpServers": {
    "distillery": {
      "command": "python",
      "args": ["-m", "distillery.mcp"],
      "env": {
        "DISTILLERY_EMBEDDING_PROVIDER": "fastembed",
        "DISTILLERY_CONFIG": "/path/to/distillery.yaml",
        "GITHUB_TOKEN": "ghp_..."
      }
    }
  }
}
```

Restart Claude Code and verify:

```text
distillery_status()
```

## Private Repository Polling

To monitor private GitHub repositories via `/watch`, set the `GITHUB_TOKEN` environment variable. This is optional — public repos work without it.

```bash
export GITHUB_TOKEN=ghp_...
```

The token is passed to the GitHub adapter at poll time. It is never stored in entry metadata or logged. Distillery's security module redacts `ghp_`, `gho_`, and `github_pat_` patterns from all log output.

If `GITHUB_TOKEN` is not set, feeds poll public repos only. A DEBUG-level log message indicates which mode is active.

## Embedding Providers

### fastembed (plugin default, no API key)

Runs ONNX inference on-device — no network call, no API key. Requires the `[fastembed]` extra. The default model (`bge-small`) is ~67 MB and is downloaded once on first use (cached under `~/.cache/fastembed`).

```yaml
embedding:
  provider: fastembed
  model: BAAI/bge-small-en-v1.5
  dimensions: 384
```

Other supported aliases: `bge-base` (768 dim), `bge-large` (1024 dim), `nomic`, `mxbai` — see [`distillery.yaml.example`](https://github.com/norrietaylor/distillery/blob/main/distillery.yaml.example) (Option C) for the full block.

### Jina

Sign up at [jina.ai](https://jina.ai) for an API key:

```bash
export JINA_API_KEY=jina_...
```

```yaml
embedding:
  provider: jina
  model: jina-embeddings-v3
  dimensions: 1024
  api_key_env: JINA_API_KEY
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
