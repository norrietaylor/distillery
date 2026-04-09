# Source: docs/specs/14-spec-briefing/14-spec-briefing.md
# Pattern: CLI/Process + API (skill orchestrating MCP tools)
# Recommended test type: Integration

Feature: Solo briefing skill

  Scenario: Default invocation auto-detects project from cwd
    Given a knowledge base with 10 entries for the project "distillery"
    And the current working directory is inside the "distillery" git repository
    When the user invokes "/briefing" with no arguments
    Then the output header reads "# Briefing: distillery (solo)"
    And a generation timestamp is displayed below the header

  Scenario: Explicit project flag overrides auto-detection
    Given a knowledge base with entries for projects "distillery" and "other-project"
    And the current working directory is inside the "distillery" git repository
    When the user invokes "/briefing --project other-project"
    Then the output header reads "# Briefing: other-project (solo)"

  Scenario: Recent entries section displays up to 10 entries sorted by recency
    Given a knowledge base with 15 entries for the project "distillery" created at different times
    When the user invokes "/briefing --project distillery"
    Then the "Recent" section lists 10 entries
    And each entry shows a type badge, a content preview of at most 100 characters, and a relative timestamp
    And entries are ordered from most recent to oldest

  Scenario: Corrections section shows correction chains
    Given a knowledge base where entry "Earth is a geoid" has a "corrects" relation to "Earth is an oblate spheroid"
    When the user invokes "/briefing --project distillery"
    Then the "Corrections" section lists at least one correction chain
    And the chain shows the correcting entry, the corrected entry, and a relative timestamp

  Scenario: Expiring soon section surfaces entries expiring within 7 days
    Given a knowledge base with an entry whose "expires_at" is 3 days from now
    And a knowledge base with an entry whose "expires_at" is 30 days from now
    When the user invokes "/briefing --project distillery"
    Then the "Expiring Soon" section lists the entry expiring in 3 days
    And the entry expiring in 30 days does not appear in the "Expiring Soon" section

  Scenario: Stale knowledge section shows entries not accessed for 30 days
    Given a knowledge base with an entry last accessed 45 days ago
    And a knowledge base with an entry last accessed 5 days ago
    When the user invokes "/briefing --project distillery"
    Then the "Stale" section includes the entry last accessed 45 days ago
    And the "Stale" section does not include the entry last accessed 5 days ago

  Scenario: Unresolved section shows entries with verification status testing
    Given a knowledge base with an entry whose verification status is "testing"
    When the user invokes "/briefing --project distillery"
    Then the "Unresolved" section lists that entry with its verification status

  Scenario: Empty sections are omitted from output
    Given a knowledge base with no entries that have "expires_at" within 7 days
    And a knowledge base with no entries that have "corrects" relations
    When the user invokes "/briefing --project distillery"
    Then the output does not contain an "Expiring Soon" section
    And the output does not contain a "Corrections" section

  Scenario: MCP health check runs before producing output
    Given the MCP server is not reachable
    When the user invokes "/briefing --project distillery"
    Then the skill reports that the MCP server is unavailable
    And no briefing sections are rendered
