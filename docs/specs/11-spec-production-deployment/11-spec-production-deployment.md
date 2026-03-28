# 11-spec-production-deployment

## Introduction/Overview

This spec establishes production deployment infrastructure for the Distillery MCP server on AWS. The hosted server at `able-red-cougar.fastmcp.app` is broken (MotherDuck lacks VSS support, Lambda cold starts timeout at 180s), and there is no deployment pipeline. This spec replaces FastMCP Cloud with a self-hosted AWS Lambda behind a configurable HTTPS endpoint (Lambda Function URL or API Gateway), backed by S3 storage, with Terraform IaC and GitHub Actions CD that deploys on merge to `main`.

**Epic:** [#41](https://github.com/norrietaylor/distillery/issues/41)

## Goals

1. Provision production AWS infrastructure via Terraform (Lambda, S3 bucket, ECR, IAM, secrets)
2. Deploy the MCP server as a Docker container on Lambda with provisioned concurrency
3. Automate deployment via GitHub Actions — merge to `main` triggers build, deploy, smoke test
4. Make DuckDBStore resilient to missing VSS extension (graceful degradation, not crash)
5. Add a health check endpoint and connection retry logic for production reliability
6. Configurable HTTPS endpoint: Lambda Function URL (simple) or API Gateway + custom domain (production)

## User Stories

- As an **operator**, I want to run `terraform apply` and have all AWS infrastructure provisioned so that I don't manually configure resources.
- As an **operator**, I want deployment to happen automatically when I merge to `main` so that the hosted server is always up-to-date.
- As a **team member**, I want the hosted server to respond to all 21 MCP tools with GitHub OAuth so that I can access shared knowledge remotely.
- As a **contributor**, I want a smoke test to run after each deployment so that I know the server is healthy before users hit it.
- As an **operator**, I want DuckDB to start even when VSS is unavailable so that basic CRUD operations work while I debug extension issues.
- As an **operator**, I want to choose between a simple Function URL and a full API Gateway setup via a Terraform variable so that I can start simple and upgrade later.

## Demoable Units of Work

### Unit 1: Application Resilience

**Purpose:** Make DuckDBStore resilient to missing VSS extension and transient connection failures so the server starts reliably in any environment.

**Functional Requirements:**

- `DuckDBStore._setup_vss()` shall wrap VSS installation (`INSTALL vss`, `LOAD vss`) in a try-except block. On failure, log a warning with the exception message and set an instance flag `self._vss_available = False`. Do not crash.
- When `self._vss_available is False`, `DuckDBStore._create_index()` shall skip HNSW index creation and log a warning: "VSS extension unavailable — HNSW index not created, falling back to brute-force search"
- `DuckDBStore.search()` and `DuckDBStore.find_similar()` shall work without HNSW indexes by using brute-force cosine similarity (DuckDB's `list_cosine_similarity` function). The existing SQL already uses this as a fallback when no index exists.
- `DuckDBStore._sync_initialize()` shall retry the full initialization sequence (connection + schema + index) up to 3 times with exponential backoff (1s, 2s, 4s) on transient errors (`duckdb.IOException`, `duckdb.ConnectionException`, `duckdb.HTTPException`). The existing write-write conflict retry (100ms, 200ms) remains as an inner loop.
- The MCP server shall expose a `/health` endpoint that returns JSON `{"status": "ok", "vss_available": true|false, "store_initialized": true|false, "database_path": "..."}` without requiring authentication
- `create_server()` in `server.py` shall register the health endpoint via FastMCP's route mechanism or as a Starlette route on the underlying ASGI app
- All new code shall pass `mypy --strict` and `ruff check`

**Proof Artifacts:**

- Test: `tests/test_duckdb_store.py::test_vss_unavailable_graceful_degradation` — mock `INSTALL vss` to raise, verify store initializes with `_vss_available = False`
- Test: `tests/test_duckdb_store.py::test_search_without_hnsw_index` — store and search entries without VSS, verify results returned via brute-force
- Test: `tests/test_duckdb_store.py::test_connection_retry_on_transient_error` — mock connection failure on first attempt, verify retry succeeds
- Test: `tests/test_mcp_http_transport.py::test_health_endpoint` — HTTP GET `/health` returns 200 with expected JSON fields
- CLI: `distillery-mcp --transport http` starts successfully when VSS extension is not loadable

### Unit 2: AWS Infrastructure (Terraform)

**Purpose:** Provision all AWS resources needed to run the Distillery MCP server via Terraform, with a configurable HTTPS endpoint.

**Functional Requirements:**

- A `terraform/` directory at the repository root shall contain all Terraform configuration
- `terraform/main.tf` shall define:
  - AWS provider with configurable region (variable `aws_region`, default `us-east-1`)
  - S3 bucket for DuckDB storage with versioning enabled, server-side encryption (AES-256), and a lifecycle rule to expire old versions after 30 days
  - ECR repository for the Docker container image
  - Lambda function configured with:
    - Container image from ECR
    - Memory: 2048 MB (configurable via variable)
    - Timeout: 300 seconds (configurable via variable)
    - Provisioned concurrency: 1 (configurable via variable, 0 to disable)
    - Environment variables sourced from AWS Secrets Manager
  - IAM execution role for Lambda with policies for S3 read/write, Secrets Manager read, ECR pull, CloudWatch Logs write
  - AWS Secrets Manager secret for application secrets (`JINA_API_KEY`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `DISTILLERY_BASE_URL`)
- `terraform/variables.tf` shall define all configurable inputs with sensible defaults and descriptions
- `terraform/outputs.tf` shall output the endpoint URL, S3 bucket name, ECR repository URL, and Lambda function name
- `terraform/endpoint.tf` shall define the HTTPS endpoint, controlled by a variable `endpoint_type`:
  - `"function_url"` (default): Lambda Function URL with `AUTH_TYPE = NONE` (auth handled by application-level GitHub OAuth)
  - `"api_gateway"`: API Gateway v2 (HTTP API) with a custom domain name (variable `custom_domain`), ACM certificate, and Route53 record
- `terraform/backend.tf` shall configure remote state in S3 with DynamoDB locking (bucket and table names as variables, allowing bootstrap)
- `terraform/versions.tf` shall pin the AWS provider to `~> 5.0` and Terraform to `>= 1.5`
- A `terraform/bootstrap/` subdirectory shall contain a minimal Terraform config to create the state bucket and DynamoDB lock table (one-time setup)
- All Terraform files shall pass `terraform validate` and `terraform fmt -check`

**Proof Artifacts:**

- CLI: `cd terraform && terraform validate` succeeds
- CLI: `cd terraform && terraform fmt -check` passes (no formatting issues)
- CLI: `cd terraform && terraform plan -var="endpoint_type=function_url"` produces a valid plan
- CLI: `cd terraform && terraform plan -var="endpoint_type=api_gateway" -var="custom_domain=distillery.example.com"` produces a valid plan
- File: `terraform/outputs.tf` contains `endpoint_url`, `s3_bucket_name`, `ecr_repository_url`, `lambda_function_name`

### Unit 3: Docker Container & ECR

**Purpose:** Package the Distillery MCP server as a Docker container image that runs on AWS Lambda.

**Functional Requirements:**

- `Dockerfile` at the repository root shall:
  - Use `public.ecr.aws/lambda/python:3.12` as the base image
  - Install the distillery package and all dependencies (including `duckdb`, `fastmcp>=2.12.0`)
  - Set the Lambda handler to a new `src/distillery/mcp/lambda_handler.py` module
  - Include a `distillery.yaml` configured for S3 storage and GitHub OAuth (with env var references, not secrets)
- `src/distillery/mcp/lambda_handler.py` shall:
  - Provide a Lambda-compatible handler function that wraps the FastMCP ASGI app
  - Use `mangum` (or equivalent ASGI-to-Lambda adapter) to translate API Gateway / Function URL events to ASGI
  - Configure the server with `--transport http` equivalent settings (streamable-HTTP, stateless, auth from config)
- The container image shall be buildable with `docker build -t distillery-mcp .` and runnable locally with `docker run -p 8000:8080 distillery-mcp`
- `distillery.yaml` in the container shall use environment variable references for all secrets (no hardcoded values)

**Proof Artifacts:**

- CLI: `docker build -t distillery-mcp .` succeeds
- CLI: `docker run --rm -e JINA_API_KEY=test -e AWS_ACCESS_KEY_ID=test -e AWS_SECRET_ACCESS_KEY=test distillery-mcp` starts without error (may fail on S3 connection, but Lambda handler initializes)
- File: `Dockerfile` exists at repository root
- File: `src/distillery/mcp/lambda_handler.py` exists with handler function
- Test: `tests/test_lambda_handler.py::test_handler_returns_response` — invoke handler with mock API Gateway event, verify HTTP response

### Unit 4: GitHub Actions CD Pipeline

**Purpose:** Automate deployment so that merging to `main` builds, deploys, and smoke-tests the production server.

**Functional Requirements:**

- `.github/workflows/deploy.yml` shall trigger on push to `main` (after CI passes)
- The workflow shall:
  1. Run the full test suite (`pytest --cov-fail-under=80`) — fail deployment if tests fail
  2. Build the Docker container image
  3. Push the image to ECR (authenticate via OIDC or stored AWS credentials)
  4. Update the Lambda function to use the new image
  5. Wait for Lambda to stabilize (provisioned concurrency warm)
  6. Run a smoke test against the live endpoint:
     - `POST /health` returns `{"status": "ok"}`
     - MCP `initialize` handshake succeeds
     - `tools/list` returns 21 tools
  7. On failure: send notification (GitHub Actions summary + optional Slack/email)
- The workflow shall use GitHub Actions OIDC for AWS authentication (no long-lived access keys stored in GitHub Secrets)
- AWS account ID, region, ECR repo, and Lambda function name shall be configurable via GitHub Actions variables (not hardcoded)
- The workflow shall reuse the existing `ci.yml` test step (not duplicate it) — use `workflow_run` trigger or job dependency
- Terraform state shall NOT be applied by the CD pipeline (infrastructure changes are manual `terraform apply` — the CD pipeline only updates the Lambda container image)

**Proof Artifacts:**

- File: `.github/workflows/deploy.yml` exists with correct trigger and steps
- File: `.github/workflows/deploy.yml` contains smoke test step
- CLI: `act -n` (or equivalent) validates the workflow syntax
- Test: Manual trigger of the workflow (after Terraform provisions infrastructure) deploys successfully

### Unit 5: End-to-End Validation

**Purpose:** Verify the complete production deployment works: infrastructure provisioned, server deployed, OAuth flow complete, all tools accessible.

**Functional Requirements:**

- A `scripts/smoke-test.sh` shall:
  - Accept the endpoint URL as an argument
  - Check `/health` returns `{"status": "ok"}`
  - Perform MCP `initialize` handshake (unauthenticated, expect 401 if auth is enabled or 200 if not)
  - If auth is enabled: perform OAuth DCR, generate auth URL, print instructions for manual token exchange
  - If auth is not enabled: call `tools/list` and verify 21 tools, call `distillery_status`
- The smoke test shall be usable both in CI (with a pre-configured token) and locally (interactive)
- Documentation in `docs/deployment.md` shall be updated with:
  - AWS deployment section (Terraform bootstrap, apply, verify)
  - CD pipeline section (how it works, how to monitor)
  - Troubleshooting section for common Lambda/S3 issues

**Proof Artifacts:**

- CLI: `./scripts/smoke-test.sh https://<endpoint-url>` returns success
- File: `scripts/smoke-test.sh` exists and is executable
- File: `docs/deployment.md` updated with AWS deployment and CD pipeline sections

## Non-Goals (Out of Scope)

- Staging environment — production only for now; staging can be added by duplicating Terraform with different variable values
- Multi-region deployment — single region is sufficient for small teams
- Custom domain and DNS — configurable in Terraform but not provisioned in this spec's validation (requires domain ownership)
- WAF or DDoS protection — defer to API Gateway or CloudFront in a future spec
- Decommissioning FastMCP Cloud (`able-red-cougar.fastmcp.app`) — can coexist; removal is a manual step
- Lambda@Edge or CloudFront distribution — not needed for MCP server
- Auto-scaling beyond provisioned concurrency — one warm instance is sufficient for small teams
- Monitoring dashboards (CloudWatch, Grafana) — the health endpoint and smoke test provide basic observability; dashboards are a follow-up

## Design Considerations

### Endpoint configurability

Terraform variable `endpoint_type` controls the HTTPS endpoint:
- `"function_url"` (default): Simplest path. Lambda Function URL provides a permanent HTTPS URL with no additional resources. Auth is handled at the application layer by FastMCP's GitHubProvider.
- `"api_gateway"`: API Gateway v2 HTTP API with optional custom domain. Adds throttling, request validation, and custom domain support. Requires ACM certificate and Route53 hosted zone.

Both options pass requests to the same Lambda function running `distillery-mcp --transport http`.

### Terraform state bootstrap

Chicken-and-egg problem: Terraform needs an S3 bucket for remote state, but we use Terraform to create S3 buckets. Solution: `terraform/bootstrap/` contains a minimal config that creates the state bucket and DynamoDB lock table using local state. Run once, then configure `backend.tf` to use the created bucket.

### Docker container on Lambda

Lambda supports container images up to 10 GB. The Distillery image includes Python 3.12, DuckDB (with native extensions), FastMCP, and all dependencies. The `public.ecr.aws/lambda/python:3.12` base image includes the Lambda Runtime Interface Client (RIC). The handler uses `mangum` to adapt ASGI (FastMCP/Starlette) to Lambda's event format.

### VSS graceful degradation

The `_vss_available` flag is checked at index creation time and at search time. When VSS is unavailable:
- Index creation is skipped (no HNSW)
- Search uses DuckDB's built-in `list_cosine_similarity()` for brute-force comparison
- Performance degrades at scale (~10K+ entries) but is functionally correct
- The `/health` endpoint reports `"vss_available": false` so operators can diagnose

## Repository Standards

- Conventional Commits: `feat(store):`, `feat(mcp):`, `chore(infra):`, `ci:`, `docs:`
- Scopes: `store`, `mcp`, `infra`, `ci`
- mypy strict for `src/`, relaxed for `tests/`
- ruff with existing rule set (line length 100, E501 ignored)
- Terraform: `terraform fmt`, `terraform validate`
- Docker: multi-stage builds where beneficial, `.dockerignore` for build context
- CI matrix: Python 3.11, 3.12, 3.13 (existing `ci.yml` unchanged)

## Technical Considerations

- **Lambda memory**: DuckDB + VSS requires ~512 MB minimum. 2048 MB recommended for headroom with S3 I/O and embedding API calls. Configurable via Terraform variable.
- **Lambda timeout**: 300 seconds (5 minutes) to handle cold starts with S3-backed DuckDB initialization. Provisioned concurrency eliminates this for steady-state traffic.
- **S3 DuckDB behavior**: DuckDB with `httpfs` reads the full database file into `/tmp` on first access. File size directly impacts cold start time. For small teams (<10K entries), the database file is typically <100 MB.
- **`mangum` adapter**: Translates API Gateway / Function URL HTTP events to ASGI. Handles streaming responses which FastMCP's streamable-HTTP transport requires. Verify SSE compatibility.
- **OIDC for CI**: GitHub Actions OIDC eliminates stored AWS access keys. The Terraform IAM config creates a role that trusts the GitHub OIDC provider for the specific repository.
- **Secrets rotation**: Secrets Manager supports automatic rotation. Not implemented in this spec but the infrastructure supports it.

## Security Considerations

- No AWS access keys stored in GitHub Secrets — OIDC federation only
- Application secrets (API keys, OAuth credentials) stored in AWS Secrets Manager, injected as Lambda environment variables
- S3 bucket has server-side encryption (AES-256) and versioning enabled
- Lambda execution role follows least-privilege: S3 read/write to specific bucket, Secrets Manager read for specific secret, CloudWatch Logs write
- GitHub OAuth credentials never appear in Terraform state (they're in Secrets Manager, referenced by ARN)
- `.dockerignore` excludes `.env`, credentials, and test files from the container image
- ECR repository has image scanning enabled

## Success Metrics

- `terraform apply` provisions all resources in < 5 minutes
- Merge to `main` deploys to production in < 10 minutes (build + push + deploy + smoke test)
- Cold start with provisioned concurrency: first request completes in < 10 seconds
- All 21 MCP tools accessible over HTTPS with GitHub OAuth
- `/health` endpoint responds in < 1 second
- Smoke test passes: initialize + tools/list + distillery_status
- Existing test suite (1000+ tests) passes at 80%+ coverage with new resilience code

## Open Questions

1. **mangum SSE compatibility** — Does `mangum` correctly handle Server-Sent Events (SSE) streaming responses from FastMCP's streamable-HTTP transport? Lambda Function URLs support response streaming, but API Gateway may buffer. Needs verification during implementation.
2. **DuckDB S3 file locking** — With provisioned concurrency = 1, there's only one Lambda instance. If scaled to >1, concurrent DuckDB writes to the same S3 file will conflict. Document this limitation for now; address in a future multi-instance spec.
