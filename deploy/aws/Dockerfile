# Distillery MCP — AWS Lambda container image
#
# Build:
#   docker build -f deploy/aws/Dockerfile -t distillery-mcp .
#
# Run locally (Lambda RIE):
#   docker run -p 9000:8080 \
#     -e JINA_API_KEY=... \
#     -e GITHUB_CLIENT_ID=... \
#     -e GITHUB_CLIENT_SECRET=... \
#     -e DISTILLERY_BASE_URL=https://example.com \
#     -e AWS_ACCESS_KEY_ID=... \
#     -e AWS_SECRET_ACCESS_KEY=... \
#     distillery-mcp
FROM public.ecr.aws/lambda/python:3.12

# Install build tools needed by some transitive deps (e.g. duckdb wheels).
# Using --no-cache keeps the layer lean.
RUN pip install --no-cache-dir --upgrade pip

# Copy project metadata first so dependency layer is cached independently
# from source changes.
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the package and all runtime dependencies.
# --no-deps is NOT used so that transitive requirements are resolved.
RUN pip install --no-cache-dir .

# Copy the container-specific configuration.
# This must come AFTER pip install so the file is picked up at runtime rather
# than baked into the wheel.
COPY deploy/aws/distillery.lambda.yaml /var/task/distillery.yaml

# The Lambda handler entrypoint: <module>.<function>
CMD ["distillery.mcp.lambda_handler.handler"]
