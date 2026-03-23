# Source: docs/specs/04-spec-public-release/04-spec-public-release.md
# Pattern: State
# Recommended test type: Integration

Feature: CONTRIBUTING.md & CHANGELOG.md

  Scenario: CONTRIBUTING.md contains all required sections
    Given the repository includes a CONTRIBUTING.md at the root
    When a user reads the CONTRIBUTING.md file
    Then the file contains a "Prerequisites" section
    And the file contains a "Setup" section with install instructions for editable dev mode
    And the file contains a "Code Style" section referencing ruff and mypy
    And the file contains a "Testing" section referencing pytest and pytest-asyncio
    And the file contains a "Commit Conventions" section with Conventional Commits examples
    And the file contains a "Pull Request Process" section
    And the file contains an "Architecture Overview" section describing the 4-layer model
    And the file contains a license note referencing Apache 2.0

  Scenario: CHANGELOG.md follows Keep a Changelog format with v0.1.0 entry
    Given the repository includes a CHANGELOG.md at the root
    When a user reads the CHANGELOG.md file
    Then the file contains a header referencing Semantic Versioning
    And the file contains a version entry "[v0.1.0] - 2026-03-22"

  Scenario: CHANGELOG v0.1.0 documents all three MVP specs
    Given the repository includes a CHANGELOG.md at the root
    When a user reads the v0.1.0 section of CHANGELOG.md
    Then the section documents Spec 01 covering storage layer and data model
    And the section documents Spec 02 covering core skills
    And the section documents Spec 03 covering classification pipeline
