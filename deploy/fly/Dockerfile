FROM python:3.13-slim

WORKDIR /app

ARG BUILD_SHA=unknown
ENV DISTILLERY_BUILD_SHA=${BUILD_SHA}

RUN useradd --create-home --uid 10001 appuser

# Copy the full repo (build context is repo root)
COPY . .

# Install the package (production only, no dev deps)
RUN pip install --no-cache-dir .

# Flatten config path so DISTILLERY_CONFIG=/app/distillery-fly.yaml works
COPY deploy/fly/distillery-fly.yaml /app/distillery-fly.yaml

RUN chown -R appuser:appuser /app

EXPOSE 8000

# Fix volume ownership at runtime (Fly mounts as root), then drop to appuser
CMD ["sh", "-c", "chown -R appuser:appuser /data && exec su -s /bin/sh appuser -c 'distillery-mcp --transport http'"]
