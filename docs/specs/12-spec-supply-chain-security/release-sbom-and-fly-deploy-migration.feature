# Source: docs/specs/12-spec-supply-chain-security/12-spec-supply-chain-security.md
# Pattern: CLI/Process + State
# Recommended test type: Integration

Feature: Release SBOM Attachment and Fly Deploy Migration

  Scenario: SBOM is attached to GitHub Release on tag push
    Given a tag v1.2.3 has been pushed
    And the supply-chain workflow has generated sbom-fly.cdx.json
    When the release asset upload step executes
    Then running gh release view v1.2.3 shows sbom-fly.cdx.json in the assets list
    And the SBOM file is downloadable from the release page

  Scenario: Vulnerability report is attached to GitHub Release on tag push
    Given a tag v1.2.3 has been pushed
    And the supply-chain workflow has generated grype-report-fly.json
    When the release asset upload step executes
    Then running gh release view v1.2.3 shows grype-report-fly.json in the assets list
    And the vulnerability report is downloadable from the release page

  Scenario: Fly deploy uses pre-built GHCR image instead of remote build
    Given the supply-chain workflow has completed successfully on main
    And the Docker image has been pushed to ghcr.io/norrietaylor/distillery
    When the fly-deploy workflow triggers
    Then the flyctl deploy command includes --image ghcr.io/norrietaylor/distillery with the appropriate tag
    And the flyctl deploy command does not include --remote-only
    And the deployed application serves the same image that was scanned and signed

  Scenario: Fly deploy workflow triggers after supply-chain workflow completes
    Given the supply-chain workflow has completed successfully on main
    When GitHub Actions evaluates the fly-deploy workflow triggers
    Then the fly-deploy workflow is triggered via workflow_run or workflow_call
    And the fly-deploy workflow does not run if the supply-chain workflow failed

  Scenario: BUILD_SHA is baked into the image during supply-chain build
    Given the supply-chain workflow is building the Docker image
    And the current git commit SHA is abc123def
    When the Docker build step executes with BUILD_SHA build arg
    Then the resulting container image has DISTILLERY_BUILD_SHA set to abc123def
    And the distillery status command inside the container reports build SHA abc123def

  Scenario: Release assets are not uploaded for non-tag pushes
    Given a commit is pushed to the main branch without a tag
    When the supply-chain workflow completes
    Then no release asset upload step is executed
    And the SBOM and Grype report are available only as CI workflow artifacts
