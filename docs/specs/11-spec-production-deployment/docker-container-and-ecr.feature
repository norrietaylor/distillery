# Source: docs/specs/11-spec-production-deployment/11-spec-production-deployment.md
# Pattern: CLI/Process
# Recommended test type: Integration

Feature: Docker Container and ECR

  Scenario: Docker image builds successfully
    Given a Dockerfile exists at the repository root
    And a .dockerignore file exists excluding secrets and test files
    When "docker build -t distillery-mcp ." is run at the repository root
    Then the command exits with code 0
    And the image "distillery-mcp" appears in the local Docker image list

  Scenario: Lambda handler initializes in container
    Given the distillery-mcp Docker image has been built
    When the container is started with placeholder environment variables for JINA_API_KEY, AWS_ACCESS_KEY_ID, and AWS_SECRET_ACCESS_KEY
    Then the Lambda handler module loads without import errors
    And the container logs show the handler initialization sequence

  Scenario: Lambda handler returns HTTP response for API Gateway event
    Given the lambda_handler module is imported
    When the handler is invoked with a mock API Gateway HTTP event for GET /health
    Then the handler returns a response with status code 200
    And the response body is valid JSON containing a "status" field

  Scenario: Container configuration uses environment variables for secrets
    Given the distillery-mcp Docker image has been built
    When the container's distillery.yaml is inspected
    Then no hardcoded API keys or OAuth credentials are present
    And secret values reference environment variables

  Scenario: Container is based on Lambda Python 3.12 runtime
    Given the Dockerfile at the repository root
    When the base image is inspected
    Then the base image is "public.ecr.aws/lambda/python:3.12"
