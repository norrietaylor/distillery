# Source: docs/specs/05-spec-skill-ux/05-spec-skill-ux.md
# Pattern: CLI/Process + State
# Recommended test type: Integration

Feature: Token Budget Reduction and Progressive Disclosure

  Scenario: /setup SKILL.md body is reduced to 150 lines or fewer
    Given the /setup skill has been refactored for progressive disclosure
    When the SKILL.md body lines are counted (excluding frontmatter)
    Then the line count is 150 or fewer

  Scenario: /setup cron payload details are loaded on demand from references
    Given the /setup SKILL.md references cron-payloads.md
    When a user invokes /setup and the skill needs cron job payload definitions
    Then the skill reads references/cron-payloads.md for the detailed payload schemas
    And the cron job is configured using the payload definitions from the reference file

  Scenario: /setup transport detection logic is loaded on demand from references
    Given the /setup SKILL.md references transport-detection.md
    When a user invokes /setup and the skill needs to detect MCP transport
    Then the skill reads references/transport-detection.md for the detection logic
    And the correct transport type is identified and used for configuration

  Scenario: Complex skills use progressive disclosure with references directory
    Given the /setup skill has a references/ subdirectory
    When the main SKILL.md is loaded by Claude
    Then the SKILL.md contains dispatch logic and flag descriptions
    And detailed mode-specific instructions are deferred to references/ files
    And the SKILL.md includes "Read references/<file>.md for details" instructions

  Scenario: CONVENTIONS.md documents the references pattern for large skills
    Given the CONVENTIONS.md file has been updated
    When the user reads the progressive disclosure section
    Then the section specifies that skills exceeding 150 lines must use references/ subdirectories
    And the section describes the pattern of keeping dispatch logic in SKILL.md
    And the section describes deferring detailed instructions to reference files
