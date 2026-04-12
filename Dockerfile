# syntax=docker/dockerfile:1.7

# ──────────────────────────────────────────────────────────────────────
# Stage 1: build the Svelte dashboard
#
# The Distillery MCP server exposes the dashboard as a ui:// resource
# (src/distillery/mcp/resources.py) that inlines dashboard/dist/index.html
# at read time. Without this stage, the final image ships without
# dashboard/dist/, the resource falls through to a stub HTML page, and
# the Explore tab never renders. We build the dashboard in an isolated
# Node stage and copy only the dist/ output into the Python runtime,
# keeping the final image free of Node, npm, and the ~200 MB of
# node_modules.
# ──────────────────────────────────────────────────────────────────────
FROM node:22-alpine AS dashboard-builder

WORKDIR /build

# Leverage Docker layer caching: copy package manifests first, install,
# then copy sources. Changes to dashboard sources will reuse the
# npm ci layer as long as package.json and package-lock.json don't change.
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY dashboard/ ./
RUN npm run build

# Sanity check: fail the build here (not silently at runtime with a
# fallback HTML stub) if Vite didn't produce the expected entry point.
RUN test -f /build/dist/index.html || (echo "Dashboard build did not produce dist/index.html" && exit 1)

# ──────────────────────────────────────────────────────────────────────
# Stage 2: Python runtime
# ──────────────────────────────────────────────────────────────────────
FROM cgr.dev/chainguard/wolfi-base:latest

WORKDIR /app

ARG BUILD_SHA=unknown
ENV DISTILLERY_BUILD_SHA=${BUILD_SHA}

# Install Python 3.13
RUN apk add --no-cache python-3.13

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /usr/local/bin/uv

# Create non-root user
RUN adduser --disabled-password --uid 10001 appuser

# Copy the full repo (build context is repo root)
COPY . .

# Replace any locally-committed dashboard/dist/ with the freshly built
# artifacts from stage 1. This makes the image build reproducible
# regardless of whether a developer committed stale dist output.
RUN rm -rf /app/dashboard/dist
COPY --from=dashboard-builder /build/dist/ /app/dashboard/dist/

# Point the dashboard resource loader at the in-container path.
#
# src/distillery/mcp/resources.py::_DEFAULT_DIST_DIR walks
# Path(__file__).resolve().parents[3] / "dashboard" / "dist" to find
# the Svelte build output. In a source checkout that resolves to
# <repo>/dashboard/dist; in an installed package (like this image,
# where uv pip install drops the code into /usr/lib/python3.13/
# site-packages/distillery/...) it resolves to
# /usr/lib/python3.13/dashboard/dist, which doesn't exist — and the
# resource handler silently falls back to a stub HTML page.
#
# _find_dist_dir() checks DISTILLERY_DASHBOARD_DIR first, so setting
# the env var here bypasses the broken ancestor walk without
# requiring a code change in resources.py. The underlying packaging
# bug in resources.py should be fixed separately (ideally by
# bundling dashboard/dist/ as Python package data so importlib.
# resources can find it without filesystem walking).
ENV DISTILLERY_DASHBOARD_DIR=/app/dashboard/dist

# Install the package (production only, no dev deps)
RUN uv pip install --system --no-cache .

# Pre-install the DuckDB VSS extension so HNSW indexing is available at runtime
# without a network download. Run as appuser so it lands in ~/.duckdb/extensions/.
RUN su -s /bin/sh appuser -c "python -c \"import duckdb; duckdb.connect(':memory:').execute('INSTALL vss')\""

RUN chown -R appuser:appuser /app

USER appuser
EXPOSE 8000

# Default: HTTP transport on port 8000.
# Configure via environment variables:
#   DISTILLERY_CONFIG  — path to distillery.yaml (default: ./distillery.yaml)
#   DISTILLERY_HOST    — bind address (default: 0.0.0.0)
#   DISTILLERY_PORT    — bind port (default: 8000)
#   GITHUB_CLIENT_ID   — GitHub OAuth client ID (optional, enables auth)
#   GITHUB_CLIENT_SECRET — GitHub OAuth client secret (optional)
#   DISTILLERY_BASE_URL — public URL for OAuth callbacks (required if auth enabled)
#   JINA_API_KEY       — Jina embedding API key
CMD ["distillery-mcp", "--transport", "http"]
