FROM cgr.dev/chainguard/wolfi-base:latest

WORKDIR /app

ARG BUILD_SHA=unknown
ENV DISTILLERY_BUILD_SHA=${BUILD_SHA}

# Install Python 3.14
RUN apk add --no-cache python-3.14

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /usr/local/bin/uv

# Create non-root user
RUN adduser --disabled-password --uid 10001 appuser

# Copy the full repo (build context is repo root)
COPY . .

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
