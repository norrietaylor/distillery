# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the Distillery MCP server.
#
# Stage 1 (builder): Wolfi base + Python 3.14 + the `uv` static binary
# (copied from the official Astral image). Resolves dependencies from
# `uv.lock` and produces a self-contained `/app/.venv`.
#
# Stage 2 (runtime): the same Wolfi + Python 3.14 base — but only the
# prebuilt virtualenv is copied in. No `uv` (~48 MB), no compilers, no
# pip cache, and no source tree shipped to production.

ARG WOLFI_TAG=latest
ARG UV_VERSION=0.11.3

# Pinned `uv` binary. Pulled in via a separate stage so we can parameterise
# the version via the UV_VERSION build arg in the `COPY --from=` below.
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ─────────────────────────────────────────────────────────────────────
# Stage 1: builder — resolve and install dependencies with uv
# ─────────────────────────────────────────────────────────────────────
FROM cgr.dev/chainguard/wolfi-base:${WOLFI_TAG} AS builder

# Python 3.14 + uv. Wolfi's `python-3.14` package ships the interpreter
# only; we layer `uv` on top from the pinned Astral image.
RUN apk add --no-cache python-3.14
COPY --from=uv /uv /usr/local/bin/uv

# Speed/size knobs for uv:
#   - copy link mode avoids hardlink fallbacks across mounted layers
#   - bytecode compile up front so the runtime image has no first-call cost
#   - never download a different Python: use the one provided by the base
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/bin/python3.14 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# 1. Install dependencies first using only lockfile + project metadata.
#    This layer is cached unless dependencies change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# 2. Install the project itself in non-editable mode.
COPY src ./src
COPY README.md ./README.md
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --no-dev

# ─────────────────────────────────────────────────────────────────────
# Stage 2: runtime — Wolfi base + Python only, venv copied from builder
# ─────────────────────────────────────────────────────────────────────
FROM cgr.dev/chainguard/wolfi-base:${WOLFI_TAG} AS runtime

ARG BUILD_SHA=unknown
ENV DISTILLERY_BUILD_SHA=${BUILD_SHA} \
    PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv

# OCI labels (preserve provenance and discoverability).
LABEL org.opencontainers.image.source="https://github.com/norrietaylor/distillery" \
      org.opencontainers.image.description="Distillery MCP server — persistent shared memory for Claude Code" \
      org.opencontainers.image.licenses="Apache-2.0"

# Install only the runtime Python; no compilers, no `uv`, no build tools.
RUN apk add --no-cache python-3.14

# Create a non-root user with a writable home so DuckDB can install its
# VSS extension under ~/.duckdb at build time.
RUN adduser --disabled-password --uid 10001 --home /app appuser \
    && chown -R appuser:appuser /app

WORKDIR /app

# Copy the prebuilt virtualenv from the builder. Owned by appuser so it
# remains writable for runtime cache files (e.g. DuckDB extension dir).
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

USER appuser

# Pre-install the DuckDB VSS extension so HNSW indexing is available at
# runtime without a network download. Lands in /app/.duckdb/extensions/.
RUN python -c "import duckdb; duckdb.connect(':memory:').execute('INSTALL vss')"

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
