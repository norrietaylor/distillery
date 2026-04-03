# Fly.io Deployment

Deploy the Distillery MCP server to [Fly.io](https://fly.io) with persistent DuckDB storage on a volume, GitHub OAuth, and scale-to-zero billing.

!!! warning "Demo Server"
    The hosted instance at `distillery-mcp.fly.dev` is a **demo server** for evaluation and testing only. Do not store sensitive, proprietary, or confidential data. There are no uptime guarantees, data may be reset without notice, and storage is not encrypted at rest. For production use, deploy your own instance using the instructions below.

## Prerequisites

- [Fly CLI](https://fly.io/docs/flyctl/install/) installed
- A Fly.io account: `fly auth login`
- A [GitHub OAuth App](deployment.md#step-1-register-a-github-oauth-app) registered

## Configuration Files

| File | Purpose |
|------|---------|
| `deploy/fly/Dockerfile` | Python 3.13-slim image with `distillery-mcp` entrypoint |
| `deploy/fly/fly.toml` | Fly Machine config (scale-to-zero, volume mount, health check) |
| `deploy/fly/distillery-fly.yaml` | Distillery config (DuckDB on volume, Jina embeddings, GitHub OAuth) |

## Quick Start

All commands run from the **repository root**.

### 1. Create the app

```bash
fly apps create <app-name>
```

Update the `app` value in `deploy/fly/fly.toml` to match.

### 2. Create a persistent volume

```bash
fly volumes create distillery_data --size 1 --app <app-name>
```

Creates a 1 GB NVMe volume for DuckDB. Data persists across deploys and restarts.

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
fly status --app <app-name>
fly logs --app <app-name>

curl -X POST https://<app-name>.fly.dev/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

### 6. Configure webhook scheduling (optional)

Set up automated feed polling, rescoring, and KB maintenance via the webhook endpoints:

```bash
# Generate a shared secret
SECRET=$(openssl rand -hex 32)

# Set on Fly.io
fly secrets set DISTILLERY_WEBHOOK_SECRET=$SECRET --app <app-name>

# Set on GitHub (for the Actions cron workflow)
gh secret set DISTILLERY_WEBHOOK_SECRET --body "$SECRET"
gh variable set DISTILLERY_URL --body "https://<app-name>.fly.dev"
```

The GitHub Actions workflow at `.github/workflows/scheduler.yml` runs:

| Schedule | Endpoint | Operation |
|----------|----------|-----------|
| Hourly (:23) | `POST /api/poll` | Poll all feed sources |
| Daily (06:17 UTC) | `POST /api/rescore` | Re-score feed entries |
| Weekly (Mon 07:41 UTC) | `POST /api/maintenance` | KB metrics, quality, stale detection, digest |

Verify manually:

```bash
curl -sf -X POST \
  -H "Authorization: Bearer $SECRET" \
  https://<app-name>.fly.dev/api/poll
```

## Connecting from Claude Code

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

Claude Code triggers the GitHub OAuth flow on first connection.

## Architecture

| Aspect | Details |
|--------|---------|
| **Transport** | Streamable HTTP (FastMCP) on port 8000 + REST webhooks at `/api/*` |
| **Storage** | Local DuckDB on Fly Volume (`/data/distillery.db`) |
| **Auth** | GitHub OAuth via FastMCP `GitHubProvider` (identity gate only) |
| **Scaling** | Single machine, scale-to-zero when idle |
| **Concurrency** | hard_limit=10, soft_limit=5 |
| **Memory** | 512 MB minimum |
| **Cost** | ~$3-5/month (512 MB shared CPU + 1 GB volume) |

### Authentication Model

GitHub OAuth is used purely as an **identity gate** — it verifies who the caller is, not what they can access on GitHub. The server never gains access to user repositories or organizations.

The flow (handled by FastMCP's `GitHubProvider`):

1. OAuth requests only the `user` scope (read-only public profile)
2. `GitHubTokenVerifier` calls `https://api.github.com/user` to verify tokens
3. Identity claims (`login`, `name`, `email`) are available to tool handlers
4. The raw GitHub token is never exposed to application code

### Rate Limiting

| Guard | Default | Purpose |
|-------|---------|---------|
| `embedding_budget_daily` | 500 | Max Jina API calls/day (0 = unlimited) |
| `max_db_size_mb` | 900 | Reject writes above this DB size |
| `warn_db_size_pct` | 80 | Warn in `distillery_metrics` at this % |

Budget counters are stored in DuckDB's `_meta` table and survive scale-to-zero restarts.

## Backup

Fly takes automatic daily volume snapshots (5-day retention). For additional safety:

```bash
fly volumes snapshots create <volume-id> --app <app-name>
fly volumes snapshots list <volume-id> --app <app-name>
```
