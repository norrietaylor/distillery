# Source: docs/specs/11-spec-fly-deployment/11-spec-fly-deployment.md
# Pattern: CLI/Process
# Recommended test type: Integration

Feature: Update documentation and cross-references

  Scenario: CLAUDE.md includes deployment directory documentation
    Given the CLAUDE.md file exists at the repo root
    When the user reads the Architecture section
    Then a Deployment subsection describes the deploy/ directory structure
    And the subsection notes that local dev uses distillery-dev.yaml at root

  Scenario: Deployment docs reference both provider directories
    Given the file docs/deployment.md exists
    When the user reads the deployment guide
    Then the document references deploy/prefect/ for Horizon deployments
    And the document references deploy/fly/ for Fly.io deployments

  Scenario: Example config notes production configs live under deploy/
    Given the file distillery.yaml.example exists at the repo root
    When the user reads the header comment
    Then the comment indicates production configs live under deploy/

  Scenario: No stale references to root-level prefect.yaml
    Given the deployment files have been fully reorganized
    When the user runs "rg -n --glob '*.md' --glob '*.py' '\bprefect\.yaml\b' . | rg -v 'deploy/prefect/|docs/specs/'" from the repo root
    Then the command returns zero matches
    And no references point to a root-level prefect.yaml path

  Scenario: No stale references to root-level distillery.yaml in docs
    Given the deployment files have been fully reorganized
    When the user runs "grep -rn 'distillery\.yaml' --include='*.md' ." from the repo root
    Then matches outside deploy/ are limited to dev config and example template references
    And no match points to a root-level production distillery.yaml

  Scenario: Linting passes after documentation updates
    Given all documentation and cross-references have been updated
    When the user runs "ruff check src/ tests/"
    Then the command exits with code 0

  Scenario: Type checking passes after documentation updates
    Given all documentation and cross-references have been updated
    When the user runs "mypy --strict src/distillery/"
    Then the command exits with code 0

  Scenario: Full test suite passes after all changes
    Given all three demoable units are complete
    When the user runs "pytest"
    Then the command exits with code 0
    And no test failures are reported
