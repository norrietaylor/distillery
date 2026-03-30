FROM cgr.dev/chainguard/wolfi-base:latest

WORKDIR /app

ARG BUILD_SHA=unknown
ENV DISTILLERY_BUILD_SHA=${BUILD_SHA}

# Install Python 3.13 and pip
RUN apk add --no-cache python-3.13 py3.13-pip

# Create non-root user
RUN adduser --disabled-password --uid 10001 appuser

# Copy the full repo (build context is repo root)
COPY . .

# Install the package (production only, no dev deps)
RUN pip install --no-cache-dir .

# Pre-install the DuckDB VSS extension so HNSW indexing is available at runtime
# without a network download. Run as appuser so it lands in ~/.duckdb/extensions/.
RUN su -s /bin/sh appuser -c "python -c \"import duckdb; duckdb.connect(':memory:').execute('INSTALL vss')\""

# Flatten config path so DISTILLERY_CONFIG=/app/distillery-fly.yaml works
COPY deploy/fly/distillery-fly.yaml /app/distillery-fly.yaml

RUN chown -R appuser:appuser /app

EXPOSE 8000

# Fix volume ownership at runtime (Fly mounts as root), then drop to appuser.
# One-time DB reset: remove corrupt WAL and stale DB to start fresh.
CMD ["sh", "-c", "chown -R appuser:appuser /data && if [ ! -f /data/.db-reset-v1 ]; then rm -f /data/distillery.db /data/distillery.db.wal && touch /data/.db-reset-v1; fi && exec su -s /bin/sh appuser -c 'distillery-mcp --transport http'"]
