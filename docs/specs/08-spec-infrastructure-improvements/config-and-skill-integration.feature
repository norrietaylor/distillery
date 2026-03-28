# Source: docs/specs/08-spec-infrastructure-improvements/08-spec-infrastructure-improvements.md
# Pattern: State + Error Handling
# Recommended test type: Integration

Feature: Config and Skill Integration

  Scenario: Tags config section is parsed from distillery.yaml
    Given a distillery.yaml file with a tags section containing enforce_namespaces true and reserved_prefixes ["system"]
    When the configuration is loaded
    Then the TagsConfig enforce_namespaces value is true
    And the TagsConfig reserved_prefixes list contains "system"

  Scenario: Default tags config values are applied when section is absent
    Given a distillery.yaml file with no tags section
    When the configuration is loaded
    Then the TagsConfig enforce_namespaces value is false
    And the TagsConfig reserved_prefixes list is empty

  Scenario: Invalid reserved prefix is rejected during config validation
    Given a distillery.yaml file with reserved_prefixes ["INVALID-PREFIX!"]
    When the configuration is loaded
    Then a validation error is raised
    And the error message indicates the reserved prefix is not a valid tag segment

  Scenario: Enforce namespaces rejects flat tags on new entries
    Given the configuration has enforce_namespaces set to true
    And an in-memory DuckDB store is initialized with that configuration
    When a user attempts to store a new entry with tags ["flat-tag"]
    Then a ValueError is raised
    And the error message indicates flat tags are not allowed when namespace enforcement is enabled

  Scenario: Enforce namespaces accepts hierarchical tags on new entries
    Given the configuration has enforce_namespaces set to true
    And an in-memory DuckDB store is initialized with that configuration
    When a user stores a new entry with tags ["domain/architecture"]
    Then the entry is stored successfully and returns a valid UUID

  Scenario: Existing entries with flat tags remain readable under namespace enforcement
    Given the configuration has enforce_namespaces set to false
    And an entry exists with flat tags ["meeting-notes"]
    When the configuration is changed to enforce_namespaces true
    And the user reads the existing entry
    Then the entry is returned with its original flat tags intact
    And no validation error is raised

  Scenario: Reserved prefix blocks unauthorized tag usage
    Given the configuration has reserved_prefixes ["system"]
    And an in-memory DuckDB store is initialized with that configuration
    When a user attempts to store an entry with tags ["system/internal"] and source "user-input"
    Then the entry is rejected
    And the error message indicates the "system" prefix is reserved

  Scenario: Reserved prefix allows authorized source to use the tag
    Given the configuration has reserved_prefixes ["system"] with allowed source "distillery-core"
    And an in-memory DuckDB store is initialized with that configuration
    When a user stores an entry with tags ["system/internal"] and source "distillery-core"
    Then the entry is stored successfully and returns a valid UUID

  Scenario: Distill skill suggests hierarchical tags based on project context
    Given a git repository named "billing-v2"
    When the /distill skill generates tag suggestions
    Then the suggested tags include a hierarchical tag matching "project/billing-v2/sessions"

  Scenario: Bookmark skill suggests hierarchical tags with domain
    Given a bookmark URL from "docs.python.org"
    When the /bookmark skill generates tag suggestions
    Then the suggested tags include a hierarchical tag matching "source/bookmark/docs-python-org"

  Scenario: Example config file documents tags section
    Given the distillery.yaml.example file exists
    When the file is read
    Then it contains a "tags" section
    And the section includes enforce_namespaces with a comment explaining its purpose
    And the section includes reserved_prefixes with a comment explaining its purpose
