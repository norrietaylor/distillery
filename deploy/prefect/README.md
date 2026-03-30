# Prefect Horizon Deployment

Deploy the Distillery MCP server to [Prefect Horizon](https://www.prefect.io/horizon), a managed MCP hosting platform purpose-built for FastMCP servers.

## Prerequisites

- A [Horizon](https://horizon.prefect.io) account (sign in with GitHub)
- Horizon granted access to the `norrietaylor/distillery` repository
- [Prefect CLI](https://docs.prefect.io/v3/get-started/install) installed: `pip install prefect`

## Configuration

This directory contains:

| File | Purpose |
|------|---------|
| `prefect.yaml` | Horizon deployment manifest |
| `distillery.yaml` | Production config (MotherDuck storage, GitHub OAuth) |

## Quick Start

### 1. Register a GitHub OAuth App

See [docs/deployment.md](../../docs/deployment.md) for detailed OAuth setup instructions.

### 2. Add secrets in the Horizon dashboard

| Secret | Purpose |
|--------|---------|
| `JINA_API_KEY` | Jina embedding API key |
| `GITHUB_CLIENT_ID` | GitHub OAuth app client ID |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth app client secret |
| `MOTHERDUCK_TOKEN` | MotherDuck cloud DuckDB token |
| `DISTILLERY_BASE_URL` | Public server URL for OAuth callbacks |
| `DISTILLERY_CONFIG` | Path to config file (set to the path where Horizon places `distillery.yaml`) |

### 3. Deploy

From the **repository root**:

```bash
prefect deploy -f deploy/prefect/prefect.yaml
```

A live endpoint is available in ~60 seconds.

## Architecture

- **Transport**: Streamable HTTP (FastMCP)
- **Storage**: MotherDuck (cloud DuckDB) for shared multi-replica access
- **Auth**: GitHub OAuth via FastMCP's `GitHubProvider`, plus Horizon Gateway RBAC
- **Scaling**: Stateless HTTP mode enables horizontal scaling across replicas
