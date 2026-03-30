# Source: docs/specs/11-spec-fly-deployment/11-spec-fly-deployment.md
# Pattern: CLI/Process + State
# Recommended test type: Integration

Feature: Create Fly.io deployment configuration

  Scenario: Dockerfile builds successfully from repo root
    Given the file deploy/fly/Dockerfile exists
    When the user runs "docker build -f deploy/fly/Dockerfile ." from the repo root
    Then the build completes with exit code 0
    And the resulting image contains the distillery-mcp entrypoint

  Scenario: Dockerfile uses correct base image and entrypoint
    Given the file deploy/fly/Dockerfile exists
    When the user inspects the built Docker image
    Then the base image is python:3.13-slim
    And the entrypoint runs "distillery-mcp --transport http"
    And port 8000 is exposed

  Scenario: Fly.toml configures scale-to-zero with volume mount
    Given the file deploy/fly/fly.toml exists
    When the user reads the fly.toml configuration
    Then the service internal port is 8000 with force_https enabled
    And auto_stop_machines is set to "stop"
    And auto_start_machines is set to true
    And min_machines_running is set to 0
    And a volume mount maps "distillery_data" to "/data"

  Scenario: Fly.toml does not hardcode a region
    Given the file deploy/fly/fly.toml exists
    When the user reads the fly.toml configuration
    Then no primary_region or region field is present

  Scenario: Fly.toml sets DISTILLERY_CONFIG environment variable
    Given the file deploy/fly/fly.toml exists
    When the user reads the [env] section
    Then DISTILLERY_CONFIG is set to "/app/distillery-fly.yaml"

  Scenario: Distillery Fly config loads successfully via load_config
    Given the file deploy/fly/distillery-fly.yaml exists
    And the DISTILLERY_CONFIG env var is set to "deploy/fly/distillery-fly.yaml"
    When the user runs "python -c 'from distillery.config import load_config; load_config()'"
    Then the command exits with code 0
    And the loaded config specifies duckdb backend with database_path "/data/distillery.db"
    And the loaded config specifies jina embedding provider

  Scenario: Fly config references secrets by env var name only
    Given the file deploy/fly/distillery-fly.yaml exists
    When the user reads the YAML content
    Then the file references JINA_API_KEY as an environment variable name
    And the file references GITHUB_CLIENT_ID as an environment variable name
    And the file references GITHUB_CLIENT_SECRET as an environment variable name
    And no actual secret values are present in the file

  Scenario: Fly README contains complete quickstart commands
    Given the file deploy/fly/README.md exists
    When the user reads the quickstart section
    Then the document contains the command "fly apps create"
    And the document contains the command "fly volumes create distillery_data --size 1"
    And the document contains the command "fly secrets set"
    And the document contains the command "fly deploy -c deploy/fly/fly.toml"

  Scenario: Dockerfile copies Fly config into the image
    Given the file deploy/fly/Dockerfile exists
    When the user reads the Dockerfile
    Then a COPY instruction places distillery-fly.yaml at /app/distillery-fly.yaml
