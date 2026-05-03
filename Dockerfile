# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the Distillery MCP server.
#
# Stage 1 (builder): cgr.dev/chainguard/python:latest-dev — has shell, apk,
# and a writable filesystem. Used to install the `uv` static binary, resolve
# dependencies from `uv.lock`, and pre-install the DuckDB VSS extension.
#
# Stage 2 (runtime): cgr.dev/chainguard/python:latest — Chainguard distroless
# Python. No shell, no apk, no busybox, no pip cache; runs as the built-in
# `nonroot` user (uid 65532). Only the prebuilt virtualenv and DuckDB
# extension cache are copied in. Estimated final size: ~200 MB (vs 383 MB
# on the previous Wolfi-base image, ~40% reduction). See issue #419 for the
# size/CVE-surface analysis that motivated this migration.

ARG PYTHON_TAG=latest
ARG UV_VERSION=0.11.3

# Pinned `uv` binary. Pulled in via a separate stage so we can parameterise
# the version via the UV_VERSION build arg in the `COPY --from=` below.
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ─────────────────────────────────────────────────────────────────────
# Stage 1: builder — resolve and install dependencies with uv,
# pre-install the DuckDB VSS extension into ~/.duckdb.
# ─────────────────────────────────────────────────────────────────────
FROM cgr.dev/chainguard/python:${PYTHON_TAG}-dev AS builder

# The `-dev` variant runs as `nonroot` by default. Switch to root so we can
# copy the `uv` binary into /usr/local/bin and write to /app.
USER root
COPY --from=uv /uv /usr/local/bin/uv

# Speed/size knobs for uv:
#   - copy link mode avoids hardlink fallbacks across mounted layers
#   - bytecode compile up front so the runtime image has no first-call cost
#   - never download a different Python: use the one provided by the base
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
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

# 3. Pre-install the DuckDB VSS extension into a directory the runtime user
#    will own. The runtime stage has no shell to execute RUN commands, so
#    this must happen here. The Chainguard distroless image's `nonroot` user
#    has uid/gid 65532 and home directory /home/nonroot.
RUN mkdir -p /home/nonroot/.duckdb \
    && HOME=/home/nonroot /app/.venv/bin/python -c \
       "import duckdb; duckdb.connect(':memory:').execute('INSTALL vss')" \
    && chown -R 65532:65532 /home/nonroot/.duckdb /app/.venv

# ─────────────────────────────────────────────────────────────────────
# Stage 2: runtime — Chainguard distroless Python, venv copied from builder
# ─────────────────────────────────────────────────────────────────────
FROM cgr.dev/chainguard/python:${PYTHON_TAG} AS runtime

ARG BUILD_SHA=unknown
ENV DISTILLERY_BUILD_SHA=${BUILD_SHA} \
    PATH="/app/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/bin:/usr/sbin:/sbin:/bin" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/app/.venv

# OCI labels (preserve provenance and discoverability).
LABEL org.opencontainers.image.source="https://github.com/norrietaylor/distillery" \
      org.opencontainers.image.description="Distillery MCP server — persistent shared memory for Claude Code" \
      org.opencontainers.image.licenses="Apache-2.0"

WORKDIR /app

# Copy the prebuilt virtualenv and DuckDB extension cache from the builder.
# Both are owned by uid 65532 (`nonroot`), the default user in the
# Chainguard distroless image.
COPY --from=builder --chown=65532:65532 /app/.venv /app/.venv
COPY --from=builder --chown=65532:65532 /home/nonroot/.duckdb /home/nonroot/.duckdb

# The Chainguard distroless image already declares `USER 65532` (nonroot)
# in its metadata; restating it here keeps intent explicit.
USER 65532

EXPOSE 8000

# The base image's default ENTRYPOINT is /usr/bin/python; override it so
# the container runs the `distillery-mcp` console script directly. Default
# transport is HTTP on port 8000.
#
# Configure via environment variables:
#   DISTILLERY_CONFIG    — path to distillery.yaml (default: ./distillery.yaml)
#   DISTILLERY_HOST      — bind address (default: 0.0.0.0)
#   DISTILLERY_PORT      — bind port (default: 8000)
#   GITHUB_CLIENT_ID     — GitHub OAuth client ID (optional, enables auth)
#   GITHUB_CLIENT_SECRET — GitHub OAuth client secret (optional)
#   DISTILLERY_BASE_URL  — public URL for OAuth callbacks (required if auth enabled)
#   JINA_API_KEY         — Jina embedding API key
#
# Debug note: there is no shell in this image. To inspect a running
# container, exec into the Python REPL:
#   docker run --rm -it --entrypoint /app/.venv/bin/python <image>
# Or rebuild against the `-dev` tag for a debug variant with a shell.
ENTRYPOINT ["/app/.venv/bin/distillery-mcp"]
CMD ["--transport", "http"]
