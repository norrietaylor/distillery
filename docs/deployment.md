# Deployment Guide — Running Distillery as a Team Service

This guide explains how to deploy the Distillery MCP server in HTTP mode with GitHub OAuth authentication, enabling team members to connect securely from their Claude Code installations.

## Prerequisites

- Distillery installed: `pip install distillery`
- A public domain name or IP address for your server (required for OAuth callback)
- A GitHub OAuth App registered (see below)
- Appropriate hosting infrastructure (server, container, PaaS)

## Step 1: Register a GitHub OAuth App

GitHub OAuth requires an application to be registered with GitHub before the server can authenticate users.

### Create the OAuth App

1. Visit https://github.com/settings/developers
2. Click **"New OAuth App"**
3. Fill in the form:

   - **Application name**: `Distillery` (or your team name, e.g., `My Team Distillery`)
   - **Homepage URL**: The base URL of your deployment (e.g., `https://distillery.myteam.com`)
   - **Application description** (optional): `Team knowledge base MCP server`
   - **Authorization callback URL**: `https://distillery.myteam.com/mcp/auth/callback`

4. Click **"Register application"**
5. GitHub will show you:
   - **Client ID** — Copy this value
   - **Client Secret** — Copy this value and store securely

### Important notes on callback URLs

- The callback URL must match exactly what you use in `DISTILLERY_BASE_URL`
- The path is always `/mcp/auth/callback` (managed by FastMCP)
- HTTPS is required for production deployments
- For local testing, `http://localhost:8000/mcp/auth/callback` is allowed

## Step 2: Set Environment Variables

The Distillery server reads configuration from environment variables and the `distillery.yaml` config file.

### Required environment variables

For HTTP mode with GitHub OAuth:

```bash
# GitHub OAuth credentials (from Step 1)
export GITHUB_CLIENT_ID="<your-client-id>"
export GITHUB_CLIENT_SECRET="<your-client-secret>"

# Base URL of your server (used for OAuth callback)
# Must be publicly accessible and match your GitHub OAuth App callback URL
export DISTILLERY_BASE_URL="https://distillery.myteam.com"

# Optional: MotherDuck token (if using MotherDuck for shared storage)
export MOTHERDUCK_TOKEN="<your-motherduck-token>"
```

### Environment variable naming

The environment variable names are configurable in `distillery.yaml`. The defaults above match the example config. See Step 3 for customization.

### Storing secrets securely

**Never commit secrets to version control.** Store them in:
- Kubernetes secrets (if using Kubernetes)
- Docker secrets (if using Docker Compose)
- HashiCorp Vault
- AWS Secrets Manager / Parameter Store
- GitHub Actions secrets (for CI/CD)
- `.env` file (local development only, in `.gitignore`)

## Step 3: Configure distillery.yaml

Create or update `distillery.yaml` with server and storage configuration.

### Minimal server configuration

```yaml
# distillery.yaml
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

### Configuration sections

**server** (NEW in this spec)
- `auth.provider`: `"github"` or `"none"` (default `"none"`)
  - `"github"` requires valid GitHub OAuth credentials
  - `"none"` allows HTTP without auth (development only)
- `auth.client_id_env`: Name of the environment variable holding the GitHub Client ID
- `auth.client_secret_env`: Name of the environment variable holding the GitHub Client Secret

**storage** (existing)
- `backend`: `"duckdb"` (local/S3), `"motherduck"`, or your storage backend
- `database_path`: Path to the database
  - Local: `~/.distillery/distillery.db`
  - S3: `s3://my-bucket/distillery.db`
  - MotherDuck: `md:distillery` (must start with `md:` for MotherDuck backend)
- `motherduck_token_env`: Environment variable name holding the MotherDuck token (if using MotherDuck)

**embedding** (existing)
- `provider`: `"jina"`, `"openai"`, or `"mock"`
- `model`: Embedding model to use
- `dimensions`: Vector dimensions
- `api_key_env`: Environment variable name holding the API key

**team** (existing)
- `name`: Human-readable team name for knowledge entries

**classification** (existing)
- Deduplication thresholds (see `distillery.yaml.example` for details)

### Validations performed at startup

Distillery validates configuration at startup to catch errors early:

1. **MotherDuck backend validation** — If `storage.backend == "motherduck"`:
   - `database_path` must start with `md:`
   - The environment variable named by `motherduck_token_env` must be set

   If validation fails, the server will print an error and exit.

2. **GitHub OAuth validation** — If `server.auth.provider == "github"`:
   - Both `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` must be set and non-empty
   - `DISTILLERY_BASE_URL` must be set and valid

   If validation fails, the server will print an error and exit.

## Step 4: Start the Server

### Basic HTTP mode

```bash
distillery-mcp --transport http --port 8000
```

This starts the Distillery MCP server in HTTP mode on port 8000, listening on all interfaces (`0.0.0.0`).

### With custom host/port

```bash
distillery-mcp --transport http --host 0.0.0.0 --port 8080
```

### With environment variable configuration

```bash
# Set variables from .env file or shell
export DISTILLERY_HOST=0.0.0.0
export DISTILLERY_PORT=8000

distillery-mcp --transport http
```

### CLI flags reference

```
distillery-mcp --help

Usage: distillery-mcp [OPTIONS]

Options:
  --transport {stdio|http}  Transport mode (default: stdio)
  --host HOST              Bind address (default: 0.0.0.0, env: DISTILLERY_HOST)
  --port PORT              Bind port (default: 8000, env: DISTILLERY_PORT)
  --help                   Show this help message
```

### Expected startup output

```
Starting Distillery MCP server in HTTP mode
Host: 0.0.0.0
Port: 8000
Path: /mcp
Auth: GitHub OAuth enabled
Storage: MotherDuck (distillery)
Embedding: Jina (1024 dimensions)
```

If you don't see all fields, check that environment variables and `distillery.yaml` are configured correctly.

## Step 5: Verify the Server is Running

### Test from the server host

```bash
# Check that the server is responding
curl -I https://distillery.myteam.com/mcp

# Expected: HTTP 200, 401, or 405
# (401 is expected on auth-enabled deployments before login;
#  405 is normal for MCP endpoints that only accept POST)
```

### Test from a client machine

Use a team member's Claude Code installation to verify connectivity:
1. Have them follow the steps in **docs/team-setup.md**
2. Have them invoke `/recall test` and confirm results

## Deployment Scenarios

### Local development (no auth)

```yaml
server:
  auth:
    provider: none

storage:
  backend: duckdb
  database_path: ~/.distillery/distillery.db
```

Start with:
```bash
distillery-mcp --transport http --port 8000
```

Warning: This mode allows unauthenticated access. Use only for local development.

### Production with MotherDuck

```yaml
server:
  auth:
    provider: github
    client_id_env: GITHUB_CLIENT_ID
    client_secret_env: GITHUB_CLIENT_SECRET

storage:
  backend: motherduck
  database_path: md:distillery
```

Set environment variables:
```bash
export GITHUB_CLIENT_ID="github_oauth_client_id"
export GITHUB_CLIENT_SECRET="github_oauth_client_secret"
export DISTILLERY_BASE_URL="https://distillery.myteam.com"
export MOTHERDUCK_TOKEN="your_motherduck_token"
export JINA_API_KEY="your_jina_api_key"
```

### Production with S3 storage

```yaml
server:
  auth:
    provider: github
    client_id_env: GITHUB_CLIENT_ID
    client_secret_env: GITHUB_CLIENT_SECRET

storage:
  backend: duckdb
  database_path: s3://my-bucket/distillery/distillery.db
  s3_region: us-east-1
```

S3 credentials are resolved from AWS environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) or IAM roles.

## Scaling and High Availability

### Current limitations

- Distillery HTTP server runs as a single-worker process (stateless)
- Suitable for teams up to ~100 active users per instance
- All storage operations delegate to the backend (MotherDuck or S3), which scales independently

### Multi-instance deployment (future)

For larger teams, deploy multiple Distillery instances behind a load balancer, all pointing to the same MotherDuck or S3 backend. This is supported architecturally but requires operational setup (reverse proxy, SSL termination).

### Load balancer configuration

```
                  Internet
                     |
              Load Balancer (SSL)
             /        |        \
         HTTP      HTTP      HTTP
         (8000)   (8000)    (8000)
           |        |         |
      Distillery  Distillery  Distillery
      (instance)  (instance)  (instance)
           |        |         |
          \_________MotherDuck DB_________/
```

## Monitoring and Troubleshooting

### Check server status

```bash
curl -I https://distillery.myteam.com/mcp
```

Expected: HTTP 200, 401, or 405 (401 is normal on auth-enabled deployments)

### Check authentication

```bash
# This requires valid GitHub OAuth token
# Team members should run this from their local Claude Code setup
/recall test
```

### View server logs

Most deployment platforms log to stdout. Check your platform's logs:
- Docker: `docker logs <container-id>`
- Kubernetes: `kubectl logs <pod-name>`
- Systemd: `journalctl -u distillery-mcp`

### Common startup errors

**Error: "GITHUB_CLIENT_ID environment variable not set"**
- Cause: GitHub OAuth credentials not configured
- Fix: Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` environment variables

**Error: "MotherDuck backend requires database_path to start with 'md:'"**
- Cause: Storage config mismatch
- Fix: Ensure `storage.database_path` is `md:distillery` (or similar), not a local path

**Error: "MotherDuck token environment variable MOTHERDUCK_TOKEN is not set"**
- Cause: MotherDuck token not configured
- Fix: Set the `MOTHERDUCK_TOKEN` environment variable

**Error: "Server failed to start on port 8000"**
- Cause: Port already in use or permission denied
- Fix: Use a different port with `--port 9000` or check what's using the port with `lsof -i :8000` (macOS/Linux)

## Security Checklist

- [ ] HTTPS is enabled (required for OAuth)
- [ ] GitHub OAuth App credentials are stored securely (not in code or config files)
- [ ] MotherDuck token is stored securely
- [ ] Server is behind a firewall (not directly exposed to the internet)
- [ ] Logs do not contain sensitive data
- [ ] Team members use strong GitHub accounts with 2FA enabled
- [ ] OAuth callback URL in GitHub App matches deployment URL exactly

## Next Steps: Horizon Deployment (Future)

Prefect Horizon is a managed hosting platform optimized for Distillery deployments. Configuration and deployment instructions will be added in a follow-up spec.

For now, deploy to your preferred platform:
- Docker/Container Registry
- Kubernetes
- AWS/GCP/Azure cloud service
- PaaS platform (Heroku, Railway, Fly.io, etc.)
- Traditional VPS

## Questions or Issues?

- **Team members**: See `docs/team-setup.md` for connection and troubleshooting
- **Operators**: Check the deployment scenario section for your use case
- **Contributors**: See the spec in `docs/specs/10-spec-github-team-oauth/` for design rationale
