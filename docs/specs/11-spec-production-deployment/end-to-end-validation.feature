# Source: docs/specs/11-spec-production-deployment/11-spec-production-deployment.md
# Pattern: CLI/Process + API
# Recommended test type: E2E

Feature: End-to-End Validation

  Scenario: Smoke test checks health endpoint
    Given the smoke test script exists at scripts/smoke-test.sh and is executable
    And a deployed MCP server is running at a known endpoint URL
    When "./scripts/smoke-test.sh <endpoint-url>" is run
    Then the script reports that /health returned status "ok"
    And the script exits with code 0

  Scenario: Smoke test detects unhealthy endpoint
    Given the smoke test script exists at scripts/smoke-test.sh
    And the target endpoint is not responding
    When "./scripts/smoke-test.sh <unreachable-url>" is run
    Then the script reports a health check failure
    And the script exits with a non-zero exit code

  Scenario: Smoke test performs MCP handshake on unauthenticated server
    Given the smoke test script is run against an endpoint without OAuth enabled
    When the script reaches the MCP handshake step
    Then an MCP initialize request is sent and receives a valid response
    And tools/list is called and returns 21 tools
    And distillery_status is called and returns a valid response

  Scenario: Smoke test handles OAuth-protected endpoint
    Given the smoke test script is run against an endpoint with GitHub OAuth enabled
    And no pre-configured auth token is provided
    When the script reaches the MCP handshake step
    Then the script detects a 401 response on the unauthenticated request
    And the script prints instructions for manual OAuth token exchange

  Scenario: Smoke test uses pre-configured token in CI mode
    Given the smoke test script is run against an OAuth-protected endpoint
    And a valid auth token is provided via environment variable
    When the script performs the MCP handshake with the token
    Then the initialize handshake succeeds
    And tools/list returns 21 tools
    And the script exits with code 0

  Scenario: Deployment documentation covers AWS setup
    Given the docs/deployment.md file exists
    When the deployment documentation is reviewed
    Then it contains a section on Terraform bootstrap and apply
    And it contains a section on the CD pipeline and monitoring
    And it contains a troubleshooting section for common Lambda and S3 issues
