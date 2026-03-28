# Source: docs/specs/11-spec-production-deployment/11-spec-production-deployment.md
# Pattern: CLI/Process
# Recommended test type: Integration

Feature: GitHub Actions CD Pipeline

  Scenario: Deploy workflow triggers on push to main
    Given the deploy workflow file exists at .github/workflows/deploy.yml
    When the workflow trigger configuration is evaluated
    Then the workflow triggers on push events to the main branch

  Scenario: Deploy workflow runs tests before deployment
    Given the deploy workflow is triggered
    When the workflow job sequence is examined
    Then the test suite runs with coverage threshold of 80 percent before any deployment step
    And a test failure causes the workflow to abort without deploying

  Scenario: Deploy workflow builds and pushes Docker image to ECR
    Given the test suite has passed in the deploy workflow
    When the build and push steps execute
    Then the Docker image is built from the repository Dockerfile
    And the image is pushed to the configured ECR repository
    And AWS authentication uses OIDC federation without long-lived access keys

  Scenario: Deploy workflow updates Lambda function
    Given a new Docker image has been pushed to ECR
    When the deploy step executes
    Then the Lambda function is updated to use the new container image
    And the workflow waits for provisioned concurrency to stabilize

  Scenario: Deploy workflow runs smoke test against live endpoint
    Given the Lambda function has been updated with the new image
    When the smoke test step executes
    Then an HTTP request to /health returns status "ok"
    And an MCP initialize handshake is attempted against the live endpoint
    And tools/list is called and returns 21 tools

  Scenario: Deploy workflow reports failure on smoke test failure
    Given the smoke test step detects a failure
    When the workflow completes
    Then the workflow exits with a non-zero status
    And a failure summary is posted to the GitHub Actions run summary

  Scenario: Deploy workflow uses configurable infrastructure references
    Given the deploy workflow file exists
    When the workflow configuration is evaluated
    Then AWS account ID, region, ECR repository, and Lambda function name are sourced from GitHub Actions variables
    And no infrastructure identifiers are hardcoded in the workflow file
