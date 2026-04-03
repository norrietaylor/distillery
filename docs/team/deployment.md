# Operator Deployment Guide

Deploy the Distillery MCP server in HTTP mode with GitHub OAuth, enabling team members to connect from their Claude Code installations.

## Prerequisites

- Distillery installed: `pip install distillery`
- A public domain or IP address for your server
- A GitHub OAuth App registered (see below)

## Step 1: Register a GitHub OAuth App

1. Visit [GitHub Developer Settings](https://github.com/settings/developers)
2. Click **"New OAuth App"**
3. Fill in:
   - **Application name**: `Distillery` (or your team name)
   - **Homepage URL**: `https://distillery.myteam.com`
   - **Authorization callback URL**: `https://distillery.myteam.com/mcp/auth/callback`
4. Click **"Register application"**
5. Copy the **Client ID** and **Client Secret**

!!! important "Callback URL"
    The callback URL must match exactly. The path is always `/mcp/auth/callback` (managed by FastMCP). HTTPS is required for production.

## Step 2: Set Environment Variables

```bash
# GitHub OAuth credentials
export GITHUB_CLIENT_ID="<your-client-id>"
export GITHUB_CLIENT_SECRET="<your-client-secret>"

# Base URL for OAuth callback (must be publicly accessible)
export DISTILLERY_BASE_URL="https://distillery.myteam.com"

# Embedding provider
export JINA_API_KEY="<your-jina-api-key>"

# Optional: MotherDuck (if using shared cloud storage)
export MOTHERDUCK_TOKEN="<your-motherduck-token>"
```

!!! warning "Secrets"
    Never commit secrets to version control. Use your platform's secret management (Kubernetes secrets, Fly.io secrets, Vault, AWS Secrets Manager, etc.).

## Step 3: Configure distillery.yaml

```yaml
server:
  auth:
    provider: github
    client_id_env: GITHUB_CLIENT_ID
    client_secret_env: GITHUB_CLIENT_SECRET

storage:
  backend: motherduck
  database_path: md:distillery
  motherduck_token_env: MOTHERDUCK_TOKEN

embedding:
  provider: jina
  model: jina-embeddings-v3
  dimensions: 1024
  api_key_env: JINA_API_KEY

team:
  name: My Team

classification:
  confidence_threshold: 0.6
  dedup_skip_threshold: 0.95
  dedup_merge_threshold: 0.80
  dedup_link_threshold: 0.60
  dedup_limit: 5
```

### Configuration Sections

**server.auth**

| Field | Values | Description |
|-------|--------|-------------|
| `provider` | `github`, `none` | Auth provider. `none` allows unauthenticated access (dev only) |
| `client_id_env` | env var name | Environment variable holding GitHub Client ID |
| `client_secret_env` | env var name | Environment variable holding GitHub Client Secret |

**storage**

| Field | Values | Description |
|-------|--------|-------------|
| `backend` | `duckdb`, `motherduck` | Storage backend |
| `database_path` | path | Local path, `s3://...`, or `md:...` for MotherDuck |

### Startup Validations

Distillery validates configuration at startup:

- **MotherDuck**: `database_path` must start with `md:`; if the token env var is not set, a warning is logged and the server continues (it will attempt to connect without authentication)
- **GitHub OAuth**: `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, and `DISTILLERY_BASE_URL` must be set; missing credentials prevent HTTP transport from starting

## Step 4: Start the Server

```bash
distillery-mcp --transport http --port 8000
```

### Verify

```bash
curl -I https://distillery.myteam.com/mcp
# Expected: HTTP 200, 401, or 405
```

Then have a team member follow the [Team Member Guide](team-setup.md) to connect.

## Deployment Scenarios

### Local Development (no auth)

```yaml
server:
  auth:
    provider: none
```

```bash
distillery-mcp --transport http --host 127.0.0.1 --port 8000
```

!!! warning
    Unauthenticated mode. Bind to `127.0.0.1` to restrict to localhost only.

### Production with MotherDuck

```yaml
server:
  auth:
    provider: github
storage:
  backend: motherduck
  database_path: md:distillery
```

### Production with S3 Storage

```yaml
storage:
  backend: duckdb
  database_path: s3://my-bucket/distillery/distillery.db
  s3_region: us-east-1
```

S3 credentials are resolved from `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` or IAM roles.

## Platform-Specific Guides

Platform-specific deployment configs live in the [distill_ops](https://github.com/norrietaylor/distill_ops) repo:

- [Fly.io](https://github.com/norrietaylor/distill_ops/tree/main/fly) — persistent DuckDB on volume, scale-to-zero (~$3-5/month)
- [Prefect Horizon](https://github.com/norrietaylor/distill_ops/tree/main/prefect) — managed hosting with MotherDuck

For other platforms (Docker, Kubernetes, AWS/GCP/Azure), use the root `Dockerfile` in the distillery repo as a starting point:

```bash
docker build -t distillery .
docker run -p 8000:8000 -e JINA_API_KEY=... distillery
```

## Scaling

- Single-worker process, suitable for teams up to ~100 active users
- Storage delegates to the backend (MotherDuck or S3), which scales independently
- For larger teams, deploy multiple instances behind a load balancer pointing to the same backend

## Security Checklist

- [ ] HTTPS enabled (required for OAuth)
- [ ] GitHub OAuth App credentials stored securely
- [ ] MotherDuck/embedding tokens stored securely
- [ ] Server behind firewall (not directly exposed)
- [ ] Logs do not contain sensitive data
- [ ] Team members use GitHub accounts with 2FA
- [ ] OAuth callback URL matches deployment URL exactly

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `GITHUB_CLIENT_ID not set` | Missing OAuth credentials | Set the environment variable |
| `database_path must start with 'md:'` | MotherDuck config mismatch | Use `md:distillery` as the path |
| `MOTHERDUCK_TOKEN not set` (warning) | Missing token for MotherDuck | Set `MOTHERDUCK_TOKEN` env var for authenticated access |
| `Server failed to start on port 8000` | Port in use | Use `--port 9000` or check `lsof -i :8000` |
