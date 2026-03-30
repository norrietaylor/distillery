FROM python:3.13-slim

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

# Copy the full repo (build context is repo root)
COPY . .

# Install the package (production only, no dev deps)
RUN pip install --no-cache-dir .

# Flatten config path so DISTILLERY_CONFIG=/app/distillery-fly.yaml works
COPY deploy/fly/distillery-fly.yaml /app/distillery-fly.yaml

# Create /data for the volume mount and set ownership
RUN mkdir -p /data && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

CMD ["distillery-mcp", "--transport", "http"]
