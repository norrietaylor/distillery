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

**server**
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
     (these are the default env var names; customize them via `client_id_env` and
     `client_secret_env` in `distillery.yaml`)
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

```text
distillery-mcp --help

Usage: distillery-mcp [OPTIONS]

Options:
  --transport {stdio|http}  Transport mode (default: stdio)
  --host HOST              Bind address (default: 0.0.0.0, env: DISTILLERY_HOST)
  --port PORT              Bind port (default: 8000, env: DISTILLERY_PORT)
  --help                   Show this help message
```

### Verifying startup

The server logs to stderr via Python logging. On startup you will reliably see database initialization and embedding provider details. Transport and auth configuration are not currently emitted as structured log lines — verify those by checking the config file and testing connectivity (see Step 5).

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
distillery-mcp --transport http --host 127.0.0.1 --port 8000
```

Warning: This mode allows unauthenticated access. Binding to `127.0.0.1` ensures
the server is only reachable from localhost. Use only for local development.

### Production with S3 storage (recommended for hosted deployments)

S3-backed DuckDB is the recommended storage backend for hosted deployments (FastMCP Cloud,
containers, PaaS). It uses standard DuckDB with the `httpfs` extension, so the VSS extension
and HNSW vector indexes work normally. The database file persists on S3 across container
restarts and cold starts.

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

Set environment variables:
```bash
export GITHUB_CLIENT_ID="github_oauth_client_id"
export GITHUB_CLIENT_SECRET="github_oauth_client_secret"
export DISTILLERY_BASE_URL="https://distillery.myteam.com"
export AWS_ACCESS_KEY_ID="your_aws_access_key"
export AWS_SECRET_ACCESS_KEY="your_aws_secret_key"
export JINA_API_KEY="your_jina_api_key"
```

S3 credentials can also be resolved from IAM roles when running on AWS infrastructure
(no env vars needed).

GCS is also supported via the S3-compatible API:

```yaml
storage:
  backend: duckdb
  database_path: gs://my-bucket/distillery/distillery.db
  s3_endpoint: https://storage.googleapis.com
```

GCS authentication uses HMAC keys (`GCS_ACCESS_KEY_ID` + `GCS_SECRET`).

### MotherDuck (not recommended for hosted deployments)

> **Known limitation:** MotherDuck does not support the DuckDB VSS extension. HNSW vector
> index creation will fail with `Unknown index type: HNSW`. This means semantic search
> (which relies on vector similarity) will not work on MotherDuck. Use S3-backed DuckDB
> instead for hosted deployments that require search.

MotherDuck can still be used if you do not need vector search (e.g., for simple CRUD
operations with `distillery_store`, `distillery_get`, `distillery_list`):

```yaml
storage:
  backend: motherduck
  database_path: md:distillery
```

```bash
export MOTHERDUCK_TOKEN="your_motherduck_token"
```

## AWS Lambda Deployment

Distillery can be deployed to AWS Lambda for serverless, auto-scaling hosting. This section covers the Terraform-based infrastructure setup and deployment process.

### AWS Infrastructure Setup

The Distillery project includes Terraform configuration in `terraform/` to provision all required AWS resources:

- **S3 Bucket** — Stores the DuckDB database file, with versioning and encryption
- **ECR Repository** — Stores the Distillery Docker container image
- **Lambda Function** — Runs the Distillery MCP server with 2048MB memory, 300s timeout, and provisioned concurrency
- **IAM Role** — Execution role with least-privilege policies for S3 and Secrets Manager access
- **Secrets Manager** — Stores GitHub OAuth credentials and embedding API keys
- **Lambda Function URL** or **API Gateway v2** — HTTPS endpoint for the MCP server (configurable via `endpoint_type` variable)

#### Prerequisites

- AWS account with appropriate permissions
- Terraform installed (1.0+)
- AWS CLI configured with credentials
- GitHub OAuth App credentials (see Step 1 above)

#### Bootstrap (One-Time)

Before applying Terraform, create the state backend infrastructure:

```bash
cd terraform/bootstrap
terraform init
terraform apply
# Output: S3 bucket name and DynamoDB table name for remote state
# Copy these values to terraform/backend.tf
```

Record the S3 bucket and DynamoDB table names, then update `terraform/backend.tf`:

```hcl
terraform {
  backend "s3" {
    bucket         = "distillery-terraform-state-<account-id>"  # From bootstrap
    key            = "distillery.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "distillery-lock"  # From bootstrap
  }
}
```

#### Deploy Infrastructure

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

Terraform will prompt for required variables:
- `github_client_id` — From your GitHub OAuth App
- `github_client_secret` — From your GitHub OAuth App
- `jina_api_key` — Your Jina embeddings API key
- `endpoint_type` — `"lambda-url"` (default) or `"api-gateway"`
- `custom_domain` (optional) — For API Gateway custom domain
- `acm_certificate_arn` (optional) — For API Gateway HTTPS

#### Verify Deployment

After Terraform applies successfully:

```bash
# Get Lambda function URL
aws lambda get-function-url-config \
  --function-name distillery-mcp \
  --region us-east-1 \
  --query 'FunctionUrl' \
  --output text

# Test the endpoint
curl https://<function-url-from-above>/health
```

Expected response: `{"status": "ok"}`

#### Troubleshooting

**Error: "Failed to assume role"**
- Cause: IAM permissions insufficient
- Fix: Ensure your AWS credentials have permissions for Lambda, ECR, S3, Secrets Manager, and IAM

**Error: "S3 bucket already exists"**
- Cause: Bucket name conflict (S3 bucket names are globally unique)
- Fix: Modify the `project_name` and/or `environment` variables in `terraform/variables.tf` (the bucket name is `${project_name}-${environment}-storage`)

### Continuous Deployment Pipeline

The GitHub Actions CD pipeline automatically deploys changes to AWS Lambda whenever code is merged to `main`.

#### How It Works

1. **Trigger** — Runs after CI passes on `main`, or manually via workflow_dispatch
2. **Test** — Re-runs the full test suite to verify the commit
3. **Build** — Builds Docker image and pushes to ECR
4. **Deploy** — Updates Lambda function to the new image
5. **Verify** — Runs smoke tests (/health, MCP initialize, tools/list)

#### Configuration

The pipeline uses GitHub Actions variables (not secrets) for AWS identifiers:

```
AWS_REGION               (default: us-east-1)
AWS_ACCOUNT_ID           (required)
ECR_REPOSITORY           (required)
LAMBDA_FUNCTION_NAME     (required)
ENDPOINT_URL             (required, Lambda Function URL)
```

Set these in your repository settings:
1. Go to Settings → Secrets and variables → Actions
2. Click "New repository variable"
3. Add each variable above

#### Authentication

The pipeline uses GitHub OIDC to authenticate with AWS, avoiding long-lived access keys. The IAM role `distillery-github-actions-deploy` is created by Terraform and trusts the GitHub Actions OIDC provider.

#### Monitoring Deployments

1. **View workflow runs** — Go to Actions tab in GitHub
2. **Check deployment summary** — Each workflow run includes a markdown summary with deployment info
3. **View server logs** — CloudWatch Logs group: `/aws/lambda/distillery-mcp`
4. **Monitor Lambda metrics** — CloudWatch Dashboard auto-created by Terraform

#### Smoke Test Details

The CD pipeline runs three smoke tests after deployment:

1. **GET /health** — Verifies the server is responding and returns `{"status": "ok"}`
2. **POST /mcp (initialize)** — Tests the MCP protocol handshake
3. **POST /mcp (tools/list)** — Verifies exactly 21 tools are available

All tests are also available locally:

```bash
./scripts/smoke-test.sh https://<lambda-url>
```

The script outputs color-coded test results and detailed error messages if any test fails.

#### Rollback Procedures

If a deployment introduces issues:

1. **Revert the commit** that caused the issue:
   ```bash
   git revert <commit-sha>
   git push
   ```
   This will trigger a new deployment with the previous working version.

2. **Manual rollback** (if urgent):
   ```bash
   aws lambda update-function-code \
     --function-name distillery-mcp \
     --image-uri <previous-image-uri>
   ```
   Find the previous image in ECR console.

#### Troubleshooting Deployments

**Smoke test fails with "401 Unauthorized"**
- This indicates the server requires GitHub OAuth, which is expected
- The CD pipeline assumes no auth (or local auth) for testing
- To test auth-enabled deployment, see docs/team-setup.md

**Lambda function times out during update**
- Check CloudWatch Logs for errors
- Verify the Docker image builds successfully locally:
  ```bash
  docker build -t distillery-test .
  docker run -p 8000:8000 distillery-test distillery-mcp --transport http --port 8000
  ```

**ECR push fails with "AccessDenied"**
- Verify the GitHub OIDC role has ECR push permissions
- Check that `ECR_REPOSITORY` variable matches the repository name in AWS

## Scaling and High Availability

### Current limitations

- Distillery HTTP server runs as a single-worker process (stateless)
- Suitable for teams up to ~100 active users per instance
- All storage operations delegate to the backend (S3 or MotherDuck), which scales independently

### Multi-instance deployment (future)

For larger teams, deploy multiple Distillery instances behind a load balancer, all pointing to the same S3 backend. This is supported architecturally but requires operational setup (reverse proxy, SSL termination).

### Load balancer configuration

```text
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
          \_________ S3 DuckDB ________/
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

## Platform-Specific Deployment Guides

Production deployment configs live under `deploy/` in the repository root, with one directory per provider:

### Prefect Horizon (managed hosting)

See [`deploy/prefect/README.md`](../deploy/prefect/README.md) for quickstart instructions. Uses MotherDuck for shared cloud storage and the Horizon Gateway for RBAC.

### Fly.io (self-hosted, persistent volume)

See [`deploy/fly/README.md`](../deploy/fly/README.md) for quickstart instructions. Uses local DuckDB on a persistent NVMe volume with scale-to-zero billing.

### Other platforms

You can also deploy to Docker, Kubernetes, AWS/GCP/Azure, or any PaaS that runs containers. Use `deploy/fly/Dockerfile` as a starting point.

## Questions or Issues?

- **Team members**: See `docs/team-setup.md` for connection and troubleshooting
- **Operators**: Check the deployment scenario section for your use case
- **Contributors**: See the spec in `docs/specs/10-spec-github-team-oauth/` for design rationale
