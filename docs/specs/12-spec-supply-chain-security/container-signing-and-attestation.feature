# Source: docs/specs/12-spec-supply-chain-security/12-spec-supply-chain-security.md
# Pattern: CLI/Process
# Recommended test type: Integration

Feature: Container Signing and Attestation (Main/Tag Push)

  Scenario: Image is pushed to GHCR on main branch push
    Given a commit is pushed to the main branch
    And the supply-chain workflow build step completes successfully
    When the push step executes
    Then the Docker image is pushed to ghcr.io/norrietaylor/distillery
    And the image is tagged as latest
    And the image is tagged as sha-{7char} derived from the git commit SHA

  Scenario: Image is tagged with version on tag push
    Given a tag v1.2.3 is pushed to the repository
    And the supply-chain workflow build step completes successfully
    When the push step executes
    Then the Docker image is pushed to ghcr.io/norrietaylor/distillery
    And the image is tagged as v1.2.3
    And the image is tagged as sha-{7char} derived from the git commit SHA

  Scenario: Pushed image is signed with Cosign keyless signing
    Given the Docker image has been pushed to ghcr.io/norrietaylor/distillery
    And the image digest sha256 value is available from the build output
    When the Cosign sign step executes against the image digest
    Then running cosign verify with certificate-oidc-issuer https://token.actions.githubusercontent.com succeeds
    And the signature is recorded in the Rekor transparency log

  Scenario: SBOM attestation is attached to the signed image
    Given the Docker image has been pushed and signed
    And the SBOM file sbom-fly.cdx.json has been generated
    When the cosign attest step executes with type cyclonedx and the SBOM as predicate
    Then running cosign verify-attestation with type cyclonedx against the image succeeds
    And the attestation predicate contains the CycloneDX SBOM content

  Scenario: Vulnerability scan attestation is attached to the signed image
    Given the Docker image has been pushed and signed
    And the Grype report grype-report-fly.json has been generated
    When the cosign attest step executes with type vuln and the Grype report as predicate
    Then running cosign verify-attestation with type vuln against the image succeeds
    And the attestation predicate contains the vulnerability scan results

  Scenario: SLSA provenance attestation is generated
    Given the Docker image has been pushed to GHCR
    And the image digest is available
    When the attest-build-provenance action executes against the image digest
    Then a SLSA provenance attestation is attached to the OCI manifest
    And the provenance references the GitHub Actions workflow as the build system

  Scenario: Signing targets the immutable digest not a mutable tag
    Given the Docker image has been pushed to GHCR
    When the signing and attestation steps execute
    Then all cosign sign and cosign attest commands reference the image by sha256 digest
    And no signing command references the image by a mutable tag such as latest
