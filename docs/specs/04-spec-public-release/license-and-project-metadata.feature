# Source: docs/specs/04-spec-public-release/04-spec-public-release.md
# Pattern: CLI/Process + State
# Recommended test type: Integration

Feature: License & Project Metadata

  Scenario: LICENSE file contains Apache 2.0 text with correct copyright
    Given the repository has been updated with the new license
    When a user reads the LICENSE file at the repository root
    Then the file contains the text "Apache License"
    And the file contains the text "Version 2.0"
    And the file contains the copyright line "Copyright 2026 Distillery Contributors"

  Scenario: pyproject.toml declares Apache-2.0 license
    Given the repository has been updated with the new license metadata
    When a user parses pyproject.toml for the license field
    Then the license value is "Apache-2.0"
    And the previous MIT license reference is no longer present

  Scenario: pyproject.toml includes all required PyPI classifiers
    Given the repository has been updated with PyPI metadata
    When a user parses the classifiers in pyproject.toml
    Then the classifiers include "Development Status :: 3 - Alpha"
    And the classifiers include "License :: OSI Approved :: Apache Software License"
    And the classifiers include "Programming Language :: Python :: 3.11"
    And the classifiers include "Programming Language :: Python :: 3.12"
    And the classifiers include "Programming Language :: Python :: 3.13"

  Scenario: pyproject.toml includes discovery keywords
    Given the repository has been updated with PyPI metadata
    When a user parses the keywords in pyproject.toml
    Then the keywords include "knowledge-base" and "embeddings" and "mcp" and "duckdb"

  Scenario: README references Apache 2.0 license
    Given the repository has been updated with the new license
    When a user reads the README.md file
    Then the file references "Apache 2.0"
    And the file does not reference "MIT" as the project license
