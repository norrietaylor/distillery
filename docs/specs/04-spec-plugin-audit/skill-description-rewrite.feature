# Source: docs/specs/04-spec-plugin-audit/04-spec-plugin-audit.md
# Pattern: State (configuration affects runtime model behavior)
# Recommended test type: Integration

Feature: Skill Description Rewrite

  Scenario: Skill description communicates purpose without trigger phrases
    Given the /distill skill is loaded by the plugin runtime
    When Claude reads the skill description to determine available capabilities
    Then the description conveys "Capture decisions, insights, and action items from the current session into the knowledge base"
    And the description does not contain "Triggered by:" or a list of trigger phrases

  Scenario: Concise descriptions reduce context token consumption
    Given all 10 skill SKILL.md files are loaded by the plugin runtime
    When the runtime serializes skill descriptions into the model context
    Then each description is 120 characters or fewer
    And the total token cost of skill descriptions is lower than the previous trigger-phrase format

  Scenario: Trigger phrases remain discoverable in skill body
    Given the /recall skill SKILL.md has been updated with a concise description
    When a developer reads the full SKILL.md file body
    Then the original trigger phrases are documented in a comment or documentation section
    And the trigger phrases are not present in the YAML frontmatter description field

  Scenario: Model correctly matches user intent to rewritten skill description
    Given the /bookmark skill description reads "Save a URL with an auto-generated summary to the knowledge base"
    When a user says "save this link for later"
    Then Claude matches the request to the /bookmark skill
    And the skill is offered or invoked based on the description match
