# 11-spec-fly-deployment

## Introduction/Overview

Add Fly.io as a deployment target for the Distillery MCP server and reorganize the repository so deployment configurations live under a `deploy/` directory with one subdirectory per provider. The root directory should contain only what is needed for local development and testing. Fly.io provides persistent NVMe volumes (ideal for DuckDB), scale-to-zero billing, and public HTTPS endpoints — making it a cost-effective self-hosted alternative to Prefect Horizon.

## Goals

1. Create a working Fly.io deployment (Dockerfile, fly.toml, config) that runs the Distillery MCP server with persistent DuckDB storage on a Fly Volume and GitHub OAuth authentication.
2. Reorganize deployment files into `deploy/<provider>/` directories, removing deployment-specific configs from the repo root.
3. Provide per-provider README quickstart guides so a new user can deploy in under 10 minutes.
4. Ensure no breaking changes to local development workflow, CI, or the existing Prefect Horizon deployment.

## User Stories

- As a developer, I want to deploy Distillery to Fly.io so that I have a persistent, low-cost MCP server with DuckDB storage that survives restarts.
- As a contributor, I want deployment configs separated from development files so the repo root is clean and focused on local dev.
- As an operator, I want per-provider deployment docs so I can follow a quickstart without reading unrelated provider instructions.

## Demoable Units of Work

### Unit 1: Reorganize deployment files into `deploy/` directory

**Purpose:** Move existing Prefect Horizon deployment files out of the repo root into `deploy/prefect/`, establishing the `deploy/<provider>/` convention. Root retains only dev-focused files.

**Functional Requirements:**
- The system shall have `deploy/prefect/prefect.yaml` (moved from root via `git mv`)
- The system shall have `deploy/prefect/distillery.yaml` (moved from root via `git mv`, this is the MotherDuck + GitHub OAuth production config)
- The system shall have `deploy/prefect/README.md` with Prefect Horizon quickstart instructions extracted/adapted from the existing comments in `prefect.yaml`
- The `deploy/prefect/prefect.yaml` comments shall be updated to reference `prefect deploy -f deploy/prefect/prefect.yaml` instead of running from repo root
- The `distillery-dev.yaml` cross-reference comment (line 7) shall be updated from "use distillery.yaml" to reference `deploy/prefect/distillery.yaml` and `deploy/fly/distillery-fly.yaml`
- The `CLAUDE.md` Architecture section shall gain a Deployment subsection documenting the `deploy/` structure
- The `docs/deployment.md` shall be updated to reference new file locations
- No changes to `src/distillery/` — config resolution via `DISTILLERY_CONFIG` env var already supports arbitrary paths

**Proof Artifacts:**
- CLI: `ls deploy/prefect/` shows `prefect.yaml`, `distillery.yaml`, `README.md`
- CLI: `ls distillery.yaml 2>&1` returns "No such file" (removed from root)
- CLI: `git log --follow deploy/prefect/prefect.yaml` shows history preserved
- Test: `pytest` passes (no test changes expected)

### Unit 2: Create Fly.io deployment configuration

**Purpose:** Add all files needed to deploy Distillery to Fly.io with persistent DuckDB storage on a volume, GitHub OAuth, and scale-to-zero.

**Functional Requirements:**
- The system shall have `deploy/fly/Dockerfile` using `python:3.13-slim`, installing the package via `pip install --no-cache-dir .`, exposing port 8000, with entrypoint `distillery-mcp --transport http`
- The Dockerfile build context shall be the repo root (COPY . .) so that `fly deploy -c deploy/fly/fly.toml` works from the repo root
- The system shall have `deploy/fly/fly.toml` configuring: build with `dockerfile = "deploy/fly/Dockerfile"`, HTTP service on internal port 8000 with force_https, scale-to-zero (`auto_stop_machines = "stop"`, `auto_start_machines = true`, `min_machines_running = 0`), a volume mount (`source = "distillery_data"`, `destination = "/data"`), and a health check on `/mcp`
- The `fly.toml` shall not hardcode a region (user picks on first deploy)
- The system shall have `deploy/fly/distillery-fly.yaml` with: `storage.backend = duckdb`, `storage.database_path = /data/distillery.db`, `embedding.provider = jina` (1024 dims, `JINA_API_KEY`), `server.auth.provider = github` with `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` env var references
- The `fly.toml` `[env]` section shall set `DISTILLERY_CONFIG = "/app/distillery-fly.yaml"`
- The Dockerfile shall copy `deploy/fly/distillery-fly.yaml` to `/app/distillery-fly.yaml`
- The system shall have `deploy/fly/README.md` with quickstart: prerequisites, `fly apps create`, `fly volumes create distillery_data --size 1`, `fly secrets set JINA_API_KEY=... GITHUB_CLIENT_ID=... GITHUB_CLIENT_SECRET=... DISTILLERY_BASE_URL=...`, `fly deploy -c deploy/fly/fly.toml`, verification steps

**Proof Artifacts:**
- File: `deploy/fly/Dockerfile` exists and passes `docker build -f deploy/fly/Dockerfile .` from repo root
- File: `deploy/fly/fly.toml` exists with correct mount, service, and build config
- File: `deploy/fly/distillery-fly.yaml` is valid YAML loadable by `load_config()`
- Test: `python -c "from distillery.config import load_config; import os; os.environ['DISTILLERY_CONFIG']='deploy/fly/distillery-fly.yaml'; load_config()"` succeeds (with auth validation skipped since no GitHub secrets present locally)
- CLI: `deploy/fly/README.md` contains all required `fly` CLI commands

### Unit 3: Update documentation and cross-references

**Purpose:** Ensure all docs, guides, and repo metadata reflect the new directory structure so nothing points at stale paths.

**Functional Requirements:**
- `CLAUDE.md` shall include a Deployment subsection after Architecture explaining the `deploy/` structure and that local dev uses `distillery-dev.yaml` at root
- `docs/deployment.md` shall reference `deploy/prefect/` for Horizon deployments and `deploy/fly/` for Fly.io deployments
- `distillery-dev.yaml` line 7 comment shall reference both `deploy/prefect/distillery.yaml` and `deploy/fly/distillery-fly.yaml`
- `distillery.yaml.example` header comment shall note that production configs live under `deploy/`
- No links or references in the codebase shall point to the old root-level `prefect.yaml` or `distillery.yaml` paths

**Proof Artifacts:**
- CLI: `grep -r 'prefect\.yaml' --include='*.md' --include='*.py' .` returns zero hits outside `deploy/prefect/`
- CLI: `grep -rn 'distillery\.yaml' --include='*.md' . | grep -v deploy/ | grep -v dev | grep -v example | grep -v specs/` returns only appropriate references (dev config, example template)
- Test: `pytest` passes
- Test: `ruff check src/ tests/` passes
- Test: `mypy --strict src/` passes

## Non-Goals (Out of Scope)

- Implementing bearer token authentication (Horizon/Fly use OAuth or no-auth)
- Adding a CI/CD pipeline for automated Fly.io deployments (manual `fly deploy` for now)
- MotherDuck or S3 storage backend for Fly.io (uses local DuckDB on volume)
- Multi-region or multi-machine Fly.io deployment
- Automated backup/export of the Fly volume DuckDB database
- Changes to any application code in `src/distillery/`

## Design Considerations

No UI/UX requirements. This is infrastructure and documentation only.

## Repository Standards

- **Commit format**: Conventional Commits — `type(scope): description`
  - Likely scopes: `chore` (file moves), `feat` (Fly deployment), `docs` (updates)
- **Python**: 3.11+ required, 3.13 preferred for Dockerfile
- **Linting**: `ruff check`, `mypy --strict` on `src/`
- **Testing**: `pytest` with existing fixtures, no new tests expected (no `src/` changes)

## Technical Considerations

- **Config resolution**: `src/distillery/config.py` resolves config via (1) explicit arg, (2) `DISTILLERY_CONFIG` env var, (3) `distillery.yaml` in cwd. Moving production configs to `deploy/` means all deployments must set `DISTILLERY_CONFIG`. Prefect already does this via secrets. Fly.io will do it via `[env]` in `fly.toml`.
- **Prefect deploy command**: After moving `prefect.yaml`, operators must use `prefect deploy -f deploy/prefect/prefect.yaml` from repo root. The build step `pip install -e .` resolves relative to the repo root when run this way.
- **Fly build context**: `fly deploy -c deploy/fly/fly.toml` uses repo root as build context. The Dockerfile COPY paths are relative to this context.
- **Health check**: FastMCP's `/mcp` endpoint returns 405 on GET. Fly health checks accept 2xx-4xx as healthy by default, so this works.
- **Scale-to-zero + volumes**: Fly Volumes persist while the Machine is stopped. Data survives stop/start cycles.

## Security Considerations

- GitHub OAuth secrets (`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`) must be set via `fly secrets set`, not in `fly.toml` or committed files
- `JINA_API_KEY` must be set via `fly secrets set`
- `DISTILLERY_BASE_URL` set via `fly secrets set` (contains the public Fly URL for OAuth callbacks)
- The `distillery-fly.yaml` config file references env var *names* only, never actual secret values
- The Dockerfile should include a `.dockerignore` or the existing `.gitignore` patterns should exclude `.env`, credentials, and local databases

## Success Metrics

- `fly deploy -c deploy/fly/fly.toml` from repo root produces a running Distillery MCP server accessible at `https://<app>.fly.dev/mcp`
- DuckDB data persists across deploys and machine restarts (volume-backed)
- GitHub OAuth flow works end-to-end from a Claude Code client
- All existing tests, linting, and type checking pass without modification
- Repo root contains zero deployment-specific config files (only `distillery-dev.yaml` and `distillery.yaml.example` remain)

## Open Questions

- Should we add a `.dockerignore` file at repo root to exclude tests, docs, .git, etc. from the Docker build context? (Reduces image size but not blocking.)
