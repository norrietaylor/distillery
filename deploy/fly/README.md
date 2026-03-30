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
      "type": "http",
      "url": "https://<app-name>.fly.dev/mcp"
    }
  }
}
```

Claude Code will trigger the GitHub OAuth flow on first connection.

## Architecture

- **Transport**: Streamable HTTP (FastMCP) on port 8000
- **Storage**: Local DuckDB on a Fly Volume (`/data/distillery.db`)
- **Auth**: GitHub OAuth via FastMCP's `GitHubProvider`
- **Scaling**: Single machine, scale-to-zero when idle
- **Cost**: ~$2-5/month (256 MB shared CPU + 1 GB volume)

## Backup

Fly takes automatic daily volume snapshots (5-day retention). For additional safety:

```bash
# Manual snapshot
fly volumes snapshots create <volume-id> --app <app-name>

# List snapshots
fly volumes snapshots list <volume-id> --app <app-name>
```
