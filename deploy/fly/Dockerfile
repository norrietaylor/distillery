FROM python:3.13-slim

WORKDIR /app

# Copy the full repo (build context is repo root)
COPY . .

# Install the package (production only, no dev deps)
RUN pip install --no-cache-dir .

# Flatten config path so DISTILLERY_CONFIG=/app/distillery-fly.yaml works
COPY deploy/fly/distillery-fly.yaml /app/distillery-fly.yaml

EXPOSE 8000

CMD ["distillery-mcp", "--transport", "http"]
