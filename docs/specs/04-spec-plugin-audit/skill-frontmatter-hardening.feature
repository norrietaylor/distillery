# Source: docs/specs/04-spec-plugin-audit/04-spec-plugin-audit.md
# Pattern: State + CLI/Process (configuration takes effect at runtime)
# Recommended test type: Integration

Feature: Skill Frontmatter Hardening

  Scenario: Skill restricted to allowed tools rejects unauthorized tool access
    Given the /recall skill is loaded with allowed-tools limited to distillery_search, distillery_get, and distillery_status
    When the skill attempts to invoke a tool outside its allowed-tools list
    Then the tool invocation is rejected by the runtime
    And only distillery_search, distillery_get, and distillery_status remain available during the skill session

  Scenario: Each skill declares a minimum-privilege allowed-tools set
    Given all 10 skill SKILL.md files are loaded by the plugin runtime
    When the plugin enumerates available tools for each skill
    Then each skill exposes only the tools matching its declared allowed-tools set
    And no skill has access to tools outside its declared set

  Scenario: Side-effect skill cannot be auto-invoked by the model
    Given the /distill skill has disable-model-invocation set to true
    When Claude encounters conversation context that would normally trigger /distill
    Then the skill is not auto-invoked
    And the user must explicitly type /distill to activate the skill

  Scenario: Bookmark skill cannot be auto-invoked by the model
    Given the /bookmark skill has disable-model-invocation set to true
    When Claude encounters a URL in conversation that would normally trigger /bookmark
    Then the skill is not auto-invoked
    And the user must explicitly type /bookmark to activate the skill

  Scenario: Minutes skill cannot be auto-invoked by the model
    Given the /minutes skill has disable-model-invocation set to true
    When Claude encounters meeting discussion that would normally trigger /minutes
    Then the skill is not auto-invoked
    And the user must explicitly type /minutes to activate the skill

  Scenario: Watch skill cannot be auto-invoked by the model
    Given the /watch skill has disable-model-invocation set to true
    When Claude encounters feed source references that would normally trigger /watch
    Then the skill is not auto-invoked
    And the user must explicitly type /watch to activate the skill

  Scenario: Long-running skill executes in a forked context
    Given the /pour skill is configured with context set to fork
    When a user invokes /pour with a synthesis query
    Then the skill runs in an isolated subagent process
    And the main conversation remains responsive during execution

  Scenario: Radar skill executes in a forked context
    Given the /radar skill is configured with context set to fork
    When a user invokes /radar to generate a digest
    Then the skill runs in an isolated subagent process
    And the main conversation remains responsive during execution

  Scenario: Lightweight skill reports low effort hint
    Given the /recall skill is configured with effort set to low
    When the plugin runtime loads the skill
    Then the runtime schedules the skill with low resource allocation
    And the skill completes without requesting additional compute budget

  Scenario: Heavy skill reports high effort hint
    Given the /pour skill is configured with effort set to high
    When the plugin runtime loads the skill
    Then the runtime allocates elevated resources for the skill execution
    And the skill is permitted extended execution time
