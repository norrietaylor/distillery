# Source: docs/specs/05-spec-skill-ux/05-spec-skill-ux.md
# Pattern: CLI/Process + API + State
# Recommended test type: Integration

Feature: /radar Consent and /tune Runtime Configuration

  Scenario: /radar displays digest without storing by default
    Given the knowledge base contains feed entries with new content
    When the user runs /radar without any flags
    Then a digest summary is displayed to the user
    And no new entry is created in the knowledge base

  Scenario: /radar --store persists the digest after dedup check
    Given the knowledge base contains feed entries with new content
    And no similar digest exists in the knowledge base
    When the user runs /radar --store
    Then a digest summary is displayed to the user
    And the digest is stored as a new entry in the knowledge base
    And the stored entry has entry_type "digest"

  Scenario: /radar no longer accepts --no-store flag
    Given the user attempts to run /radar with --no-store
    When the skill parses the flags
    Then the --no-store flag is not recognized
    And the skill proceeds with the default display-only behavior

  Scenario: distillery_configure applies threshold change at runtime
    Given the MCP server is running with feeds.thresholds.alert set to 0.8
    When the distillery_configure tool is called with section "feeds.thresholds" key "alert" value 0.7
    Then the tool returns the previous value 0.8 and new value 0.7
    And the in-memory configuration reflects alert threshold 0.7
    And the distillery.yaml file on disk contains the updated alert value 0.7

  Scenario: distillery_configure validates threshold ranges
    Given the MCP server is running
    When the distillery_configure tool is called with section "feeds.thresholds" key "alert" value 1.5
    Then the tool returns a validation error indicating the value must be between 0.0 and 1.0
    And the configuration is not modified

  Scenario: distillery_configure enforces alert >= digest constraint
    Given the MCP server is running with feeds.thresholds.digest set to 0.5
    When the distillery_configure tool is called with section "feeds.thresholds" key "alert" value 0.3
    Then the tool returns a validation error indicating alert must be greater than or equal to digest
    And the configuration is not modified

  Scenario: distillery_configure rejects unknown configuration keys
    Given the MCP server is running
    When the distillery_configure tool is called with section "unknown_section" key "arbitrary_key" value "anything"
    Then the tool returns an error indicating the configuration key is not recognized
    And no changes are written to distillery.yaml

  Scenario: distillery_configure writes atomically to prevent corruption
    Given the MCP server is running with a valid distillery.yaml
    When the distillery_configure tool is called with a valid configuration change
    Then the change is written to a temporary file first
    And the temporary file is renamed to distillery.yaml
    And the original configuration is not corrupted if the write is interrupted

  Scenario: /tune applies threshold changes via MCP without manual YAML editing
    Given the MCP server is running with feeds.thresholds.alert set to 0.8
    When the user runs /tune to set alert threshold to 0.7
    Then the skill calls distillery_configure with the new threshold value
    And the skill displays the before value 0.8 and after value 0.7
    And the user does not need to manually edit any YAML file
