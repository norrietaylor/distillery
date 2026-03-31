# Source: docs/specs/12-spec-supply-chain-security/12-spec-supply-chain-security.md
# Pattern: CLI/Process
# Recommended test type: Integration

Feature: Supply Chain Scanning Workflow (PR Gate)

  Scenario: PR build generates SBOM artifact from Docker image
    Given a pull request is opened against the main branch
    And the repository contains deploy/fly/Dockerfile
    When the supply-chain workflow runs to completion
    Then the workflow produces a file named sbom-fly.cdx.json in CycloneDX JSON format
    And the SBOM artifact is uploaded to the workflow run with 30-day retention
    And the SBOM contains package entries from the built Docker image

  Scenario: Vulnerability scan fails the build on high-severity finding
    Given the supply-chain workflow is running on a PR build
    And the built Docker image contains a dependency with a high-severity CVE
    And no suppression for that CVE exists in .grype.yaml
    When the Grype scan step executes against the generated SBOM
    Then the scan step exits with a non-zero exit code
    And the overall workflow check reports failure on the pull request
    And the Grype scan report artifact is uploaded alongside the SBOM

  Scenario: Vulnerability scan passes when no high or critical findings exist
    Given the supply-chain workflow is running on a PR build
    And the built Docker image has no high or critical severity vulnerabilities
    When the Grype scan step executes against the generated SBOM
    Then the scan step exits with code 0
    And the overall workflow check reports success on the pull request

  Scenario: False-positive suppression allows build to pass
    Given the built Docker image contains a known false-positive CVE
    And the .grype.yaml file at the repository root includes that CVE in its ignore list
    When the Grype scan step executes against the generated SBOM
    Then the suppressed CVE does not cause a build failure
    And the workflow check reports success on the pull request

  Scenario: Workflow triggers on push to main branch
    Given a commit is pushed directly to the main branch
    When GitHub Actions evaluates the supply-chain workflow triggers
    Then the supply-chain workflow is triggered and runs
    And the build step loads the Docker image locally without pushing to a registry

  Scenario: Workflow triggers on version tag push
    Given a tag matching the pattern v* is pushed to the repository
    When GitHub Actions evaluates the supply-chain workflow triggers
    Then the supply-chain workflow is triggered and runs

  Scenario: Docker image build uses correct permissions and build args
    Given the supply-chain workflow is running
    When the Docker build step executes
    Then the build uses BUILD_SHA set to the current git commit SHA
    And the workflow has id-token write permission for OIDC signing
    And the workflow has packages write permission for GHCR access
