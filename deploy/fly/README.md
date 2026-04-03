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

### 6. Configure webhook scheduling (optional)

Enable automated feed polling, rescoring, and KB maintenance:

```bash
SECRET=$(openssl rand -hex 32)
fly secrets set DISTILLERY_WEBHOOK_SECRET=$SECRET --app <app-name>
gh secret set DISTILLERY_WEBHOOK_SECRET --body "$SECRET"
gh variable set DISTILLERY_URL --body "https://<app-name>.fly.dev"
```

The GitHub Actions workflow (`.github/workflows/scheduler.yml`) calls `/api/poll` hourly, `/api/rescore` daily, and `/api/maintenance` weekly.

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

- **Transport**: Streamable HTTP (FastMCP) on port 8000 + REST webhooks at `/api/*`
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

## Database Migrations

Distillery uses a **forward-only schema migration system** that automatically runs on startup. Schema migrations are additive only—they never modify or delete existing columns. This ensures:

- **Automatic updates**: New deployments automatically migrate the database schema to the latest version
- **Zero-downtime**: Additive migrations don't require data restructuring or downtime
- **Safe rollbacks**: Pre-deploy backups allow reverting to a previous schema version if needed

### How Automatic Migrations Work

When the server starts, it:

1. Checks the current `schema_version` in the `_meta` table
2. Executes any pending migrations in order (migration 1, 2, 3, etc.)
3. Updates `schema_version` after each migration
4. Completes startup once all migrations are applied

No manual intervention is required—migrations run automatically on deploy.

### Pre-Deploy Backup

Before deploying a new version with schema migrations, create a backup:

```bash
# SSH into the machine and export all data
fly ssh console -C "distillery export --output /data/backup-$(date +%Y%m%d).json" --app <app-name>
```

This creates a portable JSON export containing all entries, feed sources, and metadata. Embeddings are omitted so the export is independent of embedding model changes.

### Volume Snapshots

Fly.io automatically takes daily volume snapshots (5-day retention). For manual snapshots before risky operations:

```bash
# Create a manual snapshot
fly volumes snapshots create <volume-id> --app <app-name>

# List all snapshots
fly volumes snapshots list <volume-id> --app <app-name>

# Restore from snapshot (creates a new volume; restore manually afterward)
fly volumes snapshots restore <snapshot-id> --app <app-name>
```

### Breaking Migration Procedure

If a new Distillery version requires breaking schema changes, the migration system is still forward-only—it never deletes data. However, to reset for incompatible versions:

1. **Export current data**:
   ```bash
   fly ssh console -C "distillery export --output /data/backup-before-breaking.json" --app <app-name>
   ```

2. **Create a volume snapshot** (optional extra safety):
   ```bash
   fly volumes snapshots create <volume-id> --app <app-name>
   ```

3. **Deploy the new version**:
   ```bash
   fly deploy -c deploy/fly/fly.toml
   ```
   The new schema migrations will run on startup, creating fresh tables as needed.

4. **Re-import previous data** (if compatible):
   ```bash
   fly ssh console --app <app-name>
   # Inside the SSH console:
   distillery import --input /data/backup-before-breaking.json --mode merge
   exit
   ```

5. **Verify** the server is operational:
   ```bash
   fly logs --app <app-name>
   # Look for successful startup and no errors
   ```

6. **Clean up**:
   ```bash
   fly ssh console -C "rm /data/backup-before-breaking.json" --app <app-name>
   ```

### Rollback from Backup

If a deployment causes issues, restore from a pre-deploy backup:

#### Option 1: Restore from JSON Export

```bash
# Export current (broken) database as a fallback
fly ssh console -C "distillery export --output /data/broken-state.json" --app <app-name>

# Clear and restore from backup
fly ssh console --app <app-name>
# Inside the SSH console:
# First, delete the current database file to start fresh
rm /data/distillery.db
# Restart the machine to recreate the schema
exit

fly machines restart <machine-id> --app <app-name>

# Wait for restart, then import the backup
fly ssh console -C "distillery import --input /data/backup-YYYYMMDD.json --mode replace" --app <app-name>

# Verify
fly logs --app <app-name>
```

#### Option 2: Restore from Volume Snapshot

```bash
# List available snapshots
fly volumes snapshots list <volume-id> --app <app-name>

# Create a new volume from the snapshot
fly volumes snapshots restore <snapshot-id> --app <app-name>

# Detach the broken volume
fly volumes detach <current-volume-id> --app <app-name>

# Attach the restored volume
fly machines update <machine-id> --mount-volume <restored-volume-id>:/data --app <app-name>

# Restart
fly machines restart <machine-id> --app <app-name>

# Verify
fly logs --app <app-name>
```

### Schema Version Tracking

The current schema version is stored in the `_meta` table. View it:

```bash
# From local CLI
distillery status
# Output includes: schema_version: 6, duckdb_version: 1.5.x

# From SSH console
fly ssh console -C "distillery status" --app <app-name>
```

## Backup

Fly takes automatic daily volume snapshots (5-day retention). For additional safety:

```bash
# Manual snapshot
fly volumes snapshots create <volume-id> --app <app-name>

# List snapshots
fly volumes snapshots list <volume-id> --app <app-name>
```
