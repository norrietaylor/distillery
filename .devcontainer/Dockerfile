FROM mcr.microsoft.com/devcontainers/python:3.12

# Install Python 3.11 and 3.13 for multi-version testing
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev \
    python3.13 python3.13-venv python3.13-dev \
    && rm -rf /var/lib/apt/lists/*

# Pre-install project dependencies into the default Python (3.12)
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
RUN pip install --no-cache-dir -e ".[dev]"

# Create data directory for DuckDB
RUN mkdir -p /home/vscode/.distillery && chown vscode:vscode /home/vscode/.distillery
