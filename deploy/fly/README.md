# Fly.io Deployment

Deploy the Distillery MCP server to [Fly.io](https://fly.io) with persistent DuckDB storage on a volume, GitHub OAuth, and scale-to-zero billing.

## Prerequisites

- [Fly CLI](https://fly.io/docs/flyctl/install/) installed
- A Fly.io account: `fly auth login`
- A [GitHub OAuth App](../../docs/deployment.md) registered

## Configuration

| File | Purpose |
|------|---------|
| `Dockerfile` | Python 3.13-slim image with `distillery-mcp` entrypoint |
| `fly.toml` | Fly Machine config (scale-to-zero, volume mount, health check) |
| `distillery-fly.yaml` | Distillery config (DuckDB on volume, Jina embeddings, GitHub OAuth) |

## Quick Start

All commands run from the **repository root**.

### 1. Create the app

```bash
fly apps create <app-name>
```

Then update the `app` value in `deploy/fly/fly.toml` to match your app name.

### 2. Create a persistent volume

```bash
fly volumes create distillery_data --size 1 --app <app-name>
```

This creates a 1 GB NVMe volume for DuckDB storage. Data persists across deploys and machine restarts.

### 3. Set secrets

```bash
fly secrets set \
  JINA_API_KEY=<your-jina-api-key> \
  GITHUB_CLIENT_ID=<your-github-client-id> \
  GITHUB_CLIENT_SECRET=<your-github-client-secret> \
  DISTILLERY_BASE_URL=https://<app-name>.fly.dev \
  --app <app-name>
```

### 4. Deploy

```bash
fly deploy -c deploy/fly/fly.toml
```

### 5. Verify

```bash
# Check machine status
fly status --app <app-name>

# View logs
fly logs --app <app-name>

# Test the endpoint
curl -X POST https://<app-name>.fly.dev/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

## Connecting from Claude Code

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "distillery": {
      "url": "https://<app-name>.fly.dev/mcp",
      "transport": "http"
    }
  }
}
```

Claude Code will trigger the GitHub OAuth flow on first connection.

## Architecture

- **Transport**: Streamable HTTP (FastMCP) on port 8000
- **Storage**: Local DuckDB on a Fly Volume (`/data/distillery.db`)
- **Auth**: GitHub OAuth via FastMCP's `GitHubProvider` (identity gate only — see below)
- **Scaling**: Single machine, scale-to-zero when idle
- **Concurrency**: hard_limit=10, soft_limit=5 requests (configured in `fly.toml`)
- **Memory**: 512 MB minimum (256 MB causes OOM with DuckDB + FastMCP)
- **Cost**: ~$3-5/month (512 MB shared CPU + 1 GB volume)

### Authentication model

GitHub OAuth is used **purely as an identity gate** — it verifies who the caller is, not what they can access on GitHub. The server never gains access to the user's repositories, organizations, or other GitHub resources.

How it works (handled by FastMCP's [`GitHubProvider`](https://github.com/jlowin/fastmcp/blob/main/src/fastmcp/server/auth/providers/github.py)):

1. OAuth flow requests only the `user` scope (read-only public profile)
2. `GitHubTokenVerifier` calls `https://api.github.com/user` to verify tokens
3. Identity claims extracted: `login`, `name`, `email`, `avatar_url`
4. Claims are available to tool handlers via FastMCP's `Context` object
5. The raw GitHub token is never exposed to application code

**Not included**: organization membership checks (`read:org` scope not requested), repository access, or any write permissions. To restrict access by org membership, extend `required_scopes` to `["user", "read:org"]` and add org-checking middleware.

### Rate limiting

Resource protection is configured via the `rate_limit` section in `distillery-fly.yaml`:

| Guard | Default | Purpose |
|-------|---------|---------|
| `embedding_budget_daily` | 500 | Max Jina API calls/day (0=unlimited) |
| `max_db_size_mb` | 900 | Reject writes above this DB size |
| `warn_db_size_pct` | 80 | Warn in `distillery_status` at this % |

Budget counters are stored in DuckDB's `_meta` table and survive scale-to-zero restarts.

## Backup

Fly takes automatic daily volume snapshots (5-day retention). For additional safety:

```bash
# Manual snapshot
fly volumes snapshots create <volume-id> --app <app-name>

# List snapshots
fly volumes snapshots list <volume-id> --app <app-name>
```
