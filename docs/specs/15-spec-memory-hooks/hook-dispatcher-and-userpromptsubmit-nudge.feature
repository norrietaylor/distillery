# Source: docs/specs/15-spec-memory-hooks/15-spec-memory-hooks.md
# Pattern: CLI/Process + State
# Recommended test type: Integration

Feature: Hook dispatcher and UserPromptSubmit nudge

  Scenario: Dispatcher routes UserPromptSubmit event to the nudge handler
    Given the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    And the environment variable DISTILLERY_NUDGE_INTERVAL is set to "1"
    When the user pipes '{"hook_event_name":"UserPromptSubmit","session_id":"test-abc"}' to the dispatcher via stdin
    Then stdout contains "[Distillery] You've exchanged 1 messages this session"
    And the command exits with code 0

  Scenario: Dispatcher routes unknown hook event silently
    Given the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    When the user pipes '{"hook_event_name":"UnknownEvent","session_id":"test-abc"}' to the dispatcher via stdin
    Then stdout is empty
    And the command exits with code 0

  Scenario: Nudge fires at the configured interval
    Given the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    And the environment variable DISTILLERY_NUDGE_INTERVAL is set to "3"
    And no counter file exists for session "test-interval"
    When the user sends 3 sequential UserPromptSubmit events for session "test-interval"
    Then the first 2 invocations produce no stdout output
    And the 3rd invocation outputs "[Distillery] You've exchanged 3 messages this session. Consider whether any decisions, insights, or corrections from this conversation should be stored with /distill."
    And the command exits with code 0 on every invocation

  Scenario: Nudge fires again at multiples of the interval
    Given the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    And the environment variable DISTILLERY_NUDGE_INTERVAL is set to "2"
    And no counter file exists for session "test-multi"
    When the user sends 4 sequential UserPromptSubmit events for session "test-multi"
    Then the 2nd invocation outputs a nudge mentioning "2 messages"
    And the 4th invocation outputs a nudge mentioning "4 messages"
    And the 1st and 3rd invocations produce no stdout output

  Scenario: Prompt counter persists across invocations in a temp file
    Given the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    And no counter file exists for session "test-persist"
    When the user sends a UserPromptSubmit event for session "test-persist"
    Then a counter file exists at /tmp/distillery-prompt-count-test-persist
    And the counter file contains the value "1"

  Scenario: Counter increments atomically on subsequent prompts
    Given the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    And a counter file for session "test-incr" already contains "4"
    When the user sends a UserPromptSubmit event for session "test-incr"
    Then the counter file for session "test-incr" contains the value "5"

  Scenario: Default nudge interval is 30 when env var is unset
    Given the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    And the environment variable DISTILLERY_NUDGE_INTERVAL is not set
    And no counter file exists for session "test-default"
    When the user sends 29 sequential UserPromptSubmit events for session "test-default"
    Then all 29 invocations produce no stdout output
    And the command exits with code 0 on every invocation

  Scenario: Dispatcher exits silently on malformed JSON input
    Given the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    When the user pipes "this is not json" to the dispatcher via stdin
    Then stdout is empty
    And the command exits with code 0

  Scenario: Dispatcher reads hook_event_name, session_id, and cwd from stdin JSON
    Given the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    And the environment variable DISTILLERY_NUDGE_INTERVAL is set to "1"
    When the user pipes '{"hook_event_name":"UserPromptSubmit","session_id":"sess-xyz","cwd":"/home/user/project"}' to the dispatcher via stdin
    Then stdout contains a nudge message referencing "sess-xyz"
    And the command exits with code 0
